import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
import hive, replication as r, sync_agent
from retention import POLICY

class CodeSyncIntegrationTests(unittest.TestCase):
 def test_memory_success_survives_code_failure_with_visible_partial_status(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);db=root/'memory.sqlite3';hive.initialize(db)
   hive.append(db,'run','test','claim',{'test':True});m=r.snapshot(db,root/'snapshot','test')
   config={'database':str(db),'database_id':'test','state_dir':str(root/'state'),'log_dir':str(root/'logs'),'code':{'repo':'unused'}}
   remote={'manifest':m,'protocol':2,'retention_policy':POLICY,'max_snapshot_bytes':96*1024**2}
   with patch('sync_agent.r.transfer',return_value=remote),patch('code_sync.tick',return_value={'status':'failed','last_error':'test failure'}) as tick:
    result=sync_agent.attempt(config,now=100,notifier=lambda m:None)
   self.assertEqual(result['status'],'partial_failed');self.assertEqual(result['last_success'],100)
   self.assertEqual(result['code']['last_error'],'test failure');tick.assert_called_once()
 def test_code_attempt_runs_even_if_memory_is_unreachable(self):
  with tempfile.TemporaryDirectory() as t:
   config={'state_dir':t,'log_dir':str(Path(t)/'logs'),'code':{'repo':'unused'}}
   with patch('sync_agent.r.transfer',side_effect=OSError('memory offline')),patch('code_sync.tick',return_value={'status':'ok'}) as tick:
    result=sync_agent.attempt(config,now=100,notifier=lambda m:None)
   self.assertEqual(result['status'],'failed');self.assertEqual(result['code']['status'],'ok');tick.assert_called_once()
 def test_mac_staging_does_not_modify_installed_files(self):
  import json,plistlib,prepare_mac_code_sync
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);old=root/'old.json';old.write_text('{"state_dir":"unchanged"}')
   plist=root/'old.plist';plist.write_bytes(plistlib.dumps({'Label':'local.hive.sync','ProgramArguments':['python3','old.py','sync','--config',str(old)]}))
   code=root/'code.json';code.write_text(json.dumps({'repo':'repo','ssh':{},'approvals':'approvals','signers':'signers'}))
   before=(old.read_bytes(),plist.read_bytes());out=root/'stage'
   prepare_mac_code_sync.prepare(old,plist,code,out,'/future/runtime')
   self.assertEqual((old.read_bytes(),plist.read_bytes()),before)
   self.assertTrue((out/'runtime/code_sync.py').is_file());self.assertIn('code',json.loads((out/'config.json').read_text()))
