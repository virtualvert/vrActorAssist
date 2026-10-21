/// Normalize folder's number crunching, off the UI thread (spec §8.4.2).

import { run, type Job, type JobResult } from "./jobs";

// The project's TS config uses the DOM lib, so describe the worker scope by hand.
const scope = self as unknown as {
  onmessage: ((event: MessageEvent<Job & { id: number }>) => void) | null;
  postMessage(message: unknown, transfer?: Transferable[]): void;
};

scope.onmessage = (event) => {
  const { id, ...job } = event.data;
  let result: JobResult;
  try {
    result = run(job);
  } catch (err) {
    scope.postMessage({ id, ok: false, error: err instanceof Error ? err.message : String(err) });
    return;
  }
  scope.postMessage({ id, ok: true, result }, "wav" in result ? [result.wav.buffer] : []);
};
