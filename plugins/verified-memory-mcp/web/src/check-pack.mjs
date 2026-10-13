// "Check a signed pack": runs the shared verifier (the dist/verify.js that the MCP server and
// the OpenClaw plugin run) over a pack chosen in this browser. That verifier is synchronous
// and asks its caller for SHA-256, SHA-512 and Ed25519 results; Web Crypto is asynchronous.
// So a result the page has not computed yet stops the run, gets computed, and the run starts
// again from the top. Every rule is decided by the shared verifier; this file only supplies
// bytes and crypto, and never claims a signature it could not check.
import { FILE_MAX, checkPackSignature, parseTrustedKeys, requireValue, verifyPackEntries } from '../../dist/verify.js';
import { isZip, openZip, readEntry } from './zip.mjs';

export class CheckError extends Error {}
export class Unsupported extends Error {}
class Pending { constructor(job) { this.job = job; } }
const hex = (bytes) => Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');

/** Runs the synchronous fn(primitives), computing each missing crypto result and retrying. */
export async function withAsyncCrypto(fn, subtle = globalThis.crypto?.subtle) {
  if (!subtle) throw new Unsupported('This browser has no Web Crypto, so it cannot check packs.');
  const cache = new Map();
  // Large inputs are the pack files, read once, so the same array comes back on every run.
  const lookup = (kind, parts, compute) => {
    const id = parts.length === 1 && parts[0].length > 4096 ? parts[0] : `${kind}:${parts.map(hex).join(':')}`;
    if (cache.has(id)) return cache.get(id);
    throw new Pending(async () => { cache.set(id, await compute()); });
  };
  const sha256hex = (b) => lookup('sha256', [b], async () => hex(new Uint8Array(await subtle.digest('SHA-256', b))));
  const crypto = {
    sha512: (b) => lookup('sha512', [b], async () => new Uint8Array(await subtle.digest('SHA-512', b))),
    ed25519Verify: (key, message, signature) => lookup('ed25519', [key, message, signature], async () => {
      let publicKey;
      try { publicKey = await subtle.importKey('raw', key, { name: 'Ed25519' }, false, ['verify']); }
      catch { throw new Unsupported('This browser cannot check Ed25519 signatures. Use a current Chrome, Firefox or Safari, or check the pack with ssh-keygen -Y verify.'); }
      return subtle.verify({ name: 'Ed25519' }, publicKey, signature, message);
    })
  };
  for (let round = 0; round < 32; round++) {
    try { return fn({ sha256hex, crypto }); }
    catch (error) { if (!(error instanceof Pending)) throw error; await error.job(); }
  }
  throw new Error('verification did not finish');
}

/**
 * Chosen files -> Map of pack entry name -> bytes. Either one .zip holding the pack files (at
 * its top level or inside one folder, as the pack maker's download does), or the loose files.
 * Folder entries and macOS __MACOSX/ resource entries in a zip are zip artefacts, not pack files.
 */
export async function readPackFiles(files) {
  const out = new Map();
  if (files.length === 1 && await isZip(files[0].source)) {
    const { name, source } = files[0];
    let entries;
    try { entries = (await openZip(source)).filter((e) => !e.name.endsWith('/') && !e.name.startsWith('__MACOSX/')); }
    catch (error) { throw new CheckError(`${name}: ${error.message}`); }
    const tops = new Set(entries.map((e) => (e.name.includes('/') ? e.name.slice(0, e.name.indexOf('/') + 1) : '')));
    const prefix = tops.size === 1 ? [...tops][0] : null;
    if (prefix === null || entries.some((e) => e.name.slice(prefix.length).includes('/'))) throw new CheckError(`${name}: the zip must hold one pack, either at its top level or in a single folder`);
    for (const entry of entries) {
      try { out.set(entry.name.slice(prefix.length), await readEntry(source, entry, FILE_MAX)); }
      catch (error) { throw new CheckError(`${name}: ${error.message}`); }
    }
    return out;
  }
  for (const { name, source } of files) {
    if (out.has(name)) throw new CheckError(`${name} was chosen twice`);
    if (source.size > FILE_MAX) throw new CheckError(`${name}: larger than a pack file can be`);
    out.set(name, await source.read(0, source.size));
  }
  return out;
}

/** Pack files + the trusted keys text -> { records, signature } exactly as the server would decide. */
export async function checkPack(files, trustedKeysText, requireSignature, subtle) {
  // Trust configuration is checked first, as loadPack does: a misconfiguration never loads.
  const trusted = parseTrustedKeys([trustedKeysText]);
  requireValue(!requireSignature || trusted.length > 0, 'requiring a signature needs at least one trusted key');
  const read = (name, max) => { const bytes = files.get(name); requireValue(bytes.length <= max, 'unsafe or oversized pack file'); return bytes; };
  const pack = await withAsyncCrypto(({ sha256hex }) => verifyPackEntries([...files.keys()], read, sha256hex), subtle);
  const signature = await withAsyncCrypto(({ sha256hex, crypto }) => checkPackSignature(pack.manifest, pack.signature, trusted, requireSignature, crypto, sha256hex), subtle);
  return { records: pack.records.size, signature };
}

/** Result or error -> { text, kind } for the status line. Never reports an unchecked signature. */
export function describeCheck(result, error) {
  if (error instanceof Unsupported) return { text: error.message, kind: 'error' };
  if (error) {
    const message = error.message.replace(/^verified-memory: /, '');
    return { text: `Not accepted: ${message.charAt(0).toUpperCase()}${message.slice(1)}.`, kind: 'error' };
  }
  const records = `Checksums pass for ${result.records} record${result.records === 1 ? '' : 's'}.`;
  const s = result.signature;
  if (!s) return { text: `${records} This pack is not signed, so nothing here says who made it.`, kind: 'ok' };
  if (s.status === 'untrusted') return { text: `${records} The signature is valid, but its key (${s.fingerprint}) is not one you listed, so the signer is unknown.`, kind: '' };
  return { text: `${records} Signed by “${s.signer}” (${s.fingerprint}), a key you listed. This proves that key signed these exact files, not that what they say is true.`, kind: 'ok' };
}
