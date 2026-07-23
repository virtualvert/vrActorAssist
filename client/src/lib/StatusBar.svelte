<script lang="ts">
  import { connectionState, latencyMs } from "./stores";

  let { mode }: { mode: "director" | "actor" } = $props();
</script>

<div class="status-bar">
  <span class="mode">{mode === "director" ? "Director" : "Actor"}</span>
  <span class="status">{typeof $connectionState === "string" ? $connectionState : "Failed"}</span>
  <span class="latency">{$latencyMs}ms</span>
</div>

<style>
  .status-bar { display: flex; gap: 1rem; padding: 0.4rem 0.8rem; font-size: 0.85rem; opacity: 0.8; }
</style>
