"""Storage-only publisher. Authenticated socket requests; shared memory budget/lock."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import struct
import tempfile
import time
import code_release as c
import replication as r


def read_exact(stream, n):
    chunks=[]
    while n:
        block=stream.read(min(n,1024*1024));c.require(block,'Interrupted transfer')
        chunks.append(block);n-=len(block)
    return b''.join(chunks)


def send(stream, command, package=None, pin=None):
    lengths={name:(Path(package)/name).stat().st_size for name in c.FILES} if package else {}
    header=c.canonical({'command':command,'lengths':lengths,'pin':pin})
    stream.write(struct.pack('!I',len(header)));stream.write(header)
    if package:
        for name in c.FILES:
            with (Path(package)/name).open('rb') as f:shutil.copyfileobj(f,stream)
    stream.flush()


def state(root):
    p=Path(root)/'index.json'
    return c.decode(p.read_bytes()) if p.exists() else {'sequence':0,'current':None,'pin':None,'pin_sequence':0,'last_time':0,'releases':{},'candidates':{}}


def budget(config, extra):
    root=Path(config['budget_root'])
    total=0
    def inaccessible(error):raise ValueError('Cannot account for all storage: '+str(error))
    for directory,dirs,files in os.walk(root,onerror=inaccessible):
        for name in dirs+files:
            path=Path(directory)/name
            c.require(not path.is_symlink(),'Storage symlink cannot be budgeted')
        total+=sum((Path(directory)/name).stat().st_size for name in files)
    c.require(total+extra <= config.get('budget',r.BUDGET),'Combined storage budget exceeded')
    c.require(shutil.disk_usage(root).free-extra >= config.get('reserve',r.RESERVE),'Free-space reserve breached')


def kept(index):
    entries=index['releases'];ordered=sorted(entries,key=lambda h:entries[h]['sequence'],reverse=True)
    keep=set(ordered[:3]);weekly={};monthly={}
    # Earliest accepted release in each period; rolling newest periods.
    for h in reversed(ordered):
        t=datetime.fromtimestamp(entries[h]['accepted_at'],timezone.utc)
        weekly.setdefault(t.strftime('%G-%V'),h);monthly.setdefault(t.strftime('%Y-%m'),h)
    keep.update(weekly[k] for k in sorted(weekly)[-2:]);keep.update(monthly[k] for k in sorted(monthly)[-2:])
    keep.update(h for h in (index['current'],index['pin']) if h)
    return keep


def prune(root,index):
    retain=kept(index)
    index['releases']={h:v for h,v in index['releases'].items() if h in retain}
    candidates=sorted(index['candidates'],key=lambda h:index['candidates'][h]['accepted_at'],reverse=True)[:2]
    index['candidates']={h:index['candidates'][h] for h in candidates}
    # Durable index before deletion. Crash leftovers are cleaned on the next request.
    c.atomic(root/'index.json',c.canonical(index))
    (root/'index.json').chmod(0o644)  # Recovery identity may read, never write.
    keep=retain|set(candidates)
    for p in (root/'objects').iterdir():
        if p.name not in keep:shutil.rmtree(p)


def publish(config,stream, now=None, fault=lambda stage:None):
    now=time.time() if now is None else now
    root=Path(config['store']);root.mkdir(exist_ok=True);(root/'objects').mkdir(exist_ok=True)
    # Same lock as memory acceptance: concurrent writes cannot overcommit budget.
    with r.locked(config['budget_root']):
        header_size=struct.unpack('!I',read_exact(stream,4))[0]
        c.require(header_size<=c.MAX_META,'Oversized header')
        header=c.decode(read_exact(stream,header_size))
        c.require(set(header)=={'command','lengths','pin'},'Unexpected request fields')
        command=header['command'];c.require(command in {'candidate','approve','pin','status'},'Command denied')
        index=state(root);c.require(now>=index['last_time'],'Receiver clock rollback')
        if command=='status':
            c.require(not header['lengths'] and header['pin'] is None,'Unexpected status data');return index
        if command=='pin':
            c.require(not header['lengths'],'Unexpected pin data')
            data=header['pin'];c.require(isinstance(data,dict) and set(data)=={'manifest','signature'},'Invalid pin')
            raw=data['manifest'].encode();pin=c.decode(raw)
            c.verify_signature(raw,data['signature'].encode(),config['signers'])
            c.require(set(pin)=={'project','action','sequence','release','drill_sha256'},'Invalid pin fields')
            c.require(pin['project']==c.PROJECT and pin['action']=='recovery-tested','Wrong pin purpose')
            c.require(type(pin['sequence']) is int and pin['sequence']>index['pin_sequence'],'Pin rollback/replay')
            c.require(pin['release'] in index['releases'],'Pin release not retained')
            c.require(re.fullmatch('[0-9a-f]{64}',pin['drill_sha256']) is not None,'Missing drill evidence hash')
            # Pin is attested by operator, not inferred from upload success.
            index.update(pin=pin['release'],pin_sequence=pin['sequence'],pin_approval=data,last_time=now)
            budget(config,len(raw)+len(data['signature'])+c.MAX_META)
            prune(root,index);return index
        c.require(header['pin'] is None and set(header['lengths'])==set(c.FILES),'Invalid artifact list')
        for name,size in header['lengths'].items():
            c.require(type(size) is int and 0<=size<=(c.MAX_BUNDLE if name=='hive.bundle' else c.MAX_META),'Oversized artifact')
        # Clean only unreferenced leftovers, under the same lock; never protected generations.
        for stale in root.glob('.incoming-*'):shutil.rmtree(stale)
        referenced=set(index['releases'])|set(index['candidates'])
        for stale in (root/'objects').iterdir():
            if stale.name not in referenced:shutil.rmtree(stale)
        budget(config,3*sum(header['lengths'].values())+c.MAX_META*4)
        # Abort/crash staging can never be served. Delete stale staging while locked.
        for p in root.glob('.incoming-*'):shutil.rmtree(p)
        with tempfile.TemporaryDirectory(prefix='.incoming-',dir=root) as tmp:
            p=Path(tmp);p.chmod(0o755)
            for name in c.FILES:
                with (p/name).open('wb') as f:
                    remain=header['lengths'][name]
                    while remain:
                        block=read_exact(stream,min(remain,1024*1024));f.write(block);remain-=len(block)
                    f.flush();os.fsync(f.fileno())
                (p/name).chmod(0o644)
            fault('received')
            m=c.validate(p,config['signers'] if command=='approve' else None)
            h=c.digest((p/'manifest.json').read_bytes())
            if command=='approve':
                if m['sequence']==index['sequence']:
                    c.require(h==index['current'],'Conflicting release sequence');return index
                c.require(m['sequence']>index['sequence'],'Release rollback')
            target=root/'objects'/h
            if target.exists():
                c.require(all((target/n).read_bytes()==(p/n).read_bytes() for n in c.FILES),'Conflicting existing artifact')
            else:
                # tmp context may remove an empty recreated dir; rename is durable before pointer.
                os.rename(p,target);target.chmod(0o755);r.sync_dir(root/'objects')
            fault('stored')
            entry={'commit':m['commit'],'sequence':m['sequence'],'accepted_at':now}
            if command=='approve':index['releases'][h]=entry;index.update(sequence=m['sequence'],current=h)
            else:
                index['candidates'][h]=entry
                index['latest_candidate']=h
            index['last_time']=now
            fault('before_index');prune(root,index)
            return index


def read(config,command,output):
    parts=command.split();root=Path(config['store'])
    # Read-only lock acquisition; recovery identity gets no write permission.
    with open(Path(config['budget_root'])/'receiver.lock','rb') as lock:
        fcntl.flock(lock,fcntl.LOCK_SH)
        index=state(root)
        if parts==['code-status']:
            output.write(c.canonical(index));return
        c.require(len(parts)==3 and parts[0]=='code-fetch','Recovery command denied')
        h,name=parts[1:]
        c.require(re.fullmatch('[0-9a-f]{64}',h) is not None and name in c.FILES,'Invalid release fetch')
        c.require(h in index['releases'] or h in index['candidates'],'Release not retained')
        path=root/'objects'/h/name
        with path.open('rb') as f:shutil.copyfileobj(f,output)


def daemon(config):
    path=config['socket']
    if os.path.exists(path):os.unlink(path)
    sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);sock.bind(path);os.chmod(path,0o660);sock.listen(4)
    while True:
        conn,_=sock.accept();conn.settimeout(60)
        with conn:
            try:
                with conn.makefile('rb') as f:reply={'ok':True,'state':publish(config,f)}
            except Exception as e:reply={'ok':False,'error':str(e)}
            conn.sendall(c.canonical(reply))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',required=True);a=p.parse_args()
    daemon(json.loads(Path(a.config).read_text()))
