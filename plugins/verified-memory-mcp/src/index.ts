#!/usr/bin/env node
import { existsSync } from 'node:fs';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { createServer } from './server.js';

try {
  const args = process.argv.slice(2);
  if (args.length !== 0 && (args.length !== 2 || args[0] !== '--pack' || !args[1])) {
    throw new Error('Usage: verified-memory-mcp [--pack /absolute/path/to/pack]');
  }
  // The npm package ships no pack; only a repository build has the fictional sample.
  if (args.length === 0 && !existsSync(new URL('../sample-pack/', import.meta.url))) {
    throw new Error('Usage: verified-memory-mcp --pack /absolute/path/to/pack (no bundled sample pack in this install)');
  }
  const server = createServer(args[1]);
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
