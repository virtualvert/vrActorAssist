<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";

  interface ActorInfo { name: string; approved: boolean; enabled: boolean; }

  let countdownSeconds = $state(3);
  let countdownTimer: ReturnType<typeof setTimeout> | null = $state(null);
  let countdownLabel = $state("");

  async function enabledTargets(): Promise<string[]> {
    const actors = await invoke<ActorInfo[]>("list_actors");
    return actors.filter((a) => a.approved && a.enabled).map((a) => a.name);
  }

  async function sendGo() {
    const targets = await enabledTargets();
    if (targets.length === 0) return;
    await invoke("send_command", { command: "*go", targets });
  }

  async function sendStop() {
    if (countdownTimer) { clearTimeout(countdownTimer); countdownTimer = null; countdownLabel = ""; }
    const targets = await enabledTargets();
    if (targets.length === 0) return;
    await invoke("send_command", { command: "*stop", targets });
  }

  function playInCountdown() {
    let remaining = countdownSeconds;
    countdownLabel = `${remaining}...`;
    countdownTimer = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(countdownTimer!);
        countdownTimer = null;
        countdownLabel = "";
        sendGo();
      } else {
        countdownLabel = `${remaining}...`;
      }
    }, 1000) as unknown as ReturnType<typeof setTimeout>;
  }
</script>

<div class="cue-controls">
  <div class="cue-buttons">
    <button onclick={sendGo} class="cue go">Go</button>
    <button onclick={sendStop} class="cue stop">Stop</button>
    <div class="countdown-group">
      <button onclick={playInCountdown} class="cue countdown">
        Play in {countdownSeconds}s {countdownLabel}
      </button>
      <select bind:value={countdownSeconds}>
        <option value={3}>3s</option>
        <option value={5}>5s</option>
        <option value={10}>10s</option>
      </select>
    </div>
  </div>
</div>

<style>
  .cue-buttons { display: flex; gap: 0.75rem; align-items: center; flex-wrap: wrap; }
  .cue { font-size: 1.1rem; padding: 0.75rem 1.5rem; border-radius: 8px; border: none; cursor: pointer; }
  .cue.go { background: #2ecc71; }
  .cue.stop { background: #e74c3c; }
  .countdown-group { display: flex; gap: 0.25rem; align-items: center; }
</style>
