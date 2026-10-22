<script lang="ts">
  import type { Snippet } from "svelte";
  import type { HTMLButtonAttributes } from "svelte/elements";

  interface Props extends HTMLButtonAttributes {
    variant?: "subtle" | "ghost" | "primary" | "go" | "stop" | "warn" | "danger";
    size?: "s" | "m" | "l" | "xl";
    block?: boolean;
    icon?: boolean;
    children: Snippet;
  }

  // type defaults to "button": inside a <form> a plain <button> submits it as well as running its onclick
  // (laptop run, M3: "Reset to 0" saved the old delay again, "Arm #N" also played it). Submit buttons say so.
  let { variant = "subtle", size = "m", block = false, icon = false, type = "button", children, class: cls = "", ...rest }: Props = $props();
</script>

<button {type} class="btn {variant} {size} {cls}" class:block class:icon {...rest}>
  {@render children()}
</button>

<style>
  .btn {
    position: relative;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.55rem;
    min-height: var(--target);
    padding: 0 1.1rem;
    border-radius: var(--radius);
    border: 1px solid transparent;
    font-weight: 650;
    line-height: 1;
    letter-spacing: 0.005em;
    white-space: nowrap;
    user-select: none;
    transition:
      transform var(--t-fast) var(--ease-out),
      box-shadow var(--t) var(--ease-out),
      background-color var(--t-fast),
      border-color var(--t-fast),
      opacity var(--t-fast),
      filter var(--t-fast);
  }

  .btn:not(:disabled):active {
    transform: scale(0.97);
  }

  .btn:disabled {
    opacity: 0.42;
    filter: saturate(0.4);
  }

  .block {
    width: 100%;
  }

  .s {
    min-height: calc(var(--target) * 0.8);
    padding: 0 0.85rem;
    font-size: 0.875rem;
    border-radius: var(--radius-s);
  }


  .l {
    min-height: calc(var(--target) * 1.3);
    padding: 0 1.5rem;
    font-size: 1.125rem;
    border-radius: var(--radius-l);
  }

  .xl {
    min-height: calc(var(--target) * 1.9);
    padding: 0 2rem;
    font-size: 1.5rem;
    font-weight: 750;
    letter-spacing: 0.02em;
    border-radius: var(--radius-xl);
  }

  /* Square icon buttons: no text padding, so the icon keeps its size at every scale. */
  .btn.icon {
    padding: 0;
    width: var(--target);
    flex: none;
  }

  .btn.s.icon {
    width: calc(var(--target) * 0.8);
  }

  .btn :global(svg) {
    flex: none;
  }

  .subtle {
    background: var(--surface-3);
    border-color: var(--border);
  }

  .subtle:not(:disabled):hover {
    border-color: var(--border-strong);
    background: color-mix(in srgb, var(--surface-3) 80%, var(--text) 6%);
  }

  .ghost {
    background: transparent;
    color: var(--text-2);
  }

  .ghost:not(:disabled):hover {
    background: var(--surface-3);
    color: var(--text);
  }

  .primary,
  .go,
  .stop,
  .warn {
    color: var(--on-strong);
    border-color: rgb(255 255 255 / 0.12);
  }

  .primary {
    background: linear-gradient(135deg, var(--accent), color-mix(in srgb, var(--accent) 55%, var(--accent-2)));
    box-shadow: 0 10px 30px -12px color-mix(in srgb, var(--accent) 70%, transparent);
  }

  .go {
    background: linear-gradient(160deg, var(--go), var(--go-deep));
    box-shadow:
      0 1px 0 rgb(255 255 255 / 0.25) inset,
      0 14px 40px -14px color-mix(in srgb, var(--go) 80%, transparent);
  }

  .stop {
    background: linear-gradient(160deg, var(--stop), var(--stop-deep));
    box-shadow:
      0 1px 0 rgb(255 255 255 / 0.2) inset,
      0 14px 40px -14px color-mix(in srgb, var(--stop) 80%, transparent);
  }

  .warn {
    background: linear-gradient(160deg, var(--warn), color-mix(in srgb, var(--warn) 70%, #7c2d12));
    color: #1a1204;
    box-shadow: 0 14px 40px -14px color-mix(in srgb, var(--warn) 70%, transparent);
  }

  .primary:not(:disabled):hover,
  .go:not(:disabled):hover,
  .stop:not(:disabled):hover,
  .warn:not(:disabled):hover {
    filter: brightness(1.08) saturate(1.05);
  }

  .danger {
    background: transparent;
    color: var(--bad);
    border-color: color-mix(in srgb, var(--bad) 40%, transparent);
  }

  .danger:not(:disabled):hover {
    background: color-mix(in srgb, var(--bad) 12%, transparent);
  }
</style>
