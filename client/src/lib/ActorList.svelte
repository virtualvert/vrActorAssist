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
  .actor-list h2 { margin: 0 0 0.5rem 0; font-size: 1.1rem; }
  .actor-row { display: flex; align-items: center; gap: 0.5rem; padding: 0.3rem 0; }
  .status-dot { width: 10px; height: 10px; border-radius: 50%; }
  .status-dot.green { background: #2ecc71; }
  .status-dot.yellow { background: #f1c40f; }
  .status-dot.red { background: #e74c3c; }
</style>
