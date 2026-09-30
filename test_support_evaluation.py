import unittest
from evaluate_support import metrics, CASES


class MetricsTests(unittest.TestCase):
    def test_false_accept_and_false_reject_are_separate(self):
        result = metrics([
            {"answerable": False, "accepted": True, "correct": False, "audit_passed": True},
            {"answerable": True, "accepted": False, "correct": False, "audit_passed": True},
            {"answerable": True, "accepted": True, "correct": True, "audit_passed": True},
            {"answerable": False, "accepted": False, "correct": False, "audit_passed": True,
             "result": {"status": "not_found_in_source"}},
        ])
        self.assertEqual(result["false_accepts"], 1)
        self.assertEqual(result["false_rejects"], 1)
        self.assertEqual(result["correct_accepts"], 1)
        self.assertEqual(result["not_found_findings"], 1)

    def test_runtime_error_on_answerable_is_not_hidden(self):
        result = metrics([{"answerable": True, "error": "timeout"}])
        self.assertEqual(result["errors"], 1)
        self.assertEqual(result["false_rejects"], 1)

    def test_explicit_negative_statement_is_valid_gold_answer(self):
        case = next(c for c in CASES if c[0] == "replication_support")
        self.assertIn("it does not provide peer replication", case[3])


if __name__ == "__main__":
    unittest.main()
