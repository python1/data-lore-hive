// Freshness and strict mode (v0.3). Every pack is the fictional sample; every key is a fresh
// in-memory key from sshsig.mjs. Times are relative to the real clock or an injected one.
import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, cpSync, readFileSync, writeFileSync, rmSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { verifyPackEntries, freshnessWarning, CLOCK_SKEW_MS } from '../dist/verify.js';
import { loadPack } from '../dist/pack.js';
import plugin from '../dist/index.js';
import { newKey, sshsig } from './sshsig.mjs';
const sample = resolve('sample-pack');
const hash = b => createHash('sha256').update(b).digest('hex');
const DAY = 86400000;
const iso = ms => new Date(Math.floor(ms / 1000) * 1000).toISOString().replace('.000Z', 'Z');
function fixture(t) { const root = mkdtempSync(join(tmpdir(), 'verified-memory-fresh-')); t.after(() => rmSync(root, { recursive: true, force: true })); const dir = join(root, 'pack'); cpSync(sample, dir, { recursive: true }); return dir; }
function reseal(dir) { writeFileSync(join(dir, 'SHA256SUMS'), readdirSync(dir).filter(n => !n.startsWith('SHA256SUMS')).sort().map(n => hash(readFileSync(join(dir, n))) + '  ' + n + '\n').join('')); }
const packJson = (created, expires, extra = {}) => JSON.stringify({ format: 'verified-memory-pack', version: 2, created_utc: iso(created), expires_utc: iso(expires), ...extra }, null, 2) + '\n';
/** Adds PACK.json, re-seals, and signs with `key` (if given): what sign-pack produces. */
function dated(dir, created, expires, key) {
  writeFileSync(join(dir, 'PACK.json'), packJson(created, expires)); reseal(dir);
  if (key) writeFileSync(join(dir, 'SHA256SUMS.sig'), sshsig(key, readFileSync(join(dir, 'SHA256SUMS'))));
  return dir;
}
const now = Date.now();

test('v0.1 pack: loads unsigned and undated outside strict; strict refuses it', t => {
  const v = loadPack(sample).verification;
  assert.equal(v.signature.status, 'unsigned'); assert.deepEqual(Object.keys(v.freshness), ['status', 'scope']); assert.equal(v.freshness.status, 'unknown');
  assert.equal(freshnessWarning(v.freshness), undefined, 'undated v0.1 packs load quietly');
  assert.throws(() => loadPack(sample, { trustedKeys: [newKey().line('k')], strict: true }), /unsigned/);
});

test('signed and fresh by a trusted key: strict loads it, dates authenticated', t => {
  const key = newKey(), dir = dated(fixture(t), now - DAY, now + 30 * DAY, key);
  const v = loadPack(dir, { trustedKeys: [key.line('publisher')], strict: true }).verification;
  assert.equal(v.signature.status, 'verified'); assert.equal(v.signature.signer, 'publisher');
  assert.deepEqual({ ...v.freshness, scope: undefined }, { status: 'fresh', created_utc: iso(now - DAY), expires_utc: iso(now + 30 * DAY), authenticated: true, scope: undefined });
  assert.match(v.freshness.scope, /not that it is complete or true\. These dates are signed by a key you listed\.$/);
});

test('expired pack: reported as stale outside strict (requireSignature included), refused in strict', t => {
  const key = newKey(), dir = dated(fixture(t), now - 60 * DAY, now - DAY, key);
  const v = loadPack(dir, { trustedKeys: [key.line('publisher')] }).verification;
  assert.equal(v.freshness.status, 'stale'); assert.equal(v.freshness.authenticated, true);
  assert.match(v.freshness.scope, /^This pack expired at \S+Z; its records may be out of date\. It is served only because strict mode is off\./);
  assert.match(freshnessWarning(v.freshness), /^warning: pack expired at \S+Z \(stale\); serving it because strict mode is off$/);
  assert.equal(loadPack(dir, { trustedKeys: [key.line('publisher')], requireSignature: true }).verification.freshness.status, 'stale', 'requireSignature reports freshness but does not enforce it');
  assert.throws(() => loadPack(dir, { trustedKeys: [key.line('publisher')], strict: true }), new RegExp(`^Error: verified-memory: pack expired at ${iso(now - DAY)} and strict mode refuses stale packs$`));
});

test('expiry is exclusive and checked against the clock on every read, not only at load', t => {
  const key = newKey(), expires = now + DAY, dir = dated(fixture(t), now - DAY, expires, key);
  let clock = now;
  const options = { trustedKeys: [key.line('publisher')], now: () => clock };
  const loose = loadPack(dir, options), strict = loadPack(dir, { ...options, strict: true }), required = loadPack(dir, { ...options, requireSignature: true });
  assert.equal(loose.verification.freshness.status, 'fresh'); assert.equal(strict.verification.freshness.status, 'fresh');
  clock = Date.parse(iso(expires)) - 1; assert.equal(strict.verification.freshness.status, 'fresh');
  clock = Date.parse(iso(expires));
  assert.equal(loose.verification.freshness.status, 'stale');
  assert.equal(required.verification.freshness.status, 'stale', 'requireSignature keeps serving and reports stale');
  assert.throws(() => strict.verification, /strict mode refuses stale packs/, 'a strict host stops serving once the pack expires');
  assert.equal(strict.get('M-sample-2').record_id, 'M-sample-2', 'reads themselves are unchanged; hosts always attach verification');
});

test('pack dated in the future beyond clock skew: not_yet_valid, refused in strict', t => {
  const key = newKey(), trust = [key.line('publisher')];
  const within = dated(fixture(t), now + CLOCK_SKEW_MS - 60000, now + DAY, key);
  assert.equal(loadPack(within, { trustedKeys: trust, strict: true }).verification.freshness.status, 'fresh');
  const future = dated(fixture(t), now + 2 * DAY, now + 30 * DAY, key);
  const v = loadPack(future, { trustedKeys: trust }).verification;
  assert.equal(v.freshness.status, 'not_yet_valid'); assert.match(freshnessWarning(v.freshness), /dated in the future/);
  assert.throws(() => loadPack(future, { trustedKeys: trust, strict: true }), /pack is dated in the future \(created_utc \S+\) and strict mode refuses it/);
});

test('v0.2 signed pack without PACK.json: requireSignature loads it as in 0.2.0 (freshness unknown); strict refuses', t => {
  const key = newKey(), dir = fixture(t);
  writeFileSync(join(dir, 'SHA256SUMS.sig'), sshsig(key, readFileSync(join(dir, 'SHA256SUMS'))));
  for (const requireSignature of [false, true]) {
    const v = loadPack(dir, { trustedKeys: [key.line('publisher')], requireSignature }).verification;
    assert.equal(v.signature.status, 'verified'); assert.equal(v.freshness.status, 'unknown');
  }
  assert.throws(() => loadPack(dir, { trustedKeys: [key.line('publisher')], strict: true }), /^Error: verified-memory: pack has no PACK\.json, so no expiry date, and strict mode requires a fresh pack$/);
});

test('dates are only authenticated by a trusted signature', t => {
  const unsigned = dated(fixture(t), now - DAY, now + DAY);
  const u = loadPack(unsigned).verification;
  assert.equal(u.signature.status, 'unsigned'); assert.equal(u.freshness.status, 'fresh'); assert.equal(u.freshness.authenticated, false);
  assert.match(u.freshness.scope, /anyone could have written them\.$/);
  const untrusted = dated(fixture(t), now - DAY, now + DAY, newKey());
  const v = loadPack(untrusted, { trustedKeys: [newKey().line('someone-else')] }).verification;
  assert.equal(v.signature.status, 'untrusted'); assert.equal(v.freshness.authenticated, false);
  assert.throws(() => loadPack(untrusted, { trustedKeys: [newKey().line('someone-else')], strict: true }), /not a trusted key/);
});

test('extending an expiry is caught: unsealed edit fails the checksum, re-sealed edit fails the signature', t => {
  const key = newKey(), dir = dated(fixture(t), now - 60 * DAY, now - DAY, key), trust = [key.line('publisher')];
  writeFileSync(join(dir, 'PACK.json'), packJson(now - 60 * DAY, now + 365 * DAY));
  assert.throws(() => loadPack(dir, { trustedKeys: trust }), /^Error: verified-memory: checksum mismatch: PACK\.json$/);
  reseal(dir);
  assert.throws(() => loadPack(dir, { trustedKeys: trust }), /^Error: verified-memory: pack signature does not verify$/);
});

test('removing PACK.json from a signed pack is caught', t => {
  const key = newKey(), dir = dated(fixture(t), now - DAY, now + DAY, key);
  rmSync(join(dir, 'PACK.json'));
  assert.throws(() => loadPack(dir), /checksum entry for a file not in the pack: PACK\.json/);
  reseal(dir);
  assert.throws(() => loadPack(dir), /pack signature does not verify/);
});

test('PACK.json must be pinned in SHA256SUMS', t => {
  const dir = fixture(t); writeFileSync(join(dir, 'PACK.json'), packJson(now - DAY, now + DAY));
  assert.throws(() => loadPack(dir), /^Error: verified-memory: missing checksum entry$/);
});

const malformedPackJson = {
  'not JSON': ['{', /PACK\.json: not JSON/],
  'array': ['[]', /must have exactly format, version/],
  'extra key': [packJson(now - DAY, now + DAY, { signer: 'me' }), /must have exactly format, version/],
  'missing key': [JSON.stringify({ format: 'verified-memory-pack', version: 2, created_utc: iso(now) }), /must have exactly format, version/],
  'wrong format': [packJson(now - DAY, now + DAY, { format: 'other' }), /format verified-memory-pack, version 2/],
  'wrong version': [packJson(now - DAY, now + DAY, { version: 3 }), /format verified-memory-pack, version 2/],
  'string version': [packJson(now - DAY, now + DAY, { version: '2' }), /format verified-memory-pack, version 2/],
  'local time': [packJson(now - DAY, now + DAY, { expires_utc: '2027-01-01T00:00:00+01:00' }), /dates must be UTC ISO 8601/],
  'date only': [packJson(now - DAY, now + DAY, { expires_utc: '2027-01-01' }), /dates must be UTC ISO 8601/],
  'expires before created': [packJson(now + DAY, now - DAY), /created_utc before expires_utc/],
  'expires equals created': [packJson(now, now), /created_utc before expires_utc/],
  'oversized': [' '.repeat(4097), /oversized/]
};
for (const [name, [content, message]] of Object.entries(malformedPackJson)) test(`malformed PACK.json refuses load even outside strict: ${name}`, t => {
  const dir = fixture(t); writeFileSync(join(dir, 'PACK.json'), content); reseal(dir);
  assert.throws(() => loadPack(dir), message);
});

test('pure verifier returns the dates it checked', () => {
  const files = Object.fromEntries(readdirSync(sample).map(n => [n, readFileSync(join(sample, n))]));
  files['PACK.json'] = Buffer.from(packJson(now - DAY, now + DAY));
  files['SHA256SUMS'] = Buffer.from(Object.keys(files).filter(n => n !== 'SHA256SUMS').sort().map(n => hash(files[n]) + '  ' + n + '\n').join(''));
  assert.deepEqual(verifyPackEntries(Object.keys(files), n => files[n], hash).dates, { created_utc: iso(now - DAY), expires_utc: iso(now + DAY) });
});

test('plugin: stale pack loads with a logged warning; strict registers zero tools; strict stops serving after expiry', async t => {
  const key = newKey(), trustedKeys = [key.line('publisher')];
  const stale = dated(fixture(t), now - 60 * DAY, now - DAY, key);
  const warnings = [], tools = [];
  plugin.register({ pluginConfig: { packPath: stale, trustedKeys }, logger: { warn: m => warnings.push(m), info() {}, error() {} }, registerTool: x => tools.push(x) });
  assert.deepEqual(warnings, [`verified-memory: warning: pack expired at ${iso(now - DAY)} (stale); serving it because strict mode is off`]);
  assert.equal((await tools[0].execute('1', { query: 'pottery' })).details.verification.freshness.status, 'stale');
  const refused = [];
  assert.throws(() => plugin.register({ pluginConfig: { packPath: stale, trustedKeys, strict: true }, registerTool: x => refused.push(x) }), /strict mode refuses stale packs/);
  assert.equal(refused.length, 0);
  // Fresh at registration, expired later: the strict tool call itself refuses.
  const t0 = Date.now(), soon = dated(fixture(t), t0 - DAY, t0 + 3000, key), live = [];
  plugin.register({ pluginConfig: { packPath: soon, trustedKeys, strict: true }, registerTool: x => live.push(x) });
  assert.equal((await live[0].execute('1', { query: 'pottery' })).details.verification.freshness.status, 'fresh');
  await new Promise(r => setTimeout(r, Date.parse(iso(t0 + 3000)) - Date.now() + 50));
  await assert.rejects(live[0].execute('2', { query: 'pottery' }), /strict mode refuses stale packs/);
  await assert.rejects(live[1].execute('3', { id: 'M-sample-2' }), /strict mode refuses stale packs/);
});
