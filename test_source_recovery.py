import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import hive
import knowledge
import source_recovery as r


class SourceRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.db = self.base / 'memory.sqlite3'
        self.source = self.base / 'original.md'
        self.source.write_bytes(b'Reservoir capacity is 37 litres.\r\n')
        self.sid = knowledge.ingest(self.db, self.source)['source_id']
        self.root = self.base / 'recovered'

    def target(self):
        return self.root / 'sources' / self.sid / 'source.md'

    def test_recreates_exact_bytes_without_rewriting_history(self):
        original = self.source.read_bytes()
        self.source.unlink()
        with hive.connect(self.db) as db:
            before = [tuple(row) for row in db.execute('SELECT * FROM events ORDER BY sequence')]
        r.recover(self.db, self.root)
        self.assertEqual(self.target().read_bytes(), original)
        with hive.connect(self.db) as db:
            after = [tuple(row) for row in db.execute('SELECT * FROM events ORDER BY sequence')]
        self.assertEqual(before, after)
        found = knowledge.search(self.db, 'reservoir capacity', recovery_root=self.root)
        self.assertEqual(found['candidates'][0]['source_id'], self.sid)
        self.assertEqual(found['candidates'][0]['path'], str(self.target()))
        self.assertEqual(found['candidates'][0]['original_path'], str(self.source))

    def test_latest_only_and_corrupt_latest_does_not_fall_back(self):
        self.source.write_text('Reservoir capacity is 42 litres.')
        latest = knowledge.ingest(self.db, self.source)['source_id']
        m = r.recover(self.db, self.root)
        self.assertEqual(set(m['sources']), {latest})
        self.assertFalse(self.target().exists())
        snapshot = knowledge.latest_sources(self.db)[0]
        hive.append(self.db, 'bad', 'test', 'source_ingested', {**snapshot, 'text': 'corrupted'})
        with self.assertRaisesRegex(ValueError, 'snapshot hash'):
            r.recover(self.db, self.base / 'another')

    def test_existing_identical_file_reused_and_conflict_untouched(self):
        r.recover(self.db, self.root)
        inode = self.target().stat().st_ino
        r.recover(self.db, self.root)
        self.assertEqual(self.target().stat().st_ino, inode)
        self.target().write_text('different')
        with self.assertRaises(ValueError):
            r.recover(self.db, self.root)
        self.assertEqual(self.target().read_text(), 'different')

    def test_file_symlink_and_parent_symlink_refused(self):
        self.target().parent.mkdir(parents=True)
        self.target().symlink_to(self.source)
        with self.assertRaises(OSError):
            r.recover(self.db, self.root)
        self.assertTrue(self.target().is_symlink())
        self.target().unlink(); self.target().parent.rmdir()
        self.target().parent.symlink_to(self.base, target_is_directory=True)
        with self.assertRaises(OSError):
            r.recover(self.db, self.root)
        self.assertFalse((self.base / 'source.md').exists())

    def test_directory_at_file_path_refused(self):
        self.target().mkdir(parents=True)
        with self.assertRaises((ValueError, OSError)):
            r.recover(self.db, self.root)
        self.assertTrue(self.target().is_dir())

    def test_manifest_path_escape_refused(self):
        r.recover(self.db, self.root)
        p = self.root / r.MANIFEST
        m = json.loads(p.read_text()); m['sources'][self.sid]['path'] = str(self.source)
        p.write_text(json.dumps(m))
        result = knowledge.answer_question(self.db, 'reservoir capacity', 'test', recovery_root=self.root)
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(result['reason'], 'invalid_source_recovery')

    def test_missing_map_never_falls_back_to_existing_original(self):
        with patch('knowledge.ask') as model:
            result = knowledge.answer_question(self.db, 'reservoir capacity', 'test', recovery_root=self.root)
        self.assertEqual(result['status'], 'needs_review')
        model.assert_not_called()

    def test_missing_modified_and_symlink_recovered_file_excluded(self):
        r.recover(self.db, self.root)
        for change in ('missing', 'modified', 'symlink'):
            if self.target().exists() or self.target().is_symlink(): self.target().unlink()
            if change == 'modified': self.target().write_text('Reservoir capacity is 99 litres.')
            if change == 'symlink': self.target().symlink_to(self.source)
            with self.subTest(change=change):
                found = knowledge.search(self.db, 'reservoir capacity', recovery_root=self.root)
                self.assertEqual(found['candidates'], [])
                self.assertEqual(len(found['excluded_sources']), 1)

    def test_interruption_leaves_no_manifest_and_retry_succeeds(self):
        original_publish = r.publish
        def interrupt(fd, name, raw):
            if name == r.MANIFEST: raise OSError('interrupted')
            return original_publish(fd, name, raw)
        with patch('source_recovery.publish', side_effect=interrupt):
            with self.assertRaises(OSError): r.recover(self.db, self.root)
        self.assertFalse((self.root / r.MANIFEST).exists())
        r.recover(self.db, self.root)
        self.assertTrue((self.root / r.MANIFEST).exists())

    def test_concurrent_file_creation_is_not_overwritten(self):
        real_link = r.os.link
        def race(src, dst, **kwargs):
            with r.os.fdopen(r.os.open(dst, r.os.O_WRONLY | r.os.O_CREAT | r.os.O_EXCL,
                                     0o600, dir_fd=kwargs['dst_dir_fd']), 'wb') as f:
                f.write(b'raced')
            return real_link(src, dst, **kwargs)
        with patch('source_recovery.os.link', side_effect=race):
            with self.assertRaises(ValueError): r.recover(self.db, self.root)
        self.assertEqual(self.target().read_bytes(), b'raced')
        self.assertFalse((self.root / r.MANIFEST).exists())

    def test_post_inference_freshness_uses_recovered_path(self):
        r.recover(self.db, self.root)
        chunk = knowledge.search(self.db, 'reservoir capacity', recovery_root=self.root)['candidates'][0]
        answer = {'outcome': 'answered', 'answer': '37 litres', 'chunk_id': chunk['chunk_id'], 'quote': 'Reservoir capacity is 37 litres.'}
        def support(*args):
            self.target().write_text('changed during inference')
            return {'outcome': 'answered', 'answer': '37 litres'}, {}
        with patch('knowledge.ask', return_value=(answer, {})), patch('knowledge.support_review', side_effect=support):
            result = knowledge.answer_question(self.db, 'reservoir capacity', 'test', recovery_root=self.root)
        self.assertEqual(result['status'], 'stale_source')
        self.assertNotIn('answer', result)

    def test_absence_freshness_uses_recovered_path(self):
        r.recover(self.db, self.root)
        absent = {'outcome': 'not_found_in_source', 'answer': '', 'chunk_id': '', 'quote': ''}
        def support(*args):
            self.target().unlink()
            return {'outcome': 'not_found_in_source', 'answer': ''}, {}
        with patch('knowledge.ask', return_value=(absent, {})), patch('knowledge.support_review', side_effect=support):
            result = knowledge.answer_question(self.db, 'Who manufactured the reservoir?', 'test', recovery_root=self.root)
        self.assertEqual(result['status'], 'needs_review')
        self.assertNotIn('finding_id', result)


if __name__ == '__main__':
    unittest.main()
