import { describe, expect, test } from "bun:test";
import { mat4 } from "gl-matrix";
import { axisDirections, projectSegment } from "./overlay";

// a camera 3 m back on +z looking down -z, like AvatarView's default
const vp = mat4.multiply(mat4.create(), mat4.perspective(mat4.create(), Math.PI / 4, 1, 0.1, 100), mat4.fromTranslation(mat4.create(), [0, 0, -3]));

describe("projectSegment", () => {
  test("in front: both ends on the canvas", () => {
    const s = projectSegment(vp, [-1, 0, 0], [1, 0, 0], 200, 200)!;
    expect(s[0]).toBeLessThan(100);
    expect(s[2]).toBeGreaterThan(100);
    expect(s[1]).toBeCloseTo(100);
  });
  test("crossing the camera: cut at the near plane", () => {
    const s = projectSegment(vp, [0, -1, 0], [0, -1, 10], 200, 200)!;
    expect(s.every(Number.isFinite)).toBe(true);
    expect(s[3]).toBeGreaterThan(s[1]); // the near end is lower on the canvas
  });
  test("all behind: nothing", () => expect(projectSegment(vp, [0, 0, 4], [1, 0, 5], 200, 200)).toBeNull());
});

describe("axisDirections", () => {
  test("default view: X to the left (mirrored), Y up, Z toward the viewer", () => {
    const [x, y, z] = axisDirections([0, 0]);
    expect(x[0]).toBeCloseTo(-1);
    expect(y[1]).toBeCloseTo(-1);
    expect(z[2]).toBeCloseTo(1);
  });
  test("turned a quarter: Z points right", () => {
    const [, , z] = axisDirections([0, Math.PI / 2]);
    expect(z[0]).toBeCloseTo(1);
  });
});
