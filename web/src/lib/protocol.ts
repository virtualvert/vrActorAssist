// Contract between the web UI and whatever drives it: the local agent (agent/state.py builds
// the same shapes) or the in-browser demo session. Keep both sides in sync when editing.

export type Role = "director" | "actor" | "camera";
export type Theme = "system" | "dark" | "light";

export interface Prefs {
  theme: Theme;
  /** Multiplier for the whole UI (rem-based). 0.75 – 2. */
  scale: number;
  /** Bigger targets, always-visible labels, no hover-only details. */
  vrMode: boolean;
  reduceMotion: boolean;
}

export interface Profile {
  name: string;
  serverUrl: string;
  /** Directors authenticate with a secret; the UI never receives the value itself. */
  hasSecret: boolean;
}

export type ConnStatus = "disconnected" | "connecting" | "pending" | "connected" | "error";

export interface Connection {
  status: ConnStatus;
  detail: string;
  host: string;
  serverVersion: string | null;
  /** True while talking to a v0.3.x relay over the pipe protocol (reduced roster info). */
  legacy: boolean;
}

export type PeerStatus = "online" | "pending" | "timeout";
export type Activity = "idle" | "playing" | "rolling";

export interface Peer {
  id: string;
  name: string;
  role: Role;
  status: PeerStatus;
  latencyMs: number | null;
  activity: Activity;
  self: boolean;
}

export interface PendingActor {
  id: string;
  name: string;
}

export interface ActorLocal {
  soundpad: { enabled: boolean; state: "ready" | "simulated" | "missing" | "disabled"; detail: string };
  osc: { enabled: boolean; host: string; port: number; ready: boolean };
  lastCue: { command: string; at: number; ok: boolean } | null;
}

export interface CameraLocal {
  obs: { connected: boolean; detail: string };
  recording: boolean;
  recordingSince: number | null;
}

export interface Countdown {
  endsAt: number;
  durationMs: number;
}

export interface AppState {
  appVersion: string;
  demo: boolean;
  /** null until the user picks a seat; afterwards the app always opens in that role. */
  role: Role | null;
  prefs: Prefs;
  profile: Profile;
  connection: Connection;
  /** Everyone we know about, including ourselves (`self: true`). The relay itself is implicit. */
  peers: Peer[];
  pending: PendingActor[];
  /** Director only: peer ids that receive Go / Stop. */
  targets: string[];
  countdown: Countdown | null;
  actor: ActorLocal | null;
  camera: CameraLocal | null;
}

export type LogLevel = "info" | "success" | "warning" | "error" | "chat";

export interface LogEntry {
  id: number;
  ts: number;
  level: LogLevel;
  text: string;
  from?: string;
}

export type TrafficKind = "cue" | "stop" | "chat" | "approve";

/** A message moving through the relay, drawn as a packet on the node graph. */
export interface Traffic {
  from: string;
  to: string[];
  kind: TrafficKind;
}

export type AgentEvent =
  | { type: "state"; state: AppState }
  | { type: "logs"; entries: LogEntry[] }
  | { type: "log"; entry: LogEntry }
  | { type: "traffic"; traffic: Traffic }
  | { type: "toast"; level: LogLevel; text: string }
  | { type: "result"; id: number; ok: boolean; error?: string };

export type Call =
  | { call: "setRole"; args: { role: Role } }
  | { call: "setPrefs"; args: Partial<Prefs> }
  | { call: "setProfile"; args: { name?: string; serverUrl?: string; secret?: string } }
  | { call: "connect" }
  | { call: "disconnect" }
  | { call: "sendChat"; args: { text: string } }
  | { call: "cue"; args: { command: "go" | "stop" | "countdown" } }
  | { call: "setTargets"; args: { ids: string[] } }
  | { call: "approve"; args: { id: string } }
  | { call: "deny"; args: { id: string } }
  | { call: "forget"; args: { id: string } }
  | { call: "setActorLocal"; args: { soundpadEnabled?: boolean; oscEnabled?: boolean; soundpadPath?: string } }
  | { call: "camera"; args: { action: "roll" | "cut" } }
  | { call: "openBrowser" };

export const SCALE_MIN = 0.75;
export const SCALE_MAX = 2;
export const VR_SCALE = 1.4;

export function clampScale(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return Math.round(Math.min(SCALE_MAX, Math.max(SCALE_MIN, value)) * 20) / 20;
}
