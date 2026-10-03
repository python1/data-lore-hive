#!/usr/bin/env python3
"""Operator-only replica CT rollback: restore legacy reader and disable publication, preserve artifacts."""
import os
from pathlib import Path
import subprocess


def main():
    if os.geteuid()!=0 or os.uname().nodename!='replica-host':raise SystemExit('replica CT root only')
    config=Path('/etc/hive-code');backup=config/'backups'
    key=Path('/var/lib/hive-recovery/.ssh/authorized_keys')
    expected='command="/usr/bin/python3 /usr/local/lib/hive-code/code_transport.py reader --config /etc/hive-code/config.json"'
    if key.read_text().count(expected)!=1:raise SystemExit('Recovery key changed; stop for manual review')
    original=(backup/'authorized_keys').read_bytes()
    if b'command="/usr/bin/python3 /usr/local/lib/hive-recovery/recovery_server.py"' not in original:raise SystemExit('Unexpected backup')
    upload=Path('/var/lib/hive-code-upload/.ssh/authorized_keys')
    saved=backup/'disabled-upload-authorized_keys'
    if saved.exists():raise SystemExit('Rollback already attempted; stop for inspection')
    subprocess.run(['systemctl','disable','--now','hive-code-publisher.service'],check=True)
    upload.rename(saved)
    key.write_bytes(original);key.chmod(0o644)
    import fcntl,sys
    sys.path.insert(0,'/usr/local/lib/hive-code')
    with open('/var/lib/hive-replica/receiver.lock','a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        from code_release import atomic
        atomic('/etc/hive-replica/config.json',(backup/'memory-config.json').read_bytes())
        Path('/etc/hive-replica/config.json').chmod(0o644)
        atomic('/usr/local/lib/hive-replica/replication.py',(backup/'memory-wrapper.py').read_bytes())
        Path('/usr/local/lib/hive-replica/replication.py').chmod(0o644)
        subprocess.run(['setfacl','--restore='+str(backup/'store.acl')],check=True)
    subprocess.run(['sshd','-t'],check=True)
    print('Publisher disabled; upload access removed; legacy recovery reader restored.')
    print('Code artifacts, config, service definition, accounts and backups preserved for inspection.')
    print('Pause the Mac code-sync configuration separately; memory sync is unchanged.')
if __name__=='__main__':main()
