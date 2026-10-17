// Tests the built Claude Desktop bundle (run via `npm run test:mcpb`). The server command
// line comes from @anthropic-ai/mcpb's getMcpConfigForManifest, the substitution code Claude
// Desktop uses, so these runs see the arguments a real install would pass.
import test from 'node:test';
import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative, resolve, sep } from 'node:path';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { getMcpConfigForManifest, unpackExtension, validateManifest } from '@anthropic-ai/mcpb';
import { createHash } from 'node:crypto';
import { fingerprint } from '../../dist/verify.js';
import { newKey, sshsig } from '../../../verified-memory/test/sshsig.mjs';

const { version } = JSON.parse(readFileSync('package.json', 'utf8'));
const bundle = resolve(`build/verified-memory-${version}.mcpb`);
const signedFixture = resolve('../verified-memory/test/fixtures/signed-sample');
const root = mkdtempSync(join(tmpdir(), 'mcpb-bundle-test-'));
test.after(() => rmSync(root, { recursive: true, force: true }));
const unpacked = join(root, 'unpacked');
await unpackExtension({ mcpbPath: bundle, outputDir: unpacked, silent: true });
const manifest = JSON.parse(readFileSync(join(unpacked, 'manifest.json'), 'utf8'));

function walk(dir) {
  return readdirSync(dir).flatMap(name => statSync(join(dir, name)).isDirectory() ? walk(join(dir, name)) : [relative(unpacked, join(dir, name)).split(sep).join('/')]);
}
// A pack folder whose path has spaces, like a real user's Documents folder.
function packCopy(name, signed) {
  const dir = join(root, 'my packs', name);
  // The fixture signature signs the fictional sample pack.
  cpSync(signed ? 'sample-pack' : 'examples/pack', dir, { recursive: true });
  if (signed) cpSync(join(signedFixture, 'SHA256SUMS.sig'), join(dir, 'SHA256SUMS.sig'));
  return dir;
}
async function configFor(userConfig) {
  const config = await getMcpConfigForManifest({ manifest, extensionPath: unpacked, systemDirs: { HOME: root, DESKTOP: root, DOCUMENTS: root, DOWNLOADS: root }, userConfig, pathSeparator: sep });
  assert.ok(config, 'required settings are present');
  assert.equal(config.command, 'node');
  return config;
}
// Claude Desktop runs `node` with its built-in runtime; here the test's own Node stands in.
async function connect(t, userConfig) {
  const { args } = await configFor(userConfig);
  const transport = new StdioClientTransport({ command: process.execPath, args, cwd: tmpdir(), stderr: 'pipe', env: {} });
  let stderr = ''; transport.stderr?.on('data', d => { stderr += d; });
  const client = new Client({ name: 'fictional-bundle-test', version: '1.0.0' });
  t.after(() => client.close());
  try { await client.connect(transport); } catch (error) { error.stderr = stderr; throw error; }
  return client;
}
const search = async (client, query) => (await client.callTool({ name: 'verified_memory_search', arguments: { query } })).structuredContent;

// The packs below are checked byte for byte. A checkout that rewrote their line endings
// (core.autocrlf on Windows, without the .gitattributes rules) fails here with a clear message
// instead of as an opaque "checksum mismatch" in every server test.
test('fixture packs are checked out byte for byte, with no CRLF conversion', () => {
  for (const dir of ['examples/pack', 'sample-pack', '../verified-memory/sample-pack', signedFixture])
    for (const name of readdirSync(dir))
      assert.ok(!readFileSync(join(dir, name)).includes(13), `${dir}/${name} has CR bytes: line endings were converted at checkout; see .gitattributes`);
});

test('bundle manifest is valid, versioned with the package and lists the real tools', async t => {
  assert.equal(validateManifest(unpacked), true);
  assert.equal(manifest.version, version);
  assert.equal(JSON.parse(readFileSync('server.json', 'utf8')).version, version);
  const client = await connect(t, { pack_dir: packCopy('tools', false) });
  assert.deepEqual(manifest.tools.map(x => x.name), (await client.listTools()).tools.map(x => x.name));
});

test('bundle contains only the allowlisted files, the npm dist, and no keys or packs', () => {
  const files = walk(unpacked);
  const top = [...new Set(files.map(f => f.split('/')[0]))].sort();
  assert.deepEqual(top, ['LICENSE', 'README.md', 'dist', 'manifest.json', 'node_modules', 'package.json']);
  const dist = readdirSync('dist').filter(f => !f.endsWith('.d.ts')).sort();
  assert.deepEqual(files.filter(f => f.startsWith('dist/')).map(f => f.slice(5)).sort(), dist);
  for (const f of dist) assert.deepEqual(readFileSync(join(unpacked, 'dist', f)), readFileSync(join('dist', f)), f);
  assert.ok(!files.some(f => /(^|\/)(SHA256SUMS(\.sig)?|records\.jsonl|MEMORY\.md|trusted_keys|id_[^/]*|[^/]*\.key)$/.test(f)), 'no packs, signatures or keys');
  assert.ok(!files.some(f => f.startsWith('node_modules/') && /^node_modules\/(typescript|@types|@anthropic-ai)\//.test(f)), 'no dev dependencies');
  // Real key material: a PEM private key header followed by a base64 body. (Libraries such as
  // jose mention the bare header string when checking input formats.)
  for (const f of files) assert.doesNotMatch(readFileSync(join(unpacked, f), 'latin1'), /-----BEGIN ([A-Z]+ )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=]{16}/, f);
});

test('only the pack folder set: trusted keys, pin, revocation and minimum sequence blank, signature off by default', async t => {
  const config = await configFor({ pack_dir: '/fictional/pack' });
  assert.deepEqual(config.args.slice(1), ['--pack=/fictional/pack', '--trusted-keys=', '--trusted-fingerprint=', '--revoked-keys=', '--min-sequence=', '--require-signature=false', '--strict=false']);
  const result = await search(await connect(t, { pack_dir: packCopy('unsigned', false) }), 'seedlings');
  assert.equal(result.matched, 1); assert.equal(result.verification.sha256sums, 'passed');
});

test('missing pack folder: no server config, so the extension cannot start', async () => {
  assert.equal(await getMcpConfigForManifest({ manifest, extensionPath: unpacked, systemDirs: {}, userConfig: {}, pathSeparator: sep }), undefined);
});

test('signed pack with trusted keys and signature required reports the signer', async t => {
  const client = await connect(t, { pack_dir: packCopy('signed', true), trusted_keys: join(signedFixture, 'trusted_keys'), require_signature: true });
  const { signature } = (await search(client, 'pottery')).verification;
  assert.equal(signature.status, 'verified'); assert.equal(signature.signer, 'fictional-signer');
});

test('signature required but pack unsigned: refuses to start', async t => {
  await assert.rejects(connect(t, { pack_dir: packCopy('unsigned-required', false), trusted_keys: join(signedFixture, 'trusted_keys'), require_signature: true }),
    e => /unsigned .* a signature is required/.test(e.stderr) || assert.fail(e.stderr ?? String(e)));
});

test('signature required with no trusted keys file: refuses to start', async t => {
  await assert.rejects(connect(t, { pack_dir: packCopy('signed-nokeys', true), require_signature: true }),
    e => /at least one trusted key/.test(e.stderr) || assert.fail(e.stderr ?? String(e)));
});

// v0.4 settings. The fixture key's fingerprint, as ssh-keygen -l prints it.
const fixturePrint = 'SHA256:QdQEQAWD+03v/nksLJaA+zSSRPOSa/V/eODKuTXBY94';
const otherPrint = 'SHA256:' + 'A'.repeat(43);

test('pinned signer fingerprint setting: the pinned key starts (no trusted keys file needed); any other refuses', async t => {
  const { signature } = (await search(await connect(t, { pack_dir: packCopy('pinned', true), trusted_fingerprint: `${otherPrint}, ${fixturePrint}` }), 'pottery')).verification;
  assert.equal(signature.status, 'verified'); assert.equal(signature.pinned, true); assert.equal(signature.fingerprint, fixturePrint);
  await assert.rejects(connect(t, { pack_dir: packCopy('pinned-other', true), trusted_keys: join(signedFixture, 'trusted_keys'), trusted_fingerprint: otherPrint }),
    e => /which is not a pinned signer fingerprint/.test(e.stderr) || assert.fail(e.stderr ?? String(e)));
});

test('revoked keys file setting: a revoked signer refuses to start even when pinned', async t => {
  const revoked = join(root, 'revoked keys.txt'); writeFileSync(revoked, `# lost\n${fixturePrint}\n`);
  await assert.rejects(connect(t, { pack_dir: packCopy('revoked', true), trusted_fingerprint: fixturePrint, revoked_keys: revoked }),
    e => new RegExp(`${fixturePrint.replace(/[+/]/g, '\\$&')}, which is revoked`).test(e.stderr) || assert.fail(e.stderr ?? String(e)));
});

test('minimum sequence setting: a pack without a signed sequence refuses to start; a bad value is a clear error', async t => {
  await assert.rejects(connect(t, { pack_dir: packCopy('sequence', true), trusted_fingerprint: fixturePrint, min_sequence: '1' }),
    e => /pack has no sequence in PACK\.json/.test(e.stderr) || assert.fail(e.stderr ?? String(e)));
  await assert.rejects(connect(t, { pack_dir: packCopy('sequence-bad', true), trusted_fingerprint: fixturePrint, min_sequence: 'one' }),
    e => /--min-sequence must be a whole number/.test(e.stderr) || assert.fail(e.stderr ?? String(e)));
});

test('strict setting: refuses an undated signed pack; off by default keeps 0.3.0 behaviour', async t => {
  await assert.rejects(connect(t, { pack_dir: packCopy('strict-undated', true), trusted_fingerprint: fixturePrint, strict: true }),
    e => /no PACK\.json, so no expiry date, and strict mode requires a fresh pack/.test(e.stderr) || assert.fail(e.stderr ?? String(e)));
  await assert.rejects(connect(t, { pack_dir: packCopy('strict-nokeys', true), strict: true }),
    e => /at least one trusted key or pinned fingerprint/.test(e.stderr) || assert.fail(e.stderr ?? String(e)));
  const { freshness } = (await search(await connect(t, { pack_dir: packCopy('strict-off', true), trusted_fingerprint: fixturePrint, strict: false }), 'pottery')).verification;
  assert.equal(freshness.status, 'unknown');
});

test('strict setting with a dated pack signed by the pinned key: starts and reports fresh', async t => {
  const dir = packCopy('strict-fresh', false), key = newKey(), now = Date.now();
  cpSync('sample-pack', dir, { recursive: true, force: true });
  const iso = ms => new Date(Math.floor(ms / 1000) * 1000).toISOString().replace('.000Z', 'Z');
  writeFileSync(join(dir, 'PACK.json'), JSON.stringify({ format: 'verified-memory-pack', version: 2, created_utc: iso(now - 86400000), expires_utc: iso(now + 30 * 86400000), sequence: 2 }));
  const hash = b => createHash('sha256').update(b).digest('hex');
  writeFileSync(join(dir, 'SHA256SUMS'), ['MEMORY.md', 'PACK.json', 'README.md', 'records.jsonl'].map(n => `${hash(readFileSync(join(dir, n)))}  ${n}\n`).join(''));
  writeFileSync(join(dir, 'SHA256SUMS.sig'), sshsig(key, readFileSync(join(dir, 'SHA256SUMS'))));
  const pin = fingerprint(key.raw, hash);
  const { verification } = await search(await connect(t, { pack_dir: dir, trusted_fingerprint: pin, min_sequence: '2', strict: true }), 'pottery');
  assert.equal(verification.signature.pinned, true); assert.equal(verification.freshness.status, 'fresh'); assert.equal(verification.freshness.sequence, 2);
});
