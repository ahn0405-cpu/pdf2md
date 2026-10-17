/* 브라우저에서 ZIP 파일 만들기 (외부 라이브러리 없음).
 *
 * 서버가 없으므로 압축도 브라우저가 한다. CompressionStream('deflate-raw') 이
 * 있으면 압축(method 8), 없으면 무압축(method 0)으로 저장한다.
 */

const textEncoder = new TextEncoder();

function crc32Table() {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[i] = c >>> 0;
  }
  return table;
}
const CRC_TABLE = crc32Table();

function crc32(bytes) {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) c = CRC_TABLE[(c ^ bytes[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

async function deflateRaw(bytes) {
  if (typeof CompressionStream === 'undefined') return null;
  try {
    const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream('deflate-raw'));
    return new Uint8Array(await new Response(stream).arrayBuffer());
  } catch {
    return null;
  }
}

class ByteWriter {
  constructor() { this.parts = []; this.length = 0; }
  push(bytes) { this.parts.push(bytes); this.length += bytes.length; }
  u16(v) { this.push(new Uint8Array([v & 0xff, (v >> 8) & 0xff])); }
  u32(v) {
    this.push(new Uint8Array([v & 0xff, (v >> 8) & 0xff, (v >> 16) & 0xff, (v >>> 24) & 0xff]));
  }
  blob(type) { return new Blob(this.parts, { type }); }
}

/**
 * @param {Array<{name: string, data: Uint8Array|string}>} entries
 * @returns {Promise<Blob>}
 */
export async function makeZip(entries) {
  const out = new ByteWriter();
  const central = [];

  for (const entry of entries) {
    const nameBytes = textEncoder.encode(entry.name);
    const raw = typeof entry.data === 'string' ? textEncoder.encode(entry.data) : entry.data;
    const compressed = await deflateRaw(raw);
    const useDeflate = compressed !== null && compressed.length < raw.length;
    const body = useDeflate ? compressed : raw;
    const offset = out.length;

    out.u32(0x04034b50);            // local file header
    out.u16(20);                    // version needed
    out.u16(0x0800);                // UTF-8 파일명
    out.u16(useDeflate ? 8 : 0);
    out.u16(0); out.u16(0);         // 시각 (0으로 고정 — 결과가 매번 같도록)
    out.u32(crc32(raw));
    out.u32(body.length);
    out.u32(raw.length);
    out.u16(nameBytes.length);
    out.u16(0);
    out.push(nameBytes);
    out.push(body);

    central.push({ nameBytes, offset, crc: crc32(raw), csize: body.length,
                   size: raw.length, method: useDeflate ? 8 : 0 });
  }

  const centralStart = out.length;
  for (const e of central) {
    out.u32(0x02014b50);            // central directory header
    out.u16(20); out.u16(20);
    out.u16(0x0800);
    out.u16(e.method);
    out.u16(0); out.u16(0);
    out.u32(e.crc);
    out.u32(e.csize);
    out.u32(e.size);
    out.u16(e.nameBytes.length);
    out.u16(0); out.u16(0); out.u16(0); out.u16(0);
    out.u32(0);
    out.u32(e.offset);
    out.push(e.nameBytes);
  }
  const centralSize = out.length - centralStart;

  out.u32(0x06054b50);              // end of central directory
  out.u16(0); out.u16(0);
  out.u16(central.length); out.u16(central.length);
  out.u32(centralSize);
  out.u32(centralStart);
  out.u16(0);

  return out.blob('application/zip');
}
