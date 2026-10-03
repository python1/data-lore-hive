"""Forced upload bridge, local uploader, and read-only recovery wrapper."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import code_release as c
import code_publisher as p
import replication as r


def upload(config,command,package=None,pin=None):
    with tempfile.TemporaryFile() as f:
        p.send(f,command,package,pin);f.seek(0)
        result=subprocess.run(r.ssh_command(config,'code-submit'),stdin=f,capture_output=True,timeout=300,check=True)
    reply=json.loads(result.stdout);c.require(reply.get('ok'),reply.get('error','Invalid receiver reply'))
    return reply['state']


def bridge(config):
    c.require(os.environ.get('SSH_ORIGINAL_COMMAND')=='code-submit','Upload command denied')
    # Bounded frame forwarding, no arbitrary socket commands or shell interpolation.
    import struct
    n=struct.unpack('!I',p.read_exact(sys.stdin.buffer,4))[0];c.require(n<=c.MAX_META,'Oversized header')
    raw=p.read_exact(sys.stdin.buffer,n);header=c.decode(raw)
    lengths=header.get('lengths',{})
    c.require(set(lengths)<=set(c.FILES),'Invalid files')
    c.require(all(type(v) is int and 0<=v<=(c.MAX_BUNDLE if k=='hive.bundle' else c.MAX_META) for k,v in lengths.items()),'Oversized upload')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
        sock.settimeout(300);sock.connect(config['socket']);sock.sendall(struct.pack('!I',n)+raw)
        for size in lengths.values():
            while size:
                block=p.read_exact(sys.stdin.buffer,min(size,1024*1024));sock.sendall(block);size-=len(block)
        sock.shutdown(socket.SHUT_WR)
        with sock.makefile('rb') as f:reply=f.read(c.MAX_META*4)
        sys.stdout.buffer.write(reply)


def main():
    a=argparse.ArgumentParser();a.add_argument('action',choices=['bridge','reader','upload','verify']);a.add_argument('--config');a.add_argument('--command',default='candidate');a.add_argument('--package');a.add_argument('--pin');a.add_argument('--signers');a.add_argument('--receipt');a.add_argument('--state');v=a.parse_args()
    if v.action=='verify':
        print(json.dumps(c.bootstrap_verify(v.package,v.signers,v.receipt,v.state),indent=2));return
    config=json.loads(Path(v.config).read_text())
    if v.action=='bridge':bridge(config)
    elif v.action=='reader':
        command=os.environ.get('SSH_ORIGINAL_COMMAND','')
        if command.startswith('code-'):p.read(config,command,sys.stdout.buffer)
        else:
            sys.path.insert(0,'/usr/local/lib/hive-recovery')
            import recovery_server
            recovery_server.serve(recovery_server.EXPORT,command,sys.stdout.buffer)
    else:print(json.dumps(upload(config,v.command,v.package,json.loads(Path(v.pin).read_text()) if v.pin else None),indent=2))

if __name__=='__main__':
    try:main()
    except Exception as e:print('Code recovery refused: '+str(e),file=sys.stderr);sys.exit(1)
