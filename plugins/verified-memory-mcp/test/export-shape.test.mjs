import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawnSync } from 'node:child_process';
import { deflateRawSync } from 'node:zlib';
const permissionFlag = process.allowedNodeEnvironmentFlags.has('--permission') ? '--permission' : '--experimental-permission';

// Invented export shapes. Every string, ID, date and number below is a canary that must not appear in the output.
const CANARIES = ['Larkfield', 'tomato beds', 'Rowan Ashby', 'Seed swap plans', 'notes-from-rowan.txt', 'secret-garden-photo.png',
  'a1b2c3d4-0000-4000-8000-00000000c0de', 'node-root', '1767000123.25', '1767000123', '2026-03-02T08:15:00', 'rowan@example.invalid', 'shed code 4471', '4471'];
const chatgpt = [{
  title: 'Seed swap plans', create_time: 1767000123.25, update_time: null, id: 'a1b2c3d4-0000-4000-8000-00000000c0de', current_node: 'a1b2c3d4-0000-4000-8000-00000000c0de',
  mapping: {
    'node-root': { id: 'node-root', message: null, parent: null, children: ['a1b2c3d4-0000-4000-8000-00000000c0de'] },
    'a1b2c3d4-0000-4000-8000-00000000c0de': { id: 'a1b2c3d4-0000-4000-8000-00000000c0de', parent: 'node-root', children: [], message: {
      author: { role: 'user', name: 'Rowan Ashby', metadata: {} }, create_time: 1767000123, status: 'finished_successfully', recipient: 'all',
      content: { content_type: 'multimodal_text', parts: ['I look after the tomato beds at Larkfield. The shed code 4471.', { content_type: 'image_asset_pointer', asset_pointer: 'file-service://secret-garden-photo.png', width: 4471 }] },
      metadata: { attachments: [{ name: 'notes-from-rowan.txt', mime_type: 'text/plain' }], model_slug: 'Rowan Ashby' } } }
  }
}];
// A map keyed by many identifier-looking data keys must collapse entirely.
const people = Object.fromEntries(Array.from({ length: 70 }, (_, i) => [`neighbour_${i}_larkfield`, i]));
const claude = [{ uuid: 'a1b2c3d4-0000-4000-8000-00000000c0de', name: 'Seed swap plans', created_at: '2026-03-02T08:15:00.123456Z', people,
  chat_messages: [{ uuid: 'a1b2c3d4-0000-4000-8000-00000000c0de', sender: 'human', created_at: '2026-03-02T08:15:00+00:00', text: 'tomato beds',
    content: [{ type: 'text', text: 'tomato beds at Larkfield' }], attachments: [{ file_name: 'notes-from-rowan.txt', extracted_content: 'shed code 4471' }] }] }];
const users = { email_address: 'rowan@example.invalid', full_name: 'Rowan Ashby' };

function crc32(buf) { let c, crc = ~0; for (const b of buf) { c = (crc ^ b) & 0xff; for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1; crc = (crc >>> 8) ^ c; } return ~crc >>> 0; }
function zip(files) {
  const locals = [], centrals = []; let offset = 0;
  for (const [name, text] of Object.entries(files)) {
    const raw = Buffer.from(text), data = deflateRawSync(raw), n = Buffer.from(name);
    const h = Buffer.alloc(30); h.writeUInt32LE(0x04034b50, 0); h.writeUInt16LE(20, 4); h.writeUInt16LE(8, 8); h.writeUInt32LE(crc32(raw), 14); h.writeUInt32LE(data.length, 18); h.writeUInt32LE(raw.length, 22); h.writeUInt16LE(n.length, 26);
    const c = Buffer.alloc(46); c.writeUInt32LE(0x02014b50, 0); c.writeUInt16LE(20, 4); c.writeUInt16LE(20, 6); c.writeUInt16LE(8, 10); c.writeUInt32LE(crc32(raw), 16); c.writeUInt32LE(data.length, 20); c.writeUInt32LE(raw.length, 24); c.writeUInt16LE(n.length, 28); c.writeUInt32LE(offset, 42);
    locals.push(h, n, data); centrals.push(c, n); offset += h.length + n.length + data.length;
  }
  const cd = Buffer.concat(centrals), e = Buffer.alloc(22); e.writeUInt32LE(0x06054b50, 0); e.writeUInt16LE(centrals.length / 2, 8); e.writeUInt16LE(centrals.length / 2, 10); e.writeUInt32LE(cd.length, 12); e.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, cd, e]);
}
function shape(t, target, root) {
  const p = spawnSync(process.execPath, [permissionFlag, `--allow-fs-read=${resolve('tools')}`, `--allow-fs-read=${root}`, 'tools/export-shape.mjs', target], { encoding: 'utf8', timeout: 10000 });
  assert.equal(p.status, 0, p.stderr);
  for (const canary of CANARIES) assert.equal(p.stdout.includes(canary), false, `output leaked ${canary}`);
  return p.stdout;
}
function workdir(t) { const root = mkdtempSync(join(tmpdir(), 'export-shape-test-')); t.after(() => rmSync(root, { recursive: true, force: true })); return root; }

test('export-shape prints structure and enum tokens but none of the invented export content', (t) => {
  const root = workdir(t);
  const files = { 'conversations.json': JSON.stringify(chatgpt), 'user.json': JSON.stringify(users), 'secret-garden-photo.png': 'png', 'Rowan Ashby/notes-from-rowan.json': '{}' };
  writeFileSync(join(root, 'export.zip'), zip(files));
  const out = shape(t, join(root, 'export.zip'), root);
  assert.match(out, /4 files; by extension: \.json×3, \.png×1/);
  assert.match(out, /== conversations\.json/);
  assert.match(out, /\(json file 1, name hidden\)/);
  assert.match(out, /\$\[\]\.mapping\.\{\*\}\.message\.author\.role  string×1 .*values: user×1/);
  assert.match(out, /\.content\.content_type  string×1 .*values: multimodal_text×1/);
  assert.match(out, /\.content\.parts\[\]  string×1  object×1/);
  assert.match(out, /\.metadata\.model_slug  string×1 .*values: <not a short token>×1/);
  assert.match(out, /\$\[\]\.create_time  float×1/);
});

test('export-shape reads a folder and a single JSON file, collapsing maps keyed by data', (t) => {
  const root = workdir(t);
  mkdirSync(join(root, 'export'));
  writeFileSync(join(root, 'export', 'conversations.json'), JSON.stringify(claude));
  writeFileSync(join(root, 'export', 'users.json'), JSON.stringify([users]));
  const out = shape(t, join(root, 'export'), root);
  assert.match(out, /\$\[\]\.chat_messages\[\]\.sender  string×1 .*values: human×1/);
  assert.match(out, /\$\[\]\.chat_messages\[\]\.created_at  string×1  kind: iso-offset×1/);
  assert.match(out, /\$\[\]\.people  object×1  \(64\+ distinct keys collapsed to \{\*\}\)/);
  assert.doesNotMatch(out, /neighbour_/);
  assert.match(shape(t, join(root, 'export', 'conversations.json'), root), /== input\.json/);
});

test('export-shape hides invalid JSON details and refuses bad input', (t) => {
  const root = workdir(t);
  writeFileSync(join(root, 'conversations.json'), '{"title": "Seed swap plans", tomato beds');
  assert.match(shape(t, join(root, 'conversations.json'), root), /could not parse: invalid JSON/);
  writeFileSync(join(root, 'bad.zip'), 'Larkfield');
  const p = spawnSync(process.execPath, ['tools/export-shape.mjs', join(root, 'bad.zip')], { encoding: 'utf8' });
  assert.equal(p.status, 1); assert.match(p.stderr, /not a zip file/);
});
