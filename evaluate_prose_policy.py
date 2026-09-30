#!/usr/bin/env python3
"""Three-seed prose rendering of the existing fictional laboratory policy."""
import json
from pathlib import Path
import sys
import uuid
import hive
import knowledge
from policy_tables import status_table

SOURCE = """# Fictional laboratory policy fixture

This document is a synthetic evaluation source, not an operational policy.

If calibration is overdue, the resulting status is inspection_required.
If the seal is open, the resulting status is locked.

Vibration can exceed the warning threshold.
"""


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "prose-evaluation").resolve() / str(uuid.uuid4())
    root.mkdir(parents=True)
    source = root / "prose-policy.md"
    source.write_text(SOURCE)
    db = root / "memory.sqlite3"
    knowledge.ingest(db, source)
    assert status_table(SOURCE) is None
    summary = {"source_text": SOURCE, "model": "gemma4:e4b", "seeds": [11, 29, 47],
               "temperature": 0.2, "table_parser_active": False, "cases": []}
    question = "What happens when calibration is overdue?"
    for seed in summary["seeds"]:
        case = {"seed": seed, "question": question, "expected": "inspection_required", "passed": False}
        try:
            result = knowledge.answer_question(db, question, "gemma4:e4b", seed, 0.2)
            case["result"] = result
            case["passed"] = result["status"] == "supported_answer" and knowledge.normalize_answer(result["answer"]) == "inspection_required"
            with hive.connect(db) as connection:
                rows = connection.execute("SELECT kind,cookie,payload FROM events WHERE run_id=? ORDER BY sequence", (result["task_id"],)).fetchall()
            case["events"] = [{"kind": r["kind"], "cookie": r["cookie"], "payload": json.loads(r["payload"])} for r in rows]
        except Exception as error:
            case["error"] = str(error)
        summary["cases"].append(case)
        summary["passed"] = sum(c["passed"] for c in summary["cases"])
        (root / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(seed, case.get("result", case.get("error")), flush=True)
    print(f"Summary: {root / 'summary.json'}", flush=True)
    return 0 if summary["passed"] == 3 else 1


if __name__ == "__main__":
    raise SystemExit(main())
