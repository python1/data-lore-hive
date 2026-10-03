"""Auto-sync transports candidates and approvals; cannot sign a release."""
import json
from pathlib import Path
import shutil
import time
import code_builder
import code_release as c
import code_transport


def tick(config, now=None, notifier=lambda text:None):
    now=time.time() if now is None else now
    root=Path(config['state_dir'])/'code-sync';root.mkdir(exist_ok=True)
    status_path=root/'status.json'
    status=json.loads(status_path.read_text()) if status_path.exists() else {}
    try:
        remote=code_transport.upload(config['ssh'],'status')
        commit=c.git('rev-parse','refs/heads/master^{commit}',cwd=config['repo']).decode().strip()
        status.update(master_commit=commit,latest_approved=remote['current'],last_recovery_tested=remote['pin'],legacy_export='separate; not checked by this status call')
        candidate=root/commit
        if not any(v['commit']==commit for v in remote['candidates'].values()):
            if candidate.exists():
                try:c.validate(candidate)
                except Exception:shutil.rmtree(candidate)
            if not candidate.exists():code_builder.build(config['repo'],candidate)
            remote=code_transport.upload(config['ssh'],'candidate',candidate)
        status['backed_up_master']=commit
        # Sorted by signed sequence, never directory names. Local writer cannot mint signatures.
        approvals=[]
        for p in Path(config['approvals']).iterdir():
            if p.is_dir():
                m=c.validate(p,config['signers']);approvals.append((m['sequence'],p,m))
        for sequence,p,m in sorted(approvals):
            if sequence<remote['sequence']:continue
            remote=code_transport.upload(config['ssh'],'approve',p)
        status.update(status='ok',last_success=now,pending_master=False,
                      latest_approved=remote['current'],last_recovery_tested=remote['pin'],
                      approval_pending=not remote['current'] or remote['releases'][remote['current']]['commit']!=commit,
                      retained_releases=len(remote['releases']),retained_candidates=len(remote['candidates']),
                      failure_since=None,last_error=None)
        if status['approval_pending'] and status.get('last_candidate_notice')!=commit:
            notifier('Hive master '+commit[:12]+' is backed up; independent release signature is pending.')
            status['last_candidate_notice']=commit
        for p in root.iterdir():
            if p.is_dir() and len(p.name)==40 and p!=candidate:shutil.rmtree(p)
    except Exception as e:
        since=status.get('failure_since');since=now if since is None else since
        status.update(status='failed',failure_since=since,last_error=str(e),pending_master='unknown')
        if now-since>=1800 and now-status.get('last_alert',-7200)>=7200:
            try:notifier('Hive code sync failed: '+str(e)[:180]);status['last_alert']=now
            except Exception:pass
    status['last_attempt']=now;c.atomic(status_path,c.canonical(status));return status
