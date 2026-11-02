// ShaderMotion's lipsync blend space (MorphSettings.cs blendPresets, Morph.cs BlendSpace). The recorder writes
// sum(viseme weight x control point) into slots 80/81, consonants included (DD = 0.3 A + 0.7 I, ...); playback
// samples the five vowel shapes at their corners with bilinear tents. So only the vowels come back.
import { Shapes } from "./FaceLayout.js";

export const LipSyncSlot = 80; // x at 80, y at 81 (MotionLayout.defaultBlendLayout)
// [name, MorphSettings name alternatives, corner]
export const Vowels = [
	["v_aa", "a|aa|ah", [1, 0]],  // open vowel
	["v_ih", "i|ih", [0, 1]],     // close unrounded
	["v_ou", "u|ou", [0, -1]],    // close rounded
	["v_e", "e|eh", [1, 1]],      // mid unrounded
	["v_oh", "o|oh", [1, -1]],    // mid rounded
];
// Viseme sources follow the face shapes in FaceMatch's source indices, so one morph/curve path serves both
export const VisemeBase = Shapes.length;
export const SourceCount = VisemeBase + Vowels.length;

const tent = d => Math.min(Math.max(1 - Math.abs(d), 0), 1);
// Vowel weights in [0, 1] for a lipsync coordinate (BlendSpace.Sample)
export function VowelWeights(x, y, out = new Float32Array(Vowels.length)) {
	Vowels.forEach(([, , [cx, cy]], v) => out[v] = tent(x - cx) * tent(y - cy));
	return out;
}

// MorphSettings.visemePattern, tried in this order over all names (MorphSettings.AutoDetect)
const Patterns = ["[.]v_({0})$", "v_({0})$", "^({0})$", "[^0-9a-z]({0})$"];
// The avatar's blendshape for each vowel, found the way ShaderMotion's playback finds it: [{name, index, shapes}]
export function MatchVisemes(names) {
	return Vowels.flatMap(([, alts], v) => {
		for(const p of Patterns) {
			const re = new RegExp(p.replace("{0}", alts), "i");
			const index = names.findIndex(n => re.test(n));
			if(index >= 0) return [{name: names[index], index, shapes: [VisemeBase + v]}];
		}
		return [];
	});
}
// [[name, sources]] for exporting under a name prefix (VRChat's usual "vrc.v_aa", ...)
export function VisemeTargets(prefix = "vrc.") {
	return Vowels.map(([name], v) => [prefix + name, [VisemeBase + v]]);
}
