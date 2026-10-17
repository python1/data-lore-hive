import { constants, openSync, closeSync, fstatSync, readFileSync, lstatSync, readdirSync, type Stats } from 'node:fs';
import { join, isAbsolute } from 'node:path';
import { createHash, createPublicKey, verify } from 'node:crypto';
import { checkPackFreshness, checkPackSequence, checkPackSignature, parseTrustPolicy, requireValue, verifyPackEntries, type SignatureCrypto } from './verify.js';

export type { Citation, FreshnessResult, MemoryRecord, SignatureResult } from './verify.js';
export type PackOptions = {
  trustedKeys?: string[];
  /** Pinned signer fingerprints (SHA256:…). If any is set, only these signers are accepted; trustedKeys then only names them. */
  trustedFingerprints?: string[];
  /** Revoked key fingerprints, one per line as readRevokedKeys returns them: always refused. */
  revokedKeys?: string[];
  /** Refuse unless PACK.json carries a signed sequence of at least this. Implies requireSignature. */
  minSequence?: number;
  /** Refuse unless signed by a trusted key and fresh, at load and on every later read. */
  strict?: boolean;
  /** As in 0.2.0: refuse unless signed by a trusted key; freshness is reported, not enforced. */
  requireSignature?: boolean;
  /** Clock in ms for freshness; defaults to Date.now. */
  now?: () => number;
};
const hash = (data: Uint8Array) => createHash('sha256').update(data).digest('hex');
const signatureCrypto: SignatureCrypto = {
  sha512: data => createHash('sha512').update(data).digest(),
  ed25519Verify: (key, message, signature) => verify(null, message, createPublicKey({ key: { kty: 'OKP', crv: 'Ed25519', x: Buffer.from(key).toString('base64url') }, format: 'jwk' }), signature)
};
function readRegular(path: string, max: number, onStat?: (info: Stats) => void): Buffer {
  const before = lstatSync(path);
  requireValue(before.isFile() && !before.isSymbolicLink(), 'pack entries must be regular files');
  onStat?.(before);
  const fd = openSync(path, constants.O_RDONLY | constants.O_NOFOLLOW | constants.O_NONBLOCK);
  try {
    const info = fstatSync(fd);
    requireValue(info.isFile() && info.size <= max && info.ino === before.ino && info.dev === before.dev, 'unsafe or oversized pack file');
    const bytes = readFileSync(fd);
    requireValue(bytes.length <= max, 'oversized pack file');
    return bytes;
  } finally { closeSync(fd); }
}
function readConfigFile(path: string, what: string): string[] {
  requireValue(isAbsolute(path), `${what} path must be absolute`);
  try { return [new TextDecoder('utf-8', { fatal: true }).decode(readRegular(path, 64 * 1024))]; }
  catch { throw new Error(`verified-memory: cannot read ${what} file; it must be a regular UTF-8 file of at most 64 KiB`); }
}
/** Read a trusted keys file (allowed_signers lines) without following symlinks. */
export function readTrustedKeys(path: string): string[] { return readConfigFile(path, 'trusted keys'); }
/** Read a revoked keys file (one SHA256:… fingerprint per line) without following symlinks. */
export function readRevokedKeys(path: string): string[] { return readConfigFile(path, 'revoked keys'); }
/** What changes when a file's bytes or identity change; ctime cannot be set back by a normal user. */
const stamp = (info: Stats) => [info.dev, info.ino, info.size, info.mtimeMs, info.ctimeMs].join(':');
export function tokens(s: string): string[] { return s.normalize('NFKC').toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []; }

/** Read once, hash those exact bytes, then serve an isolated in-memory snapshot. */
export function loadPack(folder: string, options: PackOptions = {}) {
  // Trust configuration is checked before the pack is read: a misconfiguration never loads.
  const policy = parseTrustPolicy(options);
  const now = options.now ?? Date.now;
  requireValue(isAbsolute(folder), 'packPath must be absolute');
  let root;
  try { root = lstatSync(folder); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') throw new Error('verified-memory: pack directory missing; set plugins.entries.verified-memory.config.packPath to an existing absolute pack directory, or rebuild the bundled fictional sample with npm run sample');
    throw error;
  }
  requireValue(root.isDirectory() && !root.isSymbolicLink(), 'pack root must be a real directory');
  const names = readdirSync(folder), stamps = new Map<string, string>();
  const { records, manifest, manifest_sha256, dates, signature: signatureBytes } = verifyPackEntries(names, (name, max) => readRegular(join(folder,name), max, info => stamps.set(name, stamp(info))), hash);
  // Precedence: revoked, pinned, trusted keys (in checkPackSignature); then sequence; then expiry.
  const signature = checkPackSignature(manifest, signatureBytes, policy, signatureCrypto, hash);
  checkPackSequence(dates, signature, policy.minSequence);
  // The snapshot is only served while the pack on disk is still the one that was verified: any
  // change to its listing or to a file's size, times or identity stops serving. Metadata only;
  // nothing is re-read, watched or written.
  const listing = JSON.stringify([...names].sort());
  const unchanged = () => {
    let same = false;
    try {
      const current = lstatSync(folder);
      same = current.isDirectory() && !current.isSymbolicLink() && current.dev === root.dev && current.ino === root.ino && JSON.stringify(readdirSync(folder).sort()) === listing
        && [...stamps].every(([name, s]) => stamp(lstatSync(join(folder, name))) === s);
    } catch { same = false; }
    requireValue(same, 'pack files changed on disk since startup, so the verified snapshot no longer matches them; restart to verify the pack again');
  };
  // Freshness is judged again on every read, so a long-running host notices expiry; in strict
  // mode an expired snapshot then refuses to serve. This first call refuses at load.
  const verification = () => ({ sha256sums: 'passed' as const, manifest_sha256, records: records.size, scope: 'Checksum integrity of loaded snapshot; not authenticity or factual truth.',
    signature, freshness: checkPackFreshness(dates, signature, policy.strict, now()) });
  verification();
  const indexed = [...records.values()].map(record => ({ record, words: tokens([record.statement,record.topic,...record.evidence.map(c=>c.quote)].join(' ')) }));
  return {
    get verification() { unchanged(); return verification(); },
    search(query: string) {
      unchanged();
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
      unchanged();
      requireValue(typeof id === 'string' && /^M-[A-Za-z0-9_-]{1,127}$/.test(id), 'invalid record ID');
      const record = records.get(id);
      return record ? structuredClone(record) : null;
    }
  };
}
