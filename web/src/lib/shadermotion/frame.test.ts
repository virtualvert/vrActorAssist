import { describe, expect, test } from "bun:test";
import { FRAME_SLOTS, faceSources, isStrip } from "./frame";

function frame(): number[] {
  const v = new Array<number>(FRAME_SLOTS).fill(0);
  v.splice(6, 6, 0, 0.5, 0, 0, 0, 0.5); // hips y and z axes: orthogonal, long enough
  return v;
}

describe("isStrip", () => {
  test("a real strip", () => expect(isStrip(frame())).toBe(true));
  test("the dense grid's marker plays too", () => {
    const v = frame();
    v[133] = 0.5;
    v[134] = -0.5;
    expect(isStrip(v)).toBe(true);
  });
  test("scene pixels fail the hips test", () => {
    const v = frame();
    v.splice(6, 6, 0.4, 0.4, 0.1, 0.5, 0.3, -0.2);
    expect(isStrip(v)).toBe(false);
    expect(isStrip(new Array(FRAME_SLOTS).fill(0))).toBe(false);
  });
});

describe("faceSources", () => {
  test("no face block: neutral", () => expect(faceSources(frame())).toBeNull());
  test("weights follow the header", () => {
    const v = frame();
    v.splice(135, 5, 0.5, -0.5, 0.125, 0.75, 0.25);
    const face = faceSources(v)!;
    expect(face[0]).toBe(0.75);
    expect(face[1]).toBe(0.25);
    expect(face.length).toBe(102 + 5); // + the vowel visemes AvatarView may read
  });
});
