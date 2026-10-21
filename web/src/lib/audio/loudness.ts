/**
 * Loudness (ITU-R BS.1770-4 / EBU R128) and true peak of decoded audio.
 *
 * Pure functions over Float32Array channels, so the same code runs in unit tests, in the page
 * and in the normalize worker. Spec §8.4.2.
 */

export interface Biquad {
  b0: number;
  b1: number;
  b2: number;
  a1: number;
  a2: number;
}

export interface Loudness {
  /** Integrated loudness in LUFS; -Infinity when everything is below the -70 LUFS gate. */
  integrated: number;
  /** True peak in dBTP (4× oversampled); -Infinity for digital silence. */
  truePeak: number;
  durationS: number;
  /** Shorter than one 400 ms block: measured as a single block, without gating. */
  short: boolean;
}

const OFFSET = -0.691;
const ABSOLUTE_GATE = -70;
const RELATIVE_GATE = -10;
/** 400 ms blocks built from 100 ms segments, so consecutive blocks overlap by 75 %. */
const BLOCK_SEGMENTS = 4;

/**
 * The two K-weighting filters (head shelf, then RLB high-pass) for any sample rate.
 * Derived from the analog prototypes as libebur128 does; at 48 kHz they match the BS.1770 table.
 */
export function kWeighting(rate: number): [Biquad, Biquad] {
  const shelfF0 = 1681.974450955533;
  const shelfGain = 3.999843853973347;
  const shelfQ = 0.7071752369554196;
  let k = Math.tan((Math.PI * shelfF0) / rate);
  const vh = Math.pow(10, shelfGain / 20);
  const vb = Math.pow(vh, 0.4996667741545416);
  let a0 = 1 + k / shelfQ + k * k;
  const shelf: Biquad = {
    b0: (vh + (vb * k) / shelfQ + k * k) / a0,
    b1: (2 * (k * k - vh)) / a0,
    b2: (vh - (vb * k) / shelfQ + k * k) / a0,
    a1: (2 * (k * k - 1)) / a0,
    a2: (1 - k / shelfQ + k * k) / a0,
  };

  const highF0 = 38.13547087602444;
  const highQ = 0.5003270373238773;
  k = Math.tan((Math.PI * highF0) / rate);
  a0 = 1 + k / highQ + k * k;
  const highpass: Biquad = {
    b0: 1,
    b1: -2,
    b2: 1,
    a1: (2 * (k * k - 1)) / a0,
    a2: (1 - k / highQ + k * k) / a0,
  };
  return [shelf, highpass];
}

/** BS.1770 channel weights: 1.0 for front channels, 1.41 for surrounds, LFE left out. */
export function channelWeights(count: number): number[] {
  if (count === 5) return [1, 1, 1, 1.41, 1.41];
  if (count === 6) return [1, 1, 1, 0, 1.41, 1.41];
  return new Array<number>(count).fill(1);
}

/** Sum of squared K-weighted samples per 100 ms segment (the last one may be partial). */
function segmentEnergy(x: Float32Array, [s, h]: [Biquad, Biquad], segment: number): Float64Array {
  const out = new Float64Array(Math.ceil(x.length / segment));
  let sx1 = 0, sx2 = 0, sy1 = 0, sy2 = 0;
  let hx1 = 0, hx2 = 0, hy1 = 0, hy2 = 0;
  let acc = 0;
  let filled = 0;
  let index = 0;
  for (let n = 0; n < x.length; n++) {
    const xn = x[n];
    const ys = s.b0 * xn + s.b1 * sx1 + s.b2 * sx2 - s.a1 * sy1 - s.a2 * sy2;
    sx2 = sx1;
    sx1 = xn;
    sy2 = sy1;
    sy1 = ys;
    const yh = h.b0 * ys + h.b1 * hx1 + h.b2 * hx2 - h.a1 * hy1 - h.a2 * hy2;
    hx2 = hx1;
    hx1 = ys;
    hy2 = hy1;
    hy1 = yh;
    acc += yh * yh;
    if (++filled === segment) {
      out[index++] = acc;
      acc = 0;
      filled = 0;
    }
  }
  if (filled > 0) out[index] = acc;
  return out;
}

export function measure(channels: Float32Array[], rate: number): Loudness {
  const length = channels[0]?.length ?? 0;
  const durationS = length / rate;
  const peak = toDb(truePeak(channels));
  if (length === 0) return { integrated: -Infinity, truePeak: peak, durationS, short: true };

  const filters = kWeighting(rate);
  const weights = channelWeights(channels.length);
  const segment = Math.max(1, Math.round(rate / 10));
  const energies = channels.map((x) => segmentEnergy(x, filters, segment));
  const blockCount = Math.floor(length / segment) - BLOCK_SEGMENTS + 1;

  if (blockCount < 1) {
    // Under 400 ms: one block over the whole file, no relative gate.
    let sum = 0;
    energies.forEach((e, c) => {
      let total = 0;
      for (const v of e) total += v;
      sum += weights[c] * (total / length);
    });
    const loudness = OFFSET + 10 * Math.log10(sum);
    return { integrated: loudness > ABSOLUTE_GATE ? loudness : -Infinity, truePeak: peak, durationS, short: true };
  }

  // Weighted mean square of each 400 ms block, summed over channels.
  const blocks = new Float64Array(blockCount);
  const samplesPerBlock = segment * BLOCK_SEGMENTS;
  energies.forEach((e, c) => {
    if (weights[c] === 0) return;
    let window = 0;
    for (let i = 0; i < BLOCK_SEGMENTS; i++) window += e[i];
    for (let j = 0; j < blockCount; j++) {
      if (j > 0) window += e[j + BLOCK_SEGMENTS - 1] - e[j - 1];
      blocks[j] += weights[c] * (window / samplesPerBlock);
    }
  });

  const meanAbove = (threshold: number) => {
    let sum = 0;
    let count = 0;
    for (const z of blocks) {
      if (OFFSET + 10 * Math.log10(z) > threshold) {
        sum += z;
        count++;
      }
    }
    return count ? sum / count : 0;
  };

  const absolute = meanAbove(ABSOLUTE_GATE);
  if (absolute === 0) return { integrated: -Infinity, truePeak: peak, durationS, short: false };
  const relative = OFFSET + 10 * Math.log10(absolute) + RELATIVE_GATE;
  const integrated = OFFSET + 10 * Math.log10(meanAbove(Math.max(ABSOLUTE_GATE, relative)));
  return { integrated, truePeak: peak, durationS, short: false };
}

/* ---------------------------------------------------------------- true peak --- */

const OVERSAMPLE = 4;
const TAPS_PER_PHASE = 16;

/**
 * Polyphase 4× interpolator: a Kaiser-windowed sinc split into one 16-tap filter per phase,
 * each phase normalised to unity gain at DC.
 */
function interpolator(): Float64Array[] {
  const n = OVERSAMPLE * TAPS_PER_PHASE;
  const center = (n - 1) / 2;
  const beta = 6;
  const proto = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const t = (i - center) / OVERSAMPLE;
    const sinc = t === 0 ? 1 : Math.sin(Math.PI * t) / (Math.PI * t);
    const r = (2 * i) / (n - 1) - 1;
    proto[i] = sinc * (besselI0(beta * Math.sqrt(1 - r * r)) / besselI0(beta));
  }
  const phases: Float64Array[] = [];
  for (let p = 0; p < OVERSAMPLE; p++) {
    const taps = new Float64Array(TAPS_PER_PHASE);
    let sum = 0;
    for (let k = 0; k < TAPS_PER_PHASE; k++) {
      taps[k] = proto[p + k * OVERSAMPLE];
      sum += taps[k];
    }
    for (let k = 0; k < TAPS_PER_PHASE; k++) taps[k] /= sum;
    phases.push(taps);
  }
  return phases;
}

function besselI0(x: number): number {
  let sum = 1;
  let term = 1;
  for (let k = 1; k < 50; k++) {
    term *= (x / (2 * k)) * (x / (2 * k));
    sum += term;
    if (term < 1e-12 * sum) break;
  }
  return sum;
}

let phasesCache: Float64Array[] | null = null;

/** Largest absolute value of the 4× oversampled signal, across all channels (linear). */
export function truePeak(channels: Float32Array[]): number {
  phasesCache ??= interpolator();
  const phases = phasesCache;
  let peak = 0;
  for (const x of channels) {
    // Zero padding on both sides, so the filter loop needs no bounds checks.
    const padded = new Float32Array(x.length + 2 * TAPS_PER_PHASE);
    padded.set(x, TAPS_PER_PHASE);
    for (let i = 0; i < x.length; i++) {
      const a = Math.abs(x[i]);
      if (a > peak) peak = a;
    }
    const end = x.length + TAPS_PER_PHASE;
    for (let p = 0; p < OVERSAMPLE; p++) {
      const taps = phases[p];
      for (let m = 0; m < end; m++) {
        const base = m + TAPS_PER_PHASE;
        let y = 0;
        for (let k = 0; k < TAPS_PER_PHASE; k++) y += taps[k] * padded[base - k];
        const a = y < 0 ? -y : y;
        if (a > peak) peak = a;
      }
    }
  }
  return peak;
}

export function toDb(linear: number): number {
  return linear > 0 ? 20 * Math.log10(linear) : -Infinity;
}
