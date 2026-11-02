// Floor grid and orientation gizmo, drawn on a 2D canvas behind the avatars (AvatarView clears to transparent).
import { mat4, vec4, type ReadonlyMat4 } from "gl-matrix";

/** AvatarView's camera.znear: for its perspective matrix, clip w is the distance in front of the camera. */
const NEAR = 0.1;

/** A world segment through `vp` into canvas pixels [x0, y0, x1, y1], cut where it passes behind the camera; null if all of it does. */
export function projectSegment(vp: ReadonlyMat4, a: number[], b: number[], width: number, height: number): number[] | null {
  const p = vec4.transformMat4(vec4.create(), [a[0], a[1], a[2], 1], vp);
  const q = vec4.transformMat4(vec4.create(), [b[0], b[1], b[2], 1], vp);
  if (p[3] < NEAR && q[3] < NEAR) return null;
  if (p[3] < NEAR) vec4.lerp(p, p, q, (NEAR - p[3]) / (q[3] - p[3]));
  else if (q[3] < NEAR) vec4.lerp(q, q, p, (NEAR - q[3]) / (p[3] - q[3]));
  const px = (v: vec4) => ((v[0] / v[3] + 1) / 2) * width;
  const py = (v: vec4) => ((1 - v[1] / v[3]) / 2) * height;
  return [px(p), py(p), px(q), py(q)];
}

/**
 * The X, Y and Z axes as seen by OrbitControls' rotation [x, y]: [right, down, toward the viewer] each, in the
 * mirrored view AvatarView draws (Unity's left-handed axes).
 */
export function axisDirections(rotation: number[]): number[][] {
  const m = mat4.create();
  mat4.rotateX(m, m, rotation[0]);
  mat4.rotateY(m, m, rotation[1]);
  mat4.scale(m, m, [-1, 1, 1]);
  return [0, 1, 2].map((axis) => {
    const v = vec4.transformMat4(vec4.create(), [axis === 0 ? 1 : 0, axis === 1 ? 1 : 0, axis === 2 ? 1 : 0, 0], m);
    return [v[0], -v[1], v[2]];
  });
}
