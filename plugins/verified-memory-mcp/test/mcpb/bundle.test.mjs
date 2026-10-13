// Tests the built Claude Desktop bundle (run via `npm run test:mcpb`). The server command
// line comes from @anthropic-ai/mcpb's getMcpConfigForManifest, the substitution code Claude
// Desktop uses, so these runs see the arguments a real install would pass.
import test from 'node:test';
import assert from 'node:assert/strict';
import { cpSync, mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative, resolve, sep } from 'node:path';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { getMcpConfigForManifest, unpackExtension, validateManifest } from '@anthropic-ai/mcpb';

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

test('only the pack folder set: trusted keys blank and signature off by default', async t => {
  const config = await configFor({ pack_dir: '/fictional/pack' });
  assert.deepEqual(config.args.slice(1), ['--pack=/fictional/pack', '--trusted-keys=', '--require-signature=false']);
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
