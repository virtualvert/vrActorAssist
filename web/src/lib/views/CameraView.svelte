<script lang="ts">
  import { Circle, Clapperboard, Maximize, Square, Undo2, Video } from "@lucide/svelte";
  import { onDestroy } from "svelte";
  import Button from "../components/Button.svelte";
  import ConnectBanner from "../components/ConnectBanner.svelte";
  import Toggle from "../components/Toggle.svelte";
  import { duration } from "../format";
  import NodeGraph from "../graph/NodeGraph.svelte";
  import type { AppState, WindowState } from "../protocol";
  import { app } from "../state.svelte";

  interface Props {
    data: AppState;
  }

  let { data }: Props = $props();

  let now = $state(Date.now());
  const clock = window.setInterval(() => (now = Date.now()), 250);
  onDestroy(() => window.clearInterval(clock));

  const cam = $derived(data.camera);
  const live = $derived(!!cam?.recording);
  const connected = $derived(data.connection.status === "connected");
  const canControl = $derived(data.demo && connected);

  const obs = $derived(cam?.obs);
  const win = $derived(cam?.window);
  const canMatch = $derived(!!win?.allowResize && win.state === "mismatch" && win.mode === "window" && !live);

  const WINDOW_CHIP: Record<WindowState, string> = {
    matched: "Matches",
    mismatch: "Wrong size",
    unknown: "Not compared",
    not_found: "Not found",
    unsupported: "Windows only",
  };

  const px = (size: [number, number] | null | undefined) => (size ? `${size[0]}×${size[1]}` : "—");

  function windowText(): string {
    if (!win || !obs) return "";
    switch (win.state) {
      case "matched":
        return `VRChat renders at ${px(win.size)}, the canvas size, so OBS captures it pixel for pixel.`;
      case "mismatch":
        return `VRChat is ${px(win.size)}; the canvas is ${px(obs.base)}.` + (win.mode !== "window" ? ` It's ${win.mode}: switch it to a normal window to match.` : "");
      case "unknown":
        return `VRChat is ${px(win.size)}. Connect OBS to compare it with the canvas.`;
      case "not_found":
        return "VRChat isn't running, or it has no window. Start it in desktop mode.";
      case "unsupported":
        return "Resizing the VRChat window works on Windows only so far.";
    }
  }

  const camera = (action: "match" | "restore") => app.call({ call: "camera", args: { action } });
</script>

<div class="wrap">
  <div class="view compact-view">
    <div class="banner-slot"><ConnectBanner /></div>

    <section class="tally card" class:live aria-live="polite">
      <span class="eyebrow">{data.profile.name || "Camera"}</span>
      <div class="lamp">
        {#if live}
          <span class="rec-dot"></span>
          <span class="big">REC</span>
          <span class="time mono">{duration(now - (cam?.recordingSince ?? now))}</span>
        {:else}
          <span class="big standby">STANDBY</span>
        {/if}
      </div>
      <div class="row controls">
        <Button variant="stop" size="l" disabled={!canControl || live} onclick={() => app.call({ call: "camera", args: { action: "roll" } })}>
          <Circle size="1em" fill="currentColor" /> Roll
        </Button>
        <Button variant="subtle" size="l" disabled={!canControl || !live} onclick={() => app.call({ call: "camera", args: { action: "cut" } })}>
          <Square size="0.95em" fill="currentColor" /> Cut
        </Button>
      </div>
    </section>

    <section class="stage card">
      <header><h2>On the network</h2></header>
      <div class="graph-slot"><NodeGraph {data} compact /></div>
    </section>

    <section class="card card-pad obs">
      <div class="tool-head">
        <span class="tool-icon role-camera"><Video size="1.3em" /></span>
        <div>
          <h3>OBS</h3>
          <span class="chip" class:ok={obs?.connected}>{obs?.connected ? "Connected" : "Not connected"}</span>
        </div>
      </div>
      <p class="faint">{obs?.detail}</p>
      {#if obs?.base}
        <p>Canvas <span class="mono">{px(obs.base)}</span> · recording <span class="mono">{px(obs.output)}</span> at {obs.fps} fps</p>
      {/if}

      {#if win}
        <div class="vrchat">
          <div class="vrchat-head">
            <h4>VRChat window</h4>
            <span class="chip" class:ok={win.state === "matched"} class:warn={win.state === "mismatch"}>{WINDOW_CHIP[win.state]}</span>
          </div>
          <p class="faint">{windowText()}</p>
          {#if win.state !== "unsupported"}
            <Toggle
              checked={win.allowResize}
              label="Let vrcActorSync resize the VRChat window"
              description="Only its size, when you press Match now or the director runs a ready check, never while OBS records. Closing the app puts it back."
              onchange={(allowWindowResize) => app.call({ call: "setCameraLocal", args: { allowWindowResize } })}
            />
            <div class="row">
              <Button disabled={!canMatch} onclick={() => camera("match")}><Maximize size="1em" /> Match now</Button>
              <Button variant="subtle" disabled={!win.canRestore || live} onclick={() => camera("restore")}><Undo2 size="1em" /> Restore</Button>
            </div>
          {/if}
        </div>
      {/if}

      {#if !data.demo}
        <p class="note">
          <Clapperboard size="1em" /> Roll-on-cue comes next (spec §8.5). The tally follows OBS; Roll / Cut
          here are only simulated in demo mode (<span class="mono">?demo=camera</span>).
        </p>
      {/if}
    </section>
  </div>
</div>

<style>
  .wrap {
    container-type: inline-size;
    height: 100%;
    overflow-y: auto;
  }

  .view {
    display: grid;
    grid-template-columns: minmax(0, 1.1fr) minmax(0, 1fr);
    grid-template-areas:
      "banner banner"
      "tally stage"
      "obs stage";
    grid-template-rows: auto minmax(18rem, 1fr) auto;
    gap: var(--gap);
    min-height: 100%;
    padding: var(--gap);
  }

  .tally {
    grid-area: tally;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 1.5rem;
    padding: 2rem;
    text-align: center;
    transition: background var(--t), border-color var(--t), box-shadow var(--t);
  }

  .tally.live {
    border-color: color-mix(in srgb, var(--live) 60%, transparent);
    background:
      radial-gradient(80% 100% at 50% 40%, color-mix(in srgb, var(--live) 26%, transparent), transparent 70%),
      var(--surface);
    box-shadow:
      0 0 0 1px var(--live),
      0 30px 80px -30px color-mix(in srgb, var(--live) 80%, transparent);
  }

  .lamp {
    display: flex;
    align-items: center;
    gap: 1rem;
  }

  .big {
    font-size: clamp(3rem, 11cqi, 6rem);
    font-weight: 900;
    letter-spacing: 0.04em;
    line-height: 1;
    color: var(--live);
  }

  .big.standby {
    color: var(--text-3);
    font-size: clamp(2.2rem, 8cqi, 4.5rem);
  }

  .rec-dot {
    width: clamp(1.5rem, 4cqi, 2.6rem);
    aspect-ratio: 1;
    border-radius: 50%;
    background: var(--live);
    box-shadow: 0 0 24px var(--live);
    animation: breathe 1s ease-in-out infinite;
  }

  .time {
    font-size: clamp(1.4rem, 4cqi, 2.2rem);
    font-weight: 700;
    color: var(--text);
  }

  .controls {
    justify-content: center;
    flex-wrap: wrap;
  }

  .stage {
    grid-area: stage;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .obs h3 {
    font-size: 1.1rem;
  }

  .obs {
    grid-area: obs;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .chip.ok {
    color: var(--ok);
  }

  .chip.warn {
    color: var(--warn);
  }

  .vrchat {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    padding-top: 0.75rem;
    border-top: 1px solid var(--border);
  }

  .vrchat-head {
    display: flex;
    align-items: center;
    gap: 0.6rem;
  }

  .vrchat h4 {
    font-size: 1rem;
  }

  .note {
    padding: 0.75rem 0.9rem;
    border-radius: var(--radius);
    background: var(--surface-2);
    border: 1px solid var(--border);
    font-size: 0.875rem;
    color: var(--text-2);
  }

  @container (max-width: 56rem) {
    .view {
      grid-template-columns: minmax(0, 1fr);
      grid-template-areas: "banner" "tally" "stage" "obs";
      grid-template-rows: auto auto 20rem auto;
    }
  }
</style>
