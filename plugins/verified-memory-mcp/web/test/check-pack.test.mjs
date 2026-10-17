// The browser "Check a signed pack" path must reach exactly the server's verdict. All keys are
// invented: fresh in-memory keys, or the committed fixture key whose private half was deleted.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, cpSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { checkPack, describeCheck, readPackFiles, trustOptions, Unsupported } from '../src/check-pack.mjs';
import { bytesSource } from '../src/zip.mjs';
import { signCommand } from '../src/ui-logic.mjs';
import { loadPack } from '../../dist/pack.js';
import { fingerprint } from '../../dist/verify.js';
import { newKey, sshsig } from '../../../verified-memory/test/sshsig.mjs';
import { nodeZip } from './helpers.mjs';

const sample = resolve('../../verified-memory/sample-pack');
const fixture = resolve('../../verified-memory/test/fixtures/signed-sample');
const fixtureKeys = readFileSync(join(fixture, 'trusted_keys'), 'utf8');
const hash = (b) => createHash('sha256').update(b).digest('hex');
const filesOf = (dir) => new Map(readdirSync(dir).map((n) => [n, new Uint8Array(readFileSync(join(dir, n)))]));
const asInputs = (map) => [...map].map(([name, data]) => ({ name, source: bytesSource(data) }));
function copy(t) { const root = mkdtempSync(join(tmpdir(), 'fictional-check-')); t.after(() => rmSync(root, { recursive: true, force: true })); const dir = join(root, 'pack'); cpSync(sample, dir, { recursive: true }); return dir; }

/** Same verdict from the browser path and from loadPack: both pass with equal results, or both fail with the same message. */
async function same(dir, trust) {
  let server, serverError, browser, browserError;
  try { server = loadPack(dir, trustOptions(trust)).verification; } catch (e) { serverError = e.message; }
  try { browser = await checkPack(filesOf(dir), trust); } catch (e) { browserError = e.message; }
  assert.equal(browserError, serverError);
  if (!serverError) { assert.equal(browser.records, server.records); assert.deepEqual(browser.signature, server.signature); assert.deepEqual(browser.freshness, server.freshness); }
  return { server, serverError };
}

const DAY = 86400000;
const iso = (ms) => new Date(Math.floor(ms / 1000) * 1000).toISOString().replace('.000Z', 'Z');
/** PACK.json + re-seal (+ signature by `key`), as sign-pack makes a pack. */
function dated(dir, created, expires, key, sequence) {
  writeFileSync(join(dir, 'PACK.json'), JSON.stringify({ format: 'verified-memory-pack', version: 2, created_utc: iso(created), expires_utc: iso(expires), sequence }));
  writeFileSync(join(dir, 'SHA256SUMS'), ['MEMORY.md', 'PACK.json', 'README.md', 'records.jsonl'].map((n) => `${hash(readFileSync(join(dir, n)))}  ${n}\n`).join(''));
  if (key) writeFileSync(join(dir, 'SHA256SUMS.sig'), sshsig(key, readFileSync(join(dir, 'SHA256SUMS'))));
}

test('browser check matches the server verdict across signed, unsigned, dated and broken packs', async (t) => {
  const outcomes = [];
  const fresh = newKey(), freshKeys = fresh.line('fictional-publisher'), freshPrint = fingerprint(fresh.raw, hash), otherPrint = fingerprint(newKey().raw, hash);
  const now = Date.now();
  const variants = {
    unsigned: () => {},
    'fixture signature': (dir) => cpSync(join(fixture, 'SHA256SUMS.sig'), join(dir, 'SHA256SUMS.sig')),
    'unlisted key': (dir) => writeFileSync(join(dir, 'SHA256SUMS.sig'), sshsig(fresh, readFileSync(join(dir, 'SHA256SUMS')))),
    'flipped signature': (dir) => writeFileSync(join(dir, 'SHA256SUMS.sig'), sshsig(fresh, readFileSync(join(dir, 'SHA256SUMS')), { mutateSignature: (s) => { s[5] ^= 1; return s; } })),
    'other namespace': (dir) => writeFileSync(join(dir, 'SHA256SUMS.sig'), sshsig(fresh, readFileSync(join(dir, 'SHA256SUMS')), { namespace: 'hive-release' })),
    'resealed edit': (dir) => { cpSync(join(fixture, 'SHA256SUMS.sig'), join(dir, 'SHA256SUMS.sig')); writeFileSync(join(dir, 'README.md'), 'edited\n'); writeFileSync(join(dir, 'SHA256SUMS'), ['MEMORY.md', 'README.md', 'records.jsonl'].map((n) => `${hash(readFileSync(join(dir, n)))}  ${n}\n`).join('')); },
    'tampered file': (dir) => writeFileSync(join(dir, 'records.jsonl'), 'tampered'),
    'extra file': (dir) => writeFileSync(join(dir, 'notes.txt'), 'x'),
    'dated fresh': (dir) => dated(dir, now - DAY, now + 30 * DAY, fresh),
    'dated expired': (dir) => dated(dir, now - 60 * DAY, now - DAY, fresh),
    'dated future': (dir) => dated(dir, now + 2 * DAY, now + 30 * DAY, fresh),
    'dated unsigned': (dir) => dated(dir, now - DAY, now + DAY),
    'dated, expiry extended': (dir) => { dated(dir, now - 60 * DAY, now - DAY, fresh); dated(dir, now - 60 * DAY, now + DAY); },
    'sequence 3': (dir) => dated(dir, now - DAY, now + 30 * DAY, fresh, 3),
    'sequence 7': (dir) => dated(dir, now - DAY, now + 30 * DAY, fresh, 7),
    'bad PACK.json': (dir) => { dated(dir, now - DAY, now + DAY); writeFileSync(join(dir, 'PACK.json'), '{"format":"verified-memory-pack"}'); writeFileSync(join(dir, 'SHA256SUMS'), ['MEMORY.md', 'PACK.json', 'README.md', 'records.jsonl'].map((n) => `${hash(readFileSync(join(dir, n)))}  ${n}\n`).join('')); }
  };
  for (const [name, make] of Object.entries(variants)) {
    const dir = copy(t); make(dir);
    for (const [keys, strict] of [['', false], [fixtureKeys, false], [fixtureKeys, true], [freshKeys, false], [freshKeys, true], ['', true], ['alice ssh-rsa AAAA', false]]) {
      const { server, serverError } = await same(dir, { trustedKeys: keys, strict });
      outcomes.push(`${name}|${keys === freshKeys ? 'fresh-key' : keys === fixtureKeys ? 'fixture-key' : 'other'}|${strict}|${serverError ?? `${server.signature.status}/${server.freshness.status}`}`);
    }
    // v0.4: pins, revocation and a minimum sequence, alone and together.
    for (const [label, trust] of Object.entries({
      'pin-fresh': { trustedFingerprints: freshPrint }, 'pin-other': { trustedKeys: freshKeys, trustedFingerprints: otherPrint },
      'revoke-fresh': { trustedKeys: freshKeys, revokedKeys: freshPrint }, 'pin+revoke-fresh': { trustedFingerprints: freshPrint, revokedKeys: `# lost\n${freshPrint}` },
      'pin-fresh+min5': { trustedFingerprints: freshPrint, minSequence: '5' }, 'keys+min5+strict': { trustedKeys: freshKeys, minSequence: ' 5 ', strict: true },
      'min-bad': { trustedFingerprints: freshPrint, minSequence: 'five' }, 'pin-bad': { trustedFingerprints: 'SHA256:short' }
    })) {
      const { server, serverError } = await same(dir, trust);
      outcomes.push(`${name}|${label}|${serverError ?? `${server.signature.status}/${server.freshness.status}`}`);
    }
  }
  // The comparison is only meaningful if every kind of outcome actually occurred.
  for (const expected of ['unsigned|other|false|unsigned/unknown', 'fixture signature|fixture-key|false|verified/unknown', 'unlisted key|other|false|untrusted/unknown',
    'flipped signature|other|false|verified-memory: pack signature does not verify',
    'fixture signature|fixture-key|true|verified-memory: pack has no PACK.json, so no expiry date, and strict mode requires a fresh pack',
    'dated fresh|fresh-key|true|verified/fresh', 'dated expired|fresh-key|false|verified/stale', 'dated future|fresh-key|false|verified/not_yet_valid',
    `dated expired|fresh-key|true|verified-memory: pack expired at ${iso(now - DAY)} and strict mode refuses stale packs`, 'dated unsigned|other|false|unsigned/fresh',
    'dated, expiry extended|fresh-key|false|verified-memory: pack signature does not verify',
    'bad PACK.json|other|false|verified-memory: PACK.json must have exactly format, version, created_utc and expires_utc, plus an optional sequence',
    'sequence 7|pin-fresh+min5|verified/fresh', 'sequence 7|keys+min5+strict|verified/fresh',
    'sequence 3|pin-fresh+min5|verified-memory: pack sequence 3 is lower than the minimum 5; refusing a possible rollback to an older pack',
    'dated fresh|pin-fresh+min5|verified-memory: pack has no sequence in PACK.json, and a minimum sequence of 5 is required',
    'unsigned|pin-fresh|verified-memory: pack is unsigned (no SHA256SUMS.sig) but a signature is required',
    `sequence 7|pin-other|verified-memory: pack is signed by ${freshPrint}, which is not a pinned signer fingerprint`,
    `sequence 7|revoke-fresh|verified-memory: pack is signed by ${freshPrint}, which is revoked`,
    `sequence 7|pin+revoke-fresh|verified-memory: pack is signed by ${freshPrint}, which is revoked`,
    'sequence 7|min-bad|verified-memory: minimum sequence must be a whole number, 0 or more',
    'unsigned|pin-bad|verified-memory: invalid pinned signer fingerprint; expected SHA256: and 43 base64 characters, as ssh-keygen -l prints'])
    assert.ok(outcomes.includes(expected), `${expected} not in ${outcomes.join(', ')}`);
});

test('a browser without Ed25519 gets an explicit "cannot check", never a pass', async (t) => {
  const dir = copy(t); cpSync(join(fixture, 'SHA256SUMS.sig'), join(dir, 'SHA256SUMS.sig'));
  const subtle = { digest: (...a) => crypto.subtle.digest(...a), importKey: async () => { throw new DOMException('Unrecognized name', 'NotSupportedError'); }, verify: () => { throw new Error('unreachable'); } };
  let error; try { await checkPack(filesOf(dir), { trustedKeys: fixtureKeys }, subtle); } catch (e) { error = e; }
  assert.ok(error instanceof Unsupported);
  assert.deepEqual(describeCheck(undefined, error), { text: error.message, kind: 'error' });
  assert.match(error.message, /cannot check Ed25519 signatures/);
  // Unsigned packs need no Ed25519, so they still check.
  assert.equal((await checkPack(filesOf(sample), {}, subtle)).signature.status, 'unsigned');
});

test('pack files from a zip (top level or one folder) or loose files; other layouts refused', async () => {
  const files = filesOf(sample);
  files.set('SHA256SUMS.sig', new Uint8Array(readFileSync(join(fixture, 'SHA256SUMS.sig'))));
  const inFolder = Object.fromEntries([...files].map(([n, b]) => [`my-pack/${n}`, b]));
  for (const zip of [nodeZip(Object.fromEntries(files)), nodeZip({ 'my-pack/': '', ...inFolder, '__MACOSX/my-pack/._README.md': 'x' })]) {
    const read = await readPackFiles([{ name: 'my-pack.zip', source: bytesSource(new Uint8Array(zip)) }]);
    assert.deepEqual([...read.keys()].sort(), [...files.keys()].sort());
    assert.equal((await checkPack(read, { trustedKeys: fixtureKeys })).signature.status, 'verified');
  }
  assert.deepEqual([...(await readPackFiles(asInputs(files))).keys()].sort(), [...files.keys()].sort());
  for (const layout of [{ ...inFolder, 'other/README.md': 'x' }, { 'a/b/MEMORY.md': 'x' }, { ...inFolder, 'loose.md': 'x' }])
    await assert.rejects(readPackFiles([{ name: 'bad.zip', source: bytesSource(new Uint8Array(nodeZip(layout))) }]), /one pack/);
  await assert.rejects(readPackFiles([...asInputs(files), ...asInputs(new Map([['README.md', new Uint8Array(1)]]))]), /chosen twice/);
});

test('status text: honest about what a signature and a date do and do not show', () => {
  const unknown = { status: 'unknown' };
  assert.deepEqual(describeCheck({ records: 8, signature: { status: 'unsigned' }, freshness: unknown }), { text: 'Checksums pass for 8 records. This pack is not signed, so nothing here says who made it. It has no expiry date.', kind: 'ok' });
  assert.match(describeCheck({ records: 1, signature: { status: 'untrusted', fingerprint: 'SHA256:x' }, freshness: unknown }).text, /^Checksums pass for 1 record\. .*not one you listed, so the signer is unknown\. It has no expiry date\.$/);
  const signer = { status: 'verified', signer: 'fictional-signer', fingerprint: 'SHA256:x' };
  const verified = describeCheck({ records: 8, signature: signer, freshness: { status: 'fresh', created_utc: '2026-10-01T00:00:00Z', expires_utc: '2027-01-01T00:00:00Z', authenticated: true } });
  assert.equal(verified.kind, 'ok'); assert.match(verified.text, /Signed by “fictional-signer” \(SHA256:x\), a key you listed\. This proves that key signed these exact files, not that what they say is true\. Fresh until 2027-01-01T00:00:00Z\.$/);
  const stale = describeCheck({ records: 8, signature: signer, freshness: { status: 'stale', created_utc: '2026-01-01T00:00:00Z', expires_utc: '2026-02-01T00:00:00Z', authenticated: true } });
  assert.equal(stale.kind, ''); assert.match(stale.text, / It expired at 2026-02-01T00:00:00Z, so its records may be out of date\.$/);
  const future = describeCheck({ records: 8, signature: { status: 'unsigned' }, freshness: { status: 'not_yet_valid', created_utc: '2030-01-01T00:00:00Z', expires_utc: '2031-01-01T00:00:00Z', authenticated: false } });
  assert.equal(future.kind, ''); assert.match(future.text, /in the future by this computer's clock \(these dates are not signed by a key you listed\)\.$/);
  assert.deepEqual(describeCheck(undefined, new Error('verified-memory: pack signature does not verify')), { text: 'Not accepted: Pack signature does not verify.', kind: 'error' });
  const pinned = describeCheck({ records: 8, signature: { ...signer, signer: 'pinned', pinned: true }, freshness: { status: 'fresh', created_utc: '2026-10-01T00:00:00Z', expires_utc: '2027-01-01T00:00:00Z', sequence: 4, authenticated: true } });
  assert.deepEqual(pinned, { text: 'Checksums pass for 8 records. Signed by the key you pinned (SHA256:x). This proves that key signed these exact files, not that what they say is true. Fresh until 2027-01-01T00:00:00Z. Sequence 4.', kind: 'ok' });
  assert.match(describeCheck({ records: 8, signature: { ...signer, pinned: true }, freshness: unknown }).text, /Signed by the key you pinned, “fictional-signer” \(SHA256:x\)\./);
  assert.equal(signCommand('my-memory-pack'), 'node tools/sign-pack.mjs --pack my-memory-pack --key ~/.ssh/YOUR_KEY --expires 90d --sequence 1 --out my-memory-pack-signed');
});
