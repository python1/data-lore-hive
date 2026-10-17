import test from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import vm from 'node:vm';
import { bundle, buildPage } from '../build.mjs';

const html = buildPage();
const scriptBodies = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const styleBodies = [...html.matchAll(/<style>([\s\S]*?)<\/style>/g)].map((m) => m[1]);
const csp = /http-equiv="Content-Security-Policy" content="([^"]*)"/.exec(html)[1];
const hash = (s) => `'sha256-${createHash('sha256').update(s, 'utf8').digest('base64')}'`;

// The one URL allowed in the page: a plain link to the Claude Desktop add-on. It loads nothing
// into the page; only a click navigates, and the page sends no referrer.
const DESKTOP_DOWNLOAD = 'https://github.com/python1/data-lore-hive/releases/download/verified-memory-v0.4.0/verified-memory-0.4.0.mcpb';

test('page is self-contained: no external URLs but the add-on link, one inline script and style, both pinned by CSP hash', () => {
  assert.equal(html.split(DESKTOP_DOWNLOAD).length - 1, 1);
  assert.ok(html.includes(`<a id="desktop-download" href="${DESKTOP_DOWNLOAD}" rel="noopener noreferrer">`));
  assert.match(html, /<meta name="referrer" content="no-referrer">/);
  assert.doesNotMatch(html.replace(DESKTOP_DOWNLOAD, ''), /https?:\/\/|\bsrc=|<link (?!rel="icon" href="data:,")/);
  assert.equal(scriptBodies.length, 1); assert.equal(styleBodies.length, 1);
  const directives = Object.fromEntries(csp.split(';').map((d) => d.trim().split(/\s+/)).map(([k, ...v]) => [k, v.join(' ')]));
  assert.deepEqual(directives, {
    'default-src': "'none'", 'script-src': hash(scriptBodies[0]), 'style-src': hash(styleBodies[0]), 'worker-src': 'blob:', 'img-src': 'data:',
    'connect-src': "'none'", 'form-action': "'none'", 'base-uri': "'none'", 'object-src': "'none'"
  });
  assert.doesNotMatch(html, /\sstyle="/, 'inline style attributes would be blocked by the CSP');
  assert.doesNotMatch(scriptBodies[0], /\binnerHTML\b|\bouterHTML\b|insertAdjacentHTML|document\.write|\beval\(|new Function/);
  assert.doesNotMatch(scriptBodies[0], /\bfetch\(|XMLHttpRequest|WebSocket|EventSource|sendBeacon|localStorage|sessionStorage|indexedDB/);
});

test('bundler refuses import and export forms it does not understand', (t) => {
  const dir = mkdtempSync(join(tmpdir(), 'bundle-test-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  for (const [line, pattern] of [["export default 1;", /unsupported import\/export form/], ["import x from './y.mjs';", /unsupported import\/export form/],
    ["const m = import('./y.mjs');", /unsupported import\/export form/], ["export { a as b };", /unsupported export form/]]) {
    writeFileSync(join(dir, 'entry.mjs'), `const a = 1;\n${line}\n`);
    assert.throws(() => bundle(join(dir, 'entry.mjs')), pattern, line);
  }
  writeFileSync(join(dir, 'a.mjs'), "import { b } from './b.mjs';\nexport const a = 1;\n");
  writeFileSync(join(dir, 'b.mjs'), "import { a } from './a.mjs';\nexport const b = 2;\n");
  assert.throws(() => bundle(join(dir, 'a.mjs')), /import cycle/);
});

// Run the real modules through the bundler and the golden pipeline inside a bare VM context,
// so the bundled code (not just the source modules) is shown to build the golden pack.
test('bundled modules build the golden ChatGPT pack in a bare context', async (t) => {
  const dir = mkdtempSync(join(resolve('src'), '.bundle-test-'));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  writeFileSync(join(dir, 'entry.mjs'), [
    "import { loadExport } from '../load-export.mjs';",
    "import { bytesSource } from '../zip.mjs';",
    "import { buildPack } from '../pack-inputs.mjs';",
    "import { makeQuote } from '../ui-logic.mjs';",
    "import { verifyPackEntries } from '../../../dist/verify.js';",
    'globalThis.run = async (bytes) => {',
    "  const data = await loadExport({ name: 'conversations.json', source: bytesSource(bytes) });",
    '  const messages = new Map(data.conversations.flatMap((c) => c.messages.map((m) => [m.key, m])));',
    "  const m = [...messages.values()].find((x) => x.text.startsWith('Morning!'));",
    "  const at = m.text.indexOf('I look after');",
    "  const q = makeQuote(m, at - 1, m.text.indexOf('garden.') + 7);",
    "  const records = [{ record_id: 'M-role', role: 'user', topic: 'Role', category: 'profile', quotes: [q] }];",
    "  const built = await buildPack({ messages, records, speakers: { user: 'Rowan', agent: 'ChatGPT' }, title: 'T' });",
    '  return built.files;',
    '};'
  ].join('\n'));
  const context = vm.createContext({ TextEncoder, TextDecoder, crypto: globalThis.crypto, Blob, Response, DecompressionStream, Uint8Array, DataView, console });
  vm.runInContext(bundle(join(dir, 'entry.mjs')), context);
  const files = await context.run(new Uint8Array(readFileSync(resolve('test/fixtures/chatgpt-conversations.json'))));
  assert.match(files['records.jsonl'], /"quote":"I look after the tomato beds at the Larkfield community garden\.","start":9,"end":72/);
  assert.equal(files.SHA256SUMS.split('\n').filter(Boolean).length, 3);
});
