// sign-pack: real ssh-keygen with throwaway passphrase-protected keys made in a temporary
// directory (removed after each test) and the fictional sample pack. The passphrase comes from
// an SSH_ASKPASS script, standing in for a person typing it.
import test from 'node:test';
import assert from 'node:assert/strict';
import { chmodSync, cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { loadPack } from '../dist/pack.js';
const sample = resolve('sample-pack');
const script = resolve('tools/sign-pack.mjs');
const PASSPHRASE = 'fictional passphrase for tests';
const permissionFlag = process.allowedNodeEnvironmentFlags.has('--permission') ? '--permission' : '--experimental-permission';
const hasSshKeygen = spawnSync('ssh-keygen', ['-Y', 'verify'], { encoding: 'utf8' }).error === undefined;
const skip = hasSshKeygen ? false : 'ssh-keygen not installed';
// In CI, Windows OpenSSH's ssh-keygen did not take the passphrase from SSH_ASKPASS, so on
// Windows the throwaway keys have no passphrase and only the wrong-passphrase test is skipped.
// The permission-mode test still shows sign-pack cannot read the private key file itself.
const askpassWorks = process.platform !== 'win32';
const DEFAULT_PASSPHRASE = askpassWorks ? PASSPHRASE : '';

/** root/{pack,keys,work}: the private key sits alone in keys/, apart from what the script may read. */
function setup(t, { type = 'ed25519', passphrase = DEFAULT_PASSPHRASE } = {}) {
  const root = mkdtempSync(join(tmpdir(), 'verified-memory-sign-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const pack = join(root, 'pack'), keys = join(root, 'keys'), work = join(root, 'work');
  cpSync(sample, pack, { recursive: true }); mkdirSync(keys); mkdirSync(work);
  const key = join(keys, 'pack_signing');
  assert.equal(spawnSync('ssh-keygen', ['-q', '-t', type, '-N', passphrase, '-C', 'fictional-signing-key', '-f', key]).status, 0);
  const askpass = join(root, 'askpass.sh');
  writeFileSync(askpass, `#!/bin/sh\necho '${PASSPHRASE}'\n`); chmodSync(askpass, 0o700);
  return { root, pack, keys, work, key, askpass };
}
function sign(env, args, nodeArgs = []) {
  return spawnSync(process.execPath, [...nodeArgs, script, ...args], {
    encoding: 'utf8', timeout: 30000, stdio: ['ignore', 'pipe', 'pipe'],
    // Windows OpenSSH's ssh-keygen exits 255 without a message in a minimal environment, so
    // there it keeps the runner's environment.
    env: { ...(process.platform === 'win32' ? process.env : { PATH: process.env.PATH, HOME: env.root }), SSH_ASKPASS: env.askpass, SSH_ASKPASS_REQUIRE: 'force', DISPLAY: ':0' }
  });
}
const pubLine = (key, name = 'publisher') => `${name} ${readFileSync(key + '.pub', 'utf8').split(' ').slice(0, 2).join(' ')}`;
const leftovers = (dir) => readdirSync(dir).filter((n) => n.includes('.signing-'));

test('signs with a passphrase-protected key without ever being able to read it; hosts verify it in strict mode', { skip }, (t) => {
  const env = setup(t), out = join(env.work, 'signed');
  const before = Object.fromEntries(readdirSync(env.pack).map((n) => [n, readFileSync(join(env.pack, n))]));
  // Node's permission model: the script may read the repo, the pack, its own work folder and
  // KEY.pub, but not the private key file. Only the ssh-keygen child process can read it.
  const p = sign(env, ['--pack', env.pack, '--key', env.key, '--expires', '90d', '--out', out], [permissionFlag,
    `--allow-fs-read=${resolve('.')}`, `--allow-fs-read=${env.pack}`, `--allow-fs-read=${env.work}`, `--allow-fs-read=${env.key}.pub`,
    `--allow-fs-write=${env.work}`, '--allow-child-process']);
  assert.equal(p.status, 0, p.stderr);
  assert.deepEqual(readdirSync(out).sort(), ['MEMORY.md', 'PACK.json', 'README.md', 'SHA256SUMS', 'SHA256SUMS.sig', 'records.jsonl']);
  const dates = JSON.parse(readFileSync(join(out, 'PACK.json'), 'utf8'));
  assert.deepEqual(Object.keys(dates), ['format', 'version', 'created_utc', 'expires_utc']);
  assert.equal(dates.format, 'verified-memory-pack'); assert.equal(dates.version, 2);
  const days = (Date.parse(dates.expires_utc) - Date.parse(dates.created_utc)) / 86400000;
  assert.ok(days === 90 && Math.abs(Date.parse(dates.created_utc) - Date.now()) < 60000, JSON.stringify(dates));
  for (const name of ['MEMORY.md', 'README.md', 'records.jsonl']) assert.deepEqual(readFileSync(join(out, name)), before[name]);
  assert.deepEqual(Object.fromEntries(readdirSync(env.pack).map((n) => [n, readFileSync(join(env.pack, n))])), before, 'the input pack is untouched');
  assert.deepEqual(leftovers(env.work), []);

  const v = loadPack(out, { trustedKeys: [pubLine(env.key)], strict: true }).verification;
  assert.equal(v.signature.status, 'verified'); assert.equal(v.freshness.status, 'fresh'); assert.equal(v.freshness.authenticated, true);
  assert.match(p.stdout, new RegExp(`^signed 8 records into ${out.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\nkey ${v.signature.fingerprint.replace(/[+/]/g, '\\$&')}; created \\S+Z; expires \\S+Z\\n`));
  assert.ok(p.stdout.endsWith(`\npin this signer on hosts (recommended):\n--trusted-fingerprint ${v.signature.fingerprint}\ntrusted keys line for hosts (rename "signer" as you like):\nsigner ${pubLine(env.key).split(' ').slice(1).join(' ')}\n`), p.stdout);
  for (const f of readdirSync(out)) assert.doesNotMatch(readFileSync(join(out, f), 'latin1'), /PRIVATE KEY/, f);

  // OpenSSH agrees with the hosts.
  writeFileSync(join(env.root, 'allowed'), pubLine(env.key) + '\n');
  const check = spawnSync('ssh-keygen', ['-Y', 'verify', '-f', join(env.root, 'allowed'), '-I', 'publisher', '-n', 'verified-memory-pack-v1', '-s', join(out, 'SHA256SUMS.sig')], { input: readFileSync(join(out, 'SHA256SUMS')), encoding: 'utf8' });
  assert.equal(check.status, 0, check.stderr);

  // The MCP server starts on it with --strict.
  writeFileSync(join(env.root, 'trusted_keys'), pubLine(env.key) + '\n');
  const server = spawnSync(process.execPath, ['dist/index.js', '--pack', out, '--trusted-keys', join(env.root, 'trusted_keys'), '--strict'], {
    input: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'fictional-test', version: '1' } } }) + '\n',
    encoding: 'utf8', timeout: 5000 });
  assert.equal(server.stderr, ''); assert.equal(JSON.parse(server.stdout.split('\n')[0]).result.serverInfo.name, 'verified-memory-mcp');
});

test('--sequence: signed into PACK.json; the server pins the printed fingerprint and gates on the sequence', { skip }, (t) => {
  const env = setup(t), out = join(env.work, 'signed');
  const p = sign(env, ['--pack', env.pack, '--key', env.key, '--expires', '30d', '--sequence', '7', '--out', out]);
  assert.equal(p.status, 0, p.stderr);
  const dates = JSON.parse(readFileSync(join(out, 'PACK.json'), 'utf8'));
  assert.deepEqual(Object.keys(dates), ['format', 'version', 'created_utc', 'expires_utc', 'sequence']); assert.equal(dates.sequence, 7);
  const fp = /^--trusted-fingerprint (SHA256:\S+)$/m.exec(p.stdout)[1];
  assert.match(p.stdout, new RegExp(`^key ${fp.replace(/[+/]/g, '\\$&')}; created \\S+Z; expires \\S+Z; sequence 7$`, 'm'));
  const start = (args) => spawnSync(process.execPath, ['dist/index.js', '--pack', out, ...args], {
    input: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'fictional-test', version: '1' } } }) + '\n',
    encoding: 'utf8', timeout: 5000 });
  const ok = start(['--trusted-fingerprint', fp, '--min-sequence', '7', '--strict']);
  assert.equal(ok.stderr, ''); assert.equal(JSON.parse(ok.stdout.split('\n')[0]).result.serverInfo.name, 'verified-memory-mcp');
  const newer = start(['--trusted-fingerprint', fp, '--min-sequence', '8']);
  assert.equal(newer.status, 1); assert.match(newer.stderr, /pack sequence 7 is lower than the minimum 8/);
  for (const bad of ['-1', '1.5', 'seven', '1e3']) {
    const r = sign(env, ['--pack', env.pack, '--key', env.key, '--expires', '30d', '--sequence', bad, '--out', join(env.work, 'bad')]);
    assert.equal(r.status, 1, bad); assert.match(r.stderr, /--sequence must be a whole number, 0 or more|Usage: /);
    assert.ok(!existsSync(join(env.work, 'bad')));
  }
});

test('re-signing a signed, dated pack replaces its dates and signature', { skip }, (t) => {
  const env = setup(t), first = join(env.work, 'first'), second = join(env.work, 'second');
  assert.equal(sign(env, ['--pack', env.pack, '--key', env.key, '--expires', '2d', '--out', first]).status, 0);
  const p = sign(env, ['--pack', first, '--key', env.key, '--expires', '2030-01-01T00:00:00Z', '--out', second]);
  assert.equal(p.status, 0, p.stderr);
  assert.equal(JSON.parse(readFileSync(join(second, 'PACK.json'), 'utf8')).expires_utc, '2030-01-01T00:00:00Z');
  assert.equal(loadPack(second, { trustedKeys: [pubLine(env.key)], strict: true }).verification.freshness.status, 'fresh');
});

test('wrong passphrase: ssh-keygen fails and nothing is written', { skip: skip || (askpassWorks ? false : 'Windows OpenSSH did not read SSH_ASKPASS in CI') }, (t) => {
  const env = setup(t, { passphrase: 'a different fictional passphrase' }), out = join(env.work, 'signed');
  const p = sign(env, ['--pack', env.pack, '--key', env.key, '--expires', '90d', '--out', out]);
  assert.equal(p.status, 1); assert.match(p.stderr, /verified-memory-sign-pack: ssh-keygen -Y sign failed \(nothing was written\)\n$/);
  assert.ok(!existsSync(out)); assert.deepEqual(leftovers(env.work), []);
});

test('refuses bad input before signing, writing nothing', { skip }, (t) => {
  const env = setup(t), out = join(env.work, 'signed');
  const tampered = join(env.root, 'tampered'); cpSync(env.pack, tampered, { recursive: true }); writeFileSync(join(tampered, 'README.md'), 'tampered');
  mkdirSync(join(env.work, 'exists'));
  const rsa = setup(t, { type: 'rsa' });
  const base = ['--pack', env.pack, '--key', env.key, '--expires', '90d', '--out', out];
  const withArg = (flag, value) => { const a = [...base]; a[a.indexOf(flag) + 1] = value; return a; };
  for (const [args, message, who = env] of [
    [[], /^verified-memory-sign-pack: Usage: /],
    [base.slice(0, 6), /Usage: /],
    [[...base, '--extra', 'x'], /Usage: /],
    [withArg('--expires', '0d'), /--expires must be a number of days/],
    [withArg('--expires', 'tomorrow'), /--expires must be a number of days/],
    [withArg('--expires', '2027-01-01'), /--expires must be a number of days/],
    [withArg('--expires', '2020-01-01T00:00:00Z'), /--expires must be in the future/],
    [withArg('--expires', '1826d'), /at most 1825 days away/],
    [withArg('--out', join(env.work, 'exists')), /--out already exists/],
    [withArg('--out', join(env.root, 'no', 'such', 'dir')), /parent directory does not exist/],
    [withArg('--key', join(env.root, 'missing-key')), /cannot read the public key/],
    [withArg('--pack', tampered), /verifier rejected the pack: verified-memory: checksum mismatch: README\.md/],
    [['--pack', rsa.pack, '--key', rsa.key, '--expires', '90d', '--out', join(rsa.work, 'signed')], /must be an ssh-ed25519 key/, rsa]
  ]) {
    const p = sign(who, args);
    assert.equal(p.status, 1, args.join(' ')); assert.match(p.stderr, message); assert.equal(p.stdout, '');
  }
  assert.ok(!existsSync(out)); assert.deepEqual(leftovers(env.work), []);
});

test('sign-pack is not in the npm package and is not an installed command', () => {
  const pkg = JSON.parse(readFileSync('package.json', 'utf8'));
  assert.ok(!Object.values(pkg.bin).some((p) => p.includes('sign')));
  const files = JSON.parse(spawnSync('npm', ['pack', '--dry-run', '--json', '--ignore-scripts'], { encoding: 'utf8', shell: process.platform === 'win32' }).stdout)[0].files.map((f) => f.path);
  assert.ok(files.includes('tools/build-pack.mjs') && !files.some((f) => /sign/.test(f)), files.join(', '));
});
