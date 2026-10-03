"""Stage a reviewable Mac runtime/config/plist update; never installs or loads it."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib

FILES=['sync_agent.py','replication.py','retention.py','code_sync.py','code_builder.py','code_release.py','code_transport.py','code_publisher.py']

def prepare(old_config,old_plist,code_config,destination,installed_runtime):
    out=Path(destination);out.mkdir();repo=Path(__file__).resolve().parent
    runtime=out/'runtime';runtime.mkdir()
    for name in FILES:(runtime/name).write_bytes((repo/name).read_bytes())
    config=json.loads(Path(old_config).read_text());config['code']=json.loads(Path(code_config).read_text())
    required={'repo','ssh','approvals','signers'}
    if set(config['code'])!=required:raise ValueError('Code config requires exactly repo, ssh, approvals, signers')
    (out/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    plist=plistlib.loads(Path(old_plist).read_bytes())
    if plist['Label']!='local.hive.sync':raise ValueError('Unexpected sync job')
    plist['ProgramArguments'][1]=str(Path(installed_runtime)/'sync_agent.py')
    (out/'local.hive.sync.plist').write_bytes(plistlib.dumps(plist))
    hashes={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}
    (out/'SHA256SUMS').write_text('\n'.join(h+'  '+n for n,h in sorted(hashes.items()))+'\n')
    return hashes

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--old-config',required=True);p.add_argument('--old-plist',required=True);p.add_argument('--code-config',required=True);p.add_argument('--destination',required=True);p.add_argument('--installed-runtime',required=True);a=p.parse_args()
    print(json.dumps(prepare(a.old_config,a.old_plist,a.code_config,a.destination,a.installed_runtime),indent=2))
