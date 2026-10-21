<script lang="ts">
  import { FileCheck, Pause, Play, RefreshCw, RotateCcw, RotateCw, Search, Square, Volume2, VolumeX } from "@lucide/svelte";
  import { onDestroy, untrack } from "svelte";
  import Button from "../components/Button.svelte";
  import Drawer from "../components/Drawer.svelte";
  import Segmented from "../components/Segmented.svelte";
  import { mediaTime } from "../format";
  import type { Lines, SoundRef } from "../protocol";
  import { LINE_HELP, LINE_OPTIONS, positionNow, searchSounds, soundpadReach } from "../soundpad";
  import { app } from "../state.svelte";

  type LineChoice = Lines | "default";
  const SHOWN = 200;
  const JUMP_MS = 5000;
  const STATUS_TEXT = { STOPPED: "Stopped", PLAYING: "Playing", PAUSED: "Paused", SEEKING: "Seeking" } as const;

  const data = $derived(app.state!);
  const peer = $derived(app.soundpadFor ? (data.peers.find((p) => p.id === app.soundpadFor) ?? null) : null);
  const sp = $derived(peer?.soundpad ?? null);
  const reach = $derived(peer ? soundpadReach(peer) : "none");
  const list = $derived(peer ? (app.sounds[peer.id] ?? null) : null);
  const playing = $derived(!!sp && sp.status !== null && sp.status !== "STOPPED");

  let query = $state("");
  let line = $state<LineChoice>("default");
  let playNumber = $state<number | null>(null);
  let volumeDraft = $state<number | null>(null);
  let seekDraft = $state<number | null>(null);

  // A clock for the position between reports (positions arrive at most twice a second)
  let now = $state(Date.now());
  const tick = window.setInterval(() => {
    if (app.soundpadFor && sp?.status === "PLAYING") now = Date.now();
  }, 200);
  onDestroy(() => window.clearInterval(tick));

  const position = $derived(seekDraft ?? (sp ? positionNow(sp, now) : 0));
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

  function playIndex(event: SubmitEvent) {
    event.preventDefault();
    if (playNumber && playNumber >= 1) void app.call({ call: "playIndex", args: { ids: ids(), index: Math.floor(playNumber) } });
  }

  function seconds(ms: number | null): string {
    return ms === null ? "" : mediaTime(ms);
  }
</script>

<Drawer open={!!app.soundpadFor} title={peer ? `${peer.name}'s Soundpad` : "Soundpad"} onclose={() => (app.soundpadFor = null)}>
  <div class="panel">
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
          {#if playing}<span class="mono small">{seconds(position)} / {seconds(sp.durationMs)}</span>{/if}
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
            transport("seek", Math.round(Number(e.currentTarget.value)));
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
          <Button icon variant="ghost" disabled={!playing} aria-label="Back 5 seconds" title="Back 5 s" onclick={() => transport("jump", -JUMP_MS)}>
            <RotateCcw size="1.1em" />
          </Button>
          <Button icon variant="ghost" disabled={!playing} aria-label="Forward 5 seconds" title="Forward 5 s" onclick={() => transport("jump", JUMP_MS)}>
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
            value={volumeDraft ?? sp.volume ?? 0}
            aria-label="Volume"
            oninput={(e) => (volumeDraft = Number(e.currentTarget.value))}
            onchange={(e) => {
              transport("volume", Number(e.currentTarget.value));
              volumeDraft = null;
            }}
          />
          <span class="mono small vol-num">{volumeDraft ?? sp.volume ?? "–"}</span>
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
            {#each results.slice(0, SHOWN) as s (s.key)}
              <li class:current={playing && sp.key === s.key}>
                <span class="num mono">{s.index}</span>
                <span class="title">{s.title}</span>
                <span class="mono small faint">{seconds(s.durationMs)}</span>
                <Button size="s" variant="subtle" aria-label="Play {s.title}" onclick={() => play({ key: s.key }, s.title)}>
                  <Play size="0.9em" fill="currentColor" /> Play
                </Button>
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
              <li>
                <FileCheck size="1em" aria-hidden="true" />
                <span class="title">{f.name}</span>
                <Button size="s" variant="subtle" aria-label="Play {f.name}" onclick={() => play({ sha256: f.sha256 }, f.name)}>
                  <Play size="0.9em" fill="currentColor" /> Play
                </Button>
              </li>
            {/each}
          </ul>
          <span class="faint small">Their app adds a received file to Soundpad if it isn't there yet (full version).</span>
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
        <span class="faint small">Their All-sounds number; works with every app version.</span>
      </form>
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

  .message {
    padding: 0.65rem 0.85rem;
    border-radius: var(--radius-s);
    font-size: 0.875rem;
  }

  .message.bad {
    color: var(--bad);
    background: color-mix(in srgb, var(--bad) 10%, transparent);
  }

  .message.note {
    background: color-mix(in srgb, var(--warn) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--warn) 35%, transparent);
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

  @container (max-width: 26rem) {
    .num {
      display: none;
    }
  }
</style>
