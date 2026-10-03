"""Signed code release format and bootstrap verification. Never executes bundled code."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

PROJECT = 'aster-hive'
NAMESPACE = 'hive-release'
MAX_BUNDLE = 64 * 1024**2
MAX_META = 64 * 1024
FILES = ('manifest.json', 'manifest.sig', 'hive.bundle', 'evidence.json')


def require(ok, message):
    if not ok: raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()+b'\n'


def digest(raw): return hashlib.sha256(raw).hexdigest()


def decode(raw):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, 'Duplicate JSON key'); result[k] = v
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    require(canonical(value) == raw, 'Noncanonical metadata')
    return value


def git(*args, cwd=None):
    env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_TERMINAL_PROMPT': '0', 'GIT_TEMPLATE_DIR': ''}
    for k in list(env):
        if k.startswith('GIT_') and k not in {'GIT_CONFIG_NOSYSTEM','GIT_CONFIG_GLOBAL','GIT_TERMINAL_PROMPT','GIT_TEMPLATE_DIR'}:del env[k]
    return subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', *args], cwd=cwd,
                          env=env, check=True, capture_output=True, timeout=120).stdout


def check_bundle(path, commit):
    require(re.fullmatch('[0-9a-f]{40}', commit) is not None, 'Invalid commit')
    require(0 < path.stat().st_size <= MAX_BUNDLE, 'Bundle size outside limit')
    with tempfile.TemporaryDirectory(prefix='hive-bundle-') as tmp:
        git('init','--bare',tmp)
        git('bundle','verify',str(path.resolve()),cwd=tmp)
        heads=git('bundle','list-heads',str(path.resolve())).decode().splitlines()
        require(heads == [commit+' refs/heads/master'], 'Bundle must advertise only exact master')
        git('fetch',str(path.resolve()),'refs/heads/master:refs/heads/master',cwd=tmp)
        git('fsck','--full','--strict',cwd=tmp)
        require(git('rev-parse','master^{commit}',cwd=tmp).decode().strip()==commit, 'Commit mismatch')


def verify_signature(raw, signature, allowed_signers):
    require(0 < len(signature) <= MAX_META, 'Missing/oversized signature')
    with tempfile.TemporaryDirectory() as tmp:
        p=Path(tmp)/'signature';p.write_bytes(signature)
        result=subprocess.run(['ssh-keygen','-Y','verify','-f',str(allowed_signers),
            '-I',PROJECT,'-n',NAMESPACE,'-s',str(p)],input=raw,capture_output=True,timeout=15)
        require(result.returncode==0, 'Release signature rejected')


def validate(directory, allowed_signers=None):
    p=Path(directory)
    require({v.name for v in p.iterdir()} == set(FILES), 'Unexpected/missing release files')
    require(all(v.is_file() and not v.is_symlink() for v in p.iterdir()), 'Nonregular release artifact')
    for name in FILES:
        require((p/name).stat().st_size <= (MAX_BUNDLE if name=='hive.bundle' else MAX_META), 'Artifact oversized')
    raw=(p/'manifest.json').read_bytes();m=decode(raw)
    require(set(m)=={'format','project','sequence','commit','bundle_sha256','bundle_bytes','evidence_sha256','compatibility'}, 'Unexpected release fields')
    require(m['format']==1 and m['project']==PROJECT, 'Wrong release project/format')
    require(type(m['sequence']) is int and 0 <= m['sequence'] < 2**53, 'Invalid release sequence')
    require(m['compatibility']=={'memory_protocol':1,'receiver_protocol':2,'minimum_ollama':'0.32.14'}, 'Unsupported compatibility')
    require(type(m['bundle_bytes']) is int and m['bundle_bytes']==(p/'hive.bundle').stat().st_size, 'Bundle length mismatch')
    require(m['bundle_sha256']==digest((p/'hive.bundle').read_bytes()), 'Bundle hash mismatch')
    require(m['evidence_sha256']==digest((p/'evidence.json').read_bytes()), 'Evidence hash mismatch')
    evidence=decode((p/'evidence.json').read_bytes())
    require(evidence.get('commit')==m['commit'], 'Evidence commit mismatch')
    if allowed_signers is not None:
        require(m['sequence']>0, 'Approval requires positive release number')
        verify_signature(raw,(p/'manifest.sig').read_bytes(),allowed_signers)
        require(evidence.get('tests_passed') is True and evidence.get('smoke_passed') is True, 'Release lacks passing evidence')
    else:
        require(m['sequence']==0 and (p/'manifest.sig').read_bytes()==b'', 'Candidate must be explicitly unsigned')
    check_bundle(p/'hive.bundle',m['commit'])
    return m


def atomic(path, raw):
    path=Path(path)
    fd,tmp=tempfile.mkstemp(prefix='.atomic-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
        fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def bootstrap_verify(directory, signers, receipt, state, rescue=False):
    """Receipt and verifier must come from outside CT's downloaded bundle."""
    m=validate(directory,signers);raw=(Path(directory)/'manifest.json').read_bytes();h=digest(raw)
    floor=json.loads(Path(receipt).read_text())
    if rescue:
        require(m['sequence']==floor['sequence'] and h==floor['manifest_sha256'], 'Rescue must exactly match independent pinned receipt')
        return {'verified':True,'rescue':True,'commit':m['commit'],'sequence':m['sequence'],'manifest_sha256':h,'high_watermark_unchanged':True}
    prior=json.loads(Path(state).read_text()) if Path(state).exists() else floor
    for required in (floor,prior):
        require(m['sequence']>=required['sequence'], 'Rollback below trusted receipt')
        if m['sequence']==required['sequence']:require(h==required['manifest_sha256'], 'Conflicting trusted release')
    atomic(state,canonical({'sequence':m['sequence'],'manifest_sha256':h}))
    return {'verified':True,'commit':m['commit'],'sequence':m['sequence'],'manifest_sha256':h,
            'freshness':'At least trusted receipt; server may hide newer releases'}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('directory');parser.add_argument('--signers',required=True)
    parser.add_argument('--receipt',required=True);parser.add_argument('--state',required=True)
    parser.add_argument('--rescue-pinned',action='store_true')
    args=parser.parse_args()
    print(json.dumps(bootstrap_verify(args.directory,args.signers,args.receipt,args.state,args.rescue_pinned),indent=2))
