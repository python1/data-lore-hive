#!/usr/bin/env python3
"""Replay preserved model bytes through current parsing and acceptance code, offline."""
import argparse
from contextlib import nullcontext
import hashlib
import json
from pathlib import Path
import shutil
from unittest.mock import patch
import hive,knowledge,ollama_local,support_cookie

class Response:
    status=200
    def __init__(self,body):self.body=body.encode()
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self):return self.body


def main():
    p=argparse.ArgumentParser();p.add_argument('record');p.add_argument('fixtures');p.add_argument('directory');a=p.parse_args()
    previous=json.loads(Path(a.record).read_text());root=Path(a.directory).resolve();root.mkdir()
    fixtures=Path(a.fixtures).resolve()
    report={'scope':'Offline replay of actual saved model bytes through final code; no fresh model inference',
            'source_record_sha256':hashlib.sha256(Path(a.record).read_bytes()).hexdigest(),
            'implementation':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},
            'suites':{}}
    for suite,data in previous['suites'].items():
        db=root/(suite+'.sqlite3');shutil.copyfile(fixtures/(suite+'.sqlite3'),db);rows=[]
        report['suites'][suite]={'cases':rows}
        for trial in data['cases']:
            requests=[e['payload']['request'] for e in trial['events'] if e['kind']=='model_request']
            raw=[e['payload']['raw_text'] for e in trial['events'] if e['kind']=='model_raw_response']
            identities=[e['payload']['identity'] for e in trial['events'] if e['kind']=='model_call' and e['cookie']=='cookie-relevance']
            assert len(requests)==len(raw)
            calls=[]
            class Opener:
                def open(self,request,timeout):
                    index=len(calls);payload=json.loads(request.data);calls.append(payload)
                    assert payload==requests[index], 'Replay request changed; cannot claim identical inputs'
                    return Response(raw[index])
            def support(question,quote,model,seed,temperature):return support_cookie.review(question,quote,model,seed,temperature)
            with hive.connect(db) as c:last=c.execute('SELECT COALESCE(MAX(sequence),0) FROM events').fetchone()[0]
            row={k:trial[k] for k in ['name','question','seed','answerable','gold']}
            with patch('ollama_local.build_opener',return_value=Opener()),patch('knowledge.support_review',side_effect=support),patch('relevance_cookie.identity',side_effect=lambda model:identities[0]),patch('knowledge.read_source',side_effect=AssertionError('No original source access')) if suite=='drill' else nullcontext():
                result=knowledge.answer_question(db,trial['question'],trial['result']['model'],trial['seed'],0.2,
                    recovery_root=fixtures/'drill-sources' if suite=='drill' else None)
            assert len(calls)==len(requests), 'Not all preserved calls were replayed'
            with hive.connect(db) as c:events=[dict(e) for e in c.execute('SELECT * FROM events WHERE sequence>? ORDER BY sequence',(last,))]
            for e in events:e['payload']=json.loads(e['payload'])
            positive=result['status']=='supported_answer'
            correct=positive and trial['answerable'] and knowledge.normalize_answer(result['answer']) in {knowledge.normalize_answer(v) for v in trial['gold']}
            row.update(result=result,events=events,path=result.get('binding_path','general' if result.get('question_route')!='policy' else 'pre_binding'),
                       available=positive,correct_positive=correct,false_accept=(positive and not correct) or (result['status']=='not_found_in_source' and trial['answerable']),
                       false_reject=trial['answerable'] and not positive,confirmed_not_found=result['status']=='not_found_in_source' and not trial['answerable'],
                       abstention=result['status'] not in {'supported_answer','not_found_in_source'},
                       error=any(e['kind'] in {'model_call_error','support_error','relevance_error'} for e in events),
                       matches_live_status=result['status']==trial['result']['status'])
            rows.append(row)
        report['suites'][suite]['metrics']={k:sum(bool(r.get(k)) for r in rows) for k in ['answerable','available','correct_positive','false_accept','false_reject','confirmed_not_found','abstention','error']}
    report['paths']={}
    allrows=[r for s in report['suites'].values() for r in s['cases']]
    for path in ['general','pre_binding','deterministic','fallback','promoted']:
        rows=[r for r in allrows if r['path']==path];metrics={k:sum(bool(r.get(k)) for r in rows) for k in ['answerable','available','correct_positive','false_accept','confirmed_not_found','abstention','error']}
        metrics.update(trials=len(rows),false_accept_rate=metrics['false_accept']/len(rows) if rows else None,
                       false_accepts_per_delivered=metrics['false_accept']/metrics['available'] if metrics['available'] else None)
        report['paths'][path]=metrics
    report['finished']=True
    (root/'summary.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report['paths'],indent=2))

if __name__=='__main__':main()
