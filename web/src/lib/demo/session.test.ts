import { beforeEach, describe, expect, test } from "bun:test";
import type { AgentEvent, AppState } from "../protocol";
import { DemoSession, type DemoStorage, type SavedDemo } from "./session";

class FakeClock {
  t = 1_000_000;
  now = () => this.t;
  random = () => 0.5;
  advance(ms: number, session: DemoSession) {
    const end = this.t + ms;
    while (this.t < end) {
      this.t = Math.min(end, this.t + 250);
      session.tick();
    }
  }
}

class MemoryStorage implements DemoStorage {
  saved: SavedDemo | null = null;
  constructor(initial: Partial<SavedDemo> | null = null) {
    this.saved = initial as SavedDemo | null;
  }
  load() {
    return this.saved;
  }
  save(s: SavedDemo) {
    this.saved = structuredClone(s);
  }
}

let clock: FakeClock;
let events: AgentEvent[];
let lastState: () => AppState;

function make(storage = new MemoryStorage(), role?: SavedDemo["role"]) {
  events = [];
  const session = new DemoSession(clock, storage, (e) => events.push(e), role);
  lastState = () => {
    const states = events.filter((e): e is Extract<AgentEvent, { type: "state" }> => e.type === "state");
    return states[states.length - 1].state;
  };
  return session;
}

beforeEach(() => {
  clock = new FakeClock();
});

describe("DemoSession", () => {
  test("first run waits for a role; picking one connects and is remembered", () => {
    const storage = new MemoryStorage();
    const s = make(storage);
    expect(lastState().role).toBeNull();
    s.handle({ call: "setRole", args: { role: "director" } });
    expect(lastState().connection.status).toBe("disconnected");
    s.handle({ call: "connect" });
    clock.advance(1000, s);
    expect(lastState().connection.status).toBe("connected");
    expect(storage.saved?.role).toBe("director");

    // Next launch opens straight into the saved role.
    const again = make(storage);
    expect(lastState().role).toBe("director");
    clock.advance(1000, again);
    expect(lastState().connection.status).toBe("connected");
  });

  test("actors go through approval before connecting", () => {
    const s = make(new MemoryStorage(), "actor");
    clock.advance(800, s);
    expect(lastState().connection.status).toBe("pending");
    clock.advance(2000, s);
    expect(lastState().connection.status).toBe("connected");
    expect(lastState().actor?.soundpad.state).toBe("simulated");
  });

  test("director GO marks targeted actors as playing and sends traffic", () => {
    const s = make(new MemoryStorage(), "director");
    clock.advance(1000, s);
    const state = lastState();
    const first = state.peers.find((p) => p.role === "actor")!;
    s.handle({ call: "setTargets", args: { ids: [first.id] } });
    s.handle({ call: "cue", args: { command: "go" } });
    const after = lastState();
    expect(after.peers.find((p) => p.id === first.id)?.activity).toBe("playing");
    expect(after.peers.filter((p) => p.activity === "playing")).toHaveLength(1);
    expect(events.some((e) => e.type === "traffic" && e.traffic.kind === "cue" && e.traffic.to.includes(first.id))).toBe(true);
    s.handle({ call: "cue", args: { command: "stop" } });
    expect(lastState().peers.some((p) => p.activity === "playing")).toBe(false);
  });

  test("countdown fires GO after three seconds and STOP cancels it", () => {
    const s = make(new MemoryStorage(), "director");
    clock.advance(1000, s);
    s.handle({ call: "cue", args: { command: "countdown" } });
    expect(lastState().countdown).not.toBeNull();
    clock.advance(3100, s);
    expect(lastState().countdown).toBeNull();
    expect(lastState().peers.some((p) => p.activity === "playing")).toBe(true);

    s.handle({ call: "cue", args: { command: "stop" } });
    s.handle({ call: "cue", args: { command: "countdown" } });
    s.handle({ call: "cue", args: { command: "stop" } });
    clock.advance(3500, s);
    expect(lastState().peers.some((p) => p.activity === "playing")).toBe(false);
  });

  test("a late joiner shows up as pending and can be approved", () => {
    const s = make(new MemoryStorage(), "director");
    clock.advance(9500, s);
    const pending = lastState().pending;
    expect(pending).toHaveLength(1);
    s.handle({ call: "approve", args: { id: pending[0].id } });
    const after = lastState();
    expect(after.pending).toHaveLength(0);
    expect(after.peers.some((p) => p.id === pending[0].id && p.status === "online")).toBe(true);
    expect(after.targets).toContain(pending[0].id);
  });

  test("prefs are clamped and persisted", () => {
    const storage = new MemoryStorage();
    const s = make(storage, "camera");
    s.handle({ call: "setPrefs", args: { scale: 9, theme: "light", vrMode: true } });
    expect(lastState().prefs).toMatchObject({ scale: 2, theme: "light", vrMode: true });
    expect(storage.saved?.prefs.scale).toBe(2);
  });

  test("director sends files: progress, results, a v0.3 actor through the bridge, cancel", () => {
    const s = make(new MemoryStorage(), "director");
    clock.advance(1000, s);
    const peers = lastState().peers;
    const coda = peers.find((p) => p.name === "Coda")!;
    const quincey = peers.find((p) => p.name === "Quincey")!;
    expect(coda.caps).toContain("files");
    expect(quincey.caps).toEqual(["legacy"]);

    s.handle({ call: "sendFiles", args: { folder: "/x", items: [{ path: "Scene 1 - Diego.wav", actorId: coda.id }, { path: "sfx/door.wav", actorId: coda.id }] } });
    let batch = lastState().director!.files.batches[0];
    expect(batch).toMatchObject({ actorName: "Coda", files: 2, state: "sending" });
    clock.advance(500, s);
    expect(lastState().director!.files.batches[0].current?.waiting).toBe(true);
    clock.advance(5000, s);
    batch = lastState().director!.files.batches[0];
    expect(batch).toMatchObject({ state: "done", ok: 2, failed: 0, done: 2 });
    expect(batch.results.map((r) => r.state)).toEqual(["ok", "ok"]);

    s.handle({ call: "sendFiles", args: { folder: "/x", items: [{ path: "a.wav", actorId: quincey.id }] } });
    expect(lastState().director!.files.batches[1]).toMatchObject({ actorName: "Quincey", state: "sending" });
    expect(events.some((e) => e.type === "toast" && e.level === "error")).toBe(false);

    s.handle({ call: "sendFiles", args: { folder: "/x", items: [{ path: "a.wav", actorId: coda.id }, { path: "b.wav", actorId: coda.id }] } });
    clock.advance(1200, s);
    const running = lastState().director!.files.batches[2];
    s.handle({ call: "cancelBatch", args: { id: running.id } });
    expect(lastState().director!.files.batches[2]).toMatchObject({ state: "cancelled", ok: 0, failed: 2 });
  });

  test("actor is asked about incoming files and can accept the rest of the batch", () => {
    const s = make(new MemoryStorage(), "actor");
    clock.advance(3000, s);
    expect(lastState().connection.status).toBe("connected");
    clock.advance(9500, s);
    const incoming = lastState().actor!.files.incoming;
    expect(incoming.map((f) => [f.index, f.count, f.state])).toEqual([[1, 2, "asking"], [2, 2, "asking"]]);
    expect(incoming[1].replaces).toBe(true);
    s.handle({ call: "answerFile", args: { transferId: incoming[0].transferId, accept: true, rest: true } });
    expect(lastState().actor!.files.incoming.every((f) => f.state === "receiving")).toBe(true);
    clock.advance(3000, s);
    const files = lastState().actor!.files;
    expect(files.incoming).toEqual([]);
    expect(files.recent.map((r) => r.ok)).toEqual([true, true]);
    expect(files.recent[0].detail).toBe("replaced your copy");

    s.handle({ call: "setActorLocal", args: { autoAcceptFiles: true, receiveDir: "D:\\Lines" } });
    expect(lastState().actor!.files).toMatchObject({ autoAccept: true, receiveDir: "D:\\Lines" });
  });

  test("camera roll and cut toggle recording", () => {
    const s = make(new MemoryStorage(), "camera");
    clock.advance(3000, s);
    s.handle({ call: "camera", args: { action: "roll" } });
    expect(lastState().camera?.recording).toBe(true);
    expect(lastState().peers.find((p) => p.self)?.activity).toBe("rolling");
    s.handle({ call: "camera", args: { action: "cut" } });
    expect(lastState().camera?.recording).toBe(false);
  });
});
