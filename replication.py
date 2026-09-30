#!/usr/bin/env python3
"""Storage-only, one-way SQLite event replication. Python standard library only."""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import struct
import subprocess
import sys
import tempfile

VERSION = 1
BUDGET = 2 * 1024**3
RESERVE = 1024**3
MAX_SNAPSHOT = 512 * 1024**2
COLS = ('sequence', 'id', 'run_id', 'cookie', 'kind', 'recorded_at', 'payload')
ZERO = '0' * 64


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


@contextmanager
def database(path, immutable=True):
    uri = Path(path).resolve().as_uri() + '?mode=ro' + ('&immutable=1' if immutable else '')
    db = sqlite3.connect(uri, uri=True)
    try:
        db.execute('PRAGMA trusted_schema=OFF')
        yield db
    finally:
        db.close()


def inspect(path):
    """Hash raw event fields; verify order and the full embedded source contents."""
    with database(path) as db:
        require(db.execute('PRAGMA integrity_check').fetchall() == [('ok',)], 'SQLite integrity failure')
        objects = db.execute('SELECT type,name,sql FROM sqlite_master').fetchall()
        allowed = {'events', 'sqlite_sequence', 'sqlite_autoindex_events_1', 'no_update', 'no_delete'}
        require({r[1] for r in objects} == allowed, 'Unexpected database schema')
        require({name: kind for kind, name, _ in objects} == {
            'events': 'table', 'sqlite_sequence': 'table', 'sqlite_autoindex_events_1': 'index',
            'no_update': 'trigger', 'no_delete': 'trigger'}, 'Unexpected schema object types')
        require(tuple(r[1] for r in db.execute('PRAGMA table_info(events)')) == COLS, 'Unexpected event columns')
        # Preserve the original append-only enforcement, not just its trigger names.
        sql = {name: ' '.join((stmt or '').split()).lower() for _, name, stmt in objects}
        require(sql['events'] == 'create table events ( sequence integer primary key autoincrement, '
                'id text unique not null, run_id text not null, cookie text not null, kind text not null, '
                'recorded_at text not null, payload text not null )', 'Unexpected event constraints')
        require(sql['sqlite_sequence'] == 'create table sqlite_sequence(name,seq)', 'Invalid sequence schema')
        for action in ('update', 'delete'):
            expected = (f"create trigger no_{action} before {action} on events "
                        "begin select raise(abort, 'memory events are append-only'); end")
            require(sql['no_' + action] == expected, 'Invalid append-only trigger')
        head, count, sources, ids = ZERO, 0, 0, set()
        for row in db.execute('SELECT * FROM events ORDER BY sequence'):
            require(type(row[0]) is int and row[0] == count + 1, 'Event sequence gap or invalid order')
            require(all(type(v) is str for v in row[1:]), 'Invalid event field type')
            require(row[1] not in ids, 'Duplicate event ID')
            ids.add(row[1])
            payload = json.loads(row[6])
            require(isinstance(payload, dict), 'Event payload must be an object')
            if row[4] == 'source_ingested':
                require(type(payload.get('text')) is str, 'Missing source text')
                require(hashlib.sha256(payload['text'].encode()).hexdigest() == payload.get('sha256'),
                        'Source snapshot hash mismatch')
                sources += 1
            if row[4] == 'data':
                require('snapshot' in payload and hashlib.sha256(canonical(payload['snapshot'])).hexdigest()
                        == payload.get('source_sha256'), 'Fixture snapshot hash mismatch')
                sources += 1
            head = hashlib.sha256(bytes.fromhex(head) + canonical(dict(zip(COLS, row)))).hexdigest()
            count += 1
        seq = db.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchall()
        require(seq == [(count,)] if count else seq in ([], [(0,)]), 'Invalid sequence allocator')
        return {'event_count': count, 'first_sequence': 1 if count else 0,
                'last_sequence': count, 'chain_head': head, 'source_snapshots': sources}


def manifest_for(path, identity):
    require(re.fullmatch(r'[a-zA-Z0-9-]{1,80}', identity) is not None, 'Invalid database identity')
    size = Path(path).stat().st_size
    require(0 < size <= MAX_SNAPSHOT, 'Snapshot size out of bounds')
    return {'version': VERSION, 'database_id': identity, 'bytes': size, 'sha256': sha(path), **inspect(path)}


def validate(package, identity):
    package = Path(package)
    manifest = json.loads((package / 'manifest.json').read_text())
    actual = manifest_for(package / 'knowledge.sqlite3', identity)
    require(canonical(manifest) == canonical(actual), 'Manifest, identity, or content mismatch')
    return actual


def durable_file(path, data):
    with open(path, 'xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def snapshot(source, destination, identity):
    destination = Path(destination)
    destination.mkdir(mode=0o700)  # Never overwrite a previous snapshot.
    target = destination / 'knowledge.sqlite3'
    with database(source, immutable=False) as src:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
            dst.execute('PRAGMA journal_mode=DELETE')
        finally:
            dst.close()
    with open(target, 'rb') as stream:
        os.fsync(stream.fileno())
    manifest = manifest_for(target, identity)
    durable_file(destination / 'manifest.json', canonical(manifest) + b'\n')
    sync_dir(destination)
    return manifest


def read_exact(stream, size):
    result = bytearray()
    while len(result) < size:
        chunk = stream.read(min(size - len(result), 1024 * 1024))
        require(bool(chunk), 'Truncated transfer')
        result.extend(chunk)
    return bytes(result)


def send(package, stream):
    package = Path(package)
    raw = (package / 'manifest.json').read_bytes()
    stream.write(struct.pack('!I', len(raw)))
    stream.write(raw)
    with open(package / 'knowledge.sqlite3', 'rb') as db:
        shutil.copyfileobj(db, stream)
    stream.flush()


def receive(stream, destination, preflight=lambda size: None, max_snapshot=MAX_SNAPSHOT):
    size = struct.unpack('!I', read_exact(stream, 4))[0]
    require(0 < size <= 16384, 'Invalid manifest size')
    raw = read_exact(stream, size)
    manifest = json.loads(raw)
    count = manifest.get('bytes')
    require(type(count) is int and 0 < count <= max_snapshot, 'Invalid snapshot size')
    preflight(count + size + 4096)
    destination = Path(destination)
    durable_file(destination / 'manifest.json', raw)
    with open(destination / 'knowledge.sqlite3', 'xb') as db:
        remaining = count
        while remaining:
            data = read_exact(stream, min(remaining, 1024 * 1024))
            db.write(data)
            remaining -= len(data)
        db.flush()
        os.fsync(db.fileno())
    require(stream.read(1) == b'', 'Trailing transfer data')
    sync_dir(destination)


def prefix_matches(previous, incoming):
    with database(previous) as old, database(incoming) as new:
        cursor = iter(new.execute('SELECT * FROM events ORDER BY sequence'))
        for row in old.execute('SELECT * FROM events ORDER BY sequence'):
            require(next(cursor, None) == row, 'History rewrite, deletion, or rollback')


def current(root, identity):
    root = Path(root)
    index = root / 'retention.json'
    if index.exists():
        name = json.loads(index.read_text())['current']
        require(isinstance(name, str) and re.fullmatch(r'[0-9a-f]{64}', name), 'Invalid current pointer')
        package = root / 'generations' / name
        return package, validate(package, identity)
    pointer = root / 'current'
    if not pointer.exists():
        return None, None
    name = pointer.read_text().strip()
    require(re.fullmatch(r'[0-9a-f]{64}', name) is not None, 'Invalid current pointer')
    package = root / 'generations' / name
    manifest = validate(package, identity)
    require(name == manifest['sha256'], 'Generation name mismatch')
    return package, manifest


def usage(root):
    return sum(f.stat().st_size for f in Path(root).rglob('*') if f.is_file())


@contextmanager
def locked(root):
    root = Path(root)
    with open(root / 'receiver.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def accept(root, identity, stream, budget=BUDGET, reserve=RESERVE):
    root = Path(root)
    with locked(root):
        previous, old = current(root, identity)
        existing = list((root / 'generations').iterdir()) if (root / 'generations').exists() else []
        require(previous is not None or not existing, 'Missing current pointer with existing generations')
        # Detect damage to retained generations before accepting anything new.
        for folder in existing:
            stored = validate(folder, identity)
            require(folder.name == stored['sha256'], 'Generation name mismatch')
            if stored['event_count'] <= old['event_count']:
                prefix_matches(folder / 'knowledge.sqlite3', previous / 'knowledge.sqlite3')
        # A killed transfer leaves only staging data, never an accepted generation.
        for partial in root.glob('.incoming-*'):
            if partial.is_dir() and not partial.is_symlink():
                shutil.rmtree(partial)
        def preflight(size):
            require(usage(root) + size <= budget, 'Replication storage budget exceeded')
            require(shutil.disk_usage(root).free - size >= reserve, 'Free-space reserve would be breached')
        with tempfile.TemporaryDirectory(prefix='.incoming-', dir=root) as temp:
            receive(stream, temp, preflight)
            incoming = validate(temp, identity)
            preflight(0)
            if previous:
                prefix_matches(previous / 'knowledge.sqlite3', Path(temp) / 'knowledge.sqlite3')
                if incoming['event_count'] == old['event_count']:
                    return {'status': 'unchanged', 'manifest': old}
            for folder in existing:
                # A complete generation may remain after a crash before pointer publication.
                # Do not prune or accept past a conflicting/pending history.
                prefix_matches(folder / 'knowledge.sqlite3', Path(temp) / 'knowledge.sqlite3')
            generations = root / 'generations'
            generations.mkdir(exist_ok=True)
            target = generations / incoming['sha256']
            if target.exists():
                require(validate(target, identity) == incoming, 'Conflicting generation')
            else:
                os.rename(temp, target)
                sync_dir(generations)
            pointer = root / '.next-current'
            if pointer.exists():
                pointer.unlink()
            durable_file(pointer, (incoming['sha256'] + '\n').encode())
            os.replace(pointer, root / 'current')
            sync_dir(root)
            # Only after durable publication: remove accepted generations beyond three.
            retained = []
            for folder in generations.iterdir():
                m = validate(folder, identity)
                retained.append((m['event_count'], folder))
            for _, folder in sorted(retained, key=lambda item: (item[0], item[1].name), reverse=True)[3:]:
                shutil.rmtree(folder)
            sync_dir(generations)
            return {'status': 'accepted', 'manifest': incoming}


def serve(config):
    signal.alarm(300)  # Bound a stalled transfer/lock holder; SSH starts each invocation.
    root, identity = Path(config['store']), config['database_id']
    command = os.environ.get('SSH_ORIGINAL_COMMAND', '')
    if config.get('retention_policy') == 'recent3-hourly6-daily7-pin1-v2':
        import retention
        retention.dispatch(config, command, sys.stdin.buffer, sys.stdout.buffer)
        return
    require(command in {'push', 'fetch', 'status'}, 'Command is not permitted')
    if command == 'push':
        print(json.dumps(accept(root, identity, sys.stdin.buffer)))
    else:
        with locked(root):
            package, manifest = current(root, identity)
            require(package is not None, 'No accepted generation')
            if command == 'fetch':
                send(package, sys.stdout.buffer)
            else:
                print(json.dumps({'manifest': manifest, 'generations': len(list((root / 'generations').iterdir())),
                                  'stored_bytes': usage(root)}))


def ssh_command(config, command):
    agent = [] if config.get('use_ssh_agent') is True else ['-o', 'IdentityAgent=none']
    host_key = ['-o', 'HostKeyAlgorithms=ssh-ed25519'] if config.get('ed25519_host_only') is True else []
    return ['ssh', '-F', '/dev/null', '-T', '-i', config['key'], *agent, *host_key,
            '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
            '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
            config['remote'], command]


def transfer(config, command, package=None):
    if command == 'push':
        wanted = validate(package, config['database_id'])
        with tempfile.TemporaryFile() as wire:
            send(package, wire)
            wire.seek(0)
            result = subprocess.run(ssh_command(config, command), stdin=wire, capture_output=True, timeout=300, check=True)
        reply = json.loads(result.stdout)
        require(reply['manifest']['database_id'] == wanted['database_id']
                and reply['manifest']['chain_head'] == wanted['chain_head']
                and reply['manifest']['event_count'] == wanted['event_count'], 'Replica acknowledgement differs')
        return reply
    if command == 'status':
        result = subprocess.run(ssh_command(config, command), capture_output=True, timeout=30, check=True)
        return json.loads(result.stdout)
    raise ValueError('Unsupported transfer')


def restore(config, destination, expected, generation=None):
    destination = Path(destination)
    require(not any(Path(str(destination) + suffix).exists() for suffix in ('', '-wal', '-shm', '-journal')),
            'Restore destination or journals already exist')
    with tempfile.TemporaryDirectory(prefix='.restore-', dir=destination.parent) as temp:
        with tempfile.TemporaryFile() as wire:
            subprocess.run(ssh_command(config, 'fetch' + (' ' + generation if generation else '')), stdout=wire, stderr=subprocess.PIPE, timeout=300, check=True)
            wire.seek(0)
            receive(wire, temp)
        actual = validate(temp, config['database_id'])
        require(actual == expected, 'Recovery generation differs from the expected checkpoint')
        # Atomic no-clobber publication, same filesystem; never overwrite existing memory.
        os.link(Path(temp) / 'knowledge.sqlite3', destination)
        sync_dir(destination.parent)
        return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['snapshot', 'push', 'status', 'restore', 'serve'])
    parser.add_argument('--config', required=True)
    parser.add_argument('--package')
    parser.add_argument('--destination')
    parser.add_argument('--generation', help='Explicit retained SHA-256 to fetch (v2 receiver)')
    parser.add_argument('--expected-manifest')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    if args.command == 'serve':
        serve(config)
        return
    if args.command == 'snapshot':
        result = snapshot(config['database'], args.package, config['database_id'])
    elif args.command == 'restore':
        result = restore(config, args.destination, json.loads(Path(args.expected_manifest).read_text()), generation=args.generation)
    else:
        if args.command == 'push' and config.get('state_dir'):
            from sync_agent import run_lock
            with run_lock(Path(config['state_dir'])):
                result = transfer(config, args.command, args.package)
        else:
            result = transfer(config, args.command, args.package)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError, KeyError, TypeError) as error:
        print(f'Replication refused: {error}', file=sys.stderr)
        sys.exit(1)
