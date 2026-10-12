// Test-only zip builder written against Node's zlib, independent of src/zip.mjs, so the
// reader is not only tested against its own writer. Can emit deflate or stored entries and
// zip64 records (saturated 32-bit fields plus zip64 extra fields and end records).
import * as zlib from 'node:zlib';
const { deflateRawSync } = zlib;

function crc32(buf) {
  if (zlib.crc32) return zlib.crc32(buf) >>> 0; // Node 22.2+
  let c, crc = ~0;
  for (const b of buf) { c = (crc ^ b) & 0xff; for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1; crc = (crc >>> 8) ^ c; }
  return ~crc >>> 0;
}

export function nodeZip(files, { method = 8, zip64 = false, flags = 0 } = {}) {
  const locals = [], centrals = [];
  let offset = 0;
  for (const [name, content] of Object.entries(files)) {
    const raw = Buffer.from(content), data = method === 8 ? deflateRawSync(raw) : raw, n = Buffer.from(name);
    const h = Buffer.alloc(30);
    h.writeUInt32LE(0x04034b50, 0); h.writeUInt16LE(zip64 ? 45 : 20, 4); h.writeUInt16LE(flags, 6); h.writeUInt16LE(method, 8);
    h.writeUInt32LE(crc32(raw), 14); h.writeUInt32LE(data.length, 18); h.writeUInt32LE(raw.length, 22); h.writeUInt16LE(n.length, 26);
    let extra = Buffer.alloc(0);
    if (zip64) { extra = Buffer.alloc(28); extra.writeUInt16LE(1, 0); extra.writeUInt16LE(24, 2); extra.writeBigUInt64LE(BigInt(raw.length), 4); extra.writeBigUInt64LE(BigInt(data.length), 12); extra.writeBigUInt64LE(BigInt(offset), 20); }
    const c = Buffer.alloc(46);
    c.writeUInt32LE(0x02014b50, 0); c.writeUInt16LE(45, 4); c.writeUInt16LE(zip64 ? 45 : 20, 6); c.writeUInt16LE(flags, 8); c.writeUInt16LE(method, 10);
    c.writeUInt32LE(crc32(raw), 16);
    c.writeUInt32LE(zip64 ? 0xffffffff : data.length, 20); c.writeUInt32LE(zip64 ? 0xffffffff : raw.length, 24);
    c.writeUInt16LE(n.length, 28); c.writeUInt16LE(extra.length, 30); c.writeUInt32LE(zip64 ? 0xffffffff : offset, 42);
    locals.push(h, n, data); centrals.push(Buffer.concat([c, n, extra]));
    offset += h.length + n.length + data.length;
  }
  const cd = Buffer.concat(centrals), count = centrals.length;
  const tail = [];
  if (zip64) {
    const z = Buffer.alloc(56);
    z.writeUInt32LE(0x06064b50, 0); z.writeBigUInt64LE(44n, 4); z.writeUInt16LE(45, 12); z.writeUInt16LE(45, 14);
    z.writeBigUInt64LE(BigInt(count), 24); z.writeBigUInt64LE(BigInt(count), 32); z.writeBigUInt64LE(BigInt(cd.length), 40); z.writeBigUInt64LE(BigInt(offset), 48);
    const loc = Buffer.alloc(20);
    loc.writeUInt32LE(0x07064b50, 0); loc.writeBigUInt64LE(BigInt(offset + cd.length), 8); loc.writeUInt32LE(1, 16);
    tail.push(z, loc);
  }
  const e = Buffer.alloc(22);
  e.writeUInt32LE(0x06054b50, 0);
  e.writeUInt16LE(zip64 ? 0xffff : count, 8); e.writeUInt16LE(zip64 ? 0xffff : count, 10);
  e.writeUInt32LE(zip64 ? 0xffffffff : cd.length, 12); e.writeUInt32LE(zip64 ? 0xffffffff : offset, 16);
  return Buffer.concat([...locals, cd, ...tail, e]);
}
