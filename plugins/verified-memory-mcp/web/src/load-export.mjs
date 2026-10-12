// Loads a ChatGPT or Claude export (.zip, or the conversations.json inside it), or a plain
// messages.jsonl in the pack builder's own format. The format is recognised from the data,
// not the file name. Returns { format, conversations, warnings } with messages normalised as
// described in export-common.mjs, plus a global `order` index on each message.
import { makeWarnings, isObject, wellFormed } from './export-common.mjs';
import { detectChatGPT, parseChatGPT } from './export-chatgpt.mjs';
import { detectClaude, parseClaude } from './export-claude.mjs';
import { isZip, openZip, readEntry } from './zip.mjs';
import { InputError, parseMessages } from '../../tools/pack-core.mjs';

export class ExportError extends Error {}

// A JSON text this large cannot become one JavaScript string in current browsers.
export const MAX_JSON_BYTES = 500 * 1024 * 1024;
const CONVERSATION_FILE = /(^|\/)conversations(-\d+)?\.json$/i;

function decodeJson(bytes, label) {
  let text;
  try { text = new TextDecoder('utf-8', { fatal: true }).decode(bytes); } catch { throw new ExportError(`${label}: not valid UTF-8`); }
  // Never echo parser messages: they quote the file's contents.
  try { return JSON.parse(text); } catch { throw new ExportError(`${label}: not valid JSON`); }
}

function adapt(json, label, warn) {
  if (!Array.isArray(json)) throw new ExportError(`${label}: not a ChatGPT or Claude conversations file (expected a list of conversations)`);
  // Decide from the first conversation that looks like either format, so one damaged or
  // message-less conversation at the top cannot hide the rest.
  const sample = json.find((c) => detectChatGPT(c) || detectClaude(c));
  if (sample !== undefined && detectChatGPT(sample)) return { format: 'chatgpt', conversations: parseChatGPT(json, warn) };
  if (sample !== undefined) return { format: 'claude', conversations: parseClaude(json, warn) };
  if (!json.some(isObject)) return { format: null, conversations: [] };
  throw new ExportError(`${label}: conversations are in a format this page does not recognise yet (no "mapping" or "chat_messages")`);
}

function adaptJsonl(bytes, label, warn) {
  let rows;
  try { rows = parseMessages(bytes); } catch (error) { throw error instanceof InputError ? new ExportError(error.message) : error; }
  const messages = [...rows.values()].map((m) => ({
    key: `jsonl/${m.id}`, conversationId: 'jsonl', role: null, speaker: m.speaker, kind: 'text',
    date: m.date, text: wellFormed(m.text, warn), current: true, attachments: 0
  }));
  return { format: 'messages-jsonl', conversations: [{ id: 'jsonl', title: label, date: messages[0].date, messages }] };
}

/**
 * file: { name, source } where source is a zip.mjs source (bytesSource / blobSource).
 * Throws ExportError with a message suitable for showing to the person.
 */
export async function loadExport({ name, source }) {
  const warn = makeWarnings();
  const parts = [];
  if (await isZip(source)) {
    let entries;
    try { entries = await openZip(source); } catch (error) { throw new ExportError(`${name}: ${error.message}`); }
    const candidates = entries.filter((e) => CONVERSATION_FILE.test(e.name)).sort((a, b) => a.name.localeCompare(b.name));
    if (!candidates.length) throw new ExportError(`${name}: no conversations.json inside this zip; is it a ChatGPT or Claude data export?`);
    for (const entry of candidates) {
      let bytes;
      try { bytes = await readEntry(source, entry, MAX_JSON_BYTES); } catch (error) { throw new ExportError(`${name}: ${error.message}`); }
      parts.push(adapt(decodeJson(bytes, entry.name), entry.name, warn));
    }
  } else {
    if (source.size > MAX_JSON_BYTES) throw new ExportError(`${name}: too large to open in a browser`);
    const bytes = await source.read(0, source.size);
    parts.push(/\.jsonl$/i.test(name) ? adaptJsonl(bytes, name, warn) : adapt(decodeJson(bytes, name), name, warn));
  }
  const formats = [...new Set(parts.map((p) => p.format).filter(Boolean))];
  if (formats.length > 1) throw new ExportError(`${name}: mixes ChatGPT and Claude conversation files`);
  const conversations = parts.flatMap((p) => p.conversations);
  if (!conversations.length) throw new ExportError(`${name}: the export contains no conversations with readable messages`);
  let order = 0;
  const keys = new Set();
  for (const c of conversations) for (const m of c.messages) {
    if (keys.has(m.key)) { warn('duplicate-message-id'); m.key = `${m.key}~${order}`; }
    keys.add(m.key);
    m.order = order++;
  }
  return { format: formats[0], conversations, warnings: warn.list() };
}
