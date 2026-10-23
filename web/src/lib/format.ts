import type { Activity, Peer, PeerStatus } from "./protocol";

export type LatencyLevel = "good" | "fair" | "poor" | "lost" | "unknown";

/** Same thresholds as the v0.3 director: <100 ms good, ≤300 ms fair, above that poor. */
export function latencyLevel(status: PeerStatus, latencyMs: number | null): LatencyLevel {
  if (status === "timeout") return "lost";
  if (latencyMs === null || latencyMs <= 0) return "unknown";
  if (latencyMs < 100) return "good";
  if (latencyMs <= 300) return "fair";
  return "poor";
}

export function latencyText(status: PeerStatus, latencyMs: number | null): string {
  if (status === "pending") return "Waiting for approval";
  if (status === "timeout") return "No response";
  if (latencyMs === null || latencyMs <= 0) return "Online";
  return `${latencyMs} ms`;
}

export const ACTIVITY_TEXT: Record<Activity, string> = {
  idle: "Idle",
  playing: "Playing",
  rolling: "Rolling",
};

/** Short status line for a peer: activity wins over latency when something is happening. */
export function peerSubtitle(peer: Pick<Peer, "status" | "latencyMs" | "activity">): string {
  if (peer.status === "online" && peer.activity !== "idle") return ACTIVITY_TEXT[peer.activity];
  return latencyText(peer.status, peer.latencyMs);
}

export function clockTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

/** "12s ago", "3m ago" — for the last cue and similar. */
export function ago(ts: number, now: number): string {
  const s = Math.max(0, Math.round((now - ts) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.round(m / 60)}h ago`;
}

/** 00:01:23 for recording timers. */
export function duration(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

/** 1:23 (or 1:02:03) for a position in a sound, like a media player. */
export function mediaTime(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

/** A sound's length, rounded to the second like Soundpad's own list (49.6 s → 0:50). */
export function mediaLength(ms: number): string {
  return mediaTime(Math.round(Math.max(0, ms) / 1000) * 1000);
}

/** A file's length to a tenth of a second (0:04.2, 0:00.3), for short lines and effects. */
export function clipLength(ms: number): string {
  const tenths = Math.round(Math.max(0, ms) / 100);
  return `${mediaTime(Math.floor(tenths / 10) * 1000)}.${tenths % 10}`;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}

/** Decibels with one decimal and a real minus sign; `signed` adds "+" to gains. "—" when unknown. */
export function decibels(value: number, signed = false): string {
  if (!Number.isFinite(value)) return "—";
  const rounded = Math.round(value * 10) / 10;
  const text = Math.abs(rounded).toFixed(1);
  if (rounded < 0) return `−${text}`;
  return signed && rounded > 0 ? `+${text}` : text;
}

/** "350 KB", "1.2 MB", "2.4 GB" — sizes of files being sent. */
export function fileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024 * 1024) return `${Math.max(bytes ? 1 : 0, Math.round(bytes / 1024))} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
}

/** Whole percent, never 100 before the end. */
export function percent(done: number, total: number): number {
  if (total <= 0) return done > 0 ? 100 : 0;
  return done >= total ? 100 : Math.min(99, Math.floor((done / total) * 100));
}
