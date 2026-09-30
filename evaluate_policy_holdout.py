#!/usr/bin/env python3
"""Independent synthetic policy cases; does not reuse the README's status labels."""
import argparse
import json
from pathlib import Path
import uuid

import hive
import knowledge

SOURCE = """# Fictional laboratory policy fixture

This document is a synthetic evaluation source, not an operational policy.

| Resulting status | Trigger |
|---|---|
| inspection_required | Calibration is overdue |
| locked | The seal is open |

Vibration can exceed the warning threshold.
"""
CASES = [
    ("overdue", "What happens when calibration is overdue?", "inspection_required"),
    ("open_seal", "What happens when the seal is open?", "locked"),
    ("trigger_only", "What happens when vibration exceeds the warning threshold?", None),
    ("missing_manufacturer", "Who manufactured the seal?", None),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="gemma4:e4b")
    parser.add_argument("--state-dir", default="policy-holdout")
    args = parser.parse_args()
    root = Path(args.state_dir).resolve() / str(uuid.uuid4())
    root.mkdir(parents=True)
    source = root / "policy.md"
    source.write_text(SOURCE)
    db_path = root / "memory.sqlite3"
    knowledge.ingest(db_path, source)
    summary = {"model": args.model, "source_text": SOURCE, "seeds": [11, 29, 47], "temperature": 0.2,
               "planned": 12, "cases": [], "status": "running"}
    for seed in summary["seeds"]:
        for name, question, expected in CASES:
            case = {"seed": seed, "name": name, "question": question, "expected": expected,
                    "accepted": False, "correct": False}
            try:
                result = knowledge.answer_question(db_path, question, args.model, seed, 0.2)
                case["result"] = result
                case["accepted"] = result["status"] == "supported_answer"
                case["correct"] = case["accepted"] and expected is not None and knowledge.normalize_answer(result["answer"]) == expected
                with hive.connect(db_path) as db:
                    rows = db.execute("SELECT kind,cookie,payload FROM events WHERE run_id=? ORDER BY sequence", (result["task_id"],)).fetchall()
                case["events"] = [{"kind": r["kind"], "cookie": r["cookie"], "payload": json.loads(r["payload"])} for r in rows]
            except Exception as error:
                case["error"] = f"{type(error).__name__}: {error}"
            summary["cases"].append(case)
            cases = summary["cases"]
            summary["metrics"] = {
                "completed": len(cases), "false_accepts": sum(c["accepted"] and not c["correct"] for c in cases),
                "false_rejects": sum(c["expected"] is not None and not c["accepted"] for c in cases),
                "correct_accepts": sum(c["correct"] for c in cases),
                "not_found_findings": sum(c.get("result", {}).get("status") == "not_found_in_source" for c in cases),
                "errors": sum("error" in c for c in cases),
            }
            if len(cases) == summary["planned"]:
                summary["status"] = "passed" if (summary["metrics"]["correct_accepts"] == 6 and
                    summary["metrics"]["not_found_findings"] == 6 and not summary["metrics"]["errors"]) else "failed"
            (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
            print(f"seed={seed} {name}: {case.get('result', {}).get('status', 'error')} answer={case.get('result', {}).get('answer', '')!r}", flush=True)
    print(f"Summary: {root / 'summary.json'}", flush=True)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
