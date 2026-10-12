#!/usr/bin/env node
// Prints the *structure* of a ChatGPT or Claude data export so the pack maker's parsers and
// invented fixtures can track format changes without any real chat data leaving your machine.
// Output: key paths, value types, counts and string lengths. It never prints message text,
// titles, names, file names, IDs, dates or numbers. String values are printed only for an
// allowlist of enum-like fields (role, type, content_type, ...) and only when they look like a
// short lowercase token such as "assistant" or "multimodal_text". Repo-only; not in the npm package.
// Reads one .zip (stored or deflate) or .json file, or a folder of .json files. Writes nothing.
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { extname, join, relative } from 'node:path';
import { inflateRawSync } from 'node:zlib';

const USAGE = 'Usage: node tools/export-shape.mjs EXPORT.zip | conversations.json | EXPORT_FOLDER';
const ENUM_KEYS = new Set(['role', 'type', 'content_type', 'sender', 'status', 'recipient', 'channel', 'stop_reason',
  'model_slug', 'default_model_slug', 'mime_type', 'file_type', 'kind', 'format', 'language']);
const TOKEN = /^[a-z][a-z0-9_.\/+-]{0,39}$/;
const KEY = /^[a-z_][A-Za-z0-9_]{0,40}$/;
const MAX_KEYS = 64; // an object path with more distinct keys than this is a map keyed by data: collapse all
const MAX_ENUM_VALUES = 40;
const SAFE_FILE = /^[a-z_]{1,40}(?:-\d{1,4})?\.json$/;

/** Minimal zip reader: central directory, stored or deflate entries, no zip64. */
function zipEntries(buf) {
  let eocd = -1;
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 65557); i--) if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) throw new Error('not a zip file (no end of central directory)');
  const count = buf.readUInt16LE(eocd + 10);
  let at = buf.readUInt32LE(eocd + 16);
  if (count === 0xffff || at === 0xffffffff) throw new Error('zip64 archive; unzip it and pass the folder instead');
  const entries = [];
  for (let i = 0; i < count; i++) {
    if (buf.readUInt32LE(at) !== 0x02014b50) throw new Error('corrupt zip central directory');
    const method = buf.readUInt16LE(at + 10), size = buf.readUInt32LE(at + 20);
    const nameLen = buf.readUInt16LE(at + 28), extraLen = buf.readUInt16LE(at + 30), commentLen = buf.readUInt16LE(at + 32);
    const local = buf.readUInt32LE(at + 42);
    const name = buf.subarray(at + 46, at + 46 + nameLen).toString('utf8');
    entries.push({ name, read() {
      const start = local + 30 + buf.readUInt16LE(local + 26) + buf.readUInt16LE(local + 28);
      const data = buf.subarray(start, start + size);
      if (method === 0) return data;
      if (method === 8) return inflateRawSync(data);
      throw new Error(`unsupported zip compression method ${method}`);
    } });
    at += 46 + nameLen + extraLen + commentLen;
  }
  return entries;
}

function folderEntries(dir) {
  const out = [];
  const walk = (d) => { for (const n of readdirSync(d)) { const p = join(d, n); statSync(p).isDirectory() ? walk(p) : out.push({ name: relative(dir, p), read: () => readFileSync(p) }); } };
  walk(dir);
  return out;
}

function stringClass(s) {
  if (s === '') return 'empty';
  if (/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$/.test(s)) return 'iso-utc-Z';
  if (/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?[+-]\d\d:\d\d$/.test(s)) return 'iso-offset';
  if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s)) return 'uuid';
  if (/^https?:\/\//.test(s)) return 'url';
  return 'text';
}

function lengthBucket(n) { return n === 0 ? '0' : n < 10 ? '1-9' : n < 100 ? '10-99' : n < 1000 ? '100-999' : n < 10000 ? '1k-9k' : '10k+'; }

const identifier = (k) => KEY.test(k) && !/^[0-9a-f]{8,}$/i.test(k);
const childPath = (p, k) => identifier(k) ? `${p}.${k}` : `${p}.{*}`;

// First pass: distinct keys per object path, with paths built from key names alone.
function keyCounts(root) {
  const counts = new Map();
  const walk = (v, p) => {
    if (Array.isArray(v)) { for (const x of v) walk(x, `${p}[]`); return; }
    if (v === null || typeof v !== 'object') return;
    if (!counts.has(p)) counts.set(p, new Set());
    const keys = counts.get(p);
    for (const [k, x] of Object.entries(v)) { if (keys.size <= MAX_KEYS) keys.add(k); walk(x, childPath(p, k)); }
  };
  walk(root, '$');
  return counts;
}

function shape(root) {
  const many = keyCounts(root);
  const paths = new Map();
  const slot = (p) => { if (!paths.has(p)) paths.set(p, { types: new Map(), strings: new Map(), lengths: new Map(), enums: new Map(), enumOverflow: false, keys: new Set() }); return paths.get(p); };
  const bump = (m, k) => m.set(k, (m.get(k) ?? 0) + 1);
  // p is the printed path; q is the first-pass path used to look up key counts.
  const walk = (v, p, lastKey, q) => {
    const s = slot(p);
    const t = v === null ? 'null' : Array.isArray(v) ? 'array' : typeof v === 'number' ? (Number.isInteger(v) ? 'int' : 'float') : typeof v;
    bump(s.types, t);
    if (t === 'string') {
      bump(s.strings, stringClass(v));
      bump(s.lengths, lengthBucket([...v].length));
      if (ENUM_KEYS.has(lastKey)) {
        const value = TOKEN.test(v) ? v : '<not a short token>';
        if (s.enums.has(value) || s.enums.size < MAX_ENUM_VALUES) bump(s.enums, value); else s.enumOverflow = true;
      }
    } else if (t === 'array') {
      for (const x of v) walk(x, `${p}[]`, lastKey, `${q}[]`);
    } else if (t === 'object') {
      for (const [k, x] of Object.entries(v)) {
        const safe = identifier(k) && many.get(q).size <= MAX_KEYS;
        if (!safe && s.keys.size <= MAX_KEYS) s.keys.add(k);
        walk(x, safe ? `${p}.${k}` : `${p}.{*}`, safe ? k : undefined, childPath(q, k));
      }
    }
  };
  walk(root, '$', undefined, '$');
  return paths;
}

function report(label, json) {
  const lines = [`== ${label}`];
  for (const [p, s] of shape(json)) {
    const parts = [...s.types].map(([t, n]) => `${t}×${n}`);
    if (s.keys.size) parts.push(`(${s.keys.size > MAX_KEYS ? `${MAX_KEYS}+` : s.keys.size} distinct keys collapsed to {*})`);
    if (s.strings.size) parts.push(`kind: ${[...s.strings].map(([k, n]) => `${k}×${n}`).join(', ')}`);
    if (s.lengths.size) parts.push(`length: ${[...s.lengths].map(([k, n]) => `${k}×${n}`).join(', ')}`);
    if (s.enums.size) parts.push(`values: ${[...s.enums].sort((a, b) => b[1] - a[1]).map(([k, n]) => `${k}×${n}`).join(', ')}${s.enumOverflow ? ', …more' : ''}`);
    lines.push(`${p}  ${parts.join('  ')}`);
  }
  return lines.join('\n');
}

function main() {
  const [target, ...rest] = process.argv.slice(2);
  if (!target || rest.length) throw new Error(USAGE);
  const info = statSync(target);
  const entries = info.isDirectory() ? folderEntries(target)
    : extname(target).toLowerCase() === '.zip' ? zipEntries(readFileSync(target))
    : [{ name: 'input.json', read: () => readFileSync(target) }];
  const files = entries.filter(e => !e.name.endsWith('/'));
  const byExt = new Map();
  for (const e of files) { const x = extname(e.name).toLowerCase() || '(none)'; byExt.set(x, (byExt.get(x) ?? 0) + 1); }
  const out = [`# export-shape: ${files.length} files; by extension: ${[...byExt].map(([x, n]) => `${x}×${n}`).join(', ')}`,
    '# structure only: no text, titles, names, file names, IDs, dates or numbers', ''];
  let other = 0;
  for (const e of files.filter(e => extname(e.name).toLowerCase() === '.json')) {
    const base = e.name.split('/').pop();
    const label = SAFE_FILE.test(base) && e.name.split('/').length <= 2 ? base : `(json file ${++other}, name hidden)`;
    let json;
    try { json = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(e.read())); }
    catch (error) { out.push(`== ${label}\n(could not parse: ${error instanceof SyntaxError ? 'invalid JSON' : error.message.split(':')[0]})`, ''); continue; }
    out.push(report(label, json), '');
  }
  process.stdout.write(out.join('\n'));
}

try { main(); } catch (error) {
  process.stderr.write(`export-shape: ${error instanceof Error ? error.message : String(error)}\n`);
  process.exitCode = 1;
}
