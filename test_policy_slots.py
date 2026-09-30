import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import knowledge
import policy_slots
import support_cookie

TEXT = "If calibration is overdue, the resulting status is inspection_required."


class SlotTests(unittest.TestCase):
    def test_routing_does_not_depend_on_policy_evidence(self):
        for question, route in [("Who manufactured the seal?", "general"),
                                ("What happens when the seal opens?", "policy"),
                                ("Under what condition is inspection required?", "policy"),
                                ("Explain this policy", "review"),
                                ("What should happen next?", "review")]:
            with self.subTest(question=question):
                self.assertEqual(policy_slots.question_route(question), route)
                for evidence in [TEXT, "| Trigger | Status |\n|---|---|\n|open|locked|", "Plain text"]:
                    self.assertEqual(policy_slots.policy_mode(question, [evidence]), route == "policy")

    def test_manufacturer_uses_general_schema_in_both_cookies(self):
        absent = {"outcome": "not_found_in_source", "answer": ""}
        result, calls = self.run_case("Who manufactured the calibration device?", absent, absent)
        self.assertEqual(result["question_route"], "general")
        self.assertEqual(result["status"], "not_found_in_source")
        self.assertEqual(calls, 1)
        with patch("support_cookie.ask", return_value=(absent, {})) as model:
            support_cookie.review("Who manufactured the calibration device?", TEXT, "test")
        self.assertEqual(set(model.call_args.args[3]), {"outcome", "answer"})
        self.assertEqual(set(model.call_args.args[2]), {"question", "quote"})

    def test_manufacturer_not_found_requires_support_confirmation(self):
        absent = {"outcome": "not_found_in_source", "answer": ""}
        found = {"outcome": "answered", "answer": "Example Labs"}
        result, calls = self.run_case("Who manufactured the calibration device?", absent, found)
        self.assertEqual(calls, 1)
        self.assertEqual(result["status"], "needs_review")

    def test_requested_slot_is_deterministic(self):
        for question, expected in [("What happens when calibration is overdue?", "outcome"),
                                   ("What is required after calibration expires?", "outcome"),
                                   ("When is inspection required?", "condition"),
                                   ("Under what condition is inspection required?", "condition"),
                                   ("Explain this policy", None)]:
            with self.subTest(question=question):
                self.assertEqual(policy_slots.requested_slot(question), expected)

    def run_case(self, question, solver_fields, support_fields, text=TEXT):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, db = root / "policy.md", root / "memory.sqlite3"
            source.write_text(text)
            knowledge.ingest(db, source)
            found = knowledge.search(db, question)
            chunk = found["candidates"][0]
            proposal = {**solver_fields, "chunk_id": chunk["chunk_id"], "quote": text}
            with patch("knowledge.ask", return_value=(proposal, {"answer": proposal})), patch("knowledge.support_review", return_value=(support_fields, {"answer": support_fields})) as support:
                result = knowledge.answer_question(db, question, "test")
            return result, support.call_count

    def test_matching_prose_triggers_in_outcome_slot_are_caught(self):
        wrong = {"decision": "answered", "condition": "calibration is overdue", "outcome": "calibration is overdue"}
        result, _ = self.run_case("What happens when calibration is overdue?", wrong, wrong)
        self.assertTrue(result["checks"]["answers_agree"])
        self.assertTrue(result["checks"]["solver_answer_anchored"])
        self.assertFalse(result["checks"]["solver_value_in_requested_role"])
        self.assertEqual(result["status"], "needs_review")
        self.assertNotIn("answer", result)

    def test_prose_outcome_is_accepted(self):
        fields = {"decision": "answered", "condition": "calibration is overdue", "outcome": "inspection_required"}
        result, _ = self.run_case("What happens when calibration is overdue?", fields, fields)
        self.assertEqual(result["answer"], "inspection_required")

    def test_condition_question_compares_condition(self):
        fields = {"decision": "answered", "condition": "calibration is overdue", "outcome": "inspection_required"}
        result, _ = self.run_case("When is inspection_required?", fields, fields)
        self.assertEqual(result["answer"], "calibration is overdue")
        self.assertEqual(result["requested_slot"], "condition")

    def test_ambiguous_policy_question_is_withheld(self):
        fields = {"decision": "answered", "condition": "calibration is overdue", "outcome": "inspection_required"}
        result, calls = self.run_case("Explain this calibration policy", fields, fields)
        self.assertEqual(result["status"], "needs_review")
        self.assertEqual(result["reason"], "unclassified_policy_question")
        self.assertEqual(calls, 0)

    def test_missing_structured_fields_are_withheld(self):
        legacy = {"outcome": "answered", "answer": "calibration is overdue"}
        result, _ = self.run_case("What happens when calibration is overdue?", legacy, legacy)
        self.assertEqual(result["status"], "needs_review")

    def test_role_parser_preserves_direction(self):
        self.assertTrue(policy_slots.role_matches("calibration is overdue", "condition", TEXT))
        self.assertFalse(policy_slots.role_matches("calibration is overdue", "outcome", TEXT))
        self.assertTrue(policy_slots.role_matches("inspection_required", "outcome", TEXT))

    def test_seed29_cross_row_pair_withheld_even_with_agreement(self):
        table = """| Status | Meaning | Promotion | CLI exit |
|---|---|---|---|
| `verified` | All source checks pass; the model calculation agrees when enabled | Yes | 0 |
| `disputed` | A deterministic evidence or arithmetic check failed | No | 2 |
| `needs_review` | Source checks pass, but the model calculates a different total | No | 3 |"""
        wrong = {"decision": "answered", "condition": "Source checks pass, but the model calculates a different total", "outcome": "disputed"}
        result, _ = self.run_case("What happens when the model calculation disagrees?", wrong, wrong, table)
        self.assertTrue(result["checks"]["answers_agree"])
        self.assertTrue(result["checks"]["solver_answer_anchored"])
        self.assertTrue(result["checks"]["solver_value_in_requested_role"])
        self.assertFalse(result["checks"]["solver_pair_in_same_rule"])
        self.assertFalse(result["checks"]["support_pair_in_same_rule"])
        self.assertEqual(result["status"], "needs_review")
        self.assertNotIn("answer", result)

    def test_each_cookie_pair_checked_for_either_requested_slot(self):
        text = "If calibration is overdue, the resulting status is inspection_required. If seal is broken, the resulting status is locked."
        good = {"decision":"answered", "condition":"calibration is overdue", "outcome":"inspection_required"}
        for question, other in [("What happens when calibration is overdue?", "condition"),
                                ("When is inspection_required?", "outcome")]:
            bad = {**good, other: "seal is broken" if other == "condition" else "locked"}
            for solver, support, key in [(bad,good,"solver_pair_in_same_rule"),(good,bad,"support_pair_in_same_rule")]:
                with self.subTest(question=question,key=key):
                    result, _ = self.run_case(question,solver,support,text)
                    self.assertTrue(result["checks"]["answers_agree"])
                    self.assertFalse(result["checks"][key])
                    self.assertEqual(result["status"],"needs_review")
                    self.assertNotIn("answer",result)

    def test_pair_requires_parseable_complete_rule(self):
        good = {"decision":"answered", "condition":"calibration is overdue", "outcome":"inspection_required"}
        self.assertTrue(policy_slots.pair_matches(good,TEXT))
        self.assertFalse(policy_slots.pair_matches(good,"calibration is overdue inspection_required"))
        self.assertFalse(policy_slots.pair_matches({**good,"condition":""},TEXT))
        self.assertFalse(policy_slots.pair_matches({**good,"decision":"not_found_in_source"},TEXT))


if __name__ == "__main__":
    unittest.main()
