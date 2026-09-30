#!/usr/bin/env python3
"""Evaluate arithmetic and source retrieval without modifying production memory."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

import hive
import knowledge


def run(command, timeout=240):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemma4:e4b")
    parser.add_argument("--state-dir", default="batch-evaluation")
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    root = Path(args.state_dir).resolve() / str(uuid.uuid4())
    root.mkdir(parents=True)
    summary = {"model": args.model, "batch_id": root.name, "status": "running", "suites": {}}

    def save():
        (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    save()
    unit = run([sys.executable, "-W", "error::ResourceWarning", "-m", "unittest", "discover", "-s", str(base), "-v"])
    summary["unit_tests"] = unit
    save()
    print(f"Unit tests: {'PASS' if unit['exit_code'] == 0 else 'FAIL'}", flush=True)
    # The existing evaluator preserves per-case errors and continues after failures.
    arithmetic_dir = root / "arithmetic"
    try:
        process = run([sys.executable, str(base / "evaluate.py"), "--model", args.model,
                       "--state-dir", str(arithmetic_dir)], timeout=3800)
        reports = list(arithmetic_dir.glob("*/summary.json"))
        arithmetic = json.loads(reports[0].read_text()) if len(reports) == 1 else {"error": "Missing arithmetic summary"}
        summary["suites"]["arithmetic"] = {**arithmetic, "process": process}
        print(f"Arithmetic: {arithmetic.get('passed', 0)}/6 passed", flush=True)
    except Exception as error:
        summary["suites"]["arithmetic"] = {"error": str(error)}
    save()

    # Freeze the actual project documentation; no tailored answer text is added.
    source = root / "README-snapshot.md"
    source.write_bytes((base / "PROTOTYPE-NOTES.md").read_bytes())
    db_path = root / "source-memory.sqlite3"
    ingestion = run([sys.executable, str(base / "knowledge.py"), "--db", str(db_path), "ingest", str(source)])
    if ingestion["exit_code"]:
        summary["suites"]["source_memory"] = {"error": "Ingestion failed", "process": ingestion}
        summary["status"] = "failed"
        save()
        return 1
    source_id = json.loads(ingestion["stdout"])["source_id"]
    specs = [
        ("review_policy", "What happens when the model calculation disagrees?", "supported_answer", "needs_review", True),
        ("replication_support", "Does this project support peer replication?", "supported_answer", "does not provide peer replication", True),
        ("absent_temperature", "What is the reservoir water temperature in Celsius?", "not_found_in_source", None, True),
        ("absent_ip", "What is the hive server IP address?", "not_found_in_source", None, True),
        ("absent_manufacturer", "Who manufactured the reservoir?", "not_found_in_source", None, True),
        ("no_keyword_match", "Platypus habitat?", "not_found_in_source", None, False),
    ]
    suite = {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "source_id": source_id,
             "planned": len(specs), "cases": []}
    summary["suites"]["source_memory"] = suite
    for name, question, expected, phrase, expect_candidates in specs:
        case = {"name": name, "question": question, "expected_status": expected,
                "expected_answer_phrase": phrase, "expected_candidates": expect_candidates, "passed": False}
        try:
            retrieved = knowledge.search(db_path, question)
            case["retrieval"] = retrieved
            path = root / f"{name}.json"
            process = run([sys.executable, str(base / "knowledge.py"), "--db", str(db_path), "ask",
                           question, "--model", args.model, "--report", str(path)])
            case["process"] = process
            result = json.loads(path.read_text())
            case["result"] = result
            checks = {
                "expected_status": result["status"] == expected,
                "expected_exit": process["exit_code"] == 0,
                "retrieval_exercised": bool(retrieved["candidates"]) == expect_candidates,
            }
            if expected == "supported_answer":
                quote = result.get("quote", "")
                citation = result.get("citation", {})
                matching = next((c for c in retrieved["candidates"] if c["chunk_id"] == citation.get("chunk_id")), None)
                text = source.read_text()
                offset = matching["offset"] + matching["text"].find(quote) if matching else -1
                checks.update(
                    answer_content=bool(quote) and phrase in quote.lower(),
                    exact_quote=bool(quote) and bool(matching) and quote in matching["text"],
                    source_link=citation.get("source_id") == source_id,
                    source_hash=citation.get("sha256") == suite["source_sha256"],
                    source_path=citation.get("path") == str(source),
                    source_line=offset >= 0 and citation.get("line") == text.count("\n", 0, offset) + 1,
                )
            else:
                checks["no_answer_or_citation"] = "quote" not in result and "citation" not in result
            with hive.connect(db_path) as db:
                events = db.execute("SELECT kind,payload FROM events WHERE run_id=? ORDER BY sequence", (result["task_id"],)).fetchall()
            case["events"] = [{"kind": row["kind"], "payload": json.loads(row["payload"])} for row in events]
            calls = sum(event["kind"] == "model_call" and event["payload"].get("answer", {}).get("chunk_id") is not None for event in case["events"])
            checks["model_called_as_expected"] = calls == int(expect_candidates)
            case.update(checks=checks, passed=all(checks.values()))
        except Exception as error:
            case["error"] = f"{type(error).__name__}: {error}"
        suite["cases"].append(case)
        suite["completed"] = len(suite["cases"])
        suite["passed"] = sum(c["passed"] for c in suite["cases"])
        save()
        print(f"Source {name}: {'PASS' if case['passed'] else 'FAIL'}", flush=True)
    arithmetic = summary["suites"]["arithmetic"]
    success = (unit["exit_code"] == 0 and arithmetic.get("passed") == 6
               and arithmetic.get("process", {}).get("exit_code") == 0 and suite["passed"] == len(specs))
    summary["status"] = "passed" if success else "failed"
    save()
    print(f"Batch {summary['status']}: {root / 'summary.json'}", flush=True)
    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
