// GPU tile sampler: averages a grid of taps around the center of each color square (80x45, or 160x90 for the
// dense grid; center sampling avoids the blurred square edges) and batches many frames into one float readback.
export const GridW = 80, GridH = 45;

const VS = `#version 300 es
void main() {
	vec2 p = vec2(gl_VertexID & 1, gl_VertexID >> 1) * 4.0 - 1.0; // fullscreen triangle
	gl_Position = vec4(p, 0, 1);
}`;
const FS = (w, h) => `#version 300 es
precision highp float;
uniform sampler2D uSrc;
uniform vec4 uRegion;  // data region in source uv (x, y, w, h), y measured from the top
uniform float uSpan;   // fraction of a square covered by the taps
uniform int uRowBase;  // atlas row of this frame
out vec4 outColor;
const int N = 4;
void main() {
	ivec2 p = ivec2(gl_FragCoord.xy);
	vec2 cell = vec2(1.0/${w}.0, 1.0/${h}.0);
	vec2 center = (vec2(p.x, p.y - uRowBase) + 0.5) * cell;
	vec3 acc = vec3(0);
	for(int j=0; j<N; j++)
	for(int i=0; i<N; i++) {
		vec2 o = ((vec2(i, j) + 0.5) / float(N) - 0.5) * uSpan * cell;
		acc += textureLod(uSrc, uRegion.xy + (center + o) * uRegion.zw, 0.0).rgb;
	}
	outColor = vec4(acc / float(N*N), 1);
}`;

export class TileSampler {
	constructor({batch = 32, grid = [GridW, GridH]} = {}) {
		this.batch = batch;
		[this.w, this.h] = grid;
		this.canvas = typeof OffscreenCanvas !== "undefined" ? new OffscreenCanvas(1, 1) : document.createElement("canvas");
		const gl = this.gl = this.canvas.getContext("webgl2", {antialias: false, depth: false, premultipliedAlpha: false});
		if(!gl) throw new Error("WebGL2 is not available");
		this.float = !!gl.getExtension("EXT_color_buffer_float");

		const prog = this.prog = gl.createProgram();
		for(const [type, src] of [[gl.VERTEX_SHADER, VS], [gl.FRAGMENT_SHADER, FS(this.w, this.h)]]) {
			const sh = gl.createShader(type);
			gl.shaderSource(sh, src);
			gl.compileShader(sh);
			if(!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh));
			gl.attachShader(prog, sh);
		}
		gl.linkProgram(prog);
		if(!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
		this.loc = Object.fromEntries(["uSrc", "uRegion", "uSpan", "uRowBase"].map(n => [n, gl.getUniformLocation(prog, n)]));

		this.srcTex = gl.createTexture();
		gl.bindTexture(gl.TEXTURE_2D, this.srcTex);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
		gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

		this.atlas = gl.createTexture();
		gl.bindTexture(gl.TEXTURE_2D, this.atlas);
		gl.texStorage2D(gl.TEXTURE_2D, 1, this.float ? gl.RGBA32F : gl.RGBA8, this.w, this.h * batch);
		this.fb = gl.createFramebuffer();
		gl.bindFramebuffer(gl.FRAMEBUFFER, this.fb);
		gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, this.atlas, 0);
		this.pixels = this.float ? new Float32Array(this.w * this.h * batch * 4) : new Uint8Array(this.w * this.h * batch * 4);
		this.count = 0;
		this.region = [0, 0, 1, 1];
		this.span = 0.5;
		this.srcFormat = null;
	}
	upload(source) {
		const gl = this.gl;
		gl.bindTexture(gl.TEXTURE_2D, this.srcTex);
		gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
		// prefer a half-float upload so 10-bit video keeps its extra precision
		if(this.srcFormat !== "rgba8") {
			gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA16F, gl.RGBA, gl.HALF_FLOAT, source);
			if(gl.getError() === gl.NO_ERROR) return this.srcFormat = "rgba16f";
			this.srcFormat = "rgba8";
		}
		gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
	}
	// Sample one frame into the next atlas row; returns its index within the batch.
	add(source) {
		if(this.count >= this.batch) throw new Error("batch full; call read() first");
		const gl = this.gl;
		this.upload(source);
		gl.bindFramebuffer(gl.FRAMEBUFFER, this.fb);
		gl.viewport(0, this.count * this.h, this.w, this.h);
		gl.useProgram(this.prog);
		gl.uniform1i(this.loc.uSrc, 0);
		gl.uniform4fv(this.loc.uRegion, this.region);
		gl.uniform1f(this.loc.uSpan, this.span);
		gl.uniform1i(this.loc.uRowBase, this.count * this.h);
		gl.activeTexture(gl.TEXTURE0);
		gl.bindTexture(gl.TEXTURE_2D, this.srcTex);
		gl.drawArrays(gl.TRIANGLES, 0, 3);
		return this.count++;
	}
	// Read the batch: returns [count, getRGB(frame, sx, sy) -> [r,g,b] in 0..1 with sy=0 at the top]
	read() {
		const gl = this.gl, n = this.count;
		if(n) {
			gl.bindFramebuffer(gl.FRAMEBUFFER, this.fb);
			gl.readPixels(0, 0, this.w, this.h * n, gl.RGBA, this.float ? gl.FLOAT : gl.UNSIGNED_BYTE, this.pixels);
		}
		this.count = 0;
		const px = this.pixels, scale = this.float ? 1 : 1/255, {w, h} = this;
		return {count: n, pixels: px, scale, index: (k, sx, sy) => ((k * h + sy) * w + sx) * 4};
	}
}
