"""Deterministic, word-for-word quote verification. Nothing is repaired or normalised.

A model's proposal is either proven against the original message bytes or rejected with a
reason. No whitespace folding, spelling fixes, ellipses or joined fragments.
"""
import re

import masking
from tg_export import sha256_text

MAX_QUOTE = 1000


def record_id(role, statement):
    return 'M-' + sha256_text(role + '\0' + statement)[:16]


def voice_ok(role, statement, user_name):
    """The user's records are written about them by name; the agent's stay in its own first person."""
    if role == 'user':
        return re.match(re.escape(user_name) + r'\b', statement) is not None
    return re.match(r'(I|My)\b', statement) is not None


def cite(ref, role, run, visible):
    """One citation for an evidence reference, or ValueError."""
    mid, quote = ref['message_id'], ref['quote']
    if mid not in visible or mid not in run.messages:
        raise ValueError('unknown or out-of-chunk message ID')
    message = run.messages[mid]
    if run.role_of(message) != role:
        raise ValueError('quote is from the other voice; voices are never merged')
    if not quote.strip() or len(quote) > MAX_QUOTE or '[SECRET:' in quote:
        raise ValueError('empty, overlong or masked quote')
    masked_text, spans = run.outgoing[mid]
    if quote not in masked_text:
        raise ValueError('quote is not in the text the model was shown')
    start = message.text.find(quote)
    while start >= 0:
        end = start + len(quote)
        if not any(s['start'] < end and s['end'] > start for s in spans):
            return {'message_id': mid, 'role': role, 'date_utc': message.date_utc,
                    'start': start, 'end': end, 'quote': quote,
                    'message_sha256': sha256_text(message.text)}
        start = message.text.find(quote, start + 1)
    raise ValueError('quote does not match the original message word for word outside secret spans')


def verify_proposal(proposal, role, run, visible):
    """Turn a schema-valid proposal into a record with verified citations, or raise ValueError."""
    statement, topic = proposal['statement'], proposal['topic']
    if not 8 <= len(statement) <= 500 or not 1 <= len(topic) <= 100 or not proposal['evidence']:
        raise ValueError('statement, topic or evidence out of bounds')
    if not voice_ok(role, statement, run.voices['user']['name']):
        raise ValueError('statement is not in its required voice')
    for text in (statement, topic):
        if '[SECRET:' in text or masking.detected_unmasked(text, run.known):
            raise ValueError('secret or marker in generated text')
    evidence = [cite(ref, role, run, visible) for ref in proposal['evidence']]
    evidence = list({(c['message_id'], c['start'], c['end']): c for c in evidence}.values())
    first = min(c['date_utc'] for c in evidence)
    supersedes = []
    for mid in proposal['supersedes_message_ids']:
        if mid not in visible or mid not in run.messages or run.role_of(run.messages[mid]) != role:
            raise ValueError('supersession must name a visible message by the same voice')
        if run.messages[mid].date_utc >= first:
            raise ValueError('superseded message is not earlier')
        supersedes.append({'message_id': mid, 'date_utc': run.messages[mid].date_utc,
                           'status': 'proposed, needs human review'})
    return {'record_id': record_id(role, statement), 'role': role, 'category': proposal['category'],
            'topic': topic, 'statement': statement, 'evidence': evidence,
            'date_first_utc': first, 'date_last_utc': max(c['date_utc'] for c in evidence),
            'supersedes': supersedes}


def recheck(record, run):
    """Re-prove a stored record against the original export before it is exported."""
    if record['record_id'] != record_id(record['role'], record['statement']):
        raise ValueError(f'{record["record_id"]}: statement or voice changed after verification')
    if not voice_ok(record['role'], record['statement'], run.voices['user']['name']):
        raise ValueError(f'{record["record_id"]}: wrong voice')
    if '[SECRET:' in record['statement'] or masking.detected_unmasked(record['statement'], run.known):
        raise ValueError(f'{record["record_id"]}: secret in statement')
    for c in record['evidence']:
        message = run.messages.get(c['message_id'])
        if message is None or run.role_of(message) != record['role']:
            raise ValueError(f'{record["record_id"]}: cited message missing or wrong voice')
        if sha256_text(message.text) != c['message_sha256'] or message.text[c['start']:c['end']] != c['quote']:
            raise ValueError(f'{record["record_id"]}: quote no longer matches the original')
        _, spans = run.outgoing[c['message_id']]
        if any(s['start'] < c['end'] and s['end'] > c['start'] for s in spans) \
                or masking.detected_unmasked(c['quote'], run.known):
            raise ValueError(f'{record["record_id"]}: quote overlaps a detected secret')
