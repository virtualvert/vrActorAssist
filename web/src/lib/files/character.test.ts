import { describe, expect, test } from "bun:test";
import { assignments, groupFiles, parseCharacterName } from "./character";

describe("parseCharacterName", () => {
  // The examples from the v0.3 director's docstring, plus the edges
  test.each([
    ["Scene 4 - Diego.mp3", "Diego"],
    ["EP3 - Scene 4.2 - Diego.wav", "Diego"],
    ["intro.wav", null],
    ["Scene 4 - .mp3", null],
    ["Scene 4 - Mira Jones.flac", "Mira Jones"],
    ["Scene 4 - Diego", "Diego"],
    ["Scene 4 -Diego.wav", null],
    ["Scene 4 - Diego.take2.wav", "Diego.take2"],
  ])("%s → %s", (name, character) => {
    expect(parseCharacterName(name)).toBe(character);
  });
});

test("groupFiles groups by character and keeps the order", () => {
  const groups = groupFiles(["a/Scene 1 - Diego.wav", "intro.wav", "Scene 1 - Mira.wav", "normalized/Scene 2 - Diego.wav"]);
  expect([...groups.characters.keys()]).toEqual(["Diego", "Mira"]);
  expect(groups.characters.get("Diego")).toEqual(["a/Scene 1 - Diego.wav", "normalized/Scene 2 - Diego.wav"]);
  expect(groups.loose).toEqual(["intro.wav"]);
});

test("assignments: character map, per-file overrides, skips and clashes", () => {
  const paths = ["Scene 1 - Diego.wav", "Scene 2 - Diego.wav", "Scene 1 - Mira.wav", "intro.wav", "x/Scene 1 - Diego.wav"];
  const { items, clashes } = assignments(paths, { Diego: "s_coda", Mira: "" }, { "intro.wav": "s_rin", "x/Scene 1 - Diego.wav": "s_rin" });
  expect(items).toEqual([
    { path: "Scene 1 - Diego.wav", actorId: "s_coda" },
    { path: "Scene 2 - Diego.wav", actorId: "s_coda" },
    { path: "intro.wav", actorId: "s_rin" },
    { path: "x/Scene 1 - Diego.wav", actorId: "s_rin" },
  ]);
  expect(clashes).toEqual([]);
  const clash = assignments(["a/Scene 1 - Diego.wav", "b/Scene 1 - Diego.wav"], { Diego: "s_coda" }, {});
  expect(clash.clashes).toEqual(["Scene 1 - Diego.wav"]);
});
