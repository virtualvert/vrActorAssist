// Color-tile codec for offline decoding, ported from Shader/Codec.hlsl.
// A slot is two horizontally adjacent squares; each square's RGB holds 3 base-3 Gray-code digits
// in GRB order, and the 6 digits together encode a real number in [-1, +1].
import { DecodeVideoFloat } from "../SM/ShaderImpl.js";

export const TileRadix = 3;
export const TileLen = 2;
export const TilePow = TileRadix ** (TileLen * 3); // 729
const Half = (TilePow - 1) / 2; // 364

function grayAdd(state, x, radix, cont=true) {
	if(state[0] & 1)
		x = radix-1-x;
	const r = Math.round(x);
	state[0] = state[0]*radix + r;
	if(!(cont && r === 0))
		state[1] = x-r;
	if(!(cont && r === radix-1))
		state[2] = x-r;
}
function graySum(state) {
	const px = Math.max(0, state[2]*2), py = Math.max(0, state[1]*-2);
	return (Math.min(px,py)/Math.max(Math.max(px,py)-px*py, 1e-5)*(px-py) + (px-py)) * 0.5 + state[0];
}
const _state = [0, 0, 0];
// c0, c1: gamma-space RGB in [0,1] for the first and second square of a slot
export function DecodeSnorm(r0, g0, b0, r1, g1, b1) {
	_state[0] = _state[1] = _state[2] = 0;
	grayAdd(_state, g0*2, TileRadix); grayAdd(_state, r0*2, TileRadix); grayAdd(_state, b0*2, TileRadix);
	grayAdd(_state, g1*2, TileRadix); grayAdd(_state, r1*2, TileRadix); grayAdd(_state, b1*2, TileRadix);
	_state[0] -= Half;
	return graySum(_state) / Half;
}
// How far a slot's colors are from a valid Gray-curve point, in digit units (0 = perfect).
// A valid slot has every digit on {0,1,2} except at most one that sits between two neighbors.
export function SlotError(r0, g0, b0, r1, g1, b1) {
	let sum = 0, max = 0;
	for(const v of [r0, g0, b0, r1, g1, b1]) {
		const e = Math.abs(v*2 - Math.round(v*2));
		sum += e;
		if(e > max) max = e;
	}
	return sum - max;
}

// Inverse of DecodeVideoFloat: split a value (in slot units) into the hi/lo slot pair used by hips position.
export function EncodeVideoFloat(value) {
	const T = value * Half + (TilePow*TilePow - 1)/2;
	const r = Math.floor((T + 0.5) / TilePow);
	const rem = T - r*TilePow;
	const lo = (r & 1) ? TilePow-1 - rem : rem;
	return [(r - Half) / Half, (lo - Half) / Half];
}
export { DecodeVideoFloat };

// Float <-> RGBA8 packing used by the WebGL motion texture (EncodeBufferSnorm / DecodeBufferSnorm).
export function PackBufferSnorm(value, out, offset) {
	let x = Math.min(Math.max((value + 1) * 64, 0), 256 - 2**-24);
	for(let i=0; i<4; i++) {
		const b = Math.floor(x);
		out[offset+i] = b;
		x = (x - b) * 256;
	}
}
export function UnpackBufferSnorm(bytes, offset) {
	return (((bytes[offset+3]/256 + bytes[offset+2])/256 + bytes[offset+1])/256 + bytes[offset])/64 - 1;
}
