#!/usr/bin/env python3
"""Three-seed evaluation on the frozen six-case source-memory regression set."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
from datetime import datetime, timezone

import hive
import knowledge

CASES = [
    ("review_policy", "What happens when the model calculation disagrees?", True, {"needs_review", "needs review"}),
    ("replication_support", "Does this project support peer replication?", True, {"no", "it does not provide peer replication"}),
    ("absent_temperature", "What is the reservoir water temperature in Celsius?", False, set()),
    ("absent_ip", "What is the hive server IP address?", False, set()),
    ("absent_manufacturer", "Who manufactured the reservoir?", False, set()),
    ("no_keyword_match", "Platypus habitat?", False, set()),
]


def metrics(cases):
    return {
        "completed": len(cases),
        "answerable": sum(c["answerable"] for c in cases),
        "unanswerable": sum(not c["answerable"] for c in cases),
        "false_accepts": sum(c.get("accepted", False) and not c.get("correct", False) for c in cases),
        "false_rejects": sum(c["answerable"] and not c.get("accepted", False) for c in cases),
        "correct_accepts": sum(c.get("correct", False) for c in cases),
        "wrong_accepts_on_answerable": sum(c["answerable"] and c.get("accepted", False) and not c.get("correct", False) for c in cases),
        "not_found_findings": sum(c.get("result", {}).get("status") == "not_found_in_source" for c in cases),
        "needs_review": sum(c.get("result", {}).get("status") == "needs_review" for c in cases),
        "errors": sum("error" in c for c in cases),
        "audit_failures": sum(not c.get("audit_passed", False) for c in cases),
        "statuses": dict(Counter(c.get("result", {}).get("status", "error") for c in cases)),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemma4:e4b")
    parser.add_argument("--state-dir", default="support-evaluation")
    parser.add_argument("--seeds", nargs=3, type=int, default=[11, 29, 47])
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--baseline", help="Prior seeded report; preserve source/chunk IDs for identical solver inputs")
    args = parser.parse_args()
    if len(set(args.seeds)) != 3:
        parser.error("Provide three distinct seeds")
    base = Path(__file__).resolve().parent
    previous = base / "batch-validation-1d3dc0b9.json"
    original_bytes = previous.read_bytes()
    previous_hash = hashlib.sha256(original_bytes).hexdigest()
    original = json.loads(original_bytes)
    baseline = None
    baseline_hash = None
    if args.baseline:
        baseline_bytes = Path(args.baseline).read_bytes()
        baseline_hash = hashlib.sha256(baseline_bytes).hexdigest()
        baseline = json.loads(baseline_bytes)
        if (baseline["model"], baseline["seeds"], baseline["temperature"]) != (args.model, args.seeds, args.temperature):
            parser.error("Model, seeds and temperature must match the baseline")
        if baseline["evaluation_source_text"] != original["evaluation_source_text"]:
            parser.error("Baseline source does not match the frozen regression source")
    root = Path(args.state_dir).resolve() / str(uuid.uuid4())
    root.mkdir(parents=True)
    source = root / "README-frozen.md"
    source.write_text(original["evaluation_source_text"])
    db_path = root / "memory.sqlite3"
    if baseline:
        # Seed only the frozen source event in a NEW database. Prior query history
        # is not copied, and production ingestion/answering code is unchanged.
        source_ids = {chunk["source_id"] for case in baseline["cases"] for chunk in case["retrieval"]["candidates"]}
        if len(source_ids) != 1:
            parser.error("Expected one baseline source")
        source_id = source_ids.pop()
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        hive.initialize(db_path)
        payload = {"path": str(source), "source_uri": source.as_uri(), "text": source.read_text(),
                   "sha256": sha, "supersedes": None, "trust": "Frozen evaluation snapshot"}
        with hive.connect(db_path) as db:
            db.execute("INSERT INTO events(id,run_id,cookie,kind,recorded_at,payload) VALUES(?,?,?,?,?,?)",
                       (source_id, str(uuid.uuid4()), "evaluation-fixture", "source_ingested",
                        datetime.now(timezone.utc).isoformat(), json.dumps(payload)))
        ingested = {"source_id": source_id, "sha256": sha}
    else:
        ingested = knowledge.ingest(db_path, source)
    summary = {"policy": "quote-support-v2", "model": args.model, "seeds": args.seeds,
               "temperature": args.temperature, "planned": 18, "status": "running",
               "previous_report_sha256": previous_hash, "source_sha256": ingested["sha256"],
               "evaluation_source_text": source.read_text(), "cases": [],
               "definitions": {
                   "false_accept": "Delivered supported_answer on an unanswerable question or with a wrong answer/citation on an answerable question",
                   "false_reject": "Answerable question with no delivered supported_answer, including runtime errors",
                   "correct_answer_rule": "Gold answers: needs_review/needs review; No or the source's exact statement 'It does not provide peer replication'; plus exact quote and citation checks",
                   "sampling": "Three seeds with identical source and prompts, temperature 0.2; same model for both cookies; not independent model populations",
               }}
    summary["baseline_report_sha256"] = baseline_hash
    summary["implementation_sha256"] = {name: hashlib.sha256((base / name).read_bytes()).hexdigest()
                                         for name in ("knowledge.py", "support_cookie.py", "ollama_local.py")}

    def save():
        summary["metrics"] = metrics(summary["cases"])
        summary["per_seed"] = {str(seed): metrics([c for c in summary["cases"] if c["seed"] == seed]) for seed in args.seeds}
        (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    save()
    for seed in args.seeds:
        for name, question, answerable, gold in CASES:
            case = {"name": name, "question": question, "seed": seed, "answerable": answerable,
                    "gold_answers": sorted(gold), "accepted": False, "correct": False}
            try:
                retrieval = knowledge.search(db_path, question)
                case["retrieval"] = retrieval
                path = root / f"{seed}-{name}.json"
                command = [sys.executable, str(base / "knowledge.py"), "--db", str(db_path), "ask", question,
                           "--model", args.model, "--seed", str(seed), "--temperature", str(args.temperature), "--report", str(path)]
                process = subprocess.run(command, capture_output=True, text=True, timeout=420)
                case["process"] = {"exit_code": process.returncode, "stdout": process.stdout, "stderr": process.stderr}
                result = json.loads(path.read_text())
                case["result"] = result
                with hive.connect(db_path) as db:
                    rows = db.execute("SELECT kind,cookie,payload FROM events WHERE run_id=? ORDER BY sequence", (result["task_id"],)).fetchall()
                events = [{"kind": row["kind"], "cookie": row["cookie"], "payload": json.loads(row["payload"])} for row in rows]
                case["events"] = events
                calls = [event for event in events if event["kind"] == "model_call"]
                support_calls = [event for event in calls if event["cookie"] == "cookie-support"]
                case["accepted"] = result["status"] == "supported_answer"
                audits = {
                    "sampling_logged": all(c["payload"]["generation_options"].get("seed") == seed and c["payload"]["generation_options"]["temperature"] == args.temperature for c in calls),
                    "solver_called_on_candidates": sum(c["cookie"] == "cookie-solver" for c in calls) == int(bool(retrieval["candidates"])),
                    "support_context_isolated": all(set(c["payload"]["context"]) == {"question", "quote"} and c["payload"]["context"]["question"] == question for c in support_calls),
                    "withheld_answer_not_exposed": case["accepted"] or not any(k in result for k in ("answer", "quote", "citation")),
                }
                if baseline:
                    baseline_case = next(c for c in baseline["cases"] if c["seed"] == seed and c["name"] == name)
                    old_contexts = [e["payload"]["context_sha256"] for e in baseline_case["events"]
                                    if e["kind"] == "model_call" and e["cookie"] == "cookie-solver"]
                    new_contexts = [e["payload"]["context_sha256"] for e in calls if e["cookie"] == "cookie-solver"]
                    audits["solver_context_matches_baseline"] = old_contexts == new_contexts
                if case["accepted"]:
                    citation = result["citation"]
                    quote = result["quote"]
                    selected = next((c for c in retrieval["candidates"] if c["chunk_id"] == citation["chunk_id"]), None)
                    offset = selected["offset"] + selected["text"].find(quote) if selected else -1
                    grounded = (bool(quote) and bool(selected) and quote in selected["text"]
                                and citation["source_id"] == ingested["source_id"] and citation["sha256"] == ingested["sha256"]
                                and citation["path"] == str(source) and offset >= 0
                                and citation["line"] == source.read_text().count("\n", 0, offset) + 1)
                    case["correct"] = answerable and knowledge.normalize_answer(result["answer"]) in gold and grounded
                    audits["supported_before_delivery"] = len(support_calls) == 1 and all(result["checks"].values()) and process.returncode == 0
                elif result["status"] == "not_found_in_source":
                    audits["finding_recorded"] = bool(result.get("finding_id")) and any(e["kind"] == "source_finding" and e["payload"]["finding"] == "not_found_in_source" for e in events)
                    audits["finding_not_failure"] = process.returncode == 0
                elif result["status"] == "needs_review":
                    audits["review_exit"] = process.returncode == 3
                else:
                    audits["valid_terminal_status"] = False
                case["audit_checks"] = audits
                case["audit_passed"] = all(audits.values())
            except Exception as error:
                case["error"] = f"{type(error).__name__}: {error}"
            summary["cases"].append(case)
            save()
            print(f"seed={seed} {name}: {case.get('result', {}).get('status', 'error')} answer={case.get('result', {}).get('answer', '')!r}", flush=True)
    summary["previous_report_unchanged"] = hashlib.sha256(previous.read_bytes()).hexdigest() == previous_hash
    if args.baseline:
        summary["baseline_report_unchanged"] = hashlib.sha256(Path(args.baseline).read_bytes()).hexdigest() == baseline_hash
    m = metrics(summary["cases"])
    summary["status"] = "passed" if not any(m[k] for k in ("false_accepts", "false_rejects", "errors", "audit_failures")) and summary["previous_report_unchanged"] else "failed"
    save()
    print(json.dumps(summary["metrics"]), flush=True)
    print(f"Summary: {root / 'summary.json'}", flush=True)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
