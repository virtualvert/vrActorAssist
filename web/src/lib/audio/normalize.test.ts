import { describe, expect, test } from "bun:test";
import { measure } from "./loudness";
import { clampSetting, DEFAULT_SETTINGS, planGain, planOutputs, TARGET_RANGE } from "./normalize";
import { encodeWav16, readWav16 } from "./wav";

const loudness = (integrated: number, truePeak: number) => ({ integrated, truePeak, durationS: 3, short: false });

describe("planGain", () => {
  test("brings a file to the target", () => {
    const plan = planGain(loudness(-24, -9), DEFAULT_SETTINGS)!;
    expect(plan.gainDb).toBeCloseTo(8);
    expect(plan.resultLufs).toBeCloseTo(-16);
    expect(plan.resultPeak).toBeCloseTo(-1);
    expect(plan.peakLimited).toBe(false);
  });

  test("turns loud files down", () => {
    expect(planGain(loudness(-10, -0.5), DEFAULT_SETTINGS)!.gainDb).toBeCloseTo(-6);
  });

  test("holds back when the peak would pass the ceiling", () => {
    const plan = planGain(loudness(-20, -2), DEFAULT_SETTINGS)!;
    expect(plan.gainDb).toBeCloseTo(1);
    expect(plan.resultLufs).toBeCloseTo(-19);
    expect(plan.resultPeak).toBeCloseTo(-1);
    expect(plan.peakLimited).toBe(true);
  });

  test("a sliver of headroom isn't reported as limited, but the gain still respects the ceiling", () => {
    const plan = planGain(loudness(-18, -2.98), DEFAULT_SETTINGS)!;
    expect(plan.gainDb).toBeCloseTo(1.98);
    expect(plan.peakLimited).toBe(false);
  });

  test("silence gets no plan", () => {
    expect(planGain(loudness(-Infinity, -Infinity), DEFAULT_SETTINGS)).toBeNull();
  });
});

describe("planOutputs", () => {
  test("copies keep their folder and name, as .wav", () => {
    expect(planOutputs(["Scene 4 - Diego.mp3", "sfx/door.flac"])).toEqual([
      { path: "Scene 4 - Diego.mp3", output: "Scene 4 - Diego.wav" },
      { path: "sfx/door.flac", output: "sfx/door.wav" },
    ]);
  });

  test("of two files with one name, the lossless one wins", () => {
    const plans = planOutputs(["a/Line.mp3", "a/line.wav", "b/line.mp3"]);
    expect(plans[0]).toEqual({ path: "a/Line.mp3", output: null, skipReason: "Same name as a/line.wav" });
    expect(plans[1].output).toBe("a/line.wav");
    expect(plans[2].output).toBe("b/line.wav");
  });

  test("names without an extension and dotted folders", () => {
    expect(planOutputs(["v1.2/take"])[0].output).toBe("v1.2/take.wav");
  });
});

describe("clampSetting", () => {
  test("keeps values in range, one decimal", () => {
    expect(clampSetting(-50, TARGET_RANGE, -16)).toBe(-36);
    expect(clampSetting(-15.04, TARGET_RANGE, -16)).toBe(-15);
    expect(clampSetting(Number.NaN, TARGET_RANGE, -16)).toBe(-16);
  });
});

describe("16-bit WAV", () => {
  test("round-trips within one step, with the gain applied", () => {
    const rate = 48000;
    const x = new Float32Array(rate).map((_, i) => 0.25 * Math.sin((2 * Math.PI * 440 * i) / rate));
    const bytes = encodeWav16({ rate, channels: [x, x] }, 6.0206, () => 0.5);
    expect(new TextDecoder().decode(bytes.slice(0, 4))).toBe("RIFF");
    const back = readWav16(bytes);
    expect(back.rate).toBe(rate);
    expect(back.channels.length).toBe(2);
    for (let i = 0; i < x.length; i += 997) expect(Math.abs(back.channels[1][i] - 2 * x[i])).toBeLessThan(2 / 32768);
  });

  test("clips instead of wrapping", () => {
    const back = readWav16(encodeWav16({ rate: 8000, channels: [new Float32Array([0.9, -0.9])] }, 6, () => 0.5));
    expect(back.channels[0][0]).toBeCloseTo(32767 / 32768, 5);
    expect(back.channels[0][1]).toBe(-1);
  });

  test("a normalized copy measures at the target", () => {
    const rate = 48000;
    const x = new Float32Array(rate * 5).map((_, i) => 0.05 * Math.sin((2 * Math.PI * 1000 * i) / rate));
    const before = measure([x, x], rate);
    const plan = planGain(before, DEFAULT_SETTINGS)!;
    const after = measure(readWav16(encodeWav16({ rate, channels: [x, x] }, plan.gainDb)).channels, rate);
    expect(after.integrated).toBeCloseTo(-16, 1);
  });
});
