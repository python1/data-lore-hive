// review: proposed memory writes, approved by the owner into the next signed pack. Real
// ssh-keygen with a throwaway passphrase-protected key (as in sign-pack.test.mjs) and the
// fictional Brightline example in examples/proposals/.
import test from 'node:test';
import assert from 'node:assert/strict';
import { chmodSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { loadPack } from '../dist/pack.js';
const example = resolve('examples/proposals');
const PASSPHRASE = 'fictional passphrase for tests';
const hasSshKeygen = spawnSync('ssh-keygen', ['-Y', 'verify'], { encoding: 'utf8' }).error === undefined;
const skip = hasSshKeygen ? false : 'ssh-keygen not installed';

/** root/{source,keys,work}, plus work/pack-3: the example source signed with sequence 3. */
function setup(t, { currentSequence = 3 } = {}) {
  const root = mkdtempSync(join(tmpdir(), 'verified-memory-review-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const source = join(root, 'source'), keys = join(root, 'keys'), work = join(root, 'work');
  cpSync(join(example, 'source'), source, { recursive: true }); mkdirSync(keys); mkdirSync(work);
  const key = join(keys, 'pack_signing');
  assert.equal(spawnSync('ssh-keygen', ['-q', '-t', 'ed25519', '-N', PASSPHRASE, '-C', 'fictional-signing-key', '-f', key]).status, 0);
  const askpass = join(root, process.platform === 'win32' ? 'askpass.cmd' : 'askpass.sh');
  writeFileSync(askpass, process.platform === 'win32' ? `@echo ${PASSPHRASE}\r\n` : `#!/bin/sh\necho '${PASSPHRASE}'\n`); chmodSync(askpass, 0o700);
  const env = { root, source, keys, work, key, askpass, proposals: join(example, 'proposals.jsonl') };
  const unsigned = join(work, 'unsigned');
  assert.equal(run(env, 'build-pack.mjs', ['--messages', join(source, 'messages.jsonl'), '--records', join(source, 'records.jsonl'), '--out', unsigned]).status, 0);
  env.current = join(work, `pack-${currentSequence}`);
  const signed = run(env, 'sign-pack.mjs', ['--pack', unsigned, '--key', key, '--expires', '30d', '--sequence', String(currentSequence), '--out', env.current]);
  assert.equal(signed.status, 0, signed.stderr);
  return env;
}
function run(env, script, args, input) {
  return spawnSync(process.execPath, [resolve('tools', script), ...args], {
    encoding: 'utf8', timeout: 30000, input, stdio: [input === undefined ? 'ignore' : 'pipe', 'pipe', 'pipe'],
    env: { ...(process.platform === 'win32' ? process.env : { PATH: process.env.PATH, HOME: env.root }), SSH_ASKPASS: env.askpass, SSH_ASKPASS_REQUIRE: 'force', DISPLAY: ':0' }
  });
}
const review = (env, out, extra = [], input) =>
  run(env, 'review.mjs', ['--source', env.source, '--proposals', env.proposals, '--key', env.key, '--expires', '30d', '--current', env.current, '--out', out, ...extra], input);
const rows = (path) => readFileSync(path, 'utf8').split('\n').filter(Boolean).map((l) => JSON.parse(l));
const pubLine = (key) => `publisher ${readFileSync(key + '.pub', 'utf8').split(' ').slice(0, 2).join(' ')}`;
const snapshot = (dir) => Object.fromEntries(readdirSync(dir).map((n) => [n, readFileSync(join(dir, n))]));
const leftovers = (dir) => readdirSync(dir).filter((n) => n.startsWith('.'));

test('approved proposals: 4471 -> 5521 and a new record go into a pack signed with the next sequence', { skip }, async (t) => {
  const env = setup(t), out = join(env.work, 'pack-4');
  const before = readFileSync(join(env.source, 'messages.jsonl'), 'utf8');
  const p = review(env, out, ['--approve-ids', 'P1,P2']);
  assert.equal(p.status, 0, p.stderr);
  assert.match(p.stdout, /P1 {2}replace M-brightline-door {3}proposed by studio-assistant\n/);
  assert.match(p.stdout, /now: {5}The Brightline front door keypad code is 4471\.\n.*\n {4}new: {5}The Brightline front door keypad code is 5521\./);
  assert.match(p.stdout, /P1 approved, P2 approved, P3 invalid\n/);
  assert.match(p.stdout, /--min-sequence 4\n$/);

  // Source: the replaced record keeps its place; the new record and both new messages are appended.
  const records = rows(join(env.source, 'records.jsonl'));
  assert.deepEqual(records.map((r) => r.record_id), ['M-brightline-1', 'M-brightline-door', 'M-brightline-3', 'M-brightline-ink']);
  assert.equal(records[1].statement, 'The Brightline front door keypad code is 5521.');
  assert.ok(readFileSync(join(env.source, 'messages.jsonl'), 'utf8').startsWith(before), 'existing messages are kept byte for byte');
  assert.deepEqual(rows(join(env.source, 'messages.jsonl')).map((m) => m.id), [1, 2, 3, 4, 5]);

  // The pack: signed sequence 4, loads with --min-sequence 4 in strict mode, refuses 5.
  assert.equal(JSON.parse(readFileSync(join(out, 'PACK.json'), 'utf8')).sequence, 4);
  const pack = loadPack(out, { trustedKeys: [pubLine(env.key)], strict: true, minSequence: 4 });
  assert.equal(pack.verification.freshness.sequence, 4); assert.equal(pack.verification.records, 4);
  assert.equal(pack.get('M-brightline-door').evidence[0].quote, 'The new door code is 5521.');
  assert.throws(() => loadPack(out, { trustedKeys: [pubLine(env.key)], minSequence: 5 }), /pack sequence 4 is lower than the minimum 5/);
  // The previous pack is now a rollback: refused at the new minimum.
  assert.throws(() => loadPack(env.current, { trustedKeys: [pubLine(env.key)], minSequence: 4 }), /pack sequence 3 is lower than the minimum 4/);

  // Log: every proposal, with what a replace overwrote.
  const log = rows(join(env.source, 'review-log.jsonl'));
  assert.deepEqual(log.map((e) => [e.proposal, e.decision]), [['P1', 'approved'], ['P2', 'approved'], ['P3', 'invalid']]);
  assert.equal(log[0].replaced.statement, 'The Brightline front door keypad code is 4471.');
  assert.equal(log[0].sequence, 4); assert.equal(log[0].pack, out);
  assert.deepEqual(leftovers(env.work), []); assert.deepEqual(leftovers(env.source), []);

  // The MCP server serves it with the new minimum, read-only as before.
  const fp = /^--trusted-fingerprint (SHA256:\S+)$/m.exec(p.stdout)[1];
  const client = new Client({ name: 'fictional-test', version: '1.0.0' });
  await client.connect(new StdioClientTransport({ command: process.execPath, args: ['dist/index.js', '--pack', out, '--trusted-fingerprint', fp, '--min-sequence', '4', '--strict'], stderr: 'pipe' }));
  try {
    assert.deepEqual((await client.listTools()).tools.map((x) => x.name), ['verified_memory_search', 'verified_memory_get']);
    const hit = await client.callTool({ name: 'verified_memory_search', arguments: { query: 'door code' } });
    assert.equal(hit.structuredContent.matched, 1); assert.equal(hit.structuredContent.verification.freshness.sequence, 4);
    assert.equal(hit.structuredContent.matches[0].statement, 'The Brightline front door keypad code is 5521.');
  } finally { await client.close(); }
});

test('a quote that is not verbatim in its message is invalid, logged, never applied, and cannot be approved', { skip }, (t) => {
  const env = setup(t), out = join(env.work, 'pack-4');
  const source = snapshot(env.source);
  const forced = review(env, out, ['--approve-ids', 'P3']);
  assert.equal(forced.status, 1); assert.match(forced.stderr, /--approve-ids: P3 is invalid and cannot be approved/);
  assert.deepEqual(snapshot(env.source), source, 'nothing written, not even the log'); assert.ok(!existsSync(out));

  const p = review(env, out, ['--approve-ids', 'P1']);
  assert.equal(p.status, 0, p.stderr);
  assert.match(p.stdout, /P3 {2}INVALID, never applied: record quote 1: quote is not verbatim in message text/);
  const records = rows(join(env.source, 'records.jsonl'));
  assert.ok(!records.some((r) => /9999/.test(r.statement)));
  assert.ok(!rows(join(env.source, 'messages.jsonl')).some((m) => m.id === 6), 'the invalid proposal\'s message is not added');
  assert.equal(loadPack(out, { trustedKeys: [pubLine(env.key)], minSequence: 4 }).search('9999').length, 0);
  const invalid = rows(join(env.source, 'review-log.jsonl')).find((e) => e.proposal === 'P3');
  assert.equal(invalid.decision, 'invalid'); assert.match(invalid.error, /not verbatim/); assert.match(invalid.line, /9999/);
});

test('interactive: a rejected proposal is logged and not applied', { skip }, (t) => {
  const env = setup(t), out = join(env.work, 'pack-4');
  const p = review(env, out, [], 'n\ny\n');
  assert.equal(p.status, 0, p.stderr);
  assert.match(p.stdout, /approve P1\? \[y\/N\] P1: rejected\n/); assert.match(p.stdout, /approve P2\? \[y\/N\] P2: approved\n/);
  assert.doesNotMatch(p.stdout, /approve P3/, 'invalid proposals are not offered');
  const door = rows(join(env.source, 'records.jsonl')).find((r) => r.record_id === 'M-brightline-door');
  assert.equal(door.statement, 'The Brightline front door keypad code is 4471.');
  assert.ok(!rows(join(env.source, 'messages.jsonl')).some((m) => m.id === 4), 'the rejected proposal\'s message is not added');
  const pack = loadPack(out, { trustedKeys: [pubLine(env.key)], minSequence: 4 });
  assert.equal(pack.get('M-brightline-door').statement, 'The Brightline front door keypad code is 4471.');
  assert.ok(pack.get('M-brightline-ink'));
  const log = rows(join(env.source, 'review-log.jsonl'));
  assert.deepEqual(log.map((e) => [e.proposal, e.decision]), [['P1', 'rejected'], ['P2', 'approved'], ['P3', 'invalid']]);
  assert.equal(log[0].record.statement, 'The Brightline front door keypad code is 5521.'); assert.equal(log[0].replaced, undefined);
});

test('nothing approved: no pack, source unchanged, decisions still logged; no answer: nothing written', { skip }, (t) => {
  const env = setup(t), out = join(env.work, 'pack-4');
  const source = snapshot(env.source);
  const eof = review(env, out, [], 'n\n');
  assert.equal(eof.status, 1); assert.match(eof.stderr, /no answer for P2; nothing was written/);
  assert.deepEqual(snapshot(env.source), source);

  const p = review(env, out, ['--approve-ids', 'none']);
  assert.equal(p.status, 0, p.stderr); assert.match(p.stdout, /nothing approved: no pack written, source unchanged/);
  assert.ok(!existsSync(out));
  for (const name of ['messages.jsonl', 'records.jsonl']) assert.deepEqual(readFileSync(join(env.source, name)), source[name]);
  assert.deepEqual(rows(join(env.source, 'review-log.jsonl')).map((e) => e.decision), ['rejected', 'rejected', 'invalid']);
});

test('--sequence auto increments from the current signed pack, run after run', { skip }, (t) => {
  const env = setup(t, { currentSequence: 41 });
  const first = join(env.work, 'next'), second = join(env.work, 'after');
  assert.equal(review(env, first, ['--approve-ids', 'P1']).status, 0);
  assert.equal(loadPack(first, { trustedKeys: [pubLine(env.key)], strict: true, minSequence: 42 }).verification.freshness.sequence, 42);
  env.current = first;
  const p = review(env, second, ['--approve-ids', 'P2']);
  assert.equal(p.status, 0, p.stderr);
  assert.equal(loadPack(second, { trustedKeys: [pubLine(env.key)], strict: true, minSequence: 43 }).verification.freshness.sequence, 43);
  assert.ok(loadPack(second, { trustedKeys: [pubLine(env.key)] }).get('M-brightline-ink'));
  // An explicit sequence is used as given, but never at or below the current one.
  env.current = second;
  const low = review(env, join(env.work, 'low'), ['--approve-ids', 'none', '--sequence', '42']);
  assert.equal(low.status, 1); assert.match(low.stderr, /--sequence 42 must be higher than the current pack's 43/);
  const high = review(env, join(env.work, 'high'), ['--approve-ids', 'P2', '--sequence', '50']);
  assert.equal(high.status, 0, high.stderr);
  assert.equal(loadPack(join(env.work, 'high'), { trustedKeys: [pubLine(env.key)], minSequence: 50 }).verification.freshness.sequence, 50);
});

test('refuses before the review: no current pack for auto, a current pack from another key, bad flags', { skip }, (t) => {
  const env = setup(t), other = setup(t), out = join(env.work, 'pack-4');
  const source = snapshot(env.source);
  const base = ['--source', env.source, '--proposals', env.proposals, '--key', env.key, '--expires', '30d', '--out', out, '--approve-ids', 'P1'];
  for (const [args, message] of [
    [base, /--sequence auto needs --current/],
    [[...base, '--current', other.current], /pack is signed by SHA256:\S+, which is not a trusted key/],
    [[...base, '--current', env.current, '--expires', 'soon'], /Usage: /],
    [[...base.map((a) => (a === '30d' ? 'soon' : a)), '--current', env.current], /--expires must be a number of days/],
    [[...base, '--current', env.current, '--sequence', '-1'], /Usage: |--sequence must be auto or a whole number/],
    [[...base.map((a) => (a === 'P1' ? 'P9' : a)), '--current', env.current], /--approve-ids: no proposal P9/]
  ]) {
    const p = run(env, 'review.mjs', args);
    assert.equal(p.status, 1, args.join(' ')); assert.match(p.stderr, message);
  }
  assert.deepEqual(snapshot(env.source), source); assert.ok(!existsSync(out));
});

test('a proposal cannot rewrite an existing message; two approved changes to one record are refused; agent text is shown escaped', { skip }, (t) => {
  const env = setup(t), out = join(env.work, 'pack-4');
  const door = (text, statement, id = 4) => ({ proposer: 'agent\u001b[2J', reason: 'r‮evil', message: { id, date: '2026-10-14T08:30:00Z', speaker: 'Avery', text },
    record: { record_id: 'M-brightline-door', role: 'user', topic: 'Door code', category: 'access', statement, quotes: [{ message_id: id, quote: text }] } });
  env.proposals = join(env.root, 'proposals.jsonl');
  writeFileSync(env.proposals, [
    { ...door('the code is 1234.', 'code 1234', 2) },
    door('The new door code is 5521.', 'code 5521'),
    door('The new door code is 5521.', 'code 5521\nP9  approved'),
    '{not json'
  ].map((x) => (typeof x === 'string' ? x : JSON.stringify(x))).join('\n') + '\n');
  const source = snapshot(env.source);
  const p = review(env, out, ['--approve-ids', 'P2,P3']);
  assert.equal(p.status, 1); assert.match(p.stderr, /P3: another approved proposal also changes M-brightline-door/);
  assert.match(p.stdout, /P1 {2}INVALID, never applied: message 2 already exists with different content/);
  assert.match(p.stdout, /P4 {2}INVALID, never applied: not valid JSON/);
  assert.match(p.stdout, /proposed by agent\\u001b\[2J\n/); assert.match(p.stdout, /reason: {2}r\\u202eevil\n/); assert.match(p.stdout, /new: {5}code 5521\\u000aP9  approved\n/);
  assert.doesNotMatch(p.stdout, /[\u001b‮]/);
  assert.deepEqual(snapshot(env.source), source); assert.ok(!existsSync(out)); assert.deepEqual(leftovers(env.work), []);
});

test('review ships in the npm package next to sign-pack', () => {
  const pkg = JSON.parse(readFileSync('package.json', 'utf8'));
  assert.equal(pkg.bin['verified-memory-review'], 'tools/review.mjs');
  assert.match(readFileSync('tools/review.mjs', 'utf8'), /^#!\/usr\/bin\/env node\n/);
  assert.ok(pkg.files.includes('tools/review.mjs'));
});
