import base64
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import hive
import ollama_local as model
import ollama_preflight as preflight

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.db=Path(self.tmp.name)/'audit.sqlite3';hive.initialize(self.db)
    def events(self):
        with hive.connect(self.db) as c:
            return [(r['kind'],json.loads(r['payload'])) for r in c.execute('SELECT kind,payload FROM events ORDER BY sequence')]
    def call(self,body):
        with model.audit_session(self.db,'run','cookie-solver'),patch('ollama_local.build_opener') as opener:
            opener.return_value.open.return_value=io.BytesIO(body)
            return model.ask('test','policy',{}, {'quote':{'type':'string'},'outcome':{'type':'string','enum':['needs_review']}})
    def test_original_fenced_response_saved_before_parse_failure(self):
        raw=json.dumps({'done':True,'done_reason':'stop','message':{'content':'```json\n{"outcome":"No"}\n```','thinking':None},'eval_count':31}).encode()
        with self.assertRaises(json.JSONDecodeError):self.call(raw)
        events=self.events()
        self.assertEqual([e[0] for e in events],['model_request','model_raw_response','model_call_error'])
        self.assertEqual(base64.b64decode(events[1][1]['raw_base64']),raw)
        self.assertEqual(events[2][1]['stage'],'content_json_parse')
        self.assertEqual(len({e[1]['call_id'] for e in events}),1)
    def test_missing_quote_and_out_of_enum_remain_rejected(self):
        for answer in [{'outcome':'needs_review'},{'quote':'source','outcome':'No'}]:
            raw=json.dumps({'done':True,'message':{'content':json.dumps(answer)}}).encode()
            with self.assertRaises(ValueError):self.call(raw)
            self.assertEqual(self.events()[-1][1]['stage'],'schema_validation')
    def test_success_also_preserves_raw_before_validation(self):
        raw=b'{"done":true,"message":{"content":"{\\"quote\\":\\"source\\",\\"outcome\\":\\"needs_review\\"}"}}'
        answer,record=self.call(raw)
        self.assertEqual(answer['outcome'],'needs_review')
        self.assertEqual([e[0] for e in self.events()],['model_request','model_raw_response'])
        self.assertEqual(record['call_id'],self.events()[0][1]['call_id'])
    def test_bad_outer_json_and_http_error_leave_evidence(self):
        with self.assertRaises(json.JSONDecodeError):self.call(b'not json')
        self.assertEqual(self.events()[-1][1]['stage'],'outer_json_parse')
        with model.audit_session(self.db,'http','cookie-solver'),patch('ollama_local.build_opener') as opener:
            opener.return_value.open.side_effect=HTTPError('url',500,'fail',{},io.BytesIO(b'backend error'))
            with self.assertRaises(HTTPError):model.ask('test','',{}, {'x':{'type':'string'}})
        self.assertEqual(self.events()[-2][1]['http_status'],500)
        self.assertEqual(self.events()[-1][1]['stage'],'transport')
    def test_transport_failure_has_request_and_error(self):
        with model.audit_session(self.db,'timeout','cookie-support'),patch('ollama_local.build_opener') as opener:
            opener.return_value.open.side_effect=TimeoutError('timed out')
            with self.assertRaises(TimeoutError):model.ask('test','',{}, {})
        self.assertEqual([e[0] for e in self.events()],['model_request','model_call_error'])
    def test_failed_request_audit_prevents_network_call(self):
        with model.audit_session(self.db,'fail','cookie-solver'),patch('hive.append',side_effect=OSError('disk full')),patch('ollama_local.build_opener') as opener:
            with self.assertRaises(OSError):model.ask('test','',{}, {})
            opener.assert_not_called()

class PreflightTests(unittest.TestCase):
    def test_tested_minimum_and_ambiguous_versions(self):
        for value in ['0.20.0','0.32.13','0.32.14-rc1',None,'']:
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'tested minimum'):preflight.check_version(value)
        for value in ['0.32.14','0.32.15','1.0.0']:preflight.check_version(value)
    def test_schema_violation_refuses_even_after_other_seeds_pass(self):
        record={'call_id':'test'}
        with patch.object(preflight,'policy_request',return_value=(('test','',{},{}),{})),patch.object(model,'ask',side_effect=[({},record),ValueError('Invalid model response choice for outcome'),({},record)]) as ask:
            result=preflight.schema_probe('unused','unused','test')
        self.assertFalse(result['ok']);self.assertEqual(ask.call_count,3)
        self.assertIn('choice',result['seeds'][1]['reason'])

class SupportProcessAuditTests(unittest.TestCase):
    def test_support_subprocess_failure_persists_raw_response(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as temp:
            db=Path(temp)/'support.sqlite3';hive.initialize(db)
            request={'question':'Who made it?','quote':'The text names no manufacturer.','model':'test','seed':11,'temperature':0.2,
                     'audit':{'db':str(db),'run_id':'support-test','cookie':'cookie-support'}}
            program="""import io,json,runpy\nfrom unittest.mock import patch\nwith patch('ollama_local.build_opener') as opener:\n opener.return_value.open.return_value=io.BytesIO(json.dumps({'done':True,'message':{'content':'```json\\n{}\\n```'}}).encode())\n runpy.run_module('support_cookie',run_name='__main__')\n"""
            p=subprocess.run([sys.executable,'-c',program],input=json.dumps(request),text=True,capture_output=True,cwd=Path(__file__).resolve().parent)
            self.assertNotEqual(p.returncode,0)
            with hive.connect(db) as c:rows=c.execute('SELECT cookie,kind,payload FROM events ORDER BY sequence').fetchall()
            self.assertEqual([r['kind'] for r in rows],['model_request','model_raw_response','model_call_error'])
            self.assertTrue(all(r['cookie']=='cookie-support' for r in rows))
            self.assertIn('```json',json.loads(rows[1]['payload'])['raw_text'])
