<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";

  interface UpdateInfo { available: boolean; version: string; notes: string; portable: boolean; }

  let update: UpdateInfo | null = $state(null);
  let installing = $state(false);

  onMount(async () => {
    try {
      const info = await invoke<UpdateInfo>("check_for_update");
      if (info.available) update = info;
    } catch {
      // Silently ignore — e.g. offline at startup. User can retry via Settings later.
    }
  });

  async function install() {
    installing = true;
    try {
      await invoke("install_update");
    } finally {
      installing = false;
    }
  }

  function openReleasePage() {
    window.open("https://github.com/virtualvert/vrActorAssist/releases/latest", "_blank");
  }
</script>

{#if update}
  <div class="update-banner">
    <span>Version {update.version} is available.</span>
    {#if update.portable}
      <button onclick={openReleasePage}>Download</button>
    {:else}
      <button onclick={install} disabled={installing}>{installing ? "Installing..." : "Install & Restart"}</button>
    {/if}
  </div>
{/if}

<style>
  .update-banner { display: flex; gap: 1rem; align-items: center; justify-content: center; padding: 0.5rem 1rem; background: var(--bg-tertiary); color: var(--text-primary); border-bottom: 1px solid var(--border); font-size: 0.9rem; }
</style>