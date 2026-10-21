import { describe, expect, test } from "bun:test";
import { positionNow, searchSounds, soundpadReach } from "./soundpad";

describe("positionNow", () => {
  const base = { positionMs: 1400, durationMs: 5000, at: 10_000 };
  test("runs on while playing, up to the end", () => {
    expect(positionNow({ ...base, status: "PLAYING" }, 10_300)).toBe(1700);
    expect(positionNow({ ...base, status: "PLAYING" }, 99_999)).toBe(5000);
    expect(positionNow({ ...base, status: "PLAYING" }, 9_000)).toBe(1400);
  });
  test("stands still otherwise", () => {
    expect(positionNow({ ...base, status: "PAUSED" }, 20_000)).toBe(1400);
    expect(positionNow({ ...base, status: null }, 20_000)).toBe(1400);
  });
});

describe("searchSounds", () => {
  const sounds = [
    { index: 1, key: "a".repeat(16), title: "Scene 1 - Diego", durationMs: 1000 },
    { index: 2, key: "b".repeat(16), title: "Door slam", durationMs: 500 },
    { index: 12, key: "c".repeat(16), title: "Scene 12 - Mira", durationMs: null },
  ];
  test("every word, any order, any case", () => {
    expect(searchSounds(sounds, "diego SCENE").map((s) => s.index)).toEqual([1]);
    expect(searchSounds(sounds, "scene").map((s) => s.index)).toEqual([1, 12]);
    expect(searchSounds(sounds, "  ")).toHaveLength(3);
    expect(searchSounds(sounds, "nothing")).toEqual([]);
  });
  test("a number finds that sound", () => {
    expect(searchSounds(sounds, "#12").map((s) => s.title)).toEqual(["Scene 12 - Mira"]);
    expect(searchSounds(sounds, "2").map((s) => s.title)).toEqual(["Door slam"]);
  });
});

test("soundpadReach", () => {
  expect(soundpadReach({ role: "actor", caps: ["soundpad", "soundpad.list", "files"] })).toBe("full");
  expect(soundpadReach({ role: "actor", caps: ["legacy"] })).toBe("legacy");
  expect(soundpadReach({ role: "actor", caps: ["soundpad", "osc", "files"] })).toBe("old");
  expect(soundpadReach({ role: "camera", caps: [] })).toBe("none");
});
