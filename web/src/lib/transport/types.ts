import type { AgentEvent, Call } from "../protocol";

/** State of the link between this page and whatever drives it (agent or demo). */
export type LinkState = "connecting" | "open" | "closed" | "unauthorized";

export interface Transport {
  readonly kind: "agent" | "demo";
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
