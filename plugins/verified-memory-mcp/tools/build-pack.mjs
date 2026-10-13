#!/usr/bin/env node
// Offline pack builder: plain messages + quoted records in, verified four-file pack out.
// Computes hashes and offsets itself, refuses any quote that is not verbatim in its
// message, and only renames the pack into place after the server's own verifier loads it.
// The MCP server never runs this; it is the only part of the package that writes files.
import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { basename, dirname, isAbsolute, join, resolve } from 'node:path';
import { InputError, buildRecords, check, parseMessages, renderPack } from './pack-core.mjs';

const USAGE = 'Usage: verified-memory-build-pack --messages messages.jsonl --records records.jsonl --out NEW_DIR [--title TEXT] [--description TEXT]';

function parseArgs(argv) {
  const known = new Set(['--messages', '--records', '--out', '--title', '--description']);
  const opts = {};
  for (let i = 0; i < argv.length; i += 2) {
    check(known.has(argv[i]) && argv[i + 1] !== undefined && !(argv[i].slice(2) in opts), USAGE);
    opts[argv[i].slice(2)] = argv[i + 1];
  }
  check(opts.messages && opts.records && opts.out, USAGE);
  return opts;
}

function readInput(path, label) {
  try { return readFileSync(path); } catch { throw new InputError(`${label}: cannot read file`); }
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const out = resolve(opts.out);
  check(!existsSync(out), `--out already exists; choose a new directory (nothing was written)`);
  check(existsSync(dirname(out)), `--out parent directory does not exist`);
  const messagesBytes = readInput(opts.messages, 'messages');
  const messages = parseMessages(messagesBytes);
  const recordsBytes = readInput(opts.records, 'records');
  const records = await buildRecords(recordsBytes, messages);
  const files = await renderPack({ records, messagesBytes, recordsBytes, title: opts.title, description: opts.description });

  // Stage beside the target, verify with the server's own loader, then rename into place.
  const staging = join(dirname(out), `.${basename(out)}.building-${process.pid}`);
  mkdirSync(staging);
  try {
    for (const [name, content] of Object.entries(files)) writeFileSync(join(staging, name), content, { flag: 'wx' });
    const { loadPack } = await import(new URL('../dist/pack.js', import.meta.url));
    const pack = loadPack(isAbsolute(staging) ? staging : resolve(staging));
    check(pack.verification.records === records.length, 'verifier record count mismatch');
    renameSync(staging, out);
  } catch (error) {
    rmSync(staging, { recursive: true, force: true });
    throw error;
  }
  process.stdout.write(`wrote ${records.length} records to ${out}\nrun: verified-memory-mcp --pack ${out}\n`
    + `optional, to sign it with your own ssh key: ssh-keygen -Y sign -f ~/.ssh/YOUR_KEY -n verified-memory-pack-v1 ${join(out, 'SHA256SUMS')}\n`);
}

main().catch((error) => {
  const message = error instanceof InputError ? error.message
    : error instanceof Error && error.message.startsWith('verified-memory:') ? `verifier rejected the pack: ${error.message}`
    : error?.code === 'ERR_MODULE_NOT_FOUND' ? 'dist/pack.js missing; run npm run build first'
    : `failed: ${error instanceof Error ? error.message : String(error)}`;
  process.stderr.write(`verified-memory-build-pack: ${message}\n`);
  process.exitCode = 1;
});
