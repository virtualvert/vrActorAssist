<script lang="ts" module>
  /** Sent after a drawer opens, so the toasts can move above it (Toasts.svelte). */
  export const LAYER_EVENT = "vrcas:layer";
</script>

<script lang="ts">
  import type { Snippet } from "svelte";
  import { X } from "@lucide/svelte";
  import Button from "./Button.svelte";

  interface Props {
    open: boolean;
    title: string;
    side?: "right" | "left";
    /** Room for a table: up to 60rem instead of 32rem. */
    wide?: boolean;
    onclose: () => void;
    children: Snippet;
    footer?: Snippet;
  }

  let { open, title, side = "right", wide = false, onclose, children, footer }: Props = $props();
  let dialog: HTMLDialogElement | undefined = $state();

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      window.dispatchEvent(new Event(LAYER_EVENT));
    }
    else if (!open && dialog.open) dialog.close();
  });
</script>

<dialog
  bind:this={dialog}
  class="drawer {side}"
  class:wide
  aria-label={title}
  onclose={onclose}
  onclick={(e) => {
    if (e.target === dialog) onclose();
  }}
>
  <div class="panel">
    <header>
      <h2>{title}</h2>
      <Button icon variant="ghost" aria-label="Close" onclick={onclose}><X size="1.3em" /></Button>
    </header>
    <div class="body">
      <!-- An error in a panel stays in the panel: without this, one throw stopped the whole
           page updating (stale cast checkmarks, drawers that wouldn't open) -->
      <svelte:boundary onerror={(error) => console.error(`${title}:`, error)}>
        {@render children()}
        {#snippet failed(error, reset)}
          <div class="failed" role="alert">
            <p><strong>This panel hit an error.</strong> The rest of the app keeps working.</p>
            <p class="detail">{error instanceof Error ? error.message : String(error)}</p>
            <Button size="s" variant="subtle" onclick={reset}>Try again</Button>
          </div>
        {/snippet}
      </svelte:boundary>
    </div>
    {#if footer}<footer>{@render footer()}</footer>{/if}
  </div>
</dialog>

<style>
  dialog {
    margin: 0;
    padding: 0;
    border: 0;
    background: transparent;
    max-width: none;
    max-height: none;
    width: 100%;
    height: 100%;
    color: inherit;
  }

  dialog::backdrop {
    background: rgb(4 6 10 / 0.5);
    backdrop-filter: blur(3px);
  }

  .panel {
    position: absolute;
    top: 0;
    bottom: 0;
    right: 0;
    display: flex;
    flex-direction: column;
    width: min(32rem, 100%);
    background: var(--surface);
    border-left: 1px solid var(--border);
    box-shadow: var(--shadow-pop);
    animation: slide-in var(--t) var(--ease-out);
  }

  .wide .panel {
    width: min(60rem, 100%);
  }

  .left .panel {
    right: auto;
    left: 0;
    border-left: 0;
    border-right: 1px solid var(--border);
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 1rem 1rem 1rem var(--pad);
    border-bottom: 1px solid var(--border);
  }

  h2 {
    font-size: 1.25rem;
  }

  .body {
    flex: 1;
    overflow-y: auto;
    padding: var(--pad);
  }

  .failed {
    display: grid;
    gap: 0.6rem;
    justify-items: start;
    padding: 0.65rem 0.85rem;
    border-radius: var(--radius-s);
    color: var(--bad);
    background: color-mix(in srgb, var(--bad) 10%, transparent);
    font-size: 0.875rem;
  }

  .failed .detail {
    font-family: var(--font-mono);
    font-size: 0.8125rem;
    overflow-wrap: anywhere;
  }

  footer {
    padding: 1rem var(--pad);
    border-top: 1px solid var(--border);
  }

  @keyframes slide-in {
    from {
      transform: translateX(2rem);
      opacity: 0;
    }
  }
</style>
