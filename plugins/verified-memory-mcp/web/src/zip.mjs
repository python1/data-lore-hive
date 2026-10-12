// Minimal zip reader and writer for the pack maker. No imports; runs in browsers and Node 22+.
// Reader: random access through a source, so a multi-gigabyte export with media is never loaded
// whole; only the central directory and the entries asked for are read. Stored and deflate
// entries, zip64, CRC-checked. Writer: stored entries, UTF-8 names, fixed timestamp, so the
// same files always give the same bytes.

export class ZipError extends Error {}

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
  return t;
})();
export function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

/** Source over bytes already in memory. */
export function bytesSource(bytes) {
  return { size: bytes.length, read: async (offset, length) => bytes.subarray(offset, offset + length) };
}
/** Source over a File or Blob; reads only the slices asked for. */
export function blobSource(blob) {
  return { size: blob.size, read: async (offset, length) => new Uint8Array(await blob.slice(offset, offset + length).arrayBuffer()) };
}

const view = (b) => new DataView(b.buffer, b.byteOffset, b.byteLength);
function u64(dv, at) {
  const n = dv.getBigUint64(at, true);
  if (n > BigInt(Number.MAX_SAFE_INTEGER)) throw new ZipError('zip64 value too large');
  return Number(n);
}

export async function isZip(source) {
  if (source.size < 4) return false;
  const head = view(await source.read(0, 4));
  return head.getUint32(0, true) === 0x04034b50 || head.getUint32(0, true) === 0x06054b50;
}

/** Lists entries. Each has { name, size, compressedSize, method, flags, crc, localOffset }. */
export async function openZip(source) {
  const tailLength = Math.min(source.size, 22 + 65535);
  const tailStart = source.size - tailLength;
  const tail = await source.read(tailStart, tailLength);
  const tv = view(tail);
  let eocd = -1;
  for (let i = tail.length - 22; i >= 0; i--) if (tv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) throw new ZipError('not a zip file (no end of central directory)');
  let count = tv.getUint16(eocd + 10, true);
  let cdSize = tv.getUint32(eocd + 12, true);
  let cdOffset = tv.getUint32(eocd + 16, true);
  if (count === 0xffff || cdSize === 0xffffffff || cdOffset === 0xffffffff) {
    if (eocd < 20 || tv.getUint32(eocd - 20, true) !== 0x07064b50) throw new ZipError('zip64 locator missing');
    const z = view(await source.read(u64(tv, eocd - 20 + 8), 56));
    if (z.getUint32(0, true) !== 0x06064b50) throw new ZipError('zip64 end of central directory missing');
    count = u64(z, 32); cdSize = u64(z, 40); cdOffset = u64(z, 48);
  }
  if (cdOffset + cdSize > source.size) throw new ZipError('truncated zip (central directory past end of file)');
  const cd = await source.read(cdOffset, cdSize);
  const dv = view(cd);
  const names = new TextDecoder('utf-8');
  const entries = [];
  let at = 0;
  for (let i = 0; i < count; i++) {
    if (at + 46 > cd.length || dv.getUint32(at, true) !== 0x02014b50) throw new ZipError('corrupt zip central directory');
    const nameLength = dv.getUint16(at + 28, true), extraLength = dv.getUint16(at + 30, true), commentLength = dv.getUint16(at + 32, true);
    const entry = {
      name: names.decode(cd.subarray(at + 46, at + 46 + nameLength)),
      flags: dv.getUint16(at + 8, true), method: dv.getUint16(at + 10, true), crc: dv.getUint32(at + 16, true),
      compressedSize: dv.getUint32(at + 20, true), size: dv.getUint32(at + 24, true), localOffset: dv.getUint32(at + 42, true)
    };
    // zip64 extra field: 64-bit values appear only for the fields saturated at 0xffffffff, in this order.
    for (let e = at + 46 + nameLength; e + 4 <= at + 46 + nameLength + extraLength;) {
      const id = dv.getUint16(e, true), length = dv.getUint16(e + 2, true);
      if (id === 0x0001) {
        let p = e + 4;
        for (const key of ['size', 'compressedSize', 'localOffset']) if (entry[key] === 0xffffffff) { entry[key] = u64(dv, p); p += 8; }
      }
      e += 4 + length;
    }
    entries.push(entry);
    at += 46 + nameLength + extraLength + commentLength;
  }
  return entries;
}

async function inflateRaw(bytes) {
  const stream = new Blob([bytes]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

/** Reads one entry's bytes, refusing entries over maxSize, encrypted entries and CRC mismatches. */
export async function readEntry(source, entry, maxSize = Infinity) {
  if (entry.flags & 1) throw new ZipError(`${entry.name}: encrypted zip entries are not supported`);
  if (entry.size > maxSize) throw new ZipError(`${entry.name}: too large to open in a browser (${entry.size} bytes)`);
  const local = view(await source.read(entry.localOffset, 30));
  if (local.byteLength < 30 || local.getUint32(0, true) !== 0x04034b50) throw new ZipError(`${entry.name}: corrupt local header`);
  const start = entry.localOffset + 30 + local.getUint16(26, true) + local.getUint16(28, true);
  if (start + entry.compressedSize > source.size) throw new ZipError(`${entry.name}: truncated`);
  const raw = await source.read(start, entry.compressedSize);
  let data;
  if (entry.method === 0) data = raw;
  else if (entry.method === 8) {
    try { data = await inflateRaw(raw); } catch { throw new ZipError(`${entry.name}: corrupt compressed data`); }
  } else throw new ZipError(`${entry.name}: unsupported compression method ${entry.method}`);
  if (data.length !== entry.size || crc32(data) !== entry.crc) throw new ZipError(`${entry.name}: CRC or size mismatch (damaged download?)`);
  return data;
}

/** [{ name, data: Uint8Array }] -> zip bytes. Stored, UTF-8 names, 1980-01-01 00:00 timestamps. */
export function writeZip(files) {
  const encoder = new TextEncoder();
  const parts = [], central = [];
  let offset = 0;
  for (const { name, data } of files) {
    const n = encoder.encode(name), crc = crc32(data);
    if (data.length >= 0xffffffff || offset >= 0xffffffff) throw new ZipError('pack too large for a zip');
    const local = new Uint8Array(30 + n.length), lv = view(local);
    lv.setUint32(0, 0x04034b50, true); lv.setUint16(4, 20, true); lv.setUint16(6, 0x0800, true);
    lv.setUint16(12, 0x0021, true); lv.setUint32(14, crc, true); lv.setUint32(18, data.length, true); lv.setUint32(22, data.length, true);
    lv.setUint16(26, n.length, true); local.set(n, 30);
    const entry = new Uint8Array(46 + n.length), cv = view(entry);
    cv.setUint32(0, 0x02014b50, true); cv.setUint16(4, 20, true); cv.setUint16(6, 20, true); cv.setUint16(8, 0x0800, true);
    cv.setUint16(14, 0x0021, true); cv.setUint32(16, crc, true); cv.setUint32(20, data.length, true); cv.setUint32(24, data.length, true);
    cv.setUint16(28, n.length, true); cv.setUint32(42, offset, true); entry.set(n, 46);
    parts.push(local, data); central.push(entry);
    offset += local.length + data.length;
  }
  const cdSize = central.reduce((s, c) => s + c.length, 0);
  const end = new Uint8Array(22), ev = view(end);
  ev.setUint32(0, 0x06054b50, true); ev.setUint16(8, files.length, true); ev.setUint16(10, files.length, true);
  ev.setUint32(12, cdSize, true); ev.setUint32(16, offset, true);
  const out = new Uint8Array(offset + cdSize + 22);
  let at = 0;
  for (const p of [...parts, ...central, end]) { out.set(p, at); at += p.length; }
  return out;
}
