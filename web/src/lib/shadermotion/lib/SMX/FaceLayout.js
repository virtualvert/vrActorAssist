// Face block layout, ported from Script/Common/FaceLayout.cs: Unified Expressions weights in [0, 1] in the
// three slot columns right of a humanoid block (layout slots 135..269), after a 3-slot header.
export const BlockStart = 135;
export const Header = [0.5, -0.5, 0.125];
export const Slot = shape => BlockStart + Header.length + shape;

export const Shapes = [
	"EyeLookOutRight", "EyeLookInRight", "EyeLookUpRight", "EyeLookDownRight",
	"EyeLookOutLeft", "EyeLookInLeft", "EyeLookUpLeft", "EyeLookDownLeft",
	"EyeClosedRight", "EyeClosedLeft", "EyeSquintRight", "EyeSquintLeft", "EyeWideRight", "EyeWideLeft",
	"EyeDilationRight", "EyeDilationLeft", "EyeConstrictRight", "EyeConstrictLeft",
	"BrowPinchRight", "BrowPinchLeft", "BrowLowererRight", "BrowLowererLeft",
	"BrowInnerUpRight", "BrowInnerUpLeft", "BrowOuterUpRight", "BrowOuterUpLeft",
	"NoseSneerRight", "NoseSneerLeft", "NasalDilationRight", "NasalDilationLeft", "NasalConstrictRight", "NasalConstrictLeft",
	"CheekSquintRight", "CheekSquintLeft", "CheekPuffRight", "CheekPuffLeft", "CheekSuckRight", "CheekSuckLeft",
	"JawOpen", "JawRight", "JawLeft", "JawForward", "JawBackward", "JawClench", "JawMandibleRaise",
	"MouthClosed",
	"LipSuckUpperRight", "LipSuckUpperLeft", "LipSuckLowerRight", "LipSuckLowerLeft", "LipSuckCornerRight", "LipSuckCornerLeft",
	"LipFunnelUpperRight", "LipFunnelUpperLeft", "LipFunnelLowerRight", "LipFunnelLowerLeft",
	"LipPuckerUpperRight", "LipPuckerUpperLeft", "LipPuckerLowerRight", "LipPuckerLowerLeft",
	"MouthUpperUpRight", "MouthUpperUpLeft", "MouthLowerDownRight", "MouthLowerDownLeft",
	"MouthUpperDeepenRight", "MouthUpperDeepenLeft",
	"MouthUpperRight", "MouthUpperLeft", "MouthLowerRight", "MouthLowerLeft",
	"MouthCornerPullRight", "MouthCornerPullLeft", "MouthCornerSlantRight", "MouthCornerSlantLeft",
	"MouthFrownRight", "MouthFrownLeft", "MouthStretchRight", "MouthStretchLeft",
	"MouthDimpleRight", "MouthDimpleLeft", "MouthRaiserUpper", "MouthRaiserLower",
	"MouthPressRight", "MouthPressLeft", "MouthTightenerRight", "MouthTightenerLeft",
	"TongueOut", "TongueUp", "TongueDown", "TongueRight", "TongueLeft", "TongueRoll",
	"TongueBendDown", "TongueCurlUp", "TongueSquish", "TongueFlat", "TongueTwistRight", "TongueTwistLeft",
	"SoftPalateClose", "ThroatSwallow", "NeckFlexRight", "NeckFlexLeft",
];

// ARKit shape -> Unified Expressions shapes it covers; playback averages them (ARKit -> UE -> ARKit is exact)
export const ARKit = [
	["eyeBlinkLeft", ["EyeClosedLeft"]], ["eyeBlinkRight", ["EyeClosedRight"]],
	["eyeLookDownLeft", ["EyeLookDownLeft"]], ["eyeLookDownRight", ["EyeLookDownRight"]],
	["eyeLookInLeft", ["EyeLookInLeft"]], ["eyeLookInRight", ["EyeLookInRight"]],
	["eyeLookOutLeft", ["EyeLookOutLeft"]], ["eyeLookOutRight", ["EyeLookOutRight"]],
	["eyeLookUpLeft", ["EyeLookUpLeft"]], ["eyeLookUpRight", ["EyeLookUpRight"]],
	["eyeSquintLeft", ["EyeSquintLeft"]], ["eyeSquintRight", ["EyeSquintRight"]],
	["eyeWideLeft", ["EyeWideLeft"]], ["eyeWideRight", ["EyeWideRight"]],
	["jawForward", ["JawForward"]], ["jawLeft", ["JawLeft"]], ["jawRight", ["JawRight"]], ["jawOpen", ["JawOpen"]],
	["mouthClose", ["MouthClosed"]],
	["mouthFunnel", ["LipFunnelUpperRight", "LipFunnelUpperLeft", "LipFunnelLowerRight", "LipFunnelLowerLeft"]],
	["mouthPucker", ["LipPuckerUpperRight", "LipPuckerUpperLeft", "LipPuckerLowerRight", "LipPuckerLowerLeft"]],
	["mouthLeft", ["MouthUpperLeft", "MouthLowerLeft"]], ["mouthRight", ["MouthUpperRight", "MouthLowerRight"]],
	["mouthSmileLeft", ["MouthCornerPullLeft", "MouthCornerSlantLeft"]], ["mouthSmileRight", ["MouthCornerPullRight", "MouthCornerSlantRight"]],
	["mouthFrownLeft", ["MouthFrownLeft"]], ["mouthFrownRight", ["MouthFrownRight"]],
	["mouthDimpleLeft", ["MouthDimpleLeft"]], ["mouthDimpleRight", ["MouthDimpleRight"]],
	["mouthStretchLeft", ["MouthStretchLeft"]], ["mouthStretchRight", ["MouthStretchRight"]],
	["mouthRollLower", ["LipSuckLowerRight", "LipSuckLowerLeft"]], ["mouthRollUpper", ["LipSuckUpperRight", "LipSuckUpperLeft"]],
	["mouthShrugLower", ["MouthRaiserLower"]], ["mouthShrugUpper", ["MouthRaiserUpper"]],
	["mouthPressLeft", ["MouthPressLeft"]], ["mouthPressRight", ["MouthPressRight"]],
	["mouthLowerDownLeft", ["MouthLowerDownLeft"]], ["mouthLowerDownRight", ["MouthLowerDownRight"]],
	["mouthUpperUpLeft", ["MouthUpperUpLeft"]], ["mouthUpperUpRight", ["MouthUpperUpRight"]],
	["browDownLeft", ["BrowLowererLeft", "BrowPinchLeft"]], ["browDownRight", ["BrowLowererRight", "BrowPinchRight"]],
	["browInnerUp", ["BrowInnerUpRight", "BrowInnerUpLeft"]],
	["browOuterUpLeft", ["BrowOuterUpLeft"]], ["browOuterUpRight", ["BrowOuterUpRight"]],
	["cheekPuff", ["CheekPuffRight", "CheekPuffLeft"]],
	["cheekSquintLeft", ["CheekSquintLeft"]], ["cheekSquintRight", ["CheekSquintRight"]],
	["noseSneerLeft", ["NoseSneerLeft"]], ["noseSneerRight", ["NoseSneerRight"]],
	["tongueOut", ["TongueOut"]],
];

export function IsHeader(h0, h1, h2) {
	return Math.abs(h0 - Header[0]) < 0.05 && Math.abs(h1 - Header[1]) < 0.05 && Math.abs(h2 - Header[2]) < 0.05;
}

// Output blendshapes for a naming scheme: [[name, [face shape indices averaged]]]
export function TargetShapes(scheme) {
	const ue = Shapes.map((name, i) => [name, [i]]);
	const arkit = ARKit.map(([name, list]) => [name, list.map(s => Shapes.indexOf(s))]);
	return scheme === "ue" ? ue : scheme === "arkit" ? arkit : scheme === "both" ? [...arkit, ...ue] : [];
}
