"""Build an unsigned candidate from master; no signing keys or remote access."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import code_release as c


def build(repo, destination):
    repo=Path(repo).resolve();out=Path(destination);out.mkdir()
    commit=c.git('rev-parse','refs/heads/master^{commit}',cwd=repo).decode().strip()
    # Export only master reachability; catch accidental private material before upload.
    for line in c.git('rev-list','--objects','refs/heads/master',cwd=repo).decode().splitlines():
        oid,_,name=line.partition(' ')
        c.require(not name.endswith(('.sqlite3','.sqlite','.db','.pem','.key')) and '/.ssh/' not in name, 'Sensitive tracked history path: '+name)
        if c.git('cat-file','-t',oid,cwd=repo).strip()==b'blob':
            size=int(c.git('cat-file','-s',oid,cwd=repo));c.require(size<=c.MAX_BUNDLE,'Historical blob exceeds cap')
            raw=c.git('cat-file','blob',oid,cwd=repo)
            markers=[b'-----BEGIN '+v+b' PRIVATE KEY-----' for v in (b'OPENSSH',b'RSA',b'EC')]
            markers += [b'-----BEGIN '+b'PRIVATE KEY-----']
            c.require(name=='build_recovery_kit.py' or not any(v in raw for v in markers),'Private key marker in history: '+name)
    c.git('bundle','create',str((out/'hive.bundle').resolve()),'refs/heads/master',cwd=repo)
    c.check_bundle(out/'hive.bundle',commit)
    evidence={'commit':commit,'tests_passed':False,'smoke_passed':False,'kind':'local isolated validation, not independent attestation'}
    with tempfile.TemporaryDirectory(prefix='hive-code-test-') as tmp:
        clone=Path(tmp)/'repo';c.git('clone',str((out/'hive.bundle').resolve()),str(clone))
        # Source code tests execute locally, never on CT. There is no automatic signing.
        run=subprocess.run([sys.executable,'-m','unittest','discover'],cwd=clone,capture_output=True,timeout=600)
        evidence.update(tests_passed=run.returncode==0,test_exit=run.returncode,
                        test_log_sha256=c.digest(run.stdout+run.stderr),test_log_tail=(run.stdout+run.stderr).decode(errors='replace')[-16000:])
        # Fresh memory with supported/not-found evidence, snapshot transport and source recreation.
        smoke="""import tempfile,pathlib,shutil,hive,knowledge,replication as r,source_recovery
with tempfile.TemporaryDirectory() as t:
 p=pathlib.Path(t);s=p/'source.txt';s.write_text('Python 3.10 or newer is required.')
 db=p/'knowledge.sqlite3';item=knowledge.ingest(db,s)
 support=hive.append(db,'smoke','cookie-support','support_check',{'confirmed':True})
 for status in ['supported_answer','not_found_in_source']:
  hive.append(db,'smoke','cookie-reader','knowledge_query',{'status':status,'source_id':item['source_id'],'support_event_id':support})
 m=r.snapshot(db,p/'snapshot','code-smoke');restored=p/'restored.sqlite3';shutil.copyfile(p/'snapshot/knowledge.sqlite3',restored)
 assert r.sha(restored)==m['sha256'];s.unlink();source_recovery.recover(restored,p/'sources')
 assert list((p/'sources').rglob('*'))
"""
        result=subprocess.run([sys.executable,'-c',smoke],cwd=clone,capture_output=True,timeout=60)
        evidence.update(smoke_passed=result.returncode==0,smoke_exit=result.returncode,
                        smoke_log=(result.stdout+result.stderr).decode(errors='replace')[-8000:])
    raw=c.canonical(evidence);(out/'evidence.json').write_bytes(raw)
    m={'format':1,'project':c.PROJECT,'sequence':0,'commit':commit,'bundle_sha256':c.digest((out/'hive.bundle').read_bytes()),
       'bundle_bytes':(out/'hive.bundle').stat().st_size,'evidence_sha256':c.digest(raw),
       'compatibility':{'memory_protocol':1,'receiver_protocol':2,'minimum_ollama':'0.32.14'}}
    (out/'manifest.json').write_bytes(c.canonical(m));(out/'manifest.sig').write_bytes(b'')
    c.validate(out)
    return m


def prepare(candidate, destination, sequence):
    c.validate(candidate);c.require(sequence>0,'Positive sequence required')
    shutil.copytree(candidate,destination)
    p=Path(destination);m=json.loads((p/'manifest.json').read_bytes());m['sequence']=sequence
    (p/'manifest.json').write_bytes(c.canonical(m))
    return m


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    q=sub.add_parser('build');q.add_argument('repo');q.add_argument('destination')
    q=sub.add_parser('prepare');q.add_argument('candidate');q.add_argument('destination');q.add_argument('--sequence',required=True,type=int)
    a=p.parse_args();print(json.dumps(build(a.repo,a.destination) if a.action=='build' else prepare(a.candidate,a.destination,a.sequence),indent=2))
if __name__=='__main__':main()
