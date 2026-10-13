#!/usr/bin/env node
import { existsSync } from 'node:fs';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { createServer } from './server.js';
import { readTrustedKeys } from './pack.js';

const USAGE = 'Usage: verified-memory-mcp [--pack /absolute/path/to/pack] [--trusted-keys /absolute/path/to/trusted_keys] [--require-signature] [--strict]';
// Accepts `--flag value` and the registry's `--flag=value` form. --require-signature and
// --strict are switches, optionally given as =true/=false (or a following true/false) by
// registry clients. --strict implies --require-signature and also enforces freshness.
function parseArgs(args: string[]) {
  const opts: { pack?: string; trustedKeys?: string; requireSignature?: boolean; strict?: boolean } = {};
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
    // An empty `--trusted-keys=` means no keys file: Claude Desktop passes the bundle's
    // optional file setting this way when the user leaves it blank.
    if (flag === '--trusted-keys' && inline === '') continue;
    const key = flag === '--pack' ? 'pack' : flag === '--trusted-keys' ? 'trustedKeys' : undefined;
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
  const trustedKeys = opts.trustedKeys === undefined ? undefined : readTrustedKeys(opts.trustedKeys);
  // A stale or future-dated pack still loads outside --strict; say so once on stderr (never stdout).
  const server = createServer(opts.pack, { trustedKeys, requireSignature: opts.requireSignature, strict: opts.strict }, warning => process.stderr.write(`verified-memory-mcp: ${warning}\n`));
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
