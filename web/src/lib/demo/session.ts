// A self-contained, simulated session so the UI can be seen and tested without the
// agent or a relay: `bun run dev` (no agent running) or any page URL with `?demo`.
// Pure TypeScript with an injectable clock and storage, so it runs under `bun test`.

import {
  clampScale,
  type ActorLocal,
  type AgentEvent,
  type AppState,
  type Call,
  type CameraLocal,
  type ClockState,
  type IncomingFile,
  type Lines,
  type LogLevel,
  type Peer,
  type PeerSoundpad,
  type Prefs,
  type Role,
  type SendBatch,
  type SoundEntry,
  type SoundRef,
  type SoundpadPlayback,
  type TrafficKind,
} from "../protocol";
import { baseName } from "../files/character";
import { armedText, armReason, DEFAULT_START_LATENCY_MS, delayText } from "../timing";

export interface DemoClock {
  now(): number;
  random(): number;
}

export interface SavedDemo {
  role: Role | null;
  prefs: Prefs;
  name: string;
  serverUrl: string;
}

export interface DemoStorage {
  load(): Partial<SavedDemo> | null;
  save(saved: SavedDemo): void;
}

interface CastMember {
  name: string;
  role: Role;
  baseLatency: number;
  /** Runs the v0.3 client (receives files through the relay's bridge). */
  legacy?: boolean;
}

const CAST: CastMember[] = [
  { name: "Mira", role: "director", baseLatency: 24 },
  { name: "Coda", role: "actor", baseLatency: 38 },
  { name: "Infinity", role: "actor", baseLatency: 61 },
  { name: "Quincey", role: "actor", baseLatency: 240, legacy: true },
  { name: "Juno", role: "actor", baseLatency: 85 },
  { name: "Cam A", role: "camera", baseLatency: 30 },
  { name: "Cam B", role: "camera", baseLatency: 118 },
];

const LATE_JOINER: CastMember = { name: "Nova", role: "actor", baseLatency: 52 };

export const DEFAULT_NAMES: Record<Role, string> = {
  director: "Director",
  actor: "Rowan",
  camera: "Cam C",
};

export const DEFAULT_PREFS: Prefs = { theme: "system", scale: 1, vrMode: false, reduceMotion: false };

const HOST = "relay.demo";
const JITTER_EVERY_MS = 2000;
const INCOMING_CUE_EVERY_MS = 14_000;
const COUNTDOWN_MS = 3000;
const SELF_SOUND_MS = 5000;
/** Simulated transfer speed for Send files. */
const DEMO_BYTES_PER_S = 3 * 1024 * 1024;
const DEMO_ACCEPT_MS = 900;
const INCOMING_FILES_AFTER_MS = 9000;
const RECEIVE_DIR = "C:\\Users\\you\\Documents\\vrcActorSync";
/** Juno's Soundpad isn't running in the demo, so the "unavailable" look shows up. */
const SOUNDPAD_OFF = "Juno";
const SELECTED_SOUND_MS = 6000;
const DEMO_SOUNDPAD_EXE = "C:\\Program Files\\Soundpad\\Soundpad.exe";
const NO_CLOCK: ClockState = { synced: false, offsetMs: null, rttMs: null };
const DEMO_CLOCK: ClockState = { synced: true, offsetMs: 12, rttMs: 46 };
const DEFAULT_LEAD_MS = 300;
const ACTOR_CAPS = ["soundpad", "soundpad.lines", "soundpad.position", "soundpad.list", "soundpad.add", "soundpad.calibrate", "osc", "files", "schedule"];

/** HH:MM:SS.mmm, as the agent logs server times. */
function serverTime(ms: number): string {
  const d = new Date(ms);
  const two = (n: number) => String(n).padStart(2, "0");
  return `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}.${String(d.getMilliseconds()).padStart(3, "0")}`;
}

/** A stable 16-hex-digit key, like the agent's hash of a sound's path. */
export function demoKey(text: string): string {
  let a = 0x811c9dc5;
  let b = 0x01000193;
  for (const ch of text) {
    a = Math.imul(a ^ ch.charCodeAt(0), 0x01000193) >>> 0;
    b = Math.imul(b ^ ch.charCodeAt(0), 0x5bd1e995) >>> 0;
  }
  return a.toString(16).padStart(8, "0") + b.toString(16).padStart(8, "0");
}

/** The pretend sound list of a demo actor. */
export function demoSounds(name: string): SoundEntry[] {
  const titles = [`Scene 1 - ${name}`, `Scene 2 - ${name}`, `Scene 3 - ${name}`, "Door slam", "Room tone", `Scene 4 - ${name} (alt)`, "Applause", "Phone ring"];
  return titles.map((title, i) => ({ index: i + 1, key: demoKey(`${name}/${title}`), title, durationMs: 3000 + ((i * 1700) % 9000) }));
}

function stoppedPlayback(): SoundpadPlayback {
  return { status: "STOPPED", positionMs: 0, durationMs: 0, title: null, lines: null };
}

export function peerId(name: string): string {
  return `peer:${name.toLowerCase().replace(/\s+/g, "-")}`;
}

export class DemoSession {
  state: AppState;
  #clock: DemoClock;
  #storage: DemoStorage;
  #emit: (event: AgentEvent) => void;
  #timers: { at: number; fn: () => void }[] = [];
  #playingUntil = new Map<string, number>();
  /** When the simulated Soundpad started the current sound (actor role). */
  #selfPlayStart: number | null = null;
  #cast = new Map<string, CastMember>();
  #connectedAt: number | null = null;
  #lastJitter = 0;
  #nextIncomingCue = 0;
  #logId = 1;
  #changed = false;
  #batchId = 1;
  /** Simulated sends (director role): when each batch's current file started, and its sizes. */
  #sending = new Map<string, { started: number; sizes: number[]; index: number; accepted: boolean }>();
  #sizeOf: (path: string) => number | undefined;
  /** Demo actors' Soundpad clocks: when the current sound started (adjusted for pauses and seeks). */
  #spStart = new Map<string, number>();
  #incomingCount = 0;

  constructor(
    clock: DemoClock,
    storage: DemoStorage,
    emit: (event: AgentEvent) => void,
    forcedRole?: Role | null,
    sizeOf: (path: string) => number | undefined = () => undefined,
  ) {
    this.#sizeOf = sizeOf;
    this.#clock = clock;
    this.#storage = storage;
    this.#emit = emit;
    const saved = storage.load() ?? {};
    const role = forcedRole !== undefined && forcedRole !== null ? forcedRole : (saved.role ?? null);
    this.state = {
      appVersion: "0.4.0-dev",
      demo: true,
      role,
      prefs: { ...DEFAULT_PREFS, ...saved.prefs, scale: clampScale(saved.prefs?.scale ?? 1) },
      profile: {
        // A forced ?demo=<role> keeps a custom name but swaps another role's default name.
        name:
          saved.name && !(saved.role && saved.role !== role && saved.name === DEFAULT_NAMES[saved.role])
            ? saved.name
            : role
              ? DEFAULT_NAMES[role]
              : "",
        serverUrl: saved.serverUrl || `wss://${HOST}`,
        hasSecret: role === "director",
      },
      connection: { status: "disconnected", detail: "Not connected", host: HOST, serverVersion: null, legacy: false },
      peers: [],
      pending: [],
      targets: [],
      countdown: null,
      clock: { ...NO_CLOCK },
      actor: null,
      camera: null,
      director: null,
    };
    this.#applyRoleLocals();
    this.#setSelfOnly();
    if (role) {
      this.#save();
      this.#connect();
    }
    this.#flush(true);
  }

  // ---- public API -------------------------------------------------------

  handle(call: Call): void {
    switch (call.call) {
      case "setRole":
        this.#setRole(call.args.role);
        break;
      case "setPrefs":
        this.state.prefs = { ...this.state.prefs, ...call.args };
        this.state.prefs.scale = clampScale(this.state.prefs.scale);
        this.#save();
        break;
      case "setProfile":
        if (call.args.name !== undefined) {
          this.state.profile.name = call.args.name.trim() || this.#defaultName();
          const self = this.state.peers.find((p) => p.self);
          if (self) self.name = this.state.profile.name;
        }
        if (call.args.serverUrl !== undefined) this.state.profile.serverUrl = call.args.serverUrl.trim();
        if (call.args.secret) this.state.profile.hasSecret = true;
        this.#save();
        break;
      case "connect":
        this.#connect();
        break;
      case "disconnect":
        this.#disconnect("Disconnected");
        break;
      case "sendChat":
        this.#chat(call.args.text);
        break;
      case "cue":
        if (call.args.command === "go") this.#go();
        else if (call.args.command === "stop") this.#stop();
        else this.#startCountdown();
        break;
      case "setTargets": {
        const valid = new Set(this.#onlineActors().map((p) => p.id));
        this.state.targets = call.args.ids.filter((id) => valid.has(id));
        break;
      }
      case "approve":
        this.#approve(call.args.id);
        break;
      case "deny":
        this.#deny(call.args.id);
        break;
      case "forget":
        this.#forget(call.args.id);
        break;
      case "setActorLocal":
        if (this.state.actor) {
          if (call.args.soundpadEnabled !== undefined) {
            this.state.actor.soundpad.enabled = call.args.soundpadEnabled;
            this.state.actor.soundpad.state = call.args.soundpadEnabled ? "simulated" : "disabled";
            this.state.actor.soundpad.playback = call.args.soundpadEnabled ? stoppedPlayback() : null;
            this.#selfPlayStart = null;
          }
          if (call.args.oscEnabled !== undefined) {
            this.state.actor.osc.enabled = call.args.oscEnabled;
            this.state.actor.osc.ready = call.args.oscEnabled;
          }
          if (call.args.receiveDir !== undefined) this.state.actor.files.receiveDir = call.args.receiveDir.trim() || RECEIVE_DIR;
          if (call.args.defaultLines !== undefined) this.state.actor.soundpad.defaultLines = call.args.defaultLines;
          if (call.args.autoAddReceived !== undefined) this.state.actor.soundpad.autoAddReceived = call.args.autoAddReceived;
          if (call.args.autoLaunch !== undefined) this.state.actor.soundpad.autoLaunch = call.args.autoLaunch;
          if (call.args.soundpadPath !== undefined) this.state.actor.soundpad.path = call.args.soundpadPath.trim();
          if (call.args.autoAcceptFiles !== undefined) this.state.actor.files.autoAccept = call.args.autoAcceptFiles;
          if (call.args.autoCompensateLatency !== undefined) this.state.actor.timing.autoCompensate = call.args.autoCompensateLatency;
        }
        break;
      case "setDirectorLocal":
        if (this.state.director && call.args.leadMs !== undefined) {
          this.state.director.leadMs = Math.max(0, Math.min(2000, Math.round(call.args.leadMs)));
          const lead = this.state.director.leadMs;
          this.#log("info", lead ? `GO lead time: ${lead} ms` : "GO lead time: 0 (GO goes out at once)");
        }
        break;
      case "setDelay": {
        const p = this.state.peers.find((q) => q.id === call.args.id && q.role === "actor");
        if (p) {
          p.delayMs = call.args.ms;
          this.#log("info", `${p.name}'s delay: ${delayText(call.args.ms)}`);
        }
        break;
      }
      case "calibrate":
        this.#calibrate(call.args.id);
        break;
      case "arm":
        this.#arm(call.args.id, call.args.sound, call.args.label, call.args.lines ?? null);
        break;
      case "disarm": {
        const armed = this.state.director?.armed;
        if (armed && armed[call.args.id]) {
          delete armed[call.args.id];
          const name = this.state.peers.find((q) => q.id === call.args.id)?.name ?? "That actor";
          this.#log("info", `Cleared the armed sound on ${name}: GO plays their selected sound`);
        }
        break;
      }
      case "camera":
        this.#camera(call.args.action);
        break;
      case "sendFiles":
        this.#sendFiles(call.args.items);
        break;
      case "cancelBatch":
        this.#cancelBatch(call.args.id);
        break;
      case "answerFile":
        this.#answerFile(call.args.transferId, call.args.accept, call.args.rest ?? false, call.args.always ?? false);
        break;
      case "play":
        this.#play(call.args.ids, call.args.sound, call.args.lines, call.args.volume, call.args.label);
        break;
      case "playIndex":
        this.#play(call.args.ids, { index: call.args.index }, undefined, undefined, `Sound ${call.args.index}`);
        break;
      case "transport":
        this.#transport(call.args.ids, call.args.action, call.args.value);
        break;
      case "requestSounds": {
        const peer = this.state.peers.find((p) => p.id === call.args.id);
        if (peer?.soundpad?.available) {
          const sounds = demoSounds(peer.name);
          this.#emit({ type: "sounds", peerId: peer.id, sounds, categories: [{ index: 2, name: "EP3" }], total: sounds.length, at: this.#clock.now() });
        }
        break;
      }
      case "detectSoundpad":
        if (this.state.actor) this.state.actor.soundpad.path = DEMO_SOUNDPAD_EXE;
        this.#log("info", `Soundpad found: ${DEMO_SOUNDPAD_EXE}`);
        this.#toast("success", "Soundpad found");
        break;
      case "pickReceiveDir":
        if (this.state.actor) this.state.actor.files.receiveDir = "C:\\Users\\you\\Music\\Lines";
        break;
      case "openBrowser":
        this.#log("info", "Demo mode already runs in the browser.");
        break;
    }
    this.#changed = true;
    this.#flush();
  }

  /** Advance the simulation. The demo transport calls this a few times per second. */
  tick(): void {
    const now = this.#clock.now();
    const due = this.#timers.filter((t) => t.at <= now);
    this.#timers = this.#timers.filter((t) => t.at > now);
    for (const t of due) t.fn();
    if (due.length) this.#changed = true;

    if (this.state.connection.status === "connected") {
      if (now - this.#lastJitter >= JITTER_EVERY_MS) {
        this.#lastJitter = now;
        this.#jitter(now);
      }
      if (this.state.countdown && now >= this.state.countdown.endsAt) {
        this.state.countdown = null;
        this.#changed = true;
        this.#go();
      }
      this.#finishPlayback(now);
      this.#advanceSelfPlayback(now);
      this.#advanceSends(now);
      this.#advanceIncoming(now);
      this.#advanceSoundpads(now);
      if (this.state.role !== "director" && now >= this.#nextIncomingCue) {
        this.#nextIncomingCue = now + INCOMING_CUE_EVERY_MS;
        // Every other cue is a Play in 3s, so the actor's countdown shows up too
        if (this.state.role === "actor" && (this.#incomingCount++ % 2 === 1)) this.#incomingCountdown();
        else this.#incomingCue();
      }
    }
    this.#flush();
  }

  // ---- connection -------------------------------------------------------

  #setRole(role: Role): void {
    const previousDefault = this.state.role ? DEFAULT_NAMES[this.state.role] : "";
    const wasConnected = this.state.connection.status !== "disconnected";
    if (wasConnected) this.#disconnect(`Switching to ${role}`);
    this.state.role = role;
    if (!this.state.profile.name || this.state.profile.name === previousDefault) {
      this.state.profile.name = DEFAULT_NAMES[role];
    }
    this.state.profile.hasSecret = role === "director" || this.state.profile.hasSecret;
    this.#applyRoleLocals();
    this.#setSelfOnly();
    this.#save();
    // Switching roles keeps you online; picking the first role waits for the Connect step.
    if (wasConnected) this.#connect();
  }

  #connect(): void {
    if (!this.state.role) return;
    const status = this.state.connection.status;
    if (status === "connecting" || status === "connected" || status === "pending") return;
    this.state.connection = { ...this.state.connection, status: "connecting", detail: `Connecting to ${HOST}…` };
    this.#log("info", `Connecting to ${HOST}…`);
    this.#later(700, () => {
      if (this.state.connection.status !== "connecting") return;
      if (this.state.role === "director") {
        this.#connected();
        return;
      }
      this.state.connection = { ...this.state.connection, status: "pending", detail: "Waiting for the director to approve you" };
      this.#log("warning", "Waiting for director approval…");
      this.#later(1800, () => {
        if (this.state.connection.status !== "pending") return;
        this.#toast("success", "Approved by Mira");
        this.#connected();
      });
    });
  }

  #connected(): void {
    const now = this.#clock.now();
    this.#connectedAt = now;
    this.#lastJitter = 0;
    this.#nextIncomingCue = now + 5000;
    this.state.connection = {
      status: "connected",
      detail: `Connected as ${this.state.role}`,
      host: HOST,
      serverVersion: "0.4.0-demo",
      legacy: false,
    };
    this.state.clock = { ...DEMO_CLOCK };
    const selfName = this.state.profile.name.toLowerCase();
    this.#cast.clear();
    const others = CAST.filter((m) => m.name.toLowerCase() !== selfName);
    for (const m of others) this.#cast.set(peerId(m.name), m);
    this.state.peers = [this.#selfPeer(), ...others.map((m) => this.#peerFor(m))];
    this.state.targets = this.state.role === "director" ? this.#onlineActors().map((p) => p.id) : [];
    this.#jitter(now);
    this.#log("success", `Connected to ${HOST} as ${this.state.role}`);
    if (this.state.role === "director") {
      this.#later(8000, () => this.#addPending(LATE_JOINER));
    }
    if (this.state.role === "actor") {
      this.#later(INCOMING_FILES_AFTER_MS, () => this.#incomingFiles());
    }
  }

  #disconnect(detail: string): void {
    this.#timers = [];
    this.#playingUntil.clear();
    for (const id of this.#sending.keys()) this.#endBatch(id, "failed", "Lost the relay connection");
    if (this.state.actor) this.state.actor.files.incoming = [];
    this.#connectedAt = null;
    this.state.connection = { ...this.state.connection, status: "disconnected", detail, serverVersion: null };
    this.state.pending = [];
    this.state.targets = [];
    this.state.countdown = null;
    this.state.clock = { ...NO_CLOCK };
    if (this.state.camera) this.state.camera = { ...this.state.camera, recording: false, recordingSince: null };
    this.#setSelfOnly();
    this.#log("info", detail);
  }

  // ---- director actions -------------------------------------------------

  #go(): void {
    if (this.state.connection.status !== "connected") return;
    const now = this.#clock.now();
    const targets = this.#onlineActors().filter((p) => this.state.targets.includes(p.id));
    if (!targets.length) {
      this.#log("warning", "GO skipped — no actors targeted");
      return;
    }
    const armed = this.state.director?.armed ?? {};
    const parts: string[] = [];
    for (const p of targets) {
      const sound = armed[p.id];
      const entry = sound ? demoSounds(p.name).find((s) => ("key" in sound.sound && s.key === sound.sound.key) || ("index" in sound.sound && s.index === sound.sound.index)) : undefined;
      const length = entry?.durationMs ?? SELECTED_SOUND_MS;
      this.#playingUntil.set(p.id, now + (sound ? length : 4000 + Math.round(this.#clock.random() * 4000)));
      p.activity = "playing";
      this.#spPlay(p, { title: sound ? (entry?.title ?? sound.label) : null, index: entry?.index ?? null, key: entry?.key ?? null, lines: sound?.lines ?? "both", durationMs: length });
      // Scheduled starts report how late they ran; the demo's are on time
      p.lastLateMs = Math.round(this.#clock.random() * 6);
      parts.push(sound ? `${p.name} (${armedText(sound)})` : p.name);
    }
    for (const cam of this.state.peers.filter((p) => p.role === "camera" && p.status === "online")) {
      cam.activity = "rolling";
    }
    this.#traffic("self", targets.map((p) => p.id), "cue");
    const lead = this.state.director?.leadMs ?? 0;
    this.#log("success", `▶ GO → ${parts.join(", ")}${lead ? ` for ${serverTime(now + lead)} server time (+${lead} ms)` : ""}`);
  }

  #arm(id: string, sound: SoundRef, label: string, lines: Lines | null): void {
    const director = this.state.director;
    const p = this.state.peers.find((q) => q.id === id && q.role === "actor");
    if (!director || !p) return;
    const reason = armReason(p, sound, lines, false);
    if (reason) {
      this.#toast("error", reason);
      return;
    }
    director.armed[id] = { sound, label: label || ("index" in sound ? `Sound ${sound.index}` : "A sound"), lines };
    this.#log("info", `Armed for GO: ${armedText(director.armed[id])} on ${p.name}`);
  }

  #calibrate(id: string | undefined): void {
    const actor = this.state.actor;
    if (this.state.role === "actor" && !id && actor) {
      this.#log("info", "Calibrating the start latency (speakers only)…");
      this.#later(1500, () => {
        const ms = 46 + Math.round(this.#clock.random() * 12);
        const t = actor.timing;
        t.startLatencyMs = t.measured ? Math.round((t.startLatencyMs * t.samples + ms) / (t.samples + 1)) : ms;
        t.samples = Math.min(5, t.samples + 1);
        t.measured = true;
        this.#log("success", `Start latency ${ms} ms this time; ${t.startLatencyMs} ms over the last ${t.samples} plays`);
      });
      return;
    }
    const p = this.state.peers.find((q) => q.id === id && q.role === "actor");
    if (!p) return;
    if (!p.caps.includes("soundpad.calibrate")) {
      this.#toast("error", `${p.name}'s app is too old to calibrate`);
      return;
    }
    if (!p.soundpad?.available) {
      this.#log("warning", `${p.name}: calibrate — ${p.soundpad?.detail || "Soundpad isn't answering"}`);
      return;
    }
    this.#log("info", `Calibrating ${p.name}'s start latency (a short speakers-only play)…`);
    this.#traffic("self", [p.id], "cue");
    this.#later(1500, () => {
      const ms = 46 + Math.round(this.#clock.random() * 30);
      this.#spSet(p, { startLatencyMs: ms });
      this.#log("success", `${p.name}: start latency ${ms} ms`);
    });
  }

  #stop(): void {
    if (this.state.connection.status !== "connected") return;
    const wasCounting = this.state.countdown !== null;
    this.state.countdown = null;
    const targets = this.#onlineActors().filter((p) => this.state.targets.includes(p.id));
    for (const p of this.state.peers) {
      if (!p.self) p.activity = "idle";
      if (p.soundpad?.available && targets.includes(p)) this.#spSet(p, { status: "STOPPED", positionMs: 0, durationMs: 0, title: null, index: null, key: null, lines: null });
    }
    this.#playingUntil.clear();
    this.#traffic("self", targets.map((p) => p.id), "stop");
    this.#log("info", wasCounting ? "■ Countdown cancelled" : "■ STOP → all targeted actors");
  }

  #startCountdown(): void {
    if (this.state.connection.status !== "connected" || this.state.countdown) return;
    this.state.countdown = { endsAt: this.#clock.now() + COUNTDOWN_MS, durationMs: COUNTDOWN_MS };
    this.#log("info", "⏱ Playing in 3 seconds…");
  }

  #addPending(member: CastMember): void {
    if (this.state.connection.status !== "connected" || this.state.role !== "director") return;
    const id = peerId(member.name);
    if (this.state.pending.some((p) => p.id === id) || this.state.peers.some((p) => p.id === id)) return;
    this.#cast.set(id, member);
    this.state.pending = [...this.state.pending, { id, name: member.name }];
    this.#toast("warning", `${member.name} wants to join`);
    this.#log("warning", `${member.name} is waiting for approval`);
  }

  #approve(id: string): void {
    const entry = this.state.pending.find((p) => p.id === id);
    const member = this.#cast.get(id);
    if (!entry || !member) return;
    this.state.pending = this.state.pending.filter((p) => p.id !== id);
    this.state.peers = [...this.state.peers, this.#peerFor(member)];
    this.state.targets = [...this.state.targets, id];
    this.#traffic("self", [id], "approve");
    this.#log("success", `Approved ${member.name}`);
  }

  #deny(id: string): void {
    const entry = this.state.pending.find((p) => p.id === id);
    if (!entry) return;
    this.state.pending = this.state.pending.filter((p) => p.id !== id);
    this.#log("info", `Denied ${entry.name}`);
  }

  #forget(id: string): void {
    const peer = this.state.peers.find((p) => p.id === id && !p.self);
    const member = this.#cast.get(id);
    if (!peer) return;
    this.state.peers = this.state.peers.filter((p) => p.id !== id);
    this.state.targets = this.state.targets.filter((t) => t !== id);
    this.#playingUntil.delete(id);
    this.#log("info", `Forgot ${peer.name} — they need approval again`);
    if (member) this.#later(5000, () => this.#addPending(member));
  }

  // ---- Soundpad on demo actors (director) ---------------------------------

  #spSet(p: Peer, patch: Partial<PeerSoundpad>): void {
    if (!p.soundpad) return;
    p.soundpad = { ...p.soundpad, ...patch, at: this.#clock.now() };
    this.#changed = true;
  }

  #spPlay(p: Peer, what: { title: string | null; index: number | null; key: string | null; lines: Lines; durationMs: number }): void {
    if (!p.soundpad?.available) return;
    this.#spStart.set(p.id, this.#clock.now());
    this.#spSet(p, { status: "PLAYING", positionMs: 0, ...what });
  }

  #play(ids: string[], sound: SoundRef, lines: Lines | undefined, volume: number | undefined, label: string | undefined): void {
    if (this.state.connection.status !== "connected") return;
    const played: Peer[] = [];
    for (const id of ids) {
      const p = this.state.peers.find((q) => q.id === id && q.role === "actor");
      if (!p) continue;
      const legacy = p.caps.includes("legacy");
      const simple = ("index" in sound || "selected" in sound) && (lines ?? "both") === "both" && volume === undefined;
      if (legacy && !simple) {
        this.#toast("error", `${p.name} uses the v0.3 app, which can only play the selected sound or a sound by number`);
        continue;
      }
      if (!legacy && !p.soundpad?.available) {
        this.#log("warning", `${p.name}: play — ${p.soundpad?.detail || "Soundpad isn't answering"}`);
        continue;
      }
      const list = demoSounds(p.name);
      const entry = "key" in sound ? list.find((s) => s.key === sound.key) : "index" in sound ? list.find((s) => s.index === sound.index) : undefined;
      if (volume !== undefined) this.#spSet(p, { volume });
      this.#spPlay(p, {
        title: entry?.title ?? ("sha256" in sound ? (label ?? "Sent file") : null),
        index: entry?.index ?? null,
        key: entry?.key ?? null,
        lines: lines ?? "both",
        durationMs: entry?.durationMs ?? SELECTED_SOUND_MS,
      });
      p.activity = "playing";
      this.#playingUntil.set(p.id, this.#clock.now() + (entry?.durationMs ?? SELECTED_SOUND_MS));
      played.push(p);
    }
    if (played.length) {
      this.#traffic("self", played.map((p) => p.id), "cue");
      this.#log("success", `▶ ${label ?? "Sound"} → ${played.map((p) => p.name).join(", ")}`);
    }
  }

  #transport(ids: string[], action: string, value: number | undefined): void {
    const now = this.#clock.now();
    for (const id of ids) {
      const p = this.state.peers.find((q) => q.id === id);
      const sp = p?.soundpad;
      if (!p || !sp?.available) continue;
      const started = this.#spStart.get(id) ?? now;
      if (action === "pause" && sp.status === "PLAYING") this.#spSet(p, { status: "PAUSED", positionMs: now - started });
      else if (action === "resume" && sp.status === "PAUSED") {
        this.#spStart.set(id, now - sp.positionMs);
        this.#spSet(p, { status: "PLAYING" });
      } else if (action === "stop") {
        this.#spSet(p, { status: "STOPPED", positionMs: 0, durationMs: 0, title: null, index: null, key: null, lines: null });
        p.activity = "idle";
      } else if (action === "volume" && value !== undefined) this.#spSet(p, { volume: value });
      else if (action === "mute" || action === "unmute") this.#spSet(p, { muted: action === "mute" });
      else if ((action === "seek" || action === "jump") && value !== undefined && sp.status !== "STOPPED") {
        const target = Math.max(0, Math.min(sp.durationMs, action === "seek" ? value : sp.positionMs + value));
        this.#spStart.set(id, now - target);
        this.#spSet(p, { positionMs: target });
      }
    }
    if (action !== "volume") this.#traffic("self", ids, action === "stop" ? "stop" : "cue");
  }

  /** Positions move in ~140 ms steps, like the real Soundpad. */
  #advanceSoundpads(now: number): void {
    for (const p of this.state.peers) {
      const sp = p.soundpad;
      if (!sp?.available || sp.status !== "PLAYING") continue;
      const position = now - (this.#spStart.get(p.id) ?? now);
      if (position >= sp.durationMs) this.#spSet(p, { status: "STOPPED", positionMs: 0, durationMs: 0, title: null, index: null, key: null, lines: null });
      else this.#spSet(p, { positionMs: Math.floor(position / 140) * 140 });
    }
  }

  // ---- files (director sends) --------------------------------------------

  #sendFiles(items: { path: string; actorId: string }[]): void {
    const director = this.state.director;
    if (!director || this.state.connection.status !== "connected") return;
    const byActor = new Map<string, string[]>();
    for (const item of items) byActor.set(item.actorId, [...(byActor.get(item.actorId) ?? []), item.path]);
    const now = this.#clock.now();
    for (const [actorId, paths] of byActor) {
      const peer = this.state.peers.find((p) => p.id === actorId);
      if (!peer || !(peer.caps.includes("files") || peer.caps.includes("legacy"))) {
        this.#toast("error", `${peer?.name ?? "That actor"}'s app is too old to receive files`);
        continue;
      }
      // The demo folder's sizes, else pretend ones (0.4–2.4 MB, stable per name)
      const sizes = paths.map((p) => this.#sizeOf(p) ?? 400_000 + ([...p].reduce((a, c) => a + c.charCodeAt(0), 0) % 20) * 100_000);
      const id = `demo-b${this.#batchId++}`;
      const batch: SendBatch = {
        id,
        actorId,
        actorName: peer.name,
        files: paths.length,
        done: 0,
        ok: 0,
        failed: 0,
        bytes: sizes.reduce((a, b) => a + b, 0),
        sentBytes: 0,
        current: null,
        state: "sending",
        detail: "",
        results: paths.map((p) => ({ name: baseName(p), state: "queued", detail: "", sha256: null })),
      };
      director.files.batches = [...director.files.batches.slice(-9), batch];
      this.#sending.set(id, { started: now, sizes, index: 0, accepted: false });
      this.#traffic("self", [actorId], "cue");
      this.#log("info", `Sending ${paths.length} file${paths.length === 1 ? "" : "s"} to ${peer.name}`);
    }
  }

  #advanceSends(now: number): void {
    const director = this.state.director;
    if (!director) return;
    for (const [id, run] of this.#sending) {
      const batch = director.files.batches.find((b) => b.id === id);
      if (!batch) {
        this.#sending.delete(id);
        continue;
      }
      const size = run.sizes[run.index];
      const result = batch.results[run.index];
      this.#changed = true;
      if (!run.accepted) {
        result.state = "offered";
        batch.current = { name: result.name, size, sent: 0, waiting: true };
        if (now - run.started < DEMO_ACCEPT_MS) continue;
        // Infinity declines files that replace a copy she has (every third file, for the demo)
        if (batch.actorName === "Infinity" && run.index % 3 === 2) {
          result.state = "declined";
          result.detail = "Declined";
          this.#nextFile(batch, run, now, false);
          continue;
        }
        run.accepted = true;
        run.started = now;
        result.state = "sending";
      }
      const sent = Math.min(size, Math.round(((now - run.started) / 1000) * DEMO_BYTES_PER_S));
      batch.current = { name: result.name, size, sent, waiting: false };
      batch.sentBytes = run.sizes.slice(0, run.index).reduce((a, b) => a + b, 0) + sent;
      if (sent >= size) {
        result.state = "ok";
        result.sha256 = demoKey(`sha/${result.name}`).repeat(4);
        this.#nextFile(batch, run, now, true);
      }
    }
  }

  #nextFile(batch: SendBatch, run: { started: number; sizes: number[]; index: number; accepted: boolean }, now: number, ok: boolean): void {
    batch.done += 1;
    if (ok) batch.ok += 1;
    else batch.failed += 1;
    run.index += 1;
    run.accepted = false;
    run.started = now;
    this.#changed = true;
    if (run.index >= run.sizes.length) {
      this.#endBatch(batch.id, "done", "");
      this.#log(batch.failed ? "warning" : "success", `Files to ${batch.actorName}: ${batch.ok} sent${batch.failed ? `, ${batch.failed} not` : ""}`);
    }
  }

  #endBatch(id: string, state: SendBatch["state"], detail: string): void {
    this.#sending.delete(id);
    const batch = this.state.director?.files.batches.find((b) => b.id === id);
    if (!batch) return;
    batch.state = state;
    batch.detail = detail;
    batch.current = null;
    for (const r of batch.results) if (r.state === "queued" || r.state === "offered" || r.state === "sending") r.state = state === "done" ? "failed" : "cancelled";
    batch.failed = batch.results.filter((r) => r.state !== "ok").length;
    batch.done = batch.ok + batch.failed;
    this.#changed = true;
  }

  #cancelBatch(id: string): void {
    const ids = id === "all" ? [...this.#sending.keys()] : [id];
    for (const each of ids) {
      if (!this.#sending.has(each)) continue;
      const name = this.state.director?.files.batches.find((b) => b.id === each)?.actorName ?? "";
      this.#endBatch(each, "cancelled", "Cancelled by director");
      this.#log("warning", `Files to ${name} cancelled`);
    }
  }

  // ---- files (actor receives) ---------------------------------------------

  #incomingFiles(): void {
    const files = this.state.actor?.files;
    const director = this.state.peers.find((p) => p.role === "director" && !p.self);
    if (!files || !director || this.state.connection.status !== "connected") return;
    const self = this.state.profile.name || "Rowan";
    const names = [`Scene 4 - ${self}.wav`, `Scene 5 - ${self}.wav`];
    this.#log("info", `${director.name} is sending 2 files (2.1 MB)`);
    names.forEach((name, i) => {
      const offer: IncomingFile = {
        transferId: `demo-t${this.#batchId++}`,
        batchId: "demo-in",
        name,
        size: 900_000 + i * 300_000,
        from: director.name,
        character: self,
        replaces: i === 1,
        index: i + 1,
        count: names.length,
        state: files.autoAccept ? "receiving" : "asking",
        receivedBytes: 0,
      };
      files.incoming = [...files.incoming, offer];
    });
    if (!files.autoAccept) this.#toast("info", `${director.name} wants to send ${names[0]}`);
    this.#traffic(director.id, ["self"], "cue");
  }

  #answerFile(transferId: string, accept: boolean, rest: boolean, always: boolean): void {
    const files = this.state.actor?.files;
    if (!files) return;
    const item = files.incoming.find((f) => f.transferId === transferId);
    if (!item || item.state !== "asking") return;
    if (always) files.autoAccept = true;
    if (!accept) {
      files.incoming = files.incoming.filter((f) => f !== item);
      files.recent = [{ name: item.name, ok: false, at: this.#clock.now(), from: item.from, detail: "declined" }, ...files.recent].slice(0, 20);
      this.#log("info", `Declined ${item.name}`);
      return;
    }
    for (const f of files.incoming) {
      if (f === item || (f.state === "asking" && (always || (rest && f.batchId === item.batchId)))) f.state = "receiving";
    }
  }

  #advanceIncoming(now: number): void {
    const files = this.state.actor?.files;
    if (!files || !files.incoming.length) return;
    // One file at a time, like the real thing
    const current = files.incoming.find((f) => f.state === "receiving");
    if (!current) return;
    current.receivedBytes = Math.min(current.size, current.receivedBytes + Math.round(DEMO_BYTES_PER_S / 4));
    if (current.receivedBytes >= current.size) {
      files.incoming = files.incoming.filter((f) => f !== current);
      const detail = current.replaces ? "replaced your copy" : "";
      files.recent = [{ name: current.name, ok: true, at: now, from: current.from, detail }, ...files.recent].slice(0, 20);
      this.#log("success", `Received ${current.name} from ${current.from} → ${files.receiveDir}`);
    }
    this.#changed = true;
  }

  // ---- other roles ------------------------------------------------------

  /** The director's Play in 3s, as an actor sees it: a countdown on server time, then GO. */
  #incomingCountdown(): void {
    const director = this.state.peers.find((p) => p.role === "director" && !p.self);
    if (!director || this.state.connection.status !== "connected") return;
    const latency = this.state.actor?.timing.autoCompensate ? (this.state.actor.timing.startLatencyMs ?? DEFAULT_START_LATENCY_MS) : 0;
    const fireIn = COUNTDOWN_MS + (this.state.actor?.timing.delayMs ?? 0) - latency;
    this.state.countdown = { endsAt: this.#clock.now() + fireIn, durationMs: COUNTDOWN_MS };
    this.#log("info", `⏱ ${director.name}: Play in 3s`);
    this.#traffic(director.id, ["self"], "cue");
    this.#later(fireIn, () => {
      if (!this.state.countdown) return;
      this.state.countdown = null;
      this.#incomingCue();
    });
  }

  #incomingCue(): void {
    const director = this.state.peers.find((p) => p.role === "director" && !p.self);
    if (!director) return;
    const now = this.#clock.now();
    const self = this.state.peers.find((p) => p.self);
    const actors = this.#onlineActors().filter((p) => !p.self && this.#clock.random() > 0.4);
    const to = [...(this.state.role === "actor" ? ["self"] : []), ...actors.map((p) => p.id)];
    for (const p of actors) {
      this.#playingUntil.set(p.id, now + 5000);
      p.activity = "playing";
    }
    if (this.state.role === "actor" && self && this.state.actor) {
      this.#playingUntil.set("self", now + 5000);
      self.activity = "playing";
      this.state.actor.lastCue = { command: "*go", at: now, ok: true };
      if (this.state.actor.soundpad.enabled) {
        this.#selfPlayStart = now;
        this.state.actor.soundpad.playback = { status: "PLAYING", positionMs: 0, durationMs: SELF_SOUND_MS, title: null, lines: "both" };
      }
      const how = this.state.actor.soundpad.enabled ? "played the selected sound (simulated)" : "Soundpad is off, nothing played";
      this.#log("success", `▶ GO from ${director.name} — ${how}`);
    } else {
      this.#log("info", `${director.name} sent GO to ${actors.length} actor(s)`);
    }
    this.#traffic(director.id, to, "cue");
  }

  #camera(action: "roll" | "cut"): void {
    if (!this.state.camera || this.state.connection.status !== "connected") return;
    const self = this.state.peers.find((p) => p.self);
    if (action === "roll" && !this.state.camera.recording) {
      this.state.camera = { ...this.state.camera, recording: true, recordingSince: this.#clock.now() };
      if (self) self.activity = "rolling";
      this.#log("success", "● Rolling (demo)");
    } else if (action === "cut" && this.state.camera.recording) {
      this.state.camera = { ...this.state.camera, recording: false, recordingSince: null };
      if (self) self.activity = "idle";
      this.#log("info", "■ Cut — recording stopped (demo)");
    }
  }

  #chat(text: string): void {
    const clean = text.trim();
    if (!clean) return;
    this.#log("chat", clean, this.state.profile.name);
    const everyone = this.state.peers.filter((p) => !p.self).map((p) => p.id);
    this.#traffic("self", everyone, "chat");
    const replier = this.state.peers.find((p) => !p.self && (this.state.role === "director" ? p.role === "actor" : p.role === "director"));
    if (replier) {
      this.#later(1200, () => {
        this.#log("chat", this.state.role === "director" ? "Ready when you are!" : "Copy that 👍", replier.name);
        this.#traffic(replier.id, ["self"], "chat");
      });
    }
  }

  // ---- simulation helpers -----------------------------------------------

  #jitter(now: number): void {
    this.#changed = true;
    const since = this.#connectedAt === null ? 0 : now - this.#connectedAt;
    for (const p of this.state.peers) {
      if (p.self) {
        p.latencyMs = Math.round(20 + this.#clock.random() * 14);
        continue;
      }
      const member = this.#cast.get(p.id);
      if (!member) continue;
      // Juno drops out for 6 s every 45 s, so the "lost" state shows up in the graph.
      if (member.name === "Juno" && since > 20_000 && since % 45_000 < 6000) {
        p.status = "timeout";
        p.latencyMs = null;
        continue;
      }
      p.status = "online";
      p.latencyMs = Math.round(member.baseLatency * (0.85 + this.#clock.random() * 0.3));
    }
  }

  #finishPlayback(now: number): void {
    let anyPlaying = false;
    for (const p of this.state.peers) {
      const id = p.self ? "self" : p.id;
      const until = this.#playingUntil.get(id);
      if (until === undefined) continue;
      if (now >= until) {
        this.#playingUntil.delete(id);
        this.#changed = true;
        if (p.activity === "playing") p.activity = "idle";
      } else {
        anyPlaying = true;
      }
    }
    if (!anyPlaying) {
      for (const p of this.state.peers) {
        if (p.role === "camera" && !p.self && p.activity === "rolling") {
          p.activity = "idle";
          this.#changed = true;
        }
      }
    }
  }

  /** The simulated Soundpad moves in ~140 ms steps like the real one; the tick is coarser anyway. */
  #advanceSelfPlayback(now: number): void {
    const playback = this.state.actor?.soundpad.playback;
    if (!playback || this.#selfPlayStart === null) return;
    const position = now - this.#selfPlayStart;
    if (position >= playback.durationMs) {
      this.state.actor!.soundpad.playback = stoppedPlayback();
      this.#selfPlayStart = null;
    } else {
      playback.positionMs = Math.floor(position / 140) * 140;
    }
    this.#changed = true;
  }

  #onlineActors(): Peer[] {
    return this.state.peers.filter((p) => p.role === "actor" && p.status === "online");
  }

  #selfPeer(): Peer {
    return {
      id: "self",
      name: this.state.profile.name || "You",
      role: this.state.role ?? "actor",
      status: "online",
      latencyMs: null,
      activity: "idle",
      self: true,
      caps: [],
      soundpad: null,
      delayMs: null,
      lastLateMs: null,
    };
  }

  #peerFor(member: CastMember): Peer {
    return {
      id: peerId(member.name),
      name: member.name,
      role: member.role,
      status: "online",
      latencyMs: member.baseLatency,
      activity: "idle",
      self: false,
      caps: member.legacy ? ["legacy"] : member.role === "actor" ? [...ACTOR_CAPS] : [],
      delayMs: member.role === "actor" ? 0 : null,
      lastLateMs: null,
      soundpad:
        member.role === "actor" && !member.legacy
          ? {
              available: member.name !== SOUNDPAD_OFF,
              status: member.name !== SOUNDPAD_OFF ? "STOPPED" : null,
              positionMs: 0,
              durationMs: 0,
              title: null,
              index: null,
              key: null,
              lines: null,
              volume: member.name !== SOUNDPAD_OFF ? 80 : null,
              muted: member.name !== SOUNDPAD_OFF ? false : null,
              detail: member.name === SOUNDPAD_OFF ? "Soundpad isn't running (its remote-control pipe isn't open)" : "",
              at: this.#clock.now(),
              startLatencyMs: null,
            }
          : null,
    };
  }

  #setSelfOnly(): void {
    this.state.peers = this.state.role ? [this.#selfPeer()] : [];
  }

  #applyRoleLocals(): void {
    const role = this.state.role;
    this.state.actor =
      role === "actor"
        ? ({
            soundpad: {
              enabled: true,
              state: "simulated",
              detail: "Demo — no Soundpad needed",
              info: null,
              playback: stoppedPlayback(),
              volume: 80,
              muted: false,
              defaultLines: "both",
              autoAddReceived: true,
              autoLaunch: false,
              path: "",
            },
            osc: { enabled: true, host: "127.0.0.1", port: 9000, ready: true },
            lastCue: null,
            files: { receiveDir: RECEIVE_DIR, autoAccept: false, incoming: [], recent: [] },
            timing: { startLatencyMs: DEFAULT_START_LATENCY_MS, measured: false, samples: 0, autoCompensate: true, delayMs: 0 },
          } satisfies ActorLocal)
        : null;
    this.state.director = role === "director" ? { files: { batches: [] }, leadMs: DEFAULT_LEAD_MS, armed: {} } : null;
    this.state.camera =
      role === "camera"
        ? ({ obs: { connected: true, detail: "OBS 31 · demo" }, recording: false, recordingSince: null } satisfies CameraLocal)
        : null;
  }

  #defaultName(): string {
    return this.state.role ? DEFAULT_NAMES[this.state.role] : "";
  }

  #later(ms: number, fn: () => void): void {
    this.#timers.push({ at: this.#clock.now() + ms, fn });
  }

  #log(level: LogLevel, text: string, from?: string): void {
    this.#emit({ type: "log", entry: { id: this.#logId++, ts: this.#clock.now(), level, text, from } });
    this.#changed = true;
  }

  #toast(level: LogLevel, text: string): void {
    this.#emit({ type: "toast", level, text });
  }

  #traffic(from: string, to: string[], kind: TrafficKind): void {
    if (to.length) this.#emit({ type: "traffic", traffic: { from, to, kind } });
  }

  #save(): void {
    this.#storage.save({
      role: this.state.role,
      prefs: this.state.prefs,
      name: this.state.profile.name,
      serverUrl: this.state.profile.serverUrl,
    });
  }

  #flush(force = false): void {
    if (!force && !this.#changed) return;
    this.#changed = false;
    this.#emit({ type: "state", state: structuredClone(this.state) });
  }
}
