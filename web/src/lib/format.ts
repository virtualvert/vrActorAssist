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

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[1][0]).toUpperCase();
}
