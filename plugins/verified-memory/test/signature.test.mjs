// Signed packs (v0.2). Every key here is invented: fresh in-memory keys from sshsig.mjs, or
// the committed fixture key, whose private half was deleted after signing the sample.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, cpSync, readFileSync, writeFileSync, rmSync, symlinkSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { parseTrustedKeys, parsePackSignature } from '../dist/verify.js';
import { loadPack, readTrustedKeys } from '../dist/pack.js';
import { newKey, sshsig, armor } from './sshsig.mjs';
const sample = resolve('sample-pack');
const signedFixture = resolve('test/fixtures/signed-sample');
const fixtureTrust = [readFileSync(join(signedFixture, 'trusted_keys'), 'utf8')];
const hash = b => createHash('sha256').update(b).digest('hex');
const V01_KEYS = ['sha256sums', 'manifest_sha256', 'records', 'scope'];
const KEYS = [...V01_KEYS, 'signature', 'freshness'];
const UNSIGNED = { status: 'unsigned', scope: 'This pack has no SHA256SUMS.sig, so nothing establishes who made it.' };
function fixture(t) { const root = mkdtempSync(join(tmpdir(), 'verified-memory-sig-')); t.after(() => rmSync(root, { recursive: true, force: true })); const dir = join(root, 'pack'); cpSync(sample, dir, { recursive: true }); return dir; }
function signWith(dir, key, opts) { writeFileSync(join(dir, 'SHA256SUMS.sig'), sshsig(key, readFileSync(join(dir, 'SHA256SUMS')), opts)); return dir; }
function reseal(dir) { writeFileSync(join(dir, 'SHA256SUMS'), ['MEMORY.md', 'README.md', 'records.jsonl'].map(n => hash(readFileSync(join(dir, n))) + '  ' + n + '\n').join('')); }
const hasSshKeygen = spawnSync('ssh-keygen', ['-Y', 'verify'], { encoding: 'utf8' }).error === undefined;

test('unsigned v0.1 packs still load: v0.1 fields unchanged, reported as unsigned with unknown freshness', () => {
  const plain = loadPack(sample).verification;
  assert.deepEqual(Object.keys(plain), KEYS);
  assert.deepEqual(plain.signature, UNSIGNED); assert.equal(plain.freshness.status, 'unknown'); assert.match(plain.freshness.scope, /no PACK\.json/);
  assert.deepEqual(loadPack(sample, { trustedKeys: fixtureTrust }).verification, plain);
  assert.equal(JSON.stringify(loadPack(sample, { trustedKeys: [newKey().line('someone')] }).verification), JSON.stringify(plain));
});

test('committed fixture: an ssh-keygen signature verifies with the matching ssh-keygen fingerprint', t => {
  const dir = fixture(t); cpSync(join(signedFixture, 'SHA256SUMS.sig'), join(dir, 'SHA256SUMS.sig'));
  const v = loadPack(dir, { trustedKeys: fixtureTrust, requireSignature: true }).verification;
  assert.deepEqual(v.signature, { status: 'verified', signer: 'fictional-signer', fingerprint: 'SHA256:QdQEQAWD+03v/nksLJaA+zSSRPOSa/V/eODKuTXBY94',
    scope: 'A key you listed as trusted signed these exact pack bytes. This does not establish that the content is true, complete or current.' });
  assert.deepEqual(Object.keys(v), KEYS); assert.equal(v.freshness.status, 'unknown');
  assert.equal(v.manifest_sha256, loadPack(sample).verification.manifest_sha256);
});

test('valid signature by an unlisted key loads as untrusted, never as verified', t => {
  const dir = signWith(fixture(t), newKey());
  for (const trustedKeys of [undefined, [], fixtureTrust]) {
    const s = loadPack(dir, { trustedKeys }).verification.signature;
    assert.equal(s.status, 'untrusted'); assert.equal(s.signer, undefined); assert.match(s.fingerprint, /^SHA256:[A-Za-z0-9+/]{43}$/); assert.match(s.scope, /signer is unknown/);
  }
  assert.throws(() => loadPack(dir, { trustedKeys: fixtureTrust, requireSignature: true }), /^Error: verified-memory: pack is signed by SHA256:\S+, which is not a trusted key, and a signature is required$/);
});

test('trust is matched by key bytes; the name comes from the trust list, not the pack', t => {
  const key = newKey(), dir = signWith(fixture(t), key);
  assert.equal(loadPack(dir, { trustedKeys: [key.line('chosen-by-user')] }).verification.signature.signer, 'chosen-by-user');
  const nearMiss = Buffer.from(key.blob); nearMiss[nearMiss.length - 1] ^= 1;
  assert.equal(loadPack(dir, { trustedKeys: [`near-miss ssh-ed25519 ${nearMiss.toString('base64')}`] }).verification.signature.status, 'untrusted');
});

test('requireSignature and strict both refuse unsigned packs and refuse to start without trusted keys', t => {
  for (const mode of [{ strict: true }, { requireSignature: true }])
    assert.throws(() => loadPack(sample, { trustedKeys: fixtureTrust, ...mode }), /^Error: verified-memory: pack is unsigned \(no SHA256SUMS\.sig\) but a signature is required$/);
  // Checked before the pack is read: a missing pack still reports the configuration error.
  for (const trustedKeys of [undefined, [], ['# only a comment\n']]) {
    for (const mode of [{ strict: true }, { requireSignature: true }]) assert.throws(() => loadPack(join(sample, 'missing'), { trustedKeys, ...mode }), /requiring a signature needs at least one trusted key/);
  }
});

test('a re-sealed edit is caught: the signature covers SHA256SUMS, which pins every file', t => {
  const dir = signWith(fixture(t), newKey());
  writeFileSync(join(dir, 'README.md'), readFileSync(join(dir, 'README.md'), 'utf8') + 'edited\n'); reseal(dir);
  assert.throws(() => loadPack(dir), /^Error: verified-memory: pack signature does not verify$/);
});

const BAD = /^Error: verified-memory: invalid SHA256SUMS\.sig; expected an ssh-keygen -Y sign signature$/;
const malformed = {
  'flipped signature byte': [{ mutateSignature: s => { s[0] ^= 1; return s; } }, /^Error: verified-memory: pack signature does not verify$/],
  'other namespace (code release signature)': [{ namespace: 'hive-release' }, /namespace must be verified-memory-pack-v1$/],
  'sha256 hash': [{ hash: 'sha256' }, /hash must be sha512$/],
  'version 2': [{ version: 2 }, BAD],
  'non-empty reserved field': [{ reserved: 'x' }, BAD],
  'trailing bytes': [{ trailing: Buffer.from([0]) }, BAD],
  'short signature': [{ mutateSignature: s => s.subarray(0, 63) }, BAD],
  'rsa key type': [{ keyBlob: Buffer.concat([Buffer.from([0, 0, 0, 7]), Buffer.from('ssh-rsa'), Buffer.from([0, 0, 0, 1, 1])]) }, /signature key must be ssh-ed25519$/],
  'rsa signature type': [{ sigType: 'rsa-sha2-512' }, /^Error: verified-memory: pack signature must be ssh-ed25519$/]
};
for (const [name, [opts, message]] of Object.entries(malformed)) test(`present but malformed signature refuses load, even with no trust configured: ${name}`, t => {
  const dir = signWith(fixture(t), newKey(), opts);
  assert.throws(() => loadPack(dir), message);
});

test('signature file must be armored, bounded and a regular file', t => {
  const dir = fixture(t);
  for (const bytes of ['', 'not a signature', Buffer.from([0xff, 0xfe]), armor(Buffer.from('SSHSIG')), armor(Buffer.alloc(4000, 1))]) {
    writeFileSync(join(dir, 'SHA256SUMS.sig'), bytes); assert.throws(() => loadPack(dir), /SHA256SUMS\.sig|oversized/);
  }
  const good = sshsig(newKey(), readFileSync(join(dir, 'SHA256SUMS')));
  writeFileSync(join(dir, 'SHA256SUMS.sig'), good.replace(/\n/g, '\r\n')); assert.equal(loadPack(dir).verification.signature.status, 'untrusted');
  writeFileSync(join(dir, '..', 'elsewhere.sig'), good); rmSync(join(dir, 'SHA256SUMS.sig'));
  symlinkSync(join(dir, '..', 'elsewhere.sig'), join(dir, 'SHA256SUMS.sig')); assert.throws(() => loadPack(dir), /regular files/);
  rmSync(join(dir, 'SHA256SUMS.sig')); writeFileSync(join(dir, 'SHA256SUMS.asc'), good);
  assert.throws(() => loadPack(dir), /pack must contain exactly four expected files, plus an optional PACK\.json and SHA256SUMS\.sig/);
});

test('trusted key lines: strict allowed_signers subset', () => {
  const key = newKey();
  assert.deepEqual(parseTrustedKeys([`# comment\n\n${key.line('alice')} laptop key\r\n`]).map(k => k.name), ['alice']);
  const short = Buffer.concat([Buffer.from([0, 0, 0, 11]), Buffer.from('ssh-ed25519'), Buffer.from([0, 0, 0, 31]), Buffer.alloc(31)]).toString('base64');
  for (const [lines, message] of [
    [['ssh-ed25519 ' + key.blob.toString('base64')], /invalid trusted key line/],
    [['alice'], /invalid trusted key line/],
    [['alice,bob ' + key.line('x').split(' ').slice(1).join(' ')], /invalid trusted key line/],
    [[`alice namespaces="x" ${key.line('x').split(' ').slice(1).join(' ')}`], /must be ssh-ed25519/],
    [['alice ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQ=='], /must be ssh-ed25519/],
    [['alice ssh-ed25519 not*base64'], /invalid trusted key/],
    [[`alice ssh-ed25519 ${short}`], /invalid trusted key/],
    [[key.line('alice'), key.line('bob')], /duplicate trusted key/],
    [Array.from({ length: 257 }, (_, i) => newKey().line('k' + i)), /too many trusted keys/]
  ]) assert.throws(() => parseTrustedKeys(lines), message);
});

test('trusted keys file must be absolute, regular, small UTF-8, and errors never show the path', t => {
  const dir = fixture(t), file = join(dir, '..', 'trusted_keys');
  writeFileSync(file, fixtureTrust[0]); assert.deepEqual(readTrustedKeys(file), fixtureTrust);
  assert.throws(() => readTrustedKeys('relative/trusted_keys'), /must be absolute/);
  for (const make of [() => {}, () => writeFileSync(file, Buffer.alloc(64 * 1024 + 1, 0x23)), () => writeFileSync(file, Buffer.from([0xff])), () => symlinkSync(join(signedFixture, 'trusted_keys'), file)]) {
    rmSync(file, { force: true }); make();
    assert.throws(() => readTrustedKeys(file), e => !e.message.includes(dir) && /^verified-memory: cannot read trusted keys file/.test(e.message));
  }
});

test('parsePackSignature exposes exactly what was signed (used by the browser caller)', () => {
  const key = newKey(), manifest = readFileSync(join(sample, 'SHA256SUMS'));
  const parsed = parsePackSignature(Buffer.from(sshsig(key, manifest)));
  assert.deepEqual(Buffer.from(parsed.key), key.raw); assert.equal(parsed.signature.length, 64);
});

test('interop with OpenSSH: ssh-keygen signs, we verify; we sign in tests, ssh-keygen verifies', { skip: hasSshKeygen ? false : 'ssh-keygen not installed' }, t => {
  const dir = fixture(t), work = join(dir, '..');
  // ssh-keygen writes the private key into the temporary directory, which t.after removes.
  assert.equal(spawnSync('ssh-keygen', ['-q', '-t', 'ed25519', '-N', '', '-C', 'fictional', '-f', join(work, 'k')]).status, 0);
  assert.equal(spawnSync('ssh-keygen', ['-q', '-Y', 'sign', '-f', join(work, 'k'), '-n', 'verified-memory-pack-v1', join(dir, 'SHA256SUMS')]).status, 0);
  const line = 'fictional ' + readFileSync(join(work, 'k.pub'), 'utf8').split(' ').slice(0, 2).join(' ');
  const v = loadPack(dir, { trustedKeys: [line] }).verification.signature;
  const printed = spawnSync('ssh-keygen', ['-l', '-f', join(work, 'k.pub')], { encoding: 'utf8' }).stdout;
  assert.equal(v.status, 'verified'); assert.ok(printed.includes(v.fingerprint), printed);

  const key = newKey(); signWith(dir, key);
  writeFileSync(join(work, 'allowed'), key.line('fictional') + '\n');
  const check = spawnSync('ssh-keygen', ['-Y', 'verify', '-f', join(work, 'allowed'), '-I', 'fictional', '-n', 'verified-memory-pack-v1', '-s', join(dir, 'SHA256SUMS.sig')], { input: readFileSync(join(dir, 'SHA256SUMS')), encoding: 'utf8' });
  assert.equal(check.status, 0, check.stderr);
});

test('no private key material in the repository plugin tree or the npm package', () => {
  const listed = JSON.parse(spawnSync('npm', ['pack', '--dry-run', '--json', '--ignore-scripts'], { encoding: 'utf8' }).stdout)[0].files.map(f => f.path);
  assert.ok(listed.length > 0 && !listed.some(p => p.startsWith('test/') || /(^|\/)(id_|.*\.key$)/.test(p)), listed.join(', '));
  for (const p of listed) assert.doesNotMatch(readFileSync(p, 'latin1'), /PRIVATE KEY-----/, p);
  assert.ok(!existsSync('test/fixtures/signed-sample/k'));
});
