import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { blobSource, bytesSource, crc32, isZip, openZip, readEntry, writeZip, ZipError } from '../src/zip.mjs';
import { nodeZip } from './helpers.mjs';

const FILES = { 'conversations.json': '[{"title":"Larkfield 🌱 café"}]', 'folder/notes.txt': 'water early\n'.repeat(500), 'empty.txt': '' };
const text = (b) => new TextDecoder().decode(b);
async function readAll(bytes, options) {
  const source = bytesSource(bytes);
  const out = {};
  for (const e of await openZip(source)) out[e.name] = text(await readEntry(source, e, options?.max));
  return out;
}

test('crc32 matches the standard check value', () => {
  assert.equal(crc32(new TextEncoder().encode('123456789')), 0xcbf43926);
});

test('reads deflate, stored and zip64 archives built by an independent writer', async () => {
  for (const options of [{}, { method: 0 }, { zip64: true }, { zip64: true, method: 0 }]) {
    assert.deepEqual(await readAll(nodeZip(FILES, options)), FILES, JSON.stringify(options));
  }
});

test('reads an archive made by the system zip tool when one is installed', async (t) => {
  if (spawnSync('zip', ['-v']).status !== 0) return t.skip('zip not installed');
  const root = mkdtempSync(join(tmpdir(), 'zip-test-'));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  for (const [name, content] of Object.entries(FILES)) { spawnSync('mkdir', ['-p', join(root, 'in', name, '..')]); writeFileSync(join(root, 'in', name), content); }
  assert.equal(spawnSync('zip', ['-q', '-r', '-X', join(root, 'out.zip'), '.'], { cwd: join(root, 'in') }).status, 0);
  const got = await readAll(readFileSync(join(root, 'out.zip')));
  for (const [name, content] of Object.entries(FILES)) assert.equal(got[name], content, name);
});

test('writer output is deterministic and round-trips, including UTF-8 names', async () => {
  const files = Object.entries({ ...FILES, 'pack/Mémoire 🌱.md': 'x' }).map(([name, s]) => ({ name, data: new TextEncoder().encode(s) }));
  const a = writeZip(files), b = writeZip(files);
  assert.deepEqual(a, b);
  const got = await readAll(a);
  assert.deepEqual(Object.keys(got), files.map((f) => f.name));
  assert.equal(got['pack/Mémoire 🌱.md'], 'x');
  assert.equal(await isZip(bytesSource(a)), true);
  assert.equal(await isZip(bytesSource(new TextEncoder().encode('[{}]'))), false);
});

test('blob source reads only the central directory and the entry asked for', async () => {
  const big = { 'media/photo.png': Buffer.alloc(2_000_000, 7), 'conversations.json': '[]' };
  const blob = new Blob([nodeZip(big, { method: 0 })]);
  const source = blobSource(blob);
  let read = 0;
  const counting = { size: source.size, read: async (o, l) => { read += l; return source.read(o, l); } };
  const entry = (await openZip(counting)).find((e) => e.name === 'conversations.json');
  assert.equal(text(await readEntry(counting, entry)), '[]');
  assert.ok(read < 70_000 + 200, `read ${read} bytes of ${blob.size}`);
});

test('refuses damaged, encrypted, oversized and unsupported entries with clear errors', async () => {
  const good = nodeZip({ 'a.txt': 'hello hello hello' });
  const damaged = Buffer.from(good); damaged[40] ^= 0xff;
  const source = (b) => bytesSource(b);
  const first = async (b) => (await openZip(source(b)))[0];
  await assert.rejects(readEntry(source(damaged), await first(damaged)), /a\.txt: (CRC or size mismatch|corrupt compressed data)/);
  const encrypted = nodeZip({ 'a.txt': 'x' }, { flags: 1, method: 0 });
  await assert.rejects(readEntry(source(encrypted), await first(encrypted)), /encrypted zip entries are not supported/);
  await assert.rejects(readEntry(source(good), await first(good), 3), /too large to open in a browser/);
  const bzip = nodeZip({ 'a.txt': 'x' }, { method: 0 }); bzip.writeUInt16LE(12, bzip.indexOf(Buffer.from([0x50, 0x4b, 1, 2])) + 10);
  await assert.rejects(readEntry(source(bzip), await first(bzip)), /unsupported compression method 12/);
  await assert.rejects(openZip(source(Buffer.from('not a zip at all, just text'))), (e) => e instanceof ZipError && /not a zip file/.test(e.message));
  await assert.rejects(openZip(source(good.subarray(20))), ZipError);
});
