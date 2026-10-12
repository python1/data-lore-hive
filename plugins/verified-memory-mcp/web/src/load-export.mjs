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

/** One file -> list of { format, conversations } parts. Errors name the file. */
async function readFile({ name, source }, warn) {
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
  return parts;
}

// A Claude export is downloaded file by file: a manifest plus one zip per kind of data.
// Only conversations-NNN.zip holds chats. The other kinds are recognised by name and never opened.
const CONVERSATIONS_NAME = /^conversations(-\d+)?\.(zip|json)$/i;
const OTHER_KIND = /^(memories|projects|frames|light_metadata|users)(-\d+)?\.(zip|json)$/i;
const NOT_NEEDED = 'not needed for a memory pack (only the conversations files are), so it was not opened';
const baseName = (name) => name.split(/[\\/]/).pop();

/**
 * files: [{ name, source }] where each source is a zip.mjs source (bytesSource / blobSource);
 * one export file, or several parts of one export (conversations-000.zip, conversations-001.zip, ...).
 * Returns { format, conversations, warnings, notes, used } where notes lists chosen files that
 * were not used and why. Throws ExportError with a message suitable for showing to the person.
 */
export async function loadExports(files) {
  const warn = makeWarnings();
  const notes = [];
  const parts = [];
  let used = 0;
  const sorted = [...files].sort((a, b) => a.name.localeCompare(b.name));
  for (const file of sorted) {
    const base = baseName(file.name);
    if (OTHER_KIND.test(base)) { notes.push({ name: file.name, text: NOT_NEEDED }); continue; }
    let read;
    try { read = await readFile(file, warn); }
    catch (error) {
      // A broken conversations part is an error: skipping it would silently lose chats.
      if (!(error instanceof ExportError) || sorted.length === 1 || CONVERSATIONS_NAME.test(base)) throw error;
      notes.push({ name: file.name, text: `not used: ${error.message.startsWith(`${file.name}: `) ? error.message.slice(file.name.length + 2) : error.message}` });
      continue;
    }
    parts.push(...read);
    used++;
  }
  const label = sorted.length === 1 ? sorted[0].name : 'The chosen files';
  if (!used) {
    throw new ExportError(sorted.length === 1
      ? `${label}: ${NOT_NEEDED.replace(', so it was not opened', '')}. Choose conversations-000.zip instead (and conversations-001.zip and so on, if your export has more parts).`
      : `None of the chosen files holds conversations (${notes.map((n) => n.name).join(', ')}). For a Claude export, choose conversations-000.zip (and conversations-001.zip and so on, if there are more parts).`);
  }
  const formats = [...new Set(parts.map((p) => p.format).filter(Boolean))];
  if (formats.length > 1) throw new ExportError(`${label}: mixes ChatGPT and Claude conversation files`);
  if (formats[0] === 'messages-jsonl' && used > 1) throw new ExportError('Load a messages.jsonl file on its own, not together with other files.');
  // Parts of one export should not overlap; if a conversation does appear twice, keep the first.
  const seen = new Set();
  const conversations = parts.flatMap((p) => p.conversations).filter((c) => {
    if (c.id.startsWith('#')) return true; // positional fallback IDs are per file, not real IDs
    if (seen.has(c.id)) { warn('duplicate-conversation'); return false; }
    seen.add(c.id);
    return true;
  });
  if (!conversations.length) throw new ExportError(`${label}: the export contains no conversations with readable messages`);
  let order = 0;
  const keys = new Set();
  for (const c of conversations) for (const m of c.messages) {
    if (keys.has(m.key)) { warn('duplicate-message-id'); m.key = `${m.key}~${order}`; }
    keys.add(m.key);
    m.order = order++;
  }
  return { format: formats[0], conversations, warnings: warn.list(), notes, used };
}

/** Single-file form of loadExports. */
export const loadExport = (file) => loadExports([file]);
