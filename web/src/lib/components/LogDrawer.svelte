<script lang="ts">
  import { CircleAlert, CircleCheck, Info, MessageCircle, Send, TriangleAlert } from "@lucide/svelte";
  import { tick } from "svelte";
  import { clockTime } from "../format";
  import { app } from "../state.svelte";
  import Button from "./Button.svelte";
  import Drawer from "./Drawer.svelte";

  const ICONS = { success: CircleCheck, error: CircleAlert, warning: TriangleAlert, info: Info, chat: MessageCircle };

  let text = $state("");
  let list: HTMLOListElement | undefined = $state();
  const canChat = $derived(app.state?.connection.status === "connected");

  // Keep the newest entry in view while the drawer is open.
  $effect(() => {
    void app.logs.length;
    if (!app.logOpen) return;
    void tick().then(() => list?.lastElementChild?.scrollIntoView({ block: "end" }));
  });

  async function send(event: SubmitEvent) {
    event.preventDefault();
    const message = text.trim();
    if (!message) return;
    text = "";
    await app.call({ call: "sendChat", args: { text: message } });
  }
</script>

<Drawer open={app.logOpen} title="Activity & chat" onclose={() => app.openLog(false)}>
  {#if app.logs.length === 0}
    <p class="faint">Nothing yet. Connection events, cues and chat show up here.</p>
  {:else}
    <ol bind:this={list} class="log">
      {#each app.logs as entry (entry.id)}
        {@const Icon = ICONS[entry.level]}
        <li class={entry.level}>
          <Icon size="1.1em" aria-hidden="true" />
          <div>
            <div class="meta">
              {#if entry.from}<strong>{entry.from}</strong>{/if}
              <time class="mono">{clockTime(entry.ts)}</time>
            </div>
            <p>{entry.text}</p>
          </div>
        </li>
      {/each}
    </ol>
  {/if}

  {#snippet footer()}
    <form class="composer" onsubmit={send}>
      <input class="input" bind:value={text} placeholder={canChat ? "Message everyone" : "Connect to chat"} disabled={!canChat} aria-label="Chat message" />
      <Button type="submit" icon variant="primary" aria-label="Send" disabled={!canChat || !text.trim()}><Send size="1.15em" /></Button>
    </form>
  {/snippet}
</Drawer>

<style>
  .log {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  li {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.7rem;
    align-items: start;
    padding: 0.6rem 0.75rem;
    border-radius: var(--radius);
    color: var(--text-3);
  }

  li :global(svg) {
    margin-top: 0.15rem;
  }

  li.success { color: var(--ok); }
  li.warning { color: var(--warn); }
  li.error { color: var(--bad); background: color-mix(in srgb, var(--bad) 8%, transparent); }
  li.chat { color: var(--accent); background: var(--surface-2); }

  .meta {
    display: flex;
    gap: 0.6rem;
    align-items: baseline;
    font-size: 0.75rem;
    color: var(--text-3);
  }

  .meta strong {
    color: var(--text);
    font-size: 0.875rem;
  }

  li p {
    color: var(--text);
    overflow-wrap: anywhere;
  }

  .composer {
    display: flex;
    gap: 0.6rem;
  }
</style>
