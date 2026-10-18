<script lang="ts">
  import type { Snippet } from "svelte";
  import { X } from "@lucide/svelte";
  import Button from "./Button.svelte";

  interface Props {
    open: boolean;
    title: string;
    side?: "right" | "left";
    onclose: () => void;
    children: Snippet;
    footer?: Snippet;
  }

  let { open, title, side = "right", onclose, children, footer }: Props = $props();
  let dialog: HTMLDialogElement | undefined = $state();

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  });
</script>

<dialog
  bind:this={dialog}
  class="drawer {side}"
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
    <div class="body">{@render children()}</div>
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
