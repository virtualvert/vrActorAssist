<script lang="ts">
  import { Crosshair, FileCheck, Gauge, Pause, Play, RefreshCw, RotateCcw, RotateCw, Search, Square, Volume2, VolumeX, X } from "@lucide/svelte";
  import { onDestroy, untrack } from "svelte";
  import Button from "../components/Button.svelte";
  import DelayEditor from "../components/DelayEditor.svelte";
  import Drawer from "../components/Drawer.svelte";
  import Segmented from "../components/Segmented.svelte";
  import { mediaLength, mediaTime } from "../format";
  import type { Lines, SoundRef } from "../protocol";
  import { LINE_HELP, LINE_OPTIONS, positionNow, searchSounds, soundpadReach, STATUS_TEXT, steadyPosition, wontAddReceived, wontAddText } from "../soundpad";
  import { app } from "../state.svelte";
  import { armedText, armReason, DEFAULT_START_LATENCY_MS, isArmed } from "../timing";

  type LineChoice = Lines | "default";
  const SHOWN = 200;
  const JUMP_MS = 5000;
  const HOLD_MS = 1500;

  const data = $derived(app.state!);
  const peer = $derived(app.soundpadFor ? (data.peers.find((p) => p.id === app.soundpadFor) ?? null) : null);
  const sp = $derived(peer?.soundpad ?? null);
  const reach = $derived(peer ? soundpadReach(peer) : "none");
  const list = $derived(peer ? (app.sounds[peer.id] ?? null) : null);
  const playing = $derived(!!sp && sp.status !== null && sp.status !== "STOPPED");
  const armed = $derived(peer ? data.director?.armed[peer.id] : undefined);
  const wontAdd = $derived(wontAddReceived(sp));
  const canCalibrate = $derived(!!peer && reach === "full" && peer.caps.includes("soundpad.calibrate") && !data.connection.legacy);

  let query = $state("");
  let line = $state<LineChoice>("default");
  let playNumber = $state<number | null>(null);
  let volumeDraft = $state<number | null>(null);
  let seekDraft = $state<number | null>(null);
  // After a seek or a volume change the actor's next report can still carry the old value: the
  // requested value stays on screen for a moment, so the slider doesn't jump back and forth
  let seekHold = $state<{ ms: number; at: number } | null>(null);
  let volumeHold = $state<{ value: number; at: number } | null>(null);

  // A clock for the position between reports (positions arrive at most twice a second)
  let now = $state(Date.now());
  const tick = window.setInterval(() => {
    const t = Date.now();
    if (seekHold && t - seekHold.at >= HOLD_MS) seekHold = null;
    if (volumeHold && t - volumeHold.at >= HOLD_MS) volumeHold = null;
    if (app.soundpadFor && (sp?.status === "PLAYING" || seekHold || volumeHold)) now = t;
  }, 200);
  onDestroy(() => window.clearInterval(tick));

  let shown: number | null = null;
  let shownFor: string | null = null;
  const position = $derived.by(() => {
    if (seekDraft !== null) return seekDraft;
    if (!sp) return 0;
    const playing = sp.status === "PLAYING";
    if (seekHold) return Math.min(sp.durationMs, seekHold.ms + (playing ? Math.max(0, now - seekHold.at) : 0));
    const sound = `${peer?.id}/${sp.key ?? sp.index ?? sp.title}`;
    shown = steadyPosition(sound === shownFor ? shown : null, positionNow(sp, now), playing);
    shownFor = sound;
    return shown;
  });
  const volume = $derived(volumeDraft ?? (volumeHold && sp?.volume !== volumeHold.value ? volumeHold.value : sp?.volume) ?? null);
  const results = $derived(list ? searchSounds(list.sounds, query) : []);
  /** Files this director sent to the actor in this session that arrived: playable by their hash. */
  const sent = $derived.by(() => {
    if (!peer) return [];
    const seen = new Map<string, string>();
    for (const b of data.director?.files.batches ?? []) {
      if (b.actorId !== peer.id) continue;
      for (const r of b.results) if (r.state === "ok" && r.sha256) seen.set(r.sha256, r.name);
    }
    return [...seen].map(([sha256, name]) => ({ sha256, name }));
  });

  // Ask for the list each time the panel opens on an actor that has one
  let askedFor: string | null = null;
  $effect(() => {
    const id = app.soundpadFor;
    const ready = reach === "full" && !!sp?.available;
    untrack(() => {
      if (!id) {
        askedFor = null;
        query = "";
      } else if (ready && askedFor !== id) {
        askedFor = id;
        void app.call({ call: "requestSounds", args: { id } });
      }
    });
  });

  const ids = () => (peer ? [peer.id] : []);

  function play(sound: SoundRef, label: string) {
    void app.call({ call: "play", args: { ids: ids(), sound, lines: line === "default" ? undefined : line, label } });
  }

  function transport(action: "pause" | "resume" | "stop" | "mute" | "unmute" | "volume" | "seek" | "jump", value?: number) {
    void app.call({ call: "transport", args: { ids: ids(), action, value } });
  }

  function jump(delta: number) {
    if (!sp) return;
    transport("jump", delta);
    seekHold = { ms: Math.max(0, Math.min(sp.durationMs, position + delta)), at: Date.now() };
  }

  function playIndex(event: SubmitEvent) {
    event.preventDefault();
    if (playNumber && playNumber >= 1) void app.call({ call: "playIndex", args: { ids: ids(), index: Math.floor(playNumber) } });
  }

  /** The line kept with an armed sound: the panel's choice where the actor's app can take it. */
  const armLines = (): Lines | null => (reach === "full" && !data.connection.legacy && line !== "default" ? line : null);

  /** Arm this sound for GO (the line choice goes with it); pressing it again on the armed sound clears it. */
  function arm(sound: SoundRef, label: string) {
    if (!peer) return;
    const lines = armLines();
    if (isArmed(armed, sound) && (armed?.lines ?? null) === lines) {
      void app.call({ call: "disarm", args: { id: peer.id } });
      return;
    }
    const reason = armReason(peer, sound, lines, data.connection.legacy);
    if (reason) {
      app.toast("error", reason);
      return;
    }
    void app.call({ call: "arm", args: { id: peer.id, sound, label, lines } });
  }

  function armNumber() {
    if (playNumber && playNumber >= 1) arm({ index: Math.floor(playNumber) }, `Sound ${Math.floor(playNumber)}`);
  }

  function calibrate() {
    if (!peer) return;
    // The armed sound or the one playing, so the test play is a sound the actor really uses
    const sound: SoundRef | undefined =
      armed && !("selected" in armed.sound) && !("category" in armed.sound) ? armed.sound : sp?.key ? { key: sp.key } : undefined;
    void app.call({ call: "calibrate", args: { id: peer.id, sound } });
  }

  function length(ms: number | null): string {
    return ms === null ? "" : mediaLength(ms);
  }
</script>

<!-- Play and Arm for one sound; `hint` adds the long Arm tooltip (the sound list only) -->
{#snippet actions(sound: SoundRef, name: string, on: boolean, hint: boolean)}
  <Button size="s" variant="subtle" aria-label="Play {name}" onclick={() => play(sound, name)}>
    <Play size="0.9em" fill="currentColor" /> Play
  </Button>
  <Button
    size="s"
    class="arm"
    variant={on ? "go" : "ghost"}
    aria-pressed={on}
    aria-label="{on ? 'Clear the armed' : 'Arm'} {name} for GO"
    title={hint ? (on ? "Armed: GO plays this. Press to clear" : "Arm for GO: GO plays this on them instead of their selected sound") : undefined}
    onclick={() => arm(sound, name)}
  >
    <Crosshair size="0.9em" /> {on ? "Armed" : "Arm"}
  </Button>
{/snippet}

<Drawer open={!!app.soundpadFor} title={peer ? `${peer.name}'s Soundpad` : "Soundpad"} onclose={() => (app.soundpadFor = null)}>
  <div class="panel">
    {#if peer && armed}
      <div class="armed-banner" role="status">
        <Crosshair size="1.1em" aria-hidden="true" />
        <span class="armed-text"><strong>Armed for GO:</strong> {armedText(armed)}</span>
        <Button size="s" variant="ghost" onclick={() => app.call({ call: "disarm", args: { id: peer.id } })}><X size="1em" /> Clear</Button>
      </div>
    {/if}
    {#if !peer}
      <p class="faint">That actor isn't connected any more.</p>
    {:else if reach !== "full"}
      <p class="message note">
        {peer.name}
        {reach === "legacy" ? "uses the v0.3 app" : "uses an earlier vrcActorSync 0.4 preview"}: Go, Stop and a sound by number work; choosing a sound, the
        output line and the volume need the current app.
      </p>
    {:else if data.connection.legacy}
      <p class="message note">This relay is v0.3: only Go, Stop and a sound by number work.</p>
    {:else if !sp}
      <p class="faint">Waiting for {peer.name}'s Soundpad to report…</p>
    {:else if !sp.available}
      <p class="message bad">{sp.detail || "Soundpad isn't answering on this actor's PC."}</p>
    {:else}
      <section class="now" aria-label="Now playing">
        <div class="now-row">
          <span class="chip status-{(sp.status ?? 'STOPPED').toLowerCase()}">{STATUS_TEXT[sp.status ?? "STOPPED"]}</span>
          <span class="track">{playing ? (sp.title ?? "Their selected sound") : "Nothing playing"}</span>
          {#if playing}<span class="mono small">{mediaTime(position)} / {length(sp.durationMs)}</span>{/if}
        </div>
        {#if playing && sp.lines}<span class="faint small">{LINE_HELP[sp.lines]}</span>{/if}
        <input
          class="seek"
          type="range"
          min="0"
          max={Math.max(1, sp.durationMs)}
          step="100"
          value={position}
          disabled={!playing}
          aria-label="Position"
          oninput={(e) => (seekDraft = Number(e.currentTarget.value))}
          onchange={(e) => {
            const ms = Math.round(Number(e.currentTarget.value));
            transport("seek", ms);
            seekHold = { ms, at: Date.now() };
            seekDraft = null;
          }}
        />
        <div class="buttons">
          {#if sp.status === "PAUSED"}
            <Button variant="go" onclick={() => transport("resume")}><Play size="1em" fill="currentColor" /> Resume</Button>
          {:else}
            <Button variant="subtle" disabled={!playing} onclick={() => transport("pause")}><Pause size="1em" /> Pause</Button>
          {/if}
          <Button variant="stop" disabled={!playing} onclick={() => transport("stop")}><Square size="0.9em" fill="currentColor" /> Stop</Button>
          <Button icon variant="ghost" disabled={!playing} aria-label="Back 5 seconds" title="Back 5 s" onclick={() => jump(-JUMP_MS)}>
            <RotateCcw size="1.1em" />
          </Button>
          <Button icon variant="ghost" disabled={!playing} aria-label="Forward 5 seconds" title="Forward 5 s" onclick={() => jump(JUMP_MS)}>
            <RotateCw size="1.1em" />
          </Button>
        </div>
      </section>

      <section class="volume" aria-label="Volume">
        <div class="vol-row">
          <Button
            icon
            variant={sp.muted ? "warn" : "ghost"}
            aria-label={sp.muted ? "Unmute" : "Mute"}
            title={sp.muted ? "Muted: unmute" : "Mute"}
            onclick={() => transport(sp.muted ? "unmute" : "mute")}
          >
            {#if sp.muted}<VolumeX size="1.2em" />{:else}<Volume2 size="1.2em" />{/if}
          </Button>
          <input
            class="vol"
            type="range"
            min="0"
            max="100"
            step="1"
            value={volume ?? 0}
            aria-label="Volume"
            oninput={(e) => (volumeDraft = Number(e.currentTarget.value))}
            onchange={(e) => {
              const value = Number(e.currentTarget.value);
              transport("volume", value);
              volumeHold = { value, at: Date.now() };
              volumeDraft = null;
            }}
          />
          <span class="mono small vol-num">{volume ?? "–"}</span>
        </div>
        <span class="faint small">Soundpad has one volume for both lines, so this changes what the audience hears too.</span>
      </section>

      <section class="lines" aria-label="Output line for plays">
        <h3 class="eyebrow">Play on</h3>
        <Segmented label="Output line" options={[...LINE_OPTIONS]} value={line} onchange={(v) => (line = v)} />
        <span class="faint small">{LINE_HELP[line]}</span>
      </section>

      <section class="sounds" aria-label="Sounds">
        <div class="sounds-head">
          <h3 class="eyebrow">Sounds</h3>
          <Button size="s" variant="ghost" onclick={() => peer && app.call({ call: "requestSounds", args: { id: peer.id } })}>
            <RefreshCw size="0.95em" /> Refresh
          </Button>
        </div>
        <label class="search">
          <Search size="1em" aria-hidden="true" />
          <input class="input" bind:value={query} placeholder="Search titles, or #12" aria-label="Search sounds" />
        </label>
        {#if !list}
          <p class="faint small">Loading {peer.name}'s sound list…</p>
        {:else if !results.length}
          <p class="faint small">{list.sounds.length ? "No sound matches." : "Their Soundpad list is empty."}</p>
        {:else}
          <ul class="list">
            <!-- Not keyed by s.key: the same file can be in Soundpad twice (same path, same key),
                 and a duplicate key throws, which stopped the whole page updating -->
            {#each results.slice(0, SHOWN) as s}
              {@const on = isArmed(armed, { key: s.key })}
              <li class:current={playing && sp.key === s.key}>
                <span class="num mono">{s.index}</span>
                <span class="title">{s.title}</span>
                <span class="mono small faint">{length(s.durationMs)}</span>
                {@render actions({ key: s.key }, s.title, on, true)}
              </li>
            {/each}
          </ul>
          {#if results.length > SHOWN}<p class="faint small">Showing {SHOWN} of {results.length}; search to narrow it down.</p>{/if}
        {/if}
      </section>

      {#if sent.length}
        <section class="sent" aria-label="Files you sent">
          <h3 class="eyebrow">Sent this session</h3>
          <ul class="list">
            {#each sent as f (f.sha256)}
              {@const on = isArmed(armed, { sha256: f.sha256 })}
              <li>
                <FileCheck size="1em" aria-hidden="true" />
                <span class="title">{f.name}</span>
                {@render actions({ sha256: f.sha256 }, f.name, on, false)}
              </li>
            {/each}
          </ul>
          {#if wontAdd}
            <p class="message note">{wontAddText(peer.name, wontAdd)}</p>
          {:else}
            <span class="faint small">Their app adds a received file to Soundpad if it isn't there yet (full version).</span>
          {/if}
        </section>
      {/if}
    {/if}

    {#if peer}
      <form class="number" onsubmit={playIndex} aria-label="Play a sound by number">
        <label class="field">
          <span>Sound number</span>
          <input class="input mono" type="number" min="1" step="1" bind:value={playNumber} placeholder="e.g. 3" />
        </label>
        <Button type="submit" variant="subtle" disabled={!playNumber || playNumber < 1}>Play #{playNumber ?? "N"}</Button>
        <Button
          variant={playNumber && isArmed(armed, { index: Math.floor(playNumber) }) ? "go" : "ghost"}
          disabled={!playNumber || playNumber < 1}
          title="GO plays this number on them instead of their selected sound"
          onclick={armNumber}
        >
          <Crosshair size="0.95em" /> Arm #{playNumber ?? "N"}
        </Button>
        <span class="faint small">Their All-sounds number; works with every app version (a v0.3 app can only be armed this way).</span>
      </form>

      {#if peer.delayMs !== null || canCalibrate}
        <section class="timing" aria-label="Timing">
          <h3 class="eyebrow">Timing</h3>
          {#if peer.delayMs !== null}
            <DelayEditor id={peer.id} name={peer.name} delayMs={peer.delayMs} />
          {/if}
          {#if canCalibrate}
            <div class="calibrate">
              <Button variant="subtle" disabled={!sp?.available} onclick={calibrate}><Gauge size="1em" /> Calibrate</Button>
              <span class="faint small">
                {#if sp?.startLatencyMs !== null && sp?.startLatencyMs !== undefined}
                  Start latency {sp.startLatencyMs} ms (median of their last plays). Their cues are sent that much early, so the sound starts on time.
                {:else}
                  Plays a sound for 1.5 s on their speakers only and measures how long Soundpad takes to start it ({DEFAULT_START_LATENCY_MS} ms is assumed until then).
                {/if}
              </span>
            </div>
          {:else if reach === "full"}
            <span class="faint small">{peer.name}'s app is too old to calibrate.</span>
          {/if}
        </section>
      {/if}
    {/if}
  </div>
</Drawer>

<style>
  .panel {
    container-type: inline-size;
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  section {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .small {
    font-size: 0.8125rem;
  }

  .now-row,
  .vol-row,
  .sounds-head {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    min-width: 0;
  }

  .sounds-head {
    justify-content: space-between;
  }

  .track {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-weight: 650;
  }

  .status-playing,
  .status-seeking {
    color: var(--go);
  }

  .status-paused {
    color: var(--warn);
  }

  input[type="range"] {
    width: 100%;
    min-height: var(--target);
    accent-color: var(--accent);
  }

  .seek:disabled {
    opacity: 0.4;
  }

  .vol {
    flex: 1;
  }

  .vol-num {
    width: 2.5rem;
    text-align: right;
  }

  .buttons {
    display: flex;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .search {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    color: var(--text-3);
  }

  .search input {
    flex: 1;
  }

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    max-height: 22rem;
    overflow-y: auto;
  }

  .list li {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.35rem 0.6rem;
    border-bottom: 1px solid var(--border);
    min-height: var(--target);
  }

  .list li:last-child {
    border-bottom: 0;
  }

  .list li.current {
    background: color-mix(in srgb, var(--go) 12%, transparent);
  }

  .num {
    width: 2.5rem;
    color: var(--text-3);
    font-size: 0.8125rem;
  }

  .title {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
  }

  .number {
    display: flex;
    align-items: flex-end;
    gap: 0.6rem;
    flex-wrap: wrap;
    padding-top: 0.75rem;
    border-top: 1px solid var(--border);
  }

  .number .field {
    width: 9rem;
  }

  .list :global(.arm) {
    min-width: 6.4rem;
    justify-content: flex-start;
  }

  .armed-banner {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.55rem 0.6rem 0.55rem 0.85rem;
    border-radius: var(--radius-s);
    color: var(--go);
    background: color-mix(in srgb, var(--go) 10%, transparent);
    border: 1px solid color-mix(in srgb, var(--go) 35%, transparent);
  }

  .armed-text {
    flex: 1;
    min-width: 0;
    overflow-wrap: anywhere;
    color: var(--text);
  }

  .timing {
    padding-top: 0.75rem;
    border-top: 1px solid var(--border);
  }

  .calibrate {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .calibrate .small {
    flex: 1 1 14rem;
  }

  @container (max-width: 26rem) {
    .num {
      display: none;
    }
  }
</style>
