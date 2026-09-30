#!/usr/bin/env python3
"""Controlled negative regression: identical, sourced, nonresponsive prose answers.

No live inference: both cookie responses are forced so the final gate, not model
sampling luck, is evaluated. Exit 1 means the unsupported answer escaped the gate.
"""
import json
from pathlib import Path
import sys
import uuid
from unittest.mock import patch
import hive
import knowledge


def main():
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "prose-nonanswer").resolve() / str(uuid.uuid4())
    root.mkdir(parents=True)
    source = root / "policy.md"
    quote = "If calibration is overdue, the resulting status is inspection_required."
    source.write_text(quote + "\n")
    db = root / "memory.sqlite3"
    knowledge.ingest(db, source)
    question = "What happens when calibration is overdue?"
    chunk = knowledge.search(db, question)["candidates"][0]
    wrong_answer = "calibration is overdue"
    solver = {"outcome": "answered", "answer": wrong_answer, "quote": quote, "chunk_id": chunk["chunk_id"]}
    support = {"outcome": "answered", "answer": wrong_answer}
    with patch("knowledge.ask", return_value=(solver, {"answer": solver, "test_injected": True})), patch("knowledge.support_review", return_value=(support, {"answer": support, "test_injected": True})):
        result = knowledge.answer_question(db, question, "controlled-test")
    with hive.connect(db) as connection:
        rows = connection.execute("SELECT kind,cookie,payload FROM events WHERE run_id=? ORDER BY sequence", (result["task_id"],)).fetchall()
    report = {"test_type": "controlled cookie-response injection; no live model calls",
              "question": question, "source_text": quote, "correct_answer": "inspection_required",
              "solver_answer": wrong_answer, "support_answer": wrong_answer,
              "expected_status": "needs_review", "caught": result["status"] != "supported_answer",
              "result": result, "fixed": False,
              "events": [{"kind": r["kind"], "cookie": r["cookie"], "payload": json.loads(r["payload"])} for r in rows]}
    (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"caught": report["caught"], "status": result["status"], "report": str(root / "report.json")}), flush=True)
    return 0 if report["caught"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
