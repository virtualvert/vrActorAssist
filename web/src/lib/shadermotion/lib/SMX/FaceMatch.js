// Matches an avatar's own blendshape names to the face-tracking channels, so the preview and the export
// drive the shapes the avatar really has: ARKit or Unified Expressions names in any case, with prefixes
// ("blendShape1.", "v2/"), "_L"/"_R" style sides and the common "browOutterUp" spelling.
// Kept out of FaceLayout.js, which mirrors FaceLayout.cs line for line.
import { Shapes, ARKit } from "./FaceLayout.js";
import { MatchVisemes } from "./Visemes.js";

const base = name => name.split(/[./]/).pop();
const key = name => base(name).toLowerCase().replace(/[^a-z0-9]/g, "").replace("outter", "outer");

const Table = new Map(); // normalized name -> face shape indices averaged
const Exact = new Set(); // the scheme names themselves, lowercased
for(const [name, shapes] of [...ARKit.map(([n, list]) => [n, list.map(s => Shapes.indexOf(s))]), ...Shapes.map((n, i) => [n, [i]])]) {
	const k = key(name);
	Exact.add(name.toLowerCase());
	for(const alias of [k, k.replace(/left$/, "l").replace(/right$/, "r")])
		if(!Table.has(alias)) Table.set(alias, shapes); // ARKit first; where both schemes share a name the sources agree
}

// names: blendshape names of one mesh -> [{name, index, shapes}] for the ones that follow face tracking.
// One name per source set: an avatar's own "Tongue Out" toggle loses to its ARKit "tongueOut" (driving both doubles it).
export function MatchShapes(names) {
	const found = names.flatMap((name, index) => {
		const shapes = Table.get(key(name));
		return shapes ? [{name, index, shapes, score: Exact.has(base(name).toLowerCase()) ? 2 : /\s/.test(name) ? 0 : 1}] : [];
	});
	const best = new Map();
	for(const {shapes, score} of found) best.set(shapes.join(), Math.max(best.get(shapes.join()) ?? 0, score));
	return found.filter(m => m.score === best.get(m.shapes.join())).map(({score, ...m}) => m);
}

// glTF/VRM JSON -> [{node, path, targets}] for the mesh nodes with face-tracking or viseme blendshapes (viseme
// targets use Visemes.js source indices). path is the node names from the scene root down, which is the object
// path under the avatar root once UniVRM imports it.
export function FaceMeshes(gltf) {
	const out = [];
	const visit = (i, prefix) => {
		const node = gltf.nodes[i], path = prefix + (node.name ?? `node${i}`);
		if(node.mesh !== undefined) {
			const mesh = gltf.meshes[node.mesh], names = mesh.extras?.targetNames ?? mesh.primitives[0]?.extras?.targetNames ?? [];
			const face = MatchShapes(names);
			const targets = [...face, ...MatchVisemes(names).filter(v => !face.some(f => f.index === v.index))];
			if(targets.length) out.push({node: i, path, targets});
		}
		for(const c of node.children ?? []) visit(c, `${path}/`);
	};
	for(const i of gltf.scenes?.[gltf.scene ?? 0]?.nodes ?? []) visit(i, "");
	return out;
}

// Face shapes (indices) with data that none of the matched targets use
export function UncoveredShapes(targets, present) {
	const used = new Set(targets.flatMap(t => t.shapes));
	return present.filter(u => !used.has(u));
}
