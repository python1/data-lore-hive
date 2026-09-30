#!/usr/bin/env python3
"""Forced-command reader for a root-owned immutable replica CT recovery export."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

EXPORT = '/var/lib/hive-replica/recovery-export'


def serve(root, command, stream):
    root = Path(root)
    release = json.loads((root/'release.json').read_text())
    sha = release['checkpoint']['sha256']
    if command == 'release':
        name = 'release.json'
    elif command == 'code':
        name = 'hive-recovery.bundle'
    elif command == 'status':
        stream.write((json.dumps({'manifest': release['checkpoint'], 'read_only': True})+'\n').encode())
        return
    elif command in ('fetch', 'fetch '+sha):
        name = 'checkpoint.wire'
    else:
        raise ValueError('Recovery account permits only release, code, status, and approved checkpoint fetch')
    path = root/name
    if name == 'hive-recovery.bundle':
        if hashlib.sha256(path.read_bytes()).hexdigest() != release['bundle_sha256']:
            raise ValueError('Recovery bundle hash mismatch')
    with path.open('rb') as source:
        shutil.copyfileobj(source, stream)
    stream.flush()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', default=EXPORT)
    args=parser.parse_args()
    try:
        serve(args.export, os.environ.get('SSH_ORIGINAL_COMMAND',''), sys.stdout.buffer)
    except (ValueError,OSError,KeyError) as error:
        print('Recovery refused: '+str(error),file=sys.stderr)
        raise SystemExit(1)


if __name__=='__main__':main()
