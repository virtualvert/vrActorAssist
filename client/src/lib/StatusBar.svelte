<script lang="ts">
  import { connectionState, latencyMs } from "./stores";

  let { mode }: { mode: "director" | "actor" } = $props();

  let stateLabel = $derived(typeof $connectionState === "string" ? $connectionState : "Failed");
  let stateClass = $derived(
    $connectionState === "Connected" ? "connected"
    : $connectionState === "Connecting" ? "connecting"
    : typeof $connectionState === "object" ? "failed"
    : ""
  );
</script>

<div class="status-bar">
  <span class="badge mode">{mode === "director" ? "Director" : "Actor"}</span>
  <span class="badge state {stateClass}">{stateLabel}</span>
  <span class="badge latency">{$latencyMs}ms</span>
</div>

<style>
  .status-bar {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 0.8rem;
    flex-shrink: 0;
  }

  .badge {
    padding: 0.2rem 0.6rem;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--bg-primary);
    color: var(--text-secondary);
    white-space: nowrap;
  }

  .badge.mode {
    color: var(--accent);
    border-color: var(--accent);
    font-weight: 600;
  }

  .badge.state.connected {
    color: var(--accent-green);
    border-color: var(--accent-green);
  }

  .badge.state.connecting {
    color: var(--accent-yellow);
    border-color: var(--accent-yellow);
  }

  .badge.state.failed {
    color: var(--accent-red);
    border-color: var(--accent-red);
  }

  .badge.latency {
    font-family: var(--mono);
  }
</style>
