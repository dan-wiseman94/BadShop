import { object, parseFrame } from './protocol';
import type { Artifact } from './types';

export type BinaryArtifact = { meta: Artifact; mime: string; blob: Blob; byteLength: number };

export function binaryFrame(buffer: ArrayBuffer) {
  if (buffer.byteLength < 8 || buffer.byteLength > 65 * 2 ** 20) throw new Error('Invalid media frame size');
  const bytes = new Uint8Array(buffer);
  if (String.fromCharCode(...bytes.subarray(0, 4)) !== 'BSM1') throw new Error('Invalid media frame version');
  const length = new DataView(buffer).getUint32(4);
  if (length > 2 ** 20 || length + 8 > buffer.byteLength) throw new Error('Invalid media header size');
  const envelope = parseFrame(new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(8, length + 8)));
  if (!object(envelope.result) || typeof envelope.result.mime !== 'string' ||
      envelope.result.byte_length !== buffer.byteLength - length - 8) throw new Error('Invalid media payload size');
  const { byte_length, ...result } = envelope.result;
  return { envelope: { ...envelope, result: { ...result, data: '' } },
    blob: new Blob([buffer.slice(length + 8)], { type: result.mime as string }), byteLength: byte_length as number };
}
