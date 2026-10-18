<script lang="ts">
  import { CircleCheck, CircleAlert, Info, MessageCircle, TriangleAlert } from "@lucide/svelte";
  import { app } from "../state.svelte";

  const ICONS = { success: CircleCheck, error: CircleAlert, warning: TriangleAlert, info: Info, chat: MessageCircle };
</script>

<div class="toasts" aria-live="polite">
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
    top: calc(var(--target) * 1.6 + 0.75rem);
    right: 1rem;
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
