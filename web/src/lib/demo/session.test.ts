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

  test("director gets an actor's sound list and plays a chosen sound on a chosen line", () => {
    const s = make(new MemoryStorage(), "director");
    clock.advance(1000, s);
    const coda = lastState().peers.find((p) => p.name === "Coda")!;
    expect(coda.caps).toContain("soundpad.list");
    expect(coda.soundpad).toMatchObject({ available: true, status: "STOPPED", volume: 80, muted: false });

    s.handle({ call: "requestSounds", args: { id: coda.id } });
    const lists = events.filter((e): e is Extract<AgentEvent, { type: "sounds" }> => e.type === "sounds");
    expect(lists).toHaveLength(1);
    const list = lists[0];
    expect(list).toMatchObject({ peerId: coda.id, total: 8 });
    expect(new Set(list.sounds.map((x) => x.key)).size).toBe(8);
    expect(list.sounds.every((x) => /^[0-9a-f]{16}$/.test(x.key) && !("path" in x))).toBe(true);

    const pick = list.sounds[2];
    s.handle({ call: "play", args: { ids: [coda.id], sound: { key: pick.key }, lines: "speakers", label: pick.title } });
    let peer = lastState().peers.find((p) => p.id === coda.id)!;
    expect(peer.activity).toBe("playing");
    expect(peer.soundpad).toMatchObject({ status: "PLAYING", title: pick.title, key: pick.key, index: pick.index, lines: "speakers", durationMs: pick.durationMs });
    expect(events.some((e) => e.type === "log" && e.entry.level === "success" && e.entry.text.includes(pick.title))).toBe(true);

    // Positions move in ~140 ms steps, like Soundpad's
    clock.advance(1000, s);
    const position = lastState().peers.find((p) => p.id === coda.id)!.soundpad!.positionMs;
    expect(position).toBeGreaterThan(0);
    expect(position % 140).toBe(0);
  });

  test("director's transport: pause, resume, seek, jump, volume, mute, stop", () => {
    const s = make(new MemoryStorage(), "director");
    clock.advance(1000, s);
    const coda = lastState().peers.find((p) => p.name === "Coda")!;
    const sp = () => lastState().peers.find((p) => p.id === coda.id)!.soundpad!;
    const ids = [coda.id];
    s.handle({ call: "playIndex", args: { ids, index: 8 } }); // "Phone ring", 5.9 s
    expect(sp()).toMatchObject({ status: "PLAYING", index: 8, title: "Phone ring", lines: "both" });

    clock.advance(1000, s);
    s.handle({ call: "transport", args: { ids, action: "pause" } });
    const paused = sp().positionMs;
    expect(sp().status).toBe("PAUSED");
    clock.advance(1000, s);
    expect(sp().positionMs).toBe(paused);
    s.handle({ call: "transport", args: { ids, action: "resume" } });
    expect(sp().status).toBe("PLAYING");

    s.handle({ call: "transport", args: { ids, action: "seek", value: 2000 } });
    expect(sp().positionMs).toBe(2000);
    s.handle({ call: "transport", args: { ids, action: "jump", value: -5000 } });
    expect(sp().positionMs).toBe(0);
    s.handle({ call: "transport", args: { ids, action: "volume", value: 35 } });
    s.handle({ call: "transport", args: { ids, action: "mute" } });
    expect(sp()).toMatchObject({ volume: 35, muted: true });
    s.handle({ call: "transport", args: { ids, action: "unmute" } });
    expect(sp().muted).toBe(false);

    s.handle({ call: "transport", args: { ids, action: "stop" } });
    expect(sp()).toMatchObject({ status: "STOPPED", positionMs: 0, title: null, lines: null });
    expect(lastState().peers.find((p) => p.id === coda.id)!.activity).toBe("idle");

    // A sound that plays to its end stops by itself
    s.handle({ call: "playIndex", args: { ids, index: 1 } }); // 3 s
    clock.advance(3500, s);
    expect(sp().status).toBe("STOPPED");
  });

  test("Play #N reaches a v0.3 actor; choosing a sound or an actor without Soundpad doesn't", () => {
    const s = make(new MemoryStorage(), "director");
    clock.advance(1000, s);
    const peers = lastState().peers;
    const quincey = peers.find((p) => p.name === "Quincey")!;
    const juno = peers.find((p) => p.name === "Juno")!;
    expect(quincey.soundpad).toBeNull();
    expect(juno.soundpad).toMatchObject({ available: false });

    s.handle({ call: "playIndex", args: { ids: [quincey.id], index: 3 } });
    expect(lastState().peers.find((p) => p.id === quincey.id)!.activity).toBe("playing");

    s.handle({ call: "play", args: { ids: [quincey.id], sound: { key: "0123456789abcdef" }, lines: "mic" } });
    expect(events.some((e) => e.type === "toast" && e.level === "error" && e.text.includes("v0.3"))).toBe(true);

    s.handle({ call: "requestSounds", args: { id: juno.id } });
    expect(events.some((e) => e.type === "sounds")).toBe(false);
    s.handle({ call: "playIndex", args: { ids: [juno.id], index: 1 } });
    expect(lastState().peers.find((p) => p.id === juno.id)!.activity).toBe("idle");
    expect(events.some((e) => e.type === "log" && e.entry.level === "warning" && e.entry.text.startsWith("Juno"))).toBe(true);
  });

  test("GO plays every targeted actor's selected sound; STOP stops it", () => {
    const s = make(new MemoryStorage(), "director");
    clock.advance(1000, s);
    const coda = lastState().peers.find((p) => p.name === "Coda")!;
    s.handle({ call: "setTargets", args: { ids: [coda.id] } });
    s.handle({ call: "cue", args: { command: "go" } });
    expect(lastState().peers.find((p) => p.id === coda.id)!.soundpad).toMatchObject({ status: "PLAYING", title: null, lines: "both" });
    s.handle({ call: "cue", args: { command: "stop" } });
    expect(lastState().peers.find((p) => p.id === coda.id)!.soundpad!.status).toBe("STOPPED");
  });

  test("actor's Soundpad settings: default line, adding received files, starting Soundpad, Detect", () => {
    const s = make(new MemoryStorage(), "actor");
    clock.advance(3000, s);
    expect(lastState().actor!.soundpad).toMatchObject({ defaultLines: "both", autoAddReceived: true, autoLaunch: false, path: "", volume: 80, muted: false });
    s.handle({ call: "setActorLocal", args: { defaultLines: "mic", autoAddReceived: false, autoLaunch: true, soundpadPath: "  D:\\Apps\\Soundpad.exe " } });
    expect(lastState().actor!.soundpad).toMatchObject({ defaultLines: "mic", autoAddReceived: false, autoLaunch: true, path: "D:\\Apps\\Soundpad.exe" });
    s.handle({ call: "detectSoundpad" });
    expect(lastState().actor!.soundpad.path).toBe("C:\\Program Files\\Soundpad\\Soundpad.exe");
    expect(events.some((e) => e.type === "toast" && e.level === "success")).toBe(true);

    // A cue plays the selected sound on both lines
    clock.advance(9000, s);
    const cue = events.find((e) => e.type === "state" && e.state.actor?.soundpad.playback?.status === "PLAYING");
    expect(cue && cue.type === "state" && cue.state.actor!.soundpad.playback!.lines).toBe("both");
  });

  test("director arms sounds: GO plays them, a v0.3 actor only by number, disarm goes back to GO", () => {
    const s = make(new MemoryStorage(), "director");
    clock.advance(1000, s);
    const by = (name: string) => lastState().peers.find((p) => p.name === name)!;
    const [coda, infinity, quincey] = [by("Coda"), by("Infinity"), by("Quincey")];
    s.handle({ call: "setTargets", args: { ids: [coda.id, infinity.id, quincey.id] } });
    s.handle({ call: "requestSounds", args: { id: coda.id } });
    const list = [...events].reverse().find((e) => e.type === "sounds");
    const scene2 = list && list.type === "sounds" ? list.sounds[1] : null;
    s.handle({ call: "arm", args: { id: coda.id, sound: { key: scene2!.key }, label: scene2!.title, lines: "speakers" } });
    s.handle({ call: "arm", args: { id: quincey.id, sound: { key: scene2!.key }, label: "x" } });
    expect(events.some((e) => e.type === "toast" && e.level === "error" && e.text.includes("by its number"))).toBe(true);
    s.handle({ call: "arm", args: { id: quincey.id, sound: { index: 3 }, label: "Sound 3" } });
    expect(Object.keys(lastState().director!.armed).sort()).toEqual([coda.id, quincey.id].sort());

    s.handle({ call: "cue", args: { command: "go" } });
    expect(by("Coda").soundpad).toMatchObject({ status: "PLAYING", title: scene2!.title, lines: "speakers" });
    expect(by("Infinity").soundpad).toMatchObject({ status: "PLAYING", title: null, lines: "both" });
    expect(by("Coda").lastLateMs).not.toBeNull();
    expect(Object.keys(lastState().director!.armed)).toHaveLength(2); // still armed after GO
    s.handle({ call: "cue", args: { command: "stop" } });

    s.handle({ call: "disarm", args: { id: coda.id } });
    s.handle({ call: "cue", args: { command: "go" } });
    expect(by("Coda").soundpad).toMatchObject({ status: "PLAYING", title: null });
  });

  test("director timing: lead, per-actor delay, calibration", () => {
    const s = make(new MemoryStorage(), "director");
    clock.advance(1000, s);
    expect(lastState().director!.leadMs).toBe(300);
    expect(lastState().clock.synced).toBe(true);
    s.handle({ call: "setDirectorLocal", args: { leadMs: 5000 } });
    expect(lastState().director!.leadMs).toBe(2000);
    const coda = lastState().peers.find((p) => p.name === "Coda")!;
    expect(coda.delayMs).toBe(0);
    s.handle({ call: "setDelay", args: { id: coda.id, ms: 150 } });
    expect(lastState().peers.find((p) => p.id === coda.id)!.delayMs).toBe(150);
    s.handle({ call: "calibrate", args: { id: coda.id } });
    clock.advance(2000, s);
    expect(lastState().peers.find((p) => p.id === coda.id)!.soundpad!.startLatencyMs).toBeGreaterThan(40);
    const quincey = lastState().peers.find((p) => p.name === "Quincey")!;
    s.handle({ call: "calibrate", args: { id: quincey.id } });
    expect(events.some((e) => e.type === "toast" && e.text.includes("too old to calibrate"))).toBe(true);
  });

  test("actor: countdown before a Play in 3s, calibration, compensation", () => {
    const s = make(new MemoryStorage(), "actor");
    clock.advance(3000, s);
    expect(lastState().actor!.timing).toEqual({ startLatencyMs: 60, measured: false, samples: 0, autoCompensate: true, delayMs: 0 });
    // The second incoming cue is a Play in 3s: the countdown shows, then GO
    for (let waited = 0; !lastState().countdown && waited < 30_000; waited += 250) clock.advance(250, s);
    const countdown = lastState().countdown;
    expect(countdown?.durationMs).toBe(3000);
    clock.advance(3500, s);
    expect(lastState().countdown).toBeNull();
    expect(lastState().actor!.lastCue?.command).toBe("*go");

    s.handle({ call: "calibrate", args: {} });
    clock.advance(2000, s);
    expect(lastState().actor!.timing).toMatchObject({ measured: true, samples: 1 });
    s.handle({ call: "setActorLocal", args: { autoCompensateLatency: false } });
    expect(lastState().actor!.timing.autoCompensate).toBe(false);
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
