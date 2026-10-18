<script lang="ts">
  import { Plug, Settings, WifiOff } from "@lucide/svelte";
  import { app } from "../state.svelte";
  import Button from "./Button.svelte";

  const data = $derived(app.state!);
  const show = $derived(data.connection.status === "disconnected" || data.connection.status === "error");
</script>

{#if show}
  <div class="banner" class:error={data.connection.status === "error"} role="status">
    <WifiOff size="1.3em" aria-hidden="true" />
    <div class="text">
      <strong>{data.connection.status === "error" ? "Can't connect" : "You're offline"}</strong>
      <span>{data.connection.detail}</span>
    </div>
    <div class="actions">
      {#if data.profile.serverUrl}
        <Button variant="primary" onclick={() => app.call({ call: "connect" })}><Plug size="1.1em" /> Connect</Button>
      {/if}
      <Button variant="ghost" onclick={() => (app.settingsOpen = true)}><Settings size="1.1em" /> Connection</Button>
    </div>
  </div>
{/if}

<style>
  .banner {
    display: flex;
    align-items: center;
    gap: 0.9rem;
    flex-wrap: wrap;
    padding: 0.8rem 1rem;
    border-radius: var(--radius-l);
    background: color-mix(in srgb, var(--idle) 12%, var(--surface));
    border: 1px solid var(--border-strong);
    animation: rise-in var(--t) var(--ease-out);
  }

  .banner.error {
    background: color-mix(in srgb, var(--bad) 10%, var(--surface));
    border-color: color-mix(in srgb, var(--bad) 40%, transparent);
    color: var(--bad);
  }

  .text {
    display: flex;
    flex-direction: column;
    flex: 1;
    min-width: 12rem;
    color: var(--text);
  }

  .text span {
    color: var(--text-2);
    font-size: 0.875rem;
  }

  .actions {
    display: flex;
    gap: 0.5rem;
  }
</style>
