<script lang="ts">
  import { AudioLines, Radio, Zap } from "@lucide/svelte";
  import { onDestroy } from "svelte";
  import ConnectBanner from "../components/ConnectBanner.svelte";
  import Toggle from "../components/Toggle.svelte";
  import { ago, mediaTime } from "../format";
  import NodeGraph from "../graph/NodeGraph.svelte";
  import type { AppState } from "../protocol";
  import { app } from "../state.svelte";

  interface Props {
    data: AppState;
  }

  let { data }: Props = $props();

  let now = $state(Date.now());
  const clock = window.setInterval(() => (now = Date.now()), 1000);
  onDestroy(() => window.clearInterval(clock));

  const self = $derived(data.peers.find((p) => p.self));
  const actor = $derived(data.actor);
  const recentCue = $derived(actor?.lastCue && now - actor.lastCue.at < 3500 ? actor.lastCue : null);
  // Soundpad's real status when it answers on its pipe; null means only the cue flash is known
  const playback = $derived(actor?.soundpad.playback ?? null);
  const active = $derived(playback !== null && playback.status !== "STOPPED");
  const progress = $derived(playback && playback.durationMs > 0 ? Math.min(100, (playback.positionMs / playback.durationMs) * 100) : 0);

  const hero = $derived.by(() => {
    const c = data.connection;
    if (c.status === "error") return { tone: "bad", title: "Can't connect", sub: c.detail };
    if (c.status === "connecting") return { tone: "warn spin", title: "Connecting…", sub: c.detail };
    if (c.status === "pending")
      return { tone: "warn", title: "Waiting for the director", sub: "The director approves you once. After that you join automatically." };
    if (c.status !== "connected") return { tone: "idle", title: "Not connected", sub: "Connect to your relay to receive cues." };
    if (playback) {
      if (!active) return { tone: "ready", title: "Ready", sub: "Waiting for the next cue from the director." };
      const where = `${playback.title ?? "Your selected sound"} · ${mediaTime(playback.positionMs)} / ${mediaTime(playback.durationMs)}`;
      return playback.status === "PAUSED" ? { tone: "warn", title: "Paused", sub: where } : { tone: "go", title: "Playing", sub: where };
    }
    if (self?.activity === "playing" || recentCue) {
      const sp = actor?.soundpad;
      return {
        tone: "go",
        title: "GO!",
        sub: sp?.enabled ? (sp.state === "simulated" ? "Cue received — Soundpad simulated on this system" : "Playing your selected sound") : "Cue received — Soundpad is off",
      };
    }
    return { tone: "ready", title: "Ready", sub: "Waiting for the next cue from the director." };
  });

  const SP_LABEL = { ready: "Ready", fallback: "Command line", simulated: "Simulated", missing: "Not found", disabled: "Off" } as const;
  const STATUS_LABEL = { STOPPED: "Stopped", PLAYING: "Playing", PAUSED: "Paused", SEEKING: "Seeking" } as const;

  function edition(trial: boolean | null): string {
    if (trial === null) return "edition unknown";
    return trial ? "trial (can't add sounds)" : "full version";
  }
</script>

<div class="wrap">
  <div class="view">
    <div class="banner-slot"><ConnectBanner /></div>

    <section class="hero card {hero.tone}" aria-live="polite">
      <div class="orb" aria-hidden="true">
        <span class="core"></span>
        <span class="wave"></span>
        <span class="wave w2"></span>
      </div>
      <div class="copy">
        <span class="eyebrow">{data.profile.name || "Actor"}</span>
        <h1>{hero.title}</h1>
        <p class="muted">{hero.sub}</p>
        {#if actor?.lastCue}
          <span class="chip last" class:fail={!actor.lastCue.ok}>
            <Zap size="1em" /> Last cue: {actor.lastCue.command.replace("*", "").toUpperCase()} · {ago(actor.lastCue.at, now)}
          </span>
        {/if}
      </div>
    </section>

    <section class="stage card">
      <header><h2>On the network</h2></header>
      <div class="graph-slot"><NodeGraph {data} compact /></div>
    </section>

    {#if actor}
      <section class="card card-pad tool sp">
        <div class="tool-head">
          <span class="tool-icon role-actor"><AudioLines size="1.3em" /></span>
          <div>
            <h3>Soundpad</h3>
            <span class="chip sp-{actor.soundpad.state}">{SP_LABEL[actor.soundpad.state]}</span>
          </div>
        </div>
        {#if actor.soundpad.info}
          {@const info = actor.soundpad.info}
          <p class="small">Soundpad {info.version} · remote control {info.rcVersion} · {edition(info.trial)}</p>
        {/if}
        {#if playback && active}
          <div class="transport" aria-label="Soundpad playback">
            <div class="transport-row">
              <span class="chip status-{playback.status.toLowerCase()}">{STATUS_LABEL[playback.status]}</span>
              <span class="track">{playback.title ?? "Selected sound"}</span>
              <span class="mono small">{mediaTime(playback.positionMs)} / {mediaTime(playback.durationMs)}</span>
            </div>
            <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(progress)}>
              <span style:width="{progress}%"></span>
            </div>
          </div>
        {/if}
        <p class="faint small">{actor.soundpad.detail}</p>
        <Toggle
          checked={actor.soundpad.enabled}
          label="Play sounds on cue"
          onchange={(soundpadEnabled) => app.call({ call: "setActorLocal", args: { soundpadEnabled } })}
        />
      </section>

      <section class="card card-pad tool osc">
        <div class="tool-head">
          <span class="tool-icon role-camera"><Radio size="1.3em" /></span>
          <div>
            <h3>VRChat OSC</h3>
            <span class="chip mono">{actor.osc.host}:{actor.osc.port}</span>
          </div>
        </div>
        <p class="faint small">{actor.osc.ready ? "Avatar parameters from the director are sent to VRChat." : actor.osc.enabled ? "python-osc isn't installed, so OSC cues are skipped." : "OSC cues are ignored."}</p>
        <Toggle
          checked={actor.osc.enabled}
          label="Send avatar parameters"
          onchange={(oscEnabled) => app.call({ call: "setActorLocal", args: { oscEnabled } })}
        />
      </section>
    {/if}
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
    grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
    grid-template-areas:
      "banner banner"
      "hero stage"
      "sp osc";
    grid-template-rows: auto minmax(20rem, 1fr) auto;
    gap: var(--gap);
    min-height: 100%;
    padding: var(--gap);
  }

  .banner-slot {
    grid-area: banner;
  }

  .banner-slot:empty {
    display: none;
  }

  .hero {
    grid-area: hero;
    display: flex;
    align-items: center;
    gap: 2rem;
    padding: 2rem;
    overflow: hidden;
    --tone: var(--idle);
    background:
      radial-gradient(90% 120% at 0% 50%, color-mix(in srgb, var(--tone) 18%, transparent), transparent 65%),
      var(--surface);
    transition: background var(--t);
  }

  .hero.ready { --tone: var(--actor); }
  .hero.go { --tone: var(--go); }
  .hero.warn { --tone: var(--warn); }
  .hero.bad { --tone: var(--bad); }

  .orb {
    position: relative;
    flex: none;
    width: calc(var(--target) * 3);
    aspect-ratio: 1;
    display: grid;
    place-items: center;
  }

  .orb .core {
    width: 62%;
    aspect-ratio: 1;
    border-radius: 50%;
    background: radial-gradient(circle at 35% 30%, color-mix(in srgb, var(--tone) 45%, white), var(--tone) 55%, color-mix(in srgb, var(--tone) 55%, black));
    box-shadow:
      0 0 0 6px color-mix(in srgb, var(--tone) 18%, transparent),
      0 20px 60px -10px color-mix(in srgb, var(--tone) 70%, transparent);
    transition: transform var(--t) var(--ease-spring);
  }

  .orb .wave {
    position: absolute;
    inset: 19%;
    border-radius: 50%;
    border: 3px solid var(--tone);
    opacity: 0;
  }

  .ready .wave,
  .warn .wave {
    animation: pulse-ring 2.6s var(--ease-out) infinite;
  }

  .go .wave {
    animation: pulse-ring 0.9s var(--ease-out) infinite;
  }

  .go .core {
    transform: scale(1.08);
  }

  .orb .w2 {
    animation-delay: -1.3s !important;
  }

  .go .w2 {
    animation-delay: -0.45s !important;
  }

  .spin .core {
    background: conic-gradient(from 0deg, var(--tone), transparent 70%, var(--tone));
    animation: spin 1.1s linear infinite;
  }

  .copy {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    min-width: 0;
  }

  .copy h1 {
    font-size: clamp(2rem, 6cqi, 3.5rem);
    font-weight: 850;
    letter-spacing: -0.03em;
  }

  .go h1 {
    color: var(--go);
  }

  .last {
    align-self: flex-start;
    margin-top: 0.5rem;
    color: var(--text);
  }

  .last.fail {
    color: var(--bad);
  }

  .stage {
    grid-area: stage;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .stage header {
    padding: 1rem var(--pad) 0;
  }

  .stage h2,
  .tool h3 {
    font-size: 1.1rem;
  }

  .graph-slot {
    flex: 1;
    min-height: 16rem;
  }

  .tool {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .tool.sp {
    grid-area: sp;
  }

  .tool.osc {
    grid-area: osc;
  }

  .tool-head {
    display: flex;
    align-items: center;
    gap: 0.9rem;
  }

  .tool-head > div {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  .tool-icon {
    display: grid;
    place-items: center;
    width: var(--target);
    aspect-ratio: 1;
    border-radius: var(--radius);
    color: var(--role);
    background: color-mix(in srgb, var(--role) 14%, transparent);
  }

  .small {
    font-size: 0.875rem;
  }

  .sp-ready { color: var(--ok); }
  .sp-simulated,
  .sp-fallback { color: var(--warn); }
  .sp-missing { color: var(--bad); }

  .transport {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .transport-row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    min-width: 0;
  }

  .track {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 600;
  }

  .status-playing,
  .status-seeking { color: var(--go); }
  .status-paused { color: var(--warn); }

  .bar {
    height: 0.375rem;
    border-radius: 999px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    overflow: hidden;
  }

  .bar span {
    display: block;
    height: 100%;
    background: var(--go);
    transition: width 250ms linear;
  }

  @container (max-width: 56rem) {
    .view {
      grid-template-columns: minmax(0, 1fr);
      grid-template-areas: "banner" "hero" "stage" "sp" "osc";
      grid-template-rows: auto auto 20rem auto auto;
    }

    .hero {
      flex-direction: column;
      text-align: center;
      align-items: center;
    }

    .last {
      align-self: center;
    }
  }
</style>
