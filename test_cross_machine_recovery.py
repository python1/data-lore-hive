import io
import json
from pathlib import Path
import tempfile
import unittest
import recovery_server as server
import cross_machine_recovery as recovery
import replication as r
import hive


class RecoveryAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);bundle=self.root/'hive-recovery.bundle';bundle.write_bytes(b'test bundle')
        self.release={'bundle_sha256':r.sha(bundle),'checkpoint':{'sha256':'a'*64}}
        (self.root/'release.json').write_text(json.dumps(self.release));(self.root/'checkpoint.wire').write_bytes(b'wire')

    def test_only_selected_read_commands(self):
        for command in ['release','code','status','fetch','fetch '+'a'*64]:
            output=io.BytesIO();server.serve(self.root,command,output);self.assertTrue(output.getvalue())
        before={p.name:p.read_bytes() for p in self.root.iterdir()}
        for command in ['','push','test status','unpin '+'a'*64,'fetch '+'b'*64,'fetch ../../etc/passwd','sh','code; id','code\nstatus']:
            with self.subTest(command=command),self.assertRaises(ValueError):server.serve(self.root,command,io.BytesIO())
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})

    def test_corrupt_bundle_refused(self):
        (self.root/'hive-recovery.bundle').write_bytes(b'bad')
        with self.assertRaisesRegex(ValueError,'hash'):server.serve(self.root,'code',io.BytesIO())

    def test_different_digest_is_labeled_not_blocked(self):
        self.assertEqual(recovery.model_classification({'digest':'a'},{'digest':'a'}),'same-model')
        self.assertEqual(recovery.model_classification({'digest':'a'},{'digest':'b'}),'model-change')

    def test_counts_keep_false_accept_and_false_reject_separate(self):
        self.assertEqual(recovery.classify_result({'status':'supported_answer','answer':'needs_review'},'supported_answer','needs_review'),'correct')
        self.assertEqual(recovery.classify_result({'status':'needs_review'},'supported_answer','needs_review'),'false_reject')
        self.assertEqual(recovery.classify_result({'status':'not_found_in_source'},'supported_answer','needs_review'),'false_accept')
        self.assertEqual(recovery.classify_result({'status':'supported_answer','answer':'Acme'},'not_found_in_source',None),'false_accept')

    def _run_driver(self, schema_ok=True):
        import shutil
        import subprocess
        from unittest.mock import patch
        db=self.root/'source.sqlite3';hive.initialize(db)
        baseline=r.snapshot(db,self.root/'baseline','test')
        release={'checkpoint':baseline,'code_commit':'approved','model_baseline':{'digest':'old'}}
        release_path=self.root/'driver-release.json';release_path.write_text(json.dumps(release))
        dest=self.root/'recovered';report=self.root/'report.json'
        def restore(config,path,expected,generation=None):
            shutil.copyfile(self.root/'baseline/knowledge.sqlite3',path);return expected
        def request(url,timeout=None):
            endpoint=url.rsplit('/',1)[-1]
            data={'tags':{'models':[{'name':'gemma4:e4b','digest':'new'}]},'version':{'version':'test'},'ps':{'models':[{'size_vram':123}]}}[endpoint]
            return io.BytesIO(json.dumps(data).encode())
        class Opener:
            open=staticmethod(request)
        answers=[{'status':'needs_review'}]*3+[
            {'status':s,**({'answer':a} if a is not None else {})} for _,s,a in recovery.CASES]*3
        proofs=[{'status':'supported_answer'},{'status':'supported_answer'},{'status':'not_found_in_source'}]
        args=['drill','--release',str(release_path),'--remote','example','--key','example',
              '--destination',str(dest),'--report',str(report)]
        with patch('sys.argv',args),patch.object(recovery.r,'restore',side_effect=restore),\
             patch.object(recovery,'linked_findings',return_value=proofs),\
             patch.object(recovery.ollama_preflight,'version_status',return_value={'ok':True}),\
             patch.object(recovery.ollama_preflight,'schema_probe',return_value={'ok':schema_ok}),\
             patch.object(recovery.source_recovery,'recover',return_value={}),\
             patch.object(recovery.knowledge,'answer_question',side_effect=answers) as ask,\
             patch.object(recovery,'build_opener',return_value=Opener()),\
             patch.object(recovery.subprocess,'check_output',side_effect=['approved\n','']),\
             patch.object(recovery.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')),\
             patch('builtins.print'),self.assertRaises(SystemExit if schema_ok else ValueError) as end:
            recovery.main()
        result=json.loads(report.read_text())
        if not schema_ok:
            self.assertIn('Policy schema preflight failed',str(end.exception))
            self.assertEqual(ask.call_count,3)  # before-source checks only, no inference trials
            self.assertEqual(result['queries'],[])
            self.assertEqual(result['status'],'failed')
            self.assertIn('working_events',result)
            return
        self.assertEqual(end.exception.code,0)
        self.assertEqual(ask.call_count,12)
        self.assertEqual(result['classification'],'model-change')
        self.assertEqual(result['model_change_result'],'passed')
        self.assertEqual(result['same_model_result'],'not run: different model digest')
        self.assertEqual(result['counts'],{'correct':9,'false_accept':0,'false_reject':0,'error':0})

    def test_full_driver_continues_all_trials_on_changed_digest(self):
        self._run_driver()

    def test_schema_failure_blocks_all_answer_trials(self):
        self._run_driver(schema_ok=False)

    def test_old_version_refused_before_fetch(self):
        from unittest.mock import patch
        release=self.root/'old-version-release.json'
        release.write_text(json.dumps({'code_commit':'approved'}))
        report=self.root/'old-version-report.json'
        args=['drill','--release',str(release),'--remote','example','--key','example',
              '--destination',str(self.root/'old-version-dest'),'--report',str(report)]
        with patch('sys.argv',args),patch.object(recovery.subprocess,'check_output',side_effect=['approved\n','']),\
             patch.object(recovery.ollama_preflight,'version_status',return_value={'ok':False,'reason':'Ollama 0.20.0 below tested minimum 0.32.14'}),\
             patch.object(recovery.r,'restore') as restore, self.assertRaisesRegex(ValueError,'tested minimum'):
            recovery.main()
        restore.assert_not_called()
        result=json.loads(report.read_text())
        self.assertEqual(result['status'],'failed');self.assertEqual(result['queries'],[])

    def test_passphrase_key_uses_agent_only_when_explicitly_requested(self):
        config={'key':'/a/key','remote':'hive-recovery@example'}
        normal=r.ssh_command(config,'status')
        self.assertIn('IdentityAgent=none',normal)
        recovery_command=r.ssh_command({**config,'use_ssh_agent':True,'ed25519_host_only':True},'fetch '+'a'*64)
        self.assertNotIn('IdentityAgent=none',recovery_command)
        self.assertIn('IdentitiesOnly=yes',recovery_command)
        self.assertIn('HostKeyAlgorithms=ssh-ed25519',recovery_command)
        self.assertIn('BatchMode=yes',recovery_command)
