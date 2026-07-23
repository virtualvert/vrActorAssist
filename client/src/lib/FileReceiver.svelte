<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import { appConfig } from "./stores";

  let incoming = $state<{ filename: string; size: number } | null>(null);

  onMount(() => {
    let unlisten: (() => void) | undefined;
    listen<any>("protocol-message", (event) => {
      const msg = event.payload;
      if (msg.FileReq) {
        incoming = { filename: msg.FileReq.filename, size: msg.FileReq.size };
      }
    }).then((fn) => { unlisten = fn; });
    return () => { unlisten?.(); };
  });

  async function accept() {
    if (!incoming) return;
    const cfg = $appConfig;
    if (!cfg) return;
    await invoke("respond_to_file_request", { filename: incoming.filename, accept: true, saveDir: cfg.receive_dir });
    incoming = null;
  }

  async function decline() {
    if (!incoming) return;
    await invoke("respond_to_file_request", { filename: incoming.filename, accept: false, saveDir: "" });
    incoming = null;
  }
</script>

<div class="file-receiver">
  <h3>File Transfers</h3>
  {#if incoming}
    <div class="incoming">
      <p>Incoming: {incoming.filename} ({(incoming.size / 1024 / 1024).toFixed(1)} MB)</p>
      <button onclick={accept}>Accept</button>
      <button onclick={decline}>Decline</button>
    </div>
  {:else}
    <p class="hint">Waiting for files...</p>
  {/if}
</div>

<style>
  .file-receiver { display: flex; flex-direction: column; gap: 0.5rem; }
  h3 { margin: 0; font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); }
  .incoming { display: flex; flex-direction: column; gap: 0.5rem; padding: 0.5rem; border: 1px solid var(--accent-yellow); border-radius: 6px; background: var(--bg-primary); }
  .incoming p { margin: 0; font-size: 0.85rem; word-break: break-word; }
  .hint { margin: 0; color: var(--text-secondary); font-style: italic; font-size: 0.85rem; }
  button { width: 100%; }
</style>
