"""Tested runtime floor and exact policy-request schema probes; never relax output."""
import argparse
from contextlib import contextmanager, nullcontext
import json
from pathlib import Path
import re
import sqlite3
import uuid
from unittest.mock import patch
from urllib.request import build_opener, ProxyHandler
import hive
import knowledge
import ollama_local

MINIMUM = '0.32.14'
QUESTION = 'What happens when the model calculation disagrees?'


def check_version(value):
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)', str(value))
    if not match or tuple(map(int, match.groups())) < (0,32,14):
        raise ValueError(f'Ollama {value!r} refused: tested minimum is {MINIMUM}; upgrade before running the recovery trial')


def version_status():
    with build_opener(ProxyHandler({})).open('http://127.0.0.1:11434/api/version',timeout=30) as response:
        raw=json.load(response)
    try:check_version(raw.get('version'))
    except ValueError as error:return {'ok':False,'response':raw,'reason':str(error),'minimum':MINIMUM}
    return {'ok':True,'response':raw,'minimum':MINIMUM}


def policy_request(db, sources, model, seed):
    """Capture the production solver arguments without any memory writes."""
    db=Path(db).resolve();captured=[]
    @contextmanager
    def readonly(path):
        assert Path(path).resolve()==db
        connection=sqlite3.connect(db.as_uri()+'?mode=ro&immutable=1',uri=True)
        connection.row_factory=sqlite3.Row
        try:yield connection
        finally:connection.close()
    class Captured(BaseException):pass
    def capture(*args,**kwargs):
        captured.append((args,kwargs));raise Captured()
    with patch.object(hive,'connect',readonly),patch.object(hive,'initialize',return_value=None),\
         patch.object(hive,'append',side_effect=RuntimeError('Probe capture refuses writes')),\
         patch.object(knowledge,'read_source',side_effect=RuntimeError('Original source reads forbidden')),\
         patch.object(knowledge,'ask',side_effect=capture):
        try:knowledge.answer_question(db,QUESTION,model,seed,0.2,recovery_root=sources)
        except Captured:pass
    if len(captured)!=1:raise ValueError('Cannot construct exact policy schema probe')
    return captured[0]


def schema_probe(pristine, sources, model, audit_db=None, show_raw=False):
    result={'ok':True,'seeds':[],'scope':'Observed compliance for the exact policy solver request; not proof for every possible request'}
    for seed in [11,29,47]:
        args,kwargs=policy_request(pristine,sources,model,seed)
        row={'seed':seed,'ok':False}
        def print_event(kind,payload):
            print(json.dumps({'event':kind,**payload},ensure_ascii=False),flush=True)
        try:
            with ollama_local.audit_session(audit_db,str(uuid.uuid4()),'cookie-preflight') if audit_db else nullcontext():
                with patch.object(ollama_local,'emit',side_effect=print_event) if show_raw else nullcontext():
                    answer,record=ollama_local.ask(*args,**kwargs)
            row.update(ok=True,answer=answer,call_id=record['call_id'])
        except Exception as error:
            row.update(error_type=type(error).__name__,reason=str(error));result['ok']=False
        result['seeds'].append(row)
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',required=True);p.add_argument('--recovery-root',required=True)
    p.add_argument('--model',default='gemma4:e4b')
    args=p.parse_args()
    version=version_status();print(json.dumps({'version_preflight':version}),flush=True)
    if not version['ok']:raise SystemExit(1)
    result=schema_probe(args.db,args.recovery_root,args.model,show_raw=True)
    print(json.dumps({'schema_preflight':result},indent=2))
    raise SystemExit(0 if result['ok'] else 1)


if __name__=='__main__':main()
