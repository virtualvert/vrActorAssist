// The actor view's big status line, as a pure function of the state (unit-tested in actorHero.test.ts).

import { mediaLength, mediaTime } from "./format";
import type { AppState } from "./protocol";

export interface Hero {
  tone: string;
  title: string;
  sub: string;
}

/** How long a cue stays in the headline when Soundpad can't report playback (ms). */
export const CUE_SHOWN_MS = 3500;

const READY: Hero = { tone: "ready", title: "Ready", sub: "Waiting for the next cue from the director." };

export function actorHero(data: AppState, now: number): Hero {
  const c = data.connection;
  if (c.status === "error") return { tone: "bad", title: "Can't connect", sub: c.detail };
  if (c.status === "connecting") return { tone: "warn spin", title: "Connecting…", sub: c.detail };
  if (c.status === "pending")
    return { tone: "warn", title: "Waiting for the director", sub: "The director approves you once. After that you join automatically." };
  if (c.status !== "connected") return { tone: "idle", title: "Not connected", sub: "Connect to your relay to receive cues." };

  const actor = data.actor;
  const remaining = data.countdown ? data.countdown.endsAt - now : 0;
  if (remaining > 0) {
    return { tone: "warn", title: `Playing in ${Math.ceil(remaining / 1000)}`, sub: "Play in 3s from the director: everyone starts together." };
  }
  const recent = actor?.lastCue && now - actor.lastCue.at < CUE_SHOWN_MS ? actor.lastCue : null;
  if (recent && !recent.ok) {
    return { tone: "bad", title: "Cue failed", sub: actor?.soundpad.detail || "The last cue didn't run on this computer." };
  }
  // Soundpad's real status when it answers on its pipe; otherwise only the last cue is known
  const playback = actor?.soundpad.playback ?? null;
  if (playback) {
    if (playback.status === "STOPPED") return READY;
    const where = `${playback.title ?? "Your selected sound"} · ${mediaTime(playback.positionMs)} / ${mediaLength(playback.durationMs)}`;
    return playback.status === "PAUSED" ? { tone: "warn", title: "Paused", sub: where } : { tone: "go", title: "Playing", sub: where };
  }
  // A Stop is a cue too, but it isn't a GO (laptop run, M3: a cancelled Play in 3s showed "GO!")
  if (recent && recent.command.includes("stop")) return { tone: "ready", title: "Stopped", sub: "The director stopped the cue." };
  const self = data.peers.find((p) => p.self);
  if (self?.activity === "playing" || recent) {
    const sp = actor?.soundpad;
    return {
      tone: "go",
      title: "GO!",
      sub: sp?.enabled ? (sp.state === "simulated" ? "Cue received — Soundpad simulated on this system" : "Playing your selected sound") : "Cue received — Soundpad is off",
    };
  }
  return READY;
}
