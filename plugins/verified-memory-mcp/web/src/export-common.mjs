// Shared pieces of the export adapters. An adapter turns one parsed export file into
//   { conversations: [{ id, title, date, messages: [Message] }] }
// where Message = { key, conversationId, role: 'user'|'agent'|null, speaker?, kind, date, text, current, attachments }.
//   kind: 'text' (what was said), 'code', 'reasoning' (model thoughts), 'other' (unknown content type
//         whose text we could still read). The UI shows 'text' by default.
//   date: UTC ISO 8601 accepted by the pack builder, or null when the export has none (not quotable).
//   current: false for branches the person did not end up on (regenerations, edits).
// Adapters never throw on unexpected content: they skip it and count a warning.

const PACK_DATE = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|\+00:00)$/;

export function makeWarnings() {
  const counts = new Map();
  const warn = (code, detail = '') => { const k = `${code}\u0000${detail}`; counts.set(k, (counts.get(k) ?? 0) + 1); };
  warn.list = () => [...counts].map(([k, count]) => { const [code, detail] = k.split('\u0000'); return { code, detail, count }; });
  return warn;
}

const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;
/** Replace lone surrogates with U+FFFD so the hashed UTF-8 bytes equal the text written to messages.jsonl. */
export function wellFormed(text, warn) {
  if (!LONE_SURROGATE.test(text)) return text;
  warn('replaced-broken-characters');
  return text.replace(new RegExp(LONE_SURROGATE.source, 'g'), '\uFFFD');
}

/** Epoch seconds (number) or ISO string -> pack-compatible UTC date, or null. */
export function utcDate(value) {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    const d = new Date(value * 1000);
    return Number.isFinite(d.getTime()) ? d.toISOString() : null;
  }
  if (typeof value === 'string') {
    if (PACK_DATE.test(value) && Number.isFinite(Date.parse(value))) return value;
    const t = Date.parse(value);
    if (/^\d{4}-\d\d-\d\dT/.test(value) && Number.isFinite(t)) return new Date(t).toISOString();
  }
  return null;
}

export const isObject = (x) => x !== null && typeof x === 'object' && !Array.isArray(x);

/** Adds a message if it has quotable text; counts why it was dropped otherwise. */
export function pushMessage(out, warn, message) {
  if (typeof message.text !== 'string' || !message.text.trim()) { warn('skipped-empty-message'); return; }
  message.text = wellFormed(message.text, warn);
  if (!message.date) warn('message-without-date');
  out.push(message);
}
