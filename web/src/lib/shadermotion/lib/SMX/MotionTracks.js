// Per-layer storage of decoded slot values for every video frame, filled from TileSampler batches.
import { DecodeSnorm, SlotError } from "./TileCodec.js";
import { GridW, GridH } from "./TileSampler.js";
import { IsHeader } from "./FaceLayout.js";

export const LayerCols = 3;            // a humanoid layer spans 3 slot columns
export const LayerSlots = LayerCols * GridH; // 135
export const TrackCols = 2 * LayerCols; // stored per layer: the humanoid block and the face block to its right
export const TrackSlots = TrackCols * GridH;
export const MaxLayers = 12;

// The standard 80x45 grid, and the dense 160x90 one (recorder keyword _SHADERMOTION_DENSE): half-size squares, a layer is
// still 3 slot columns but 90 rows, with the face block below the humanoid block instead of in the next stripe.
export const Grids = {normal: {w: GridW, h: GridH, dense: false}, dense: {w: 2 * GridW, h: 2 * GridH, dense: true}};
// the dense recorder writes this into reserved slots 133-134; the normal grid leaves them at 0
export const DenseMarker = {slot: 133, values: [0.5, -0.5]};
export function IsDenseMarker(v0, v1) {
	return Math.abs(v0 - DenseMarker.values[0]) < 0.05 && Math.abs(v1 - DenseMarker.values[1]) < 0.05;
}

// [first square column, second square column, first row] holding layout column `col` of `layer`.
// Odd layers are mirrored to the right edge; tiles on the right half are written mirrored.
export function SlotSquares(layer, col, grid = Grids.normal) {
	const cols = grid.w / 2;
	let x = (grid.dense ? col % LayerCols : col) + (layer >> 1) * LayerCols;
	if(layer & 1) x = cols - 1 - x;
	const row = grid.dense && col >= LayerCols ? GridH : 0;
	return x >= cols / 2 ? [2*x + 1, 2*x, row] : [2*x, 2*x + 1, row];
}

export class LayerTrack {
	constructor(layer, frameCount, grid = Grids.normal) {
		this.layer = layer;
		this.grid = grid;
		this.frameCount = frameCount;
		this.values = new Float32Array(frameCount * TrackSlots).fill(NaN);
		this.errors = new Float32Array(frameCount * TrackSlots).fill(NaN); // Gray-curve distance per slot
		this.decoded = new Uint8Array(frameCount);
		this.squares = Array.from({length: TrackCols}, (_, c) => SlotSquares(layer, c, grid));
	}
	// Decode one sampled frame (k-th in batch) into frame `index`.
	store(batch, k, index) {
		const {pixels: px, scale} = batch, base = index * TrackSlots;
		for(let c=0; c<this.squares.length; c++) {
			const [s0, s1, top] = this.squares[c];
			if(s0 < 0 || s1 >= this.grid.w) continue; // face block of the last layer pair falls off the grid
			for(let row=0; row<GridH; row++) {
				const i0 = batch.index(k, s0, top + row), i1 = batch.index(k, s1, top + row);
				const r0 = px[i0]*scale, g0 = px[i0+1]*scale, b0 = px[i0+2]*scale;
				const r1 = px[i1]*scale, g1 = px[i1+1]*scale, b1 = px[i1+2]*scale;
				this.values[base + c*GridH + row] = DecodeSnorm(r0, g0, b0, r1, g1, b1);
				this.errors[base + c*GridH + row] = SlotError(r0, g0, b0, r1, g1, b1);
			}
		}
		this.decoded[index] = 1;
	}
	frame(index) { return this.values.subarray(index * TrackSlots, (index + 1) * TrackSlots); }
	frameErrors(index) { return this.errors.subarray(index * TrackSlots, (index + 1) * TrackSlots); }
}

// Score every possible layer in one frame sampled on `grid`: hips axes must be near-orthogonal unit-ish vectors,
// the tiles must decode cleanly and the dense marker must match the grid.
export function DetectLayers(batch, k, grid = Grids.normal) {
	const scores = [];
	const tmp = new LayerTrack(0, 1, grid);
	for(let layer=0; layer<MaxLayers; layer++) {
		tmp.layer = layer;
		tmp.squares = Array.from({length: TrackCols}, (_, c) => SlotSquares(layer, c, grid));
		tmp.store(batch, k, 0);
		const v = tmp.values;
		const y = [v[6], v[7], v[8]], z = [v[9], v[10], v[11]];
		const ny = Math.hypot(...y), nz = Math.hypot(...z);
		const cos = Math.abs(y[0]*z[0] + y[1]*z[1] + y[2]*z[2]) / (ny * nz || 1);
		let err = 0;
		for(let s=0; s<LayerSlots; s++) err += tmp.errors[s];
		// real recorder tiles sit on the Gray curve (mean error ~0.02); scene content scores ~0.3-1.0
		const meanError = err / LayerSlots;
		// layer L's face block fills layer L+2's stripe, and its weights can pass the hips test
		const face = IsHeader(v[0], v[1], v[2]);
		const marked = IsDenseMarker(v[DenseMarker.slot], v[DenseMarker.slot + 1]);
		scores.push({layer, ok: ny > 0.3 && nz > 0.3 && cos < 0.1 && meanError < 0.15 && !face && marked === grid.dense, meanError, face});
	}
	return scores;
}
