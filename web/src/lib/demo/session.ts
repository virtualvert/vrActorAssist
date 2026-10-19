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
  type LogLevel,
  type Peer,
  type Prefs,
  type Role,
  type SoundpadPlayback,
  type TrafficKind,
} from "../protocol";

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
}

const CAST: CastMember[] = [
  { name: "Mira", role: "director", baseLatency: 24 },
  { name: "Coda", role: "actor", baseLatency: 38 },
  { name: "Infinity", role: "actor", baseLatency: 61 },
  { name: "Quincey", role: "actor", baseLatency: 240 },
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

function stoppedPlayback(): SoundpadPlayback {
  return { status: "STOPPED", positionMs: 0, durationMs: 0, title: null };
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

  constructor(clock: DemoClock, storage: DemoStorage, emit: (event: AgentEvent) => void, forcedRole?: Role | null) {
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
      actor: null,
      camera: null,
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
        }
        break;
      case "camera":
        this.#camera(call.args.action);
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
      if (this.state.role !== "director" && now >= this.#nextIncomingCue) {
        this.#nextIncomingCue = now + INCOMING_CUE_EVERY_MS;
        this.#incomingCue();
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
  }

  #disconnect(detail: string): void {
    this.#timers = [];
    this.#playingUntil.clear();
    this.#connectedAt = null;
    this.state.connection = { ...this.state.connection, status: "disconnected", detail, serverVersion: null };
    this.state.pending = [];
    this.state.targets = [];
    this.state.countdown = null;
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
    for (const p of targets) {
      this.#playingUntil.set(p.id, now + 4000 + Math.round(this.#clock.random() * 4000));
      p.activity = "playing";
    }
    for (const cam of this.state.peers.filter((p) => p.role === "camera" && p.status === "online")) {
      cam.activity = "rolling";
    }
    this.#traffic("self", targets.map((p) => p.id), "cue");
    this.#log("success", `▶ GO → ${targets.map((p) => p.name).join(", ")}`);
  }

  #stop(): void {
    if (this.state.connection.status !== "connected") return;
    const wasCounting = this.state.countdown !== null;
    this.state.countdown = null;
    const targets = this.#onlineActors().filter((p) => this.state.targets.includes(p.id));
    for (const p of this.state.peers) {
      if (!p.self) p.activity = "idle";
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

  // ---- other roles ------------------------------------------------------

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
        this.state.actor.soundpad.playback = { status: "PLAYING", positionMs: 0, durationMs: SELF_SOUND_MS, title: null };
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
            soundpad: { enabled: true, state: "simulated", detail: "Demo — no Soundpad needed", info: null, playback: stoppedPlayback() },
            osc: { enabled: true, host: "127.0.0.1", port: 9000, ready: true },
            lastCue: null,
          } satisfies ActorLocal)
        : null;
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
