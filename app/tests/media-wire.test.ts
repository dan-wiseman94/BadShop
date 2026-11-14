import { describe, expect, it } from 'vitest';
import { binaryFrame } from '../src/mediaWire';

function frame(bytes: Uint8Array, length = bytes.length) {
  const header = new TextEncoder().encode(JSON.stringify({ jsonrpc: '2.0', id: 1,
    result: { meta: {}, mime: 'image/png', byte_length: length } }));
  const buffer = new ArrayBuffer(8 + header.length + bytes.length);
  const out = new Uint8Array(buffer);
  out.set(new TextEncoder().encode('BSM1'));
  new DataView(buffer).setUint32(4, header.length);
  out.set(header, 8); out.set(bytes, header.length + 8);
  return buffer;
}

describe('binary media framing', () => {
  it('separates metadata validation from exact image bytes', async () => {
    const parsed = binaryFrame(frame(new Uint8Array([0, 255, 12])));
    expect(parsed.envelope.result).toEqual({ meta: {}, mime: 'image/png', data: '' });
    expect(parsed.byteLength).toBe(3);
    expect(parsed.blob.size).toBe(3);
    expect(parsed.blob.type).toBe('image/png');
  });
  it('rejects truncated, oversized and inconsistent frames', () => {
    expect(() => binaryFrame(new ArrayBuffer(3))).toThrow();
    expect(() => binaryFrame(frame(new Uint8Array([1]), 2))).toThrow();
    const invalid = frame(new Uint8Array([1]));
    new DataView(invalid).setUint32(4, 2 ** 21);
    expect(() => binaryFrame(invalid)).toThrow();
  });
});
