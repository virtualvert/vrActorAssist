// Fixtures shared by the *.test.ts files. App code never imports this.

import type { AppState, Peer } from "./protocol";

/** An online peer (named after its id) with a 40 ms link; override what a test cares about. */
export function peer(id: string, role: Peer["role"], extra: Partial<Peer> = {}): Peer {
  return { id, name: id, role, status: "online", latencyMs: 40, activity: "idle", self: false, caps: [], soundpad: null, delayMs: null, lastLateMs: null, ...extra };
}

/** A connected director's state with nothing in it; override what a test cares about. */
export function appState(extra: Partial<AppState> = {}): AppState {
  return {
    appVersion: "test",
    demo: true,
    logDir: null,
    role: "director",
    prefs: { theme: "dark", scale: 1, vrMode: false, reduceMotion: false },
    profile: { name: "Dir", serverUrl: "ws://x", hasSecret: true },
    connection: { status: "connected", detail: "", host: "relay", serverVersion: "0.4.0", legacy: false },
    peers: [],
    pending: [],
    offline: [],
    targets: [],
    countdown: null,
    clock: { synced: false, offsetMs: null, rttMs: null },
    actor: null,
    camera: null,
    director: null,
    ...extra,
  };
}
