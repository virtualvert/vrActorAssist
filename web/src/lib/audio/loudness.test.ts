import { describe, expect, test } from "bun:test";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { kWeighting, measure, toDb, truePeak } from "./loudness";
import { encodeWav16 } from "./wav";

const RATE = 48000;

function sine(freq: number, dbfs: number, seconds: number, phase = 0, rate = RATE): Float32Array {
  const amplitude = Math.pow(10, dbfs / 20);
  const out = new Float32Array(Math.round(seconds * rate));
  for (let i = 0; i < out.length; i++) out[i] = amplitude * Math.sin((2 * Math.PI * freq * i) / rate + phase);
  return out;
}

function concat(...parts: Float32Array[]): Float32Array {
  const out = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const p of parts) {
    out.set(p, offset);
    offset += p.length;
  }
  return out;
}

const stereo = (x: Float32Array) => [x, x.slice()];

describe("K-weighting", () => {
  test("matches the BS.1770 coefficients at 48 kHz", () => {
    const [shelf, highpass] = kWeighting(48000);
    expect(shelf.b0).toBeCloseTo(1.53512485958697, 9);
    expect(shelf.b1).toBeCloseTo(-2.69169618940638, 9);
    expect(shelf.b2).toBeCloseTo(1.19839281085285, 9);
    expect(shelf.a1).toBeCloseTo(-1.69065929318241, 9);
    expect(shelf.a2).toBeCloseTo(0.73248077421585, 9);
    expect(highpass.a1).toBeCloseTo(-1.99004745483398, 9);
    expect(highpass.a2).toBeCloseTo(0.99007225036621, 9);
  });
});

// EBU Tech 3341, integrated loudness test cases 1–5 (stereo 1 kHz sine, expected −23 ±0.1 LU
// except case 2 at −33).
describe("integrated loudness (EBU Tech 3341)", () => {
  test("case 1: −23 dBFS for 20 s", () => {
    expect(measure(stereo(sine(1000, -23, 20)), RATE).integrated).toBeCloseTo(-23, 1);
  });

  test("case 2: −33 dBFS for 20 s", () => {
    expect(measure(stereo(sine(1000, -33, 20)), RATE).integrated).toBeCloseTo(-33, 1);
  });

  test("case 3: −36 / −23 / −36 dBFS (absolute gate keeps the quiet parts out)", () => {
    const x = concat(sine(1000, -36, 10), sine(1000, -23, 60), sine(1000, -36, 10));
    expect(measure(stereo(x), RATE).integrated).toBeCloseTo(-23, 1);
  });

  test("case 4: −72 / −36 / −23 / −36 / −72 dBFS", () => {
    const x = concat(sine(1000, -72, 10), sine(1000, -36, 10), sine(1000, -23, 60), sine(1000, -36, 10), sine(1000, -72, 10));
    expect(measure(stereo(x), RATE).integrated).toBeCloseTo(-23, 1);
  });

  test("case 5: −26 / −20 / −26 dBFS (relative gate)", () => {
    const x = concat(sine(1000, -26, 20), sine(1000, -20, 20.1), sine(1000, -26, 20));
    expect(measure(stereo(x), RATE).integrated).toBeCloseTo(-23, 1);
  });

  test("one channel of the same sine is 3 dB quieter", () => {
    expect(measure([sine(1000, -23, 20)], RATE).integrated).toBeCloseTo(-26.01, 1);
  });

  test("44.1 kHz gives the same result", () => {
    expect(measure(stereo(sine(1000, -23, 20, 0, 44100)), 44100).integrated).toBeCloseTo(-23, 1);
  });
});

describe("edge cases", () => {
  test("a file shorter than 400 ms is measured as one block", () => {
    const m = measure(stereo(sine(1000, -23, 0.25)), RATE);
    expect(m.short).toBe(true);
    expect(Math.abs(m.integrated + 23)).toBeLessThan(0.3);
  });

  test("silence has no loudness and no peak", () => {
    const m = measure(stereo(new Float32Array(RATE * 2)), RATE);
    expect(m.integrated).toBe(-Infinity);
    expect(m.truePeak).toBe(-Infinity);
  });

  test("everything below −70 LUFS counts as silence", () => {
    expect(measure(stereo(sine(1000, -80, 5)), RATE).integrated).toBe(-Infinity);
  });
});

describe("true peak", () => {
  test("finds the peak between samples (fs/4 at 45°: samples sit 3 dB below it)", () => {
    const x = sine(12000, 0, 1, Math.PI / 4);
    let samplePeak = 0;
    for (const v of x) samplePeak = Math.max(samplePeak, Math.abs(v));
    expect(toDb(samplePeak)).toBeCloseTo(-3.01, 1);
    expect(Math.abs(toDb(truePeak([x])))).toBeLessThan(0.2);
  });

  // EBU Tech 3341 allows +0.2 / −0.4 dB for true-peak meters. The sines fade in and out: a hard
  // start really does overshoot between samples, which would hide the filter's own accuracy.
  test("stays within +0.2 / −0.4 dB from 1 to 20 kHz at any phase", () => {
    const fadeLength = Math.round(0.02 * RATE);
    const faded = (x: Float32Array) => {
      for (let i = 0; i < fadeLength; i++) {
        const g = 0.5 - 0.5 * Math.cos((Math.PI * i) / fadeLength);
        x[i] *= g;
        x[x.length - 1 - i] *= g;
      }
      return x;
    };
    for (const freq of [1000, 5000, 9000, 12000, 15000, 18000, 20000]) {
      for (const phase of [0.1, 0.37, 0.785, 1.2, 2.9]) {
        const error = toDb(truePeak([faded(sine(freq, -6, 0.5, phase))])) + 6;
        expect(error).toBeLessThanOrEqual(0.2);
        expect(error).toBeGreaterThanOrEqual(-0.4);
      }
    }
  });
});

// Cross-check against ffmpeg's EBU R128 meter when ffmpeg is installed (skipped otherwise).
const ffmpeg = Bun.which("ffmpeg");

describe.skipIf(!ffmpeg)("agrees with ffmpeg's ebur128 filter", () => {
  test("speech-like bursts with pauses", () => {
    // Deterministic noise bursts shaped like phrases, with silence between them.
    let seed = 7;
    const random = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
    const seconds = 12;
    const left = new Float32Array(RATE * seconds);
    const right = new Float32Array(RATE * seconds);
    let lp = 0;
    for (let i = 0; i < left.length; i++) {
      const t = i / RATE;
      const phrase = Math.floor(t / 1.5) % 2 === 0 ? 1 : 0.02;
      const envelope = phrase * (0.5 + 0.5 * Math.sin(2 * Math.PI * 3 * t) ** 2);
      lp += 0.2 * (random() * 2 - 1 - lp); // soften the noise a little
      left[i] = 0.3 * envelope * (lp + 0.5 * Math.sin(2 * Math.PI * 220 * t));
      right[i] = 0.8 * left[i];
    }
    const dir = mkdtempSync(join(tmpdir(), "vrcas-loudness-"));
    try {
      const file = join(dir, "speech.wav");
      writeFileSync(file, encodeWav16({ rate: RATE, channels: [left, right] }, 0, () => 0.5));
      const run = Bun.spawnSync([ffmpeg!, "-hide_banner", "-nostats", "-i", file, "-af", "ebur128=peak=true", "-f", "null", "-"]);
      const report = run.stderr.toString();
      const summary = report.slice(report.lastIndexOf("Summary:"));
      const integrated = Number(/I:\s+(-?[\d.]+) LUFS/.exec(summary)?.[1]);
      const peak = Number(/True peak:\s+Peak:\s+(-?[\d.]+) dBFS/.exec(summary)?.[1]);

      // Measure what was actually written (16-bit), not the float signal.
      const quantised = [left, right].map((ch) => ch.map((v) => Math.round(v * 32767) / 32768));
      const ours = measure(quantised, RATE);
      expect(Math.abs(ours.integrated - integrated)).toBeLessThanOrEqual(0.1);
      expect(Math.abs(ours.truePeak - peak)).toBeLessThanOrEqual(0.3);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
