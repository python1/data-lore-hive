// Pinned signers, revocation, rollback (sequence) and stop-on-change (v0.4), through loadPack
// and the OpenClaw registration. Every pack is the fictional sample; every key is a fresh
// in-memory key from sshsig.mjs.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, cpSync, readFileSync, writeFileSync, rmSync, readdirSync, statSync, utimesSync, renameSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { fingerprint, parseFingerprints, parseTrustPolicy } from '../dist/verify.js';
import { loadPack, readRevokedKeys } from '../dist/pack.js';
import plugin from '../dist/index.js';
import { newKey, sshsig } from './sshsig.mjs';
const sample = resolve('sample-pack');
const hash = b => createHash('sha256').update(b).digest('hex');
const DAY = 86400000;
const iso = ms => new Date(Math.floor(ms / 1000) * 1000).toISOString().replace('.000Z', 'Z');
const now = Date.now();
const print = key => fingerprint(key.raw, hash);
function fixture(t) { const root = mkdtempSync(join(tmpdir(), 'verified-memory-trust-')); t.after(() => rmSync(root, { recursive: true, force: true })); const dir = join(root, 'pack'); cpSync(sample, dir, { recursive: true }); return dir; }
function reseal(dir) { writeFileSync(join(dir, 'SHA256SUMS'), readdirSync(dir).filter(n => !n.startsWith('SHA256SUMS')).sort().map(n => hash(readFileSync(join(dir, n))) + '  ' + n + '\n').join('')); }
/** What sign-pack --sequence makes: PACK.json with a sequence, re-sealed, signed by `key`. */
function signed(dir, key, { sequence, created = now - DAY, expires = now + 30 * DAY } = {}) {
  writeFileSync(join(dir, 'PACK.json'), JSON.stringify({ format: 'verified-memory-pack', version: 2, created_utc: iso(created), expires_utc: iso(expires), ...(sequence === undefined ? {} : { sequence }) }, null, 2) + '\n');
  reseal(dir);
  if (key) writeFileSync(join(dir, 'SHA256SUMS.sig'), sshsig(key, readFileSync(join(dir, 'SHA256SUMS'))));
  return dir;
}

test('fingerprints match ssh-keygen -l format; malformed ones refuse the configuration', () => {
  const key = newKey(), fp = print(key);
  assert.match(fp, /^SHA256:[A-Za-z0-9+/]{43}$/);
  assert.deepEqual(parseFingerprints([`# revoked 2026-10\n${fp} old laptop\n\n${fp}`], 'revoked key fingerprint'), [fp], 'comments and duplicates are harmless');
  for (const bad of ['SHA256:short', fp + '=', fp.replace('SHA256:', 'MD5:'), fp.slice(0, -1) + 'B', 'alice ssh-ed25519 AAAA'])
    assert.throws(() => parseFingerprints([bad], 'pinned signer fingerprint'), /^Error: verified-memory: invalid pinned signer fingerprint; expected SHA256: and 43 base64 characters, as ssh-keygen -l prints$/, bad);
  assert.throws(() => loadPack(sample, { trustedFingerprints: ['nope'] }), /invalid pinned signer fingerprint/);
  assert.throws(() => loadPack(sample, { revokedKeys: ['nope'] }), /invalid revoked key fingerprint/);
  for (const minSequence of [-1, 1.5, NaN, 2 ** 53]) assert.throws(() => loadPack(sample, { trustedFingerprints: [fp], minSequence }), /minimum sequence must be a whole number/);
});

test('policy: a pin or a minimum sequence implies a signature requirement; revocation alone does not', () => {
  const fp = print(newKey());
  assert.equal(parseTrustPolicy({ trustedFingerprints: [fp] }).requireSignature, true);
  assert.equal(parseTrustPolicy({ trustedFingerprints: [fp], minSequence: 0 }).requireSignature, true);
  assert.equal(parseTrustPolicy({ revokedKeys: [fp] }).requireSignature, false);
  assert.throws(() => parseTrustPolicy({ minSequence: 1 }), /^Error: verified-memory: requiring a signature needs at least one trusted key or pinned fingerprint$/);
  assert.equal(parseTrustPolicy({}).requireSignature, false, 'no new options: 0.3.0 behaviour');
});

test('pin: only the pinned signer is accepted, whatever trustedKeys says (the round-4 break)', t => {
  const publisher = newKey(), attacker = newKey();
  const good = signed(fixture(t), publisher, { sequence: 5 });
  // The attacker rewrote the trusted keys to their own key and re-signed a poisoned copy.
  const poisoned = fixture(t);
  writeFileSync(join(poisoned, 'records.jsonl'), readFileSync(join(poisoned, 'records.jsonl'), 'utf8').replace('pottery', 'poison'));
  signed(poisoned, attacker, { sequence: 6 });
  const attackerTrust = [attacker.line('publisher')];
  assert.equal(loadPack(poisoned, { trustedKeys: attackerTrust, strict: true }).verification.signature.status, 'verified', 'without a pin the swapped key is accepted: the break being fixed');
  assert.throws(() => loadPack(poisoned, { trustedKeys: attackerTrust, trustedFingerprints: [print(publisher)], strict: true }),
    new RegExp(`^Error: verified-memory: pack is signed by ${print(attacker).replace(/[+/]/g, '\\$&')}, which is not a pinned signer fingerprint$`));
  // The genuine pack still loads with the pin even though the swapped file no longer lists its key.
  const v = loadPack(good, { trustedKeys: attackerTrust, trustedFingerprints: [print(publisher)], strict: true }).verification;
  assert.deepEqual({ ...v.signature, scope: undefined }, { status: 'verified', signer: 'pinned', fingerprint: print(publisher), pinned: true, scope: undefined });
  assert.match(v.signature.scope, /fingerprint you pinned/);
  assert.equal(loadPack(good, { trustedKeys: [publisher.line('alice')], trustedFingerprints: [print(publisher)] }).verification.signature.signer, 'alice', 'a listed key names the pinned signer');
  assert.throws(() => loadPack(sample, { trustedFingerprints: [print(publisher)] }), /pack is unsigned \(no SHA256SUMS\.sig\) but a signature is required/);
});

test('revoked: always refused, naming the fingerprint, even trusted, pinned, or with no signature requirement', t => {
  const key = newKey(), fp = print(key), dir = signed(fixture(t), key, { sequence: 1 });
  const message = new RegExp(`^Error: verified-memory: pack is signed by ${fp.replace(/[+/]/g, '\\$&')}, which is revoked$`);
  for (const options of [{}, { trustedKeys: [key.line('publisher')] }, { trustedKeys: [key.line('publisher')], strict: true }, { trustedFingerprints: [fp] }, { trustedFingerprints: [fp], trustedKeys: [key.line('publisher')], minSequence: 1, strict: true }])
    assert.throws(() => loadPack(dir, { ...options, revokedKeys: [`# lost laptop\n${fp}`] }), message, JSON.stringify(Object.keys(options)));
  assert.equal(loadPack(dir, { trustedKeys: [key.line('publisher')], revokedKeys: [print(newKey())] }).verification.signature.status, 'verified', 'revoking another key changes nothing');
  assert.equal(loadPack(sample, { revokedKeys: [fp] }).verification.signature.status, 'unsigned', 'revocation alone does not require a signature');
});

test('revoked keys file: absolute, regular, small UTF-8; errors never show the path', t => {
  const dir = fixture(t), file = join(dir, '..', 'revoked'), fp = print(newKey());
  writeFileSync(file, `# revoked\n${fp} lost laptop\n`);
  assert.deepEqual(parseFingerprints(readRevokedKeys(file), 'revoked key fingerprint'), [fp]);
  assert.throws(() => readRevokedKeys('revoked'), /^Error: verified-memory: revoked keys path must be absolute$/);
  for (const path of [join(dir, '..', 'missing'), dir]) {
    let message = ''; try { readRevokedKeys(path); } catch (e) { message = e.message; }
    assert.equal(message, 'verified-memory: cannot read revoked keys file; it must be a regular UTF-8 file of at most 64 KiB');
  }
});

test('sequence: older, missing, unsigned or forged sequences are refused under a minimum', t => {
  const key = newKey(), trust = { trustedFingerprints: [print(key)] };
  const at = (sequence) => signed(fixture(t), key, { sequence });
  assert.equal(loadPack(at(5), { ...trust, minSequence: 5 }).verification.freshness.sequence, 5, 'equal is accepted');
  assert.equal(loadPack(at(9), { ...trust, minSequence: 5 }).verification.freshness.sequence, 9);
  assert.throws(() => loadPack(at(3), { ...trust, minSequence: 5 }), /^Error: verified-memory: pack sequence 3 is lower than the minimum 5; refusing a possible rollback to an older pack$/);
  assert.throws(() => loadPack(at(undefined), { ...trust, minSequence: 0 }), /^Error: verified-memory: pack has no sequence in PACK\.json, and a minimum sequence of 0 is required$/);
  const undated = fixture(t); writeFileSync(join(undated, 'SHA256SUMS.sig'), sshsig(key, readFileSync(join(undated, 'SHA256SUMS'))));
  assert.throws(() => loadPack(undated, { ...trust, minSequence: 0 }), /pack has no sequence in PACK\.json/);
  // Raising the sequence of an old pack breaks its signature.
  const forged = at(3); writeFileSync(join(forged, 'PACK.json'), readFileSync(join(forged, 'PACK.json'), 'utf8').replace('"sequence": 3', '"sequence": 7')); reseal(forged);
  assert.throws(() => loadPack(forged, { ...trust, minSequence: 5 }), /^Error: verified-memory: pack signature does not verify$/);
  assert.throws(() => loadPack(signed(fixture(t), null, { sequence: 9 }), { trustedKeys: [key.line('k')], minSequence: 5 }), /unsigned .* but a signature is required/);
  // Without a minimum, the sequence is reported and nothing is enforced.
  assert.equal(loadPack(at(3)).verification.freshness.sequence, 3);
  assert.equal('sequence' in loadPack(at(undefined)).verification.freshness, false, 'packs without a sequence report exactly what 0.3.0 did');
});

test('malformed sequence refuses load even with no minimum', t => {
  for (const sequence of [-1, 1.5, '3', null, 2 ** 53]) {
    const dir = fixture(t);
    writeFileSync(join(dir, 'PACK.json'), JSON.stringify({ format: 'verified-memory-pack', version: 2, created_utc: iso(now - DAY), expires_utc: iso(now + DAY), sequence }));
    reseal(dir);
    assert.throws(() => loadPack(dir), /^Error: verified-memory: PACK\.json sequence must be a whole number, 0 or more$/, String(sequence));
  }
  const dir = fixture(t);
  writeFileSync(join(dir, 'PACK.json'), JSON.stringify({ format: 'verified-memory-pack', version: 2, created_utc: iso(now - DAY), expires_utc: iso(now + DAY), sequence: 1, extra: 1 }));
  reseal(dir);
  assert.throws(() => loadPack(dir), /^Error: verified-memory: PACK\.json must have exactly format, version, created_utc and expires_utc, plus an optional sequence$/);
});

test('precedence: revoked > pinned > trusted keys, then sequence, then expiry; one specific error each', t => {
  const publisher = newKey(), other = newKey();
  const options = { trustedKeys: [publisher.line('publisher'), other.line('other')], trustedFingerprints: [print(publisher)], minSequence: 5, strict: true };
  const old = { sequence: 1, created: now - 60 * DAY, expires: now - DAY };
  const cases = [
    [signed(fixture(t), other, old), { ...options, revokedKeys: [print(other)] }, 'which is revoked'],
    [signed(fixture(t), other, old), options, 'which is not a pinned signer fingerprint'],
    [signed(fixture(t), publisher, old), options, 'pack sequence 1 is lower than the minimum 5'],
    [signed(fixture(t), publisher, { ...old, sequence: 5 }), options, 'strict mode refuses stale packs'],
    [signed(fixture(t), publisher, { ...old, sequence: 5 }), { ...options, strict: false }, null]
  ];
  for (const [dir, opts, expected] of cases) {
    if (expected === null) { assert.equal(loadPack(dir, opts).verification.freshness.status, 'stale'); continue; }
    let message = ''; try { loadPack(dir, opts); } catch (e) { message = e.message; }
    assert.ok(message.includes(expected), `${expected}: got ${message}`);
    assert.equal(message.split('verified-memory:').length, 2, 'exactly one error');
  }
});

test('stop on change: any edit, addition, removal or replacement of pack files stops serving', t => {
  const key = newKey(), base = signed(fixture(t), key, { sequence: 1 });
  const edits = {
    'append to records.jsonl': dir => writeFileSync(join(dir, 'records.jsonl'), readFileSync(join(dir, 'records.jsonl'), 'utf8') + ' '),
    'same-size edit with mtime put back': dir => {
      const file = join(dir, 'MEMORY.md'), { atime, mtime } = statSync(file), bytes = readFileSync(file); bytes[0] ^= 1;
      writeFileSync(file, bytes); utimesSync(file, atime, mtime);
    },
    'file replaced by rename, same bytes': dir => { writeFileSync(join(dir, '..', 'swap'), readFileSync(join(dir, 'README.md'))); renameSync(join(dir, '..', 'swap'), join(dir, 'README.md')); },
    'file added': dir => writeFileSync(join(dir, 'notes.txt'), 'x'),
    'signature removed': dir => rmSync(join(dir, 'SHA256SUMS.sig')),
    'whole folder swapped': dir => { const copy = dir + '-copy'; cpSync(dir, copy, { recursive: true }); renameSync(dir, dir + '-old'); renameSync(copy, dir); }
  };
  for (const [name, edit] of Object.entries(edits)) {
    const dir = join(fixture(t), '..', 'p'); cpSync(base, dir, { recursive: true });
    const pack = loadPack(dir, { trustedFingerprints: [print(key)] });
    assert.equal(pack.search('pottery').length, 1);
    edit(dir);
    for (const read of [() => pack.search('pottery'), () => pack.get('M-sample-2'), () => pack.verification])
      assert.throws(read, /^Error: verified-memory: pack files changed on disk since startup, so the verified snapshot no longer matches them; restart to verify the pack again$/, name);
  }
});

test('plugin: pin, revocation and minimum sequence config; refusals register zero tools; edits stop the tools', async t => {
  const key = newKey(), fp = print(key), dir = signed(fixture(t), key, { sequence: 4 });
  const tools = [];
  plugin.register({ pluginConfig: { packPath: dir, trustedFingerprints: [fp], minSequence: 4, strict: true }, registerTool: x => tools.push(x) });
  const v = (await tools[0].execute('1', { query: 'pottery' })).details.verification;
  assert.equal(v.signature.pinned, true); assert.equal(v.freshness.sequence, 4);
  const refused = [];
  for (const [pluginConfig, message] of [
    [{ packPath: dir, trustedFingerprints: [print(newKey())] }, /not a pinned signer fingerprint/],
    [{ packPath: dir, trustedFingerprints: [fp], revokedKeys: [fp] }, /which is revoked/],
    [{ packPath: dir, trustedFingerprints: [fp], minSequence: 5 }, /lower than the minimum 5/],
    [{ packPath: dir, trustedFingerprints: 'SHA256:x' }, /invalid configuration/],
    [{ packPath: dir, revokedKeys: [1] }, /invalid configuration/],
    [{ packPath: dir, trustedFingerprints: [fp], minSequence: '4' }, /invalid configuration/],
    [{ packPath: dir, trustedFingerprints: [fp], minSequence: -1 }, /minimum sequence must be a whole number/]
  ]) assert.throws(() => plugin.register({ pluginConfig, registerTool: x => refused.push(x) }), message, JSON.stringify(pluginConfig));
  assert.equal(refused.length, 0);
  writeFileSync(join(dir, 'records.jsonl'), 'poisoned');
  await assert.rejects(tools[0].execute('2', { query: 'pottery' }), /pack files changed on disk since startup/);
  await assert.rejects(tools[1].execute('3', { id: 'M-sample-2' }), /pack files changed on disk since startup/);
});
