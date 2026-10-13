// Pure pack verifier: no imports, so the same checks run in Node and in a browser.
// Callers supply how entries are read and hashed, and for signed packs the SHA-512 and
// Ed25519 primitives; loadPack in pack.ts is the Node caller.

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
  const signed = names.includes(SIGNATURE_FILE), dated = names.includes(FRESHNESS_FILE);
  const pinned = [...FILES, ...(dated ? [FRESHNESS_FILE] : [])];
  requireValue(JSON.stringify([...names].sort()) === JSON.stringify([...pinned,'SHA256SUMS',...(signed ? [SIGNATURE_FILE] : [])].sort()), `pack must contain exactly four expected files, plus an optional ${FRESHNESS_FILE} and ${SIGNATURE_FILE}`);
  const manifest = read('SHA256SUMS', MANIFEST_MAX);
  const expected = new Map<string,string>();
  for (const line of decode(manifest).split(/\r?\n/).filter(x => x.length)) {
    const m = /^([a-f0-9]{64})  (MEMORY\.md|README\.md|records\.jsonl|PACK\.json)$/.exec(line);
    requireValue(m && !expected.has(m[2]), 'invalid or duplicate checksum entry');
    requireValue(pinned.includes(m[2]), `checksum entry for a file not in the pack: ${m[2]}`);
    expected.set(m[2],m[1]);
  }
  requireValue(expected.size === pinned.length, 'missing checksum entry');
  let jsonl = '', dates: PackDates | undefined;
  for (const name of pinned) {
    const bytes = read(name, name === FRESHNESS_FILE ? FRESHNESS_MAX : FILE_MAX);
    requireValue(digest(bytes) === expected.get(name), `checksum mismatch: ${name}`);
    const content = decode(bytes);
    if (name === 'records.jsonl') jsonl = content;
    if (name === FRESHNESS_FILE) dates = parsePackDates(content);
  }
  const records = new Map<string,MemoryRecord>();
  for (const line of jsonl.split('\n').filter(x => x.trim())) {
    const record: unknown = JSON.parse(line);
    validateRecord(record);
    requireValue(!records.has(record.record_id), 'duplicate record ID');
    requireValue(records.size < 10000, 'too many records');
    records.set(record.record_id,record);
  }
  return { records, manifest, manifest_sha256: digest(manifest), dates, signature: signed ? read(SIGNATURE_FILE, SIGNATURE_MAX) : undefined };
}

// Freshness (v0.3): an optional PACK.json, pinned in SHA256SUMS like every other file, so a
// signature over SHA256SUMS also covers its dates. Packs without it (all v0.1 and v0.2 packs)
// load as before with freshness "unknown". The pack maker never writes it; sign-pack does.
export const FRESHNESS_FILE = 'PACK.json';
export const FRESHNESS_MAX = 4096;
/** How far in the future created_utc may be before the pack is "not_yet_valid" (clock skew). */
export const CLOCK_SKEW_MS = 5 * 60 * 1000;
export type PackDates = { created_utc: string; expires_utc: string };
function parsePackDates(content: string): PackDates {
  let x: unknown;
  try { x = JSON.parse(content); } catch { requireValue(false, `invalid ${FRESHNESS_FILE}: not JSON`); }
  requireValue(object(x) && JSON.stringify(Object.keys(x).sort()) === '["created_utc","expires_utc","format","version"]', `${FRESHNESS_FILE} must have exactly format, version, created_utc and expires_utc`);
  requireValue(x.format === 'verified-memory-pack' && x.version === 2, `${FRESHNESS_FILE} must be format verified-memory-pack, version 2`);
  requireValue(date(x.created_utc) && date(x.expires_utc) && Date.parse(x.created_utc) < Date.parse(x.expires_utc), `${FRESHNESS_FILE} dates must be UTC ISO 8601, with created_utc before expires_utc`);
  return { created_utc: x.created_utc, expires_utc: x.expires_utc };
}

// Signed packs: an OpenSSH signature (ssh-keygen -Y sign, PROTOCOL.sshsig) over the exact
// SHA256SUMS bytes, which pin every other file. Only ssh-ed25519 keys, the sha512 hash and
// this namespace are accepted. Trust is only ever a public key the user listed; a pack can
// never name its own signer. A valid signature proves which key signed these bytes, not
// that the content is true or current.
export const SIGNATURE_FILE = 'SHA256SUMS.sig';
export const SIGNATURE_MAX = 4096;
export const SIGNATURE_NAMESPACE = 'verified-memory-pack-v1';
export const TRUSTED_KEYS_MAX = 256;
export const SIGNATURE_SCOPE = {
  unsigned: 'This pack has no SHA256SUMS.sig, so nothing establishes who made it.',
  verified: 'A key you listed as trusted signed these exact pack bytes. This does not establish that the content is true, complete or current.',
  untrusted: 'The signature is valid, but its key is not one you listed as trusted, so the signer is unknown. This does not establish authenticity or truth.'
};
export type TrustedKey = { name: string; key: Uint8Array };
export type SignatureCrypto = {
  sha512: (bytes: Uint8Array) => Uint8Array;
  ed25519Verify: (publicKey: Uint8Array, message: Uint8Array, signature: Uint8Array) => boolean;
};
export type SignatureResult = { status: 'verified'; signer: string; fingerprint: string; scope: string } | { status: 'untrusted'; fingerprint: string; scope: string } | { status: 'unsigned'; scope: string };
const ascii = (s: string) => Uint8Array.from(s, c => c.charCodeAt(0));
const equal = (a: Uint8Array, b: Uint8Array) => a.length === b.length && a.every((x, i) => x === b[i]);
const concat = (...parts: Uint8Array[]) => { const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0)); let at = 0; for (const p of parts) { out.set(p, at); at += p.length; } return out; };
const sshString = (bytes: Uint8Array) => concat(Uint8Array.of(bytes.length >>> 24, bytes.length >>> 16 & 255, bytes.length >>> 8 & 255, bytes.length & 255), bytes);
function base64(s: string, message: string): Uint8Array {
  requireValue(s.length > 0 && s.length % 4 === 0 && /^[A-Za-z0-9+/]+={0,2}$/.test(s), message);
  return Uint8Array.from(atob(s), c => c.charCodeAt(0));
}
/** Reads SSH wire-format strings; every read is bounds-checked and the caller must consume everything. */
function reader(bytes: Uint8Array, message: string) {
  let at = 0;
  return {
    raw(n: number) { requireValue(at + n <= bytes.length, message); return bytes.subarray(at, at += n); },
    uint32() { const b = this.raw(4); return ((b[0] << 24) | (b[1] << 16) | (b[2] << 8) | b[3]) >>> 0; },
    string() { return this.raw(this.uint32()); },
    text() { return new TextDecoder().decode(this.string()); },
    end() { requireValue(at === bytes.length, message); }
  };
}
/** An ssh-ed25519 public key blob -> its 32-byte key; anything else is rejected. */
function ed25519Key(blob: Uint8Array, message: string): Uint8Array {
  const r = reader(blob, message);
  requireValue(r.text() === 'ssh-ed25519', message);
  const key = r.string(); r.end();
  requireValue(key.length === 32, message);
  return key;
}
/** OpenSSH-style fingerprint, as printed by ssh-keygen -l: SHA256:<unpadded base64>. */
export function fingerprint(key: Uint8Array, digest: (bytes: Uint8Array) => string): string {
  const hex = digest(concat(sshString(ascii('ssh-ed25519')), sshString(key)));
  return 'SHA256:' + btoa(String.fromCharCode(...hex.match(/../g)!.map(h => parseInt(h, 16)))).replace(/=+$/, '');
}

/**
 * Trusted keys, one per line in allowed_signers form: `name ssh-ed25519 AAAA… [comment]`.
 * Blank lines and # comments are ignored. Options, multiple principals and other key
 * types are refused, so a line never means more than it appears to.
 */
export function parseTrustedKeys(lines: string[]): TrustedKey[] {
  const keys: TrustedKey[] = [];
  for (const line of lines.flatMap(l => l.split(/\r?\n/)).map(l => l.trim()).filter(l => l && !l.startsWith('#'))) {
    const m = /^([A-Za-z0-9._@+-]{1,64})\s+(\S+)\s+(\S+)(?:\s+.*)?$/.exec(line);
    requireValue(m, 'invalid trusted key line; expected: name ssh-ed25519 AAAA… [comment]');
    requireValue(m[2] === 'ssh-ed25519', 'trusted keys must be ssh-ed25519');
    const key = ed25519Key(base64(m[3], 'invalid trusted key'), 'invalid trusted key');
    requireValue(!keys.some(k => equal(k.key, key)), 'duplicate trusted key');
    keys.push({ name: m[1], key });
    requireValue(keys.length <= TRUSTED_KEYS_MAX, 'too many trusted keys');
  }
  return keys;
}

/** SHA256SUMS.sig bytes -> the signing key, signature and the exact bytes it must cover. */
export function parsePackSignature(bytes: Uint8Array) {
  const bad = 'invalid SHA256SUMS.sig; expected an ssh-keygen -Y sign signature';
  requireValue(bytes.length <= SIGNATURE_MAX, bad);
  let text = '';
  try { text = decode(bytes); } catch { requireValue(false, bad); }
  const armor = /^-----BEGIN SSH SIGNATURE-----\r?\n([A-Za-z0-9+/=\r\n]+?)\r?\n-----END SSH SIGNATURE-----\r?\n?$/.exec(text);
  requireValue(armor, bad);
  const r = reader(base64(armor[1].replace(/\r?\n/g, ''), bad), bad);
  requireValue(equal(r.raw(6), ascii('SSHSIG')) && r.uint32() === 1, bad);
  const key = ed25519Key(r.string(), 'pack signature key must be ssh-ed25519');
  requireValue(r.text() === SIGNATURE_NAMESPACE, `pack signature namespace must be ${SIGNATURE_NAMESPACE}`);
  requireValue(r.string().length === 0, bad);
  requireValue(r.text() === 'sha512', 'pack signature hash must be sha512');
  const sig = reader(r.string(), bad); r.end();
  requireValue(sig.text() === 'ssh-ed25519', 'pack signature must be ssh-ed25519');
  const signature = sig.string(); sig.end();
  requireValue(signature.length === 64, bad);
  return {
    key, signature,
    /** The bytes ssh-keygen signed, given SHA-512 of SHA256SUMS. */
    signedData: (manifestSha512: Uint8Array) => concat(ascii('SSHSIG'), sshString(ascii(SIGNATURE_NAMESPACE)), sshString(new Uint8Array(0)), sshString(ascii('sha512')), sshString(manifestSha512))
  };
}

/**
 * The single signature policy. A present signature must be well formed and valid or the pack is
 * refused, even when no key is trusted; a valid one by an unlisted key is reported as untrusted,
 * and a missing one as unsigned. `requireSignature` (--require-signature, and implied by
 * --strict) refuses anything but a signature by a listed key, and needs a listed key to start.
 */
export function checkPackSignature(manifest: Uint8Array, signatureBytes: Uint8Array | undefined, trusted: TrustedKey[], requireSignature: boolean,
  crypto: SignatureCrypto, digest: (bytes: Uint8Array) => string): SignatureResult {
  requireValue(!requireSignature || trusted.length > 0, 'requiring a signature needs at least one trusted key');
  if (!signatureBytes) { requireValue(!requireSignature, `pack is unsigned (no ${SIGNATURE_FILE}) but a signature is required`); return { status: 'unsigned', scope: SIGNATURE_SCOPE.unsigned }; }
  const parsed = parsePackSignature(signatureBytes);
  requireValue(crypto.ed25519Verify(parsed.key, parsed.signedData(crypto.sha512(manifest)), parsed.signature) === true, 'pack signature does not verify');
  const print = fingerprint(parsed.key, digest);
  const signer = trusted.find(k => equal(k.key, parsed.key));
  if (signer) return { status: 'verified', signer: signer.name, fingerprint: print, scope: SIGNATURE_SCOPE.verified };
  requireValue(!requireSignature, `pack is signed by ${print}, which is not a trusted key, and a signature is required`);
  return { status: 'untrusted', fingerprint: print, scope: SIGNATURE_SCOPE.untrusted };
}

export type FreshnessResult = { status: 'fresh' | 'stale' | 'not_yet_valid'; created_utc: string; expires_utc: string; authenticated: boolean; scope: string } | { status: 'unknown'; scope: string };
/**
 * The single freshness policy, judged against the host clock at `now` (ms). Dates count as
 * authenticated only when a key the user listed signed them. Outside strict mode (including
 * with only requireSignature) every outcome loads and is reported; strict refuses all but "fresh".
 */
export function checkPackFreshness(dates: PackDates | undefined, signature: SignatureResult, strict: boolean, now: number): FreshnessResult {
  if (!dates) {
    requireValue(!strict, `pack has no ${FRESHNESS_FILE}, so no expiry date, and strict mode requires a fresh pack`);
    return { status: 'unknown', scope: `This pack has no ${FRESHNESS_FILE}, so it carries no creation or expiry date and nothing says whether it is current.` };
  }
  const authenticated = signature.status === 'verified';
  const { created_utc, expires_utc } = dates;
  const dated = authenticated ? 'These dates are signed by a key you listed.' : 'These dates are not covered by a signature from a key you listed, so anyone could have written them.';
  if (Date.parse(created_utc) > now + CLOCK_SKEW_MS) {
    requireValue(!strict, `pack is dated in the future (created_utc ${created_utc}) and strict mode refuses it`);
    return { status: 'not_yet_valid', created_utc, expires_utc, authenticated, scope: `This pack says it was created at ${created_utc}, which is in the future by this computer's clock. Check the clock or the pack. ${dated}` };
  }
  if (now >= Date.parse(expires_utc)) {
    requireValue(!strict, `pack expired at ${expires_utc} and strict mode refuses stale packs`);
    return { status: 'stale', created_utc, expires_utc, authenticated, scope: `This pack expired at ${expires_utc}; its records may be out of date. It is served only because strict mode is off. ${dated}` };
  }
  return { status: 'fresh', created_utc, expires_utc, authenticated, scope: `This pack is within its dates (expires ${expires_utc}). Fresh means it has not expired, not that it is complete or true. ${dated}` };
}

/** One-line host warnings for a pack that loaded outside strict mode but is not current. */
export function freshnessWarning(freshness: FreshnessResult): string | undefined {
  if (freshness.status === 'stale') return `warning: pack expired at ${freshness.expires_utc} (stale); serving it because strict mode is off`;
  if (freshness.status === 'not_yet_valid') return `warning: pack is dated in the future (created_utc ${freshness.created_utc}); check the clock; serving it because strict mode is off`;
  return undefined;
}
