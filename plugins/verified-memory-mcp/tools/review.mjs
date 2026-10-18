#!/usr/bin/env node
// Owner-side review of proposed memory writes. Agents never write to a pack: they append
// proposals (a source message and a record, with proposer and reason) to a JSONL file, and
// only the owner, running this tool, turns approved ones into the next signed pack. The MCP
// server stays read-only and never reads proposals.
// Each proposal is checked as build-pack would check it (every quote verbatim in its message),
// shown, and approved or rejected (interactively, or with --approve-ids). Approved ones are
// applied to a copy of the owner's private source files (messages.jsonl + records.jsonl), which
// build-pack and sign-pack turn into a new pack signed with the next sequence. Only after that
// pack verifies are the source files replaced and every decision appended to review-log.jsonl
// in the source folder. Rejected and invalid proposals are logged, never applied. The private
// key path is passed to sign-pack, which hands it to ssh-keygen alone; only KEY.pub is read here.
// Ships in the npm package as verified-memory-review; from a checkout, run it after
// npm ci && npm run build.
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { InputError, buildRecords, check, isText, parseMessages } from './pack-core.mjs';

const USAGE = 'Usage: verified-memory-review --source DIR --proposals FILE --key ~/.ssh/KEY --expires 90d|2027-01-31T00:00:00Z --out NEW_DIR'
  + ' [--sequence auto|N] [--current SIGNED_PACK_DIR] [--approve-ids P1,P3|none] [--title TEXT] [--description TEXT]';
const LOG = 'review-log.jsonl';

function parseArgs(argv) {
  const known = new Set(['--source', '--proposals', '--key', '--expires', '--out', '--sequence', '--current', '--approve-ids', '--title', '--description']);
  const opts = {};
  for (let i = 0; i < argv.length; i += 2) {
    check(known.has(argv[i]) && argv[i + 1] !== undefined && !argv[i + 1].startsWith('--') && !(argv[i].slice(2) in opts), USAGE);
    opts[argv[i].slice(2)] = argv[i + 1];
  }
  check(opts.source && opts.proposals && opts.key && opts.expires && opts.out, USAGE);
  opts.sequence ??= 'auto';
  check(opts.sequence === 'auto' || /^\d{1,15}$/.test(opts.sequence), '--sequence must be auto or a whole number, 0 or more');
  check(opts.sequence !== 'auto' || opts.current, '--sequence auto needs --current, the signed pack now in use (the new pack gets its sequence + 1); or give --sequence N');
  // Format only, so a typo fails before the review; sign-pack checks the range.
  check(/^[1-9]\d{0,3}d$|^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(opts.expires), '--expires must be a number of days such as 90d, or a UTC time such as 2027-01-31T00:00:00Z');
  return opts;
}

const home = (path) => (path === '~' || path.startsWith('~/') ? join(homedir(), path.slice(1)) : path);
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const iso = () => new Date().toISOString().replace(/\.\d+Z$/, 'Z');
// Proposal text is agent-written: show control and bidi characters as escapes so it cannot
// rewrite the terminal or disguise what is being approved.
const show = (s) => String(s).replace(/[\u0000-\u001f\u007f-\u009f\u200e\u200f\u202a-\u202e\u2066-\u2069]/g, (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`);
const tool = (name) => fileURLToPath(new URL(`./${name}`, import.meta.url));

function readSource(dir, name) {
  let bytes;
  try { bytes = readFileSync(join(dir, name)); } catch { throw new InputError(`--source: cannot read ${name}`); }
  return { bytes, lines: bytes.toString('utf8').split('\n').filter((line) => line.trim()) };
}

/** pack-core says "messages line 1" / "records line 1"; a proposal has one message and one record. */
async function within(fn) {
  try { return await fn(); }
  catch (error) {
    if (!(error instanceof InputError)) throw error;
    throw new InputError(error.message.replace(/^messages line 1/, 'message').replace(/^records line 1/, 'record'));
  }
}

/** One proposal line -> { id, line, valid, error? | proposer, reason, message, record, built, action, newMessage }. */
async function checkProposal(id, line, source) {
  let row;
  try { row = JSON.parse(line); } catch { return { id, line, valid: false, error: 'not valid JSON' }; }
  try {
    check(row !== null && typeof row === 'object' && !Array.isArray(row), 'must be a JSON object');
    for (const key of Object.keys(row)) check(['proposer', 'reason', 'message', 'record'].includes(key), `unknown field "${key}"`);
    check(isText(row.proposer) && isText(row.reason), `proposer and reason are required`);
    check(row.message !== null && typeof row.message === 'object' && !Array.isArray(row.message), `message must be an object {id, date, speaker, text}`);
    check(row.record !== null && typeof row.record === 'object' && !Array.isArray(row.record), 'record must be an object');
    const message = (await within(() => parseMessages(Buffer.from(JSON.stringify(row.message))))).get(row.message.id);
    const existing = source.messages.get(message.id);
    // A proposal may cite an existing message unchanged, never rewrite one.
    check(!existing || ['date', 'speaker', 'text'].every((k) => existing[k] === message[k]), `message ${message.id} already exists with different content; a proposal cannot change a message`);
    const messages = new Map(source.messages).set(message.id, message);
    const [built] = await within(() => buildRecords(Buffer.from(JSON.stringify(row.record)), messages));
    return { id, line, valid: true, proposer: row.proposer, reason: row.reason, message, record: row.record, built,
      action: source.records.has(built.record_id) ? 'replace' : 'add', newMessage: !existing };
  } catch (error) {
    if (!(error instanceof InputError)) throw error;
    return { id, line, valid: false, error: error.message };
  }
}

function describe(p, source) {
  if (!p.valid) return `\n${p.id}  INVALID, never applied: ${show(p.error)}\n`;
  const quotes = (r, messages) => r.evidence.map((c) => `             > "${show(c.quote)}" (message ${c.message_id}, ${c.date_utc}, ${show(messages.get(c.message_id).speaker)})`);
  const messages = new Map(source.messages).set(p.message.id, p.message);
  const old = source.records.get(p.built.record_id);
  return [
    '', `${p.id}  ${p.action} ${p.built.record_id}   proposed by ${show(p.proposer)}`,
    `    reason:  ${show(p.reason)}`,
    ...(old ? [`    now:     ${show(old.statement)}`, ...quotes(old, source.messages)] : []),
    `    new:     ${show(p.built.statement)}`, ...quotes(p.built, messages),
    `    topic ${show(p.built.topic)}; category ${show(p.built.category)}; role ${p.built.role}; speaker ${show(p.built.speaker)}`,
    `    message ${p.message.id} (${p.newMessage ? 'NEW, added to your source' : 'already in your source'}): ${p.message.date} ${show(p.message.speaker)}: "${show(p.message.text)}"`,
    ''
  ].join('\n');
}

async function decide(proposals, source, approveIds) {
  const valid = proposals.filter((p) => p.valid);
  for (const p of proposals.filter((p) => !p.valid)) process.stdout.write(describe(p, source));
  if (approveIds !== undefined) {
    const ids = approveIds === 'none' ? [] : approveIds.split(',').map((s) => s.trim());
    for (const id of ids) {
      const p = proposals.find((x) => x.id === id);
      check(p, `--approve-ids: no proposal ${id} (proposals are P<line number>)`);
      check(p.valid, `--approve-ids: ${id} is invalid and cannot be approved`);
    }
    for (const p of valid) {
      process.stdout.write(describe(p, source));
      p.approved = ids.includes(p.id);
      process.stdout.write(`${p.id}: ${p.approved ? 'approved' : 'rejected'} (--approve-ids)\n`);
    }
    return;
  }
  // One line per answer, read from stdin (a terminal or a pipe); closed before ssh-keygen asks
  // for the passphrase.
  const rl = createInterface({ input: process.stdin });
  const lines = rl[Symbol.asyncIterator]();
  try {
    for (const p of valid) {
      process.stdout.write(describe(p, source) + `approve ${p.id}? [y/N] `);
      const answer = await lines.next();
      check(!answer.done, `no answer for ${p.id}; nothing was written`);
      p.approved = /^\s*y(es)?\s*$/i.test(answer.value);
      process.stdout.write(`${p.id}: ${p.approved ? 'approved' : 'rejected'}\n`);
    }
  } finally { rl.close(); }
}

function logEntries(proposals, source, extra) {
  const reviewed_utc = iso();
  return proposals.map((p) => JSON.stringify(p.valid
    ? { reviewed_utc, ...extra, proposal: p.id, decision: p.approved ? 'approved' : 'rejected', proposer: p.proposer, reason: p.reason,
      action: p.action, record_id: p.built.record_id, message: p.message, record: p.record,
      ...(p.approved && p.action === 'replace' ? { replaced: source.recordRows.get(p.built.record_id) } : {}) }
    : { reviewed_utc, ...extra, proposal: p.id, decision: 'invalid', error: p.error, line: p.line }) + '\n').join('');
}

/** Replace a file by renaming a sibling into place, so a crash never leaves it half written. */
function replaceFile(path, content) {
  const temp = join(dirname(path), `.${basename(path)}.review-${process.pid}`);
  writeFileSync(temp, content, { flag: 'wx' });
  renameSync(temp, path);
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const dir = resolve(home(opts.source)), out = resolve(home(opts.out)), key = resolve(home(opts.key));
  check(!existsSync(out), '--out already exists; choose a new directory (nothing was written)');
  check(existsSync(dirname(out)), '--out parent directory does not exist');
  const pubPath = key.endsWith('.pub') ? key : `${key}.pub`;
  let pub;
  try { pub = readFileSync(pubPath, 'utf8').trim().split(/\s+/); } catch { throw new InputError(`cannot read the public key ${pubPath}; it must sit next to the private key`); }
  check(pub[0] === 'ssh-ed25519' && pub[1], 'the key must be an ssh-ed25519 key');

  // The current pack's sequence counts only if this key signed it.
  const { loadPack } = await import(new URL('../dist/pack.js', import.meta.url));
  let sequence = opts.sequence === 'auto' ? undefined : Number(opts.sequence);
  if (opts.current) {
    const current = loadPack(resolve(home(opts.current)), { trustedKeys: [`signer ssh-ed25519 ${pub[1]}`], requireSignature: true }).verification.freshness;
    check(current.sequence !== undefined, '--current has no sequence in PACK.json; give --sequence N');
    sequence ??= current.sequence + 1;
    check(sequence > current.sequence, `--sequence ${sequence} must be higher than the current pack's ${current.sequence}`);
  }
  check(Number.isSafeInteger(sequence), '--sequence is too large');

  // The owner's source must build as it is before anything is added to it.
  const msgs = readSource(dir, 'messages.jsonl'), recs = readSource(dir, 'records.jsonl');
  const messages = parseMessages(msgs.bytes);
  const records = new Map((await buildRecords(recs.bytes, messages)).map((r) => [r.record_id, r]));
  const recordRows = new Map(recs.lines.map((line) => { const row = JSON.parse(line); return [row.record_id, row]; }));
  const source = { messages, records, recordRows };

  let proposalBytes;
  try { proposalBytes = readFileSync(resolve(home(opts.proposals))); } catch { throw new InputError('--proposals: cannot read file'); }
  const proposals = [];
  for (const [i, line] of proposalBytes.toString('utf8').split('\n').entries()) {
    if (line.trim()) proposals.push(await checkProposal(`P${i + 1}`, line.replace(/\r$/, ''), source));
  }
  check(proposals.length > 0, '--proposals: no proposals');

  await decide(proposals, source, opts['approve-ids']);
  const approved = proposals.filter((p) => p.approved);
  const logPath = join(dir, LOG), proposals_sha256 = sha256(proposalBytes);
  const summary = proposals.map((p) => `${p.id} ${!p.valid ? 'invalid' : p.approved ? 'approved' : 'rejected'}`).join(', ');
  if (!approved.length) {
    appendFileSync(logPath, logEntries(proposals, source, { proposals_sha256 }));
    process.stdout.write(`\n${summary}\nnothing approved: no pack written, source unchanged; decisions appended to ${logPath}\n`);
    return;
  }

  // Apply: a replaced record keeps its place, new records and messages go at the end.
  const msgLines = [...msgs.lines], recLines = [...recs.lines], addedMessages = new Map(), touched = new Set();
  for (const p of approved) {
    check(!touched.has(p.built.record_id), `${p.id}: another approved proposal also changes ${p.built.record_id}; approve only one (nothing was written)`);
    touched.add(p.built.record_id);
    if (p.newMessage) {
      const seen = addedMessages.get(p.message.id);
      check(!seen || seen === JSON.stringify(p.message), `${p.id}: another approved proposal adds a different message ${p.message.id} (nothing was written)`);
      if (!seen) { addedMessages.set(p.message.id, JSON.stringify(p.message)); msgLines.push(JSON.stringify(p.message)); }
    }
    const at = recLines.findIndex((line) => JSON.parse(line).record_id === p.built.record_id);
    if (at === -1) recLines.push(JSON.stringify(p.record)); else recLines[at] = JSON.stringify(p.record);
  }
  const newMessages = msgLines.join('\n') + '\n', newRecords = recLines.join('\n') + '\n';
  await buildRecords(Buffer.from(newRecords), parseMessages(Buffer.from(newMessages)));

  const staging = join(dirname(out), `.${basename(out)}.review-${process.pid}`);
  mkdirSync(staging);
  try {
    writeFileSync(join(staging, 'messages.jsonl'), newMessages, { flag: 'wx' });
    writeFileSync(join(staging, 'records.jsonl'), newRecords, { flag: 'wx' });
    const extra = [...(opts.title ? ['--title', opts.title] : []), ...(opts.description ? ['--description', opts.description] : [])];
    const built = spawnSync(process.execPath, [tool('build-pack.mjs'), '--messages', join(staging, 'messages.jsonl'), '--records', join(staging, 'records.jsonl'), '--out', join(staging, 'pack'), ...extra],
      { stdio: ['ignore', 'ignore', 'inherit'] });
    check(built.status === 0, 'build-pack failed (nothing was written)');
    process.stdout.write('\n');
    // Inherit the terminal so ssh-keygen can ask for the passphrase itself.
    const signed = spawnSync(process.execPath, [tool('sign-pack.mjs'), '--pack', join(staging, 'pack'), '--key', key, '--expires', opts.expires, '--sequence', String(sequence), '--out', out],
      { stdio: 'inherit' });
    check(signed.status === 0, 'sign-pack failed (nothing was written)');
  } finally {
    rmSync(staging, { recursive: true, force: true });
  }
  // sign-pack has already verified it in strict mode; this confirms the hosts' rollback gate.
  check(loadPack(out, { trustedKeys: [`signer ssh-ed25519 ${pub[1]}`], strict: true, minSequence: sequence }).verification.freshness.sequence === sequence, 'the new pack did not verify');

  replaceFile(join(dir, 'messages.jsonl'), newMessages);
  replaceFile(join(dir, 'records.jsonl'), newRecords);
  appendFileSync(logPath, logEntries(proposals, source, { proposals_sha256, sequence, pack: out }));
  process.stdout.write(`\n${summary}\nupdated ${join(dir, 'messages.jsonl')} and records.jsonl; decisions appended to ${logPath}\n`
    + `new pack: ${out} (sequence ${sequence})\nonce it is installed, raise the hosts' minimum: --min-sequence ${sequence}\n`);
}

main().catch((error) => {
  const message = error instanceof InputError ? error.message
    : error instanceof Error && error.message.startsWith('verified-memory:') ? `verifier rejected the pack: ${error.message}`
    : error?.code === 'ERR_MODULE_NOT_FOUND' ? 'dist/pack.js missing; run npm run build first'
    : `failed: ${error instanceof Error ? error.message : String(error)}`;
  process.stderr.write(`verified-memory-review: ${message}\n`);
  process.exitCode = 1;
});
