import { constants, openSync, closeSync, fstatSync, readFileSync, lstatSync, readdirSync } from 'node:fs';
import { join, isAbsolute } from 'node:path';
import { createHash } from 'node:crypto';
import { requireValue, verifyPackEntries } from './verify.js';

export type { Citation, MemoryRecord } from './verify.js';
const hash = (data: Uint8Array) => createHash('sha256').update(data).digest('hex');
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
  const { records, manifest_sha256 } = verifyPackEntries(readdirSync(folder), (name, max) => readRegular(join(folder,name), max), hash);
  const indexed = [...records.values()].map(record => ({ record, words: tokens([record.statement,record.topic,...record.evidence.map(c=>c.quote)].join(' ')) }));
  return {
    verification: { sha256sums: 'passed' as const, manifest_sha256, records: records.size, scope: 'Checksum integrity of loaded snapshot; not authenticity or factual truth.' },
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
