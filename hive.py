#!/usr/bin/env python3
"""Three independent cookies sharing evidence-backed memory. Python stdlib only."""
import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ollama_local import ask, audit_session


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path):
    with connect(path) as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT UNIQUE NOT NULL,
            run_id TEXT NOT NULL,
            cookie TEXT NOT NULL,
            kind TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            payload TEXT NOT NULL
        );
        CREATE TRIGGER IF NOT EXISTS no_update BEFORE UPDATE ON events
        BEGIN SELECT RAISE(ABORT, 'memory events are append-only'); END;
        CREATE TRIGGER IF NOT EXISTS no_delete BEFORE DELETE ON events
        BEGIN SELECT RAISE(ABORT, 'memory events are append-only'); END;
        """)


def append(db_path, run_id, cookie, kind, payload):
    event_id = str(uuid.uuid4())
    with connect(db_path) as db:
        db.execute("INSERT INTO events(id,run_id,cookie,kind,recorded_at,payload) VALUES(?,?,?,?,?,?)",
                   (event_id, run_id, cookie, kind, datetime.now(timezone.utc).isoformat(), canonical(payload)))
    return event_id


def retrieve(db_path, run_id, kind):
    with connect(db_path) as db:
        rows = db.execute("SELECT * FROM events WHERE run_id=? AND kind=? ORDER BY sequence",
                          (run_id, kind)).fetchall()
    if len(rows) != 1:
        raise ValueError(f"Expected one {kind} event for this run, got {len(rows)}")
    row = dict(rows[0])
    row["payload"] = json.loads(row["payload"])
    return row


def source_file(path):
    source = json.loads(Path(path).read_text())
    capacity = source["reservoir_capacity_litres"]
    if type(capacity) is not int or capacity <= 0:
        raise ValueError("Source capacity must be a positive integer")
    return source


def model_step(db_path, run_id, role, model, instruction, context, fields):
    with audit_session(db_path, run_id, f"cookie-{role}"):
        answer, record = ask(model, instruction, context, fields)
    record["context_sha256"] = digest(context)
    append(db_path, run_id, f"cookie-{role}", "model_call", record)
    return answer


def learn(db_path, run_id, source_path, model=None):
    source = source_file(source_path)
    data_id = append(db_path, run_id, "cookie-learner", "data", {
        "source_uri": Path(source_path).resolve().as_uri(),
        "source_sha256": digest(source), "snapshot": source,
        "provenance": "Synthetic fixture supplied for this experiment; not a real observation",
    })
    value = source["reservoir_capacity_litres"]
    if model:
        value = model_step(db_path, run_id, "learner", model,
                           "Extract the reservoir capacity in litres from this source.", source,
                           {"capacity_litres": {"type": "integer"}})["capacity_litres"]
    append(db_path, run_id, "cookie-learner", "claim", {
        "key": "reservoir_capacity_litres", "value": value,
        "evidence_id": data_id, "status": "unverified",
        "scope": "This source snapshot only",
    })


def solve(db_path, run_id, count, inject_error=False, model=None):
    claim = retrieve(db_path, run_id, "claim")
    answer = claim["payload"]["value"] * count
    if model:
        answer = model_step(db_path, run_id, "solver", model,
                            "Calculate the combined capacity of the requested number of identical reservoirs using the retrieved claim.",
                            {"retrieved_claim": claim["payload"], "reservoir_count": count},
                            {"answer_litres": {"type": "integer"}})["answer_litres"]
    answer += 1 if inject_error else 0
    append(db_path, run_id, "cookie-solver", "result", {
        "question": f"What is the combined capacity of {count} identical reservoirs?",
        "reservoir_count": count, "answer_litres": answer, "claim_id": claim["id"],
        "method": "Model used retrieved claim" if model else "Retrieved capacity multiplied by reservoir count",
        "injected_error": inject_error, "status": "proposed",
    })


def verify(db_path, run_id, source_path, model=None):
    data = retrieve(db_path, run_id, "data")
    claim = retrieve(db_path, run_id, "claim")
    result = retrieve(db_path, run_id, "result")
    original = source_file(source_path)
    evidence, fact, answer = data["payload"], claim["payload"], result["payload"]
    expected_total = original["reservoir_capacity_litres"] * answer["reservoir_count"]
    checks = {
        "evidence_link": fact["evidence_id"] == data["id"],
        "claim_link": answer["claim_id"] == claim["id"],
        "snapshot_integrity": digest(evidence["snapshot"]) == evidence["source_sha256"],
        "source_unchanged": digest(original) == evidence["source_sha256"],
        "claim_matches_source": fact["value"] == original["reservoir_capacity_litres"],
        "positive_integer_count": type(answer["reservoir_count"]) is int and answer["reservoir_count"] > 0,
        "answer_matches_source": type(answer["answer_litres"]) is int and answer["answer_litres"] == expected_total,
    }
    model_review = None
    if model:
        review = model_step(db_path, run_id, "verifier", model,
                            "Independently calculate the combined capacity in litres of the given number of identical reservoirs from the original source. Return expected_total_litres as an integer.",
                            {"original_source": original, "reservoir_count": answer["reservoir_count"]},
                            {"expected_total_litres": {"type": "integer"}})
        model_review = {
            "expected_total_litres": review["expected_total_litres"],
            "matches_source_calculation": review["expected_total_litres"] == expected_total,
            "matches_proposed_answer": review["expected_total_litres"] == answer["answer_litres"],
            "proposed_answer_visible_to_model": False,
        }
    # An objectively failed check remains disputed even if the model agrees.
    # A model disagreement with an otherwise valid result is a review case.
    status = "disputed" if not all(checks.values()) else (
        "needs_review" if model_review and not model_review["matches_source_calculation"] else "verified")
    passed = status == "verified"
    verification_id = append(db_path, run_id, "cookie-verifier", "verification", {
        "result_id": result["id"], "checks": checks,
        "policy": "independent-calculation-v2", "expected_total_litres": expected_total,
        "model_review": model_review, "status": status,
        "scope": "Consistency with a synthetic source, not proof of real-world truth",
    })
    append(db_path, run_id, "cookie-verifier", "lore", {
        "verification_id": verification_id,
        "lesson": {
            "verified": "This run successfully reused another cookie's stored fact.",
            "disputed": "Source or arithmetic checks failed; do not promote this answer.",
            "needs_review": "Source checks passed but the model calculation disagreed; withhold promotion pending review.",
        }[status],
        "status": "run_observation", "scope": "This experiment only; not a universal conclusion",
    })
    if passed:
        append(db_path, run_id, "cookie-verifier", "working_knowledge", {
            "result_id": result["id"], "verification_id": verification_id,
            "answer_litres": answer["answer_litres"],
            "scope": answer["question"], "status": "supported_by_fixture",
        })
    return passed


def report(db_path, run_id):
    with connect(db_path) as db:
        rows = db.execute("SELECT * FROM events WHERE run_id=? ORDER BY sequence", (run_id,)).fetchall()
    events = [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]
    verification = retrieve(db_path, run_id, "verification")["payload"]
    return {"run_id": run_id, "status": verification["status"], "events": events}


def demo(args):
    root = Path(args.state_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    run_id = str(uuid.uuid4())
    source = root / f"source-{run_id}.json"
    source.write_text(json.dumps({"fixture": "Synthetic reservoir specification", "reservoir_capacity_litres": args.capacity}, indent=2) + "\n")
    db_path = root / "memory.sqlite3"
    initialize(db_path)
    base = [sys.executable, str(Path(__file__).resolve()), "worker", "--db", str(db_path),
            "--run-id", run_id, "--source", str(source)]
    if args.model:
        base += ["--model", args.model]
    for role in ("learn", "solve", "verify"):
        command = base + ["--role", role, "--count", str(args.count)]
        if args.inject_error:
            command += ["--inject-error"]
        process = subprocess.run(command, capture_output=True, text=True, timeout=200 if args.model else 30)
        if process.returncode:
            raise RuntimeError(f"{role} worker failed: {process.stderr}")
        print(f"{role}: separate process completed")
    output = report(db_path, run_id)
    report_path = root / f"report-{run_id}.json"
    report_path.write_text(json.dumps(output, indent=2) + "\n")
    proposed = retrieve(db_path, run_id, "result")["payload"]["answer_litres"]
    print(f"Result: {proposed} litres — {output['status']}")
    print(f"Report: {report_path}")
    return {"verified": 0, "disputed": 2, "needs_review": 3}[output["status"]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo_parser = commands.add_parser("demo")
    demo_parser.add_argument("--state-dir", default="state")
    demo_parser.add_argument("--count", type=int, default=3)
    demo_parser.add_argument("--capacity", type=int, default=120, help="Synthetic source capacity in litres")
    demo_parser.add_argument("--inject-error", action="store_true")
    demo_parser.add_argument("--model", help="Installed Ollama model, e.g. gemma4:e4b; omit for scripted demo")
    worker = commands.add_parser("worker")
    worker.add_argument("--role", choices=["learn", "solve", "verify"], required=True)
    worker.add_argument("--db", required=True)
    worker.add_argument("--run-id", required=True)
    worker.add_argument("--source", required=True)
    worker.add_argument("--count", type=int, default=3)
    worker.add_argument("--inject-error", action="store_true")
    worker.add_argument("--model")
    args = parser.parse_args()
    if args.count <= 0:
        parser.error("--count must be positive")
    if args.command == "demo" and args.capacity <= 0:
        parser.error("--capacity must be positive")
    if args.command == "demo":
        return demo(args)
    if args.role == "learn":
        learn(args.db, args.run_id, args.source, args.model)
    elif args.role == "solve":
        solve(args.db, args.run_id, args.count, args.inject_error, args.model)
    else:
        verify(args.db, args.run_id, args.source, args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
