// Types for the parts of the copied ShaderMotion player that the app uses (the .js is upstream's, plus `count`).
export class AvatarView {
  constructor(canvas: HTMLCanvasElement, count?: number);
  /** matrixVP: the last render's view-projection (gl-matrix mat4, mirrored in x: +x = screen left). */
  glob: { uniforms: { matrixVP: Float32Array } };
  camera: { yfov: number };
  /** translation[2]: minus the camera's distance (OrbitControls starts at 3 m; a double-click goes back there). */
  controls: { translation: number[]; rotationXY: number[] };
  setModel(url: string): Promise<void>;
  /** slots: the 135 humanoid slots (more are ignored), or null to hide. face: Visemes.SourceCount weights, or null. */
  setMotion(i: number, slots: ArrayLike<number> | null, x?: number, face?: ArrayLike<number> | null): void;
  render(): void;
}
