import { DemoFolders } from "../demo/folders";
import { DemoSession, type DemoStorage, type SavedDemo } from "../demo/session";
import type { AgentEvent, Call, Role } from "../protocol";
import { Emitter, type LinkState, type Transport } from "./types";

const STORAGE_KEY = "vrcas.demo";
const TICK_MS = 250;

const browserStorage: DemoStorage = {
  load() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "null") as Partial<SavedDemo> | null;
    } catch {
      return null;
    }
  },
  save(saved) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(saved));
    } catch {
      // Private windows can refuse storage; the demo still works for this visit.
    }
  },
};

/**
 * Runs a simulated session in the page. Used when no agent is serving the UI.
 * Subscribe with onEvent/onLink before calling start(): the first state is emitted during start().
 */
export class DemoTransport implements Transport {
  readonly kind = "demo";
  readonly folders = new DemoFolders();
  #events = new Emitter<AgentEvent>();
  #link = new Emitter<LinkState>();
  #session: DemoSession | null = null;
  #timer: number | null = null;
  #forcedRole: Role | null | undefined;

  constructor(forcedRole?: Role | null) {
    this.#forcedRole = forcedRole;
  }

  start(): void {
    this.#session = new DemoSession(
      { now: () => Date.now(), random: Math.random },
      browserStorage,
      (event) => this.#events.emit(event),
      this.#forcedRole,
    );
    this.#link.emit("open");
    this.#timer = window.setInterval(() => this.#session?.tick(), TICK_MS);
  }

  stop(): void {
    if (this.#timer !== null) window.clearInterval(this.#timer);
    this.#timer = null;
  }

  onEvent(fn: (event: AgentEvent) => void): () => void {
    return this.#events.on(fn);
  }

  onLink(fn: (state: LinkState) => void): () => void {
    return this.#link.on(fn);
  }

  async call(call: Call): Promise<void> {
    this.#session?.handle(call);
  }
}
