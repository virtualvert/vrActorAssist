import type { AgentEvent, Call, FolderListing } from "../protocol";
import { Emitter, type FolderAccess, type LinkState, type Transport } from "./types";

const CALL_TIMEOUT_MS = 10_000;

/**
 * Talks to the local agent (python -m agent) over /ui/ws.
 *
 * The agent opens this page with a one-time `?t=` token; we trade it for a session cookie
 * before opening the socket, then drop it from the address bar.
 */
export class AgentTransport implements Transport {
  readonly kind = "agent";
  readonly folders: FolderAccess = agentFolders;
  #events = new Emitter<AgentEvent>();
  #link = new Emitter<LinkState>();
  #ws: WebSocket | null = null;
  #nextId = 1;
  #pending = new Map<number, { resolve: () => void; reject: (e: Error) => void; timer: number }>();
  #retryMs = 500;
  #stopped = false;

  start(): void {
    this.#stopped = false;
    void this.#open();
  }

  stop(): void {
    this.#stopped = true;
    this.#ws?.close();
  }

  onEvent(fn: (event: AgentEvent) => void): () => void {
    return this.#events.on(fn);
  }

  onLink(fn: (state: LinkState) => void): () => void {
    return this.#link.on(fn);
  }

  call(call: Call): Promise<void> {
    const ws = this.#ws;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      return Promise.reject(new Error("The vrcActorSync app is not reachable"));
    }
    const id = this.#nextId++;
    return new Promise((resolve, reject) => {
      const timer = window.setTimeout(() => {
        this.#pending.delete(id);
        reject(new Error(`${call.call} timed out`));
      }, CALL_TIMEOUT_MS);
      this.#pending.set(id, { resolve, reject, timer });
      ws.send(JSON.stringify({ id, ...call }));
    });
  }

  async #open(): Promise<void> {
    this.#link.emit("connecting");
    const url = new URL(location.href);
    const token = url.searchParams.get("t");
    if (token) {
      const res = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token }),
        credentials: "same-origin",
      }).catch(() => null);
      url.searchParams.delete("t");
      history.replaceState(null, "", url.pathname + url.search + url.hash);
      if (!res?.ok) {
        this.#link.emit("unauthorized");
        return;
      }
    }

    const scheme = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${location.host}/ui/ws`);
    this.#ws = ws;
    let opened = false;

    ws.onopen = () => {
      opened = true;
      this.#retryMs = 500;
      this.#link.emit("open");
    };
    ws.onmessage = (msg) => {
      const event = JSON.parse(msg.data) as AgentEvent;
      if (event.type === "result") {
        const entry = this.#pending.get(event.id);
        if (!entry) return;
        window.clearTimeout(entry.timer);
        this.#pending.delete(event.id);
        if (event.ok) entry.resolve();
        else entry.reject(new Error(event.error ?? "Request failed"));
        return;
      }
      this.#events.emit(event);
    };
    ws.onclose = (ev) => {
      for (const [, entry] of this.#pending) {
        window.clearTimeout(entry.timer);
        entry.reject(new Error("Connection to the app closed"));
      }
      this.#pending.clear();
      if (this.#stopped) return;
      // 4401 = the agent rejected our session cookie (e.g. the app restarted).
      if (ev.code === 4401 || (!opened && ev.code === 1008)) {
        this.#link.emit("unauthorized");
        return;
      }
      this.#link.emit("closed");
      window.setTimeout(() => void this.#open(), this.#retryMs);
      this.#retryMs = Math.min(this.#retryMs * 2, 5000);
    };
  }
}

/** POST to one of the agent's /api/folders/ endpoints; its `{error}` becomes the thrown message. */
async function post(path: string, body: BodyInit, contentType: string): Promise<Response> {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": contentType }, body, credentials: "same-origin" }).catch(() => null);
  if (!res) throw new Error("The vrcActorSync app is not reachable");
  if (!res.ok) {
    const detail = (await res.json().catch(() => null)) as { error?: string } | null;
    throw new Error(detail?.error ?? `Request failed (${res.status})`);
  }
  return res;
}

const postJson = (path: string, body: object) => post(path, JSON.stringify(body), "application/json");

const agentFolders: FolderAccess = {
  async pick() {
    const res = await postJson("/api/folders/pick", {});
    return ((await res.json()) as { path: string | null }).path;
  },
  async open(folder, kind = "audio") {
    return (await (await postJson("/api/folders/open", { folder, kind })).json()) as FolderListing;
  },
  async read(folder, path) {
    return (await postJson("/api/folders/read", { folder, path })).arrayBuffer();
  },
  async durations(folder, paths) {
    const res = await postJson("/api/folders/durations", { folder, paths });
    return ((await res.json()) as { durations: Record<string, number | null> }).durations;
  },
  async write(folder, path, data) {
    const query = new URLSearchParams({ folder, path });
    const res = await post(`/api/folders/write?${query}`, new Blob([data]), "application/octet-stream");
    return ((await res.json()) as { path: string }).path;
  },
};
