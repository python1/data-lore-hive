import sys,json,shutil,sqlite3,hashlib,time,platform
from pathlib import Path
from urllib.request import build_opener,ProxyHandler
from unittest.mock import patch
code=Path(sys.argv[1]).resolve();root=Path(sys.argv[2]).resolve();phase=sys.argv[3]
sys.path.insert(0,str(code))
import hive,knowledge,source_recovery,evaluate_support,evaluate_prose_policy,cross_machine_recovery
fixtures=root/'fixtures';fixtures.mkdir(exist_ok=True)
if not (fixtures/'table.sqlite3').exists():
 baseline=json.loads((code/'support-seeded-0564edb2-adjudicated.json').read_text())
 source_id=next(c['source_id'] for case in baseline['cases'] for c in case['retrieval']['candidates'])
 source=fixtures/'table.md';source.write_text(baseline['evaluation_source_text'])
 dbpath=fixtures/'table.sqlite3';hive.initialize(dbpath)
 with hive.connect(dbpath) as c:
  c.execute('INSERT INTO events(id,run_id,cookie,kind,recorded_at,payload) VALUES(?,?,?,?,?,?)',(source_id,'frozen','evaluation-fixture','source_ingested','2026-09-28T00:00:00Z',json.dumps({'path':str(source),'text':source.read_text(),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source_uri':source.as_uri(),'supersedes':None,'trust':'frozen evaluation'})))
 source=fixtures/'prose.md';source.write_text(evaluate_prose_policy.SOURCE);knowledge.ingest(fixtures/'prose.sqlite3',source)
 primary=Path(sys.argv[4]).resolve()
 src=sqlite3.connect(primary.as_uri()+'?mode=ro',uri=True);dst=sqlite3.connect(fixtures/'drill.sqlite3');src.backup(dst);dst.close();src.close()
 source_recovery.recover(fixtures/'drill.sqlite3',fixtures/'drill-sources')
out=root/phase;out.mkdir()
api=build_opener(ProxyHandler({}))
def get(path):
 with api.open('http://127.0.0.1:11434/api/'+path,timeout=30) as f:return json.load(f)
report={'phase':phase,'platform':platform.platform(),'version':get('version'),'models':get('tags'),'implementation':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in code.glob('*.py')},'seeds':[11,29,47],'temperature':0.2,'suites':{}}
reportpath=out/'summary.json'
def save():reportpath.write_text(json.dumps(report,indent=2)+'\n')
for suite in ['table','prose','drill']:
 db=out/(suite+'.sqlite3');shutil.copyfile(fixtures/(suite+'.sqlite3'),db)
 if suite=='table':cases=[(n,q,ans,gold) for n,q,ans,gold in evaluate_support.CASES]
 elif suite=='prose':cases=[('prose','What happens when calibration is overdue?',True,{'inspection_required'})]
 else:cases=[('drill-'+str(i),q,st=='supported_answer',{answer} if answer else set()) for i,(q,st,answer) in enumerate(cross_machine_recovery.CASES)]
 rows=[];report['suites'][suite]={'cases':rows}
 for seed in [11,29,47]:
  for name,q,answerable,gold in cases:
   start=time.monotonic()
   with hive.connect(db) as c:last=c.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0]
   row={'name':name,'question':q,'seed':seed,'answerable':answerable,'gold':sorted(gold)}
   try:
    kwargs={'recovery_root':fixtures/'drill-sources'} if suite=='drill' else {}
    with patch('knowledge.read_source',side_effect=AssertionError('No original source access')) if suite=='drill' else __import__('contextlib').nullcontext():
     result=knowledge.answer_question(db,q,'gemma4:e4b',seed,0.2,**kwargs)
    row['result']=result;status=result['status'];positive=status=='supported_answer'
    correct=positive and answerable and knowledge.normalize_answer(result['answer']) in {knowledge.normalize_answer(v) for v in gold}
    row.update(correct_positive=correct,false_accept=(positive and not correct) or (status=='not_found_in_source' and answerable),available=positive,confirmed_not_found=status=='not_found_in_source' and not answerable,false_reject=answerable and not positive)
   except Exception as e:row.update(error=repr(e),false_reject=answerable)
   with hive.connect(db) as c:events=[dict(r) for r in c.execute('SELECT * FROM events WHERE sequence>? ORDER BY sequence',(last,))]
   for e in events:e['payload']=json.loads(e['payload'])
   row['events']=events;row['model_answers']=[{'event_id':e['id'],'cookie':e['cookie'],'answer':e['payload'].get('answer')} for e in events if e['kind']=='model_call']
   row['wall_seconds']=time.monotonic()-start;rows.append(row)
   report['suites'][suite]['metrics']={k:sum(bool(r.get(k)) for r in rows) for k in ['answerable','correct_positive','available','false_accept','false_reject','confirmed_not_found','error']}
   for trial in rows:trial['path']=trial.get('result',{}).get('binding_path','general' if not trial.get('result',{}).get('requested_slot') else 'pre_binding')
   save();print(phase,suite,seed,name,row.get('result',{}).get('status',row.get('error')),flush=True)
report['finished']=True;save();print(json.dumps({s:r['metrics'] for s,r in report['suites'].items()}),flush=True)
