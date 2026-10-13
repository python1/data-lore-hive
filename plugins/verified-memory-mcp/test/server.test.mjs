import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, cpSync, readFileSync, writeFileSync, rmSync, symlinkSync, unlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { InMemoryTransport } from '@modelcontextprotocol/sdk/inMemory.js';
import { createServer, notice } from '../dist/server.js';
import { loadPack } from '../dist/pack.js';
import { newKey, armor } from '../../verified-memory/test/sshsig.mjs';
const sample = resolve('sample-pack');
const permissionFlag = process.allowedNodeEnvironmentFlags.has('--permission') ? '--permission' : '--experimental-permission';
const networkPermissions = process.allowedNodeEnvironmentFlags.has('--allow-net');
const hash = bytes => createHash('sha256').update(bytes).digest('hex');
function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'fictional-mcp-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const dir = join(root, 'pack'); cpSync(sample, dir, { recursive: true }); return dir;
}
function reseal(dir) {
  writeFileSync(join(dir, 'SHA256SUMS'), ['MEMORY.md', 'README.md', 'records.jsonl'].map(n => hash(readFileSync(join(dir, n))) + '  ' + n + '\n').join(''));
}
async function clientFor(t, dir) {
  const server = createServer(dir);
  const client = new Client({ name: 'fictional-test', version: '1.0.0' });
  const [ct, st] = InMemoryTransport.createLinkedPair();
  t.after(async () => { await client.close(); await server.close(); });
  await server.connect(st); await client.connect(ct); return client;
}
const call = (client, name, args) => client.callTool({ name, arguments: args });
function refuse(dir, pattern) {
  assert.throws(() => createServer(dir), pattern);
  const p = spawnSync(process.execPath, ['dist/index.js', '--pack', dir], {
    input: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'fictional-test', version: '1' } } }) + '\n',
    encoding: 'utf8', timeout: 5000
  });
  assert.equal(p.status, 1, p.stderr); assert.equal(p.stdout, ''); assert.match(p.stderr, /verified-memory-mcp:/);
  assert.ok(!p.stderr.includes(dir), 'startup diagnostics do not expose configured paths');
  assert.ok(!p.stderr.includes('fictional'), 'user-facing startup errors are pack-neutral');
}
test('build reuses byte-identical verifier and fictional pack without modifying source plugin', () => {
  assert.deepEqual(readFileSync('src/pack.ts'), readFileSync('../verified-memory/src/pack.ts'));
  assert.deepEqual(readFileSync('src/verify.ts'), readFileSync('../verified-memory/src/verify.ts'));
  for (const file of ['MEMORY.md', 'README.md', 'records.jsonl', 'SHA256SUMS']) assert.deepEqual(readFileSync('sample-pack/' + file), readFileSync('../verified-memory/sample-pack/' + file));
});
test('valid pack exposes exactly matching schemas, read-only hints and exact cited results via MCP', async t => {
  const client = await clientFor(t);
  const { tools } = await client.listTools();
  assert.deepEqual(tools.map(x => x.name), ['verified_memory_search', 'verified_memory_get']);
  const publishedReadme = readFileSync('../verified-memory/README.md', 'utf8');
  const publishedSchemas = ['verified_memory_search', 'verified_memory_get'].map(name => {
    const section = publishedReadme.split('`' + name + '` input:')[1];
    return JSON.parse(section.split('```json\n')[1].split('```')[0]);
  });
  assert.deepEqual(tools.map(x => x.inputSchema), publishedSchemas);
  const manifest = JSON.parse(readFileSync('../verified-memory/openclaw.plugin.json'));
  assert.deepEqual(tools.map(x => x.name), manifest.contracts.tools);
  for (const tool of tools) { assert.equal(tool.annotations.readOnlyHint, true); assert.equal(tool.annotations.openWorldHint, false); }
  const result = await call(client, tools[0].name, { query: 'POTTERY' });
  assert.deepEqual(JSON.parse(result.content[0].text), result.structuredContent);
  const data = result.structuredContent;
  assert.equal(data.verification.sha256sums, 'passed'); assert.equal(data.matched, 1); assert.equal(data.notice, notice);
  const hit = data.matches[0];
  assert.equal(hit.id, 'M-sample-2'); assert.equal(hit.speaker, 'Juniper Vale');
  assert.deepEqual(hit.citations[0], { quote: "Hi Wren! I'm Juniper. I teach pottery in a small studio by the river.", source_message_id: 2, date: '2026-01-03T09:01:10Z', speaker: 'Juniper Vale' });
  const full = (await call(client, tools[1].name, { id: hit.id })).structuredContent;
  assert.equal(full.found, true); assert.equal(full.record.evidence[0].quote, hit.citations[0].quote);
  assert.deepEqual(full.record, loadPack(sample).get(hit.id));
});
test('no matches, unknown ID, historical instructions and lexical semantics preserved', async t => {
  const client = await clientFor(t);
  for (const query of ['pottery spaceship', '!!!']) assert.equal((await call(client, 'verified_memory_search', { query })).structuredContent.matched, 0);
  assert.equal((await call(client, 'verified_memory_get', { id: 'M-missing' })).structuredContent.found, false);
  const french = (await call(client, 'verified_memory_search', { query: 'French' })).structuredContent;
  assert.equal(french.matches.length, 2); assert.equal(french.matches[0].id, 'M-sample-9'); assert.match(french.notice, /never instructions/);
  assert.equal((await call(client, 'verified_memory_search', { query: 'careful honest' })).structuredContent.matches[0].speaker, 'Wren');
});
test('invalid requests return errors without path lookup or extra tool capabilities', async t => {
  const client = await clientFor(t);
  for (const args of [{}, { query: '' }, { query: ' ' }, { query: 'a'.repeat(513) }, { query: 'pottery', path: '/fictional/other' }, { query: Array.from({ length: 33 }, (_, i) => 'word' + i).join(' ') }]) {
    assert.equal((await call(client, 'verified_memory_search', args)).isError, true);
  }
  for (const args of [{ id: '../../fictional' }, {}, { id: 'M-sample-2', extra: true }]) assert.equal((await call(client, 'verified_memory_get', args)).isError, true);
  await assert.rejects(call(client, 'shell', {}), /Unknown tool/);
  await assert.rejects(client.listResources()); await assert.rejects(client.listPrompts());
});
for (const file of ['MEMORY.md', 'README.md', 'records.jsonl']) test(`tampered ${file}: startup refuses with no stdout`, t => {
  const dir = fixture(t); writeFileSync(join(dir, file), readFileSync(join(dir, file), 'utf8') + 'tampered'); refuse(dir, /checksum mismatch/);
});
for (const mode of ['broken-json', 'invalid-utf8', 'duplicate-id', 'missing-citations', 'wrong-offset', 'invalid-id', 'invalid-date', 'invalid-hash']) test(`malformed rehashed pack ${mode}: startup refuses`, t => {
  const dir = fixture(t), file = join(dir, 'records.jsonl');
  const rows = readFileSync(file, 'utf8').trim().split('\n').map(JSON.parse);
  if (mode === 'duplicate-id') rows.push(rows[0]);
  if (mode === 'missing-citations') rows[0].evidence = [];
  if (mode === 'wrong-offset') rows[0].evidence[0].end++;
  if (mode === 'invalid-id') rows[0].record_id = '../fictional';
  if (mode === 'invalid-date') rows[0].date_last_utc = 'yesterday';
  if (mode === 'invalid-hash') rows[0].evidence[0].message_sha256 = 'x';
  writeFileSync(file, mode === 'broken-json' ? '{' : mode === 'invalid-utf8' ? Buffer.from([255]) : rows.map(JSON.stringify).join('\n') + '\n');
  reseal(dir); refuse(dir);
});
for (const mode of ['duplicate', 'missing', 'traversal', 'malformed', 'self']) test(`malformed manifest ${mode}: startup refuses`, t => {
  const dir = fixture(t); let sums = readFileSync(join(dir, 'SHA256SUMS'), 'utf8');
  if (mode === 'duplicate') sums += sums.split('\n')[0] + '\n';
  if (mode === 'missing') sums = sums.split('\n').slice(1).join('\n');
  if (mode === 'traversal') sums = sums.replace('MEMORY.md', '../MEMORY.md');
  if (mode === 'malformed') sums = 'not a checksum';
  if (mode === 'self') sums = sums.replace('MEMORY.md', 'SHA256SUMS');
  writeFileSync(join(dir, 'SHA256SUMS'), sums); refuse(dir);
});
test('missing, extra, symlink entries and symlink root rejected', t => {
  const dir = fixture(t);
  refuse(join(dir, 'missing')); refuse('relative/fictional');
  writeFileSync(join(dir, 'extra'), 'x'); refuse(dir); unlinkSync(join(dir, 'extra'));
  const bytes = readFileSync(join(dir, 'README.md')); unlinkSync(join(dir, 'README.md')); refuse(dir);
  writeFileSync(join(dir, '..', 'outside'), bytes); symlinkSync(join(dir, '..', 'outside'), join(dir, 'README.md')); refuse(dir);
  const link = join(dir, '..', 'link'); symlinkSync(dir, link); refuse(link);
});
test('verified snapshot survives disk edits and returned-object mutation', async t => {
  const dir = fixture(t), client = await clientFor(t, dir);
  const result = (await call(client, 'verified_memory_get', { id: 'M-sample-2' })).structuredContent;
  result.record.statement = 'changed'; result.record.evidence[0].quote = 'changed';
  writeFileSync(join(dir, 'records.jsonl'), 'tampered');
  assert.match((await call(client, 'verified_memory_get', { id: 'M-sample-2' })).structuredContent.record.statement, /pottery/);
  assert.match((await call(client, 'verified_memory_search', { query: 'pottery' })).structuredContent.matches[0].citations[0].quote, /pottery/);
  refuse(dir, /checksum mismatch/);
});
test('actual stdio protocol works under Node permissions denying writes, subprocesses and workers', { timeout: 10000 }, async t => {
  const transport = new StdioClientTransport({ command: process.execPath,
    args: [permissionFlag, '--allow-fs-read=' + process.cwd(), resolve('dist/index.js')],
    cwd: tmpdir(), stderr: 'pipe', env: {} });
  const client = new Client({ name: 'fictional-stdio-test', version: '1.0.0' });
  t.after(() => client.close());
  let diagnostic = ''; transport.stderr?.on('data', chunk => { diagnostic += chunk; });
  await client.connect(transport);
  assert.equal((await client.listTools()).tools.length, 2);
  const result = (await call(client, 'verified_memory_search', { query: 'pottery' })).structuredContent;
  assert.equal(result.matched, 1);
  assert.equal((await call(client, 'verified_memory_get', { id: result.matches[0].id })).structuredContent.found, true);
  if (permissionFlag === '--experimental-permission') {
    assert.match(diagnostic, /ExperimentalWarning: Permission is an experimental feature/);
  } else {
    assert.equal(diagnostic, '');
  }
  // Prove the runtime policy actually denies the prohibited operations.
  for (const code of ["require('node:fs').writeFileSync('forbidden','x')", "require('node:child_process').spawnSync(process.execPath,['-v'])", "new (require('node:worker_threads').Worker)('',{eval:true})"]) {
    const p = spawnSync(process.execPath, [permissionFlag, '-e', code], { encoding: 'utf8', timeout: 5000 });
    assert.notEqual(p.status, 0); assert.match(p.stderr, /ERR_ACCESS_DENIED/);
  }
});
test('network permission policy denies socket access when supported', { skip: networkPermissions ? false : 'This Node version has no network permission scope' }, () => {
  const p = spawnSync(process.execPath, [permissionFlag, '-e', "require('node:net').connect(9,'127.0.0.1')"], { encoding: 'utf8', timeout: 5000 });
  assert.notEqual(p.status, 0); assert.match(p.stderr, /ERR_ACCESS_DENIED/);
});

test('every bundled citation matches only the public fictional source', () => {
  const source = JSON.parse(readFileSync('../../agent-memory/sample/telegram-export.json'));
  const messages = new Map(source.messages.map(m => [m.id, m]));
  const pack = loadPack(sample);
  for (const id of [2, 3, 4, 6, 9, 12, 13, 15]) {
    const m = messages.get(id), record = pack.get('M-sample-' + id);
    const text = Array.isArray(m.text) ? m.text.map(x => typeof x === 'string' ? x : x.text).join('') : m.text;
    assert.equal(record.speaker, m.from); assert.equal(record.evidence[0].quote, text); assert.equal(record.evidence[0].message_sha256, hash(Buffer.from(text)));
  }
});
test('invalid CLI flags refuse before protocol output', () => {
  for (const args of [['--pack'], ['--other'], ['--pack', sample, 'extra']]) {
    const p = spawnSync(process.execPath, ['dist/index.js', ...args], { encoding: 'utf8', timeout: 5000 });
    assert.equal(p.status, 1); assert.equal(p.stdout, ''); assert.match(p.stderr, /Usage:/);
    assert.ok(!p.stderr.includes('fictional'));
    assert.match(p.stderr, /--pack \/absolute\/path\/to\/pack/);
  }
});

// Signed packs (v0.2). The fixture key is invented; its private half was deleted after signing.
const signedFixture = resolve('../verified-memory/test/fixtures/signed-sample');
const trustFile = join(signedFixture, 'trusted_keys');
function signedCopy(t) { const dir = fixture(t); cpSync(join(signedFixture, 'SHA256SUMS.sig'), join(dir, 'SHA256SUMS.sig')); return dir; }
function startup(args) {
  return spawnSync(process.execPath, ['dist/index.js', ...args], {
    input: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'fictional-test', version: '1' } } }) + '\n',
    encoding: 'utf8', timeout: 5000
  });
}
test('unsigned packs keep the exact v0.1 tool output, with or without trusted keys', async t => {
  const plain = (await call(await clientFor(t), 'verified_memory_search', { query: 'pottery' })).content[0].text;
  const server = createServer(undefined, { trustedKeys: [readFileSync(trustFile, 'utf8')] });
  const client = new Client({ name: 'fictional-test', version: '1.0.0' }); const [ct, st] = InMemoryTransport.createLinkedPair();
  t.after(async () => { await client.close(); await server.close(); }); await server.connect(st); await client.connect(ct);
  assert.equal((await call(client, 'verified_memory_search', { query: 'pottery' })).content[0].text, plain);
  assert.deepEqual(Object.keys(JSON.parse(plain).verification), ['sha256sums', 'manifest_sha256', 'records', 'scope']);
});
test('signed pack over real stdio, under permission mode, with trust file and either flag form', { timeout: 15000 }, async t => {
  const dir = signedCopy(t);
  for (const args of [['--pack', dir, '--trusted-keys', trustFile, '--require-signature'], [`--pack=${dir}`, `--trusted-keys=${trustFile}`, '--require-signature=true']]) {
    const transport = new StdioClientTransport({ command: process.execPath,
      args: [permissionFlag, '--allow-fs-read=' + process.cwd(), '--allow-fs-read=' + dir, '--allow-fs-read=' + trustFile, resolve('dist/index.js'), ...args],
      cwd: tmpdir(), stderr: 'pipe', env: {} });
    const client = new Client({ name: 'fictional-stdio-test', version: '1.0.0' });
    await client.connect(transport);
    const result = (await call(client, 'verified_memory_search', { query: 'pottery' })).structuredContent;
    await client.close();
    assert.equal(result.matched, 1);
    assert.deepEqual({ ...result.verification.signature, scope: undefined }, { status: 'verified', signer: 'fictional-signer', fingerprint: 'SHA256:QdQEQAWD+03v/nksLJaA+zSSRPOSa/V/eODKuTXBY94', scope: undefined });
    assert.match(result.verification.signature.scope, /does not establish that the content is true/);
  }
});
test('valid signature by an unlisted key starts and reports untrusted', async t => {
  const dir = signedCopy(t);
  const p = startup(['--pack', dir]);
  const line = p.stdout.split('\n').find(Boolean);
  assert.ok(line, p.stderr); assert.equal(JSON.parse(line).result.serverInfo.version, '0.2.0');
  const { verification } = (await call(await clientFor(t, dir), 'verified_memory_get', { id: 'M-sample-2' })).structuredContent;
  assert.equal(verification.signature.status, 'untrusted'); assert.equal(verification.signature.signer, undefined);
});
for (const [name, setup, pattern] of [
  ['unsigned pack with --require-signature', t => ['--pack', fixture(t), '--trusted-keys', trustFile, '--require-signature'], /unsigned .* a signature is required/],
  ['--require-signature with no trusted keys', t => ['--pack', signedCopy(t), '--require-signature'], /at least one trusted key/],
  ['comment-only trust file with --require-signature', t => { const dir = signedCopy(t); const other = join(dir, '..', 'other_keys'); writeFileSync(other, '# none trusted yet\n'); return ['--pack', dir, '--trusted-keys', other, '--require-signature']; }, /at least one trusted key/],
  ['untrusted signer with --require-signature', t => { const dir = signedCopy(t); const other = join(dir, '..', 'other_keys'); writeFileSync(other, newKey().line('someone-else') + '\n'); return ['--pack', dir, '--trusted-keys', other, '--require-signature']; }, /not a trusted key, and a signature is required/],
  ['tampered signature', t => { const dir = signedCopy(t); const blob = Buffer.from(readFileSync(join(dir, 'SHA256SUMS.sig'), 'utf8').split('\n').slice(1, -2).join(''), 'base64'); blob[blob.length - 10] ^= 1; writeFileSync(join(dir, 'SHA256SUMS.sig'), armor(blob)); return ['--pack', dir]; }, /pack signature does not verify/],
  ['malformed trust file', t => { const dir = fixture(t); const bad = join(dir, '..', 'bad_keys'); writeFileSync(bad, 'alice ssh-rsa AAAA\n'); return ['--pack', dir, '--trusted-keys', bad]; }, /must be ssh-ed25519/],
  ['missing trust file', t => ['--pack', fixture(t), '--trusted-keys', join(tmpdir(), 'fictional-missing-keys')], /cannot read trusted keys file/],
  ['relative trust file', t => ['--pack', fixture(t), '--trusted-keys', 'trusted_keys'], /trusted keys path must be absolute/]
]) test(`startup refuses with no stdout: ${name}`, t => {
  const args = setup(t), p = startup(args);
  assert.equal(p.status, 1, p.stderr); assert.equal(p.stdout, ''); assert.match(p.stderr, pattern);
  for (const arg of args) if (arg.startsWith('/')) assert.ok(!p.stderr.includes(arg), 'diagnostics do not expose configured paths');
});
test('signature CLI flags: duplicates, missing values and bad switch values refuse', () => {
  for (const args of [['--trusted-keys'], ['--trusted-keys', '--require-signature'], ['--require-signature', '--require-signature'], ['--require-signature=yes'],
    ['--pack', sample, '--pack', sample], ['--trusted-keys', trustFile, '--trusted-keys=' + trustFile], ['--require-signature', 'maybe'], ['--pack=']]) {
    const p = spawnSync(process.execPath, ['dist/index.js', ...args], { encoding: 'utf8', timeout: 5000 });
    assert.equal(p.status, 1, args.join(' ')); assert.equal(p.stdout, ''); assert.match(p.stderr, /Usage: .*--trusted-keys .*--require-signature/);
  }
});
test('empty --trusted-keys= (a blank Claude Desktop setting) means no trusted keys', t => {
  const dir = signedCopy(t);
  const p = startup(['--pack', dir, '--trusted-keys=', '--require-signature=false']);
  const line = p.stdout.split('\n').find(Boolean);
  assert.ok(line, p.stderr); assert.equal(JSON.parse(line).result.serverInfo.version, '0.2.0');
  const required = startup(['--pack', dir, '--trusted-keys=', '--require-signature=true']);
  assert.equal(required.status, 1); assert.match(required.stderr, /at least one trusted key/);
});
test('npm package ships the funding link and no keys, signatures or test fixtures', () => {
  assert.equal(JSON.parse(readFileSync('package.json')).funding, 'https://buymeacoffee.com/python1');
  const files = JSON.parse(spawnSync('npm', ['pack', '--dry-run', '--json', '--ignore-scripts'], { encoding: 'utf8' }).stdout)[0].files.map(f => f.path);
  assert.ok(files.includes('dist/verify.js') && !files.some(f => /\.sig$|trusted_keys|(^|\/)id_|\.key$|^test\//.test(f)), files.join(', '));
  for (const f of files) assert.doesNotMatch(readFileSync(f, 'latin1'), /PRIVATE KEY-----/, f);
});
