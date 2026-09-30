import io
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import hive
import replication as r


class ReplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = self.root / 'replica'
        self.store.mkdir()
        self.db = self.root / 'memory.sqlite3'
        hive.initialize(self.db)
        self.add()
        self.number = 0
        self.identity = 'test-primary'

    def add(self):
        hive.append(self.db, 'run', 'test', 'observation', {'value': 'one'})

    def package(self, identity=None):
        self.number += 1
        path = self.root / f'package-{self.number}'
        r.snapshot(self.db, path, identity or self.identity)
        return path

    def wire(self, package):
        stream = io.BytesIO()
        r.send(package, stream)
        stream.seek(0)
        return stream

    def accept(self, package, **kwargs):
        return r.accept(self.store, self.identity, self.wire(package), reserve=0, **kwargs)

    def rewrite(self, package, query):
        dbpath = package / 'knowledge.sqlite3'
        with sqlite3.connect(dbpath) as db:
            sql = db.execute("SELECT sql FROM sqlite_master WHERE name='no_update'").fetchone()[0]
            db.execute('DROP TRIGGER no_update')
            db.execute(query)
            db.execute(sql)
        (package / 'manifest.json').write_bytes(r.canonical(r.manifest_for(dbpath, self.identity)))

    def test_valid_extension_and_idempotent_retry(self):
        p = self.package()
        self.assertEqual(self.accept(p)['status'], 'accepted')
        self.assertEqual(self.accept(p)['status'], 'unchanged')
        self.add()
        m = self.accept(self.package())['manifest']
        self.assertEqual(m['event_count'], 2)
        self.assertEqual(len(list((self.store / 'generations').iterdir())), 2)

    def test_retains_three_after_five_accepts(self):
        for _ in range(5):
            self.accept(self.package())
            self.add()
        counts = sorted(r.validate(p, self.identity)['event_count'] for p in (self.store / 'generations').iterdir())
        self.assertEqual(counts, [3, 4, 5])

    def test_truncated_transfer_preserves_current(self):
        p = self.package()
        self.accept(p)
        pointer = (self.store / 'current').read_bytes()
        with self.assertRaises(ValueError):
            r.accept(self.store, self.identity, io.BytesIO(self.wire(p).getvalue()[:-10]), reserve=0)
        self.assertEqual((self.store / 'current').read_bytes(), pointer)
        self.assertFalse(list(self.store.glob('.incoming-*')))

    def test_corruption_and_trailing_bytes_rejected(self):
        p = self.package()
        data = bytearray(self.wire(p).getvalue())
        data[-1] ^= 1
        for body in [data, self.wire(p).getvalue() + b'extra']:
            with self.subTest(body_length=len(body)), self.assertRaises((ValueError, sqlite3.Error)):
                r.accept(self.store, self.identity, io.BytesIO(body), reserve=0)
        self.assertFalse((self.store / 'current').exists())

    def test_valid_hash_cannot_hide_history_rewrite(self):
        self.accept(self.package())
        p = self.package()
        self.rewrite(p, "UPDATE events SET cookie='different' WHERE sequence=1")
        with self.assertRaisesRegex(ValueError, 'History rewrite'):
            self.accept(p)

    def test_reordered_events_rejected_even_with_recomputed_chain(self):
        self.add()
        self.accept(self.package())
        p = self.package()
        with sqlite3.connect(p / 'knowledge.sqlite3') as db:
            sql = db.execute("SELECT sql FROM sqlite_master WHERE name='no_update'").fetchone()[0]
            db.execute('DROP TRIGGER no_update')
            db.execute('UPDATE events SET sequence=3 WHERE sequence=1')
            db.execute('UPDATE events SET sequence=1 WHERE sequence=2')
            db.execute('UPDATE events SET sequence=2 WHERE sequence=3')
            db.execute(sql)
        (p / 'manifest.json').write_bytes(r.canonical(r.manifest_for(p / 'knowledge.sqlite3', self.identity)))
        with self.assertRaisesRegex(ValueError, 'History rewrite'):
            self.accept(p)

    def test_deleted_tail_with_recomputed_manifest_rejected(self):
        self.add()
        self.accept(self.package())
        p = self.package()
        with sqlite3.connect(p / 'knowledge.sqlite3') as db:
            sql = db.execute("SELECT sql FROM sqlite_master WHERE name='no_delete'").fetchone()[0]
            db.execute('DROP TRIGGER no_delete')
            db.execute('DELETE FROM events WHERE sequence=2')
            db.execute("UPDATE sqlite_sequence SET seq=1 WHERE name='events'")
            db.execute(sql)
        (p / 'manifest.json').write_bytes(r.canonical(r.manifest_for(p / 'knowledge.sqlite3', self.identity)))
        with self.assertRaisesRegex(ValueError, 'rollback'):
            self.accept(p)

    def test_gap_rejected(self):
        p = self.package()
        with sqlite3.connect(p / 'knowledge.sqlite3') as db:
            db.execute('DROP TRIGGER no_update')
            db.execute('UPDATE events SET sequence=2')
            db.execute("CREATE TRIGGER no_update BEFORE UPDATE ON events BEGIN SELECT RAISE(ABORT, 'memory events are append-only'); END")
        with self.assertRaisesRegex(ValueError, 'sequence gap'):
            r.inspect(p / 'knowledge.sqlite3')

    def test_rollback_rejected(self):
        old = self.package()
        self.accept(old)
        self.add()
        self.accept(self.package())
        with self.assertRaisesRegex(ValueError, 'rollback'):
            self.accept(old)

    def test_other_primary_rejected(self):
        with self.assertRaisesRegex(ValueError, 'identity'):
            self.accept(self.package('different-primary'))

    def test_source_text_and_hash_checked(self):
        hive.append(self.db, 'run', 'test', 'source_ingested', {'text': 'entire source', 'sha256': 'wrong'})
        with self.assertRaisesRegex(ValueError, 'Source snapshot hash'):
            self.package()

    def test_disk_budget_failure_does_not_prune(self):
        p = self.package()
        self.accept(p)
        pointer = (self.store / 'current').read_bytes()
        with self.assertRaisesRegex(ValueError, 'budget'):
            self.accept(p, budget=1)
        self.assertEqual((self.store / 'current').read_bytes(), pointer)
        self.assertEqual(len(list((self.store / 'generations').iterdir())), 1)

    def test_free_space_reserve(self):
        p = self.package()
        with self.assertRaisesRegex(ValueError, 'reserve'):
            r.accept(self.store, self.identity, self.wire(p), reserve=10**20)
        self.assertFalse((self.store / 'current').exists())

    def test_failed_publication_keeps_old_and_retry_succeeds(self):
        self.accept(self.package())
        pointer = (self.store / 'current').read_bytes()
        self.add()
        p = self.package()
        with patch('replication.os.replace', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                self.accept(p)
        self.assertEqual((self.store / 'current').read_bytes(), pointer)
        self.assertEqual(self.accept(p)['status'], 'accepted')

    def test_damaged_retained_generation_blocks_sync(self):
        self.accept(self.package())
        folder, _ = r.current(self.store, self.identity)
        (folder / 'manifest.json').write_text('{}')
        with self.assertRaises(ValueError):
            self.accept(self.package())

    def test_missing_pointer_cannot_reset_history(self):
        self.accept(self.package())
        (self.store / 'current').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing current'):
            self.accept(self.package())

    def test_restore_requires_exact_expected_checkpoint_and_preserves_bytes(self):
        package = self.package()
        expected = r.validate(package, self.identity)
        destination = self.root / 'restored.sqlite3'
        config = {'database_id': self.identity, 'remote': 'test', 'key': 'unused'}
        def remote(*args, **kwargs):
            r.send(package, kwargs['stdout'])
        with patch('replication.subprocess.run', side_effect=remote):
            bad = {**expected, 'chain_head': 'f' * 64}
            with self.assertRaisesRegex(ValueError, 'expected checkpoint'):
                r.restore(config, destination, bad)
            self.assertFalse(destination.exists())
            r.restore(config, destination, expected)
        self.assertEqual(destination.read_bytes(), (package / 'knowledge.sqlite3').read_bytes())
        self.assertEqual(r.inspect(destination), r.inspect(package / 'knowledge.sqlite3'))
        with self.assertRaisesRegex(ValueError, 'already exist'):
            r.restore(config, destination, expected)

    def test_unknown_ssh_command_rejected(self):
        with patch.dict('os.environ', {'SSH_ORIGINAL_COMMAND': 'sh -c id'}):
            with self.assertRaisesRegex(ValueError, 'not permitted'):
                r.serve({'store': str(self.store), 'database_id': self.identity})
        import signal
        signal.alarm(0)


if __name__ == '__main__':
    unittest.main()
