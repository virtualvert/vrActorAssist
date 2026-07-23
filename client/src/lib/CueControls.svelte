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
  </div>
  <div class="countdown-group">
    <button onclick={playInCountdown} class="cue countdown" disabled={countdownTimer !== null}>
      Play in {countdownSeconds}s {countdownLabel}
    </button>
    <select bind:value={countdownSeconds}>
      <option value={3}>3s</option>
      <option value={5}>5s</option>
      <option value={10}>10s</option>
    </select>
  </div>
</div>

<style>
  .cue-controls { display: flex; flex-direction: column; gap: 0.6rem; }
  .cue-buttons { display: flex; gap: 0.5rem; }
  .cue { font-size: 1rem; font-weight: 600; padding: 0.6rem 1rem; border-radius: 8px; border: none; cursor: pointer; flex: 1; }
  .cue.go { background: var(--accent-green); color: #0b1f13; }
  .cue.stop { background: var(--accent-red); color: #fff; }
  .cue.go:hover:not(:disabled) { background: var(--accent-green); }
  .cue.stop:hover:not(:disabled) { background: var(--accent-red); }
  .countdown-group { display: flex; gap: 0.5rem; align-items: center; }
  .cue.countdown { flex: 1; background: var(--bg-tertiary); color: var(--text-primary); border: 1px solid var(--border); font-weight: 500; }
  .countdown-group select { width: 4.5rem; }
</style>
