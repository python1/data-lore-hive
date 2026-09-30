import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import knowledge
import policy_binding
import relevance_cookie
from policy_tables import status_fields, status_table

TABLE = """| Status | Trigger | Promotion |
|---|---|---|
| inspection_required | Calibration overdue | No |
| ready | Calibration complete | Yes |"""


class PolicyTableTests(unittest.TestCase):
    def test_status_values_come_from_named_column_not_promotion(self):
        parsed = status_table(TABLE)
        self.assertEqual(parsed["statuses"], ["inspection_required", "ready"])
        self.assertEqual(parsed["quote"], TABLE)

    def test_resulting_status_header_and_different_order(self):
        text = "| Trigger | Resulting status |\n|---|---|\n| Door open | locked |"
        self.assertEqual(status_table(text)["statuses"], ["locked"])

    def test_unknown_malformed_and_overlong_tables_do_not_activate(self):
        cases = [TABLE.replace("Status", "Value"), TABLE.replace("|---|---|---|", "|bad|bad|bad|"),
                 TABLE.replace("| ready | Calibration complete | Yes |", "| ready |"),
                 TABLE.replace("Calibration overdue", "a" * 450)]
        for case in cases:
            with self.subTest(case=case):
                self.assertIsNone(status_table(case))

    def test_choices_apply_only_to_policy_question(self):
        fields = {"answer": {"type": "string"}}
        self.assertEqual(status_fields(fields, "Who made it?", [TABLE]), fields)
        narrowed = status_fields(fields, "What happens when calibration is overdue?", [TABLE])
        self.assertEqual(narrowed["answer"]["enum"], ["", "inspection_required", "ready"])
        self.assertNotIn("enum", fields["answer"])

    def test_support_receives_complete_source_table(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source, db = root / "policy.md", root / "memory.sqlite3"
            source.write_text(TABLE)
            knowledge.ingest(db, source)
            question = "What happens when calibration is overdue?"
            chunk = knowledge.search(db, question)["candidates"][0]
            proposal = {"decision": "answered", "condition": "Calibration overdue", "outcome": "inspection_required",
                        "chunk_id": chunk["chunk_id"], "quote": "Calibration overdue"}
            support = {"decision": "answered", "condition": "Calibration overdue", "outcome": "inspection_required"}
            with patch("knowledge.ask", return_value=(proposal, {})), patch("knowledge.support_review", return_value=(support, {})) as worker, patch("relevance_cookie.review", return_value={
                    "accepted": True, "rule": policy_binding.rules(TABLE)[0], "event_id": "synthetic-relevance",
                    "identity": {"family": "synthetic", "digest": "0"*64}, "seed": 11, "purpose": "binding"}):
                result = knowledge.answer_question(db, question, "test")
            self.assertEqual(worker.call_args.args[:2], (question, TABLE))
            self.assertEqual(result["quote"], TABLE)
            self.assertEqual(result["status"], "supported_answer")

    def test_disagreement_still_withholds_table_answer(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source, db = root / "policy.md", root / "memory.sqlite3"
            source.write_text(TABLE)
            knowledge.ingest(db, source)
            question = "What happens when calibration is overdue?"
            chunk = knowledge.search(db, question)["candidates"][0]
            proposal = {"decision": "answered", "condition": "Calibration overdue", "outcome": "inspection_required", "chunk_id": chunk["chunk_id"], "quote": TABLE}
            with patch("knowledge.ask", return_value=(proposal, {})), patch("knowledge.support_review", return_value=({"decision": "answered", "condition": "Calibration complete", "outcome": "ready"}, {})):
                result = knowledge.answer_question(db, question, "test")
            self.assertEqual(result["status"], "needs_review")
            self.assertNotIn("answer", result)

    def test_both_cookies_agree_on_nonanswer_is_withheld(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            source, db = root / "policy.md", root / "memory.sqlite3"
            source.write_text(TABLE)
            knowledge.ingest(db, source)
            question = "What happens when calibration is overdue?"
            chunk = knowledge.search(db, question)["candidates"][0]
            wrong = "Calibration overdue"
            proposal = {"decision": "answered", "condition": wrong, "outcome": wrong, "chunk_id": chunk["chunk_id"], "quote": TABLE}
            with patch("knowledge.ask", return_value=(proposal, {})), patch("knowledge.support_review", return_value=({"decision": "answered", "condition": wrong, "outcome": wrong}, {})):
                result = knowledge.answer_question(db, question, "test")
            self.assertTrue(result["checks"]["answers_agree"])
            self.assertTrue(result["checks"]["solver_answer_anchored"])
            self.assertEqual(result["status"], "needs_review")
            self.assertNotIn("answer", result)


if __name__ == "__main__":
    unittest.main()
