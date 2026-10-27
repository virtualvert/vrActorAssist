import { describe, expect, test } from "bun:test";
import { actorHero } from "./actorHero";
import type { ActorLocal, AppState } from "./protocol";
import { appState, peer } from "./testing";

const NOW = 1_800_000_000_000;

function state(actor: Partial<ActorLocal> = {}, extra: Partial<AppState> = {}): AppState {
  return appState({
    role: "actor",
    profile: { name: "Vega", serverUrl: "ws://x", hasSecret: false },
    peers: [peer("self", "actor", { name: "Vega", latencyMs: null, self: true })],
    clock: { synced: true, offsetMs: 9000, rttMs: 50 },
    actor: {
      soundpad: { enabled: false, state: "disabled", detail: "", info: null, playback: null, volume: null, muted: null, defaultLines: "both", autoAddReceived: true, autoLaunch: false, path: "" },
      osc: { enabled: true, host: "127.0.0.1", port: 9000, ready: true },
      lastCue: null,
      files: { receiveDir: "", autoAccept: false, incoming: [], recent: [] },
      timing: { startLatencyMs: 60, measured: false, samples: 0, autoCompensate: true, delayMs: 0 },
      ...actor,
    },
    ...extra,
  });
}

describe("actorHero", () => {
  test("a Stop with Soundpad off says Stopped, not GO! (laptop run, M3)", () => {
    expect(actorHero(state({ lastCue: { command: "*stop", at: NOW - 500, ok: true } }), NOW).title).toBe("Stopped");
    expect(actorHero(state({ lastCue: { command: "*stop", at: NOW - 5000, ok: true } }), NOW).title).toBe("Ready");
  });
  test("a GO with Soundpad off still says GO!", () => {
    const hero = actorHero(state({ lastCue: { command: "*go", at: NOW - 500, ok: true } }), NOW);
    expect(hero.title).toBe("GO!");
    expect(hero.sub).toContain("Soundpad is off");
  });
  test("the countdown comes first, in whole seconds", () => {
    expect(actorHero(state({}, { countdown: { endsAt: NOW + 2940, durationMs: 3000 } }), NOW).title).toBe("Playing in 3");
    expect(actorHero(state({}, { countdown: { endsAt: NOW + 900, durationMs: 3000 } }), NOW).title).toBe("Playing in 1");
  });
  test("a failed cue, and Soundpad's own status when it reports one", () => {
    expect(actorHero(state({ lastCue: { command: "*go", at: NOW - 100, ok: false } }), NOW).title).toBe("Cue failed");
    const sp = state().actor!.soundpad;
    const playing = { ...sp, enabled: true, state: "ready" as const, playback: { status: "PLAYING" as const, positionMs: 1000, durationMs: 5000, title: "firework", lines: "both" as const } };
    expect(actorHero(state({ soundpad: playing, lastCue: { command: "*go", at: NOW - 100, ok: true } }), NOW).title).toBe("Playing");
    const stopped = { ...playing, playback: { ...playing.playback, status: "STOPPED" as const } };
    expect(actorHero(state({ soundpad: stopped, lastCue: { command: "*stop", at: NOW - 100, ok: true } }), NOW).title).toBe("Ready");
  });
});
