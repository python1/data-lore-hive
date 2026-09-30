from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hive
import replication as r
import sync_agent as s
from retention import POLICY


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.db=self.root/'db.sqlite3';hive.initialize(self.db)
        hive.append(self.db,'run','test','claim',{'value':1})
        self.m=r.snapshot(self.db,self.root/'snapshot','test')
        self.config={'database':str(self.db),'database_id':'test','state_dir':str(self.root/'state'),'log_dir':str(self.root/'logs')}
        self.remote={'manifest':self.m,'protocol':2,'retention_policy':POLICY,'max_snapshot_bytes':96*1024**2}
        self.messages=[]
    def notify(self,message):self.messages.append(message);return {'exit':0}

    def test_unchanged_checks_connection_but_never_uploads(self):
        with patch('sync_agent.r.transfer',return_value=self.remote) as transfer:
            result=s.attempt(self.config,now=0,notifier=self.notify)
        self.assertEqual(result['status'],'unchanged');self.assertEqual(transfer.call_count,1)
        self.assertEqual(result['last_success'],0)

    def test_overlap_skips_instead_of_waiting(self):
        with s.run_lock(Path(self.config['state_dir'])):
            self.assertEqual(s.attempt(self.config,now=0)['status'],'skipped_busy')

    def test_offline_alert_after_half_hour_repeat_two_hours_recovery(self):
        with patch('sync_agent.r.transfer',side_effect=OSError('unreachable')):
            for now in [0,100,1799,1800,1900,9000]:s.attempt(self.config,now=now,notifier=self.notify)
        self.assertEqual(len(self.messages),2)
        with patch('sync_agent.r.transfer',return_value=self.remote):
            result=s.attempt(self.config,now=9100,notifier=self.notify)
        self.assertEqual(result['status'],'unchanged');self.assertIn('recovered',self.messages[-1])

    def test_old_receiver_never_receives_upload(self):
        with patch('sync_agent.r.transfer',return_value={'manifest':self.m}) as transfer:
            result=s.attempt(self.config,now=0,notifier=self.notify)
        self.assertEqual(result['status'],'failed');self.assertEqual(transfer.call_count,1);self.assertEqual(len(self.messages),1)

    def test_lost_ack_does_not_advance_local_checkpoint_and_next_status_recovers(self):
        hive.append(self.db,'run','test','claim',{'value':2})
        m=r.snapshot(self.db,self.root/'new','test')
        with patch('sync_agent.r.transfer',side_effect=[self.remote,OSError('lost acknowledgement')]):
            failed=s.attempt(self.config,now=0,notifier=self.notify)
        self.assertNotIn('acknowledged_manifest',failed)
        with patch('sync_agent.r.transfer',return_value={**self.remote,'manifest':m}) as transfer:
            recovered=s.attempt(self.config,now=300,notifier=self.notify)
        self.assertEqual(recovered['status'],'unchanged');self.assertEqual(transfer.call_count,1)

    def test_watchdog_stale_alert_and_recovery(self):
        config={**self.config,'installed_at':0}
        s.watchdog(config,now=1300,notifier=self.notify)
        s.watchdog(config,now=1500,notifier=self.notify)
        self.assertEqual(len(self.messages),1)
        with patch('sync_agent.r.transfer',return_value=self.remote):s.attempt(config,now=1600,notifier=self.notify)
        result=s.watchdog(config,now=1700,notifier=self.notify)
        self.assertFalse(result['stale']);self.assertIn('resumed',self.messages[-1])

    def test_changed_history_uploads_and_records_ack(self):
        hive.append(self.db,'run','test','claim',{'value':2})
        m=r.snapshot(self.db,self.root/'new','test')
        with patch('sync_agent.r.transfer',side_effect=[self.remote,{'manifest':m,'status':'accepted','retention_policy':POLICY}]):
            result=s.attempt(self.config,now=10,notifier=self.notify)
        self.assertEqual(result['status'],'accepted');self.assertEqual(result['acknowledged_manifest'],m)

    def test_failure_demo_leaves_production_state_untouched(self):
        state=Path(self.config['state_dir']);state.mkdir()
        original=b'{"status":"unchanged"}'
        (state/'status.json').write_bytes(original)
        result=s.failure_test(self.config,notifier=self.notify)
        self.assertTrue(result['alert_recorded'])
        self.assertEqual(result['network_calls'],0)
        self.assertEqual((state/'status.json').read_bytes(),original)
        self.assertEqual(len(self.messages),1)
        self.assertIn('TEST ONLY',self.messages[0])
