"""Offline tests: no CT contact, model calls, production memory or real signing key."""
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import recovery_drill as d
import build_recovery_drill as builder
import recovery_drill_worker as worker
import replication as r
import hive, knowledge


class DrillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.kit = self.root/'kit'; self.kit.mkdir()
        for name in d.TOOLS:
            if name == 'allowed_signers':(self.kit/name).write_text('test public trust only\n')
            else:shutil.copyfile(Path(d.__file__).parent/name, self.kit/name)
        self.hashes = {name: d.sha(self.kit/name) for name in d.TOOLS}
        self.baseline = {'format': 1, 'checkpoint': d.CHECKPOINT, 'release': {'sequence': 2, 'manifest_sha256': d.RELEASE, 'commit': d.COMMIT},
                         'criteria': d.CRITERIA, 'model': d.MODEL, 'tools': self.hashes,
                         'review': {'status': 'approved', 'reviewer': 'Claude', 'tools': self.hashes}, 'pin_sequence': 0,
                         'known_host': 'replica-host ssh-ed25519 fixture\n'}
        self.write_baseline()

    def write_baseline(self):
        (self.kit/'baseline.json').write_bytes(d.canonical(self.baseline))
        self.phone = d.sha(self.kit/'baseline.json')

    def trials(self, verdict='correct'):
        return [{'seed': seed, 'question': case[0], 'verdict': verdict} for seed in d.CRITERIA['seeds'] for case in d.CASES]

    def test_phone_and_tools_and_review_are_all_required(self):
        self.assertEqual(d.verify_kit(self.kit, self.phone)['checkpoint'], d.CHECKPOINT)
        with self.assertRaisesRegex(ValueError, 'phone'):d.verify_kit(self.kit, '0'*64)
        for name in d.TOOLS:
            original = (self.kit/name).read_bytes(); (self.kit/name).write_bytes(original+b'changed')
            with self.subTest(tool=name), self.assertRaisesRegex(ValueError, 'tool hash'):d.verify_kit(self.kit, self.phone)
            (self.kit/name).write_bytes(original)
        self.baseline['review']['status'] = 'pending'; self.write_baseline()
        with self.assertRaisesRegex(ValueError, 'review still pending'):d.verify_kit(self.kit, self.phone)
        self.baseline['review'] = {'status': 'approved', 'reviewer': 'Claude', 'tools': {}}; self.write_baseline()
        with self.assertRaisesRegex(ValueError, 'Review does not bind'):d.verify_kit(self.kit, self.phone)

    def test_changed_criteria_or_checkpoint_refused_even_with_new_phone_hash(self):
        self.baseline['checkpoint'] = {**d.CHECKPOINT, 'event_count': 27}; self.write_baseline()
        with self.assertRaisesRegex(ValueError, 'checkpoint'):d.verify_kit(self.kit, self.phone)
        self.baseline['checkpoint'] = d.CHECKPOINT
        self.baseline['criteria'] = {**d.CRITERIA, 'quality_target_correct': 7}; self.write_baseline()
        with self.assertRaisesRegex(ValueError, 'Criteria'):d.verify_kit(self.kit, self.phone)

    def test_quality_is_separate_and_all_nine_unique_trials_required(self):
        summary = d.quality_summary(self.trials(), True)
        self.assertTrue(summary['target_pass'])
        self.assertEqual(summary['correct_positive'], 6); self.assertEqual(summary['confirmed_absence'], 3)
        rows = self.trials('abstention'); summary = d.quality_summary(rows, True)
        self.assertTrue(summary['safety_pass']); self.assertFalse(summary['target_pass'])
        for verdict in ('false_accept', 'error'):
            rows = self.trials(); rows[0]['verdict'] = verdict
            self.assertFalse(d.quality_summary(rows, True)['safety_pass'])
        self.assertFalse(d.quality_summary(self.trials()[:-1], True)['safety_pass'])
        self.assertFalse(d.quality_summary([self.trials()[0]]*9, True)['safety_pass'])
        self.assertFalse(d.quality_summary(self.trials(), False)['safety_pass'])

    def test_all_remote_commands_are_read_only_and_fixed_host(self):
        for command in ('status', 'code-status', 'fetch '+d.CHECKPOINT['sha256'], 'code-fetch '+d.RELEASE+' manifest.json'):
            args = d.ssh_args(self.root/'key', self.root/'hosts', command)
            self.assertEqual(args[-2], 'hive-recovery@replica-host')
            self.assertNotIn('IdentityAgent=none', args)
            for setting in ('IdentitiesOnly=yes', 'BatchMode=yes', 'ForwardAgent=no', 'StrictHostKeyChecking=yes', 'HostKeyAlgorithms=ssh-ed25519'):
                self.assertIn(setting, args)
            self.assertIn('-i', args); self.assertIn('GlobalKnownHostsFile=/dev/null', args)
        for command in ('pin', 'push', 'sh', 'code-submit', 'fetch', 'code-fetch ../../etc/passwd manifest.json'):
            with self.subTest(command=command), self.assertRaises(ValueError):d.ssh_args('key', 'hosts', command)

    def test_failed_preflight_is_sealed_and_rerun_cannot_overwrite(self):
        with patch.object(d.os, 'geteuid', return_value=1000), patch.object(d, 'fetch') as fetch, patch.object(d, 'helper') as helper:
            result = d.run(self.kit, '0'*64, 'absent-receipt', 'key', self.root/'runs', True, 'first-failure')
            self.assertFalse(result['pin_eligible']); fetch.assert_not_called(); helper.assert_not_called()
            saved = (self.root/'runs/first-failure/report.json').read_bytes()
            with self.assertRaises(FileExistsError):d.run(self.kit, self.phone, 'absent', 'key', self.root/'runs', True, 'first-failure')
            self.assertEqual(saved, (self.root/'runs/first-failure/report.json').read_bytes())
            second = d.run(self.kit, '0'*64, 'absent', 'key', self.root/'runs', True, 'second-failure')
            self.assertEqual(second['status'], 'failed')
        self.assertTrue((self.root/'runs/first-failure/evidence-index.json').exists())
        with self.assertRaises(ValueError):d.prepare_pin(self.root/'runs/first-failure', self.root/'pin.json')

    def test_mac_off_and_nonroot_required_before_run_creation(self):
        with self.assertRaisesRegex(ValueError, 'Mac is off'):d.run('', '', '', '', self.root/'runs', False)
        with patch.object(d.os, 'geteuid', return_value=0), self.assertRaisesRegex(ValueError, 'never root'):
            d.run('', '', '', '', self.root/'runs', True)
        self.assertFalse((self.root/'runs').exists())

    def successful_evidence(self, name='evidence', verdict='correct'):
        root = d.new_run(self.root, name)
        shutil.copyfile(self.kit/'baseline.json', root/'baseline.json')
        d.save(root/'quality.json', {'trials': self.trials(verdict), 'preflight_ok': True})
        d.save(root/'report.json', {'status': 'completed', 'integrity': 'passed', 'unit_tests': 'passed', 'pristine_final': 'passed', 'pin_eligible': True, 'baseline_sha256': self.phone})
        d.seal(root)
        return root

    def test_pin_binds_sealed_evidence_and_is_only_unsigned_output(self):
        root = self.successful_evidence(verdict='abstention')
        before = d.inventory(root); pin = d.prepare_pin(root, self.root/'pin.json')
        self.assertEqual(pin, {'project': 'aster-hive', 'action': 'recovery-tested', 'sequence': 1, 'release': d.RELEASE, 'drill_sha256': d.sha(root/'evidence-index.json')})
        self.assertEqual(before, d.inventory(root))
        with self.assertRaises(FileExistsError):d.prepare_pin(root, self.root/'pin.json')
        with self.assertRaisesRegex(ValueError, 'outside sealed'):d.prepare_pin(root, root/'pin.json')
        (root/'quality.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'evidence changed'):d.prepare_pin(root, self.root/'other-pin.json')

    def test_sealed_false_accept_cannot_be_pinned_even_if_report_claims_success(self):
        root = self.successful_evidence(verdict='false_accept')
        with self.assertRaisesRegex(ValueError, 'safety gate'):d.prepare_pin(root, self.root/'pin.json')

    def test_source_inventory_does_not_modify_memory_or_read_original_source(self):
        source = self.root/'source.txt'; source.write_text('Immutable source fixture.')
        db = self.root/'memory.sqlite3'; knowledge.ingest(db, source)
        package = self.root/'package'; r.snapshot(db, package, 'test')
        pristine = package/'knowledge.sqlite3'; before = d.sha(pristine); source.unlink()
        rows = worker.source_rows(pristine)
        self.assertEqual(len(rows), 1); self.assertEqual(rows[0]['original_path'], str(source.resolve()))
        self.assertEqual(d.sha(pristine), before)

    def test_baseline_generator_rejects_wrong_snapshot_without_writing(self):
        source = self.root/'memory.sqlite3'; hive.initialize(source)
        package = self.root/'package'; r.snapshot(source, package, 'test')
        with patch.object(builder.sys, 'platform', 'darwin'), self.assertRaisesRegex(ValueError, 'Checkpoint differs'):
            builder.generate(package/'knowledge.sqlite3', 'missing', 'missing', '', 'missing', self.root/'out')
        self.assertFalse((self.root/'out').exists())


    def test_controller_verifies_release_before_workers_and_separates_quality(self):
        import test_code_recovery as fixtures
        import code_release as c
        f = fixtures.CodeTests(); f.setUp(); self.addCleanup(f.doCleanups)
        package = f.approval(2); release_hash = d.sha(package/'manifest.json')
        db = self.root/'fixture.sqlite3'; hive.initialize(db)
        snap = self.root/'snapshot'; manifest = r.snapshot(db, snap, 'test')
        self.baseline['release'] = {'sequence': 2, 'manifest_sha256': release_hash, 'commit': f.commit}
        self.baseline['checkpoint'] = manifest
        shutil.copyfile(f.signers, self.kit/'allowed_signers')
        self.hashes['allowed_signers'] = d.sha(self.kit/'allowed_signers'); self.write_baseline()
        receipt = self.root/'receipt.json'; d.save(receipt, {'sequence': 2, 'manifest_sha256': release_hash})
        def fetch(key, dest, command, label):
            target = dest/(label+'.stdout')
            if command == 'code-status':
                d.save(target, {'sequence': 2, 'current': release_hash, 'pin_sequence': 0, 'releases': {release_hash: {'commit': f.commit}}})
            elif command == 'status':d.save(target, {'read_only': True, 'manifest': manifest})
            elif command.startswith('code-fetch '):shutil.copyfile(package/command.split()[-1], target)
            else:
                with target.open('xb') as wire:r.send(snap, wire)
            return target
        invoked = []; corrupt_pristine = [False]
        def command(args, dest, label, **kwargs):
            invoked.append(label)
            if label in ('integrity-worker', 'quality-worker', 'unit-tests'):
                self.assertIn('-B', args); self.assertIn('-I', args)
            if label == 'integrity-worker':d.save(dest/'integrity.json', {'passed': True})
            if label == 'unit-tests':
                (dest/'unit-tests.stdout').write_text('')
                (dest/'unit-tests.stderr').write_text('Ran 212 tests in 1.0s\n\nOK\n')
            if label == 'quality-worker':
                d.save(dest/'quality.json', {'preflight_ok': True, 'trials': self.trials('abstention')})
                if corrupt_pristine[0]:(dest/'memory/knowledge.sqlite3').write_bytes(b'corruption')
            return 0
        with patch.object(d, 'RELEASE', release_hash), patch.object(d, 'COMMIT', f.commit), patch.object(d, 'CHECKPOINT', manifest), patch.object(d.os, 'geteuid', return_value=1000), patch.object(d, 'fetch', side_effect=fetch), patch.object(d, 'command', side_effect=command):
            report = d.run(self.kit, self.phone, receipt, 'key', self.root/'runs', True, 'synthetic-success')
            self.assertEqual(report['integrity'], 'passed'); self.assertEqual(report['unit_tests'], 'passed')
            self.assertTrue(report['pin_eligible']); self.assertFalse(report['quality']['target_pass'])
            self.assertEqual(invoked, ['clone', 'checkout', 'integrity-worker', 'unit-tests', 'quality-worker'])
            invoked.clear(); corrupt_pristine[0] = True
            report = d.run(self.kit, self.phone, receipt, 'key', self.root/'runs', True, 'pristine-corruption')
            self.assertEqual(report['integrity'], 'failed'); self.assertFalse(report['pin_eligible'])
            self.assertEqual(report['pristine_final'], 'failed')
            corrupt_pristine[0] = False
            invoked.clear(); (package/'manifest.sig').write_text('invalid signature')
            report = d.run(self.kit, self.phone, receipt, 'key', self.root/'runs', True, 'bad-signature')
            self.assertEqual(report['status'], 'failed'); self.assertFalse(report['pin_eligible']); self.assertEqual(invoked, [])

    def test_pin_upload_serialization_and_replay_against_existing_publisher(self):
        import types
        import test_code_recovery as fixtures
        import code_transport as transport
        import code_publisher as publisher
        import code_release as c
        f = fixtures.CodeTests(); f.setUp(); self.addCleanup(f.doCleanups)
        state = f.accept(f.approval(2)); pin = f.pin(state['current'])
        def remote(args, stdin, **kwargs):
            try:reply = {'ok': True, 'state': publisher.publish(f.config, stdin)}
            except ValueError as e:reply = {'ok': False, 'error': str(e)}
            return types.SimpleNamespace(stdout=c.canonical(reply))
        import subprocess
        real_run = subprocess.run
        def routed(args, **kwargs):
            return remote(args, **kwargs) if args[0] == 'ssh' else real_run(args, **kwargs)
        with patch.object(transport.subprocess, 'run', side_effect=routed):
            result = transport.upload({'key': 'fixture', 'remote': 'fixture'}, 'pin', pin=pin)
            self.assertEqual(result['pin'], state['current']); self.assertEqual(result['pin_sequence'], 1)
            with self.assertRaisesRegex(ValueError, 'rollback/replay'):transport.upload({'key': 'fixture', 'remote': 'fixture'}, 'pin', pin=pin)


    def test_generator_builds_pending_kit_and_binds_claude_review_to_runner(self):
        import test_code_recovery as fixtures
        f = fixtures.CodeTests(); f.setUp(); self.addCleanup(f.doCleanups)
        package = f.approval(2); release_hash = d.sha(package/'manifest.json')
        db = self.root/'fixture.sqlite3'; hive.initialize(db)
        snap = self.root/'snapshot'; manifest = r.snapshot(db, snap, 'test')
        state = self.root/'state.json'; d.save(state, {'sequence': 2, 'current': release_hash, 'pin': None, 'pin_sequence': 0})
        public_blob = f.signers.read_text().split()[3]
        host = 'replica-host ssh-ed25519 '+public_blob
        destination = self.root/'generated'
        with patch.object(builder.sys, 'platform', 'darwin'), patch.object(d, 'CHECKPOINT', manifest), patch.object(d, 'COMMIT', f.commit), patch.object(d, 'RELEASE', release_hash), patch.object(builder, 'SIGNER', builder.fingerprint(public_blob)), patch.object(builder, 'HOST', builder.fingerprint(public_blob)):
            result = builder.generate(snap/'knowledge.sqlite3', package, f.signers, host, state, destination)
            self.assertEqual(result['review'], 'pending')
            with self.assertRaisesRegex(ValueError, 'pending'):d.verify_kit(destination, result['baseline_sha256'])
            review = self.root/'review.json'
            d.save(review, {'status': 'approved', 'reviewer': 'Claude', 'notes': 'synthetic test review, not a real approval', 'tools': {name: d.sha(destination/name) for name in ('recovery_drill.py', 'recovery_drill_worker.py')}})
            approved = self.root/'reviewed'
            result = builder.generate(snap/'knowledge.sqlite3', package, f.signers, host, state, approved, review)
            self.assertEqual(d.verify_kit(approved, result['baseline_sha256'])['review']['status'], 'approved')
            with self.assertRaises(FileExistsError):builder.generate(snap/'knowledge.sqlite3', package, f.signers, host, state, approved, review)
            bad = json.loads(review.read_bytes()); bad['tools']['recovery_drill.py'] = '0'*64; review.write_bytes(d.canonical(bad))
            with self.assertRaisesRegex(ValueError, 'different runner'):builder.generate(snap/'knowledge.sqlite3', package, f.signers, host, state, self.root/'wrong-review', review)

    def test_real_integrity_worker_restores_only_isolated_sources(self):
        import subprocess
        import code_release as c
        repo = self.root/'authenticated-fixture-code'
        # Public export has no Git history, so release 2's commit is absent there.
        if subprocess.run(['git', 'cat-file', '-e', d.COMMIT+'^{commit}'], cwd=Path(d.__file__).parent, capture_output=True).returncode:
            self.skipTest('release 2 commit not in this repository history')
        # Offline integration test using release 2's already reviewed source.
        c.git('clone', '--no-local', str(Path(d.__file__).parent), str(repo))
        c.git('checkout', '--detach', d.COMMIT, cwd=repo)
        root = self.root/'worker-run'; root.mkdir()
        source = self.root/'source.txt'; source.write_text('Python 3.10 or newer is required.')
        db = self.root/'fixture.sqlite3'; knowledge.ingest(db, source)
        manifest = r.snapshot(db, root/'memory', 'worker-fixture')
        before = d.sha(root/'memory/knowledge.sqlite3')
        baseline = {**self.baseline, 'checkpoint': manifest, 'sources': worker.source_rows(root/'memory/knowledge.sqlite3'), 'findings': []}
        d.save(root/'baseline.json', baseline); source.unlink()
        result = subprocess.run([__import__('sys').executable, '-B', '-I', str(Path(worker.__file__).resolve()), '--repo', str(repo), '--run', str(root), '--phase', 'integrity'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertTrue(json.loads((root/'integrity.json').read_bytes())['passed'])
        self.assertEqual(d.sha(root/'memory/knowledge.sqlite3'), before)
        self.assertFalse(source.exists())
        self.assertTrue((root/'recreated-sources/source-recovery.json').exists())

if __name__ == '__main__':unittest.main()
