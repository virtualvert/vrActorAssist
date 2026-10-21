<script lang="ts">
  import { CircleCheck, CircleAlert, Info, MessageCircle, TriangleAlert } from "@lucide/svelte";
  import { onMount } from "svelte";
  import { app } from "../state.svelte";
  import { LAYER_EVENT } from "./Drawer.svelte";

  const ICONS = { success: CircleCheck, error: CircleAlert, warning: TriangleAlert, info: Info, chat: MessageCircle };

  // Drawers are modal dialogs in the browser's top layer, above any z-index. The toasts are a
  // popover so they can go there too; when a drawer opens they're shown again, since the newest
  // top-layer element is on top. Without popover support they stay as before.
  let box = $state<HTMLDivElement | undefined>();

  function place(raise = false) {
    if (!box || typeof box.showPopover !== "function") return;
    const open = box.matches(":popover-open");
    if (open && (raise || !app.toasts.length)) box.hidePopover();
    if (app.toasts.length && (raise || !open)) box.showPopover();
  }

  $effect(() => {
    void app.toasts.length;
    place();
  });

  onMount(() => {
    const raise = () => place(true);
    window.addEventListener(LAYER_EVENT, raise);
    return () => window.removeEventListener(LAYER_EVENT, raise);
  });
</script>

<div class="toasts" popover="manual" aria-live="polite" bind:this={box}>
  {#each app.toasts as t (t.id)}
    {@const Icon = ICONS[t.level]}
    <button class="toast {t.level}" type="button" onclick={() => app.dismissToast(t.id)}>
      <Icon size="1.25em" aria-hidden="true" />
      <span>{t.text}</span>
    </button>
  {/each}
</div>

<style>
  .toasts {
    position: fixed;
    inset: calc(var(--target) * 1.6 + 0.75rem) 1rem auto auto;
    margin: 0;
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    overflow: visible;
    z-index: 50;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0.6rem;
    pointer-events: none;
  }

  .toast {
    pointer-events: auto;
    display: flex;
    align-items: center;
    gap: 0.7rem;
    max-width: min(28rem, calc(100vw - 2rem));
    min-height: var(--target);
    padding: 0.6rem 1rem;
    border-radius: var(--radius);
    border: 1px solid var(--border-strong);
    background: var(--surface-glass);
    backdrop-filter: blur(14px) saturate(1.3);
    box-shadow: var(--shadow-pop);
    font-weight: 600;
    text-align: left;
    animation: rise-in var(--t) var(--ease-out);
  }

  .success { color: var(--ok); }
  .error { color: var(--bad); }
  .warning { color: var(--warn); }
  .info,
  .chat { color: var(--text); }

  .toast span {
    color: var(--text);
  }
</style>
