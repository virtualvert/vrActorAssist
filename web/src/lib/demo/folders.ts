import { measure } from "../audio/loudness";
import { encodeWav16 } from "../audio/wav";
import type { FolderListing } from "../protocol";
import type { FolderAccess } from "../transport/types";

const RATE = 48000;
const SAMPLE_FOLDER = "/home/you/EP3 lines";

interface DemoFile {
  path: string;
  seconds: number;
  /** Loudness the generated audio is scaled to; null for digital silence. */
  lufs: number | null;
  stereo: boolean;
  seed: number;
  /** A near-full-scale click, so the copy can't reach the target without passing the ceiling. */
  click?: boolean;
}

// One file for each case the panel shows: quiet, loud, peak-limited, a name clash, short, silent.
const FILES: DemoFile[] = [
  { path: "Scene 1 - Diego.wav", seconds: 4.2, lufs: -24, stereo: false, seed: 1 },
  { path: "Scene 1 - Mira.wav", seconds: 3.6, lufs: -11.5, stereo: true, seed: 2 },
  { path: "Scene 2 - Diego.wav", seconds: 5.1, lufs: -18.5, stereo: false, seed: 3 },
  { path: "Scene 2 - Mira.mp3", seconds: 3, lufs: -20, stereo: true, seed: 4 },
  { path: "Scene 2 - Mira.wav", seconds: 4.4, lufs: -27, stereo: true, seed: 5, click: true },
  { path: "sfx/door.wav", seconds: 0.3, lufs: -14, stereo: true, seed: 6 },
  { path: "sfx/room tone.wav", seconds: 3, lufs: null, stereo: true, seed: 7 },
];

const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/** A pretend folder of voice lines for demo mode. Copies are kept in memory, never written. */
export class DemoFolders implements FolderAccess {
  readonly written = new Map<string, number>();
  #cache = new Map<string, ArrayBuffer>();
  #sizes = new Map<string, number>();

  /** Size of a file in the last listing (the demo session uses it for pretend transfers). */
  sizeOf(path: string): number | undefined {
    return this.#sizes.get(path);
  }

  async pick(): Promise<string | null> {
    await wait(250);
    return SAMPLE_FOLDER;
  }

  async open(folder: string, kind: "audio" | "all" = "audio"): Promise<FolderListing> {
    await wait(120);
    const name = folder.trim() || SAMPLE_FOLDER;
    const files = FILES.map((f) => ({ path: f.path, size: 44 + Math.round(f.seconds * RATE) * (f.stereo ? 4 : 2) }));
    if (kind === "all") {
      // Send files lists everything, the normalized copies and other documents included
      files.push(
        { path: "EP3 script.pdf", size: 182_311 },
        ...[...this.written].map(([path, size]) => ({ path: `normalized/${path}`, size })),
      );
      files.sort((a, b) => a.path.localeCompare(b.path, undefined, { sensitivity: "base" }));
    }
    for (const f of files) this.#sizes.set(f.path, f.size);
    return { folder: name, output: `${name}/normalized`, files, truncated: false };
  }

  async read(_folder: string, path: string): Promise<ArrayBuffer> {
    const file = FILES.find((f) => f.path === path);
    if (!file) throw new Error(`${path} no longer exists`);
    let bytes = this.#cache.get(path);
    if (!bytes) {
      bytes = encodeWav16({ rate: RATE, channels: generate(file) }, 0, () => 0.5).buffer;
      this.#cache.set(path, bytes);
    }
    await wait(60);
    return bytes.slice(0); // decoding detaches the buffer, so hand out a copy
  }

  async write(folder: string, path: string, data: Uint8Array<ArrayBuffer>): Promise<string> {
    await wait(80);
    this.written.set(path, data.byteLength);
    return `${folder}/normalized/${path}`;
  }
}

/** Speech-like audio: harmonics plus breath noise, in syllables and phrases with pauses. */
function generate(file: DemoFile): Float32Array[] {
  const n = Math.round(file.seconds * RATE);
  const x = new Float32Array(n);
  if (file.lufs !== null) {
    let seed = file.seed * 7919;
    const random = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
    const pitch = 105 + file.seed * 21;
    let breath = 0;
    for (let i = 0; i < n; i++) {
      const t = i / RATE;
      const syllable = Math.max(0, Math.sin(Math.PI * 4 * t + file.seed)) ** 2;
      const phrase = Math.floor(t / 1.2) % 3 === 2 ? 0.04 : 1;
      breath += 0.3 * (random() * 2 - 1 - breath);
      const tone = Math.sin(2 * Math.PI * pitch * t) + 0.5 * Math.sin(4 * Math.PI * pitch * t) + 0.25 * Math.sin(6 * Math.PI * pitch * t);
      const fade = Math.min(1, i / 480, (n - 1 - i) / 480);
      x[i] = fade * syllable * phrase * (0.6 * tone + 0.4 * breath);
    }
  }
  const channels = file.stereo ? [x, x.map((v) => v * 0.9)] : [x];
  if (file.lufs !== null) {
    const gain = Math.pow(10, (file.lufs - measure(channels, RATE).integrated) / 20);
    for (const ch of channels) for (let i = 0; i < n; i++) ch[i] *= gain;
  }
  if (file.click) {
    const at = Math.round(n * 0.6);
    for (const ch of channels) {
      ch[at] = 0.97;
      ch[at + 1] = -0.9;
    }
  }
  return channels;
}
