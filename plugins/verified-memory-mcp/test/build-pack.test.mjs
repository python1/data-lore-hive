import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, readdirSync, rmSync, existsSync, mkdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
const input = resolve('examples/input');
const committed = resolve('examples/pack');
const FILES = ['MEMORY.md', 'README.md', 'SHA256SUMS', 'records.jsonl'];
function workdir(t) {
  const root = mkdtempSync(join(tmpdir(), 'build-pack-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  return root;
}
function build(args) {
  return spawnSync(process.execPath, ['tools/build-pack.mjs', ...args], { encoding: 'utf8', timeout: 10000 });
}
const exampleArgs = (out, messages = join(input, 'messages.jsonl'), records = join(input, 'records.jsonl')) =>
  ['--messages', messages, '--records', records, '--out', out, '--title', 'Larkfield garden example pack',
    '--description', 'Invented example data for verified-memory-mcp. Not a real person or conversation.'];
function refusesWithoutWriting(t, messages, records, pattern) {
  const root = workdir(t);
  const m = join(root, 'messages.jsonl'), r = join(root, 'records.jsonl');
  writeFileSync(m, messages.map(x => JSON.stringify(x)).join('\n') + '\n');
  writeFileSync(r, records.map(x => JSON.stringify(x)).join('\n') + '\n');
  const p = build(exampleArgs(join(root, 'pack'), m, r));
  assert.equal(p.status, 1, p.stdout); assert.match(p.stderr, pattern);
  assert.deepEqual(readdirSync(root).sort(), ['messages.jsonl', 'records.jsonl'], 'no pack or staging directory left behind');
}
const msg = { id: 1, date: '2026-03-02T08:15:00Z', speaker: 'Rowan', text: 'water the beds, then water the beds again.' };
const rec = (quotes, extra = {}) => ({ record_id: 'M-x-1', role: 'user', topic: 't', category: 'c', quotes, ...extra });

test('builder reproduces the committed example pack byte for byte', (t) => {
  const out = join(workdir(t), 'pack');
  const p = build(exampleArgs(out));
  assert.equal(p.status, 0, p.stderr);
  assert.deepEqual(readdirSync(out).sort(), FILES);
  for (const f of FILES) assert.deepEqual(readFileSync(join(out, f)), readFileSync(join(committed, f)), f);
});

test('installed-style stdio server loads the example pack and returns an exact quote', async (t) => {
  const client = new Client({ name: 'example-test', version: '1.0.0' });
  await client.connect(new StdioClientTransport({ command: process.execPath, args: [resolve('dist/index.js'), '--pack', committed] }));
  t.after(() => client.close());
  const search = (await client.callTool({ name: 'verified_memory_search', arguments: { query: 'café seedlings' } })).structuredContent;
  assert.equal(search.verification.sha256sums, 'passed'); assert.equal(search.verification.records, 4);
  assert.equal(search.matched, 1);
  assert.deepEqual(search.matches[0].citations, [{ quote: 'the café on the corner sells seedlings on Saturdays.', source_message_id: 3, date: '2026-03-02T08:20:00Z', speaker: 'Rowan' }]);
  const record = (await client.callTool({ name: 'verified_memory_get', arguments: { id: 'M-garden-4' } })).structuredContent.record;
  assert.equal(record.evidence.length, 2);
  assert.equal(record.date_first_utc, '2026-03-09T18:05:00Z'); assert.equal(record.date_last_utc, '2026-03-16T18:10:00Z');
  const messages = readFileSync(join(input, 'messages.jsonl'), 'utf8').trim().split('\n').map(l => JSON.parse(l));
  for (const c of record.evidence) {
    const text = messages.find(m => m.id === c.message_id).text;
    assert.equal([...text].slice(c.start, c.end).join(''), c.quote);
  }
});

test('builder refuses a quote that is not verbatim', (t) =>
  refusesWithoutWriting(t, [msg], [rec([{ message_id: 1, quote: 'water the bed, then' }])], /not verbatim/));
test('builder refuses an ambiguous quote unless start is given', (t) => {
  refusesWithoutWriting(t, [msg], [rec([{ message_id: 1, quote: 'water the beds' }])], /occurs 2 times.*one of 0, 21/);
  refusesWithoutWriting(t, [msg], [rec([{ message_id: 1, quote: 'water the beds', start: 17 }])], /does not match the message at start 17/);
});
test('builder refuses unknown messages, unknown fields, bad dates and duplicate IDs', (t) => {
  refusesWithoutWriting(t, [msg], [rec([{ message_id: 9, quote: 'then' }])], /message_id 9 is not in the messages file/);
  refusesWithoutWriting(t, [msg], [rec([{ message_id: 1, quote: 'then' }], { statment: 'typo' })], /unknown field "statment"/);
  refusesWithoutWriting(t, [{ ...msg, date: '2026-03-02 08:15' }], [rec([{ message_id: 1, quote: 'then' }])], /date must be UTC ISO 8601/);
  refusesWithoutWriting(t, [msg, msg], [rec([{ message_id: 1, quote: 'then' }])], /duplicate message id 1/);
  refusesWithoutWriting(t, [msg], [rec([{ message_id: 1, quote: 'then' }]), rec([{ message_id: 1, quote: 'again' }])], /duplicate record_id/);
});
test('builder accepts a disambiguated quote and computes code-point offsets', (t) => {
  const root = workdir(t);
  const m = join(root, 'm.jsonl'), r = join(root, 'r.jsonl');
  writeFileSync(m, JSON.stringify({ ...msg, text: '🌱 water the beds, then water the beds again.' }) + '\n');
  writeFileSync(r, JSON.stringify(rec([{ message_id: 1, quote: 'water the beds', start: 23 }])) + '\n');
  const p = build(['--messages', m, '--records', r, '--out', join(root, 'pack')]);
  assert.equal(p.status, 0, p.stderr);
  const c = JSON.parse(readFileSync(join(root, 'pack', 'records.jsonl'), 'utf8')).evidence[0];
  assert.deepEqual([c.start, c.end], [23, 37]);
});
test('builder never overwrites an existing directory', (t) => {
  const out = join(workdir(t), 'pack'); mkdirSync(out);
  const p = build(exampleArgs(out));
  assert.equal(p.status, 1); assert.match(p.stderr, /already exists/);
  assert.deepEqual(readdirSync(out), []);
  assert.ok(!existsSync(join(out, 'records.jsonl')));
});
