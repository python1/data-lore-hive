import { constants, openSync, closeSync, fstatSync, readFileSync, lstatSync, readdirSync } from 'node:fs';
import { join, isAbsolute } from 'node:path';
import { createHash } from 'node:crypto';

export type Citation = { message_id: number; date_utc: string; quote: string; start: number; end: number; message_sha256: string };
export type MemoryRecord = { record_id: string; role: 'user' | 'agent'; speaker: string; statement: string; topic: string; category: string; date_first_utc: string; date_last_utc: string; evidence: Citation[]; [key: string]: unknown };
const FILES = ['MEMORY.md', 'README.md', 'records.jsonl'];
const hash = (data: Buffer) => createHash('sha256').update(data).digest('hex');
function requireValue(ok: unknown, message: string): asserts ok { if (!ok) throw new Error(`verified-memory: ${message}`); }
function readRegular(path: string, max: number): Buffer {
  const before = lstatSync(path);
  requireValue(before.isFile() && !before.isSymbolicLink(), 'pack entries must be regular files');
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = fstatSync(fd);
    requireValue(info.isFile() && info.size <= max && info.ino === before.ino && info.dev === before.dev, 'unsafe or oversized pack file');
    const bytes = readFileSync(fd);
    requireValue(bytes.length <= max, 'oversized pack file');
    return bytes;
  } finally { closeSync(fd); }
}
const decode = (bytes: Buffer) => new TextDecoder('utf-8', { fatal: true }).decode(bytes);
function object(x: unknown): x is Record<string, unknown> { return x !== null && typeof x === 'object' && !Array.isArray(x); }
function text(x: unknown): x is string { return typeof x === 'string' && x.trim().length > 0; }
function date(x: unknown): x is string { return typeof x === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|\+00:00)$/.test(x) && Number.isFinite(Date.parse(x)); }
function validateRecord(x: unknown): asserts x is MemoryRecord {
  requireValue(object(x), 'record must be an object');
  for (const key of ['record_id','speaker','statement','topic','category']) requireValue(text(x[key]), `missing record field: ${key}`);
  requireValue(/^M-[A-Za-z0-9_-]{1,127}$/.test(x.record_id as string), 'invalid record ID');
  requireValue(x.role === 'user' || x.role === 'agent', 'invalid voice');
  requireValue(date(x.date_first_utc) && date(x.date_last_utc) && Date.parse(x.date_first_utc) <= Date.parse(x.date_last_utc), 'invalid record dates');
  requireValue(Array.isArray(x.evidence) && x.evidence.length > 0, 'record needs citations');
  for (const c of x.evidence) {
    requireValue(object(c) && Number.isSafeInteger(c.message_id) && (c.message_id as number) > 0 && date(c.date_utc) && text(c.quote), 'invalid citation');
    requireValue(Number.isSafeInteger(c.start) && Number.isSafeInteger(c.end) && (c.start as number) >= 0 && (c.end as number) - (c.start as number) === [...c.quote].length, 'invalid citation offsets');
    requireValue(typeof c.message_sha256 === 'string' && /^[a-f0-9]{64}$/.test(c.message_sha256), 'invalid message hash');
    requireValue(Date.parse(c.date_utc) >= Date.parse(x.date_first_utc as string) && Date.parse(c.date_utc) <= Date.parse(x.date_last_utc as string), 'citation outside record dates');
  }
}
export function tokens(s: string): string[] { return s.normalize('NFKC').toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []; }

/** Read once, hash those exact bytes, then serve an isolated in-memory snapshot. */
export function loadPack(folder: string) {
  requireValue(isAbsolute(folder), 'packPath must be absolute');
  let root;
  try { root = lstatSync(folder); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') throw new Error('verified-memory: pack directory missing; set plugins.entries.verified-memory.config.packPath to an existing absolute pack directory, or rebuild the bundled fictional sample with npm run sample');
    throw error;
  }
  requireValue(root.isDirectory() && !root.isSymbolicLink(), 'pack root must be a real directory');
  requireValue(JSON.stringify(readdirSync(folder).sort()) === JSON.stringify([...FILES,'SHA256SUMS'].sort()), 'pack must contain exactly four expected files');
  const manifest = readRegular(join(folder, 'SHA256SUMS'), 4096);
  const expected = new Map<string,string>();
  for (const line of decode(manifest).split(/\r?\n/).filter(x => x.length)) {
    const m = /^([a-f0-9]{64})  (MEMORY\.md|README\.md|records\.jsonl)$/.exec(line);
    requireValue(m && !expected.has(m[2]), 'invalid or duplicate checksum entry');
    expected.set(m[2],m[1]);
  }
  requireValue(expected.size === FILES.length, 'missing checksum entry');
  let jsonl = '';
  for (const name of FILES) {
    const bytes = readRegular(join(folder,name), 16 * 1024 * 1024);
    requireValue(hash(bytes) === expected.get(name), `checksum mismatch: ${name}`);
    const content = decode(bytes);
    if (name === 'records.jsonl') jsonl = content;
  }
  const records = new Map<string,MemoryRecord>();
  for (const line of jsonl.split('\n').filter(x => x.trim())) {
    const record: unknown = JSON.parse(line);
    validateRecord(record);
    requireValue(!records.has(record.record_id), 'duplicate record ID');
    requireValue(records.size < 10000, 'too many records');
    records.set(record.record_id,record);
  }
  const indexed = [...records.values()].map(record => ({ record, words: tokens([record.statement,record.topic,...record.evidence.map(c=>c.quote)].join(' ')) }));
  return {
    verification: { sha256sums: 'passed' as const, manifest_sha256: hash(manifest), records: records.size, scope: 'Checksum integrity of loaded snapshot; not authenticity or factual truth.' },
    search(query: string) {
      requireValue(typeof query === 'string' && query.trim().length > 0 && query.length <= 512, 'query must contain 1–512 characters');
      const words = [...new Set(tokens(query))];
      requireValue(words.length <= 32, 'query exceeds 32 terms');
      if (!words.length) return [];
      return indexed.filter(hit => words.every(word => hit.words.includes(word)))
        .map(hit => ({...hit, score: words.reduce((s,w)=>s+hit.words.filter(t=>t===w).length,0)}))
        .sort((a,b)=>b.score-a.score || Date.parse(b.record.date_last_utc)-Date.parse(a.record.date_last_utc) || a.record.record_id.localeCompare(b.record.record_id))
        .slice(0,10).map(({record}) => ({ id: record.record_id, statement: record.statement, speaker: record.speaker, date: record.date_last_utc,
          citations: record.evidence.map(c=>({quote:c.quote,source_message_id:c.message_id,date:c.date_utc,speaker:record.speaker})) }));
    },
    get(id: string) {
      requireValue(typeof id === 'string' && /^M-[A-Za-z0-9_-]{1,127}$/.test(id), 'invalid record ID');
      const record = records.get(id);
      return record ? structuredClone(record) : null;
    }
  };
}
