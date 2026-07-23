<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { appConfig } from "./stores";

  async function save() {
    if (!$appConfig) return;
    await invoke("save_config", { newConfig: $appConfig });
  }
</script>

{#if $appConfig}
  <div class="settings">
    <h3>Settings</h3>
    <label>Shared secret: <input type="password" bind:value={$appConfig.secret} onchange={save} /></label>
    <label>Theme:
      <select bind:value={$appConfig.theme} onchange={save}>
        <option value="dark">Dark</option>
        <option value="light">Light</option>
      </select>
    </label>
  </div>
{/if}

<style>
  .settings { display: flex; flex-direction: column; gap: 0.5rem; }
  .settings h3 { margin: 0; font-size: 1.1rem; }
  .settings label { display: flex; align-items: center; gap: 0.5rem; font-size: 0.9rem; }
  .settings input, .settings select { flex: 1; }
</style>
