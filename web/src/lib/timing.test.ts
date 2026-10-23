import { describe, expect, test } from "bun:test";
import type { Peer } from "./protocol";
import { armedText, armReason, clockText, delayText, isArmed, leadWarnings, parseDelay } from "./timing";

const CURRENT = ["soundpad", "soundpad.list", "soundpad.calibrate", "schedule"];

function actor(id: string, extra: Partial<Peer> = {}): Peer {
  return {
    id,
    name: id,
    role: "actor",
    status: "online",
    latencyMs: 40,
    activity: "idle",
    self: false,
    caps: CURRENT,
    soundpad: null,
    delayMs: 0,
    lastLateMs: null,
    ...extra,
  };
}

describe("delayText and parseDelay", () => {
  test("signs and units", () => {
    expect(delayText(150)).toBe("+150 ms");
    expect(delayText(-200)).toBe("−200 ms");
    expect(delayText(0)).toBe("0 ms");
  });
  test("what a director types", () => {
    expect(parseDelay("150")).toBe(150);
    expect(parseDelay("+150 ms")).toBe(150);
    expect(parseDelay("−80")).toBe(-80);
    expect(parseDelay("-80ms")).toBe(-80);
    expect(parseDelay("1.5")).toBeNull();
    expect(parseDelay("20000")).toBeNull();
    expect(parseDelay("")).toBeNull();
  });
});

describe("clockText", () => {
  test("behind, ahead, in step, not synced", () => {
    expect(clockText({ synced: true, offsetMs: 9012, rttMs: 40 })).toContain("9.0 s behind");
    expect(clockText({ synced: true, offsetMs: -300, rttMs: 40 })).toContain("300 ms ahead of");
    expect(clockText({ synced: true, offsetMs: 12, rttMs: 40 })).toBe("In step with the relay's clock");
    expect(clockText({ synced: false, offsetMs: null, rttMs: null })).toContain("Not synced");
  });
});

describe("leadWarnings", () => {
  const peers = [actor("near", { latencyMs: 40 }), actor("far", { latencyMs: 380 }), actor("off", { latencyMs: 900 })];
  test("only targeted actors whose trip eats most of the lead", () => {
    // budget (300 − 60) × 0.8 = 192; far: (20 + 380) / 2 = 200
    expect(leadWarnings(peers, ["near", "far"], 300, 20)).toEqual([{ id: "far", name: "far", tripMs: 200 }]);
    expect(leadWarnings(peers, ["near", "far"], 600, 20)).toEqual([]);
    expect(leadWarnings(peers, ["near", "far", "off"], 0, 20)).toEqual([]);
  });
});

describe("armReason", () => {
  const legacy = actor("Lex", { caps: ["legacy"] });
  const old = actor("Old", { caps: ["soundpad", "osc"] });
  test("current apps take any sound", () => {
    expect(armReason(actor("Nova"), { key: "0123456789abcdef" }, "speakers", false)).toBeNull();
  });
  test("v0.3 apps, older builds and a v0.3 relay only by number on both lines", () => {
    expect(armReason(legacy, { index: 3 }, null, false)).toBeNull();
    expect(armReason(legacy, { key: "0123456789abcdef" }, null, false)).toContain("the v0.3 app");
    expect(armReason(old, { index: 3 }, "speakers", false)).toContain("older vrcActorSync build");
    expect(armReason(actor("Nova"), { key: "0123456789abcdef" }, null, true)).toContain("This relay is v0.3");
    expect(armReason(actor("Nova"), { index: 2 }, "both", true)).toBeNull();
  });
});

describe("isArmed and armedText", () => {
  const armed = { sound: { key: "0123456789abcdef" }, label: "Scene 4", lines: "speakers" as const };
  test("the same reference only", () => {
    expect(isArmed(armed, { key: "0123456789abcdef" })).toBe(true);
    expect(isArmed(armed, { key: "fedcba9876543210" })).toBe(false);
    expect(isArmed(armed, { index: 1 })).toBe(false);
    expect(isArmed(undefined, { index: 1 })).toBe(false);
  });
  test("label with the line", () => {
    expect(armedText(armed)).toBe("Scene 4 · speakers only");
    expect(armedText({ ...armed, lines: null })).toBe("Scene 4");
  });
});
