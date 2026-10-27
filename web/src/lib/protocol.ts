// Contract between the web UI and whatever drives it: the local agent (agent/core.py snapshot() builds
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
  /** An actor's Soundpad as its app reports it (v2 relay); null for others and before the first report. */
  soundpad: PeerSoundpad | null;
  /**
   * An actor's delay in ms, set by a director and stored by the relay (spec §8.2.3): their
   * scheduled cues start this much later (negative: earlier). null for others and on a v0.3 relay.
   */
  delayMs: number | null;
  /** How late this actor's last scheduled start ran, in ms (from its ack); null until known. */
  lastLateMs: number | null;
}

export type Lines = "both" | "speakers" | "mic";

/** soundpad.state from an actor (spec §8.1.6). Position moves in ~140 ms steps; interpolate from `at`. */
export interface PeerSoundpad {
  /** False while Soundpad is off, missing or not answering (`detail` says why). */
  available: boolean;
  status: PlayStatus | null;
  positionMs: number;
  durationMs: number;
  title: string | null;
  index: number | null;
  key: string | null;
  lines: Lines | null;
  volume: number | null;
  muted: boolean | null;
  detail: string;
  /** The actor's own setting "Add received files to Soundpad"; null: their app doesn't say (older builds). */
  autoAddReceived: boolean | null;
  /** Their Soundpad is the trial, which can't add sounds; null: unknown. */
  trial: boolean | null;
  /** When the agent received this report (ms since epoch). */
  at: number;
  /** From the last calibration this director asked for (ms); null until then. */
  startLatencyMs: number | null;
}

/** A sound in an actor's list: the key stands for the file on their PC (its path isn't sent). */
export interface SoundEntry {
  index: number;
  key: string;
  title: string;
  durationMs: number | null;
}

export interface SoundList {
  peerId: string;
  sounds: SoundEntry[];
  categories: { index: number; name: string }[];
  total: number;
  at: number;
}

/** How to name a sound to an actor (spec §8.1.3). */
export type SoundRef = { key: string } | { sha256: string } | { index: number } | { selected: true } | { category: string; position: number };

export interface PendingActor {
  id: string;
  name: string;
}

/** Director only (v2 relay): an approved actor or camera that isn't connected. `forget` takes its id. */
export interface OfflineMachine {
  /** "offline:<machine id>" */
  id: string;
  name: string;
  role: "actor" | "camera";
  /** When the relay approved it (ISO time), if it knows. */
  approvedAt: string | null;
}

/**
 * ready: Soundpad answers on its remote-control pipe. closed: Soundpad isn't running, so cues
 * can't play (the app never starts it through a cue). fallback: it runs but its pipe can't be
 * used, so cues go through
 * `Soundpad.exe -rc` (no playback status). missing: neither works.
 */
export type SoundpadState = "ready" | "closed" | "fallback" | "simulated" | "missing" | "disabled";
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
  /** Where the sound plays (spec §8.1.4); null while stopped. */
  lines: Lines | null;
}

export interface ActorLocal {
  soundpad: {
    enabled: boolean;
    state: SoundpadState;
    detail: string;
    /** Only while the pipe is connected. */
    info: SoundpadInfo | null;
    playback: SoundpadPlayback | null;
    /** 0–100; null when unknown. One volume for both lines (spec §8.1.5). */
    volume: number | null;
    muted: boolean | null;
    /** Output line when the director doesn't pick one. */
    defaultLines: Lines;
    /** Add received files to Soundpad (full version). */
    autoAddReceived: boolean;
    /** Start Soundpad.exe when it isn't running. */
    autoLaunch: boolean;
    /** Soundpad.exe as set in Settings or by Detect; empty = found automatically. */
    path: string;
  };
  osc: { enabled: boolean; host: string; port: number; ready: boolean };
  lastCue: { command: string; at: number; ok: boolean } | null;
  files: ActorFiles;
  timing: ActorTiming;
}

/**
 * When this actor's scheduled cues start (spec §8.2.3):
 * fire_at = at + delayMs − startLatencyMs (the last term only with autoCompensate).
 */
export interface ActorTiming {
  /** Soundpad's start latency: the median of the last measured plays, else 60 ms assumed. */
  startLatencyMs: number;
  /** False while the 60 ms default is used (no play measured yet). */
  measured: boolean;
  samples: number;
  autoCompensate: boolean;
  /** Set by a director (0 on a v0.3 relay). */
  delayMs: number;
}

/** This app's clock against the relay's (spec §8.2.1); synced false off a v2 relay. */
export interface ClockState {
  synced: boolean;
  /** Relay time minus this PC's clock, ms (positive: this PC is behind). */
  offsetMs: number | null;
  /** Round trip of the best sample, ms. */
  rttMs: number | null;
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
  /** `sha256` is set for files that arrived, so the director can play them ("Sent files"). */
  results: { name: string; state: SendFileState; detail: string; sha256: string | null }[];
}

/** A sound armed for GO on one actor: GO plays it instead of their selected sound (Phase 2 M3). */
export interface ArmedSound {
  /** v0.3 apps and older builds can only be armed by number ({ index }). */
  sound: SoundRef;
  label: string;
  /** null: the actor's default line. */
  lines: Lines | null;
}

export interface DirectorLocal {
  files: { batches: SendBatch[] };
  /** GO goes out for server time now + leadMs, so actors start together (spec §8.2.2); 0 = at once. */
  leadMs: number;
  /** By actor peer id; kept after GO until cleared. */
  armed: Record<string, ArmedSound>;
}

export interface CameraLocal {
  obs: { connected: boolean; detail: string };
  recording: boolean;
  recordingSince: number | null;
}

/**
 * Play in 3s (director) or a scheduled cue more than 1 s ahead (actor). `endsAt` is on this PC's
 * clock (ms since epoch); the agent converts it from the relay's time.
 */
export interface Countdown {
  endsAt: number;
  durationMs: number;
}

export interface AppState {
  appVersion: string;
  demo: boolean;
  /** The folder with agent.log, for bug reports (null in the demo). */
  logDir: string | null;
  /** null until the user picks a seat; afterwards the app always opens in that role. */
  role: Role | null;
  prefs: Prefs;
  profile: Profile;
  connection: Connection;
  /** Everyone we know about, including ourselves (`self: true`). The relay itself is implicit. */
  peers: Peer[];
  pending: PendingActor[];
  /** Director only: approved actors and cameras that have left, so they can be forgotten. */
  offline: OfflineMachine[];
  /** Director only: peer ids that receive Go / Stop. */
  targets: string[];
  countdown: Countdown | null;
  clock: ClockState;
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
  | ({ type: "sounds" } & SoundList)
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
  /** A connected peer's id, or an offline machine's ("offline:…"). */
  | { call: "forget"; args: { id: string } }
  | {
      call: "setActorLocal";
      args: {
        soundpadEnabled?: boolean;
        oscEnabled?: boolean;
        soundpadPath?: string;
        receiveDir?: string;
        autoAcceptFiles?: boolean;
        defaultLines?: Lines;
        autoAddReceived?: boolean;
        autoLaunch?: boolean;
        autoCompensateLatency?: boolean;
      };
    }
  | { call: "setDirectorLocal"; args: { leadMs?: number } }
  | { call: "detectSoundpad" }
  /** Director → actors' Soundpad (v2 relay). `lines` left out = each actor's default. `label` is only for the log. */
  | { call: "play"; args: { ids: string[]; sound: SoundRef; lines?: Lines; volume?: number; startMs?: number; label?: string } }
  /** `*play:N`: works for v0.3 actors and on a v0.3 relay too. */
  | { call: "playIndex"; args: { ids: string[]; index: number } }
  | {
      call: "transport";
      args: { ids: string[]; action: "pause" | "resume" | "stop" | "mute" | "unmute" | "volume" | "seek" | "jump"; value?: number };
    }
  /** The actor's sound list arrives as a "sounds" event (the last one first, if known). */
  | { call: "requestSounds"; args: { id: string } }
  /** Director: an actor's delay in ms (−10000 – 10000), stored by the relay. */
  | { call: "setDelay"; args: { id: string; ms: number } }
  /** Measure the start latency with a speakers-only test play. Directors name the actor; an actor calibrates itself. */
  | { call: "calibrate"; args: { id?: string; sound?: SoundRef } }
  /** GO plays this sound on that actor until it's disarmed. `lines` left out = the actor's default. */
  | { call: "arm"; args: { id: string; sound: SoundRef; label: string; lines?: Lines | null } }
  | { call: "disarm"; args: { id: string } }
  | { call: "pickReceiveDir" }
  | { call: "answerFile"; args: { transferId: string; accept: boolean; rest?: boolean; always?: boolean } }
  /** Files from a folder opened with `folders.open(folder, "all")`, each with the actor who gets it. */
  | { call: "sendFiles"; args: { folder: string; items: { path: string; actorId: string }[] } }
  /** A batch id, or "all". */
  | { call: "cancelBatch"; args: { id: string } }
  /** Remove finished batches from the list: a batch id, or "all" (running ones stay). */
  | { call: "clearBatches"; args: { id: string } }
  | { call: "camera"; args: { action: "roll" | "cut" } }
  | { call: "openBrowser" }
  /** Show the log folder (`logDir`) in Explorer / the file manager. */
  | { call: "openLogFolder" };

/**
 * Folder access for Normalize folder (spec §8.4.2) and Send files (§8.4). The agent serves it
 * under /api/folders/ (pick, open, read, durations, write; agent/web.py + agent/folders.py) rather than as
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
