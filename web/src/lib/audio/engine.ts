/**
 * Decodes audio in the page and runs the measure / render jobs in a worker (spec §8.4.2).
 *
 * Everything is decoded at 48 kHz: the browser resamples other rates, the copies come out at
 * 48 kHz, and the loudness math always sees one rate.
 */

import { run, type Job, type JobResult } from "./jobs";
import type { Loudness } from "./loudness";
import type { Pcm } from "./wav";

export const DECODE_RATE = 48000;

export async function decode(bytes: ArrayBuffer): Promise<Pcm> {
  const context = new OfflineAudioContext(1, 1, DECODE_RATE);
  let buffer: AudioBuffer;
  try {
    buffer = await context.decodeAudioData(bytes);
  } catch {
    throw new Error("Can't decode this file here (unsupported or damaged audio)");
  }
  const channels = Array.from({ length: buffer.numberOfChannels }, (_, c) => {
    const data = new Float32Array(buffer.length);
    buffer.copyFromChannel(data, c);
    return data;
  });
  return { rate: buffer.sampleRate, channels };
}

type Pending = { resolve: (result: JobResult) => void; reject: (error: Error) => void };

export class AudioEngine {
  #worker: Worker | null = null;
  #next = 1;
  #pending = new Map<number, Pending>();

  constructor() {
    try {
      this.#worker = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
      this.#worker.onmessage = (event: MessageEvent<{ id: number; ok: boolean; result?: JobResult; error?: string }>) => {
        const { id, ok, result, error } = event.data;
        const entry = this.#pending.get(id);
        this.#pending.delete(id);
        if (!entry) return;
        if (ok && result) entry.resolve(result);
        else entry.reject(new Error(error ?? "Processing failed"));
      };
      this.#worker.onerror = () => {
        // A worker that can't load: finish the queued jobs in the page from now on.
        this.#worker = null;
        for (const [, entry] of this.#pending) entry.reject(new Error("The audio worker stopped; try again"));
        this.#pending.clear();
      };
    } catch {
      this.#worker = null;
    }
  }

  async measure(bytes: ArrayBuffer): Promise<Loudness> {
    const result = await this.#run({ op: "measure", pcm: await decode(bytes) });
    if (!("loudness" in result)) throw new Error("Unexpected result");
    return result.loudness;
  }

  async render(bytes: ArrayBuffer, gainDb: number): Promise<Uint8Array<ArrayBuffer>> {
    const result = await this.#run({ op: "render", pcm: await decode(bytes), gainDb });
    if (!("wav" in result)) throw new Error("Unexpected result");
    return result.wav;
  }

  dispose(): void {
    this.#worker?.terminate();
    this.#worker = null;
  }

  async #run(job: Job): Promise<JobResult> {
    const worker = this.#worker;
    if (!worker) {
      await new Promise((resolve) => setTimeout(resolve, 0)); // let the UI paint between files
      return run(job);
    }
    const id = this.#next++;
    return new Promise((resolve, reject) => {
      this.#pending.set(id, { resolve, reject });
      worker.postMessage({ id, ...job }, job.pcm.channels.map((c) => c.buffer));
    });
  }
}
