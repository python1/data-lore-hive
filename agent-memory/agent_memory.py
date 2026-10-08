#!/usr/bin/env python3
"""Turn your own Telegram JSON export into cited, verified memory for your local agent.

  inventory → init → propose → audit → review → approve → export → search
"""
import argparse
from collections import Counter
import json
import sys

import backends
import export_memory
import pipeline
import search_memory
import tg_export


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)

    s = sub.add_parser('inventory', help='metadata-only overview of an export (no message text)')
    s.add_argument('export')
    s.add_argument('--gap-hours', type=float, default=24)

    s = sub.add_parser('init', help='bind a run directory to one chat and two voices')
    s.add_argument('--run', required=True)
    s.add_argument('--export', required=True)
    s.add_argument('--chat', type=int, default=0, help='chat index from `inventory` (default 0)')
    s.add_argument('--user-id', required=True, help='Telegram from_id of the human, e.g. user123')
    s.add_argument('--agent-id', required=True, help='Telegram from_id of the agent/bot')
    s.add_argument('--user-name', default='User')
    s.add_argument('--agent-name', default='Agent')

    s = sub.add_parser('mask-report', help='count masked secret spans by kind (never prints values)')
    s.add_argument('--run', required=True)

    for name, text in (('propose', 'model proposes records; quotes verified word for word'),
                       ('audit', 'second model audits every verified record')):
        s = sub.add_parser(name, help=text)
        s.add_argument('--run', required=True)
        s.add_argument('--backend', required=True, help='claude:<model> or ollama:<model>[@http://127.0.0.1:11434]')
        s.add_argument('--allow-remote-endpoint', action='store_true',
                       help='permit a non-loopback Ollama endpoint (masked personal text leaves this machine)')
        s.add_argument('--claude-executable', default='claude')
        if name == 'propose':
            s.add_argument('--max-chunks', type=int, help='process only the first N chunks (a pilot)')
        else:
            s.add_argument('--allow-same-model', action='store_true',
                           help='allow the proposer\'s backend as auditor; recorded as not independent')

    s = sub.add_parser('review', help='write review.json with every audit-accepted record pending')
    s.add_argument('--run', required=True)

    s = sub.add_parser('approve', help='record human decisions in review.json')
    s.add_argument('--run', required=True)
    s.add_argument('--by', required=True, help='who is approving')
    s.add_argument('--id', action='append', default=[], help='approve one record (repeatable)')
    s.add_argument('--reject', action='append', default=[], help='reject one record (repeatable)')
    s.add_argument('--all', action='store_true', help='bulk-approve every pending record (labelled not line-reviewed)')
    s.add_argument('--note', default='')

    s = sub.add_parser('export', help='write MEMORY.md, README.md, records.jsonl and SHA256SUMS')
    s.add_argument('--run', required=True)
    s.add_argument('--out', required=True)

    s = sub.add_parser('verify', help='check an exported folder against its SHA256SUMS')
    s.add_argument('folder')

    s = sub.add_parser('search', help='plain-text search of an exported folder')
    s.add_argument('folder')
    s.add_argument('query')
    s.add_argument('--speaker', help='voice name, or "user" / "agent"')
    s.add_argument('--category', choices=pipeline.CATEGORIES)
    s.add_argument('--limit', type=int, default=10)
    s.add_argument('--json', action='store_true')

    args = p.parse_args(argv)
    try:
        return run_command(args)
    except (ValueError, pipeline.PipelineStop) as error:
        print(f'STOP: {error}', file=sys.stderr)
        return 2


def run_command(args):
    if args.command == 'inventory':
        _, data, digest = tg_export.load(args.export)
        print(json.dumps({'source_sha256': digest, **tg_export.inventory(data, args.gap_hours)},
                         ensure_ascii=False, indent=2))
    elif args.command == 'init':
        config = pipeline.init(args.run, args.export, args.chat, args.user_id, args.agent_id,
                               args.user_name, args.agent_name)
        run = pipeline.Run(args.run)
        print(json.dumps({'source_sha256': config['source_sha256'], 'voice_messages': len(run.messages),
                          'excluded_records': run.excluded, 'chunks': len(run.chunks())}, indent=2))
    elif args.command == 'mask-report':
        run = pipeline.Run(args.run)
        kinds = Counter(span['kind'] for _, spans in run.outgoing.values() for span in spans)
        print(json.dumps({'messages_with_masks': sum(bool(s) for _, s in run.outgoing.values()),
                          'masked_spans_by_kind': dict(kinds),
                          'limitation': 'Pattern-based. Read the masked text before sending if in doubt.'}, indent=2))
    elif args.command in ('propose', 'audit'):
        backend = backends.make_backend(args.backend, args.allow_remote_endpoint, args.claude_executable)
        run = pipeline.Run(args.run)
        if args.command == 'propose':
            print(json.dumps(pipeline.propose(run, backend, args.max_chunks), indent=2))
        else:
            pipeline.audit(run, backend, args.allow_same_model)
    elif args.command == 'review':
        records = pipeline.review(pipeline.Run(args.run))
        print(f'{len(records)} records pending in {args.run}/review.json')
    elif args.command == 'approve':
        if not (args.id or args.reject or args.all):
            raise ValueError('give --id, --reject or --all')
        changed = pipeline.approve(pipeline.Run(args.run), args.by, args.id, args.reject, args.all, args.note)
        print(f'{changed} decisions recorded')
    elif args.command == 'export':
        print(json.dumps(export_memory.export(pipeline.Run(args.run), args.out), indent=2))
    elif args.command == 'verify':
        export_memory.verify(args.folder)
        print('OK: every file matches SHA256SUMS')
    elif args.command == 'search':
        hits = search_memory.search(args.folder, args.query, args.speaker, args.category, args.limit)
        if args.json:
            print(json.dumps(hits, ensure_ascii=False, indent=2))
        else:
            print('\n\n'.join(map(search_memory.format_hit, hits)) or 'No match. Absence here is not proof.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
