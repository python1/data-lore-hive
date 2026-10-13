// Page logic that does not touch the DOM, so Node tests can cover it.
import { quoteFromSelection } from './pack-inputs.mjs';

export const DEFAULT_AGENT = { chatgpt: 'ChatGPT', claude: 'Claude', 'messages-jsonl': 'Assistant' };

/** Shrink a UTF-16 selection inside `text` to exclude leading/trailing whitespace; null if nothing is left. */
export function trimSelection(text, s16, e16) {
  while (s16 < e16 && /\s/.test(text[s16])) s16++;
  while (e16 > s16 && /\s/.test(text[e16 - 1])) e16--;
  return s16 < e16 ? { s16, e16 } : null;
}

/** Selection in a message -> quote object kept in page state (code-point start for the pack, UTF-16 for highlighting). */
export function makeQuote(message, s16, e16) {
  const trimmed = trimSelection(message.text, s16, e16);
  if (!trimmed) throw new Error('the selection is only spaces');
  const { quote, start } = quoteFromSelection(message.text, trimmed.s16, trimmed.e16);
  return { key: message.key, quote, start, s16: trimmed.s16, e16: trimmed.e16 };
}

export function codePointToUtf16(text, cp) {
  let i = 0;
  for (let n = 0; n < cp && i < text.length; n++) i += text.codePointAt(i) > 0xffff ? 2 : 1;
  return i;
}

export function nextRecordId(records) {
  const used = new Set(records.map((r) => r.record_id));
  let n = records.length + 1;
  while (used.has(`M-${n}`)) n++;
  return `M-${n}`;
}

export function newRecord(records, message, quote, uid) {
  return { uid, record_id: nextRecordId(records), role: message.role ?? 'user', topic: '', category: '', statement: '', speaker: '', quotes: [quote] };
}

/** "1 record", "2 records"; pass the plural when it is not the singular plus "s". */
export function plural(n, singular, pluralForm = `${singular}s`) {
  return `${n} ${n === 1 ? singular : pluralForm}`;
}

export function slug(title) {
  const s = (title || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60);
  return s || 'memory-pack';
}

/** Page records -> the shape pack-inputs.mjs takes. */
export function recordsForBuild(records) {
  return records.map((r) => ({
    record_id: r.record_id.trim(), role: r.role, topic: r.topic, category: r.category,
    statement: r.statement.trim() ? r.statement : undefined, speaker: r.speaker.trim() ? r.speaker : undefined,
    quotes: r.quotes.map((q) => ({ key: q.key, quote: q.quote, start: q.start }))
  }));
}

/**
 * Builder error -> where to show it. records.jsonl has exactly one line per record, so
 * "records line N" is record N; pack-inputs errors say "record N quote M".
 */
export function locateError(message) {
  let m = /^records? (?:line )?(\d+)(?: quote (\d+))?: (.*)$/.exec(message);
  if (m) return { record: Number(m[1]) - 1, quote: m[2] ? Number(m[2]) - 1 : null, text: m[3] };
  m = /^messages line \d+: speaker is required$/.exec(message);
  if (m) return { record: null, quote: null, text: 'Fill in both speaker names.', field: 'speakers' };
  if (/^--title/.test(message)) return { record: null, quote: null, text: 'The pack title must be one line of text.', field: 'title' };
  return { record: null, quote: null, text: message };
}

/** Messages of a conversation that the current view options show. */
export function visibleMessages(conversation, { showBranches, showOther }) {
  return conversation.messages.filter((m) => (showBranches || m.current) && (showOther || m.kind === 'text'));
}

/** Conversations matching a search (title or visible message text), each with its hit count. */
export function searchConversations(conversations, query, options) {
  const q = query.trim().toLocaleLowerCase();
  const out = [];
  for (const c of conversations) {
    const visible = visibleMessages(c, options);
    if (!visible.length) continue;
    if (!q) { out.push({ conversation: c, hits: 0 }); continue; }
    const hits = visible.filter((m) => (m.lower ??= m.text.toLocaleLowerCase()).includes(q)).length;
    if (hits || c.title.toLocaleLowerCase().includes(q)) out.push({ conversation: c, hits });
  }
  return out;
}

const WARNINGS = {
  'skipped-role': (d) => `messages from “${d}” (not you or the assistant) were left out`,
  'skipped-hidden-message': () => 'hidden system messages were left out',
  'skipped-tool-call': (d) => `assistant messages addressed to a tool (${d}) were left out`,
  'skipped-content-type': (d) => `“${d}” content was left out`,
  'unknown-content-type': (d) => `content of a type this page does not know (“${d}”) — shown as “other” when it had readable text, otherwise left out`,
  'skipped-empty-message': () => 'messages with no text were left out',
  'skipped-injected-prompt': () => 'text the Claude app added to messages (not typed by you) was left out and cannot be quoted',
  'skipped-hidden-thinking': () => 'hidden or empty reasoning blocks were left out',
  'duplicate-conversation': () => 'conversations appeared in more than one file; the first copy is used',
  'skipped-empty-conversation': () => 'conversations with no readable messages were left out',
  'skipped-conversation-without-messages': () => 'conversations without a message list were left out',
  'message-without-date': () => 'messages have no date in the export; they are shown but cannot be quoted',
  'replaced-broken-characters': () => 'messages contained broken characters, replaced with �',
  'missing-current-node': () => 'conversations did not say which branch was current; the latest one is used',
  'unreachable-nodes': () => 'conversations had messages outside the main tree; they are listed at the end',
  'duplicate-message-id': () => 'messages repeated an ID used elsewhere and were given a new one'
};
export function warningText({ code, detail, count }) {
  const text = WARNINGS[code] ? WARNINGS[code](detail) : `${code}${detail ? ` (${detail})` : ''}`;
  return `${text.charAt(0).toUpperCase()}${text.slice(1)} (${count})`;
}

export function makeDraft({ format, speakers, title, description, records }) {
  return { type: 'verified-memory-pack-maker-draft', version: 1, format, speakers, title, description,
    records: records.map(({ uid, ...r }) => ({ ...r, quotes: r.quotes.map(({ key, quote, start }) => ({ key, quote, start })) })) };
}

/** Re-attach a saved draft to the loaded export; quotes whose message or text no longer matches are dropped and reported. */
export function applyDraft(draft, messages, nextUid) {
  if (!draft || draft.type !== 'verified-memory-pack-maker-draft' || draft.version !== 1 || !Array.isArray(draft.records)) throw new Error('this is not a pack maker draft file');
  const dropped = [];
  const str = (x) => (typeof x === 'string' ? x : '');
  const records = draft.records.map((r) => ({
    uid: nextUid(), record_id: str(r.record_id), role: r.role === 'agent' ? 'agent' : 'user', topic: str(r.topic), category: str(r.category),
    statement: str(r.statement), speaker: str(r.speaker),
    quotes: (Array.isArray(r.quotes) ? r.quotes : []).flatMap((q) => {
      const m = messages.get(q?.key);
      const s16 = m && Number.isSafeInteger(q.start) ? codePointToUtf16(m.text, q.start) : -1;
      if (!m || typeof q.quote !== 'string' || m.text.slice(s16, s16 + q.quote.length) !== q.quote) { dropped.push(`${str(r.record_id)}: “${str(q?.quote).slice(0, 60)}”`); return []; }
      return [{ key: q.key, quote: q.quote, start: q.start, s16, e16: s16 + q.quote.length }];
    })
  }));
  const speakers = draft.speakers && typeof draft.speakers === 'object' ? { user: str(draft.speakers.user), agent: str(draft.speakers.agent) } : null;
  return { records, dropped, speakers, title: str(draft.title), description: str(draft.description) };
}

/** Shell command that rebuilds the pack from the downloaded input files. */
export function rebuildCommand(title, description) {
  const q = (s) => `'${s.replace(/'/g, `'\\''`)}'`;
  return ['npx -y -p @python1/verified-memory-mcp verified-memory-build-pack', '--messages messages.jsonl --records records.jsonl --out NEW_FOLDER',
    `--title ${q(title || 'Memory pack')}`, ...(description ? [`--description ${q(description)}`] : [])].join(' \\\n  ');
}

/** Shell command that signs a downloaded pack with the user's own ssh key; the page never sees the key. */
export function signCommand(folder) {
  return `node tools/sign-pack.mjs --pack ${folder} --key ~/.ssh/YOUR_KEY --expires 90d --out ${folder}-signed`;
}
