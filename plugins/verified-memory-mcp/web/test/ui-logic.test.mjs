import test from 'node:test';
import assert from 'node:assert/strict';
import { applyDraft, codePointToUtf16, locateError, makeDraft, makeQuote, nextRecordId, plural, rebuildCommand, recordsForBuild, searchConversations, slug, trimSelection, visibleMessages, warningText } from '../src/ui-logic.mjs';

const message = (text, extra = {}) => ({ key: 'c/1', conversationId: 'c', role: 'user', kind: 'text', date: '2026-03-02T08:15:00Z', text, current: true, attachments: 0, order: 0, ...extra });

test('selections are trimmed of surrounding whitespace and turned into code-point quotes', () => {
  const m = message('🌱 Water early.\r\n  Then rest. ');
  assert.deepEqual(trimSelection(m.text, 2, 18), { s16: 3, e16: 15 });
  assert.deepEqual(makeQuote(m, 2, 18), { key: 'c/1', quote: 'Water early.', start: 2, s16: 3, e16: 15 });
  assert.equal(trimSelection(m.text, 15, 19), null);
  assert.throws(() => makeQuote(m, 15, 19), /only spaces/);
  assert.equal(codePointToUtf16(m.text, 2), 3);
  assert.equal(codePointToUtf16('a😀b😀c', 4), 6);
});

test('record IDs, slugs and records handed to the builder', () => {
  assert.equal(nextRecordId([]), 'M-1');
  assert.equal(nextRecordId([{ record_id: 'M-2' }]), 'M-3');
  assert.equal(nextRecordId([{ record_id: 'M-3' }, { record_id: 'M-2' }]), 'M-4');
  assert.equal(slug('Mémoire du jardin — 2026!'), 'memoire-du-jardin-2026');
  assert.equal(slug('  '), 'memory-pack');
  assert.deepEqual(recordsForBuild([{ uid: 1, record_id: ' M-1 ', role: 'user', topic: 't', category: 'c', statement: ' ', speaker: '', quotes: [{ key: 'k', quote: 'q', start: 0, s16: 0, e16: 1 }] }]),
    [{ record_id: 'M-1', role: 'user', topic: 't', category: 'c', statement: undefined, speaker: undefined, quotes: [{ key: 'k', quote: 'q', start: 0 }] }]);
});

test('builder errors are pointed at the record, quote or field they are about', () => {
  assert.deepEqual(locateError('records line 3: topic and category are required'), { record: 2, quote: null, text: 'topic and category are required' });
  assert.deepEqual(locateError('records line 1 quote 2: quote does not match the message at start 4'), { record: 0, quote: 1, text: 'quote does not match the message at start 4' });
  assert.deepEqual(locateError('record 2 quote 1: the export has no date for this message, so it cannot be quoted'), { record: 1, quote: 0, text: 'the export has no date for this message, so it cannot be quoted' });
  assert.equal(locateError('messages line 4: speaker is required').field, 'speakers');
  assert.equal(locateError('--title must be one line').field, 'title');
  assert.deepEqual(locateError('at most 10,000 records per pack'), { record: null, quote: null, text: 'at most 10,000 records per pack' });
});

test('view options and search over titles and visible message text', () => {
  const conversations = [
    { id: 'a', title: 'Seed swap', messages: [message('tomato beds'), message('old draft about beans', { key: 'a/2', current: false }), message('print(1)', { key: 'a/3', kind: 'code' })] },
    { id: 'b', title: 'Compost', messages: [message('Beans in bed 4', { key: 'b/1' })] }
  ];
  const opts = { showBranches: false, showOther: false };
  assert.deepEqual(visibleMessages(conversations[0], opts).map((m) => m.text), ['tomato beds']);
  assert.equal(visibleMessages(conversations[0], { showBranches: true, showOther: true }).length, 3);
  assert.deepEqual(searchConversations(conversations, 'BEANS', opts).map((r) => [r.conversation.id, r.hits]), [['b', 1]]);
  assert.deepEqual(searchConversations(conversations, 'beans', { ...opts, showBranches: true }).map((r) => [r.conversation.id, r.hits]), [['a', 1], ['b', 1]]);
  assert.deepEqual(searchConversations(conversations, 'seed', opts).map((r) => [r.conversation.id, r.hits]), [['a', 0]]);
  assert.equal(searchConversations(conversations, '', opts).length, 2);
});

test('drafts round-trip and drop quotes that no longer match the export', () => {
  const m = message('I look after the tomato beds.');
  const messages = new Map([[m.key, m]]);
  const records = [{ uid: 7, record_id: 'M-1', role: 'user', topic: 'Role', category: 'profile', statement: '', speaker: '', quotes: [makeQuote(m, 2, 28)] }];
  const draft = JSON.parse(JSON.stringify(makeDraft({ format: 'chatgpt', speakers: { user: 'Rowan', agent: 'ChatGPT' }, title: 'T', description: '', records })));
  assert.equal(JSON.stringify(draft).includes('"uid"'), false);
  let n = 100;
  const back = applyDraft(draft, messages, () => ++n);
  assert.deepEqual(back.records, [{ ...records[0], uid: 101 }]);
  assert.deepEqual(back.dropped, []);
  const edited = new Map([[m.key, { ...m, text: 'I look after the bean beds.' }]]);
  const partial = applyDraft(draft, edited, () => ++n);
  assert.deepEqual(partial.records[0].quotes, []);
  assert.deepEqual(partial.dropped, ['M-1: “look after the tomato beds”']);
  assert.throws(() => applyDraft({ type: 'other' }, messages, () => 1), /not a pack maker draft/);
});

test('warning texts and the rebuild command', () => {
  assert.equal(warningText({ code: 'skipped-role', detail: 'tool', count: 3 }), 'Messages from “tool” (not you or the assistant) were left out (3)');
  assert.equal(warningText({ code: 'brand-new-code', detail: 'x', count: 1 }), 'Brand-new-code (x) (1)');
  assert.deepEqual([plural(0, 'record'), plural(1, 'record'), plural(2, 'record'), plural(1, 'kind'), plural(3, 'matching message')], ['0 records', '1 record', '2 records', '1 kind', '3 matching messages']);
  assert.equal(rebuildCommand("Rowan's garden", ''), "npx -y -p @python1/verified-memory-mcp verified-memory-build-pack \\\n  --messages messages.jsonl --records records.jsonl --out NEW_FOLDER \\\n  --title 'Rowan'\\''s garden'");
});
