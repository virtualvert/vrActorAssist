import type { AgentEvent, AppState, Call, LogEntry, LogLevel, Prefs, SoundList, Traffic } from "./protocol";
import type { FolderAccess, LinkState, Transport } from "./transport/types";
import { applyPrefs } from "./prefs";

const MAX_LOGS = 300;
const TOAST_MS = 4500;

export interface Toast {
  id: number;
  level: LogLevel;
  text: string;
}

/** The single reactive store the components read from. */
class AppStore {
  state = $state<AppState | null>(null);
  logs = $state<LogEntry[]>([]);
  toasts = $state<Toast[]>([]);
  link = $state<LinkState>("connecting");
  kind = $state<Transport["kind"] | null>(null);
  unreadLogs = $state(0);
  logOpen = $state(false);
  settingsOpen = $state(false);
  normalizeOpen = $state(false);
  sendOpen = $state(false);
  /** Director: the actor whose Soundpad panel is open (peer id), if any. */
  soundpadFor = $state<string | null>(null);
  /** Director: actors' sound lists, by peer id (they arrive as "sounds" events). */
  sounds = $state<Record<string, SoundList>>({});
  /** True while the first-run flow is on screen, even after a role has been saved. */
  onboarding = $state(false);

  #transport: Transport | null = null;
  #traffic = new Set<(t: Traffic) => void>();
  #toastId = 1;

  attach(transport: Transport): void {
    // Only one driver at a time (hot reload can mount App twice during development).
    this.#transport?.stop();
    this.#transport = transport;
    this.kind = transport.kind;
    transport.onEvent((event) => this.#handle(event, transport));
    transport.onLink((link) => {
      if (transport === this.#transport) this.link = link;
    });
    transport.start();
  }

  /** File access for Normalize folder and Send files, from whichever transport drives the page. */
  get folders(): FolderAccess | null {
    return this.#transport?.folders ?? null;
  }

  /** Sends a call; a refusal is shown as a toast. Resolves to whether it went through. */
  async call(call: Call): Promise<boolean> {
    if (!this.#transport) return false;
    try {
      await this.#transport.call(call);
      return true;
    } catch (err) {
      this.toast("error", err instanceof Error ? err.message : String(err));
      return false;
    }
  }

  /** Update preferences right away (no flash), then persist them through the agent. */
  setPrefs(patch: Partial<Prefs>): void {
    if (this.state) {
      this.state.prefs = { ...this.state.prefs, ...patch };
      applyPrefs(this.state.prefs);
    }
    void this.call({ call: "setPrefs", args: patch });
  }

  onTraffic(fn: (t: Traffic) => void): () => void {
    this.#traffic.add(fn);
    return () => this.#traffic.delete(fn);
  }

  toast(level: LogLevel, text: string): void {
    const id = this.#toastId++;
    this.toasts = [...this.toasts.slice(-3), { id, level, text }];
    setTimeout(() => this.dismissToast(id), TOAST_MS);
  }

  dismissToast(id: number): void {
    this.toasts = this.toasts.filter((t) => t.id !== id);
  }

  openLog(open: boolean): void {
    this.logOpen = open;
    if (open) this.unreadLogs = 0;
  }

  #handle(event: AgentEvent, from: Transport): void {
    if (from !== this.#transport) return;
    switch (event.type) {
      case "state":
        this.state = event.state;
        applyPrefs(event.state.prefs);
        break;
      case "logs":
        this.logs = event.entries.slice(-MAX_LOGS);
        break;
      case "log":
        this.logs = [...this.logs.slice(-(MAX_LOGS - 1)), event.entry];
        if (!this.logOpen && event.entry.level !== "info") this.unreadLogs += 1;
        break;
      case "toast":
        this.toast(event.level, event.text);
        break;
      case "traffic":
        for (const fn of this.#traffic) fn(event.traffic);
        break;
      case "sounds": {
        const { type: _type, ...list } = event;
        this.sounds = { ...this.sounds, [list.peerId]: list };
        break;
      }
    }
  }
}

export const app = new AppStore();
