#!/usr/bin/env python3
"""Independently reviewed worker; imports only the already verified release checkout."""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import platform
import shutil
import sqlite3
import subprocess
import sys
from unittest.mock import patch
from urllib.request import build_opener, ProxyHandler


def source_rows(db):
    """Read immutable downloaded memory; never initialize or modify it."""
    uri = Path(db).resolve().as_uri()+'?mode=ro&immutable=1'
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute("SELECT id,payload FROM events WHERE kind='source_ingested' ORDER BY sequence").fetchall()
    finally:
        conn.close()
    return [{'source_id': sid, 'original_path': json.loads(raw)['path'], 'sha256': json.loads(raw)['sha256']} for sid, raw in rows]


def write(path, value):
    with Path(path).open('x') as f:
        json.dump(value, f, indent=2); f.write('\n')


def main():
    p = argparse.ArgumentParser(); p.add_argument('--repo', required=True); p.add_argument('--run', required=True)
    p.add_argument('--phase', choices=['integrity', 'quality'], required=True); a = p.parse_args()
    root = Path(a.run).resolve(); repo = Path(a.repo).resolve()
    baseline = json.loads((root/'baseline.json').read_bytes())
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
    if actual != baseline['release']['commit']:raise ValueError('Worker checkout commit mismatch')
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=repo).strip():raise ValueError('Worker checkout is dirty')
    sys.path.insert(0, str(repo))
    import replication as r
    import knowledge, hive, source_recovery, cross_machine_recovery as old, ollama_preflight
    pristine = root/'memory/knowledge.sqlite3'; working = root/'working.sqlite3'; sources = root/'recreated-sources'
    r.require(r.manifest_for(pristine, baseline['checkpoint']['database_id']) == baseline['checkpoint'], 'Pristine integrity mismatch')
    original_connect = hive.connect
    @contextmanager
    def working_only(path):
        r.require(Path(path).resolve() == working, 'Refused non-working memory connection')
        with original_connect(path) as conn:yield conn
    # Queries cannot fall back to original Mac paths or write pristine memory.
    with patch.object(hive, 'connect', working_only), patch.object(knowledge, 'read_source', side_effect=AssertionError('Original source reads forbidden')):
        if a.phase == 'integrity':
            r.require(source_rows(pristine) == baseline['sources'], 'Frozen source hashes differ')
            proofs = old.linked_findings(pristine)
            r.require(proofs == baseline['findings'], 'Frozen evidence/support links differ')
            with working.open('xb') as target, pristine.open('rb') as source:shutil.copyfileobj(source, target)
            with patch.object(knowledge, 'ask', side_effect=AssertionError('Inference before source reconstruction forbidden')):
                before = [knowledge.answer_question(working, case[0], baseline['model']['name'], 11, 0.2, recovery_root=sources) for case in baseline['criteria']['cases']]
            r.require(all(x['status'] == 'needs_review' for x in before), 'Missing sources did not withhold answers')
            mapping = source_recovery.recover(working, sources)
            for entry in mapping['sources'].values():source_recovery.read_source(sources, entry, entry['sha256'])
            r.require(r.manifest_for(pristine, baseline['checkpoint']['database_id']) == baseline['checkpoint'], 'Pristine changed')
            write(root/'integrity.json', {'passed': True, 'source_snapshots': baseline['sources'], 'findings': proofs,
                                         'before_sources': before, 'reconstruction': mapping})
        else:
            result = {'preflight_ok': False, 'trials': [], 'environment': {'platform': platform.platform(), 'python': sys.version}}
            try:
                opener = build_opener(ProxyHandler({}))
                def api(path):
                    with opener.open('http://127.0.0.1:11434/api/'+path, timeout=30) as response:return json.load(response)
                result['ollama_version'] = api('version'); ollama_preflight.check_version(result['ollama_version']['version'])
                models = api('tags')['models']; model = next(m for m in models if m['name'] == baseline['model']['name'])
                result['model'] = model
                r.require(model['digest'] == baseline['model']['digest'], 'Model digest differs from frozen criteria')
                result['schema_probe'] = ollama_preflight.schema_probe(pristine, sources, model['name'], audit_db=working)
                r.require(result['schema_probe']['ok'], 'Model schema preflight failed')
                result['preflight_ok'] = True
                with (root/'trials.jsonl').open('x') as log:
                    for seed in baseline['criteria']['seeds']:
                        for question, expected_status, expected_answer in baseline['criteria']['cases']:
                            row = {'seed': seed, 'question': question}
                            try:
                                answer = knowledge.answer_question(working, question, model['name'], seed, baseline['criteria']['temperature'], recovery_root=sources)
                                verdict = old.classify_result(answer, expected_status, expected_answer)
                                row.update(result=answer, verdict='abstention' if verdict == 'false_reject' else verdict)
                            except Exception as e:row.update(error=repr(e), verdict='error')
                            result['trials'].append(row); log.write(json.dumps(row)+'\n'); log.flush()
            except Exception as e:result['error'] = repr(e)
            finally:
                # Preserve every raw model/audit event, including schema failures.
                with r.database(working, immutable=False) as db:
                    events = [{**dict(zip(r.COLS, row)), 'payload': json.loads(row[-1])} for row in db.execute('SELECT * FROM events ORDER BY sequence')]
                write(root/'working-events.json', events)
                write(root/'quality.json', result)
    r.require(r.manifest_for(pristine, baseline['checkpoint']['database_id']) == baseline['checkpoint'], 'Pristine changed during worker')

if __name__ == '__main__':main()
