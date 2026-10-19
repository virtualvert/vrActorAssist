import { describe, expect, test } from "bun:test";
import { ago, duration, initials, latencyLevel, mediaTime, peerSubtitle } from "./format";
import { clampScale } from "./protocol";

describe("latencyLevel", () => {
  test("uses the v0.3 director thresholds", () => {
    expect(latencyLevel("online", 40)).toBe("good");
    expect(latencyLevel("online", 99)).toBe("good");
    expect(latencyLevel("online", 100)).toBe("fair");
    expect(latencyLevel("online", 300)).toBe("fair");
    expect(latencyLevel("online", 301)).toBe("poor");
    expect(latencyLevel("timeout", 40)).toBe("lost");
    expect(latencyLevel("online", null)).toBe("unknown");
  });
});

describe("text helpers", () => {
  test("activity wins over latency", () => {
    expect(peerSubtitle({ status: "online", latencyMs: 40, activity: "playing" })).toBe("Playing");
    expect(peerSubtitle({ status: "online", latencyMs: 40, activity: "idle" })).toBe("40 ms");
    expect(peerSubtitle({ status: "pending", latencyMs: null, activity: "idle" })).toBe("Waiting for approval");
  });

  test("duration, ago and initials", () => {
    expect(duration(83_000)).toBe("00:01:23");
    expect(ago(1000, 1000)).toBe("just now");
    expect(ago(0, 30_000)).toBe("30s ago");
    expect(initials("Cam A")).toBe("CA");
    expect(initials("quincey")).toBe("QU");
  });

  test("mediaTime reads like a player", () => {
    expect(mediaTime(0)).toBe("0:00");
    expect(mediaTime(49_721)).toBe("0:49");
    expect(mediaTime(83_999)).toBe("1:23");
    expect(mediaTime(3_723_000)).toBe("1:02:03");
    expect(mediaTime(-5)).toBe("0:00");
  });
});

describe("clampScale", () => {
  test("keeps the UI size in range and on a 5% grid", () => {
    expect(clampScale(5)).toBe(2);
    expect(clampScale(0.1)).toBe(0.75);
    expect(clampScale(1.234)).toBe(1.25);
    expect(clampScale(Number.NaN)).toBe(1);
  });
});
