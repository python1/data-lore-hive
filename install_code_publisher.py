#!/usr/bin/env python3
"""One-time replica CT root install. Generated payload is embedded by the local builder."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import fcntl
import shutil
import subprocess

PAYLOAD = None
BASE=Path('/usr/local/lib/hive-code')
CONFIG=Path('/etc/hive-code')
STORE=Path('/var/lib/hive-replica')
SERVICE='hive-code-publisher.service'


def run(*args):return subprocess.run(args,check=True,capture_output=True).stdout

def key(path):
    line=Path(path).read_text().strip();parts=line.split()
    if len(parts)<2 or parts[0]!='ssh-ed25519' or '\n' in line:raise ValueError('Expected one Ed25519 public key')
    run('ssh-keygen','-lf',str(path));return ' '.join(parts[:2])


def main():
    p=argparse.ArgumentParser();p.add_argument('--signing-public-key',required=True);p.add_argument('--upload-public-key',required=True);a=p.parse_args()
    if os.geteuid()!=0 or os.uname().nodename!='replica-host':raise SystemExit('replica CT replica-host root only')
    if PAYLOAD is None:raise SystemExit('Use built installer')
    for name in ('git','ssh-keygen','setfacl','getfacl','systemctl','useradd','groupadd','sshd'):
        if not shutil.which(name):raise SystemExit('Missing prerequisite: '+name)
    for path in (BASE,CONFIG,STORE/'code',Path('/etc/systemd/system')/SERVICE):
        if path.exists():raise SystemExit('Existing installation; refusing overwrite: '+str(path))
    for user in ('hive-code-upload','hive-code-publisher'):
        try:pwd.getpwnam(user)
        except KeyError:pass
        else:raise SystemExit('Account already exists: '+user)
    effective=run('sshd','-T','-C','user=hive-code-upload,host=replica-host,addr=192.0.2.1').decode()
    if 'forcecommand none' not in effective.splitlines():raise SystemExit('Global ForceCommand would override restriction')
    if not any(line in effective.splitlines() for line in ('authorizedkeysfile .ssh/authorized_keys .ssh/authorized_keys2','authorizedkeysfile .ssh/authorized_keys')):raise SystemExit('Unexpected AuthorizedKeysFile')
    signing=key(a.signing_public_key);upload=key(a.upload_public_key)
    if signing==upload:raise SystemExit('Signing and transport keys must differ')
    recovery=Path('/var/lib/hive-recovery/.ssh/authorized_keys')
    old=recovery.read_text()
    expected='command="/usr/bin/python3 /usr/local/lib/hive-recovery/recovery_server.py"'
    if old.count(expected)!=1 or len(old.splitlines())!=1:raise SystemExit('Unexpected recovery forced command')
    for path in [recovery,Path('/etc/hive-replica/authorized_keys'),Path('/root/.ssh/authorized_keys')]:
        if path.exists() and any(k.split()[1] in path.read_text() for k in (signing,upload)):raise SystemExit('Do not reuse existing SSH credentials')
    if not (STORE/'receiver.lock').is_file():raise SystemExit('Missing shared memory lock')
    receiver_config=Path('/etc/hive-replica/config.json')
    receiver_wrapper=Path('/usr/local/lib/hive-replica/replication.py')
    memory_config=json.loads(receiver_config.read_text())
    if memory_config.get('store')!=str(STORE) or memory_config.get('retention_policy')!='recent3-hourly6-daily7-pin1-v2':raise SystemExit('Unexpected memory receiver configuration')
    if not receiver_wrapper.is_file():raise SystemExit('Missing stable memory receiver wrapper')
    # Preflight all payloads before mutation.
    for name,b64 in PAYLOAD.items():compile(base64.b64decode(b64),name,'exec')
    install_lock=(STORE/'receiver.lock').open('a')
    fcntl.flock(install_lock,fcntl.LOCK_EX)
    CONFIG.mkdir(mode=0o755);backup=CONFIG/'backups';backup.mkdir(mode=0o700)
    (backup/'authorized_keys').write_bytes(recovery.read_bytes())
    (backup/'memory-config.json').write_bytes(receiver_config.read_bytes())
    (backup/'memory-wrapper.py').write_bytes(receiver_wrapper.read_bytes())
    (backup/'store.acl').write_bytes(run('getfacl','-R','-p',str(STORE)))
    (backup/'receipt.json').write_text(json.dumps({'recovery_key_sha256':hashlib.sha256(recovery.read_bytes()).hexdigest(),'status':'installation-started'}))
    run('groupadd','--system','hive-code-upload')
    for user in ('hive-code-upload','hive-code-publisher'):
        run('useradd','--system','--gid','hive-code-upload','--home-dir','/var/lib/'+user,'--shell','/bin/sh',user)
        run('passwd','-l',user)
    BASE.mkdir(mode=0o755)
    for name,b64 in PAYLOAD.items():(BASE/name).write_bytes(base64.b64decode(b64));(BASE/name).chmod(0o644)
    signers=CONFIG/'allowed_signers';signers.write_text('aster-hive namespaces="hive-release" '+signing+'\n');signers.chmod(0o644)
    store=STORE/'code';store.mkdir(mode=0o755);u=pwd.getpwnam('hive-code-publisher');os.chown(store,u.pw_uid,u.pw_gid)
    # Shared budget must be able to count memory directories, including future ones.
    run('setfacl','-R','-m','u:hive-code-publisher:r-X',str(STORE))
    for directory in [STORE,*[d for d in STORE.rglob('*') if d.is_dir()]]:
        run('setfacl','-m','d:u:hive-code-publisher:r-x',str(directory))
    run('setfacl','-m','u:hive-code-publisher:rw-,u:hive-recovery:r--',str(STORE/'receiver.lock'))
    config={'store':str(store),'budget_root':str(STORE),'signers':str(signers),'socket':'/run/hive-code/publisher.sock','budget':2*1024**3,'reserve':1024**3}
    (CONFIG/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    home=Path('/var/lib/hive-code-upload');(home/'.ssh').mkdir(parents=True,mode=0o755)
    command='/usr/bin/python3 /usr/local/lib/hive-code/code_transport.py bridge --config /etc/hive-code/config.json'
    (home/'.ssh/authorized_keys').write_text('restrict,command="'+command+'" '+upload+' hive-code-upload\n')
    (home/'.ssh/authorized_keys').chmod(0o644)
    replacement='command="/usr/bin/python3 /usr/local/lib/hive-code/code_transport.py reader --config /etc/hive-code/config.json"'
    recovery.write_text(old.replace(expected,replacement));recovery.chmod(0o644)
    unit='''[Unit]
Description=Hive signed code publisher (storage only)
After=local-fs.target
[Service]
User=hive-code-publisher
Group=hive-code-upload
ExecStart=/usr/bin/python3 /usr/local/lib/hive-code/code_publisher.py --config /etc/hive-code/config.json
RuntimeDirectory=hive-code
RuntimeDirectoryMode=0750
UMask=0022
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/hive-replica/code /var/lib/hive-replica/receiver.lock /run/hive-code
RestrictAddressFamilies=AF_UNIX
MemoryMax=512M
TasksMax=16
CPUQuota=100%
LimitFSIZE=134217728
[Install]
WantedBy=multi-user.target
'''
    (Path('/etc/systemd/system')/SERVICE).write_text(unit)
    # Preserve history/pins; new receiver changes only the opt-in directory ACL mask.
    # Replace wrapper/config while holding the existing receiver lock.
    if True:  # The installation-wide receiver lock is already held.
        memory_config['code_budget_reader']=True
        if isinstance(memory_config.get('test'),dict):memory_config['test']['code_budget_reader']=True
        # Embedded release helper provides durable atomic replacement; never imports uploaded code.
        import sys
        sys.path.insert(0,str(BASE))
        from code_release import atomic,canonical
        atomic(receiver_config,canonical(memory_config));receiver_config.chmod(0o644)
        wrapper='import os,sys\nos.execv("/usr/bin/python3", ["/usr/bin/python3", "/usr/local/lib/hive-code/replication.py"] + sys.argv[1:])\n'
        atomic(receiver_wrapper,wrapper.encode());receiver_wrapper.chmod(0o644)
    run('sshd','-t');run('systemctl','daemon-reload');run('systemctl','enable','--now',SERVICE)
    print(run('systemctl','is-active',SERVICE).decode().strip())
    print('Installed signed code publisher. Legacy export preserved; no code release activated.')
    print('Backups: '+str(backup))
    install_lock.close()

if __name__=='__main__':main()
