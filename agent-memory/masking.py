"""Deterministic secret masking for text that leaves the machine or enters memory.

Pattern-based and conservative. It is not a completeness guarantee: unknown secret forms
can pass. Every masked text gets a second detection pass, and any surviving match refuses
the call instead of sending first and fixing later.
"""
import re

SECRET_PATTERNS = [
    ('private key', r'-----BEGIN [^\n]*PRIVATE KEY-----[\s\S]*?(?:-----END [^\n]*PRIVATE KEY-----|\Z)', 0),
    ('recovery phrase', r'(?im)\b(?:seed|recovery)\s+phrase\s*[:=]\s*\n([^\n]+(?:\n(?!\s*\n)[^\n]+)?)', 1),
    ('credential assignment', r'''(?im)(?:["']?(?:[\w.-]*[_-])?(?:password|passwd|pwd|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|auth[_ -]?token|bearer[_ -]?token|secret[_ -]?key|client[_ -]?secret|token|credential|recovery[_ -]?phrase|seed[_ -]?phrase|mnemonic)["']?\s*(?:[:=]|\bis\b)\s*["'`]?)([^\n\r]+)''', 1),
    ('password', r'''(?im)\b(?:password|passphrase|api key|token|recovery phrase|seed phrase)(?:\s+for\s+[^\n:=]{1,80})?\s+(?:is|was)\s+([^\n]+)''', 1),
    ('API key or token', r'\b(?:sk-(?:proj-|ant-)?[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,}|xox[baprs]-[A-Za-z0-9-]{12,}|AIza[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b', 0),
    ('bearer token', r'(?i)\bBearer\s+([A-Za-z0-9._~+/-]+=*)', 1),
    ('JWT', r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b', 0),
    ('credential URL', r'(?i)\b[a-z][a-z0-9+.-]*://[^\s<>"`]+:[^\s<>"`]+@[^\s<>"`]+', 0),
    ('login link', r'(?i)https?://[^\s<>"`]*(?:login|signin|sign-in|magic[-_]?link|reset[-_]?password|oauth|authorize|[?&](?:token|key|code|secret|sig|signature|auth)=)[^\s<>"`]*', 0),
    ('credential-like value', r'(?<![\w])[A-Za-z0-9_+/.=-]{28,}(?![\w])', 0),
]
COMPILED = [(kind, re.compile(pattern), group) for kind, pattern, group in SECRET_PATTERNS]
SERVICES = ('openai', 'anthropic', 'github', 'telegram', 'google', 'aws', 'azure', 'ollama',
            'slack', 'discord', 'proton', 'gmail', 'microsoft')
MARKER = re.compile(r'\[SECRET: (' + '|'.join(re.escape(k) for k, _, _ in SECRET_PATTERNS) + r') for ('
                    + '|'.join(map(re.escape, (*SERVICES, 'unspecified service')))
                    + r'), shared (?:\d{4}-\d{2}-\d{2}|unknown date)\]')


class KnownSecrets:
    """Values detected anywhere in the export, kept in memory only, so that a repeat of the
    same value without its label is masked too."""

    def __init__(self, labels):
        self.labels = labels
        ordered = sorted(labels, key=lambda value: -len(value))
        self.pattern = re.compile('|'.join(map(re.escape, ordered))) if ordered else None


def known_values(texts):
    labels = {}
    for text in texts:
        for span in secret_spans(text, 'unknown date'):
            value = text[span['start']:span['end']]
            for part in (value, value.strip().strip('"\'`,;}')):
                if len(part) >= 4:
                    labels[part] = (span['kind'], span['service'])
    return KnownSecrets(labels)


def _marker(kind, service, date):
    return f'[SECRET: {kind} for {service}, shared {date}]'


def secret_spans(text, date, known=None):
    """Merged, sorted spans to mask. Overlaps are merged so no part of a secret is exposed."""
    matches = []
    for kind, pattern, group in COMPILED:
        for match in pattern.finditer(text):
            start, end = match.span(group)
            if start == end:
                continue
            # Long ordinary words stay text; long machine-like strings are masked.
            if kind == 'credential-like value' and not re.search(r'[0-9_+/.=-]', text[start:end]):
                continue
            window = text[max(0, match.start() - 100):match.start()].casefold()
            service = next((s for s in SERVICES if re.search(r'\b' + s + r'\b', window)), 'unspecified service')
            matches.append({'start': start, 'end': end, 'kind': kind, 'service': service})
    if known is not None and known.pattern is not None:
        for match in known.pattern.finditer(text):
            kind, service = known.labels[match.group()]
            matches.append({'start': match.start(), 'end': match.end(), 'kind': kind, 'service': service})
    merged = []
    for span in sorted(matches, key=lambda s: (s['start'], s['end'])):
        if merged and span['start'] < merged[-1]['end']:
            merged[-1]['end'] = max(merged[-1]['end'], span['end'])
        else:
            merged.append(dict(span))
    for span in merged:
        span['marker'] = _marker(span['kind'], span['service'], date)
    return merged


def mask(text, spans):
    output, cursor = [], 0
    for span in spans:
        output.append(text[cursor:span['start']])
        output.append(span['marker'])
        cursor = span['end']
    output.append(text[cursor:])
    return ''.join(output)


def detected_unmasked(text, known=None):
    """Detectable secrets that survive outside our own exact marker syntax."""
    hidden = list(text)
    # A non-whitespace sentinel stops a label regex from jumping through a blanked marker
    # into unrelated prose on the next line.
    for marker in MARKER.finditer(text):
        hidden[marker.start():marker.end()] = ['�'] * (marker.end() - marker.start())
    blanked = ''.join(hidden)
    return [span for span in secret_spans(blanked, 'unknown date', known)
            if blanked[span['start']:span['end']].strip(' \t\r\n"\'`,;:{}[]�')]


def masked_outgoing(raw, date, known=None):
    """Mask, then re-detect. Raises if anything detectable survives."""
    spans = secret_spans(raw, date, known)
    text = mask(raw, spans)
    if detected_unmasked(text, known):
        raise ValueError('unmasked secret survived masking; refusing to send')
    return text, spans
