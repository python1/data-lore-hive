import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { ExportError, loadExport, loadExports } from '../src/load-export.mjs';
import { bytesSource } from '../src/zip.mjs';
import { nodeZip } from './helpers.mjs';

const fixtures = resolve('test/fixtures');
const chatgptJson = readFileSync(join(fixtures, 'chatgpt-conversations.json'));
const claudeJson = readFileSync(join(fixtures, 'claude-conversations.json'));
const load = (name, bytes) => loadExport({ name, source: bytesSource(new Uint8Array(bytes)) });
const PACK_DATE = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|\+00:00)$/;
const rows = (r) => r.conversations.flatMap((c) => c.messages.map((m) => [c.title, m.current ? 'current' : 'branch', m.role, m.kind, m.date, m.attachments, m.text]));
const sortWarnings = (w) => [...w].sort((a, b) => `${a.code}${a.detail}`.localeCompare(`${b.code}${b.detail}`));

test('ChatGPT: follows current_node, keeps branches, reads every part type it knows and counts the rest', async () => {
  const r = await load('conversations.json', chatgptJson);
  assert.equal(r.format, 'chatgpt');
  assert.deepEqual(rows(r), [
    ['Seed swap plans', 'current', 'user', 'text', '2026-03-02T08:15:00.000Z', 0, 'Morning! I look after the tomato beds at the Larkfield community garden. Can you help me plan the seed swap?'],
    ['Seed swap plans', 'branch', 'agent', 'text', '2026-03-02T08:15:20.000Z', 0, 'Sure. Draft one: hold the swap sometime in April.'],
    ['Seed swap plans', 'current', 'agent', 'text', '2026-03-02T08:16:00.000Z', 0, "Happy to help, Rowan. Let's hold the seed swap on the first Saturday in April."],
    ['Seed swap plans', 'branch', 'user', 'text', '2026-03-02T08:20:00.000Z', 0, 'Can we do it by the shed?'],
    ['Seed swap plans', 'branch', 'agent', 'text', '2026-03-02T08:20:10.000Z', 0, 'Yes, by the shed works.'],
    ['Seed swap plans', 'current', 'user', 'text', '2026-03-02T08:21:00.000Z', 0, 'Can we do it by the greenhouse instead? The shed code changed.'],
    ['Seed swap plans', 'current', 'agent', 'text', '2026-03-02T08:21:30.250Z', 0, "The greenhouse is a good spot. I'll note that the shed code changed."],
    ['Shed rota', 'current', 'user', 'text', '2026-03-09T18:00:00.000Z', 1, 'Here is the rota photo. Ivy waters on Mondays 🌱, Rowan on Thursdays.'],
    ['Shed rota', 'current', 'agent', 'reasoning', '2026-03-09T18:00:07.000Z', 0, 'The photo lists two people and two days.'],
    ['Shed rota', 'current', 'agent', 'reasoning', '2026-03-09T18:00:08.000Z', 0, 'Thought for 4 seconds'],
    ['Shed rota', 'current', 'agent', 'text', '2026-03-09T18:00:10.000Z', 0, 'Rota:\r\n- Ivy: Mondays\r\n- Rowan: Thursdays\r\nThe cafe\u0301 opens at 9. Water early, water deeply, water early.'],
    ['Shed rota', 'current', 'user', 'text', null, 1, 'Thanks, that matches what I said on the phone.'],
    ['Shed rota', 'current', 'agent', 'other', '2026-03-09T18:01:00.000Z', 0, "A widget type this page doesn't know yet."],
    ['Shed rota', 'current', 'agent', 'code', '2026-03-09T18:01:10.000Z', 0, "print('water early')"],
    ['Shed rota', 'current', 'user', 'text', '2026-03-09T18:02:00.000Z', 0, 'Odd byte here: \uFFFD end.'],
    ['Compost day', 'current', 'user', 'text', '2026-03-12T07:30:00.000Z', 0, 'The compost bins get turned on the first of the month.'],
    ['Compost day', 'current', 'agent', 'text', '2026-03-12T07:30:04.000Z', 0, 'Noted: compost on the first of each month.']
  ]);
  assert.deepEqual(sortWarnings(r.warnings), sortWarnings([
    { code: 'skipped-role', detail: 'system', count: 1 }, { code: 'skipped-role', detail: 'tool', count: 1 },
    { code: 'skipped-hidden-message', detail: '', count: 1 }, { code: 'skipped-tool-call', detail: 'python', count: 1 },
    { code: 'message-without-date', detail: '', count: 1 }, { code: 'unknown-content-type', detail: 'future_widget', count: 1 },
    { code: 'unknown-content-type', detail: 'hologram', count: 1 }, { code: 'replaced-broken-characters', detail: '', count: 1 },
    { code: 'skipped-empty-message', detail: '', count: 1 }, { code: 'skipped-empty-conversation', detail: '', count: 1 },
    { code: 'missing-current-node', detail: '', count: 1 }, { code: 'skipped-conversation-without-messages', detail: '', count: 1 }
  ]));
  assert.deepEqual(r.conversations.map((c) => c.messages.map((m) => m.order)).flat(), [...Array(17).keys()]);
});

test('Claude: text blocks, thinking as its own message, legacy text, tree branches and date normalisation', async () => {
  const r = await load('conversations.json', claudeJson);
  assert.equal(r.format, 'claude');
  assert.deepEqual(rows(r), [
    ['Greenhouse watering', 'current', 'user', 'text', '2026-03-06T17:00:00.123456Z', 1, 'Who waters the greenhouse on Fridays?'],
    ['Greenhouse watering', 'current', 'agent', 'reasoning', '2026-03-06T17:00:05.5+00:00', 0, 'The rota file says Tally on Fridays.'],
    ['Greenhouse watering', 'current', 'agent', 'text', '2026-03-06T17:00:05.5+00:00', 0, 'According to the rota you shared, Tally waters the greenhouse on Fridays.'],
    ['Greenhouse watering', 'current', 'user', 'text', '2026-03-06T17:00:00.000Z', 0, 'Great. Remind me: the compost bins get turned on the first of the month.'],
    ['Greenhouse watering', 'current', 'agent', 'text', '2026-03-06T17:00:20Z', 1, 'Noted: compost bins are turned on the first of the month.'],
    ['Greenhouse watering', 'current', 'user', 'text', '2026-03-06T17:01:00Z', 0, 'Legacy text only message about the café 🌻.'],
    ['Regenerated answer', 'current', 'user', 'text', '2026-03-07T09:00:00Z', 0, 'Which bed gets the beans?'],
    ['Regenerated answer', 'branch', 'agent', 'text', '2026-03-07T09:00:05Z', 0, 'Bed 3, I think.'],
    ['Regenerated answer', 'current', 'agent', 'text', '2026-03-07T09:02:00Z', 0, 'Bed 4 gets the beans; bed 3 is resting this year.'],
    ['Regenerated answer', 'current', 'user', 'text', '2026-03-07T09:03:00Z', 0, 'Bed 4 it is.']
  ]);
  assert.deepEqual(sortWarnings(r.warnings), sortWarnings([
    { code: 'skipped-content-type', detail: 'tool_use', count: 1 }, { code: 'skipped-content-type', detail: 'tool_result', count: 1 },
    { code: 'unknown-content-type', detail: 'hologram', count: 1 }, { code: 'skipped-empty-message', detail: '', count: 1 },
    { code: 'skipped-role', detail: 'system', count: 1 }, { code: 'skipped-conversation-without-messages', detail: '', count: 1 },
    { code: 'skipped-empty-conversation', detail: '', count: 1 }
  ]));
});

test('zip exports: finds conversations.json among media and other files, reads split files in order', async () => {
  const fromJson = await load('conversations.json', chatgptJson);
  const zipped = await load('export.zip', nodeZip({ 'chat.html': '<html>', 'user.json': '{}', 'file-invented-0001.png': Buffer.alloc(5000, 1), 'conversations.json': chatgptJson }));
  assert.deepEqual(zipped, fromJson);
  const list = JSON.parse(claudeJson);
  const split = await load('export.zip', nodeZip({ 'export/conversations-001.json': JSON.stringify(list.slice(2)), 'export/conversations-000.json': JSON.stringify(list.slice(0, 2)), 'users.json': '[]' }));
  assert.deepEqual(split, await load('conversations.json', claudeJson));
});

test('plain messages.jsonl in the builder format loads as one conversation with speakers kept', async () => {
  const r = await load('messages.jsonl', readFileSync(resolve('../examples/input/messages.jsonl')));
  assert.equal(r.format, 'messages-jsonl');
  assert.equal(r.conversations.length, 1);
  assert.deepEqual(r.conversations[0].messages[0], { key: 'jsonl/1', conversationId: 'jsonl', role: null, speaker: 'Rowan', kind: 'text', date: '2026-03-02T08:15:00Z', text: 'Morning! I look after the tomato beds at the Larkfield community garden.', current: true, attachments: 0, order: 0 });
  await assert.rejects(load('messages.jsonl', Buffer.from('{"id": 1}\n')), (e) => e instanceof ExportError && /messages line 1: date must be UTC/.test(e.message));
});

test('unusable files fail with an ExportError that never quotes the file contents', async () => {
  const cases = [
    ['conversations.json', Buffer.from('{"secret": "tomato beds"}'), /expected a list of conversations/],
    ['conversations.json', Buffer.from('[{"secret": "tomato beds"}]'), /format this page does not recognise yet/],
    ['conversations.json', Buffer.from('[{"title": "tomato beds", '), /not valid JSON$/],
    ['conversations.json', Buffer.from([0x5b, 0xff, 0x5d]), /not valid UTF-8/],
    ['conversations.json', Buffer.from('[]'), /contains no conversations/],
    ['export.zip', nodeZip({ 'notes/tomato beds.txt': 'x' }), /no conversations\.json inside this zip/],
    ['export.zip', nodeZip({ 'conversations-000.json': chatgptJson, 'conversations-001.json': claudeJson }), /mixes ChatGPT and Claude/]
  ];
  for (const [name, bytes, pattern] of cases) {
    await assert.rejects(load(name, bytes), (e) => e instanceof ExportError && pattern.test(e.message) && !e.message.includes('tomato'), String(pattern));
  }
  const damaged = nodeZip({ 'conversations.json': chatgptJson }, { method: 0 }); damaged[100] ^= 0xff;
  await assert.rejects(load('export.zip', damaged), (e) => e instanceof ExportError && /CRC or size mismatch/.test(e.message));
});

// Format drift: randomly delete keys and change value types throughout both fixtures. The loader
// must either succeed with well-formed messages or fail with an ExportError, never crash.
test('randomly mutated exports never crash the loader and never produce malformed messages', async () => {
  let seed = 12345;
  const rnd = (n) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
  const junk = [null, 0, 1.5, -1, '', 'x', true, [], {}, ['x'], { content_type: 'text' }, '2026-13-45T99:00:00Z'];
  const mutate = (v, depth) => {
    if (rnd(40) === 0) return junk[rnd(junk.length)];
    if (Array.isArray(v)) return v.filter(() => rnd(30) !== 0).map((x) => mutate(x, depth + 1));
    if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).filter(() => rnd(25) !== 0).map(([k, x]) => [k, mutate(x, depth + 1)]));
    return v;
  };
  let ok = 0, refused = 0;
  for (const source of [chatgptJson, claudeJson, ...[0, 1].map((i) => readFileSync(join(fixtures, `claude-current-part-00${i}.json`)))]) {
    const base = JSON.parse(source);
    for (let i = 0; i < 400; i++) {
      const bytes = Buffer.from(JSON.stringify(mutate(base, 0)));
      let r;
      try { r = await load('conversations.json', bytes); } catch (e) { assert.ok(e instanceof ExportError, `crash: ${e.stack}`); refused++; continue; }
      ok++;
      const keys = new Set();
      for (const c of r.conversations) for (const m of c.messages) {
        assert.ok(typeof m.text === 'string' && m.text.trim() && m.text.isWellFormed());
        assert.ok(m.date === null || PACK_DATE.test(m.date), m.date);
        assert.ok(m.role === 'user' || m.role === 'agent');
        assert.ok(!keys.has(m.key)); keys.add(m.key);
      }
    }
  }
  assert.ok(ok > 600 && refused > 0, `ok ${ok}, refused ${refused}`); // single-conversation parts are often emptied by mutation
});

// Current Claude exports: one zip per kind of data, downloaded one by one; chats are in
// conversations-NNN.zip parts. The manifest's real structure is not known here; this one is invented.
const claudePart = (i) => readFileSync(join(fixtures, `claude-current-part-00${i}.json`));
const part = (i) => ({ name: `conversations-00${i}.zip`, bytes: nodeZip({ 'conversations.json': claudePart(i) }) });
const loadMany = (files) => loadExports(files.map(({ name, bytes }) => ({ name, source: bytesSource(new Uint8Array(bytes)) })));
const neverRead = (name) => ({ name, source: { size: 100, read: async () => { throw new Error(`${name} was opened`); } } });

test('current Claude export: conversations parts load together; injected prompts never become messages', async () => {
  const r = await loadMany([part(1), part(0)]);
  assert.equal(r.format, 'claude');
  assert.equal(r.used, 2);
  assert.deepEqual(r.notes, []);
  assert.deepEqual(rows(r), [
    ['Tool shed inventory', 'current', 'user', 'text', '2026-04-04T10:00:00Z', 0, 'Can you list what is in the tool shed?'],
    ['Tool shed inventory', 'current', 'agent', 'text', '2026-04-04T10:00:09Z', 0, 'The shed holds two spades, a wheelbarrow and the seed tin.'],
    ['Tool shed inventory', 'current', 'agent', 'text', '2026-04-04T10:05:04Z', 0, 'Noted. The seed tin stays on the top shelf.'],
    ['Tool shed inventory', 'current', 'user', 'text', '2026-04-04T10:10:00Z', 4, 'Here is the shed map.'],
    ['Pond day', 'current', 'user', 'text', '2026-04-11T08:00:00Z', 0, 'When do we clear the pond?'],
    ['Pond day', 'branch', 'agent', 'reasoning', '2026-04-11T08:00:06Z', 0, 'The plan said late April.'],
    ['Pond day', 'branch', 'agent', 'text', '2026-04-11T08:00:06Z', 0, 'Late April, I believe.'],
    ['Pond day', 'current', 'agent', 'text', '2026-04-11T08:01:00Z', 0, 'The pond gets cleared on the last Sunday of April.'],
    ['Pond day', 'current', 'user', 'text', '2026-04-11T08:02:00Z', 0, 'Last Sunday of April. Got it, café after.']
  ]);
  assert.ok(!JSON.stringify(r.conversations).includes('INJECTED'), 'no injected prompt text anywhere in the loaded data');
  assert.deepEqual(sortWarnings(r.warnings), sortWarnings([
    { code: 'skipped-injected-prompt', detail: '', count: 2 }, { code: 'skipped-hidden-thinking', detail: '', count: 1 },
    { code: 'skipped-content-type', detail: 'tool_use', count: 1 }, { code: 'skipped-content-type', detail: 'tool_result', count: 1 },
    { code: 'skipped-content-type', detail: 'flag', count: 1 }, { code: 'skipped-content-type', detail: 'token_budget', count: 1 },
    { code: 'skipped-empty-message', detail: '', count: 1 }
  ]));
  // The conversations.json inside a part loads on its own too.
  assert.equal((await loadExport({ name: 'conversations.json', source: bytesSource(new Uint8Array(claudePart(0))) })).conversations.length, 1);
});

test('other parts of a Claude export are noted and never opened; an unknown manifest is noted, not fatal', async () => {
  const manifest = { name: 'manifest.json', bytes: Buffer.from(JSON.stringify({ invented: 'manifest', files: [{ kind: 'conversations' }] })) };
  const r = await loadExports([
    ...[part(0), manifest].map(({ name, bytes }) => ({ name, source: bytesSource(new Uint8Array(bytes)) })),
    ...['memories-000.zip', 'projects-000.zip', 'frames-000.zip', 'light_metadata-000.zip'].map(neverRead)
  ]);
  assert.equal(r.used, 1);
  assert.deepEqual(r.notes.map((n) => [n.name, n.text]), [
    ['frames-000.zip', 'not needed for a memory pack (only the conversations files are), so it was not opened'],
    ['light_metadata-000.zip', 'not needed for a memory pack (only the conversations files are), so it was not opened'],
    ['manifest.json', 'not used: not a ChatGPT or Claude conversations file (expected a list of conversations)'],
    ['memories-000.zip', 'not needed for a memory pack (only the conversations files are), so it was not opened'],
    ['projects-000.zip', 'not needed for a memory pack (only the conversations files are), so it was not opened']
  ]);
  const listManifest = { name: 'export-manifest.json', bytes: Buffer.from(JSON.stringify([{ invented: 'entry' }])) };
  assert.match((await loadMany([part(0), listManifest])).notes[0].text, /^not used: conversations are in a format this page does not recognise yet/);
});

test('choosing only non-chat files, or a broken conversations part, fails with a clear message', async () => {
  await assert.rejects(loadExports([neverRead('memories-000.zip')]),
    (e) => e instanceof ExportError && e.message === 'memories-000.zip: not needed for a memory pack (only the conversations files are). Choose conversations-000.zip instead (and conversations-001.zip and so on, if your export has more parts).');
  await assert.rejects(loadMany([{ name: 'manifest.json', bytes: Buffer.from('{}') }, { name: 'projects-000.zip', bytes: Buffer.from('x') }]),
    (e) => e instanceof ExportError && /^None of the chosen files holds conversations \(manifest\.json, projects-000\.zip\)\. For a Claude export, choose conversations-000\.zip/.test(e.message));
  const broken = part(1); broken.bytes = Buffer.from(broken.bytes); broken.bytes[60] ^= 0xff;
  await assert.rejects(loadMany([part(0), broken]), (e) => e instanceof ExportError && /^conversations-001\.zip: /.test(e.message));
  await assert.rejects(loadMany([part(0), { name: 'messages.jsonl', bytes: readFileSync(resolve('../examples/input/messages.jsonl')) }]), /mixes ChatGPT and Claude|on its own/);
});

test('a conversation present in two parts is kept once', async () => {
  const both = JSON.stringify([...JSON.parse(claudePart(0)), ...JSON.parse(claudePart(1))]);
  const r = await loadMany([part(0), { name: 'conversations-001.zip', bytes: nodeZip({ 'conversations.json': both }) }]);
  assert.deepEqual(r.conversations.map((c) => c.title), ['Tool shed inventory', 'Pond day']);
  assert.deepEqual(r.warnings.filter((w) => w.code === 'duplicate-conversation'), [{ code: 'duplicate-conversation', detail: '', count: 1 }]);
});
