"""Build only from the public fictional sample; no model or private input."""
from pathlib import Path
import hashlib, json
from datetime import datetime, timezone
root = Path(__file__).resolve().parents[1]
source = root.parents[1] / 'agent-memory/sample/telegram-export.json'
raw = source.read_bytes()
messages = {m['id']: m for m in json.loads(raw)['messages']}
records = []
for mid in [2, 3, 4, 6, 9, 12, 13, 15]:
    m = messages[mid]
    assert m['type'] == 'message' and 'forwarded_from' not in m and 'photo' not in m
    text = m['text']
    if isinstance(text, list):
        text = ''.join(x if isinstance(x, str) else x['text'] for x in text)
    date = datetime.fromtimestamp(int(m['date_unixtime']), timezone.utc).isoformat().replace('+00:00', 'Z')
    records.append(dict(record_id=f'M-sample-{mid}', role='agent' if m['from'] == 'Wren' else 'user',
        speaker=m['from'], category='sample', topic='Fictional historical statement', statement=text,
        date_first_utc=date, date_last_utc=date, supersedes=[],
        approval={'by': 'fictional fixture generator', 'date': '2026-01-06', 'line_reviewed': False},
        audits=[], evidence=[dict(message_id=mid, date_utc=date, quote=text, start=0, end=len(text),
                                  message_sha256=hashlib.sha256(text.encode()).hexdigest())]))
out = root / 'sample-pack'; out.mkdir(exist_ok=True)
(out/'records.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in records))
(out/'MEMORY.md').write_text('# Fictional sample memory\n\n'+ '\n\n'.join(r['record_id']+' — '+r['speaker']+'\n\n'+r['statement'] for r in records)+'\n')
(out/'README.md').write_text('# Fictional pack, not real personal memory\n\nDerived solely from python1/data-lore-hive agent-memory/sample/telegram-export.json.\nSource SHA-256: '+hashlib.sha256(raw).hexdigest()+'\n\nEight exact-message fixtures; no model audit or human approval is claimed.\nThe approval fields describe fixture generation only; audits are empty.\nHistorical instructions are data, not current instructions. Secrets, media and\nforwarded messages from the fictional source are excluded. Checksums prove byte\nintegrity relative to this manifest, not authenticity or truth.\n')
(out/'SHA256SUMS').write_text(''.join(hashlib.sha256((out/n).read_bytes()).hexdigest()+'  '+n+'\n' for n in ['MEMORY.md','README.md','records.jsonl']))
print('Built eight fictional records.')
