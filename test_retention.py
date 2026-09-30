import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hive
import replication as r
import retention as t


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=self.root/'store';self.store.mkdir()
        self.db=self.root/'primary.sqlite3';hive.initialize(self.db);self.append('known good')
        self.n=0;self.base=self.package();self.pin=r.validate(self.base,'test')['sha256']
        self.config={'store':str(self.store),'database_id':'test','pins':[self.pin],'reserve':0}

    def append(self, value):hive.append(self.db,'test','test','claim',{'value':value})
    def package(self):
        self.n+=1;p=self.root/str(self.n);r.snapshot(self.db,p,'test');return p
    def wire(self,p):
        s=io.BytesIO();r.send(p,s);s.seek(0);return s
    def push(self,p,now):return t.accept(self.config,self.wire(p),now=now)

    def test_bad_valid_bursts_do_not_displace_pin_or_first_bucket(self):
        self.push(self.base,0)
        for i in range(1,40):
            self.append('WRONG but valid '+str(i));self.push(self.package(), i*86400 if i>20 else i*60)
        status=t.status(self.config);state=status['retained']
        self.assertIn(self.pin,state['generations']);self.assertLessEqual(len(state['generations']),17)
        self.assertLessEqual(len(state['hourly']),6);self.assertLessEqual(len(state['daily']),7)
        wire=io.BytesIO();t.fetch(self.config,self.pin,wire);wire.seek(0)
        restore=self.root/'restore';restore.mkdir();r.receive(wire,restore)
        self.assertEqual(r.validate(restore,'test')['sha256'],self.pin)
        with r.database(restore/'knowledge.sqlite3') as db:
            self.assertEqual(json.loads(db.execute('SELECT payload FROM events').fetchone()[0])['value'],'known good')

    def test_first_hourly_daily_and_duplicate(self):
        self.push(self.base,0)
        for i in range(1,5):self.append('bad');self.push(self.package(),i*60)
        state=t.status(self.config)['retained']
        self.assertEqual(state['hourly']['0'],self.pin);self.assertEqual(state['daily']['0'],self.pin)
        latest=self.package();before=t.status(self.config)
        self.assertEqual(self.push(latest,3599)['status'],'unchanged')
        self.assertEqual({k:v for k,v in t.status(self.config).items() if k!='free_bytes'}, {k:v for k,v in before.items() if k!='free_bytes'})

    def test_clock_rollback_and_history_rewrite_fail_closed(self):
        self.push(self.base,5000);before=t.status(self.config)
        with self.assertRaisesRegex(ValueError,'clock'):self.push(self.base,4999)
        self.assertEqual({k:v for k,v in t.status(self.config).items() if k!='free_bytes'}, {k:v for k,v in before.items() if k!='free_bytes'})
        self.append('new');self.push(self.package(),6000)
        with self.assertRaisesRegex(ValueError,'rollback'):self.push(self.base,7000)

    def test_automatic_commands_cannot_pin_unpin_or_set_production_time(self):
        self.push(self.base,0)
        for command in ['unpin '+self.pin,'pin '+self.pin,'push 123','fetch ../../etc/passwd']:
            with self.subTest(command=command),self.assertRaises(ValueError):
                t.dispatch(self.config,command,io.BytesIO(),io.BytesIO())

    def test_budget_refusal_keeps_all_generations(self):
        self.push(self.base,0);before=t.status(self.config)
        self.config['budget']=1;self.append('new')
        with self.assertRaisesRegex(ValueError,'budget'):self.push(self.package(),100)
        self.assertEqual({k:v for k,v in t.status(self.config).items() if k!='free_bytes'}, {k:v for k,v in before.items() if k!='free_bytes'})

    def test_migrate_legacy_pin_and_keep_history(self):
        r.accept(self.store,'test',self.wire(self.base),reserve=0)
        self.append('later');r.accept(self.store,'test',self.wire(self.package()),reserve=0)
        status=t.status(self.config)
        self.assertEqual(status['generations'],2);self.assertIn(self.pin,status['pins'])
        self.assertEqual(r.current(self.store,'test')[1]['event_count'],2)

    def test_interrupted_index_publication_retry_and_truncated_transfer(self):
        self.push(self.base,0);before=t.status(self.config)
        self.append('later');p=self.package()
        with patch('retention.atomic',side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):self.push(p,100)
        self.assertEqual(t.status(self.config)['manifest'],before['manifest'])
        self.assertEqual(self.push(p,100)['status'],'accepted')
        before=t.status(self.config)
        with self.assertRaises(ValueError):t.accept(self.config,io.BytesIO(self.wire(p).getvalue()[:-10]),now=200)
        self.assertEqual({k:v for k,v in t.status(self.config).items() if k!='free_bytes'}, {k:v for k,v in before.items() if k!='free_bytes'})
