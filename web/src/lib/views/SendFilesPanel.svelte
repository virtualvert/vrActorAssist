<script lang="ts">
  import { FolderOpen, Send, Square } from "@lucide/svelte";
  import Button from "../components/Button.svelte";
  import Drawer from "../components/Drawer.svelte";
  import { assignments, baseName, groupFiles, parseCharacterName } from "../files/character";
  import { fileSize, percent } from "../format";
  import type { FolderListing, Peer, SendBatch, SendFileState } from "../protocol";
  import { app } from "../state.svelte";

  // Per-viewer conveniences only: the last folder, and which actor plays which character (by
  // actor name, since session ids change when the relay restarts).
  const STORE = "vrcas.send";
  const remembered = load();

  let folderInput = $state(remembered.folder ?? "");
  let listing = $state<FolderListing | null>(null);
  let include = $state<Record<string, boolean>>({});
  /** Character → actor name. */
  let castNames = $state<Record<string, string>>(remembered.cast ?? {});
  /** Path → actor id ("" = by character, "-" = nobody). */
  let perFile = $state<Record<string, string>>({});
  let busy = $state(false);
  let error = $state("");

  const data = $derived(app.state!);
  const actors = $derived(data.peers.filter((p) => p.role === "actor" && !p.self));
  const batches = $derived(data.director?.files.batches ?? []);
  const active = $derived(batches.filter((b) => b.state === "waiting" || b.state === "sending"));
  const connected = $derived(data.connection.status === "connected" && !data.connection.legacy);

  const paths = $derived(listing?.files.map((f) => f.path) ?? []);
  const groups = $derived(groupFiles(paths));
  const sizeOf = $derived(new Map(listing?.files.map((f) => [f.path, f.size]) ?? []));
  /** Character → actor id, from the remembered names of actors who can receive files. */
  const castIds = $derived.by(() => {
    const ids: Record<string, string> = {};
    for (const [character, name] of Object.entries(castNames)) {
      const peer = actors.find((p) => p.name === name && canReceive(p));
      if (peer) ids[character] = peer.id;
    }
    return ids;
  });
  const plan = $derived(
    assignments(
      paths.filter((p) => include[p] && perFile[p] !== "-"),
      castIds,
      Object.fromEntries(paths.filter((p) => perFile[p] && perFile[p] !== "-").map((p) => [p, perFile[p]])),
    ),
  );
  const recipients = $derived(new Set(plan.items.map((i) => i.actorId)).size);
  const totalBytes = $derived(plan.items.reduce((sum, i) => sum + (sizeOf.get(i.path) ?? 0), 0));

  function load(): { folder?: string; cast?: Record<string, string> } {
    try {
      return JSON.parse(localStorage.getItem(STORE) ?? "{}") ?? {};
    } catch {
      return {};
    }
  }

  function persist() {
    try {
      localStorage.setItem(STORE, JSON.stringify({ folder: folderInput, cast: castNames }));
    } catch {
      // Storage can be unavailable (private windows); the panel works without it.
    }
  }

  const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

  function canReceive(p: Peer): boolean {
    return p.status === "online" && p.caps.includes("files");
  }

  function whyNot(p: Peer): string {
    if (p.caps.includes("legacy")) return "v0.3 app";
    if (p.status !== "online") return "offline";
    return "app too old";
  }

  function targetOf(path: string): string {
    const own = perFile[path];
    if (own) return own;
    const character = parseCharacterName(baseName(path));
    return (character !== null && castIds[character]) || "";
  }

  async function browse() {
    const folders = app.folders;
    if (!folders || busy) return;
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
    if (!folders || busy) return;
    error = "";
    busy = true;
    try {
      const opened = await folders.open(folderInput, "all");
      listing = opened;
      folderInput = opened.folder;
      // Everything is ticked; a file is sent once someone is picked for it (by character or by hand)
      include = Object.fromEntries(opened.files.map((f) => [f.path, true]));
      perFile = {};
      persist();
    } catch (err) {
      error = message(err);
    }
    busy = false;
  }

  function setCast(character: string, actorId: string) {
    const peer = actors.find((p) => p.id === actorId);
    if (peer) castNames[character] = peer.name;
    else delete castNames[character];
    persist();
  }

  async function send() {
    const opened = listing;
    if (!opened || !plan.items.length || plan.clashes.length || busy) return;
    busy = true;
    error = "";
    const items = plan.items;
    // Untick what went out, so a second click doesn't send it again (a refusal shows as a toast)
    if (await app.call({ call: "sendFiles", args: { folder: opened.folder, items } })) {
      for (const item of items) include[item.path] = false;
    }
    busy = false;
  }

  const STATE_TEXT: Record<SendFileState, string> = {
    queued: "Waiting",
    offered: "Asking",
    sending: "Sending",
    ok: "Sent",
    declined: "Declined",
    failed: "Failed",
    cancelled: "Cancelled",
  };

  function batchLine(b: SendBatch): string {
    if (b.state === "waiting") return "Getting the files ready…";
    if (b.state === "sending" && b.current) {
      return b.current.waiting
        ? `Waiting for ${b.actorName} to accept ${b.current.name}`
        : `${b.current.name} · ${percent(b.current.sent, b.current.size)} %`;
    }
    const parts = [`${b.ok} sent`];
    if (b.failed) parts.push(`${b.failed} not`);
    if (b.state === "cancelled") parts.push("cancelled");
    if (b.state === "failed") parts.push(b.detail || "stopped");
    return parts.join(" · ");
  }
</script>

<Drawer open={app.sendOpen} title="Send files" wide onclose={() => (app.sendOpen = false)}>
  <div class="panel">
    {#if batches.length}
      <section class="transfers" aria-label="Transfers">
        <h3 class="eyebrow">Transfers</h3>
        <ul>
          {#each [...batches].reverse() as b (b.id)}
            {@const running = b.state === "waiting" || b.state === "sending"}
            <li class="batch {b.state}">
              <div class="batch-head">
                <strong>{b.actorName}</strong>
                <span class="faint mono">{b.done} of {b.files} · {fileSize(b.sentBytes)} / {fileSize(b.bytes)}</span>
                {#if running}
                  <Button size="s" variant="subtle" onclick={() => app.call({ call: "cancelBatch", args: { id: b.id } })}>
                    <Square size="0.9em" /> Cancel
                  </Button>
                {/if}
              </div>
              <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow={percent(b.sentBytes, b.bytes)}>
                <span style:width="{percent(b.sentBytes, b.bytes)}%"></span>
              </div>
              <span class="line" class:faint={running}>{batchLine(b)}</span>
              {#if !running}
                {@const notSent = b.results.filter((r) => r.state !== "ok")}
                {#if notSent.length}
                  <ul class="results">
                    {#each notSent as r, i (i)}
                      <li><span class="name">{r.name}</span> <span class="r-{r.state}">{STATE_TEXT[r.state]}{r.detail && r.detail !== "Declined" ? `: ${r.detail}` : ""}</span></li>
                    {/each}
                  </ul>
                {/if}
              {/if}
            </li>
          {/each}
        </ul>
      </section>
    {/if}

    <p class="intro">
      Pick a folder, check who gets which file, and send. Files named <span class="mono">… - Diego.wav</span> go to whoever plays Diego. Each
      actor is asked before a file arrives, unless they accept files automatically.
    </p>

    <form class="folder" onsubmit={openFolder}>
      <label class="field grow">
        <span>Folder</span>
        <input class="input mono" bind:value={folderInput} placeholder="Paste a folder path, or browse" spellcheck="false" disabled={busy} />
      </label>
      <div class="folder-actions">
        <Button type="button" variant="subtle" onclick={browse} disabled={busy}><FolderOpen size="1.1em" /> Browse…</Button>
        <Button type="submit" variant="primary" disabled={busy || !folderInput.trim()}>Open</Button>
      </div>
    </form>
    {#if error}<p class="message bad" role="alert">{error}</p>{/if}
    {#if !connected}
      <p class="message note">{data.connection.legacy ? "Sending files needs the v0.4 relay; this one is v0.3." : "Connect to the relay to send files."}</p>
    {/if}
    {#if app.kind === "demo"}
      <p class="message note">Demo: a pretend folder and pretend transfers. Nothing is read from your disk.</p>
    {/if}

    {#if listing}
      {#if groups.characters.size}
        <section class="cast" aria-label="Characters">
          <h3 class="eyebrow">Who plays whom</h3>
          <div class="cast-grid">
            {#each [...groups.characters] as [character, files] (character)}
              <label class="cast-row">
                <span class="char">{character} <span class="faint">({files.length})</span></span>
                <select class="input" value={castIds[character] ?? ""} onchange={(e) => setCast(character, e.currentTarget.value)}>
                  <option value="">Nobody</option>
                  {#each actors as p (p.id)}
                    <option value={p.id} disabled={!canReceive(p)}>{p.name}{canReceive(p) ? "" : ` (${whyNot(p)})`}</option>
                  {/each}
                </select>
              </label>
            {/each}
          </div>
        </section>
      {/if}

      <div class="summary">
        <span class="count"><strong>{paths.length}</strong> {paths.length === 1 ? "file" : "files"}</span>
        <span class="faint mono path" title={listing.folder}>{listing.folder}</span>
      </div>
      {#if listing.truncated}<p class="message note">Only the first 5000 files are listed.</p>{/if}

      {#if !paths.length}
        <p class="faint">This folder has no files (hidden files are left out).</p>
      {:else}
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th class="check"><span class="sr-only">Include</span></th>
                <th>File</th>
                <th>Goes to</th>
                <th class="num size">Size</th>
              </tr>
            </thead>
            <tbody>
              {#each paths as path (path)}
                {@const to = targetOf(path)}
                {@const slash = path.lastIndexOf("/")}
                <tr class:off={!include[path] || !to || to === "-"}>
                  <td class="check"><input type="checkbox" bind:checked={include[path]} aria-label="Send {path}" /></td>
                  <td class="file">
                    {#if slash >= 0}<span class="faint">{path.slice(0, slash + 1)}</span>{/if}{path.slice(slash + 1)}
                  </td>
                  <td class="to">
                    <select class="input" value={perFile[path] ?? ""} onchange={(e) => (perFile[path] = e.currentTarget.value)} aria-label="Who gets {path}">
                      <option value="">{parseCharacterName(baseName(path)) !== null ? `By character${to && to !== "-" ? ` (${actors.find((p) => p.id === to)?.name ?? "?"})` : " (nobody)"}` : "Nobody"}</option>
                      {#each actors as p (p.id)}
                        <option value={p.id} disabled={!canReceive(p)}>{p.name}{canReceive(p) ? "" : ` (${whyNot(p)})`}</option>
                      {/each}
                      <option value="-">Don't send</option>
                    </select>
                  </td>
                  <td class="num mono size">{fileSize(sizeOf.get(path) ?? 0)}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        {#if plan.clashes.length}
          <p class="message bad">One actor would get two files named <span class="mono">{plan.clashes[0]}</span>. Leave one out or send it to someone else.</p>
        {/if}
      {/if}
    {/if}
  </div>

  {#snippet footer()}
    <div class="footer">
      {#if active.length > 1}
        <Button variant="subtle" onclick={() => app.call({ call: "cancelBatch", args: { id: "all" } })}><Square size="1em" /> Cancel all</Button>
      {/if}
      <Button variant="primary" onclick={send} disabled={!connected || busy || !plan.items.length || plan.clashes.length > 0}>
        <Send size="1.1em" />
        {plan.items.length
          ? `Send ${plan.items.length} ${plan.items.length === 1 ? "file" : "files"} to ${recipients} ${recipients === 1 ? "actor" : "actors"} (${fileSize(totalBytes)})`
          : "Send"}
      </Button>
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

  .transfers ul,
  .results {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .transfers > ul {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    margin-top: 0.5rem;
  }

  .batch {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
    padding: 0.75rem 0.85rem;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--surface-2);
  }

  .batch-head {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    flex-wrap: wrap;
  }

  .batch-head .faint {
    font-size: 0.8125rem;
  }

  .batch-head :global(.btn) {
    margin-left: auto;
  }

  .line {
    font-size: 0.875rem;
    overflow-wrap: anywhere;
  }

  .batch.done .line {
    color: var(--ok);
  }

  .batch.cancelled .line,
  .batch.failed .line {
    color: var(--warn);
  }

  .results {
    font-size: 0.8125rem;
  }

  .results .name {
    overflow-wrap: anywhere;
  }

  .r-declined,
  .r-cancelled {
    color: var(--warn);
  }

  .r-failed {
    color: var(--bad);
  }

  .bar {
    height: 0.375rem;
    border-radius: 999px;
    background: var(--surface);
    border: 1px solid var(--border);
    overflow: hidden;
  }

  .bar span {
    display: block;
    height: 100%;
    background: var(--accent);
    transition: width 250ms linear;
  }

  .cast-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
    gap: 0.5rem 1rem;
    margin-top: 0.5rem;
  }

  .cast-row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
  }

  .char {
    flex: 1;
    min-width: 0;
    font-weight: 600;
    overflow-wrap: anywhere;
  }

  .cast-row select {
    flex: 0 1 11rem;
    min-width: 0;
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
    padding: 0.5rem 0.7rem;
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

  .file {
    min-width: 12rem;
    overflow-wrap: anywhere;
  }

  .to select {
    width: 100%;
    min-width: 9rem;
  }

  .num {
    text-align: right;
    white-space: nowrap;
  }

  tr.off td.file,
  tr.off td.size {
    opacity: 0.45;
  }

  .footer {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 0.6rem;
    flex-wrap: wrap;
  }

  .sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
    white-space: nowrap;
  }

  @container (max-width: 34rem) {
    .size {
      display: none;
    }

    .file {
      min-width: 0;
    }

    .to select {
      min-width: 0;
    }
  }
</style>
