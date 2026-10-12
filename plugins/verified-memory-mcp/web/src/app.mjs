// Pack maker page. Export data is only ever put into the page with textContent or text
// nodes, never as HTML. Nothing here makes a network request; the page's CSP forbids it.
import { ExportError, loadExports } from './load-export.mjs';
import { blobSource, writeZip } from './zip.mjs';
import { buildPack } from './pack-inputs.mjs';
import { sha256 } from '../../tools/pack-core.mjs';
import { verifyPackEntries } from '../../dist/verify.js';
import { DEFAULT_AGENT, applyDraft, locateError, makeDraft, makeQuote, newRecord, plural, rebuildCommand, recordsForBuild, searchConversations, slug, visibleMessages, warningText } from './ui-logic.mjs';

const $ = (id) => document.getElementById(id);
const PROPS = new Set(['value', 'checked', 'disabled', 'hidden', 'selected', 'placeholder', 'type', 'rows']);
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (PROPS.has(k)) el[k] = v;
    else el.setAttribute(k, v === true ? '' : String(v));
  }
  for (const c of children.flat()) if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : String(c));
  return el;
}
const encoder = new TextEncoder();
const fmtDate = (iso) => (iso ? `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC` : 'no date');
const FORMAT_NAMES = { chatgpt: 'ChatGPT export', claude: 'Claude export', 'messages-jsonl': 'messages.jsonl' };
const PACK_ORDER = ['MEMORY.md', 'README.md', 'SHA256SUMS', 'records.jsonl'];
const LIST_PAGE = 300;

let uid = 0;
const state = {
  data: null, messages: new Map(), conversations: new Map(), active: null,
  search: '', showBranches: false, showOther: false, listLimit: LIST_PAGE,
  speakers: { user: 'Me', agent: 'Assistant' }, records: [], selection: null, built: null,
  title: 'My memory pack', description: ''
};

function setStatus(el, text, kind = '') { el.textContent = text; el.className = `status ${kind}`.trim(); }
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }

// ---------- loading ----------

/** Parse in a Web Worker; fall back to the main thread where workers are unavailable (e.g. some file:// setups). */
const onMainThread = (files) => loadExports(files.map((file) => ({ name: file.name, source: blobSource(file) })));
async function parse(files) {
  let url, worker;
  try {
    url = URL.createObjectURL(new Blob([$('worker-source').textContent], { type: 'text/javascript' }));
    worker = new Worker(url);
  } catch { if (url) URL.revokeObjectURL(url); return onMainThread(files); }
  const result = await new Promise((resolve) => {
    worker.onmessage = ({ data }) => resolve(data);
    worker.onerror = (event) => { event.preventDefault(); resolve(null); };
    worker.postMessage(files);
  });
  worker.terminate(); URL.revokeObjectURL(url);
  if (result?.ok) return result.result;
  if (result && result.expected) throw new ExportError(result.message);
  // The worker could not start or could not read the file (WebKit cannot read a File inside a
  // worker on file:// pages): parse on the main thread instead.
  return onMainThread(files);
}

async function loadFiles(files) {
  if (!files.length) return;
  if (state.records.length && !confirm('Loading another export removes your current records. Save a draft first if you want to keep them. Continue?')) return;
  const status = $('load-status');
  setStatus(status, `Reading ${files.length === 1 ? files[0].name : plural(files.length, 'file')}…`);
  $('load-notes').replaceChildren();
  let data;
  try { data = await parse(files); }
  catch (error) {
    setStatus(status, error instanceof ExportError ? error.message : `Could not read this file: ${error.message}`, 'error');
    return;
  }
  state.data = data;
  state.messages = new Map(data.conversations.flatMap((c) => c.messages.map((m) => [m.key, m])));
  state.conversations = new Map(data.conversations.map((c) => [c.id, c]));
  state.records = []; state.selection = null; state.built = null; state.active = null; state.search = ''; state.listLimit = LIST_PAGE;
  state.speakers = { user: state.speakers.user || 'Me', agent: DEFAULT_AGENT[data.format] ?? 'Assistant' };
  $('search').value = ''; $('speaker-user').value = state.speakers.user; $('speaker-agent').value = state.speakers.agent;
  $('speaker-user').disabled = $('speaker-agent').disabled = data.format === 'messages-jsonl';

  const undated = [...state.messages.values()].filter((m) => !m.date).length;
  const undatedNote = undated ? ` ${undated} ${undated === 1 ? 'has' : 'have'} no date and cannot be quoted.` : '';
  const fromFiles = data.used > 1 ? ` (${plural(data.used, 'file')})` : '';
  setStatus(status, `${FORMAT_NAMES[data.format]}${fromFiles}: ${plural(data.conversations.length, 'conversation')}, ${plural(state.messages.size, 'message')}.${undatedNote}`, 'ok');
  $('load-notes').replaceChildren(...data.notes.map((n) => h('li', {}, h('strong', {}, n.name), `: ${n.text}.`)));
  const warnings = $('warnings');
  warnings.hidden = !data.warnings.length;
  $('warnings-summary').textContent = `${plural(data.warnings.length, 'kind')} of content ${data.warnings.length === 1 ? 'was' : 'were'} skipped or adjusted`;
  $('warnings-list').replaceChildren(...data.warnings.map((w) => h('li', {}, warningText(w))));

  $('workspace').hidden = false;
  $('save-draft').disabled = false; $('load-draft').disabled = false;
  renderList(); renderThread(); renderSelection(); renderRecords(); validate();
}

// ---------- conversation list and thread ----------

const viewOptions = () => ({ showBranches: state.showBranches, showOther: state.showOther });

function renderList() {
  const results = searchConversations(state.data.conversations, state.search, viewOptions());
  const shown = results.slice(0, state.listLimit);
  $('search-count').textContent = state.search.trim()
    ? `${plural(results.length, 'conversation')} ${results.length === 1 ? 'matches' : 'match'}` : plural(results.length, 'conversation');
  $('conversation-list').replaceChildren(...shown.map(({ conversation: c, hits }) => h('li', {},
    h('button', { type: 'button', 'aria-current': c.id === state.active ? 'true' : 'false', onclick: () => openConversation(c.id) },
      c.title || 'Untitled conversation',
      h('span', { class: 'meta' }, `${c.date ? c.date.slice(0, 10) : 'no date'} · ${hits ? `${plural(hits, 'matching message')}` : plural(visibleMessages(c, viewOptions()).length, 'message')}`)))));
  $('more-conversations').hidden = results.length <= shown.length;
}

function openConversation(id) {
  state.active = id;
  renderList(); renderThread();
  $('thread-title').scrollIntoView({ block: 'nearest' });
}

const speakerOf = (m) => m.speaker ?? (state.speakers[m.role] || (m.role === 'agent' ? 'Assistant' : 'You'));

/** Message text as text nodes, with quoted ranges wrapped in <mark>. */
function messageText(m) {
  const ranges = state.records.flatMap((r) => r.quotes).filter((q) => q.key === m.key).map((q) => [q.s16, q.e16]).sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const [s, e] of ranges) { const last = merged[merged.length - 1]; if (last && s <= last[1]) last[1] = Math.max(last[1], e); else merged.push([s, e]); }
  const parts = [];
  let at = 0;
  for (const [s, e] of merged) { if (s > at) parts.push(m.text.slice(at, s)); parts.push(h('mark', {}, m.text.slice(s, e))); at = e; }
  if (at < m.text.length) parts.push(m.text.slice(at));
  return h('div', { class: 'message-text', 'data-key': m.key }, parts);
}

function renderThread() {
  const c = state.conversations.get(state.active);
  $('thread-title').textContent = c ? (c.title || 'Untitled conversation') : 'Pick a conversation';
  if (!c) { $('thread').replaceChildren(); return; }
  const kinds = { code: 'code', reasoning: 'reasoning', other: 'other content' };
  $('thread').replaceChildren(...visibleMessages(c, viewOptions()).map((m) => h('article', { class: `message ${m.role ?? 'user'}${m.date ? '' : ' undated'}`, 'data-key': m.key },
    h('div', { class: 'message-head' },
      h('span', { class: 'who' }, speakerOf(m)), h('span', {}, fmtDate(m.date)),
      kinds[m.kind] && h('span', { class: 'badge' }, kinds[m.kind]),
      !m.current && h('span', { class: 'badge' }, 'earlier version'),
      m.attachments > 0 && h('span', { class: 'badge' }, `${m.attachments} attachment${m.attachments > 1 ? 's' : ''} not included`),
      !m.date && h('span', { class: 'badge warn' }, 'cannot be quoted: no date')),
    messageText(m))));
}

function showQuote(q) {
  const m = state.messages.get(q.key);
  if (!m) return;
  let changed = false;
  if (!m.current && !state.showBranches) { state.showBranches = $('show-branches').checked = changed = true; }
  if (m.kind !== 'text' && !state.showOther) { state.showOther = $('show-other').checked = changed = true; }
  if (changed || state.active !== m.conversationId) { state.active = m.conversationId; renderList(); renderThread(); }
  const el = [...$('thread').querySelectorAll('article.message')].find((a) => a.dataset.key === q.key);
  if (!el) return;
  el.scrollIntoView({ block: 'center' });
  el.classList.add('flash'); setTimeout(() => el.classList.remove('flash'), 1500);
}

// ---------- selection ----------

/** Characters (UTF-16) of `root`'s text before a boundary point; counts exactly the text nodes rendered from the message. */
function offsetIn(root, node, offset) {
  const r = document.createRange();
  r.selectNodeContents(root); r.setEnd(node, offset);
  return r.toString().length;
}

function readSelection() {
  const sel = getSelection();
  if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return undefined; // keep the last selection
  const range = sel.getRangeAt(0);
  if (!$('thread').contains(range.commonAncestorContainer)) return undefined;
  const texts = [...$('thread').querySelectorAll('.message-text')].filter((t) => range.intersectsNode(t));
  if (texts.length !== 1) return texts.length ? { error: 'Select text inside one message.' } : undefined;
  const el = texts[0];
  const inner = document.createRange();
  inner.selectNodeContents(el);
  if (range.compareBoundaryPoints(Range.START_TO_START, inner) > 0) inner.setStart(range.startContainer, range.startOffset);
  if (range.compareBoundaryPoints(Range.END_TO_END, inner) < 0) inner.setEnd(range.endContainer, range.endOffset);
  const message = state.messages.get(el.dataset.key);
  if (!message.date) return { error: 'This message has no date in the export, so it cannot be quoted.' };
  try { return { message, quote: makeQuote(message, offsetIn(el, inner.startContainer, inner.startOffset), offsetIn(el, inner.endContainer, inner.endOffset)) }; }
  catch (error) { return { error: `${error.message[0].toUpperCase()}${error.message.slice(1)}.` }; }
}

function renderSelection() {
  const s = state.selection;
  const ok = Boolean(s && !s.error);
  $('selection-preview').textContent = ok ? `“${s.quote.quote.length > 240 ? `${s.quote.quote.slice(0, 240)}…` : s.quote.quote}” — ${speakerOf(s.message)}, ${fmtDate(s.message.date)}` : 'No text selected.';
  $('selection-preview').classList.toggle('muted', !ok);
  $('selection-error').textContent = s?.error ?? '';
  $('new-record').disabled = !ok;
  $('add-to-record').disabled = $('target-record').disabled = !ok || !state.records.length;
}

function useSelection(target) {
  const s = state.selection;
  if (!s || s.error) return;
  let record = target;
  if (record) {
    if (record.quotes.some((q) => q.key === s.quote.key && q.start === s.quote.start && q.quote === s.quote.quote)) {
      $('selection-error').textContent = 'That quote is already in this record.'; return;
    }
    record.quotes.push(s.quote);
  } else {
    record = newRecord(state.records, s.message, s.quote, ++uid);
    state.records.push(record);
  }
  state.selection = null;
  getSelection()?.removeAllRanges();
  renderSelection(); renderRecords(); renderThread(); validate();
  const li = [...$('records').children].find((x) => x.dataset.uid === String(record.uid));
  li?.scrollIntoView({ block: 'nearest' });
  if (!target) li?.querySelector('[data-field=topic]')?.focus();
}

// ---------- records ----------

const refs = new Map(); // uid -> { li, error, quoteErrors }

function field(record, name, label, attrs = {}) {
  const tag = attrs.multiline ? 'textarea' : 'input';
  const input = h(tag, { type: attrs.multiline ? undefined : 'text', rows: attrs.multiline ? 2 : undefined, value: record[name], placeholder: attrs.placeholder, 'data-field': name,
    oninput: (e) => { record[name] = e.target.value; if (name === 'record_id') refs.get(record.uid).title.textContent = e.target.value || '(no ID)'; renderTargets(); validate(); } });
  return h('label', { class: attrs.wide ? 'wide' : undefined }, label, input);
}

function renderTargets() {
  const select = $('target-record');
  const keep = select.value;
  select.replaceChildren(...state.records.map((r) => h('option', { value: String(r.uid) }, `${r.record_id || '(no ID)'}${r.topic ? ` — ${r.topic}` : ''}`)));
  if ([...select.options].some((o) => o.value === keep)) select.value = keep;
}

function renderRecords() {
  refs.clear();
  $('records').replaceChildren(...state.records.map((r) => {
    const title = h('strong', {}, r.record_id || '(no ID)');
    const error = h('p', { class: 'error', role: 'alert' });
    const quoteErrors = [];
    const li = h('li', { class: 'record', 'data-uid': String(r.uid) },
      h('div', { class: 'record-head' }, title, h('button', { type: 'button', class: 'small', onclick: () => {
        if (!confirm(`Remove record ${r.record_id || ''}?`)) return;
        state.records = state.records.filter((x) => x !== r); renderRecords(); renderThread(); renderSelection(); validate();
      } }, 'Remove')),
      h('div', { class: 'record-grid' },
        field(r, 'record_id', 'ID'),
        h('label', {}, 'Voice', h('select', { 'data-field': 'role', onchange: (e) => { r.role = e.target.value; validate(); } },
          h('option', { value: 'user', selected: r.role === 'user' }, 'You (user)'), h('option', { value: 'agent', selected: r.role === 'agent' }, 'Assistant (agent)'))),
        field(r, 'topic', 'Topic', { placeholder: 'e.g. Garden role' }),
        field(r, 'category', 'Category', { placeholder: 'e.g. profile' }),
        field(r, 'statement', 'Statement', { wide: true, multiline: true, placeholder: 'Optional summary; empty uses the quotes' }),
        field(r, 'speaker', 'Speaker', { wide: true, placeholder: 'Optional; needed only when quotes come from both of you' })),
      h('ul', { class: 'quotes' }, r.quotes.map((q, i) => {
        const m = state.messages.get(q.key);
        const qError = h('p', { class: 'error' });
        quoteErrors.push(qError);
        return h('li', {}, h('blockquote', {}, q.quote),
          h('div', { class: 'row muted small' }, `${m ? speakerOf(m) : '?'} · ${fmtDate(m?.date)}`,
            h('button', { type: 'button', class: 'link', onclick: () => showQuote(q) }, 'Show'),
            h('button', { type: 'button', class: 'link', onclick: () => {
              r.quotes.splice(i, 1);
              if (!r.quotes.length) state.records = state.records.filter((x) => x !== r);
              renderRecords(); renderThread(); renderSelection(); validate();
            } }, 'Remove quote')),
          qError);
      })),
      error);
    refs.set(r.uid, { li, title, error, quoteErrors });
    return li;
  }));
  $('records-empty').hidden = state.records.length > 0;
  renderTargets();
}

// ---------- build, verify, download ----------

let buildToken = 0;
const validate = debounce(async () => {
  const token = ++buildToken;
  const status = $('build-status');
  state.built = null;
  for (const b of ['download-pack', 'download-inputs', 'save-folder']) $(b).disabled = true;
  $('rebuild-command').textContent = rebuildCommand(state.title.trim(), state.description.trim());
  for (const { li, error, quoteErrors } of refs.values()) { li.classList.remove('invalid'); error.textContent = ''; quoteErrors.forEach((e) => { e.textContent = ''; }); }
  if (!state.records.length) { setStatus(status, 'Add at least one record to build a pack.'); return; }
  setStatus(status, 'Checking…');
  try {
    const built = await buildPack({ messages: state.messages, records: recordsForBuild(state.records), speakers: state.speakers,
      title: state.title.trim() || undefined, description: state.description.trim() || undefined });
    // Run the server's own verifier over the exact bytes that will be downloaded.
    const bytes = Object.fromEntries(Object.entries(built.files).map(([n, s]) => [n, encoder.encode(s)]));
    const digests = new Map();
    for (const b of Object.values(bytes)) digests.set(b, await sha256(b));
    const { records } = verifyPackEntries(Object.keys(bytes), (n) => bytes[n], (b) => digests.get(b));
    if (token !== buildToken) return;
    state.built = { ...built, bytes };
    for (const b of ['download-pack', 'download-inputs', 'save-folder']) $(b).disabled = false;
    setStatus(status, `Verified: ${plural(records.size, 'record')}. Every quote matches its message word for word, and the checksums pass.`, 'ok');
  } catch (error) {
    if (token !== buildToken) return;
    const where = locateError(error.message);
    where.text = where.text.charAt(0).toUpperCase() + where.text.slice(1);
    const record = where.record !== null ? state.records[where.record] : null;
    const ref = record && refs.get(record.uid);
    if (ref) {
      ref.li.classList.add('invalid');
      (where.quote !== null && ref.quoteErrors[where.quote] ? ref.quoteErrors[where.quote] : ref.error).textContent = where.text;
    }
    setStatus(status, record ? `Fix record ${where.record + 1} (${record.record_id || 'no ID'}): ${where.text}` : where.text, 'error');
  }
}, 250);

function download(name, bytes, type) {
  const url = URL.createObjectURL(new Blob([bytes], { type }));
  const a = h('a', { href: url, download: name });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}
const folderName = () => slug(state.title);

function downloadPack() {
  if (!state.built) return;
  const folder = folderName();
  download(`${folder}.zip`, writeZip(PACK_ORDER.map((n) => ({ name: `${folder}/${n}`, data: state.built.bytes[n] }))), 'application/zip');
}

function downloadInputs() {
  if (!state.built) return;
  const folder = `${folderName()}-inputs`;
  const note = `These files rebuild the pack byte for byte with the command-line builder:\n\n${rebuildCommand(state.title.trim(), state.description.trim())}\n`;
  download(`${folder}.zip`, writeZip([
    { name: `${folder}/messages.jsonl`, data: state.built.messagesBytes },
    { name: `${folder}/records.jsonl`, data: state.built.recordsBytes },
    { name: `${folder}/REBUILD.txt`, data: encoder.encode(note) }
  ]), 'application/zip');
}

async function saveFolder() {
  if (!state.built) return;
  const status = $('build-status');
  const folder = folderName();
  let parent;
  try { parent = await window.showDirectoryPicker({ mode: 'readwrite' }); } catch { return; }
  try {
    try { await parent.getDirectoryHandle(folder); setStatus(status, `A folder named “${folder}” already exists there. Choose another place or change the pack title.`, 'error'); return; }
    catch (error) { if (error.name !== 'NotFoundError') throw error; }
    const dir = await parent.getDirectoryHandle(folder, { create: true });
    for (const n of PACK_ORDER) {
      const writable = await (await dir.getFileHandle(n, { create: true })).createWritable();
      await writable.write(state.built.bytes[n]); await writable.close();
    }
    setStatus(status, `Saved the pack to the folder “${folder}”.`, 'ok');
  } catch (error) { setStatus(status, `Could not save the folder: ${error.message}`, 'error'); }
}

function saveDraft() {
  const draft = makeDraft({ format: state.data.format, speakers: state.speakers, title: state.title, description: state.description, records: state.records });
  download(`${folderName()}-draft.json`, encoder.encode(JSON.stringify(draft, null, 1) + '\n'), 'application/json');
}

async function openDraft(file) {
  const status = $('build-status');
  if (state.records.length && !confirm('Opening a draft replaces your current records. Continue?')) return;
  try {
    const draft = JSON.parse(await file.text());
    const applied = applyDraft(draft, state.messages, () => ++uid);
    state.records = applied.records.filter((r) => r.quotes.length);
    if (applied.speakers && state.data.format !== 'messages-jsonl') { state.speakers = applied.speakers; $('speaker-user').value = applied.speakers.user; $('speaker-agent').value = applied.speakers.agent; }
    state.title = $('title').value = applied.title; state.description = $('description').value = applied.description;
    renderRecords(); renderThread(); renderSelection(); validate();
    if (applied.dropped.length) setStatus($('load-status'), `Draft opened, but ${plural(applied.dropped.length, 'quote')} did not match this export and ${applied.dropped.length === 1 ? 'was' : 'were'} left out: ${applied.dropped.join('; ')}`, 'error');
    else setStatus($('load-status'), `Draft opened: ${plural(state.records.length, 'record')}.`, 'ok');
  } catch (error) { setStatus(status, `Could not open the draft: ${error instanceof SyntaxError ? 'not a JSON file' : error.message}`, 'error'); }
}

// ---------- wiring ----------

function init() {
  const drop = $('drop');
  $('file').addEventListener('change', (e) => { const files = [...e.target.files]; e.target.value = ''; loadFiles(files); });
  drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); loadFiles([...e.dataTransfer.files]); });
  // Dropping a file anywhere else must not make the browser navigate away to it.
  addEventListener('dragover', (e) => e.preventDefault());
  addEventListener('drop', (e) => e.preventDefault());

  $('search').addEventListener('input', debounce((e) => { state.search = e.target.value; state.listLimit = LIST_PAGE; renderList(); }, 150));
  $('more-conversations').addEventListener('click', () => { state.listLimit += LIST_PAGE; renderList(); });
  $('show-branches').addEventListener('change', (e) => { state.showBranches = e.target.checked; renderList(); renderThread(); });
  $('show-other').addEventListener('change', (e) => { state.showOther = e.target.checked; renderList(); renderThread(); });
  for (const role of ['user', 'agent']) $(`speaker-${role}`).addEventListener('input', (e) => { state.speakers[role] = e.target.value; renderThread(); renderRecords(); validate(); });

  document.addEventListener('selectionchange', debounce(() => {
    if (!state.data) return;
    const s = readSelection();
    if (s === undefined) return;
    state.selection = s; renderSelection();
  }, 60));
  $('new-record').addEventListener('click', () => useSelection(null));
  $('add-to-record').addEventListener('click', () => useSelection(state.records.find((r) => String(r.uid) === $('target-record').value)));

  $('title').addEventListener('input', (e) => { state.title = e.target.value; validate(); });
  $('description').addEventListener('input', (e) => { state.description = e.target.value; validate(); });
  $('download-pack').addEventListener('click', downloadPack);
  $('download-inputs').addEventListener('click', downloadInputs);
  $('save-folder').hidden = typeof window.showDirectoryPicker !== 'function';
  $('save-folder').addEventListener('click', saveFolder);
  $('save-draft').addEventListener('click', saveDraft);
  $('load-draft').addEventListener('change', (e) => { const f = e.target.files[0]; e.target.value = ''; if (f) openDraft(f); });
  addEventListener('beforeunload', (e) => { if (state.records.length) e.preventDefault(); });
}

init();
