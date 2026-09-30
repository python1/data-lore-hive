import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hive


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / "memory.sqlite3"
        self.source = Path(self.temp.name) / "source.json"
        self.source.write_text(json.dumps({"reservoir_capacity_litres": 120}))
        hive.initialize(self.db)
        hive.learn(self.db, "run", self.source)

    def test_reuse_promotes_supported_result(self):
        hive.solve(self.db, "run", 3)
        self.assertTrue(hive.verify(self.db, "run", self.source))
        self.assertEqual(hive.retrieve(self.db, "run", "working_knowledge")["payload"]["answer_litres"], 360)

    def test_wrong_answer_retained_but_not_promoted(self):
        hive.solve(self.db, "run", 3, inject_error=True)
        self.assertFalse(hive.verify(self.db, "run", self.source))
        self.assertEqual(hive.retrieve(self.db, "run", "result")["payload"]["answer_litres"], 361)
        self.assertEqual(hive.retrieve(self.db, "run", "verification")["payload"]["status"], "disputed")
        with self.assertRaises(ValueError):
            hive.retrieve(self.db, "run", "working_knowledge")

    def test_changed_source_disputes_result(self):
        hive.solve(self.db, "run", 3)
        self.source.write_text(json.dumps({"reservoir_capacity_litres": 121}))
        self.assertFalse(hive.verify(self.db, "run", self.source))

    def test_run_isolation(self):
        with self.assertRaises(ValueError):
            hive.retrieve(self.db, "unrelated-run", "claim")

    def test_history_rejects_edits(self):
        for statement in ("UPDATE events SET cookie='changed'", "DELETE FROM events"):
            with self.subTest(statement=statement), hive.connect(self.db) as db:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(statement)

    def test_model_approval_cannot_override_wrong_answer(self):
        hive.solve(self.db, "run", 3, inject_error=True)
        with patch("hive.ask", return_value=({"expected_total_litres": 361}, {})):
            self.assertFalse(hive.verify(self.db, "run", self.source, model="test"))
        with self.assertRaises(ValueError):
            hive.retrieve(self.db, "run", "working_knowledge")

    def test_model_failure_does_not_create_scripted_fallback(self):
        with patch("hive.ask", side_effect=ValueError("Invalid model output")):
            with self.assertRaises(ValueError):
                hive.solve(self.db, "run", 3, model="test")
        with self.assertRaises(ValueError):
            hive.retrieve(self.db, "run", "result")

    def test_solver_retrieves_claim_for_model(self):
        with patch("hive.ask", return_value=({"answer_litres": 480}, {})) as model:
            hive.solve(self.db, "run", 4, model="test")
        context = model.call_args.args[2]
        self.assertEqual(context["retrieved_claim"]["value"], 120)
        self.assertEqual(context["reservoir_count"], 4)
        self.assertNotIn("original_source", context)
        self.assertEqual(hive.retrieve(self.db, "run", "result")["payload"]["answer_litres"], 480)

    def test_seven_reservoir_regression_and_blind_review(self):
        hive.solve(self.db, "run", 7)
        with patch("hive.ask", return_value=({"expected_total_litres": 840}, {})) as model:
            self.assertTrue(hive.verify(self.db, "run", self.source, model="test"))
        context = model.call_args.args[2]
        self.assertEqual(set(context), {"original_source", "reservoir_count"})
        self.assertEqual(context["reservoir_count"], 7)
        self.assertEqual(hive.retrieve(self.db, "run", "working_knowledge")["payload"]["answer_litres"], 840)

    def test_model_miscalculation_requires_review(self):
        hive.solve(self.db, "run", 7)
        with patch("hive.ask", return_value=({"expected_total_litres": 841}, {})):
            self.assertFalse(hive.verify(self.db, "run", self.source, model="test"))
        verification = hive.retrieve(self.db, "run", "verification")["payload"]
        self.assertEqual(verification["status"], "needs_review")
        self.assertTrue(all(verification["checks"].values()))
        with self.assertRaises(ValueError):
            hive.retrieve(self.db, "run", "working_knowledge")

    def test_changed_source_cannot_be_overruled_by_model(self):
        hive.solve(self.db, "run", 7)
        self.source.write_text(json.dumps({"reservoir_capacity_litres": 121}))
        with patch("hive.ask", return_value=({"expected_total_litres": 840}, {})):
            self.assertFalse(hive.verify(self.db, "run", self.source, model="test"))
        self.assertEqual(hive.retrieve(self.db, "run", "verification")["payload"]["status"], "disputed")

    def test_verifier_failure_prevents_promotion(self):
        hive.solve(self.db, "run", 7)
        with patch("hive.ask", side_effect=ValueError("Invalid model output")):
            with self.assertRaises(ValueError):
                hive.verify(self.db, "run", self.source, model="test")
        with self.assertRaises(ValueError):
            hive.retrieve(self.db, "run", "working_knowledge")


if __name__ == "__main__":
    unittest.main()
