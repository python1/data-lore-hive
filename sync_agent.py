#!/usr/bin/env python3
"""User-session sync and independent heartbeat watchdog; no root or inference."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import replication as r
from retention import atomic, POLICY

FAIL_AFTER = 1800
REPEAT_AFTER = 7200
STALE_AFTER = 1200


@contextmanager
def run_lock(root, name='sync.lock'):
    root = Path(root); root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(root/name, 'a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def log(config, name, value):
    directory = Path(config['log_dir']); directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    handler = RotatingFileHandler(directory/(name+'.jsonl'), maxBytes=2*1024**2, backupCount=4)
    logger = logging.getLogger('hive-'+name); logger.setLevel(logging.INFO); logger.propagate = False
    logger.addHandler(handler)
    try: logger.info(json.dumps(value, sort_keys=True))
    finally: logger.removeHandler(handler); handler.close()


def notify(message):
    result = subprocess.run(['/usr/bin/osascript', '-e', 'on run argv',
                             '-e', 'display notification (item 1 of argv) with title "Hive sync"',
                             '-e', 'end run', message], capture_output=True, text=True, timeout=15)
    return {'exit': result.returncode, 'stderr': result.stderr.strip()}


def read_state(path):
    return json.loads(path.read_text()) if path.exists() else {}


def critical(error):
    if isinstance(error, subprocess.CalledProcessError):
        detail = (error.stderr or b'')
        if isinstance(detail, bytes): detail = detail.decode(errors='replace')
    else: detail = str(error)
    words = ('history', 'hash', 'integrity', 'budget', 'reserve', 'clock', 'pin', 'schema', 'identity', 'protocol', 'retention', 'snapshot size')
    return any(word in detail.lower() for word in words), detail


def attempt(config, now=None, notifier=notify):
    real_clock = now is None
    now = time.time() if now is None else now
    root = Path(config['state_dir']); state_file = root/'status.json'
    try:
        with run_lock(root):
            state = read_state(state_file)
            state.update(last_attempt=now, heartbeat=now, running=True, pending_changes='unknown')
            atomic(state_file, state)
            try:
                remote = r.transfer(config, 'status')
                r.require(remote.get('protocol') == 2 and remote.get('retention_policy') == POLICY,
                          'Receiver retention protocol not ready; no upload permitted')
                m = remote['manifest']
                r.require(m['database_id'] == config['database_id'], 'Replica identity mismatch')
                state['last_replica_contact'] = now
                state['replica'] = remote
                with tempfile.TemporaryDirectory(prefix='sync-', dir=root) as temp:
                    package = Path(temp)/'snapshot'
                    local = r.snapshot(config['database'], package, config['database_id'])
                    state['local_manifest'] = local
                    r.require(local['bytes'] <= remote['max_snapshot_bytes'], 'Snapshot size exceeds retention cap')
                    same = all(local[k] == m[k] for k in ('event_count', 'chain_head', 'database_id'))
                    state['pending_changes'] = not same
                    r.require(local['event_count'] >= m['event_count'], 'Local history rollback relative to replica')
                    if same:
                        outcome = 'unchanged'
                    else:
                        reply = r.transfer(config, 'push', package)
                        r.require(reply.get('retention_policy') == POLICY, 'Unexpected retention acknowledgement')
                        state['last_upload'] = now
                        m = reply['manifest']; outcome = reply['status']
                recovered = state.get('failure_since') is not None
                state.update(status=outcome, acknowledged_manifest=m, last_success=now,
                             pending_changes=False, failure_since=None, last_error=None, consecutive_failures=0)
                if recovered:
                    try:
                        state['notification'] = notifier('Hive sync recovered; replica CT matches the last checked primary history.')
                    except Exception as error:
                        state['notification'] = {'error': str(error)}
            except Exception as error:
                urgent, detail = critical(error)
                since = state.get('failure_since')
                since = now if since is None else since
                state.update(status='failed', failure_since=since, last_error=detail,
                             pending_changes=state.get('pending_changes', 'unknown'),
                             consecutive_failures=state.get('consecutive_failures', 0)+1)
                due = urgent or now-since >= FAIL_AFTER
                previous_alert = state.get('last_failure_alert')
                if due and (previous_alert is None or now-previous_alert >= REPEAT_AFTER):
                    try:
                        state['notification'] = notifier('Hive sync failed: '+detail[:180]+'. Check HiveSync status/logs.')
                        if state['notification'].get('exit') == 0: state['last_failure_alert'] = now
                    except Exception as notification_error:
                        state['notification'] = {'error': str(notification_error)}
            state.update(heartbeat=time.time() if real_clock else now, running=False)
            atomic(state_file, state); log(config, 'sync', state)
            return state
    except BlockingIOError:
        result = {'status': 'skipped_busy', 'time': now}
        # Separate log avoids rotation races with the process holding the main lock.
        log(config, 'busy', result)
        return result


def watchdog(config, now=None, notifier=notify):
    now = time.time() if now is None else now
    root = Path(config['state_dir'])
    with run_lock(root, 'watchdog.lock'):
        state = read_state(root/'status.json'); health = read_state(root/'watchdog.json')
        heartbeat = state.get('heartbeat', config.get('installed_at', now))
        stale = now-heartbeat > STALE_AFTER
        if stale and (health.get('last_alert') is None or now-health['last_alert'] >= REPEAT_AFTER):
            try:
                result = notifier('Hive sync heartbeat is stale. The sync agent may have stopped; check HiveSync status.')
                health['notification'] = result
                if result.get('exit') == 0: health['last_alert'] = now
            except Exception as error: health['notification'] = {'error': str(error)}
        elif not stale and health.get('stale'):
            health['notification'] = notifier('Hive sync heartbeat has resumed.')
        health.update(stale=stale, checked_at=now, heartbeat=heartbeat)
        atomic(root/'watchdog.json', health); log(config, 'watchdog', health)
        return health


def failure_test(config, notifier=notify):
    """Exercise delayed failure alert with isolated state and no network calls."""
    from unittest.mock import patch
    now = time.time()
    with tempfile.TemporaryDirectory(prefix='hive-alert-test-') as temp:
        isolated = {**config, 'state_dir': temp, 'log_dir': str(Path(temp)/'logs')}
        atomic(Path(temp)/'status.json', {'failure_since': now-FAIL_AFTER-1})
        with patch.object(r, 'transfer', side_effect=OSError('TEST ONLY: simulated receiver unreachable')):
            result = attempt(isolated, now=now, notifier=notifier)
        return {'test_mode': True, 'network_calls': 0, 'production_state_modified': False,
                'simulated_failure_duration_seconds': FAIL_AFTER+1,
                'status': result['status'], 'notification': result.get('notification'),
                'alert_recorded': 'last_failure_alert' in result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['sync', 'watchdog', 'status', 'notify-test'])
    parser.add_argument('--config', required=True)
    args = parser.parse_args(); config = json.loads(Path(args.config).read_text())
    if args.action == 'status':
        print(json.dumps(read_state(Path(config['state_dir'])/'status.json'), indent=2)); return
    if args.action == 'notify-test':
        result = failure_test(config)
        print(json.dumps(result, indent=2))
        raise SystemExit(0 if result['alert_recorded'] else 1)
    # Bound hung model-free snapshots/SSH runs. A killed job leaves a stale heartbeat.
    signal.alarm(240)
    result = attempt(config) if args.action == 'sync' else watchdog(config)
    print(json.dumps({'status': result.get('status', 'watchdog'), 'last_error': result.get('last_error')}))
    raise SystemExit(1 if result.get('status') == 'failed' else 0)


if __name__ == '__main__':
    main()
