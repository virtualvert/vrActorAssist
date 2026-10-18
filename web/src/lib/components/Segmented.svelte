<script lang="ts" generics="T extends string">
  import type { Component } from "svelte";

  interface Option {
    value: T;
    label: string;
    icon?: Component;
  }

  interface Props {
    options: Option[];
    value: T;
    label: string;
    onchange: (value: T) => void;
  }

  let { options, value, label, onchange }: Props = $props();
</script>

<div class="seg" role="radiogroup" aria-label={label}>
  {#each options as opt (opt.value)}
    <button
      type="button"
      role="radio"
      aria-checked={opt.value === value}
      class:active={opt.value === value}
      onclick={() => onchange(opt.value)}
    >
      {#if opt.icon}<opt.icon size="1.1em" aria-hidden="true" />{/if}
      <span>{opt.label}</span>
    </button>
  {/each}
</div>

<style>
  .seg {
    display: flex;
    gap: 0.25rem;
    padding: 0.25rem;
    border-radius: calc(var(--radius) + 0.25rem);
    background: var(--surface-2);
    border: 1px solid var(--border);
  }

  button {
    flex: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.45rem;
    min-height: calc(var(--target) * 0.9);
    padding: 0 0.8rem;
    border: 0;
    border-radius: var(--radius);
    background: transparent;
    color: var(--text-2);
    font-weight: 600;
    transition: background-color var(--t-fast), color var(--t-fast), box-shadow var(--t);
  }

  button:hover {
    color: var(--text);
  }

  button.active {
    background: var(--surface);
    color: var(--text);
    box-shadow: 0 1px 2px rgb(0 0 0 / 0.2), 0 0 0 1px var(--border-strong);
  }
</style>
