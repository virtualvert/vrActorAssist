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
  .soundpad-config { display: flex; flex-direction: column; gap: 0.5rem; padding: 0.5rem; border: 1px solid var(--border-color, #444); border-radius: 4px; }
  h3 { margin: 0; font-size: 0.9rem; }
  label { display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; }
  .toggle { font-size: 0.85rem; }
  input[type="text"] { flex: 1; }
</style>
