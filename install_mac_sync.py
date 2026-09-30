#!/usr/bin/env python3
"""Install versioned user-only runtime and launchd jobs, then load them."""
import hashlib,json,os,plistlib,shutil,subprocess,sys,time
from pathlib import Path


def main():
    if os.geteuid()==0:raise SystemExit('Run as the logged-in Mac user, never root')
    repo=Path(__file__).resolve().parent
    workspace=repo.parent.parent
    base=Path.home()/'Library/Application Support/HiveSync'
    logs=Path.home()/'Library/Logs/HiveSync'
    agents=Path.home()/'Library/LaunchAgents'
    files=['sync_agent.py','replication.py','retention.py']
    release=hashlib.sha256(b''.join((repo/f).read_bytes() for f in files)).hexdigest()[:16]
    runtime=base/'releases'/release
    for p in (base,logs,agents,runtime):p.mkdir(parents=True,exist_ok=True,mode=0o700)
    config_path=base/'config.json'
    targets=[agents/'local.hive.sync.plist',agents/'local.hive.sync-watchdog.plist']
    if config_path.exists() or any(p.exists() for p in targets):raise SystemExit('Existing installation found; refusing to overwrite')
    for f in files:
        dest=runtime/f
        if dest.exists():
            if dest.read_bytes()!=(repo/f).read_bytes():raise SystemExit('Release conflict')
        else:dest.write_bytes((repo/f).read_bytes());dest.chmod(0o600)
    config=json.loads((workspace/'work/replication/client.json').read_text())
    key=base/'replica_ct_ed25519'
    if key.exists():raise SystemExit('Existing key destination; refusing to overwrite')
    shutil.copyfile(config['key'],key);key.chmod(0o600)
    config.update(key=str(key),state_dir=str(base),log_dir=str(logs),installed_at=time.time())
    config_path.write_text(json.dumps(config,indent=2)+'\n');config_path.chmod(0o600)
    for label,action,path in [('local.hive.sync','sync',targets[0]),('local.hive.sync-watchdog','watchdog',targets[1])]:
        plist={'Label':label,'ProgramArguments':[sys.executable,str(runtime/'sync_agent.py'),action,'--config',str(config_path)],
               'RunAtLoad':True,'StartCalendarInterval':[{'Minute':minute} for minute in range(0,60,5)],
               'ProcessType':'Background','WorkingDirectory':str(base),'Umask':0o077,
               'StandardOutPath':str(logs/(action+'-launchd.out.log')),
               'StandardErrorPath':str(logs/(action+'-launchd.err.log'))}
        path.write_bytes(plistlib.dumps(plist,sort_keys=False));path.chmod(0o600)
        subprocess.run(['/usr/bin/plutil','-lint',str(path)],check=True)
    receipt={'release':release,'runtime':str(runtime),'python':sys.executable,'config':str(config_path),'plists':[str(p) for p in targets]}
    (base/'install-receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2),flush=True)
    for path in targets:subprocess.run(['/bin/launchctl','bootstrap',f'gui/{os.getuid()}',str(path)],check=True)

if __name__=='__main__':main()
