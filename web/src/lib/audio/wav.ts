/** 16-bit PCM WAV files: the output format of Normalize folder (spec §8.4.2). */

export interface Pcm {
  rate: number;
  channels: Float32Array[];
}

const HEADER_BYTES = 44;

/**
 * Interleave, apply `gainDb` and quantise to 16 bit with TPDF dither (±1 LSB).
 * `random` is injectable so tests can make the dither repeatable.
 */
export function encodeWav16(pcm: Pcm, gainDb = 0, random: () => number = Math.random): Uint8Array<ArrayBuffer> {
  const { rate, channels } = pcm;
  const count = channels.length;
  const frames = channels[0]?.length ?? 0;
  const dataBytes = frames * count * 2;
  const buffer = new ArrayBuffer(HEADER_BYTES + dataBytes);
  const view = new DataView(buffer);
  ascii(view, 0, "RIFF");
  view.setUint32(4, 36 + dataBytes, true);
  ascii(view, 8, "WAVE");
  ascii(view, 12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, count, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * count * 2, true);
  view.setUint16(32, count * 2, true);
  view.setUint16(34, 16, true);
  ascii(view, 36, "data");
  view.setUint32(40, dataBytes, true);

  const scale = Math.pow(10, gainDb / 20) * 32767;
  let offset = HEADER_BYTES;
  for (let i = 0; i < frames; i++) {
    for (let c = 0; c < count; c++) {
      const v = channels[c][i] * scale + (random() - random());
      view.setInt16(offset, v >= 32767 ? 32767 : v <= -32768 ? -32768 : Math.round(v), true);
      offset += 2;
    }
  }
  return new Uint8Array(buffer);
}

/** Reads the 16-bit PCM files encodeWav16 writes (and other plain PCM WAVs). */
export function readWav16(bytes: Uint8Array): Pcm {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  if (text(view, 0, 4) !== "RIFF" || text(view, 8, 4) !== "WAVE") throw new Error("Not a WAV file");
  let offset = 12;
  let count = 0;
  let rate = 0;
  while (offset + 8 <= view.byteLength) {
    const id = text(view, offset, 4);
    const size = view.getUint32(offset + 4, true);
    const body = offset + 8;
    if (id === "fmt ") {
      if (view.getUint16(body, true) !== 1 || view.getUint16(body + 14, true) !== 16) throw new Error("Only 16-bit PCM WAV");
      count = view.getUint16(body + 2, true);
      rate = view.getUint32(body + 4, true);
    } else if (id === "data") {
      if (!count) throw new Error("WAV data before its format chunk");
      const frames = Math.floor(size / (2 * count));
      const channels = Array.from({ length: count }, () => new Float32Array(frames));
      for (let i = 0; i < frames; i++) {
        for (let c = 0; c < count; c++) channels[c][i] = view.getInt16(body + (i * count + c) * 2, true) / 32768;
      }
      return { rate, channels };
    }
    offset = body + size + (size % 2);
  }
  throw new Error("WAV file has no data");
}

function ascii(view: DataView, offset: number, value: string): void {
  for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
}

function text(view: DataView, offset: number, length: number): string {
  let out = "";
  for (let i = 0; i < length && offset + i < view.byteLength; i++) out += String.fromCharCode(view.getUint8(offset + i));
  return out;
}
