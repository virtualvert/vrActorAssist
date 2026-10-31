<script lang="ts">
  import { Check, ListChecks, X } from "@lucide/svelte";
  import Button from "../components/Button.svelte";
  import type { AppState, ReadyRow } from "../protocol";
  import { app } from "../state.svelte";

  interface Props {
    data: AppState;
  }

  let { data }: Props = $props();

  const check = $derived(data.director?.readyCheck ?? null);
  const readyCount = $derived(check ? check.rows.filter((r) => r.state === "ready").length : 0);
  const usable = $derived(data.connection.status === "connected" && !data.connection.legacy);

  /** Labels for the checks this build knows; newer apps' checks show by their id. */
  const LABELS: Record<string, string> = { obs: "OBS connected", window: "VRChat window" };
  const STATE_TEXT: Record<ReadyRow["state"], string> = { waiting: "Waiting…", ready: "Ready", not_ready: "Not ready", offline: "Offline" };
</script>

<section class="ready" aria-label="Ready check">
  <div class="head">
    <h3 class="eyebrow"><ListChecks size="1em" /> Ready check</h3>
    {#if check}
      <span class="summary" class:all={readyCount === check.rows.length} aria-live="polite">{readyCount} of {check.rows.length} ready</span>
    {/if}
    <div class="spacer"></div>
    <Button
      size="s"
      variant={check ? "ghost" : "primary"}
      disabled={!usable}
      title={usable ? "Ask every actor and camera; cameras match the VRChat window to OBS first" : "Needs a connection to the v0.4 relay"}
      onclick={() => app.call({ call: "readyCheck", args: {} })}
    >
      {check ? "Check again" : "Ready check"}
    </Button>
  </div>
  {#if check}
    <ul class="rows">
      {#each check.rows as r (r.peerId)}
        <li class="ready-row">
          <span class="who"><strong>{r.name}</strong> <span class="state {r.state}">{STATE_TEXT[r.state]}</span></span>
          {#each r.checks as c (c.id)}
            <span class="item" class:bad={!c.ok}>
              {#if c.ok}<Check size="1em" aria-label="OK" />{:else}<X size="1em" aria-label="Failed" />{/if}
              <span>{LABELS[c.id] ?? c.id}{#if c.detail}<span class="detail">{` — ${c.detail}`}</span>{/if}</span>
            </span>
          {/each}
        </li>
      {/each}
    </ul>
  {/if}
</section>

<style>
  .ready {
    padding: 0.5rem 0.25rem 0;
  }

  .head {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .eyebrow {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    margin: 0;
  }

  .summary {
    font-size: 0.8125rem;
    font-weight: 700;
    color: var(--warn);
  }

  .summary.all {
    color: var(--go);
  }

  .spacer {
    flex: 1;
  }

  .rows {
    list-style: none;
    margin: 0.5rem 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .ready-row {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    padding: 0.4rem 0.6rem;
    border-radius: var(--radius-s);
    background: var(--surface-2);
    border: 1px solid var(--border);
  }

  .who {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    min-width: 0;
  }

  .who strong {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .state {
    font-size: 0.8125rem;
    font-weight: 700;
    color: var(--text-3);
  }

  .state.ready { color: var(--go); }
  .state.not_ready { color: var(--bad); }
  .state.waiting { color: var(--warn); }

  .item {
    display: flex;
    align-items: baseline;
    gap: 0.35rem;
    font-size: 0.8125rem;
    color: var(--go);
  }

  .item.bad {
    color: var(--bad);
  }

  .item :global(svg) {
    flex: none;
  }

  .item > span {
    color: var(--text-2);
    overflow-wrap: anywhere;
  }

  .detail {
    color: var(--text-3);
  }

  .item.bad .detail {
    color: var(--bad);
  }
</style>
