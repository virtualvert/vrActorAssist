import type { AgentEvent, Call, FolderListing } from "../protocol";

/** State of the link between this page and whatever drives it (agent or demo). */
export type LinkState = "connecting" | "open" | "closed" | "unauthorized";

/** Reading and writing audio files for Normalize folder (spec §8.4.2). */
export interface FolderAccess {
  /** Native folder dialog. Null when the person cancels; throws when this machine has none. */
  pick(): Promise<string | null>;
  open(folder: string): Promise<FolderListing>;
  read(folder: string, path: string): Promise<ArrayBuffer>;
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
