<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { appConfig } from "./stores";

  async function save() {
    if (!$appConfig) return;
    await invoke("save_config", { newConfig: $appConfig });
  }
</script>

{#if $appConfig}
  <div class="soundpad-config">
    <h3>Soundpad</h3>
    <label class="toggle">
      <input type="checkbox" bind:checked={$appConfig.soundpad_enabled} onchange={save} />
      Enabled
    </label>
    <label>Path: <input type="text" bind:value={$appConfig.soundpad_path} onchange={save} /></label>
  </div>
{/if}

<style>
  .soundpad-config { display: flex; flex-direction: column; gap: 0.5rem; }
  h3 { margin: 0; font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); }
  label { display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; }
  input[type="text"] { flex: 1; min-width: 0; }
</style>
