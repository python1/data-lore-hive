#!/usr/bin/env node
import { existsSync } from 'node:fs';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { createServer } from './server.js';
import { readRevokedKeys, readTrustedKeys } from './pack.js';

const USAGE = 'Usage: verified-memory-mcp [--pack /absolute/path/to/pack] [--trusted-keys /absolute/path/to/trusted_keys] [--trusted-fingerprint SHA256:…]… [--revoked-keys /absolute/path/to/revoked_keys] [--min-sequence N] [--require-signature] [--strict]';
// Accepts `--flag value` and the registry's `--flag=value` form. --require-signature and
// --strict are switches, optionally given as =true/=false (or a following true/false) by
// registry clients. --strict implies --require-signature and also enforces freshness.
// --trusted-fingerprint may be repeated, and one value may hold several fingerprints
// separated by commas or spaces (Claude Desktop passes one text setting).
function parseArgs(args: string[]) {
  const opts: { pack?: string; trustedKeys?: string; revokedKeys?: string; minSequence?: string; trustedFingerprints?: string[]; requireSignature?: boolean; strict?: boolean } = {};
  for (let i = 0; i < args.length; i++) {
    const [flag, inline] = args[i].includes('=') ? [args[i].slice(0, args[i].indexOf('=')), args[i].slice(args[i].indexOf('=') + 1)] : [args[i], undefined];
    if (flag === '--strict' || flag === '--require-signature') {
      const name = flag === '--strict' ? 'strict' : 'requireSignature';
      if (opts[name] !== undefined) throw new Error(USAGE);
      const value = inline ?? (args[i + 1] === 'true' || args[i + 1] === 'false' ? args[++i] : 'true');
      if (value !== 'true' && value !== 'false') throw new Error(USAGE);
      opts[name] = value === 'true';
      continue;
    }
    // An empty `--flag=` means the setting is off: Claude Desktop passes the bundle's optional
    // settings this way when the user leaves them blank.
    if (['--trusted-keys', '--trusted-fingerprint', '--revoked-keys', '--min-sequence'].includes(flag) && inline === '') continue;
    if (flag === '--trusted-fingerprint') {
      const value = inline ?? args[++i];
      if (!value || value.startsWith('--')) throw new Error(USAGE);
      (opts.trustedFingerprints ??= []).push(...value.split(/[\s,]+/).filter(Boolean));
      continue;
    }
    const key = flag === '--pack' ? 'pack' : flag === '--trusted-keys' ? 'trustedKeys' : flag === '--revoked-keys' ? 'revokedKeys' : flag === '--min-sequence' ? 'minSequence' : undefined;
    const value = inline ?? args[++i];
    if (!key || opts[key] !== undefined || !value || value.startsWith('--')) throw new Error(USAGE);
    opts[key] = value;
  }
  return opts;
}

try {
  const opts = parseArgs(process.argv.slice(2));
  // The npm package ships no pack; only a repository build has the fictional sample.
  if (opts.pack === undefined && !existsSync(new URL('../sample-pack/', import.meta.url))) {
    throw new Error('Usage: verified-memory-mcp --pack /absolute/path/to/pack (no bundled sample pack in this install)');
  }
  if (opts.minSequence !== undefined && !/^\d{1,15}$/.test(opts.minSequence)) throw new Error('verified-memory: --min-sequence must be a whole number, 0 or more');
  const minSequence = opts.minSequence === undefined ? undefined : Number(opts.minSequence);
  const trustedKeys = opts.trustedKeys === undefined ? undefined : readTrustedKeys(opts.trustedKeys);
  const revokedKeys = opts.revokedKeys === undefined ? undefined : readRevokedKeys(opts.revokedKeys);
  // A stale or future-dated pack still loads outside --strict; say so once on stderr (never stdout).
  const server = createServer(opts.pack, { trustedKeys, trustedFingerprints: opts.trustedFingerprints, revokedKeys, minSequence, requireSignature: opts.requireSignature, strict: opts.strict },
    warning => process.stderr.write(`verified-memory-mcp: ${warning}\n`));
  // No transport connection (and no stdout) until verification succeeds.
  await server.connect(new StdioServerTransport());
} catch (error) {
  // Do not leak configured paths or raw malformed record contents.
  const message = error instanceof Error && (error.message.startsWith('verified-memory:') || error.message.startsWith('Usage:'))
    ? error.message.replace(/set plugins\.entries\.verified-memory\.config\.packPath.*$/, 'use --pack with an existing absolute pack directory')
    : 'pack verification or startup failed';
  process.stderr.write(`verified-memory-mcp: ${message}\n`);
  process.exitCode = 1;
}
