<script lang="ts">
  import { FolderOpen, RotateCcw, Save, Square } from "@lucide/svelte";
  import { onDestroy } from "svelte";
  import { AudioEngine } from "../audio/engine";
  import type { Loudness } from "../audio/loudness";
  import {
    CEILING_RANGE,
    clampSetting,
    DEFAULT_SETTINGS,
    planGain,
    planOutputs,
    TARGET_RANGE,
    type GainPlan,
    type NormalizeSettings,
  } from "../audio/normalize";
  import Button from "../components/Button.svelte";
  import Drawer from "../components/Drawer.svelte";
  import { decibels, mediaTime } from "../format";

  /** "4.2 s" for short lines, "1:23" from a minute up. */
  const length = (seconds: number) => (seconds < 60 ? `${seconds.toFixed(1)} s` : mediaTime(seconds * 1000));
  import type { FolderListing } from "../protocol";
  import { app } from "../state.svelte";

  type Status = "waiting" | "measuring" | "measured" | "saving" | "saved" | "skipped" | "error";

  interface Row {
    path: string;
    /** Where the copy goes inside normalized/; null when the file is skipped. */
    output: string | null;
    include: boolean;
    status: Status;
    note: string;
    loudness: Loudness | null;
  }

  // Per-viewer conveniences only: the last folder and settings.
  const STORE = "vrcas.normalize";
  const remembered = load();

  let folderInput = $state(remembered.folder ?? "");
  let target = $state(clampSetting(remembered.targetLufs ?? NaN, TARGET_RANGE, DEFAULT_SETTINGS.targetLufs));
  let ceiling = $state(clampSetting(remembered.ceilingDbtp ?? NaN, CEILING_RANGE, DEFAULT_SETTINGS.ceilingDbtp));
  let listing = $state<FolderListing | null>(null);
  let rows = $state<Row[]>([]);
  let busy = $state<"idle" | "opening" | "measuring" | "saving">("idle");
  let progress = $state({ done: 0, total: 0 });
  let error = $state("");
  let stopRequested = false;
  let engine: AudioEngine | null = null;

  const settings = $derived<NormalizeSettings>({ targetLufs: target, ceilingDbtp: ceiling });
  const plans = $derived(rows.map((row) => (row.loudness ? planGain(row.loudness, settings) : null)));
  const saveable = $derived(rows.filter((row, i) => row.include && row.output && plans[i] && (row.status === "measured" || row.status === "saved")).length);
  const failed = $derived(rows.filter((row) => row.status === "error").length);
  const allSaved = $derived(saveable > 0 && rows.every((row, i) => !(row.include && row.output && plans[i]) || row.status === "saved"));
  const idle = $derived(busy === "idle");

  onDestroy(() => engine?.dispose());

  function load(): { folder?: string; targetLufs?: number; ceilingDbtp?: number } {
    try {
      return JSON.parse(localStorage.getItem(STORE) ?? "{}") ?? {};
    } catch {
      return {};
    }
  }

  function persist() {
    try {
      localStorage.setItem(STORE, JSON.stringify({ folder: folderInput, targetLufs: target, ceilingDbtp: ceiling }));
    } catch {
      // Storage can be unavailable (private windows); the panel works without it.
    }
  }

  const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

  async function browse() {
    const folders = app.folders;
    if (!folders || !idle) return;
    error = "";
    try {
      const path = await folders.pick();
      if (path) {
        folderInput = path;
        await openFolder();
      }
    } catch (err) {
      error = message(err);
    }
  }

  async function openFolder(event?: SubmitEvent) {
    event?.preventDefault();
    const folders = app.folders;
    if (!folders || !idle) return;
    error = "";
    busy = "opening";
    try {
      const opened = await folders.open(folderInput);
      listing = opened;
      folderInput = opened.folder;
      persist();
      rows = planOutputs(opened.files.map((f) => f.path)).map((plan) => ({
        path: plan.path,
        output: plan.output,
        include: plan.output !== null,
        status: plan.output ? "waiting" : "skipped",
        note: plan.skipReason ?? "",
        loudness: null,
      }));
    } catch (err) {
      error = message(err);
      busy = "idle";
      return;
    }
    busy = "idle";
    await measureAll();
  }

  async function measureAll() {
    const folders = app.folders;
    const opened = listing;
    if (!folders || !opened || !idle) return;
    const todo = rows.filter((row) => row.status === "waiting" || row.status === "error");
    if (!todo.length) return;
    engine ??= new AudioEngine();
    busy = "measuring";
    stopRequested = false;
    progress = { done: 0, total: todo.length };
    for (const row of todo) {
      if (stopRequested) break;
      row.status = "measuring";
      try {
        row.loudness = await engine.measure(await folders.read(opened.folder, row.path));
        row.status = "measured";
        row.note = "";
      } catch (err) {
        row.status = "error";
        row.note = message(err);
      }
      progress.done += 1;
    }
    busy = "idle";
  }

  async function saveAll() {
    const folders = app.folders;
    const opened = listing;
    if (!folders || !opened || !idle) return;
    const todo: { row: Row; plan: GainPlan; output: string }[] = [];
    rows.forEach((row, i) => {
      const plan = plans[i];
      if (row.include && row.output && plan && (row.status === "measured" || row.status === "saved")) todo.push({ row, plan, output: row.output });
    });
    if (!todo.length) return;
    engine ??= new AudioEngine();
    busy = "saving";
    stopRequested = false;
    progress = { done: 0, total: todo.length };
    let saved = 0;
    for (const { row, plan, output } of todo) {
      if (stopRequested) break;
      row.status = "saving";
      try {
        const copy = await engine.render(await folders.read(opened.folder, row.path), plan.gainDb);
        await folders.write(opened.folder, output, copy);
        row.status = "saved";
        row.note = "";
        saved += 1;
      } catch (err) {
        row.status = "error";
        row.note = message(err);
      }
      progress.done += 1;
    }
    busy = "idle";
    if (saved) app.toast("success", `Saved ${saved} ${saved === 1 ? "copy" : "copies"} to ${opened.output}`);
    else app.toast("warning", "No copies were saved");
  }

  function changeSetting() {
    target = clampSetting(target, TARGET_RANGE, DEFAULT_SETTINGS.targetLufs);
    ceiling = clampSetting(ceiling, CEILING_RANGE, DEFAULT_SETTINGS.ceilingDbtp);
    persist();
    // Copies saved with the old settings no longer match what the table shows.
    for (const row of rows) if (row.status === "saved") row.status = "measured";
  }

  function result(row: Row, plan: GainPlan | null): { text: string; tone: "ok" | "warn" | "bad" | "faint" } {
    switch (row.status) {
      case "waiting":
        return { text: "Waiting", tone: "faint" };
      case "measuring":
        return { text: "Measuring…", tone: "faint" };
      case "saving":
        return { text: "Saving…", tone: "faint" };
      case "skipped":
        return { text: row.note, tone: "faint" };
      case "error":
        return { text: row.note, tone: "bad" };
    }
    if (!plan) return { text: "Silent — no copy", tone: "faint" };
    const notes: string[] = [];
    if (row.status === "saved") notes.push("Saved");
    if (plan.peakLimited) notes.push(`Peak-limited: ${decibels(plan.resultLufs)} LUFS`);
    if (row.loudness?.short) notes.push("Short sound");
    if (!notes.length) return { text: "Ready", tone: "faint" };
    return { text: notes.join(" · "), tone: plan.peakLimited ? "warn" : row.status === "saved" ? "ok" : "faint" };
  }

  function split(path: string): [string, string] {
    const slash = path.lastIndexOf("/");
    return slash < 0 ? ["", path] : [path.slice(0, slash + 1), path.slice(slash + 1)];
  }
</script>

<Drawer open={app.normalizeOpen} title="Normalize folder" wide onclose={() => (app.normalizeOpen = false)}>
  <div class="panel">
    <p class="intro">
      Measures how loud each audio file is and writes copies at one loudness into a <strong>normalized</strong> folder inside it, so every line
      plays at the same level. Your original files aren't changed.
    </p>

    <form class="folder" onsubmit={openFolder}>
      <label class="field grow">
        <span>Folder</span>
        <input class="input mono" bind:value={folderInput} placeholder="Paste a folder path, or browse" spellcheck="false" disabled={!idle} />
      </label>
      <div class="folder-actions">
        <Button type="button" variant="subtle" onclick={browse} disabled={!idle}><FolderOpen size="1.1em" /> Browse…</Button>
        <Button type="submit" variant="primary" disabled={!idle || !folderInput.trim()}>Open</Button>
      </div>
    </form>
    {#if error}<p class="message bad" role="alert">{error}</p>{/if}

    <div class="settings">
      <label class="field">
        <span>Target loudness <span class="faint">LUFS</span></span>
        <input class="input mono" type="number" step="0.5" min={TARGET_RANGE[0]} max={TARGET_RANGE[1]} bind:value={target} onchange={changeSetting} disabled={!idle} />
      </label>
      <label class="field">
        <span>Peak ceiling <span class="faint">dBTP</span></span>
        <input class="input mono" type="number" step="0.5" min={CEILING_RANGE[0]} max={CEILING_RANGE[1]} bind:value={ceiling} onchange={changeSetting} disabled={!idle} />
      </label>
      <p class="faint small">
        Copies are 16-bit WAV at 48 kHz with the same names, so " - Character" routing keeps working. No limiter: when a peak would pass the
        ceiling, the copy stays quieter instead.
      </p>
    </div>

    {#if app.kind === "demo"}
      <p class="message note">Demo: a pretend folder of voice lines. Nothing is read from or written to your disk.</p>
    {/if}

    {#if listing}
      <div class="summary">
        <span class="count"><strong>{rows.length}</strong> audio {rows.length === 1 ? "file" : "files"}</span>
        <span class="faint mono path" title={listing.output}>→ {listing.output}</span>
      </div>
      {#if listing.truncated}<p class="message note">Only the first 5000 audio files are listed.</p>{/if}

      {#if rows.length === 0}
        <p class="faint">No audio files here (WAV, FLAC, MP3, OGG, Opus, M4A or AAC). Files in <span class="mono">normalized</span> and hidden folders are left out.</p>
      {:else}
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th class="check"><span class="sr-only">Include</span></th>
                <th>File</th>
                <th class="num loud">Loudness</th>
                <th class="num peak">Peak</th>
                <th class="num">Gain</th>
                <th>Result</th>
              </tr>
            </thead>
            <tbody>
              {#each rows as row, i (row.path)}
                {@const plan = plans[i]}
                {@const outcome = result(row, plan)}
                {@const [dir, name] = split(row.path)}
                <tr class:off={!row.include}>
                  <td class="check">
                    <input type="checkbox" bind:checked={row.include} disabled={!row.output || !idle} aria-label="Include {row.path}" />
                  </td>
                  <td class="file">
                    <span class="name">{#if dir}<span class="faint">{dir}</span>{/if}{name}</span>
                    {#if row.loudness}<span class="faint mono len">{length(row.loudness.durationS)}</span>{/if}
                  </td>
                  <td class="num mono loud">{row.loudness ? decibels(row.loudness.integrated) : ""}</td>
                  <td class="num mono peak">{row.loudness ? decibels(row.loudness.truePeak) : ""}</td>
                  <td class="num mono gain" class:limited={plan?.peakLimited}>{plan ? `${decibels(plan.gainDb, true)} dB` : ""}</td>
                  <td class="result {outcome.tone}">{outcome.text}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        <p class="faint small">This evens out the files. Each actor's Soundpad volume and mic level still change how loud they sound in VRChat.</p>
      {/if}
    {/if}
  </div>

  {#snippet footer()}
    <div class="footer">
      {#if busy === "measuring" || busy === "saving"}
        <span class="progress" aria-live="polite">{busy === "measuring" ? "Measuring" : "Saving"} {Math.min(progress.done + 1, progress.total)} of {progress.total}…</span>
        <Button variant="subtle" onclick={() => (stopRequested = true)}><Square size="1em" /> Stop</Button>
      {:else}
        {#if failed}
          <Button variant="subtle" onclick={measureAll} disabled={!listing}><RotateCcw size="1em" /> Retry {failed} failed</Button>
        {/if}
        <Button variant="primary" onclick={saveAll} disabled={!saveable}>
          <Save size="1.1em" /> Save {saveable} {saveable === 1 ? "copy" : "copies"}{allSaved ? " again" : ""}
        </Button>
      {/if}
    </div>
  {/snippet}
</Drawer>

<style>
  .panel {
    container-type: inline-size;
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
  }

  .intro {
    color: var(--text-2);
  }

  .folder {
    display: flex;
    align-items: flex-end;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  .grow {
    flex: 1 1 18rem;
    min-width: 0;
  }

  .folder-actions {
    display: flex;
    gap: 0.5rem;
  }

  .settings {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 12rem)) minmax(0, 1fr);
    gap: 0.6rem 1rem;
    align-items: end;
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

  .summary {
    display: flex;
    align-items: baseline;
    gap: 0.8rem;
    min-width: 0;
  }

  .count {
    flex: none;
    white-space: nowrap;
  }

  .path {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-size: 0.8125rem;
  }

  .table-wrap {
    overflow-x: auto;
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }

  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
  }

  th,
  td {
    padding: 0.55rem 0.7rem;
    text-align: left;
    vertical-align: middle;
    border-bottom: 1px solid var(--border);
  }

  th {
    font-size: 0.75rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: var(--text-3);
    background: var(--surface-2);
  }

  tbody tr:last-child td {
    border-bottom: 0;
  }

  .check {
    width: 1%;
  }

  .check input {
    width: 1.15rem;
    height: 1.15rem;
    accent-color: var(--accent);
  }

  .num {
    text-align: right;
    white-space: nowrap;
  }

  .file {
    min-width: 12rem;
  }

  .name {
    display: block;
    overflow-wrap: anywhere;
  }

  .len {
    font-size: 0.75rem;
  }

  .gain.limited {
    color: var(--warn);
  }

  tr.off td:not(.check) {
    opacity: 0.45;
  }

  .result {
    min-width: 9rem;
  }

  .result.ok {
    color: var(--ok);
  }

  .result.warn {
    color: var(--warn);
  }

  .result.bad {
    color: var(--bad);
  }

  .footer {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  .progress {
    margin-right: auto;
    color: var(--text-2);
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }

  @container (max-width: 40rem) {
    .settings {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }

    .settings p {
      grid-column: 1 / -1;
    }

    .peak {
      display: none;
    }
  }

  /* Phone width: keep what to do (gain) and what happened (result) in view. */
  @container (max-width: 30rem) {
    .loud {
      display: none;
    }

    .file {
      min-width: 0;
    }

    .result {
      min-width: 0;
    }
  }
</style>
