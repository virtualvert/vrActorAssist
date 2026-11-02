<script lang="ts">
  // Prototype: each online actor's avatar, moved by the ShaderMotion strip in their VRChat window (or, in demo
  // mode, a recorded clip). Frames arrive as "shadermotion" events only while this panel is open.
  import { vec4 } from "gl-matrix";
  import { untrack } from "svelte";
  import Drawer from "../components/Drawer.svelte";
  import Segmented from "../components/Segmented.svelte";
  import type { ShaderMotionFrame } from "../protocol";
  import { faceSources, stripStatus } from "../shadermotion/frame";
  import { axisDirections, projectSegment } from "../shadermotion/overlay";
  import { AvatarView } from "../shadermotion/lib/SMX/AvatarView.js";
  import { app } from "../state.svelte";
  import { message, recall, remember } from "./folderPanel";

  // shortcut: dev-only model folder, replace with the CC0 mannequin VRM before shipping
  const MODELS = { ybot: "/dev-models/ybot/mesh.gltf", vrm: "/dev-models/avatar.vrm" };
  type Model = keyof typeof MODELS;
  const STORE = "vrcas.shadermotion";
  /** Metres between avatars. */
  const SPACING = 1;
  /** The floor grid runs this many metres out from the middle, one line a metre. */
  const GRID = 5;

  let model = $state<Model>(recall<{ model?: string }>(STORE).model === "vrm" ? "vrm" : "ybot");
  let loading = $state("");
  let labels = $state<{ id: string; name: string; note: string; left: number; top: number }[]>([]);

  const actors = $derived(app.state?.peers.filter((p) => p.role === "actor" && !p.self && p.status === "online") ?? []);
  const ids = $derived(actors.map((p) => p.id).join(" "));

  $effect(() => {
    if (!app.shadermotionOpen) return;
    void app.call({ call: "shadermotion", args: { on: true } });
    return () => void app.call({ call: "shadermotion", args: { on: false } });
  });

  function note(f: ShaderMotionFrame | undefined): string {
    if (!f) return "Waiting for frames…";
    if (!f.slots) return f.problem ?? "No frames";
    const status = stripStatus(f.slots);
    return status === "dense" ? "Dense grid not supported" : status === "none" ? "No ShaderMotion strip" : "";
  }

  /** One WebGL view per actor list and model ({#key} below makes a new canvas when either changes). */
  function stage(el: HTMLElement) {
    return untrack(() => {
      const [floor, canvas] = el.querySelectorAll("canvas");
      const peers = actors.map((p) => p.id);
      const view = new AvatarView(canvas, Math.max(1, peers.length));
      const x = (i: number) => ((peers.length - 1) / 2 - i) * SPACING; // the view is mirrored: +x is screen left
      const frames = new Map<string, ShaderMotionFrame>();
      const fresh = new Set<string>();
      const off = app.onShaderMotion((f) => {
        frames.set(f.peerId, f);
        fresh.add(f.peerId);
      });
      const at = vec4.create();
      loading = "Loading the model…";
      view.setModel(MODELS[model]).then(
        () => (loading = ""),
        (err) => (loading = `Couldn't load the model (web/dev-models): ${message(err)}`),
      );
      const g = floor.getContext("2d")!;
      const css = getComputedStyle(el);
      const rootCss = getComputedStyle(document.documentElement);
      /** Floor grid, then the orientation gizmo in the bottom-left corner. */
      const overlay = () => {
        const dpr = devicePixelRatio;
        const w = Math.round(floor.clientWidth * dpr);
        const h = Math.round(floor.clientHeight * dpr);
        if (floor.width !== w || floor.height !== h) Object.assign(floor, { width: w, height: h });
        g.clearRect(0, 0, w, h);
        g.lineWidth = dpr;
        g.strokeStyle = css.getPropertyValue("--border-strong");
        g.beginPath();
        for (let i = -GRID; i <= GRID; i++)
          for (const [a, b] of [[[i, 0, -GRID], [i, 0, GRID]], [[-GRID, 0, i], [GRID, 0, i]]]) {
            const s = projectSegment(view.glob.uniforms.matrixVP, a, b, w, h);
            if (s) g.moveTo(s[0], s[1]), g.lineTo(s[2], s[3]);
          }
        g.stroke();
        const rem = parseFloat(rootCss.fontSize) * dpr;
        const [cx, cy, r] = [2.5 * rem, h - 2.5 * rem, 1.5 * rem];
        const colors = ["--bad", "--go", "--accent"].map((t) => css.getPropertyValue(t));
        g.lineWidth = 2 * dpr;
        g.font = `600 ${0.75 * rem}px ${css.fontFamily}`;
        g.textAlign = "center";
        g.textBaseline = "middle";
        // back to front, so the axis pointing at the viewer is drawn last
        const axes = axisDirections(view.controls.rotationXY).map((d, i) => ({ d, i }));
        for (const { d, i } of axes.sort((a, b) => a.d[2] - b.d[2])) {
          g.strokeStyle = g.fillStyle = colors[i];
          g.beginPath();
          g.moveTo(cx, cy);
          g.lineTo(cx + d[0] * r, cy + d[1] * r);
          g.stroke();
          g.fillText("XYZ"[i], cx + d[0] * (r + 0.6 * rem), cy + d[1] * (r + 0.6 * rem));
        }
      };
      let raf = 0;
      let fitted = false;
      const draw = () => {
        raf = requestAnimationFrame(draw);
        if (!fitted && canvas.clientWidth) {
          // back the camera off until every avatar fits across (the canvas has no size until the dialog opens)
          fitted = true;
          const halfWidth = (peers.length * SPACING) / 2 + 0.3;
          const aspect = canvas.clientWidth / Math.max(1, canvas.clientHeight);
          view.controls.translation[2] = -Math.max(3, halfWidth / (Math.tan(view.camera.yfov / 2) * aspect));
        }
        peers.forEach((id, i) => {
          if (!fresh.delete(id)) return;
          const v = frames.get(id)!.slots;
          const ok = !!v && stripStatus(v) === "ok";
          view.setMotion(i, ok ? v : null, x(i), ok ? faceSources(v!) : null);
        });
        view.render();
        overlay();
        labels = peers.map((id, i) => {
          vec4.transformMat4(at, [x(i), 0, 0, 1], view.glob.uniforms.matrixVP);
          const name = actors.find((p) => p.id === id)?.name ?? "";
          return { id, name, note: note(frames.get(id)), left: ((at[0] / at[3] + 1) / 2) * 100, top: ((1 - at[1] / at[3]) / 2) * 100 };
        });
      };
      raf = requestAnimationFrame(draw);
      return () => {
        cancelAnimationFrame(raf);
        off();
      };
    });
  }
</script>

<Drawer open={app.shadermotionOpen} title="ShaderMotion preview" wide onclose={() => (app.shadermotionOpen = false)}>
  <div class="bar">
    <Segmented
      label="Model"
      options={[
        { value: "ybot", label: "ybot" },
        { value: "vrm", label: "VRM" },
      ]}
      value={model}
      onchange={(v) => {
        model = v;
        remember(STORE, { model: v });
      }}
    />
    <span class="faint">Prototype · drag to orbit, scroll to zoom</span>
  </div>
  {#if app.shadermotionOpen}
    {#if actors.length}
      <div class="stage">
        {#key ids + model}<div class="layers" {@attach stage}><canvas></canvas><canvas></canvas></div>{/key}
        {#each labels as l (l.id)}
          <span class="label" style:left="{l.left}%" style:top="{l.top}%">
            {l.name}{#if l.note}<small>{l.note}</small>{/if}
          </span>
        {/each}
        {#if loading}<p class="loading">{loading}</p>{/if}
      </div>
    {:else}
      <p class="faint">No actors online.</p>
    {/if}
  {/if}
</Drawer>

<style>
  .bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 1rem;
    margin-bottom: 0.75rem;
  }

  .bar .faint {
    font-size: 0.8125rem;
  }

  .stage {
    position: relative;
    height: min(36rem, 65vh);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface-2);
    overflow: hidden;
  }

  .layers,
  canvas {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }

  /* the second canvas (avatars, transparent) takes the orbit drags */
  canvas {
    touch-action: none;
  }

  .label {
    position: absolute;
    transform: translate(-50%, 0.4rem);
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 0.15rem 0.5rem;
    border-radius: var(--radius-s);
    background: var(--surface-glass);
    font-size: 0.8125rem;
    font-weight: 600;
    white-space: nowrap;
    pointer-events: none;
  }

  .label small {
    color: var(--warn);
    font-weight: 500;
  }

  .loading {
    position: absolute;
    inset: auto 0 0.75rem;
    text-align: center;
    color: var(--text-2);
    font-size: 0.875rem;
  }
</style>
