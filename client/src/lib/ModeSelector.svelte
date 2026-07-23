<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { appConfig } from "./stores";

  let { onSelect }: { onSelect: (mode: "director" | "actor") => void } = $props();

  let rememberChoice = $state(false);

  async function selectMode(mode: "director" | "actor") {
    if (rememberChoice && $appConfig) {
      const cfg = { ...$appConfig, mode, remember_mode: true };
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
  .mode-selector { display: flex; flex-direction: column; align-items: center; gap: 1rem; padding: 3rem 1rem; }
  .buttons { display: flex; gap: 1.5rem; }
  .mode-btn { display: flex; flex-direction: column; gap: 0.4rem; padding: 1.5rem 2rem; border-radius: 8px; cursor: pointer; }
  .label { font-size: 1.2rem; font-weight: 600; }
  .desc { font-size: 0.85rem; opacity: 0.75; }
</style>
