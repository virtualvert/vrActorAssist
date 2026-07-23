<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";

  interface ActorInfo { name: string; machine_id: string; latency_ms: number; approved: boolean; enabled: boolean; }

  let actors: ActorInfo[] = $state([]);

  async function refresh() {
    actors = await invoke<ActorInfo[]>("list_actors");
  }

  onMount(() => {
    refresh();
    let unlisten: (() => void) | undefined;
    listen("protocol-message", () => refresh()).then((fn) => { unlisten = fn; });
    return () => { unlisten?.(); };
  });

  async function approve(machineId: string) { await invoke("approve_actor", { machineId }); await refresh(); }
  async function deny(machineId: string) { await invoke("deny_actor", { machineId }); await refresh(); }
  async function forget(name: string) { await invoke("forget_actor", { name }); await refresh(); }
  async function toggleEnabled(name: string, enabled: boolean) { await invoke("set_actor_enabled", { name, enabled }); await refresh(); }

  function latencyClass(ms: number) { return ms < 50 ? "green" : ms < 150 ? "yellow" : "red"; }
</script>

<div class="actor-list">
  <h2>Actors</h2>
  {#if actors.length === 0}
    <p class="hint">No actors connected</p>
  {/if}
  {#each actors as actor}
    <div class="actor-row">
      <span class="status-dot {latencyClass(actor.latency_ms)}"></span>
      <span class="name">{actor.name}</span>
      <span class="latency">{actor.latency_ms}ms</span>
      {#if !actor.approved}
        <button onclick={() => approve(actor.machine_id)}>Approve</button>
        <button onclick={() => deny(actor.machine_id)}>Deny</button>
      {:else}
        <input type="checkbox" checked={actor.enabled} onchange={(e) => toggleEnabled(actor.name, e.currentTarget.checked)} />
        <button onclick={() => forget(actor.name)}>Forget</button>
      {/if}
    </div>
  {/each}
</div>

<style>
  .actor-list { display: flex; flex-direction: column; gap: 0.25rem; }
  .actor-list h2 { margin: 0 0 0.5rem 0; font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); }
  .hint { margin: 0; color: var(--text-secondary); font-style: italic; font-size: 0.85rem; }
  .actor-row { display: flex; align-items: center; gap: 0.5rem; padding: 0.35rem 0.25rem; border-radius: 4px; }
  .actor-row:hover { background: var(--bg-primary); }
  .name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .latency { font-family: var(--mono); font-size: 0.75rem; color: var(--text-secondary); }
  .actor-row button { padding: 0.25rem 0.5rem; font-size: 0.8rem; }
  .status-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  .status-dot.green { background: var(--accent-green); }
  .status-dot.yellow { background: var(--accent-yellow); }
  .status-dot.red { background: var(--accent-red); }
</style>
