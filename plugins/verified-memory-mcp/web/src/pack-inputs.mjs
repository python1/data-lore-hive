// Turns what the person selected into the two input files the CLI builder takes, then builds
// the pack with the same pack-core code. Anyone can rerun `verified-memory-build-pack` on the
// downloaded messages.jsonl and records.jsonl and get byte-identical pack files.
import { InputError, buildRecords, isText, parseMessages, renderPack } from '../../tools/pack-core.mjs';

export { InputError };

/**
 * A browser selection inside one message (UTF-16 offsets into its text, as DOM ranges give)
 * -> { quote, start } with `start` in code points, as the builder and verifier count.
 */
export function quoteFromSelection(text, startUtf16, endUtf16) {
  if (!(Number.isSafeInteger(startUtf16) && Number.isSafeInteger(endUtf16) && startUtf16 >= 0 && startUtf16 < endUtf16 && endUtf16 <= text.length)) {
    throw new InputError('select some text inside one message');
  }
  const low = (i) => { const c = text.charCodeAt(i); return c >= 0xdc00 && c <= 0xdfff; };
  if (low(startUtf16) || (endUtf16 < text.length && low(endUtf16))) throw new InputError('the selection splits a character; select a little more or less');
  const quote = text.slice(startUtf16, endUtf16);
  if (!isText(quote)) throw new InputError('the selection is only spaces');
  return { quote, start: [...text.slice(0, startUtf16)].length };
}

const encoder = new TextEncoder();
const jsonl = (rows) => encoder.encode(rows.map((r) => JSON.stringify(r)).join('\n') + '\n');

/**
 * messages: Map key -> message (from load-export.mjs)
 * records: [{ record_id, role, topic, category, statement?, speaker?, quotes: [{ key, quote, start }] }]
 * speakers: { user, agent } names used for messages without their own speaker
 * -> { messagesBytes, recordsBytes } containing only the cited messages, numbered 1..n by date.
 */
export function packInputs({ messages, records, speakers }) {
  const cited = new Map();
  records.forEach((r, i) => {
    if (!Array.isArray(r.quotes)) return;
    r.quotes.forEach((q, j) => {
      const m = messages.get(q.key);
      if (!m) throw new InputError(`record ${i + 1} quote ${j + 1}: its message is no longer loaded`);
      if (!m.date) throw new InputError(`record ${i + 1} quote ${j + 1}: the export has no date for this message, so it cannot be quoted`);
      cited.set(q.key, m);
    });
  });
  const ordered = [...cited.values()].sort((a, b) => Date.parse(a.date) - Date.parse(b.date) || a.order - b.order);
  const ids = new Map(ordered.map((m, i) => [m.key, i + 1]));
  const speakerOf = (m) => m.speaker ?? speakers?.[m.role];
  const messagesBytes = jsonl(ordered.map((m) => ({ id: ids.get(m.key), date: m.date, speaker: speakerOf(m), text: m.text })));
  const recordsBytes = jsonl(records.map((r) => ({
    record_id: r.record_id, role: r.role,
    ...(r.speaker !== undefined && r.speaker !== '' ? { speaker: r.speaker } : {}),
    topic: r.topic, category: r.category,
    ...(r.statement !== undefined && r.statement !== '' ? { statement: r.statement } : {}),
    quotes: Array.isArray(r.quotes) ? r.quotes.map((q) => ({ message_id: ids.get(q.key), quote: q.quote, start: q.start })) : r.quotes
  })));
  return { messagesBytes, recordsBytes };
}

/** Everything the download needs: the four pack files plus the two input files. */
export async function buildPack({ messages, records, speakers, title, description }) {
  const { messagesBytes, recordsBytes } = packInputs({ messages, records, speakers });
  const built = await buildRecords(recordsBytes, parseMessages(messagesBytes));
  const files = await renderPack({ records: built, messagesBytes, recordsBytes, title, description: description || undefined });
  return { files, messagesBytes, recordsBytes };
}
