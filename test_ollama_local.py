import io
import json
import unittest
from unittest.mock import patch

from ollama_local import ask


class ResponseValidationTests(unittest.TestCase):
    def request(self, answer, **overrides):
        response = {"done": True, "done_reason": "stop", "model": "test",
                    "message": {"content": json.dumps(answer)}, **overrides}
        with patch("ollama_local.build_opener") as opener:
            opener.return_value.open.return_value = io.StringIO(json.dumps(response))
            return ask("test", "Compute capacity", {"count": 7},
                       {"expected_total_litres": {"type": "integer"}})

    def test_integer_result_accepted(self):
        answer, _ = self.request({"expected_total_litres": 840})
        self.assertEqual(answer["expected_total_litres"], 840)

    def test_boolean_is_not_integer_evidence(self):
        with self.assertRaises(ValueError):
            self.request({"expected_total_litres": True})

    def test_missing_extra_and_string_fields_rejected(self):
        for answer in ({}, {"expected_total_litres": 840, "valid": False},
                       {"expected_total_litres": "840"}):
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                self.request(answer)

    def test_incomplete_responses_rejected(self):
        for overrides in ({"done": False}, {"done_reason": "length"}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.request({"expected_total_litres": 840}, **overrides)

    def test_seed_and_temperature_reach_request_and_audit(self):
        response = {"done": True, "message": {"content": '{"value": 7}'}}
        with patch("ollama_local.build_opener") as opener:
            opener.return_value.open.return_value = io.StringIO(json.dumps(response))
            _, record = ask("test", "test", {}, {"value": {"type": "integer"}}, seed=29, temperature=0.2)
            request = opener.return_value.open.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["options"]["seed"], 29)
        self.assertEqual(payload["options"]["temperature"], 0.2)
        self.assertEqual(record["generation_options"], payload["options"])

    def test_choice_outside_source_derived_enum_is_rejected(self):
        response = {"done": True, "message": {"content": '{"answer": "No"}'}}
        with patch("ollama_local.build_opener") as opener:
            opener.return_value.open.return_value = io.StringIO(json.dumps(response))
            with self.assertRaises(ValueError):
                ask("test", "test", {}, {"answer": {"type": "string", "enum": ["", "ready", "locked"]}})


if __name__ == "__main__":
    unittest.main()
