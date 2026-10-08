"""Read a Telegram Desktop JSON chat export. Never follows links or opens media."""
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

MEDIA_KEYS = ('photo', 'file', 'media_type', 'sticker_emoji', 'contact_information',
              'location_information', 'venue_information', 'poll', 'game')


def sha256_bytes(raw):
    return hashlib.sha256(raw).hexdigest()


def sha256_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def load(path):
    """Return (raw bytes, parsed JSON, SHA-256) for an export file."""
    raw = Path(path).read_bytes()
    return raw, json.loads(raw), sha256_bytes(raw)


def text_pieces(value):
    """Visible text pieces of a message `text` field. Unknown shapes raise instead of guessing."""
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        raise ValueError('invalid text field')
    pieces = []
    for item in value:
        if isinstance(item, str):
            pieces.append(item)
        elif isinstance(item, dict) and isinstance(item.get('text'), str):
            pieces.append(item['text'])
        else:
            raise ValueError('invalid text entity')
    return pieces


def timestamp(message):
    """UTC instant from `date_unixtime`, falling back to an aware ISO `date`.

    Naive ISO dates are never assumed to be UTC. Returns (datetime or None, errors).
    """
    errors, parsed = [], None
    unix = message.get('date_unixtime')
    if unix is not None:
        try:
            if isinstance(unix, bool) or not str(unix).lstrip('-').isdigit():
                raise ValueError()
            parsed = datetime.fromtimestamp(int(unix), timezone.utc)
        except (ValueError, TypeError, OverflowError, OSError):
            errors.append('invalid_date_unixtime')
    iso = message.get('date')
    if iso is not None:
        try:
            date = datetime.fromisoformat(iso)
            if date.tzinfo is not None:
                date = date.astimezone(timezone.utc)
                if parsed and date != parsed:
                    errors.append('date_timestamp_conflict')
                parsed = parsed or date
        except (ValueError, TypeError):
            errors.append('invalid_date')
    if parsed is None:
        errors.append('missing_absolute_timestamp')
    return parsed, errors


def extract_chats(data):
    """Accept a single-chat export or a full export with `chats.list`."""
    if not isinstance(data, dict):
        raise ValueError('unsupported export root; expected an object')
    if 'messages' in data:
        return [data]
    chats = data.get('chats')
    if isinstance(chats, dict) and isinstance(chats.get('list'), list):
        return chats['list']
    if isinstance(chats, list):
        return chats
    raise ValueError('missing chat/message container')


def _kind(message):
    has_media = any(message.get(key) not in (None, '', {}, []) for key in MEDIA_KEYS)
    if message.get('type') == 'service':
        return 'service', has_media
    if message.get('type') == 'message':
        return ('media' if has_media else 'text'), has_media
    return 'unknown', has_media


def inventory(data, gap_hours=24):
    """Metadata-only inventory: counts, senders, date range, gaps. Contains no message text."""
    if not math.isfinite(gap_hours) or gap_hours <= 0:
        raise ValueError('gap threshold must be positive')
    report = {'schema': 'telegram-inventory-v1', 'gap_threshold_hours': gap_hours,
              'scope': 'Export only. Time and ID gaps do not prove missing or deleted messages.',
              'chats': []}
    for index, chat in enumerate(extract_chats(data)):
        if not isinstance(chat, dict) or not isinstance(chat.get('messages'), list):
            report['chats'].append({'chat_index': index, 'malformed': True})
            continue
        counts, issues, senders, dates = Counter(), Counter(), {}, []
        ids = Counter(m.get('id') for m in chat['messages'] if isinstance(m, dict) and type(m.get('id')) is int)
        for message in chat['messages']:
            counts['records'] += 1
            if not isinstance(message, dict):
                issues['non_object_record'] += 1
                continue
            if type(message.get('id')) is not int:
                issues['missing_message_id'] += 1
            elif ids[message['id']] > 1:
                issues['duplicate_message_id'] += 1
            kind, has_media = _kind(message)
            counts[kind] += 1
            try:
                has_text = bool(''.join(text_pieces(message.get('text', ''))).strip())
            except ValueError:
                issues['invalid_text'] += 1
                has_text = False
            counts['with_text'] += has_text
            counts['edited'] += bool(message.get('edited') or message.get('edited_unixtime'))
            counts['forwarded'] += bool(message.get('forwarded_from'))
            dt, errors = timestamp(message)
            issues.update(errors)
            if dt:
                dates.append(dt)
            sid = message.get('from_id', message.get('actor_id'))
            name = message.get('from', message.get('actor'))
            key = str(sid) if isinstance(sid, (str, int)) else 'unknown'
            entry = senders.setdefault(key, {'names': set(), 'records': 0, 'with_text': 0})
            if isinstance(name, str):
                entry['names'].add(name)
            entry['records'] += 1
            entry['with_text'] += has_text
        dates.sort()
        intervals = [(b - a).total_seconds() / 3600 for a, b in zip(dates, dates[1:])]
        report['chats'].append({
            'chat_index': index, 'name': chat.get('name'), 'type': chat.get('type'),
            'counts': dict(counts), 'issues': dict(issues),
            'senders': {k: {**v, 'names': sorted(v['names'])} for k, v in senders.items()},
            'date_range_utc': [dates[0].isoformat(), dates[-1].isoformat()] if dates else None,
            'time_gaps': sum(hours >= gap_hours for hours in intervals),
            'largest_gap_hours': round(max(intervals, default=0), 2)})
    return report


@dataclass(frozen=True)
class Message:
    message_id: int
    sender_id: str
    sender_name: str
    date_utc: str
    text: str
    kind: str
    edited: bool
    forwarded: bool
    has_media: bool


def chat_messages(data, chat_index):
    """All records of one chat as Messages. Ambiguous IDs or timestamps are refused, not guessed."""
    chats = extract_chats(data)
    if not 0 <= chat_index < len(chats):
        raise ValueError(f'chat index {chat_index} is outside 0..{len(chats) - 1}')
    chat = chats[chat_index]
    if not isinstance(chat, dict) or not isinstance(chat.get('messages'), list):
        raise ValueError('malformed chat')
    ids = Counter(m.get('id') for m in chat['messages'] if isinstance(m, dict))
    result = []
    for message in chat['messages']:
        if not isinstance(message, dict):
            raise ValueError('malformed message record')
        mid = message.get('id')
        if type(mid) is not int or ids[mid] != 1:
            raise ValueError('missing or duplicate message ID; citations would be ambiguous')
        dt, errors = timestamp(message)
        if errors or dt is None:
            raise ValueError(f'message {mid} has no unambiguous UTC timestamp: {errors}')
        kind, has_media = _kind(message)
        sid = message.get('from_id', message.get('actor_id'))
        name = message.get('from', message.get('actor'))
        result.append(Message(mid, str(sid) if isinstance(sid, (str, int)) else '',
                              name if isinstance(name, str) else '', dt.isoformat(),
                              ''.join(text_pieces(message.get('text', ''))), kind,
                              bool(message.get('edited') or message.get('edited_unixtime')),
                              bool(message.get('forwarded_from')), has_media))
    return result
