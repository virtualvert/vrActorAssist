import { BlockStart, IsHeader, Shapes, Slot } from "./lib/SMX/FaceLayout.js";
import { DenseMarker, IsDenseMarker } from "./lib/SMX/MotionTracks.js";
import { SourceCount } from "./lib/SMX/Visemes.js";

/** Layer 0 has 270 slots: 135 humanoid, then the face block (header, 102 Unified Expressions weights). */
export const FRAME_SLOTS = 270;

export type StripStatus = "ok" | "dense" | "none";

/** What one decoded layer-0 frame holds: a strip the preview can play, the dense grid, or no strip at all. */
export function stripStatus(v: ArrayLike<number>): StripStatus {
  if (IsDenseMarker(v[DenseMarker.slot], v[DenseMarker.slot + 1])) return "dense";
  // MotionTracks.DetectLayers' hips test, minus its tile-error term (the UI only gets values)
  const ny = Math.hypot(v[6], v[7], v[8]);
  const nz = Math.hypot(v[9], v[10], v[11]);
  const cos = Math.abs(v[6] * v[9] + v[7] * v[10] + v[8] * v[11]) / (ny * nz || 1);
  return ny > 0.3 && nz > 0.3 && cos < 0.1 ? "ok" : "none";
}

/** AvatarView's face sources from the face block (exporter.js rawMorphs without visemes); null = neutral face. */
export function faceSources(v: ArrayLike<number>, out = new Float32Array(SourceCount)): Float32Array | null {
  if (!IsHeader(v[BlockStart], v[BlockStart + 1], v[BlockStart + 2])) return null;
  for (let i = 0; i < Shapes.length; i++) out[i] = v[Slot(i)];
  return out;
}
