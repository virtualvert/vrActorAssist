<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { open } from "@tauri-apps/plugin-dialog";

  interface ActorInfo { name: string; approved: boolean; }

  let selectedTarget = $state("");
  let actors = $state<ActorInfo[]>([]);
  let sending = $state(false);

  async function refreshActors() {
    actors = (await invoke<ActorInfo[]>("list_actors")).filter((a) => a.approved);
  }

  async function pickAndSend() {
    const paths = await open({ multiple: true, filters: [{ name: "Audio", extensions: ["wav", "mp3", "ogg"] }] });
    if (!paths) return;
    const list = Array.isArray(paths) ? paths : [paths];
    sending = true;
    try {
      for (const path of list) {
        await invoke("send_file", { target: selectedTarget, path });
      }
    } finally {
      sending = false;
    }
  }
</script>

<div class="file-sender">
  <h3>Send Files</h3>
  <select bind:value={selectedTarget} onfocus={refreshActors}>
    {#each actors as actor}
      <option value={actor.name}>{actor.name}</option>
    {/each}
  </select>
  <button onclick={pickAndSend} disabled={!selectedTarget || sending}>
    {sending ? "Sending..." : "Choose Files..."}
  </button>
</div>

<style>
  .file-sender { display: flex; flex-direction: column; gap: 0.5rem; }
  h3 { margin: 0; font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); }
  select, button { width: 100%; box-sizing: border-box; }
</style>
