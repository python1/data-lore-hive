"""Receiver-side tiered retention. Pins come only from root-owned configuration."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import replication as r

MAX_SNAPSHOT = 96 * 1024**2
POLICY = 'recent3-hourly6-daily7-pin1-v2'


def atomic(path, value):
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix='.state-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(r.canonical(value) + b'\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path); r.sync_dir(path.parent)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def pin_set(config):
    pins = config.get('pins', [])
    r.require(len(pins) == 1 and re.fullmatch('[0-9a-f]{64}', pins[0]), 'Exactly one operator pin is required')
    return set(pins)


def empty(now):
    return {'version': 2, 'current': None, 'last_time': now, 'generations': {}, 'hourly': {}, 'daily': {}}


def add(state, manifest, now, pins):
    r.require(now >= state['last_time'], 'Receiver clock moved backwards')
    state = json.loads(json.dumps(state))
    digest = manifest['sha256']
    state['generations'][digest] = {'accepted_at': now, 'event_count': manifest['event_count']}
    state['current'] = digest; state['last_time'] = now
    for field, period, count in [('hourly', 3600, 6), ('daily', 86400, 7)]:
        state[field].setdefault(str(int(now // period)), digest)
        keys = sorted(state[field], key=int)[-count:]
        state[field] = {k: state[field][k] for k in keys}
    recent = sorted(state['generations'], key=lambda k: state['generations'][k]['event_count'])[-3:]
    keep = set(recent) | set(state['hourly'].values()) | set(state['daily'].values()) | pins
    r.require(pins <= state['generations'].keys(), 'Operator-pinned generation is missing')
    state['generations'] = {k: v for k, v in state['generations'].items() if k in keep}
    return state


def load(config, now):
    root, identity = Path(config['store']), config['database_id']
    pins = pin_set(config); index = root / 'retention.json'
    if index.exists():
        state = json.loads(index.read_text())
        r.require(state['version'] == 2 and pins <= state['generations'].keys(), 'Invalid retention state or missing pin')
        r.require(state['current'] in state['generations'], 'Missing retained current')
    else:
        # One-time migration preserves every legacy generation (maximum three).
        previous, manifest = r.current(root, identity)
        state = empty(now)
        if previous:
            folders = list((root / 'generations').iterdir())
            all_manifests = sorted((r.validate(p, identity) for p in folders), key=lambda m: m['event_count'])
            r.require(pins <= {m['sha256'] for m in all_manifests}, 'Pinned migration checkpoint missing')
            for m in all_manifests:
                r.prefix_matches(root/'generations'/m['sha256']/'knowledge.sqlite3', previous/'knowledge.sqlite3')
                state['generations'][m['sha256']] = {'accepted_at': now, 'event_count': m['event_count']}
            state = add(state, all_manifests[0], now, pins)
            # Restore all original recent generations after seeding first bucket.
            for m in all_manifests[1:]: state = add(state, m, now, pins)
            r.require(state['current'] == manifest['sha256'], 'Migration current mismatch')
            atomic(index, state)
        else:
            r.require(not list((root/'generations').glob('*')), 'Missing current pointer with existing generations')
    if state['current']:
        current_db = root/'generations'/state['current']/'knowledge.sqlite3'
        for digest, meta in state['generations'].items():
            r.require(re.fullmatch('[0-9a-f]{64}', digest), 'Invalid generation ID')
            m = r.validate(root/'generations'/digest, identity)
            r.require(m['sha256'] == digest and m['event_count'] == meta['event_count'], 'Retention metadata mismatch')
            r.prefix_matches(root/'generations'/digest/'knowledge.sqlite3', current_db)
    return state


def accept(config, stream, now=None):
    now = time.time() if now is None else now
    root = Path(config['store']); identity = config['database_id']; pins = pin_set(config)
    with r.locked(root):
        state = load(config, now)
        r.require(now >= state['last_time'], 'Receiver clock moved backwards')
        for p in root.glob('.incoming-*'):
            if p.is_dir() and not p.is_symlink(): shutil.rmtree(p)
        def preflight(size):
            r.require(r.usage(root) + size <= config.get('budget', r.BUDGET), 'Replication storage budget exceeded')
            global_root = Path(config.get('budget_root', root))
            r.require(r.usage(global_root) + size <= r.BUDGET, 'Combined storage budget exceeded')
            r.require(shutil.disk_usage(root).free - size >= config.get('reserve', r.RESERVE), 'Free-space reserve would be breached')
        with tempfile.TemporaryDirectory(prefix='.incoming-', dir=root) as temp:
            r.receive(stream, temp, preflight, max_snapshot=MAX_SNAPSHOT)
            m = r.validate(temp, identity); preflight(0)
            previous = state['current']
            if previous:
                folder = root/'generations'/previous
                old = r.validate(folder, identity)
                r.prefix_matches(folder/'knowledge.sqlite3', Path(temp)/'knowledge.sqlite3')
                if old['event_count'] == m['event_count']:
                    return {'status': 'unchanged', 'manifest': old, 'retention_policy': POLICY}
            proposed = add(state, m, now, pins)
            generations = root/'generations'; generations.mkdir(exist_ok=True)
            target = generations/m['sha256']
            if target.exists(): r.require(r.validate(target, identity) == m, 'Conflicting pending generation')
            else: os.rename(temp, target); r.sync_dir(generations)
            atomic(root/'retention.json', proposed)  # Sole authoritative v2 commit point.
            # Every old/current pin is protected by the committed index before pruning.
            for folder in generations.iterdir():
                if folder.name not in proposed['generations']:
                    r.validate(folder, identity)
                    shutil.rmtree(folder)
            r.sync_dir(generations)
            return {'status': 'accepted', 'manifest': m, 'retention_policy': POLICY}


def status(config):
    root = Path(config['store'])
    with r.locked(root):
        state = load(config, time.time())
        r.require(state['current'], 'No accepted generation')
        return {'manifest': r.validate(root/'generations'/state['current'], config['database_id']),
                'protocol': 2, 'retention_policy': POLICY, 'pins': sorted(pin_set(config)),
                'retained': state, 'generations': len(state['generations']), 'stored_bytes': r.usage(root),
                'free_bytes': shutil.disk_usage(root).free, 'max_snapshot_bytes': MAX_SNAPSHOT}


def fetch(config, digest, stream):
    root = Path(config['store'])
    with r.locked(root):
        state = load(config, time.time())
        digest = digest or state['current']
        r.require(digest in state['generations'], 'Generation is not retained')
        folder = root/'generations'/digest
        r.validate(folder, config['database_id']); r.send(folder, stream)


def dispatch(config, command, stdin, stdout):
    parts = command.split()
    testing = parts[:1] == ['test']
    if testing:
        r.require('test' in config, 'Validation namespace disabled')
        config = config['test']; parts = parts[1:]
    r.require(parts, 'Command is not permitted')
    if parts == ['push'] or (testing and len(parts) == 2 and parts[0] == 'push' and parts[1].isdigit()):
        now = int(parts[1]) if len(parts) == 2 else None
        stdout.write(r.canonical(accept(config, stdin, now)) + b'\n')
    elif parts in (['status'], ['list']):
        stdout.write(r.canonical(status(config)) + b'\n')
    elif parts == ['fetch'] or (len(parts) == 2 and parts[0] == 'fetch' and re.fullmatch('[0-9a-f]{64}', parts[1])):
        fetch(config, parts[1] if len(parts) == 2 else None, stdout)
    else: raise ValueError('Command is not permitted')
    stdout.flush()
