#!/usr/bin/env node
// Pack signer, for the signing machine only. Copies a verified pack to a new folder, adds
// PACK.json (created now, expiring when asked, with the sequence number if given), re-seals
// SHA256SUMS, and has ssh-keygen sign
// SHA256SUMS. This script never opens the private key: ssh-keygen reads it and asks for its
// passphrase (or uses ssh-agent). The result must pass the hosts' own loader in strict mode,
// trusting only KEY.pub, before it is renamed into place.
// Not in the npm package: run it from a checkout, after npm ci && npm run build.
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { basename, dirname, join, resolve } from 'node:path';

const USAGE = 'Usage: node tools/sign-pack.mjs --pack DIR --key ~/.ssh/KEY --expires 90d|2027-01-31T00:00:00Z [--sequence N] --out NEW_DIR';
const NAMESPACE = 'verified-memory-pack-v1';
const MAX_DAYS = 1825;
const DAY = 24 * 60 * 60 * 1000;
class InputError extends Error {}
const check = (ok, message) => { if (!ok) throw new InputError(message); };

function parseArgs(argv) {
  const known = new Set(['--pack', '--key', '--expires', '--sequence', '--out']);
  const opts = {};
  for (let i = 0; i < argv.length; i += 2) {
    check(known.has(argv[i]) && argv[i + 1] !== undefined && !argv[i + 1].startsWith('--') && !(argv[i].slice(2) in opts), USAGE);
    opts[argv[i].slice(2)] = argv[i + 1];
  }
  check(opts.pack && opts.key && opts.expires && opts.out, USAGE);
  check(opts.sequence === undefined || /^\d{1,15}$/.test(opts.sequence), '--sequence must be a whole number, 0 or more; raise it with every pack you publish');
  return opts;
}

/** "90d" or an exact UTC time -> ms; must be in the future and at most MAX_DAYS away. */
function expiry(value, now) {
  const days = /^([1-9]\d{0,3})d$/.exec(value);
  const at = days ? now + Number(days[1]) * DAY : /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$/.test(value) ? Date.parse(value) : NaN;
  check(Number.isFinite(at), '--expires must be a number of days such as 90d, or a UTC time such as 2027-01-31T00:00:00Z');
  check(at > now, '--expires must be in the future');
  check(at <= now + MAX_DAYS * DAY, `--expires must be at most ${MAX_DAYS} days away`);
  return at;
}
const iso = (ms) => new Date(Math.floor(ms / 1000) * 1000).toISOString().replace('.000Z', 'Z');
const sha256 = (bytes) => createHash('sha256').update(bytes).digest('hex');
const home = (path) => (path === '~' || path.startsWith('~/') ? join(homedir(), path.slice(1)) : path);

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const now = Date.now();
  const expires = expiry(opts.expires, now);
  const source = resolve(home(opts.pack)), out = resolve(home(opts.out)), key = resolve(home(opts.key));
  check(!existsSync(out), '--out already exists; choose a new directory (nothing was written)');
  check(existsSync(dirname(out)), '--out parent directory does not exist');

  // Only the public half is read here; ssh-keygen alone touches the private key.
  const pubPath = key.endsWith('.pub') ? key : `${key}.pub`;
  let pub;
  try { pub = readFileSync(pubPath, 'utf8').trim().split(/\s+/); } catch { throw new InputError(`cannot read the public key ${pubPath}; it must sit next to the private key`); }
  check(pub[0] === 'ssh-ed25519' && pub[1], 'the key must be an ssh-ed25519 key');
  const trustLine = `signer ssh-ed25519 ${pub[1]}`;

  const { loadPack } = await import(new URL('../dist/pack.js', import.meta.url));
  // The input must already pass, signed or not; an existing signature and PACK.json are replaced.
  const before = loadPack(source).verification;

  const staging = join(dirname(out), `.${basename(out)}.signing-${process.pid}`);
  mkdirSync(staging);
  try {
    const files = {};
    for (const name of ['MEMORY.md', 'README.md', 'records.jsonl']) files[name] = readFileSync(join(source, name));
    const sequence = opts.sequence === undefined ? undefined : Number(opts.sequence);
    files['PACK.json'] = Buffer.from(JSON.stringify({ format: 'verified-memory-pack', version: 2, created_utc: iso(now), expires_utc: iso(expires), sequence }, null, 2) + '\n');
    for (const [name, bytes] of Object.entries(files)) writeFileSync(join(staging, name), bytes, { flag: 'wx' });
    writeFileSync(join(staging, 'SHA256SUMS'), Object.keys(files).sort().map((name) => `${sha256(files[name])}  ${name}\n`).join(''), { flag: 'wx' });

    // Inherit the terminal so ssh-keygen can ask for the passphrase itself.
    const signed = spawnSync('ssh-keygen', ['-Y', 'sign', '-f', key, '-n', NAMESPACE, join(staging, 'SHA256SUMS')], { stdio: 'inherit' });
    check(!signed.error, 'ssh-keygen not found; install OpenSSH 8.1 or later (nothing was written)');
    check(signed.status === 0, 'ssh-keygen -Y sign failed (nothing was written)');

    const after = loadPack(staging, { trustedKeys: [trustLine], strict: true, minSequence: sequence }).verification;
    check(after.records === before.records && after.signature.status === 'verified' && after.freshness.status === 'fresh' && after.freshness.sequence === sequence, 'the signed pack did not verify (nothing was written)');
    renameSync(staging, out);
    process.stdout.write(`signed ${after.records} records into ${out}\n`
      + `key ${after.signature.fingerprint}; created ${after.freshness.created_utc}; expires ${after.freshness.expires_utc}${sequence === undefined ? '' : `; sequence ${sequence}`}\n`
      + `pin this signer on hosts (recommended):\n--trusted-fingerprint ${after.signature.fingerprint}\n`
      + `trusted keys line for hosts (rename "signer" as you like):\n${trustLine}\n`);
  } catch (error) {
    rmSync(staging, { recursive: true, force: true });
    throw error;
  }
}

main().catch((error) => {
  const message = error instanceof InputError ? error.message
    : error instanceof Error && error.message.startsWith('verified-memory:') ? `verifier rejected the pack: ${error.message}`
    : error?.code === 'ERR_MODULE_NOT_FOUND' ? 'dist/pack.js missing; run npm run build first'
    : `failed: ${error instanceof Error ? error.message : String(error)}`;
  process.stderr.write(`verified-memory-sign-pack: ${message}\n`);
  process.exitCode = 1;
});
