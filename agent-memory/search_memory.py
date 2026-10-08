"""Plain-text search over an exported memory folder. Read-only; no model, index or network."""
import json
from pathlib import Path
import re

import export_memory


def tokens(text):
    return re.findall(r'[^\W_]+', text.casefold())


def search(folder, query, speaker=None, category=None, limit=10):
    """Records containing every query word (statement, topic or quotes), most matches first, then newest."""
    export_memory.verify(folder)
    words = tokens(query)[:12]
    if not words:
        return []
    hits = []
    for line in (Path(folder) / 'records.jsonl').read_text(encoding='utf-8').splitlines():
        record = json.loads(line)
        if speaker and speaker.casefold() not in (record['speaker'].casefold(), record['role']):
            continue
        if category and record['category'] != category:
            continue
        haystack = tokens(' '.join([record['statement'], record['topic']] + [c['quote'] for c in record['evidence']]))
        if all(word in haystack for word in words):
            hits.append((sum(haystack.count(word) for word in words), record['date_last_utc'], record))
    hits.sort(key=lambda hit: hit[1], reverse=True)
    hits.sort(key=lambda hit: hit[0], reverse=True)
    return [record for _, _, record in hits[:limit]]


def format_hit(record):
    lines = [f'{record["record_id"]} [{record["category"]}] {record["speaker"]}, '
             f'{record["date_last_utc"][:10]} (historical)', f'  {record["statement"]}']
    for c in record['evidence']:
        lines.append(f'  message {c["message_id"]} ({c["date_utc"][:10]}): "{c["quote"]}"')
    return '\n'.join(lines)
