/** Normalize folder: settings, the gain for each file and where its copy goes (spec §8.4.2). */

import type { Loudness } from "./loudness";

export interface NormalizeSettings {
  /** Integrated loudness every copy aims for, in LUFS. */
  targetLufs: number;
  /** No copy's true peak goes above this, in dBTP. */
  ceilingDbtp: number;
}

export const DEFAULT_SETTINGS: NormalizeSettings = { targetLufs: -16, ceilingDbtp: -1 };
export const TARGET_RANGE: [number, number] = [-36, -6];
export const CEILING_RANGE: [number, number] = [-12, 0];

/** When two files differ only by extension, the first format here wins (lossless first). */
const PREFERENCE = ["wav", "flac", "ogg", "oga", "opus", "m4a", "aac", "mp3"];

export interface GainPlan {
  gainDb: number;
  resultLufs: number;
  resultPeak: number;
  /** The peak ceiling held the gain back, so the copy stays quieter than the target. */
  peakLimited: boolean;
}

/** Gain that brings `m` to the target without its true peak passing the ceiling; null for silence. */
export function planGain(m: Loudness, settings: NormalizeSettings): GainPlan | null {
  if (!Number.isFinite(m.integrated)) return null;
  const wanted = settings.targetLufs - m.integrated;
  let gainDb = wanted;
  if (Number.isFinite(m.truePeak) && m.truePeak + gainDb > settings.ceilingDbtp) gainDb = settings.ceilingDbtp - m.truePeak;
  // Only call it limited when the copy really lands below the target (not by a rounding sliver).
  const peakLimited = wanted - gainDb >= 0.05;
  return { gainDb, resultLufs: m.integrated + gainDb, resultPeak: m.truePeak + gainDb, peakLimited };
}

export function clampSetting(value: number, [low, high]: [number, number], fallback: number): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.round(Math.min(high, Math.max(low, value)) * 10) / 10;
}

export interface SourcePlan {
  /** Relative path inside the folder, with forward slashes. */
  path: string;
  /** Relative path of the copy inside `normalized/`; null when the file is skipped. */
  output: string | null;
  skipReason?: string;
}

export function extensionOf(path: string): string {
  const name = path.slice(path.lastIndexOf("/") + 1);
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

/**
 * Every copy is `<same folder>/<same name>.wav`, so " - Character" routing keeps working.
 * Files that would collide (`line.wav` and `line.mp3`) keep the preferred format and skip the rest.
 */
export function planOutputs(paths: string[]): SourcePlan[] {
  const stemOf = (path: string) => {
    const dot = path.lastIndexOf(".");
    return dot > path.lastIndexOf("/") + 1 ? path.slice(0, dot) : path;
  };
  const rank = (path: string) => {
    const index = PREFERENCE.indexOf(extensionOf(path));
    return index < 0 ? PREFERENCE.length : index;
  };
  const winners = new Map<string, string>();
  for (const path of paths) {
    const key = stemOf(path).toLowerCase();
    const current = winners.get(key);
    if (current === undefined || rank(path) < rank(current)) winners.set(key, path);
  }
  return paths.map((path) => {
    const winner = winners.get(stemOf(path).toLowerCase());
    if (winner !== path) return { path, output: null, skipReason: `Same name as ${winner}` };
    return { path, output: `${stemOf(path)}.wav` };
  });
}
