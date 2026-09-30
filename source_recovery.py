#!/usr/bin/env python3
"""Recreate ingested text without changing source IDs or trusting stored paths."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

LIMIT = 256_000
MANIFEST = 'source-recovery.json'


def entries_for(sources):
    entries = {}
    for source in sources:
        sid = source['id']
        if not re.fullmatch(r'[0-9a-f-]{36}', sid):
            raise ValueError('Invalid source event ID')
        suffix = Path(source['path']).suffix.lower()
        if suffix not in ('.md', '.txt'):
            raise ValueError('Unsupported source extension')
        raw = source['text'].encode('utf-8')
        if (not raw or len(raw) > LIMIT or b'\0' in raw
                or hashlib.sha256(raw).hexdigest() != source['sha256']):
            raise ValueError('Stored source snapshot hash/content invalid')
        entries[sid] = {'path': f'sources/{sid}/source{suffix}',
                        'original_path': source['path'], 'sha256': source['sha256']}
    return {'version': 1, 'sources': entries}


@contextmanager
def directory(root, parts=(), create=False):
    root = Path(root).absolute()
    if create:
        root.mkdir(parents=True, exist_ok=True)
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts:
            if part in ('', '.', '..') or '/' in part:
                raise ValueError('Invalid recovery path')
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        yield fd
    finally:
        os.close(fd)


def read_at(fd, name, limit):
    file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(file_fd, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError('Recovered path is not a regular file')
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('Recovered file exceeds limit')
    return raw


def publish(fd, name, raw):
    """Atomic no-clobber link; an existing path must contain exactly the same bytes."""
    try:
        existing = read_at(fd, name, len(raw))
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if existing != raw:
            raise ValueError('Existing recovery path conflicts; refusing overwrite')
        return
    temp = '.pending-' + str(uuid.uuid4())
    f = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(f, 'wb') as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        try:
            os.link(temp, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        except FileExistsError:
            if read_at(fd, name, len(raw)) != raw:
                raise ValueError('Concurrent recovery path conflict; refusing overwrite')
        os.fsync(fd)
    finally:
        os.unlink(temp, dir_fd=fd)


def recover(db, root):
    import knowledge
    sources = knowledge.latest_sources(db)
    manifest = entries_for(sources)
    encoded = (json.dumps(manifest, sort_keys=True, indent=2) + '\n').encode()
    # Never replace a previously published map, even for a newer source version.
    with directory(root, create=True) as fd:
        try:
            previous = read_at(fd, MANIFEST, max(len(encoded), 1_000_000))
        except FileNotFoundError:
            previous = None
        if previous is not None and previous != encoded:
            raise ValueError('Existing recovery manifest conflicts; use a new recovery directory')
    for source in sources:
        entry = manifest['sources'][source['id']]
        parts = entry['path'].split('/')
        raw = source['text'].encode('utf-8')
        with directory(root, parts[:-1], create=True) as fd:
            publish(fd, parts[-1], raw)
            if hashlib.sha256(read_at(fd, parts[-1], LIMIT)).hexdigest() != source['sha256']:
                raise ValueError('Recreated source failed read-back verification')
    for source in sources:
        read_source(root, manifest['sources'][source['id']], source['sha256'])
    with directory(root) as fd:
        publish(fd, MANIFEST, encoded)
    return manifest


def load_map(root, sources):
    expected = entries_for(sources)
    with directory(root) as fd:
        actual = json.loads(read_at(fd, MANIFEST, 1_000_000))
    if actual != expected:
        raise ValueError('Recovery manifest does not match latest database source snapshots')
    return actual['sources']


def read_source(root, entry, expected_hash):
    parts = entry['path'].split('/')
    with directory(root, parts[:-1]) as fd:
        raw = read_at(fd, parts[-1], LIMIT)
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise ValueError('Recovered source changed since ingestion')
    return raw.decode('utf-8'), expected_hash


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db', required=True)
    p.add_argument('--root', required=True)
    args = p.parse_args()
    print(json.dumps(recover(args.db, args.root), indent=2))


if __name__ == '__main__':
    main()
