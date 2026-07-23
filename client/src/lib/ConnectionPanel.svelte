<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import { connectionState, type ConnectionState, appConfig } from "./stores";

  let serverUrl = $state("");

  onMount(async () => {
    const cfg = await invoke<any>("get_config");
    appConfig.set(cfg);
    serverUrl = cfg.server_url;

    await listen<ConnectionState>("connection-state", (event) => {
      connectionState.set(event.payload);
    });
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
  <span class="status-dot" class:connected={$connectionState === "Connected"}></span>
</div>

<style>
  .connection-panel { display: flex; align-items: center; gap: 0.5rem; }
  input { flex: 1; }
  .status-dot { width: 10px; height: 10px; border-radius: 50%; background: #888; }
  .status-dot.connected { background: #2ecc71; }
</style>
