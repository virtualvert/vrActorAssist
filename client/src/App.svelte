<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";
  import ModeSelector from "./lib/ModeSelector.svelte";
  import DirectorView from "./lib/DirectorView.svelte";
  import ActorView from "./lib/ActorView.svelte";
  import UpdateNotifier from "./lib/UpdateNotifier.svelte";
  import { appConfig } from "./lib/stores";

  let mode = $state<"director" | "actor" | null>(null);

  onMount(async () => {
    const cfg = await invoke<any>("get_config");
    appConfig.set(cfg);
    if (cfg.remember_mode && (cfg.mode === "director" || cfg.mode === "actor")) {
      mode = cfg.mode;
    }
  });
</script>

<main>
  <UpdateNotifier />
  {#if !mode}
    <ModeSelector onSelect={(m) => (mode = m)} />
  {:else if mode === "director"}
    <DirectorView />
  {:else}
    <ActorView />
  {/if}
</main>
