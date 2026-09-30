import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import hive
import knowledge


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "memory.sqlite3"
        self.source = self.root / "notes.md"
        self.source.write_text("# Observations\n\nThe measured reservoir capacity is 37 litres.\n")
        self.ingested = knowledge.ingest(self.db, self.source)
        support = patch("knowledge.support_review", return_value=({"outcome": "answered", "answer": "37 litres"}, {}))
        self.support = support.start()
        self.addCleanup(support.stop)

    def selection(self, quote="The measured reservoir capacity is 37 litres."):
        chunk = knowledge.search(self.db, "reservoir capacity")["candidates"][0]
        return {"outcome": "answered", "answer": "37 litres", "chunk_id": chunk["chunk_id"], "quote": quote}, {}

    def test_independent_process_can_retrieve_previous_ingestion(self):
        run = subprocess.run([sys.executable, str(Path(knowledge.__file__)), "--db", str(self.db),
                              "search", "reservoir capacity"], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(run.stdout)["candidates"][0]["source_id"], self.ingested["source_id"])

    def test_exact_quote_has_correct_citation_and_separate_task(self):
        with patch("knowledge.ask", return_value=self.selection()):
            first = knowledge.answer_question(self.db, "reservoir capacity", "test")
            second = knowledge.answer_question(self.db, "reservoir capacity", "test")
        self.assertNotEqual(first["task_id"], second["task_id"])
        self.assertEqual(first["status"], "supported_answer")
        self.assertEqual(first["citation"]["line"], 3)
        self.assertEqual(first["citation"]["source_id"], self.ingested["source_id"])
        with hive.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='working_knowledge'").fetchone()[0], 0)

    def test_fabricated_quote_is_withheld(self):
        with patch("knowledge.ask", return_value=self.selection("The reservoir capacity is 900 litres.")):
            result = knowledge.answer_question(self.db, "reservoir capacity", "test")
        self.assertEqual(result["status"], "unsupported_output")
        self.assertNotIn("quote", result)

    def test_wrong_chunk_id_is_withheld(self):
        with patch("knowledge.ask", return_value=({"outcome": "answered", "answer": "37 litres", "chunk_id": "invented", "quote": "37 litres"}, {})):
            result = knowledge.answer_question(self.db, "reservoir capacity", "test")
        self.assertEqual(result["status"], "unsupported_output")

    def test_stale_source_excluded_until_reingested(self):
        self.source.write_text("The measured reservoir capacity is 41 litres.\n")
        found = knowledge.search(self.db, "reservoir capacity")
        self.assertFalse(found["candidates"])
        self.assertEqual(found["excluded_sources"][0]["reason"], "changed_since_ingestion")
        newer = knowledge.ingest(self.db, self.source)
        self.assertNotEqual(newer["source_id"], self.ingested["source_id"])
        self.assertIn("41 litres", knowledge.search(self.db, "reservoir capacity")["candidates"][0]["text"])
        with hive.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='source_ingested'").fetchone()[0], 2)

    def test_source_changed_during_model_call_withholds_quote(self):
        selected = self.selection()
        def change_source(*args, **kwargs):
            self.source.write_text("Changed during inference")
            return selected
        with patch("knowledge.ask", side_effect=change_source):
            result = knowledge.answer_question(self.db, "reservoir capacity", "test")
        self.assertEqual(result["status"], "stale_source")

    def test_missing_source_is_excluded(self):
        self.source.unlink()
        self.assertEqual(knowledge.search(self.db, "reservoir")["excluded_sources"][0]["reason"], "unavailable")

    def test_duplicate_ingestion_does_not_duplicate_memory(self):
        self.assertEqual(knowledge.ingest(self.db, self.source)["status"], "already_ingested")

    def test_no_keyword_match_cannot_produce_unconfirmed_finding(self):
        with patch("knowledge.ask") as model:
            result = knowledge.answer_question(self.db, "penguin", "test")
        model.assert_not_called()
        self.assertEqual(result["status"], "needs_review")
        self.assertNotIn("finding_id", result)

    def test_empty_retrieval_cli_requires_review(self):
        run = subprocess.run([sys.executable, str(Path(knowledge.__file__)), "--db", str(self.db),
                              "ask", "penguin", "--model", "test"], capture_output=True, text=True)
        self.assertEqual(run.returncode, 3)
        result = json.loads(run.stdout)
        self.assertEqual(result["status"], "needs_review")
        self.assertNotIn("finding_id", result)

    def test_model_can_abstain_on_irrelevant_keyword_match(self):
        self.support.return_value = ({"outcome": "not_found_in_source", "answer": ""}, {})
        with patch("knowledge.ask", return_value=({"outcome": "not_found_in_source", "answer": "", "chunk_id": "", "quote": ""}, {})):
            result = knowledge.answer_question(self.db, "reservoir temperature", "test")
        self.assertEqual(result["status"], "not_found_in_source")
        with hive.connect(self.db) as db:
            finding = json.loads(db.execute("SELECT payload FROM events WHERE id=?", (result["finding_id"],)).fetchone()[0])
        self.assertEqual(finding["reason"], "solver_not_found_in_source")
        self.support.assert_called_once()

    def test_support_abstention_withholds_valid_quote(self):
        self.support.return_value = ({"outcome": "not_found_in_source", "answer": ""}, {})
        with patch("knowledge.ask", return_value=self.selection()):
            result = knowledge.answer_question(self.db, "Who manufactured the reservoir?", "test")
        self.assertEqual(result["status"], "needs_review")
        for key in ("answer", "quote", "citation"):
            self.assertNotIn(key, result)
        with hive.connect(self.db) as db:
            count = db.execute("SELECT COUNT(*) FROM events WHERE run_id=? AND kind='source_finding'", (result["task_id"],)).fetchone()[0]
        self.assertEqual(count, 0)

    def test_explicit_abstention_with_metadata_is_recorded_without_citation(self):
        self.support.return_value = ({"outcome": "not_found_in_source", "answer": ""}, {})
        raw, _ = self.selection()
        raw.update(outcome="not_found_in_source", answer="")
        with patch("knowledge.ask", return_value=(raw, {})):
            result = knowledge.answer_question(self.db, "reservoir temperature", "test")
        self.assertEqual(result["status"], "not_found_in_source")
        self.assertTrue(result["finding_id"])
        self.assertTrue(result["normalization_id"])
        self.support.assert_called_once()
        for key in ("answer", "quote", "citation"):
            self.assertNotIn(key, result)
        with hive.connect(self.db) as db:
            proposal = json.loads(db.execute("SELECT payload FROM events WHERE run_id=? AND kind='source_proposal'", (result["task_id"],)).fetchone()[0])
        self.assertEqual(proposal, raw)

    def test_not_found_with_nonempty_answer_remains_invalid(self):
        raw, _ = self.selection()
        raw["outcome"] = "not_found_in_source"
        with patch("knowledge.ask", return_value=(raw, {})):
            result = knowledge.answer_question(self.db, "reservoir temperature", "test")
        self.assertEqual(result["status"], "unsupported_output")
        self.assertNotIn("finding_id", result)

    def test_abstention_metadata_cannot_create_fake_source_citation(self):
        self.support.return_value = ({"outcome": "not_found_in_source", "answer": ""}, {})
        raw = {"outcome": "not_found_in_source", "answer": "", "chunk_id": "invented", "quote": "Imaginary source"}
        with patch("knowledge.ask", return_value=(raw, {})):
            result = knowledge.answer_question(self.db, "reservoir temperature", "test")
        self.assertEqual(result["status"], "not_found_in_source")
        self.assertNotIn("citation", result)
        with hive.connect(self.db) as db:
            finding = json.loads(db.execute("SELECT payload FROM events WHERE id=?", (result["finding_id"],)).fetchone()[0])
        self.assertNotIn("invented", finding["searched_chunk_ids"])

    def test_disagreement_withholds_answer(self):
        self.support.return_value = ({"outcome": "answered", "answer": "reservoir"}, {})
        with patch("knowledge.ask", return_value=self.selection()):
            result = knowledge.answer_question(self.db, "reservoir capacity", "test")
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["checks"]["answers_agree"])

    def test_shared_hallucinated_value_is_not_anchored(self):
        selection, _ = self.selection()
        selection["answer"] = "900 litres"
        self.support.return_value = ({"outcome": "answered", "answer": "900 litres"}, {})
        with patch("knowledge.ask", return_value=(selection, {})):
            result = knowledge.answer_question(self.db, "reservoir capacity", "test")
        self.assertEqual(result["status"], "needs_review")
        self.assertFalse(result["checks"]["solver_answer_anchored"])

    def test_anchor_values_and_boundaries(self):
        for answer, quote, expected in [
            ("Ann", "Anna built it.", False), ("Ann", "Ann built it.", True),
            ("37", "Capacity 137 litres.", False), ("37", "Capacity 37 litres.", True),
            ("37", "Value -37.", False), ("37", "Value 37.5.", False),
            ("37", "Value 37,500.", False), ("37", "Value 37.", True),
            ("2026-09-25", "Date: 2026-09-25.", True),
            ("2026-09-24", "Date: 2026-09-25.", False),
        ]:
            with self.subTest(answer=answer, quote=quote):
                self.assertEqual(knowledge.anchored(answer, quote), expected)

    def test_support_failure_withholds_answer(self):
        self.support.side_effect = RuntimeError("unavailable")
        with patch("knowledge.ask", return_value=self.selection()):
            result = knowledge.answer_question(self.db, "reservoir capacity", "test")
        self.assertEqual(result["status"], "needs_review")

    def test_support_gets_only_question_and_quote_as_context(self):
        import support_cookie
        with patch("support_cookie.ask", return_value=({}, {})) as model:
            support_cookie.review("Who built it?", "Ann built it.", "test", 11, 0.2)
        self.assertEqual(model.call_args.args[2], {"question": "Who built it?", "quote": "Ann built it."})
        self.assertEqual(model.call_args.kwargs, {"seed": 11, "temperature": 0.2})

    def test_answerable_question_with_malformed_solver_output_is_not_not_found(self):
        for raw in ({"outcome": "not_found_in_source"},
                    {"outcome": "answered", "answer": "", "chunk_id": "", "quote": ""}):
            with self.subTest(raw=raw), patch("knowledge.ask", return_value=(raw, {})):
                result = knowledge.answer_question(self.db, "What is the reservoir capacity?", "test")
            self.assertEqual(result["status"], "unsupported_output")
            self.assertNotIn("finding_id", result)
        with hive.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events WHERE kind='source_finding'").fetchone()[0], 0)

    def test_support_finds_answer_after_false_solver_abstention(self):
        raw = {"outcome": "not_found_in_source", "answer": "", "chunk_id": "bad metadata", "quote": ""}
        with patch("knowledge.ask", return_value=(raw, {})):
            result = knowledge.answer_question(self.db, "What is the reservoir capacity?", "test")
        self.assertEqual(result["status"], "needs_review")
        self.assertNotIn("finding_id", result)
        self.assertNotIn("answer", result)
        context_args = self.support.call_args.args
        self.assertIn("37 litres", context_args[1])
        self.assertNotIn("bad metadata", context_args[1])

    def test_support_failure_prevents_negative_finding(self):
        self.support.side_effect = RuntimeError("unavailable")
        with patch("knowledge.ask", return_value=({"outcome": "not_found_in_source", "answer": "", "chunk_id": "", "quote": ""}, {})):
            result = knowledge.answer_question(self.db, "reservoir temperature", "test")
        self.assertEqual(result["status"], "needs_review")
        self.assertNotIn("finding_id", result)

    def test_changed_source_prevents_negative_finding(self):
        def change(*args):
            self.source.write_text("New source includes the answer")
            return {"outcome": "not_found_in_source", "answer": ""}, {}
        self.support.side_effect = change
        with patch("knowledge.ask", return_value=({"outcome": "not_found_in_source", "answer": "", "chunk_id": "", "quote": ""}, {})):
            result = knowledge.answer_question(self.db, "reservoir temperature", "test")
        self.assertEqual(result["status"], "needs_review")
        self.assertNotIn("finding_id", result)

    def test_negative_finding_links_independent_confirmation(self):
        self.support.return_value = ({"outcome": "not_found_in_source", "answer": ""}, {})
        with patch("knowledge.ask", return_value=({"outcome": "not_found_in_source", "answer": "", "chunk_id": "", "quote": ""}, {})):
            result = knowledge.answer_question(self.db, "reservoir temperature", "test")
        with hive.connect(self.db) as db:
            finding = json.loads(db.execute("SELECT payload FROM events WHERE id=?", (result["finding_id"],)).fetchone()[0])
            confirmation = db.execute("SELECT cookie,payload FROM events WHERE id=?", (finding["confirmation_id"],)).fetchone()
        self.assertEqual(confirmation["cookie"], "cookie-support")
        context = json.loads(confirmation["payload"])["context"]
        self.assertEqual(set(context), {"question", "quote"})
        self.assertNotIn("not_found_in_source", context["quote"])


if __name__ == "__main__":
    unittest.main()
