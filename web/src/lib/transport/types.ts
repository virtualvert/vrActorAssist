import type { AgentEvent, Call, FolderListing } from "../protocol";

/** State of the link between this page and whatever drives it (agent or demo). */
export type LinkState = "connecting" | "open" | "closed" | "unauthorized";

/** Folder access for Normalize folder (spec §8.4.2) and Send files (§8.4). */
export interface FolderAccess {
  /** Native folder dialog. Null when the person cancels; throws when this machine has none. */
  pick(): Promise<string | null>;
  /** "audio" (default): audio files outside normalized/. "all": every non-hidden file, for sending. */
  open(folder: string, kind?: "audio" | "all"): Promise<FolderListing>;
  read(folder: string, path: string): Promise<ArrayBuffer>;
  /** Lengths in ms of audio and video files (from their headers); null for anything else. At most 500 paths per call. */
  durations(folder: string, paths: string[]): Promise<Record<string, number | null>>;
  /** Writes `<folder>/normalized/<path>` and resolves to the full path written. */
  write(folder: string, path: string, data: Uint8Array<ArrayBuffer>): Promise<string>;
}

export interface Transport {
  readonly kind: "agent" | "demo";
  readonly folders: FolderAccess;
  start(): void;
  stop(): void;
  call(call: Call): Promise<void>;
  onEvent(fn: (event: AgentEvent) => void): () => void;
  onLink(fn: (state: LinkState) => void): () => void;
}

/** Small listener set shared by the transports. */
export class Emitter<T> {
  #fns = new Set<(value: T) => void>();

  on(fn: (value: T) => void): () => void {
    this.#fns.add(fn);
    return () => this.#fns.delete(fn);
  }

  emit(value: T): void {
    for (const fn of this.#fns) fn(value);
  }
}
