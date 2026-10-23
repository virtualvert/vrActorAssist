import { describe, expect, test } from "bun:test";
import { ago, clipLength, decibels, duration, fileSize, initials, latencyLevel, mediaLength, mediaTime, peerSubtitle, percent } from "./format";
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

  test("clipLength keeps tenths, so short effects don't read 0:00", () => {
    expect(clipLength(300)).toBe("0:00.3");
    expect(clipLength(4_249)).toBe("0:04.2");
    expect(clipLength(59_960)).toBe("1:00.0");
    expect(clipLength(3_725_400)).toBe("1:02:05.4");
    expect(clipLength(-5)).toBe("0:00.0");
  });

  test("mediaLength rounds like Soundpad's list", () => {
    expect(mediaLength(49_600)).toBe("0:50");
    expect(mediaLength(49_400)).toBe("0:49");
    expect(mediaLength(2_000)).toBe("0:02");
    expect(mediaTime(49_600)).toBe("0:49"); // positions still count whole seconds
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

describe("decibels", () => {
  test("one decimal, real minus sign, optional plus", () => {
    expect(decibels(-23.44)).toBe("−23.4");
    expect(decibels(7.96, true)).toBe("+8.0");
    expect(decibels(7.96)).toBe("8.0");
    expect(decibels(-0.04, true)).toBe("0.0");
    expect(decibels(-Infinity)).toBe("—");
  });
});

test("fileSize", () => {
  expect(fileSize(0)).toBe("0 KB");
  expect(fileSize(10)).toBe("1 KB");
  expect(fileSize(350 * 1024)).toBe("350 KB");
  expect(fileSize(1.25 * 1024 * 1024)).toBe("1.3 MB");
  expect(fileSize(2.4 * 1024 ** 3)).toBe("2.4 GB");
  expect(fileSize(-1)).toBe("—");
});

test("percent", () => {
  expect(percent(0, 0)).toBe(0);
  expect(percent(5, 0)).toBe(100);
  expect(percent(999, 1000)).toBe(99);
  expect(percent(1000, 1000)).toBe(100);
  expect(percent(250, 1000)).toBe(25);
});
