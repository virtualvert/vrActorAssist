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
  /**
   * What the peer's app announced to the relay (`files`, `soundpad`, `osc`, ...). v0.3 clients
   * show as `legacy`. Empty for yourself and on a v0.3 relay.
   */
  caps: string[];
}

export interface PendingActor {
  id: string;
  name: string;
}

/**
 * ready: Soundpad answers on its remote-control pipe. fallback: it doesn't, so cues go through
 * `Soundpad.exe -rc` (no playback status). missing: neither works.
 */
export type SoundpadState = "ready" | "fallback" | "simulated" | "missing" | "disabled";
export type PlayStatus = "STOPPED" | "PLAYING" | "PAUSED" | "SEEKING";

export interface SoundpadInfo {
  version: string;
  rcVersion: string;
  /** null when Soundpad's answer wasn't 0 or 1. */
  trial: boolean | null;
}

/** Live from Soundpad's pipe. Position moves in ~140 ms steps; 0 / 0 while stopped. */
export interface SoundpadPlayback {
  status: PlayStatus;
  positionMs: number;
  durationMs: number;
  /** Known when the cue named the sound (`*play:N`), not for Go (Soundpad's selected sound). */
  title: string | null;
}

export interface ActorLocal {
  soundpad: {
    enabled: boolean;
    state: SoundpadState;
    detail: string;
    /** Only while the pipe is connected. */
    info: SoundpadInfo | null;
    playback: SoundpadPlayback | null;
  };
  osc: { enabled: boolean; host: string; port: number; ready: boolean };
  lastCue: { command: string; at: number; ok: boolean } | null;
  files: ActorFiles;
}

/** A file a director is sending (spec §8.4). `asking` waits for Accept / Decline. */
export interface IncomingFile {
  transferId: string;
  batchId: string | null;
  name: string;
  size: number;
  from: string;
  /** From the file name (" - Diego.mp3"). */
  character: string | null;
  /** A file with this name is already in the receive folder; accepting replaces it. */
  replaces: boolean;
  /** Position in the director's batch ("2 of 5"); null outside a batch. */
  index: number | null;
  count: number | null;
  state: "asking" | "receiving";
  receivedBytes: number;
}

export interface ReceivedFile {
  name: string;
  ok: boolean;
  at: number;
  from: string;
  /** Why it didn't arrive, or a note ("replaced your copy"). */
  detail: string;
}

export interface ActorFiles {
  /** The folder received files are saved in (absolute). */
  receiveDir: string;
  /** Accept without asking, and replace files with the same name (the v0.3 rule). */
  autoAccept: boolean;
  incoming: IncomingFile[];
  /** Newest first. */
  recent: ReceivedFile[];
}

export type SendFileState = "queued" | "offered" | "sending" | "ok" | "declined" | "failed" | "cancelled";

/** One batch of files to one actor, from this director. */
export interface SendBatch {
  id: string;
  actorId: string;
  actorName: string;
  files: number;
  done: number;
  ok: number;
  failed: number;
  bytes: number;
  sentBytes: number;
  /** The file on its way; `waiting` until the actor accepts it. */
  current: { name: string; size: number; sent: number; waiting: boolean } | null;
  state: "waiting" | "sending" | "done" | "cancelled" | "failed";
  detail: string;
  results: { name: string; state: SendFileState; detail: string }[];
}

export interface DirectorLocal {
  files: { batches: SendBatch[] };
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
  director: DirectorLocal | null;
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
  | {
      call: "setActorLocal";
      args: { soundpadEnabled?: boolean; oscEnabled?: boolean; soundpadPath?: string; receiveDir?: string; autoAcceptFiles?: boolean };
    }
  | { call: "pickReceiveDir" }
  | { call: "answerFile"; args: { transferId: string; accept: boolean; rest?: boolean; always?: boolean } }
  /** Files from a folder opened with `folders.open(folder, "all")`, each with the actor who gets it. */
  | { call: "sendFiles"; args: { folder: string; items: { path: string; actorId: string }[] } }
  /** A batch id, or "all". */
  | { call: "cancelBatch"; args: { id: string } }
  | { call: "camera"; args: { action: "roll" | "cut" } }
  | { call: "openBrowser" };

/**
 * Folder access for Normalize folder (spec §8.4.2) and Send files (§8.4). The agent serves it
 * under /api/folders/ (pick, open, read, write; agent/web.py + agent/folders.py) rather than as
 * calls, because it moves file bytes. The demo transport simulates a folder.
 */
export interface FolderFile {
  /** Relative to the folder, with forward slashes. */
  path: string;
  size: number;
}

export interface FolderListing {
  /** The folder as the agent resolved it (absolute). */
  folder: string;
  /** Where copies go: `<folder>/normalized`. */
  output: string;
  files: FolderFile[];
  /** More than 5000 audio files; only the first 5000 are listed. */
  truncated: boolean;
}

export const SCALE_MIN = 0.75;
export const SCALE_MAX = 2;
export const VR_SCALE = 1.4;

export function clampScale(value: number): number {
  if (!Number.isFinite(value)) return 1;
  return Math.round(Math.min(SCALE_MAX, Math.max(SCALE_MIN, value)) * 20) / 20;
}
