#!/usr/bin/env python3
"""Recover exclusively from replica CT; preserve pristine memory and all trial records."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch
from urllib.request import build_opener, ProxyHandler
import knowledge
import replication as r
import source_recovery
import ollama_preflight

CASES = [
    ('What happens when the model calculation disagrees?', 'supported_answer', 'needs_review'),
    ('What is the minimum Python version required?', 'supported_answer', 'Python 3.10 or newer'),
    ('Who manufactured the reservoir?', 'not_found_in_source', None),
]


def model_classification(baseline, actual):
    return 'same-model' if actual['digest'] == baseline['digest'] else 'model-change'


def classify_result(result, expected_status, expected_answer):
    correct = result['status'] == expected_status and (
        result.get('answer') is None if expected_answer is None else
        knowledge.normalize_answer(result.get('answer','')) == knowledge.normalize_answer(expected_answer))
    if correct:return 'correct'
    # Unsupported accepted positive OR absence claims are false accepts.
    return 'false_accept' if result['status'] in ('supported_answer','not_found_in_source') else 'false_reject'


def linked_findings(db):
    with r.database(db) as connection:
        rows = [dict(zip(r.COLS,row)) for row in connection.execute('SELECT * FROM events ORDER BY sequence')]
    byid={row['id']:row for row in rows}
    payload=lambda row:json.loads(row['payload'])
    proofs=[]
    for row in rows:
        if row['kind']!='knowledge_query':continue
        result=payload(row);status=result['status'];task=row['run_id']
        events=[e for e in rows if e['run_id']==task]
        if status=='supported_answer':
            citation=result['citation'];source=byid[citation['source_id']];snap=payload(source)
            r.require(source['kind']=='source_ingested' and citation['sha256']==snap['sha256'],'Evidence link mismatch')
            r.require(hashlib.sha256(snap['text'].encode()).hexdigest()==snap['sha256'],'Evidence source hash mismatch')
            supports=[e for e in events if e['kind']=='model_call' and e['cookie']=='cookie-support']
            checks=[e for e in events if e['kind']=='support_check']
            r.require(len(supports)==len(checks)==1,'Missing support link')
            r.require(all(v is True for v in payload(checks[0]).values()),'Failed original support check')
            r.require(payload(supports[0])['context']=={'question':result['question'],'quote':result['quote']},'Support context mismatch')
            proof={'query':row['id'],'status':status,'source':source['id'],'support':supports[0]['id'],'check':checks[0]['id']}
        elif status=='not_found_in_source':
            finding=payload(byid[result['finding_id']]);confirm=byid[finding['confirmation_id']];check=byid[finding['absence_check_id']]
            r.require(confirm['run_id']==task and confirm['cookie']=='cookie-support','Missing absence support link')
            r.require(payload(confirm)['answer']['outcome']=='not_found_in_source','Unconfirmed absence finding')
            r.require(all(v is True for v in payload(check)['checks'].values()),'Failed absence checks')
            sources=[]
            for chunk in finding['searched_chunk_ids']:
                sid=chunk.rsplit(':',1)[0];snap=payload(byid[sid])
                r.require(hashlib.sha256(snap['text'].encode()).hexdigest()==snap['sha256'],'Absence evidence hash mismatch')
                sources.append(sid)
            proof={'query':row['id'],'status':status,'finding':result['finding_id'],'support':confirm['id'],'check':check['id'],'sources':sources}
        else:continue
        proofs.append(proof)
    return proofs


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release',required=True);p.add_argument('--remote',required=True);p.add_argument('--key',required=True)
    p.add_argument('--destination',required=True);p.add_argument('--report',required=True)
    p.add_argument('--model',default='gemma4:e4b');p.add_argument('--seeds',nargs='+',type=int,default=[11,29,47])
    p.add_argument('--temperature',type=float,default=0.2)
    args=p.parse_args()
    release=json.loads(Path(args.release).read_text());dest=Path(args.destination).absolute();report=Path(args.report).absolute()
    r.require(not dest.exists() and not report.exists(),'Use new destination and report paths; never overwrite a drill')
    r.require(args.seeds==[11,29,47] and args.temperature==0.2,'This drill requires seeds 11/29/47 and temperature 0.2')
    repo=Path(__file__).resolve().parent
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    r.require(commit==release['code_commit'],'Recovery code commit mismatch')
    r.require(not subprocess.check_output(['git','status','--porcelain'],cwd=repo,text=True).strip(),'Recovery checkout must be clean')
    dest.mkdir(mode=0o700)
    record={'started':datetime.now(timezone.utc).isoformat(),'code_commit':commit,'release':release,'status':'running','queries':[]}
    def save():report.write_text(json.dumps(record,indent=2)+'\n')
    save()
    try:
        record['version_preflight']=ollama_preflight.version_status();save()
        r.require(record['version_preflight']['ok'], record['version_preflight'].get('reason','Ollama version refused'))
        config={'remote':args.remote,'key':str(Path(args.key).expanduser().resolve()),'database_id':release['checkpoint']['database_id'],
                'use_ssh_agent':True,'ed25519_host_only':True}
        pristine=dest/'pristine.sqlite3'
        record['restore']=r.restore(config,pristine,release['checkpoint'],generation=release['checkpoint']['sha256'])
        record['byte_identical']=r.sha(pristine)==release['checkpoint']['sha256'];r.require(record['byte_identical'],'Restore hash differs')
        record['original_findings']=linked_findings(pristine)
        counts={s:sum(x['status']==s for x in record['original_findings']) for s in ['supported_answer','not_found_in_source']}
        r.require(counts=={'supported_answer':2,'not_found_in_source':1},'Original findings coverage differs');save()
        working=dest/'working.sqlite3';shutil.copyfile(pristine,working);sources=dest/'recreated-sources'
        with patch('knowledge.read_source',side_effect=AssertionError('Original source reads forbidden')),patch('knowledge.ask',side_effect=AssertionError('No inference before source recovery')):
            record['before_sources']=[knowledge.answer_question(working,q,args.model,11,0.2,recovery_root=sources) for q,_,_ in CASES]
        r.require(all(x['status']=='needs_review' for x in record['before_sources']),'Answers not withheld before recovery')
        record['sources']=source_recovery.recover(working,sources);save()
        opener=build_opener(ProxyHandler({}))
        def api(path):
            with opener.open('http://127.0.0.1:11434/api/'+path,timeout=30) as response:return json.load(response)
        tags=api('tags')['models'];actual=next(m for m in tags if m['name']==args.model)
        record['actual_model']=actual;record['ollama_version']=api('version')
        category=model_classification(release['model_baseline'],actual)
        record['classification']=category
        record['same_model_result']='pending' if category=='same-model' else 'not run: different model digest'
        record['model_change_result']='pending' if category=='model-change' else 'not applicable'
        record['environment']={}
        for cmd in [['uname','-a'],['nvidia-smi'],['ollama','--version']]:
            try:
                result=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
                record['environment'][' '.join(cmd)]={'exit':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
            except OSError as e:record['environment'][' '.join(cmd)]={'error':str(e)}
        record['schema_preflight']=ollama_preflight.schema_probe(pristine,sources,args.model,audit_db=working);save()
        r.require(record['schema_preflight']['ok'],'Policy schema preflight failed; no recovery answer trials run. Raw/error events are in recovered/working.sqlite3.')
        save()
        for seed in args.seeds:
            for question,status,answer in CASES:
                try:
                    with patch('knowledge.read_source',side_effect=AssertionError('Original source reads forbidden')):
                        result=knowledge.answer_question(working,question,args.model,seed,0.2,recovery_root=sources)
                    verdict=classify_result(result,status,answer)
                    item={'seed':seed,'question':question,'result':result,'verdict':verdict}
                except Exception as e:
                    item={'seed':seed,'question':question,'error':str(e),'verdict':'error'}
                record['queries'].append(item);save();print(seed,question,item['verdict'],flush=True)
                try:record.setdefault('gpu_observations',[]).append(api('ps'))
                except Exception as e:record.setdefault('gpu_observations',[]).append({'error':str(e)})
        record['counts']={k:sum(x['verdict']==k for x in record['queries']) for k in ['correct','false_accept','false_reject','error']}
        with r.database(working,immutable=False) as db:
            record['working_events']=[{**dict(zip(r.COLS,row)),'payload':json.loads(row[-1])} for row in db.execute('SELECT * FROM events ORDER BY sequence')]
        tests=subprocess.run([sys.executable,'-m','unittest','-q'],cwd=repo,capture_output=True,text=True,timeout=180)
        record['unit_tests']={'exit':tests.returncode,'stdout':tests.stdout,'stderr':tests.stderr}
        r.require(r.sha(pristine)==release['checkpoint']['sha256'],'Pristine memory changed during trial')
        record['gpu_acceleration_observed']=any(m.get('size_vram',0)>0 for obs in record.get('gpu_observations',[]) for m in obs.get('models',[]))
        passed=record['counts']['correct']==9 and tests.returncode==0 and record['gpu_acceleration_observed']
        record[category.replace('-','_')+'_result']='passed' if passed else 'failed'
        record.update(status='passed' if passed else 'failed',finished=datetime.now(timezone.utc).isoformat());save()
        raise SystemExit(0 if passed else 1)
    except Exception as e:
        if (dest/'working.sqlite3').exists():
            with r.database(dest/'working.sqlite3',immutable=False) as db:
                record['working_events']=[{**dict(zip(r.COLS,row)),'payload':json.loads(row[-1])} for row in db.execute('SELECT * FROM events ORDER BY sequence')]
        record.update(status='failed',error=str(e));save();raise


if __name__=='__main__':main()
