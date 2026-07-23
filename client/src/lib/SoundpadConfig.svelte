<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { open } from "@tauri-apps/plugin-dialog";
  import { appConfig } from "./stores";

  async function save() {
    if (!$appConfig) return;
    await invoke("save_config", { newConfig: $appConfig });
  }

  async function browseSoundpad() {
    const path = await open({
      multiple: false,
      filters: [{ name: "Soundpad", extensions: ["exe"] }],
    });
    if (path && $appConfig) {
      $appConfig.soundpad_path = String(path);
      await invoke("save_config", { newConfig: $appConfig });
      appConfig.set({ ...$appConfig } as any);
    }
  }
</script>

{#if $appConfig}
  <div class="soundpad-config">
    <h3>Soundpad</h3>
    <label class="toggle">
      <input type="checkbox" bind:checked={$appConfig.soundpad_enabled} onchange={save} />
      Enabled
    </label>
    <div class="path-row">
      <input type="text" bind:value={$appConfig.soundpad_path} onchange={save} placeholder="Soundpad.exe" />
      <button onclick={browseSoundpad} class="browse-btn">Browse</button>
    </div>
  </div>
{/if}

<style>
  .soundpad-config { display: flex; flex-direction: column; gap: 0.5rem; }
  h3 { margin: 0; font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); }
  .toggle { display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; }
  .path-row { display: flex; gap: 0.4rem; }
  .path-row input { flex: 1; min-width: 0; }
  .browse-btn { font-size: 0.8rem; padding: 0.2rem 0.6rem; }
</style>
