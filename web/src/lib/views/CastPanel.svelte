<script lang="ts">
  import { AudioLines, Check, UserPlus, Trash, X } from "@lucide/svelte";
  import Button from "../components/Button.svelte";
  import StatusDot from "../components/StatusDot.svelte";
  import { initials, latencyLevel, peerSubtitle } from "../format";
  import type { AppState, Peer } from "../protocol";
  import { soundpadReach } from "../soundpad";
  import { app } from "../state.svelte";

  interface Props {
    data: AppState;
  }

  let { data }: Props = $props();

  const actors = $derived(data.peers.filter((p) => p.role === "actor" && !p.self));
  const cameras = $derived(data.peers.filter((p) => p.role === "camera" && !p.self));
  const directors = $derived(data.peers.filter((p) => p.role === "director" && !p.self));
  const targets = $derived(new Set(data.targets));
  let confirmForget = $state<string | null>(null);

  function setTargets(ids: string[]) {
    void app.call({ call: "setTargets", args: { ids } });
  }

  function toggle(p: Peer) {
    setTargets(targets.has(p.id) ? data.targets.filter((id) => id !== p.id) : [...data.targets, p.id]);
  }

  function forget(p: Peer) {
    if (confirmForget !== p.id) {
      confirmForget = p.id;
      setTimeout(() => confirmForget === p.id && (confirmForget = null), 4000);
      return;
    }
    confirmForget = null;
    void app.call({ call: "forget", args: { id: p.id } });
  }

  const selectable = $derived(actors.filter((p) => p.status !== "pending"));

  /** The Soundpad button's tooltip; `off` marks an actor whose Soundpad isn't answering. */
  function soundpadHint(p: Peer): { text: string; off: boolean } {
    const reach = soundpadReach(p);
    if (reach !== "full") return { text: `${p.name}'s Soundpad: Go, Stop and a sound by number (older app)`, off: false };
    if (p.soundpad && !p.soundpad.available) return { text: `${p.name}'s Soundpad isn't answering`, off: true };
    return { text: `${p.name}'s Soundpad: sounds, line, volume`, off: false };
  }
</script>

<aside class="cast card">
  <header>
    <div>
      <h2>Cast</h2>
      <span class="faint">{actors.length} actor{actors.length === 1 ? "" : "s"} · {data.targets.length} targeted</span>
    </div>
    <div class="bulk" role="group" aria-label="Target actors">
      <Button size="s" variant="ghost" onclick={() => setTargets(selectable.map((p) => p.id))}>All</Button>
      <Button size="s" variant="ghost" onclick={() => setTargets([])}>None</Button>
      <Button size="s" variant="ghost" onclick={() => setTargets(selectable.filter((p) => !targets.has(p.id)).map((p) => p.id))}>Invert</Button>
    </div>
  </header>

  <div class="scroll">
    {#if data.pending.length}
      <section class="pending">
        <h3 class="eyebrow"><UserPlus size="1em" /> Waiting to join</h3>
        {#each data.pending as p (p.id)}
          <div class="pending-row">
            <span class="avatar role-actor">{initials(p.name)}</span>
            <strong>{p.name}</strong>
            <div class="spacer"></div>
            <Button size="s" variant="go" onclick={() => app.call({ call: "approve", args: { id: p.id } })}><Check size="1em" /> Approve</Button>
            <Button size="s" icon variant="ghost" aria-label="Deny {p.name}" onclick={() => app.call({ call: "deny", args: { id: p.id } })}><X size="1.1em" /></Button>
          </div>
        {/each}
      </section>
    {/if}

    <ul class="list" aria-label="Actors">
      {#each actors as p (p.id)}
        {@const on = targets.has(p.id)}
        <li class="actor-row" class:on>
          <button
            class="target"
            type="button"
            role="checkbox"
            aria-checked={on}
            aria-label="{p.name}: {on ? 'receives cues' : 'excluded from cues'}"
            onclick={() => toggle(p)}
          >
            <span class="box" aria-hidden="true">{#if on}<Check size="1em" strokeWidth={3.2} />{/if}</span>
            <span class="avatar role-actor" class:playing={p.activity === "playing"}>{initials(p.name)}</span>
            <span class="text">
              <strong>{p.name}</strong>
              <span class="sub lvl-{latencyLevel(p.status, p.latencyMs)}" class:playing={p.activity === "playing"}>{peerSubtitle(p)}</span>
            </span>
          </button>
          <StatusDot level={latencyLevel(p.status, p.latencyMs)} pulse={p.activity === "playing"} />
          {#if p.status !== "pending"}
            {@const hint = soundpadHint(p)}
            <Button size="s" icon variant="ghost" class={hint.off ? "sp-off" : ""} aria-label="{p.name}'s Soundpad" title={hint.text} onclick={() => (app.soundpadFor = p.id)}>
              <AudioLines size="1.05em" />
            </Button>
          {/if}
          <Button
            size="s"
            icon={confirmForget !== p.id}
            variant={confirmForget === p.id ? "danger" : "ghost"}
            aria-label="Forget {p.name}"
            title="Forget — they must be approved again"
            onclick={() => forget(p)}
          >
            {#if confirmForget === p.id}Forget?{:else}<Trash size="1em" />{/if}
          </Button>
        </li>
      {:else}
        <li class="empty faint">
          {data.connection.status === "connected" ? "No actors connected yet. New actors appear in “Waiting to join”." : "Connect to see your cast."}
        </li>
      {/each}
    </ul>

    {#if cameras.length || directors.length}
      <section class="others">
        <h3 class="eyebrow">Crew</h3>
        {#each [...directors, ...cameras] as p (p.id)}
          <div class="crew-row">
            <span class="avatar role-{p.role}" class:rolling={p.activity === "rolling"}>{initials(p.name)}</span>
            <span class="text">
              <strong>{p.name}</strong>
              <span class="sub" class:rec={p.activity === "rolling"}>{p.role === "camera" ? (p.activity === "rolling" ? "● Rolling" : "Standby") : "Director"} · {peerSubtitle({ ...p, activity: "idle" })}</span>
            </span>
          </div>
        {/each}
      </section>
    {/if}
  </div>
</aside>

<style>
  .cast {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
    flex-wrap: wrap;
    padding: 1rem 1rem 0.75rem var(--pad);
    border-bottom: 1px solid var(--border);
  }

  h2 {
    font-size: 1.25rem;
  }

  header .faint {
    font-size: 0.8125rem;
  }

  .bulk {
    display: flex;
    gap: 0.15rem;
  }

  .scroll {
    flex: 1;
    overflow-y: auto;
    padding: 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 1rem;
  }

  .eyebrow {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin: 0 0 0.5rem 0.25rem;
  }

  .pending {
    padding: 0.75rem;
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--warn) 9%, transparent);
    border: 1px solid color-mix(in srgb, var(--warn) 30%, transparent);
    animation: rise-in var(--t) var(--ease-out);
  }

  .pending .eyebrow {
    color: var(--warn);
  }

  .pending-row,
  .crew-row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.35rem 0.25rem;
  }

  .spacer {
    flex: 1;
  }

  .list {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .actor-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.3rem 0.5rem 0.3rem 0.3rem;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    background: var(--surface-2);
    transition: border-color var(--t-fast), background-color var(--t-fast);
    animation: rise-in var(--t) var(--ease-out);
  }

  .actor-row.on {
    border-color: color-mix(in srgb, var(--actor) 45%, transparent);
    background: color-mix(in srgb, var(--actor) 8%, var(--surface-2));
  }

  .target {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 0.7rem;
    min-height: calc(var(--target) * 1.15);
    padding: 0.25rem 0.4rem;
    border: 0;
    background: none;
    text-align: left;
    border-radius: var(--radius-s);
  }

  .box {
    display: grid;
    place-items: center;
    width: calc(var(--target) * 0.6);
    aspect-ratio: 1;
    flex: none;
    border-radius: 0.45rem;
    border: 2px solid var(--border-strong);
    color: #fff;
    transition: background-color var(--t-fast), border-color var(--t-fast);
  }

  .on .box {
    background: var(--go);
    border-color: var(--go);
  }

  .avatar {
    display: grid;
    place-items: center;
    width: calc(var(--target) * 0.95);
    aspect-ratio: 1;
    flex: none;
    border-radius: 50%;
    font-size: 0.8125rem;
    font-weight: 800;
    color: #fff;
    background: radial-gradient(circle at 35% 30%, color-mix(in srgb, var(--role) 55%, white), var(--role) 60%, color-mix(in srgb, var(--role) 60%, black));
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--role) 20%, transparent);
  }

  .avatar.playing,
  .avatar.rolling {
    animation: breathe 1.2s ease-in-out infinite;
  }

  .avatar.rolling {
    box-shadow: 0 0 0 3px var(--live);
  }

  .text {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .text strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .sub {
    font-size: 0.8125rem;
    color: var(--text-3);
    font-weight: 600;
  }

  .sub.lvl-fair { color: var(--warn); }
  .sub.lvl-poor { color: var(--bad); }
  .sub.playing { color: var(--actor); }
  .sub.rec { color: var(--live); }

  .actor-row :global(.sp-off) {
    color: var(--warn);
  }

  .empty {
    padding: 1.5rem 0.75rem;
    text-align: center;
  }
</style>
