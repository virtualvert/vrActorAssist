/** The two jobs Normalize folder runs on decoded audio, shared by the worker and the fallback. */

import { measure, type Loudness } from "./loudness";
import { encodeWav16, type Pcm } from "./wav";

export type Job = { op: "measure"; pcm: Pcm } | { op: "render"; pcm: Pcm; gainDb: number };
export type JobResult = { loudness: Loudness } | { wav: Uint8Array<ArrayBuffer> };

export function run(job: Job): JobResult {
  if (job.op === "measure") return { loudness: measure(job.pcm.channels, job.pcm.rate) };
  return { wav: encodeWav16(job.pcm, job.gainDb) };
}
