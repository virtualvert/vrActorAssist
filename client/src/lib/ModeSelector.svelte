<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { appConfig } from "./stores";

  let { onSelect }: { onSelect: (mode: "director" | "actor") => void } = $props();

  let rememberChoice = $state(false);

  async function selectMode(mode: "director" | "actor") {
    if ($appConfig) {
      const cfg = { ...$appConfig, mode, remember_mode: rememberChoice };
      await invoke("save_config", { newConfig: cfg });
      appConfig.set(cfg as any);
    }
    onSelect(mode);
  }
</script>

<div class="mode-selector">
  <h1>vrActorAssist</h1>
  <p class="subtitle">Select your role</p>
  <div class="buttons">
    <button onclick={() => selectMode("director")} class="mode-btn director">
      <span class="label">Director</span>
      <span class="desc">Send cues, manage actors, route audio files</span>
    </button>
    <button onclick={() => selectMode("actor")} class="mode-btn actor">
      <span class="label">Actor</span>
      <span class="desc">Receive cues, play sounds, VRChat OSC</span>
    </button>
  </div>
  <label class="remember">
    <input type="checkbox" bind:checked={rememberChoice} />
    Remember my choice
  </label>
</div>

<style>
  .mode-selector { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1.25rem; padding: 3rem 1rem; }
  .mode-selector h1 { margin: 0; font-size: 2rem; color: var(--accent); }
  .subtitle { margin: 0; color: var(--text-secondary); }
  .buttons { display: flex; gap: 1.5rem; flex-wrap: wrap; justify-content: center; }
  .mode-btn { display: flex; flex-direction: column; gap: 0.4rem; padding: 1.5rem 2rem; border-radius: 10px; cursor: pointer; background: var(--bg-secondary); border: 1px solid var(--border); min-width: 220px; text-align: left; transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease; }
  .mode-btn:hover:not(:disabled) { background: var(--bg-secondary); border-color: var(--accent); box-shadow: var(--shadow); transform: translateY(-2px); }
  .mode-btn .label { font-size: 1.2rem; font-weight: 600; color: var(--text-primary); }
  .mode-btn .desc { font-size: 0.85rem; color: var(--text-secondary); }
  .remember { display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; color: var(--text-secondary); cursor: pointer; }
</style>
