import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { buildRecords, parseMessages, renderPack, sha256 } from '../tools/pack-core.mjs';
import { verifyPackEntries } from '../dist/verify.js';
const input = resolve('examples/input');
const committed = resolve('examples/pack');
const FILES = ['MEMORY.md', 'README.md', 'SHA256SUMS', 'records.jsonl'];
const options = { title: 'Larkfield garden example pack', description: 'Invented example data for verified-memory-mcp. Not a real person or conversation.' };

async function buildInMemory() {
  const messagesBytes = readFileSync(join(input, 'messages.jsonl')), recordsBytes = readFileSync(join(input, 'records.jsonl'));
  const records = await buildRecords(recordsBytes, parseMessages(messagesBytes));
  return renderPack({ records, messagesBytes, recordsBytes, ...options });
}

test('pack core and the copied verifier have no imports, so a browser can load them', () => {
  for (const file of ['tools/pack-core.mjs', 'dist/verify.js']) assert.doesNotMatch(readFileSync(file, 'utf8'), /^\s*import\b|\brequire\(|\bimport\(/m, file);
  assert.deepEqual(readFileSync('src/verify.ts'), readFileSync('../verified-memory/src/verify.ts'));
});

test('pack core builds the committed example pack in memory, byte for byte', async () => {
  const files = await buildInMemory();
  assert.deepEqual(Object.keys(files).sort(), FILES);
  for (const f of FILES) assert.deepEqual(Buffer.from(files[f], 'utf8'), readFileSync(join(committed, f)), f);
});

test('in-memory pack passes the pure verifier with Web Crypto hashes, as a browser would run it', async () => {
  const files = await buildInMemory();
  const bytes = Object.fromEntries(Object.entries(files).map(([n, s]) => [n, new TextEncoder().encode(s)]));
  const digests = new Map();
  for (const b of Object.values(bytes)) digests.set(b, await sha256(b));
  const { records } = verifyPackEntries(Object.keys(bytes), n => bytes[n], b => digests.get(b));
  assert.equal(records.size, 4);
});
