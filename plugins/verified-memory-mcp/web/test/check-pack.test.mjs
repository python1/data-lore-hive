// The browser "Check a signed pack" path must reach exactly the server's verdict. All keys are
// invented: fresh in-memory keys, or the committed fixture key whose private half was deleted.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, cpSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { checkPack, describeCheck, readPackFiles, Unsupported } from '../src/check-pack.mjs';
import { bytesSource } from '../src/zip.mjs';
import { signCommand } from '../src/ui-logic.mjs';
import { loadPack } from '../../dist/pack.js';
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
async function same(dir, keysText, requireSignature) {
  let server, serverError, browser, browserError;
  try { server = loadPack(dir, { trustedKeys: [keysText], requireSignature }).verification; } catch (e) { serverError = e.message; }
  try { browser = await checkPack(filesOf(dir), keysText, requireSignature); } catch (e) { browserError = e.message; }
  assert.equal(browserError, serverError);
  if (!serverError) { assert.equal(browser.records, server.records); assert.deepEqual(browser.signature, server.signature); }
  return { server, serverError };
}

test('browser check matches the server verdict across signed, unsigned and broken packs', async (t) => {
  const outcomes = [];
  const fresh = newKey();
  const variants = {
    unsigned: () => {},
    'fixture signature': (dir) => cpSync(join(fixture, 'SHA256SUMS.sig'), join(dir, 'SHA256SUMS.sig')),
    'unlisted key': (dir) => writeFileSync(join(dir, 'SHA256SUMS.sig'), sshsig(fresh, readFileSync(join(dir, 'SHA256SUMS')))),
    'flipped signature': (dir) => writeFileSync(join(dir, 'SHA256SUMS.sig'), sshsig(fresh, readFileSync(join(dir, 'SHA256SUMS')), { mutateSignature: (s) => { s[5] ^= 1; return s; } })),
    'other namespace': (dir) => writeFileSync(join(dir, 'SHA256SUMS.sig'), sshsig(fresh, readFileSync(join(dir, 'SHA256SUMS')), { namespace: 'hive-release' })),
    'resealed edit': (dir) => { cpSync(join(fixture, 'SHA256SUMS.sig'), join(dir, 'SHA256SUMS.sig')); writeFileSync(join(dir, 'README.md'), 'edited\n'); writeFileSync(join(dir, 'SHA256SUMS'), ['MEMORY.md', 'README.md', 'records.jsonl'].map((n) => `${hash(readFileSync(join(dir, n)))}  ${n}\n`).join('')); },
    'tampered file': (dir) => writeFileSync(join(dir, 'records.jsonl'), 'tampered'),
    'extra file': (dir) => writeFileSync(join(dir, 'notes.txt'), 'x')
  };
  for (const [name, make] of Object.entries(variants)) {
    const dir = copy(t); make(dir);
    for (const [keys, require] of [['', false], [fixtureKeys, false], [fixtureKeys, true], ['', true], ['alice ssh-rsa AAAA', false]]) {
      const { server, serverError } = await same(dir, keys, require);
      outcomes.push(`${name}|${require}|${serverError ?? server.signature?.status ?? 'unsigned'}`);
    }
  }
  // The comparison is only meaningful if every kind of outcome actually occurred.
  for (const expected of ['unsigned|false|unsigned', 'fixture signature|true|verified', 'unlisted key|false|untrusted', 'flipped signature|false|verified-memory: pack signature does not verify'])
    assert.ok(outcomes.includes(expected), `${expected} not in ${outcomes.join(', ')}`);
});

test('a browser without Ed25519 gets an explicit "cannot check", never a pass', async (t) => {
  const dir = copy(t); cpSync(join(fixture, 'SHA256SUMS.sig'), join(dir, 'SHA256SUMS.sig'));
  const subtle = { digest: (...a) => crypto.subtle.digest(...a), importKey: async () => { throw new DOMException('Unrecognized name', 'NotSupportedError'); }, verify: () => { throw new Error('unreachable'); } };
  let error; try { await checkPack(filesOf(dir), fixtureKeys, false, subtle); } catch (e) { error = e; }
  assert.ok(error instanceof Unsupported);
  assert.deepEqual(describeCheck(undefined, error), { text: error.message, kind: 'error' });
  assert.match(error.message, /cannot check Ed25519 signatures/);
  // Unsigned packs need no Ed25519, so they still check.
  assert.equal((await checkPack(filesOf(sample), '', false, subtle)).signature, undefined);
});

test('pack files from a zip (top level or one folder) or loose files; other layouts refused', async () => {
  const files = filesOf(sample);
  files.set('SHA256SUMS.sig', new Uint8Array(readFileSync(join(fixture, 'SHA256SUMS.sig'))));
  const inFolder = Object.fromEntries([...files].map(([n, b]) => [`my-pack/${n}`, b]));
  for (const zip of [nodeZip(Object.fromEntries(files)), nodeZip({ 'my-pack/': '', ...inFolder, '__MACOSX/my-pack/._README.md': 'x' })]) {
    const read = await readPackFiles([{ name: 'my-pack.zip', source: bytesSource(new Uint8Array(zip)) }]);
    assert.deepEqual([...read.keys()].sort(), [...files.keys()].sort());
    assert.equal((await checkPack(read, fixtureKeys, true)).signature.status, 'verified');
  }
  assert.deepEqual([...(await readPackFiles(asInputs(files))).keys()].sort(), [...files.keys()].sort());
  for (const layout of [{ ...inFolder, 'other/README.md': 'x' }, { 'a/b/MEMORY.md': 'x' }, { ...inFolder, 'loose.md': 'x' }])
    await assert.rejects(readPackFiles([{ name: 'bad.zip', source: bytesSource(new Uint8Array(nodeZip(layout))) }]), /one pack/);
  await assert.rejects(readPackFiles([...asInputs(files), ...asInputs(new Map([['README.md', new Uint8Array(1)]]))]), /chosen twice/);
});

test('status text: honest about what a signature does and does not show', () => {
  assert.deepEqual(describeCheck({ records: 8 }), { text: 'Checksums pass for 8 records. This pack is not signed, so nothing here says who made it.', kind: 'ok' });
  assert.match(describeCheck({ records: 1, signature: { status: 'untrusted', fingerprint: 'SHA256:x' } }).text, /^Checksums pass for 1 record\. .*not one you listed, so the signer is unknown\.$/);
  const verified = describeCheck({ records: 8, signature: { status: 'verified', signer: 'fictional-signer', fingerprint: 'SHA256:x' } });
  assert.equal(verified.kind, 'ok'); assert.match(verified.text, /Signed by “fictional-signer” \(SHA256:x\), a key you listed\. This proves that key signed these exact files, not that what they say is true\./);
  assert.deepEqual(describeCheck(undefined, new Error('verified-memory: pack signature does not verify')), { text: 'Not accepted: Pack signature does not verify.', kind: 'error' });
  assert.equal(signCommand('my-memory-pack'), 'ssh-keygen -Y sign -f ~/.ssh/YOUR_KEY -n verified-memory-pack-v1 my-memory-pack/SHA256SUMS');
});
