// Pure pack verifier: no imports, so the same checks run in Node and in a browser.
// Callers supply how entries are read and hashed; loadPack in pack.ts is the Node caller.

export type Citation = { message_id: number; date_utc: string; quote: string; start: number; end: number; message_sha256: string };
export type MemoryRecord = { record_id: string; role: 'user' | 'agent'; speaker: string; statement: string; topic: string; category: string; date_first_utc: string; date_last_utc: string; evidence: Citation[]; [key: string]: unknown };
export const FILES = ['MEMORY.md', 'README.md', 'records.jsonl'];
export const MANIFEST_MAX = 4096;
export const FILE_MAX = 16 * 1024 * 1024;
export function requireValue(ok: unknown, message: string): asserts ok { if (!ok) throw new Error(`verified-memory: ${message}`); }
const decode = (bytes: Uint8Array) => new TextDecoder('utf-8', { fatal: true }).decode(bytes);
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

/**
 * Verify a pack from its entry names and bytes. `read(name, max)` returns one entry's bytes
 * (the caller enforces `max`); `digest` returns lowercase hex SHA-256 of exactly those bytes.
 */
export function verifyPackEntries(names: string[], read: (name: string, max: number) => Uint8Array, digest: (bytes: Uint8Array) => string) {
  requireValue(JSON.stringify([...names].sort()) === JSON.stringify([...FILES,'SHA256SUMS'].sort()), 'pack must contain exactly four expected files');
  const manifest = read('SHA256SUMS', MANIFEST_MAX);
  const expected = new Map<string,string>();
  for (const line of decode(manifest).split(/\r?\n/).filter(x => x.length)) {
    const m = /^([a-f0-9]{64})  (MEMORY\.md|README\.md|records\.jsonl)$/.exec(line);
    requireValue(m && !expected.has(m[2]), 'invalid or duplicate checksum entry');
    expected.set(m[2],m[1]);
  }
  requireValue(expected.size === FILES.length, 'missing checksum entry');
  let jsonl = '';
  for (const name of FILES) {
    const bytes = read(name, FILE_MAX);
    requireValue(digest(bytes) === expected.get(name), `checksum mismatch: ${name}`);
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
  return { records, manifest_sha256: digest(manifest) };
}
