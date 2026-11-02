// 3D preview: renders `count` avatars with the ShaderMotion mesh-player shader, each driven by
// its own motion texture filled from a layer slot vector (raw decode or processed result).
// VRM blendshapes that match face-tracking channels are morphed on the CPU, per avatar slot.
import { mat4 } from "../gl-matrix.js";
import { GLContext } from "../wgl-fast.js";
import * as GLTF from "../GLTF/index.js";
import * as wGLTF from "../wGLTF/index.js";
import { TypedArray } from "../wGLTF/common.js";
import { CreateMeshPlayer } from "../SM/MeshPlayer.js";
import { createSMMContext } from "../../script2/smm.js";
import { OrbitControls } from "../../script2/OrbitControls.js";
import { resizeCanvas } from "../../script2/util.js";
import { PackBufferSnorm } from "./TileCodec.js";
import { LayerSlots } from "./MotionTracks.js";
import { FaceMeshes } from "./FaceMatch.js";

const TexW = 40, TexH = 45;
const NearestClamp = {wrapS: 33071, wrapT: 33071, magFilter: 9728, minFilter: 9728}; // CLAMP_TO_EDGE, NEAREST

export class AvatarView {
	constructor(canvas, count = 2) {
		const ctx = canvas.getContext("webgl2", {premultipliedAlpha: true, antialias: !/Mobi/.test(navigator.userAgent)});
		if(!ctx) throw new Error("WebGL2 is not available");
		const gl = this.gl = GLContext(ctx);
		this.glob = createSMMContext(gl);
		this.glob.uniforms.matrixVP = mat4.create();
		this.camera = {znear: 0.1, zfar: 100, yfov: 45/180*Math.PI, targetPos: [0, -1, 0]};
		this.controls = new OrbitControls(this.camera, canvas);
		this.models = new Map();
		this.draws = [];
		this.slots = Array.from({length: count}, () => ({
			tex: {sampler$: NearestClamp},
			bytes: new Uint8Array(TexW * TexH * 4),
			model: mat4.fromTranslation(mat4.create(), [0, 0, 0]),
			visible: false,
		}));
		this.modelURL = null;
		this.morphs = [];
		this.faceTargets = []; // [{path, name, shapes}]: the model's blendshapes that follow face tracking
	}
	async setModel(url) {
		this.modelURL = url;
		if(!this.models.has(url)) this.models.set(url, loadModel(this.gl, url, this.glob, this.slots.length));
		const model = await this.models.get(url);
		if(this.modelURL !== url) return;
		this.morphs = model.morphs;
		this.faceTargets = model.faceTargets;
		this.draws = this.slots.flatMap((slot, i) => model.draws.map(draw => ({
			__proto__: draw, slot: i,
			primitive: !draw.morph ? draw.primitive
				: {__proto__: draw.primitive, attributes$: {...draw.primitive.attributes$, POSITION: draw.morph.positions[i]}},
			uniforms: {__proto__: draw.uniforms, MODEL: slot.model, _Layer: 0, _MotionDec: {index$: slot.tex}},
		})));
	}
	// slots: layout-relative Float32Array(135) or null to hide; x: horizontal offset in meters
	// face: source weights (face-tracking shapes, then vowel visemes: Visemes.SourceCount), or null for a neutral face
	setMotion(i, slots, x = 0, face = null) {
		const slot = this.slots[i];
		slot.visible = !!slots;
		mat4.fromTranslation(slot.model, [x, 0, 0]);
		if(!slots) return;
		for(const morph of this.morphs) morph.apply(this.gl, i, face);
		const bytes = slot.bytes;
		bytes.fill(0);
		for(let p=0; p<TexW*TexH; p++) bytes[p*4] = 64; // packed 0 (all-zero bytes would read as -1)
		for(let s=0; s<LayerSlots; s++) {
			const col = Math.floor(s / TexH), row = s % TexH;
			PackBufferSnorm(Number.isFinite(slots[s]) ? slots[s] : 0, bytes, ((TexH - 1 - row) * TexW + col) * 4);
		}
		const gl = this.gl;
		gl.bindTexture(gl.TEXTURE_2D, wGLTF.loadTexture(gl, slot.tex));
		gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
		gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, TexW, TexH, 0, gl.RGBA, gl.UNSIGNED_BYTE, bytes);
	}
	render() {
		const gl = this.gl, {camera, controls, glob} = this;
		resizeCanvas(gl);
		const aspect = gl.canvas.clientWidth / Math.max(1, gl.canvas.clientHeight);
		const VP = glob.uniforms.matrixVP;
		mat4.perspective(VP, camera.yfov, aspect, camera.znear, camera.zfar);
		controls.multiplyMatrixV(VP);
		mat4.translate(VP, VP, camera.targetPos);
		mat4.scale(VP, VP, [-1, 1, 1]);
		gl.bindFramebuffer(gl.FRAMEBUFFER, null);
		gl.viewport(0, 0, gl.drawingBufferWidth, gl.drawingBufferHeight);
		gl.clearColor(0, 0, 0, 0), gl.clearDepth(1);
		gl.enable(gl.DEPTH_TEST);
		gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
		const draws = this.draws.filter(d => this.slots[d.slot].visible).sort((a, b) => a.renderOrder - b.renderOrder);
		for(const draw of draws)
			if(wGLTF.useProgram(gl, draw.technique.program$)) {
				gl.frontFace(draw.mirror ? gl.CW : gl.CCW);
				wGLTF.setStates(gl, draw.material);
				wGLTF.bindUniforms(gl, draw.uniforms, draw.technique);
				wGLTF.bindAttributes(gl, draw.primitive.attributes$, draw.technique);
				wGLTF.drawPrimitive(gl, draw.primitive);
			}
	}
}

// Positions of one morphable mesh (primitives sharing a POSITION accessor), one copy per avatar slot.
// Only vertices that some face target moves are reset and re-uploaded.
class FaceMorph {
	constructor(base, targets, slots) {
		this.base = base;
		this.targets = targets; // [{shapes, idx: Uint32Array, delta: Float32Array}]
		const touched = new Uint8Array(base.length / 3), list = [];
		for(const t of targets) for(const v of t.idx) touched[v] = 1;
		touched.forEach((on, v) => on && list.push(v));
		this.touched = Uint32Array.from(list);
		this.lo = list[0], this.hi = list[list.length - 1];
		this.next = new Float32Array(targets.length);
		this.positions = Array.from({length: slots}, () => {
			const data = base.slice();
			return {componentType: 5126/*FLOAT*/, type: "VEC3", count: base.length / 3, data, weights: new Float32Array(targets.length),
				bufferView$: {target: 34962/*ARRAY_BUFFER*/, usage: 35048/*DYNAMIC_DRAW*/, _data: Promise.resolve(data)}};
		});
	}
	apply(gl, slot, face) {
		const pos = this.positions[slot], {data, weights} = pos, {base, targets, next} = this;
		let changed = false;
		for(let k=0; k<targets.length; k++) {
			let sum = 0;
			if(face) for(const u of targets[k].shapes) sum += face[u];
			next[k] = Math.min(Math.max(sum / targets[k].shapes.length, 0), 1) || 0; // NaN (bad tile) -> 0
			changed ||= Math.abs(next[k] - weights[k]) > 1e-4;
		}
		if(!changed) return;
		weights.set(next);
		for(const v of this.touched) data[v*3] = base[v*3], data[v*3+1] = base[v*3+1], data[v*3+2] = base[v*3+2];
		for(let k=0; k<targets.length; k++) {
			const w = weights[k], {idx, delta} = targets[k];
			if(w) for(let j=0; j<idx.length; j++) {
				const o = idx[j] * 3;
				data[o] += w * delta[j*3], data[o+1] += w * delta[j*3+1], data[o+2] += w * delta[j*3+2];
			}
		}
		// before the first draw the buffer isn't uploaded yet; the upload then takes `data` as it is
		if(wGLTF.bindBuffer(gl, pos.bufferView$, gl.ARRAY_BUFFER))
			gl.bufferSubData(gl.ARRAY_BUFFER, this.lo * 12, data, this.lo * 3, (this.hi - this.lo + 1) * 3);
	}
}
async function readVec3(gltf, acc) {
	const v = new Float32Array(acc.count * 3);
	if(acc.bufferView$) v.set(await wGLTF.viewAccessor(acc));
	if(acc.sparse) {
		const {count, indices, values} = acc.sparse;
		const iv = await gltf.bufferViews[indices.bufferView]._data, vv = await gltf.bufferViews[values.bufferView]._data;
		const idx = new TypedArray[indices.componentType](iv.buffer, iv.byteOffset + (indices.byteOffset || 0), count);
		const val = new Float32Array(vv.buffer, vv.byteOffset + (values.byteOffset || 0), count * 3);
		for(let k=0; k<count; k++) v.set(val.subarray(k*3, k*3 + 3), idx[k] * 3);
	}
	return v;
}
// Morphs for the player primitives whose source mesh has face-tracking (ARKit / UE) or viseme blendshapes
async function loadFaceMorphs(gltf, prims, slots) {
	const owner = new Map(); // source primitive -> {path, targets}
	for(const face of FaceMeshes(gltf)) for(const p of gltf.meshes[gltf.nodes[face.node].mesh].primitives) owner.set(p, face);
	const byPosition = new Map(), faceTargets = [], seen = new Set();
	for(const prim of prims) {
		const src = Object.getPrototypeOf(prim), face = owner.get(src), pos = prim.attributes$.POSITION;
		if(!face || byPosition.has(pos) || (pos.bufferView$.byteStride || 12) !== 12) continue;
		const matches = face.targets.filter(m => gltf.accessors[src.targets?.[m.index]?.POSITION]?.componentType === 5126);
		if(!matches.length) continue;
		if(!seen.has(face)) seen.add(face), faceTargets.push(...matches.map(({name, shapes}) => ({path: face.path, name, shapes})));
		byPosition.set(pos, (async () => {
			const base = await wGLTF.viewAccessor(pos);
			const targets = await Promise.all(matches.map(async ({shapes, index}) => {
				const d = await readVec3(gltf, gltf.accessors[src.targets[index].POSITION]), idx = [], delta = [];
				for(let v=0; v<d.length/3; v++)
					if(d[v*3] || d[v*3+1] || d[v*3+2]) idx.push(v), delta.push(d[v*3], d[v*3+1], d[v*3+2]);
				return {shapes, idx: Uint32Array.from(idx), delta: Float32Array.from(delta)};
			}));
			return targets.some(t => t.idx.length) ? new FaceMorph(base, targets.filter(t => t.idx.length), slots) : null;
		})());
	}
	const morphOf = new Map(await Promise.all([...byPosition].map(async ([pos, m]) => [pos, await m])));
	return {morphOf, faceTargets};
}

// same as player-gltf.js loadModel, minus the shared motion texture, plus face morphs
async function loadModel(gl, modelURL, glob, slots) {
	const url = new URL(modelURL, location.href);
	const gltf = GLTF.loadGLTF(...await GLTF.fetchGLTF(url), url);
	const vrm = (gltf.extensions || {}).VRM;
	const mesh = vrm ? CreateMeshPlayer(gltf) : gltf.meshes[0];
	const {morphOf, faceTargets} = vrm ? await loadFaceMorphs(gltf, mesh.primitives, slots) : {morphOf: new Map(), faceTargets: []};
	const renderOrderMap = {OPAQUE: 2000, MASK: 2450, BLEND: 3000};
	const draws = mesh.primitives.map(prim => {
		const {
			alphaMode = "OPAQUE", alphaCutoff = 0.5,
			pbrMetallicRoughness: {baseColorTexture: mainTexInfo, baseColorFactor: mainColor = [1, 1, 1, 1]},
			extras: {boneTexture: boneTexInfo, shapeTexture: shapeTexInfo},
		} = prim.material$;
		const {
			renderQueue: renderOrder = renderOrderMap[alphaMode],
			floatProperties: {_ZWrite: depthWrite} = {},
		} = (vrm && vrm.materialProperties[prim.material]) || {};
		const tech = glob.techniques[alphaMode === "MASK" || depthWrite ? "MeshPlayerAlphaTest" : "MeshPlayer"];
		return {
			renderOrder, mirror: !vrm, primitive: prim, technique: tech, morph: morphOf.get(prim.attributes$.POSITION),
			material: {__proto__: prim.material$, depthWrite},
			uniforms: {
				VIEWPROJECTION: glob.uniforms.matrixVP, ALPHACUTOFF: alphaCutoff,
				_Color: mainColor, _MainTex: mainTexInfo, _Bone: boneTexInfo, _Shape: shapeTexInfo,
			},
		};
	});
	return {draws, morphs: [...new Set(morphOf.values())].filter(Boolean), faceTargets};
}
