<script lang="ts">
  import { Play, Square, Timer } from "@lucide/svelte";
  import { onDestroy } from "svelte";
  import Button from "../components/Button.svelte";
  import type { AppState } from "../protocol";
  import { app } from "../state.svelte";

  interface Props {
    data: AppState;
  }

  let { data }: Props = $props();

  const connected = $derived(data.connection.status === "connected");
  const targeted = $derived(data.peers.filter((p) => data.targets.includes(p.id)));
  const counting = $derived(data.countdown !== null);

  // Local clock for the countdown ring; the agent owns the actual timing.
  let now = $state(Date.now());
  let timer: number | null = null;
  $effect(() => {
    if (counting && timer === null) {
      timer = window.setInterval(() => (now = Date.now()), 50);
    } else if (!counting && timer !== null) {
      window.clearInterval(timer);
      timer = null;
    }
  });
  onDestroy(() => timer !== null && window.clearInterval(timer));

  const remaining = $derived(data.countdown ? Math.max(0, data.countdown.endsAt - now) : 0);
  const progress = $derived(data.countdown ? 1 - remaining / data.countdown.durationMs : 0);

  const summary = $derived.by(() => {
    if (!connected) return "Connect to call cues";
    if (!targeted.length) return "No actors targeted — pick some in the cast list or graph";
    const names = targeted.map((p) => p.name);
    const shown = names.slice(0, 3).join(", ");
    return `→ ${shown}${names.length > 3 ? ` +${names.length - 3}` : ""}`;
  });

  const blockReason = $derived(!connected ? "Not connected" : !targeted.length ? "No actors targeted" : undefined);
</script>

<div class="deck card">
  <div class="summary">
    <span class="eyebrow">Cue</span>
    <span class="who" class:empty={!targeted.length || !connected}>{summary}</span>
  </div>
  <div class="buttons">
    <Button variant="go" size="xl" disabled={!!blockReason || counting} title={blockReason} onclick={() => app.call({ call: "cue", args: { command: "go" } })}>
      <Play size="1.15em" fill="currentColor" /> GO
    </Button>
    <Button
      variant="warn"
      size="xl"
      class="countdown"
      disabled={!!blockReason || counting}
      title={blockReason}
      onclick={() => app.call({ call: "cue", args: { command: "countdown" } })}
    >
      {#if counting}
        <span class="ring" style="--p: {progress}"></span>
        <span class="num mono">{Math.ceil(remaining / 1000)}</span>
      {:else}
        <Timer size="1.15em" /> Play in 3s
      {/if}
    </Button>
    <Button variant="stop" size="xl" disabled={!connected} onclick={() => app.call({ call: "cue", args: { command: "stop" } })}>
      <Square size="1em" fill="currentColor" /> {counting ? "CANCEL" : "STOP"}
    </Button>
  </div>
</div>

<style>
  .deck {
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
    padding: 1rem;
    background: var(--surface-glass);
    backdrop-filter: blur(16px) saturate(1.3);
  }

  .summary {
    display: flex;
    align-items: baseline;
    gap: 0.75rem;
    min-width: 0;
    padding: 0 0.25rem;
  }

  .who {
    font-weight: 650;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .who.empty {
    color: var(--text-3);
    font-weight: 500;
  }

  .buttons {
    display: grid;
    grid-template-columns: 1.4fr 1fr 1fr;
    gap: 0.75rem;
  }

  .buttons :global(.countdown) {
    position: relative;
    overflow: hidden;
  }

  .ring {
    position: absolute;
    inset: 0;
    background: conic-gradient(rgb(255 255 255 / 0.35) calc(var(--p) * 360deg), transparent 0);
    mix-blend-mode: soft-light;
  }

  .num {
    position: relative;
    font-size: 2rem;
    font-weight: 800;
  }

  @container (max-width: 34rem) {
    .buttons {
      grid-template-columns: 1fr 1fr;
    }

    .buttons :global(.go) {
      grid-column: 1 / -1;
    }

    .buttons :global(.btn.xl) {
      font-size: 1.15rem;
      padding: 0 0.9rem;
    }
  }
</style>
