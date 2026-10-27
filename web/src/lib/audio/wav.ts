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

function ascii(view: DataView, offset: number, value: string): void {
  for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
}
