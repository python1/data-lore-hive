// Test-only: makes invented Ed25519 keys in memory and writes ssh-keygen -Y sign style
// signatures (PROTOCOL.sshsig), with knobs to produce each malformed variant. Keys are
// never written to disk, and nothing outside test/ imports this.
import { createHash, generateKeyPairSync, sign } from 'node:crypto';

const str = (b) => { const bytes = Buffer.from(b); const n = Buffer.alloc(4); n.writeUInt32BE(bytes.length); return Buffer.concat([n, bytes]); };

export function newKey() {
  const { privateKey, publicKey } = generateKeyPairSync('ed25519');
  const raw = Buffer.from(publicKey.export({ format: 'jwk' }).x, 'base64url');
  const blob = Buffer.concat([str('ssh-ed25519'), str(raw)]);
  return { privateKey, raw, blob, line: (name) => `${name} ssh-ed25519 ${blob.toString('base64')}` };
}

export function sshsig(key, manifest, opts = {}) {
  const { namespace = 'verified-memory-pack-v1', hash = 'sha512', keyBlob = key.blob, sigType = 'ssh-ed25519', version = 1, reserved = '', trailing = Buffer.alloc(0), mutateSignature } = opts;
  const digest = createHash(hash === 'sha256' ? 'sha256' : 'sha512').update(manifest).digest();
  let signature = sign(null, Buffer.concat([Buffer.from('SSHSIG'), str(namespace), str(reserved), str(hash), str(digest)]), key.privateKey);
  if (mutateSignature) signature = mutateSignature(Buffer.from(signature));
  const v = Buffer.alloc(4); v.writeUInt32BE(version);
  const blob = Buffer.concat([Buffer.from('SSHSIG'), v, str(keyBlob), str(namespace), str(reserved), str(hash), str(Buffer.concat([str(sigType), str(signature)])), trailing]);
  return armor(blob);
}

export const armor = (blob) => `-----BEGIN SSH SIGNATURE-----\n${blob.toString('base64').match(/.{1,70}/g).join('\n')}\n-----END SSH SIGNATURE-----\n`;
