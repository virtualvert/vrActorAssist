<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import { connectionState, type ConnectionState, appConfig } from "./stores";

  let serverUrl = $state("");

  onMount(() => {
    if ($appConfig) {
      serverUrl = $appConfig.server_url;
    }

    let unlisten: (() => void) | undefined;
    listen<ConnectionState>("connection-state", (event) => {
      connectionState.set(event.payload);
    }).then((fn) => { unlisten = fn; });

    return () => { unlisten?.(); };
  });

  async function toggleConnection() {
    if ($connectionState === "Disconnected" || (typeof $connectionState === "object" && "Failed" in $connectionState)) {
      if ($appConfig) {
        const updated = { ...$appConfig, server_url: serverUrl };
        await invoke("save_config", { newConfig: updated });
        appConfig.set(updated);
      }
      await invoke("connect");
    } else {
      await invoke("disconnect");
    }
  }

  let isBusy = $derived($connectionState === "Connecting");
  let label = $derived(
    $connectionState === "Connected" ? "Disconnect"
    : $connectionState === "Connecting" ? "Connecting..."
    : "Connect"
  );
</script>

<div class="connection-panel">
  <input type="text" bind:value={serverUrl} placeholder="wss://vra.dannygreyproductions.com/ws" disabled={isBusy} />
  <button onclick={toggleConnection} disabled={isBusy}>{label}</button>
  <span
    class="status-dot"
    class:connected={$connectionState === "Connected"}
    class:connecting={$connectionState === "Connecting"}
  ></span>
</div>

<style>
  .connection-panel { display: flex; align-items: center; gap: 0.5rem; }
  input { flex: 1; min-width: 0; }
  .status-dot { width: 10px; height: 10px; border-radius: 50%; background: var(--text-secondary); flex-shrink: 0; transition: background 0.2s ease; }
  .status-dot.connected { background: var(--accent-green); box-shadow: 0 0 6px var(--accent-green); }
  .status-dot.connecting { background: var(--accent-yellow); box-shadow: 0 0 6px var(--accent-yellow); }
</style>
