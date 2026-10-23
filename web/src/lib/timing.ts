// Pure helpers for scheduled cues, delays and armed sounds (spec §8.2, Phase 2 M3). Unit-tested in timing.test.ts.

import type { ArmedSound, ClockState, Lines, Peer, SoundRef } from "./protocol";
import { soundpadReach } from "./soundpad";

/** Start latency an actor assumes until it has measured its own (agent/scheduler.py). */
export const DEFAULT_START_LATENCY_MS = 60;
/** Later than this and a start counts as late (spec §8.2.3). */
export const LATE_MS = 20;
export const DELAY_LIMIT_MS = 10_000;

/** "+150 ms", "−200 ms", "0 ms". */
export function delayText(ms: number): string {
  if (ms === 0) return "0 ms";
  return `${ms > 0 ? "+" : "−"}${Math.abs(ms)} ms`;
}

/** How this PC's clock compares with the relay's. */
export function clockText(clock: ClockState): string {
  if (!clock.synced || clock.offsetMs === null) return "Not synced with the relay yet";
  const off = clock.offsetMs;
  if (Math.abs(off) < 50) return "In step with the relay's clock";
  const amount = Math.abs(off) >= 1000 ? `${(Math.abs(off) / 1000).toFixed(1)} s` : `${Math.abs(off)} ms`;
  return `This PC's clock is ${amount} ${off > 0 ? "behind" : "ahead of"} the relay's (that's fine: cues use the relay's time)`;
}

export interface LeadWarning {
  /** The peer's session id (names aren't unique). */
  id: string;
  name: string;
  /** Director → relay → actor, one way (ms). */
  tripMs: number;
}

/**
 * Targeted actors whose GO may arrive after its time (spec §8.2.2). A cue has to reach the actor
 * within the lead, less the start latency it's sent early by; past 80 % of that, warn.
 */
export function leadWarnings(peers: Peer[], targets: string[], leadMs: number, ownRttMs: number | null): LeadWarning[] {
  if (leadMs <= 0) return [];
  const budget = Math.max(0, leadMs - DEFAULT_START_LATENCY_MS) * 0.8;
  const wanted = new Set(targets);
  return peers
    .filter((p) => p.role === "actor" && wanted.has(p.id) && p.latencyMs !== null)
    .map((p) => ({ id: p.id, name: p.name, tripMs: Math.round(((ownRttMs ?? 0) + (p.latencyMs ?? 0)) / 2) }))
    .filter((w) => w.tripMs > budget);
}

/**
 * Why this sound can't be armed on this actor, or null. Only a sound number reaches v0.3 apps,
 * older builds and anything on a v0.3 relay (mirror of armable() in agent/cues.py).
 */
export function armReason(peer: Pick<Peer, "name" | "role" | "caps">, sound: SoundRef, lines: Lines | null, legacyRelay: boolean): string | null {
  if (peer.role !== "actor") return "Only actors play sounds";
  const full = soundpadReach(peer) === "full" && !legacyRelay;
  if (full) return null;
  const byNumber = "index" in sound && Object.keys(sound).length === 1 && (lines === null || lines === "both");
  if (byNumber) return null;
  if (legacyRelay) return "This relay is v0.3: arm a sound by its number";
  return `${peer.name} uses ${peer.caps.includes("legacy") ? "the v0.3 app" : "an older vrcActorSync build"}: arm a sound by its number`;
}

/** Whether exactly this sound is the one armed. */
export function isArmed(armed: ArmedSound | undefined, sound: SoundRef): boolean {
  if (!armed) return false;
  const a = armed.sound as Record<string, unknown>;
  const b = sound as Record<string, unknown>;
  const keys = Object.keys(b);
  return keys.length === Object.keys(a).length && keys.every((k) => a[k] === b[k]);
}

const LINE_WORD: Record<Lines, string> = { both: "both lines", speakers: "speakers only", mic: "mic only" };

/** "Scene 4 - Nova · speakers only". */
export function armedText(armed: ArmedSound): string {
  return armed.lines ? `${armed.label} · ${LINE_WORD[armed.lines]}` : armed.label;
}

/** Parse a delay typed by the director: whole ms within ±10 s, else null. */
export function parseDelay(text: string): number | null {
  const cleaned = text.trim().replace(/\s*ms$/i, "").replace("−", "-").replace(/^\+/, "");
  if (!/^-?\d+$/.test(cleaned)) return null;
  const ms = Number(cleaned);
  return Math.abs(ms) <= DELAY_LIMIT_MS ? ms : null;
}
