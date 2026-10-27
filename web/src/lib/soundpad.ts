// Pure helpers for the director's Soundpad controls (spec §8.1). Unit-tested in soundpad.test.ts.

import type { Lines, Peer, PeerSoundpad, SoundEntry } from "./protocol";

/**
 * Where the sound is now. Soundpad reports its position in ~140 ms steps and actors report at
 * most twice a second, so while PLAYING the position runs on from the last report.
 */
export function positionNow(sp: Pick<PeerSoundpad, "status" | "positionMs" | "durationMs" | "at">, now: number): number {
  if (sp.status !== "PLAYING") return sp.positionMs;
  return Math.max(0, Math.min(sp.durationMs, sp.positionMs + Math.max(0, now - sp.at)));
}

/**
 * The position to show while a sound plays. Reports arrive with a varying delay (the actor reads
 * Soundpad every 250 ms, Soundpad moves in 140 ms steps), so a fresher report can sit a little
 * behind the running estimate; holding instead of stepping back keeps the bar from jittering.
 * Bigger differences (a seek, another sound) are shown as they are.
 */
export function steadyPosition(shown: number | null, computed: number, playing: boolean, maxBack = 500): number {
  if (!playing || shown === null) return computed;
  return computed < shown && shown - computed <= maxBack ? shown : computed;
}

/** Case-insensitive search over titles; every word must match somewhere; `#12` finds sound 12. */
export function searchSounds(sounds: SoundEntry[], query: string): SoundEntry[] {
  const q = query.trim().toLowerCase();
  if (!q) return sounds;
  const number = /^#?(\d+)$/.exec(q);
  if (number) return sounds.filter((s) => s.index === Number(number[1]));
  const words = q.split(/\s+/);
  return sounds.filter((s) => {
    const title = s.title.toLowerCase();
    return words.every((w) => title.includes(w));
  });
}

export type SoundpadReach = "full" | "legacy" | "old" | "none";

/**
 * What a director can do with this actor's Soundpad. full: the whole panel (v0.4 actor with a
 * list). legacy: v0.3 app, only Go / Stop / Play #N. old: an earlier v0.4 preview, same as
 * legacy. none: not an actor.
 */
export function soundpadReach(peer: Pick<Peer, "role" | "caps">): SoundpadReach {
  if (peer.role !== "actor") return "none";
  if (peer.caps.includes("legacy")) return "legacy";
  return peer.caps.includes("soundpad.list") ? "full" : "old";
}

export type WontAdd = "off" | "trial";

/**
 * Why an actor's app won't add the files it receives to Soundpad, so playing them fails: "off" (the
 * actor's own setting "Add received files to Soundpad"), "trial" (the Soundpad trial can't add
 * sounds). null: it adds them, or nobody knows (apps before this report don't say, v0.3 apps
 * send no Soundpad state).
 */
export function wontAddReceived(sp: Pick<PeerSoundpad, "autoAddReceived" | "trial"> | null): WontAdd | null {
  if (sp?.autoAddReceived === false) return "off";
  if (sp?.trial === true) return "trial";
  return null;
}

/** The director's warning about that: whose setting it is, and what happens to the files. */
export function wontAddText(name: string, why: WontAdd): string {
  const saved = "The files are saved on their PC, but playing them fails";
  return why === "off"
    ? `${name}'s app won't add received files to Soundpad: their setting "Add received files to Soundpad" is off. ${saved} until ${name} turns it on or adds them in Soundpad.`
    : `${name} has the Soundpad trial, which can't add sounds. ${saved} until ${name} adds them in Soundpad by hand.`;
}

export const LINE_OPTIONS = [
  { value: "default", label: "Default" },
  { value: "both", label: "Both" },
  { value: "speakers", label: "Speakers" },
  { value: "mic", label: "Mic" },
] as const;

export const LINE_HELP: Record<string, string> = {
  default: "Each actor's own default line",
  both: "The actor and the audience hear it",
  speakers: "Only the actor hears it (rehearsal)",
  mic: "The audience hears it, the actor doesn't",
};

/** The actor's own choice of line (Settings → Actor), worded for the actor. */
export const OWN_LINE_OPTIONS: { value: Lines; label: string }[] = [
  { value: "both", label: "Both" },
  { value: "speakers", label: "Speakers" },
  { value: "mic", label: "Mic" },
];

export const OWN_LINE_HELP: Record<Lines, string> = {
  both: "You and the audience hear it",
  speakers: "Only you hear it (rehearsal)",
  mic: "The audience hears it, you don't",
};

export const STATUS_TEXT = { STOPPED: "Stopped", PLAYING: "Playing", PAUSED: "Paused", SEEKING: "Seeking" } as const;
