<script lang="ts">
  import { Plug, Unplug } from "@lucide/svelte";
  import { app } from "../state.svelte";
  import Button from "./Button.svelte";

  interface Props {
    /** Called after a successful Connect click (onboarding uses it to finish). */
    ondone?: () => void;
    submitLabel?: string;
  }

  let { ondone, submitLabel = "Connect" }: Props = $props();

  const data = $derived(app.state!);
  const isDirector = $derived(data.role === "director");
  const busy = $derived(["connecting", "pending", "connected"].includes(data.connection.status));

  // Seed the inputs from the saved profile once; after that they belong to the user.
  let name = $state(app.state?.profile.name ?? "");
  let serverUrl = $state(app.state?.profile.serverUrl ?? "");
  let secret = $state("");

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    await app.call({ call: "setProfile", args: { name, serverUrl, ...(secret ? { secret } : {}) } });
    secret = "";
    await app.call({ call: "connect" });
    ondone?.();
  }
</script>

<form class="stack" onsubmit={submit}>
  <label class="field">
    <span>Your name</span>
    <input class="input" bind:value={name} autocomplete="nickname" placeholder="How others see you" required />
  </label>
  <label class="field">
    <span>Relay server</span>
    <input class="input mono" bind:value={serverUrl} placeholder="wss://relay.example.com/ws" spellcheck="false" required />
    <small>Ask the server owner. ws://, wss://, http(s):// or host:port all work.</small>
  </label>
  {#if isDirector}
    <label class="field">
      <span>Director secret</span>
      <input
        class="input"
        type="password"
        bind:value={secret}
        autocomplete="current-password"
        placeholder={data.profile.hasSecret ? "Saved — type to replace" : "From the server owner"}
      />
    </label>
  {/if}
  <div class="row actions">
    <Button type="submit" variant="primary" size="l" disabled={data.connection.status === "connecting"}>
      <Plug size="1.2em" />
      {busy ? "Save & reconnect" : submitLabel}
    </Button>
    {#if busy}
      <Button type="button" size="l" variant="ghost" onclick={() => app.call({ call: "disconnect" })}>
        <Unplug size="1.2em" /> Disconnect
      </Button>
    {/if}
  </div>
</form>

<style>
  .actions {
    flex-wrap: wrap;
    margin-top: 0.25rem;
  }
</style>
