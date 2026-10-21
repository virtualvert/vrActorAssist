<script lang="ts">
  import { AudioLines, Check, FileDown, FolderOpen, Radio, Volume2, VolumeX, X, Zap } from "@lucide/svelte";
  import { onDestroy } from "svelte";
  import Button from "../components/Button.svelte";
  import ConnectBanner from "../components/ConnectBanner.svelte";
  import Toggle from "../components/Toggle.svelte";
  import { ago, fileSize, mediaLength, mediaTime, percent } from "../format";
  import NodeGraph from "../graph/NodeGraph.svelte";
  import type { AppState } from "../protocol";
  import { OWN_LINE_HELP, OWN_LINE_OPTIONS } from "../soundpad";
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
    if (recentCue && !recentCue.ok) {
      return { tone: "bad", title: "Cue failed", sub: actor?.soundpad.detail || "The last cue didn't run on this computer." };
    }
    if (playback) {
      if (!active) return { tone: "ready", title: "Ready", sub: "Waiting for the next cue from the director." };
      const where = `${playback.title ?? "Your selected sound"} · ${mediaTime(playback.positionMs)} / ${mediaLength(playback.durationMs)}`;
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

  const files = $derived(actor?.files ?? null);
  const asking = $derived(files?.incoming.filter((f) => f.state === "asking") ?? []);
  const receiving = $derived(files?.incoming.filter((f) => f.state === "receiving") ?? []);

  // A new prompt scrolls into view: the card sits at the top and the page may be scrolled down
  let offersEl = $state<HTMLElement | undefined>();
  let promptCount = 0;
  $effect(() => {
    const count = asking.length;
    if (count > promptCount && offersEl) {
      const still = document.documentElement.dataset.motion === "reduce";
      offersEl.scrollIntoView({ block: "nearest", behavior: still ? "auto" : "smooth" });
    }
    promptCount = count;
  });

  /** Files left in the batch, this one included. */
  const left = (f: { index: number | null; count: number | null }) => (f.index && f.count ? f.count - f.index + 1 : 1);

  function answer(transferId: string, accept: boolean, extra: { rest?: boolean; always?: boolean } = {}) {
    void app.call({ call: "answerFile", args: { transferId, accept, ...extra } });
  }

  const SP_LABEL = { ready: "Ready", closed: "Not running", fallback: "Command line", simulated: "Simulated", missing: "Not found", disabled: "Off" } as const;
  const STATUS_LABEL = { STOPPED: "Stopped", PLAYING: "Playing", PAUSED: "Paused", SEEKING: "Seeking" } as const;
  const LINE_LABEL = Object.fromEntries(OWN_LINE_OPTIONS.map((o) => [o.value, o.label]));

  function edition(trial: boolean | null): string {
    if (trial === null) return "edition unknown";
    return trial ? "trial (can't add sounds)" : "full version";
  }
</script>

<div class="wrap">
  <div class="view">
    <div class="banner-slot"><ConnectBanner /></div>

    {#if asking.length}
      <section class="offers card card-pad" aria-label="Files waiting for your answer" aria-live="polite" bind:this={offersEl}>
        {#each asking as f (f.transferId)}
          <div class="offer">
            <span class="tool-icon role-director"><FileDown size="1.3em" /></span>
            <div class="offer-text">
              <strong>{f.from} wants to send {f.name}</strong>
              <span class="small muted">
                {fileSize(f.size)}{f.character ? ` · for ${f.character}` : ""}{f.count ? ` · file ${f.index} of ${f.count}` : ""}
              </span>
              {#if f.replaces}<span class="small warn-text">A file with this name is already in your folder; accepting replaces it.</span>{/if}
            </div>
            <div class="offer-actions">
              <Button variant="primary" onclick={() => answer(f.transferId, true)}><Check size="1.1em" /> Accept</Button>
              {#if left(f) > 1}
                <Button variant="subtle" onclick={() => answer(f.transferId, true, { rest: true })}>Accept all {left(f)}</Button>
              {/if}
              <Button variant="ghost" onclick={() => answer(f.transferId, false)}><X size="1.1em" /> Decline</Button>
            </div>
          </div>
        {/each}
        <button type="button" class="link small" onclick={() => answer(asking[0].transferId, true, { always: true })}>
          Accept these and future files automatically
        </button>
      </section>
    {/if}

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
              <span class="mono small">{mediaTime(playback.positionMs)} / {mediaLength(playback.durationMs)}</span>
            </div>
            <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={Math.round(progress)}>
              <span style:width="{progress}%"></span>
            </div>
            {#if playback.lines}
              <span class="small muted">On {LINE_LABEL[playback.lines].toLowerCase()} · {OWN_LINE_HELP[playback.lines]}</span>
            {/if}
          </div>
        {/if}
        {#if actor.soundpad.enabled}
          {@const sp = actor.soundpad}
          <div class="levels small" aria-label="Soundpad levels">
            {#if sp.volume !== null}
              <span class="level" class:warn-text={sp.muted}>
                {#if sp.muted}<VolumeX size="1.05em" aria-hidden="true" /> Muted · volume {sp.volume}{:else}<Volume2 size="1.05em" aria-hidden="true" /> Volume {sp.volume}{/if}
              </span>
            {/if}
            <span class="level muted" title={OWN_LINE_HELP[sp.defaultLines]}>Default line: {LINE_LABEL[sp.defaultLines]}</span>
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

      {#if files}
        <section class="card card-pad tool files">
          <div class="tool-head">
            <span class="tool-icon role-director"><FileDown size="1.3em" /></span>
            <div>
              <h3>Files from the director</h3>
              <span class="chip">{files.autoAccept ? "Accepted automatically" : "You're asked first"}</span>
            </div>
          </div>
          <div class="folder-row">
            <span class="mono small path" title={files.receiveDir}>{files.receiveDir}</span>
            {#if app.kind === "agent"}
              <Button size="s" variant="subtle" onclick={() => app.call({ call: "pickReceiveDir" })}><FolderOpen size="1em" /> Change…</Button>
            {/if}
          </div>
          {#each receiving as f (f.transferId)}
            <div class="transport" aria-label="Receiving {f.name}">
              <div class="transport-row">
                <span class="track">{f.name}</span>
                <span class="mono small">{percent(f.receivedBytes, f.size)} %</span>
              </div>
              <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={percent(f.receivedBytes, f.size)}>
                <span style:width="{percent(f.receivedBytes, f.size)}%"></span>
              </div>
            </div>
          {/each}
          {#if files.recent.length}
            <ul class="recent">
              {#each files.recent.slice(0, 5) as r, i (i)}
                <li class:fail={!r.ok}>
                  <span class="track">{r.name}</span>
                  <span class="small faint">{r.ok ? "Saved" : "Not saved"}{r.detail ? ` · ${r.detail}` : ""} · {ago(r.at, now)}</span>
                </li>
              {/each}
            </ul>
          {:else if !receiving.length}
            <p class="faint small">Files the director sends land in this folder.</p>
          {/if}
          <Toggle
            checked={files.autoAccept}
            label="Accept files automatically"
            description="Without asking, and replacing files that have the same name"
            onchange={(autoAcceptFiles) => app.call({ call: "setActorLocal", args: { autoAcceptFiles } })}
          />
        </section>
      {/if}
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
      "offers offers"
      "hero stage"
      "sp osc"
      "files files";
    grid-template-rows: auto auto minmax(20rem, 1fr) auto auto;
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

  .tool.files {
    grid-area: files;
  }

  .offers {
    grid-area: offers;
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
    border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
    background: color-mix(in srgb, var(--accent) 8%, var(--surface));
  }

  .offer {
    display: flex;
    align-items: center;
    gap: 0.9rem;
    flex-wrap: wrap;
  }

  .offer-text {
    flex: 1 1 16rem;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    overflow-wrap: anywhere;
  }

  .offer-actions {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .warn-text {
    color: var(--warn);
  }

  .link {
    align-self: flex-start;
    padding: 0;
    border: 0;
    background: none;
    color: var(--accent);
    text-decoration: underline;
    cursor: pointer;
    min-height: var(--target);
  }

  .folder-row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    min-width: 0;
  }

  .folder-row .path {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .recent {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .recent li {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    min-width: 0;
  }

  .recent li.fail .track {
    color: var(--warn);
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
  .sp-closed,
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

  .levels {
    display: flex;
    align-items: center;
    gap: 0.4rem 1.1rem;
    flex-wrap: wrap;
  }

  .level {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    font-weight: 600;
  }

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
      grid-template-areas: "banner" "offers" "hero" "stage" "sp" "osc" "files";
      grid-template-rows: auto auto auto 20rem auto auto auto;
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
