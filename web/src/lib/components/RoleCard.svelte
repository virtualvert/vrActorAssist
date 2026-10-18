<script lang="ts">
  import { Check } from "@lucide/svelte";
  import type { RoleInfo } from "../roles";

  interface Props {
    info: RoleInfo;
    selected: boolean;
    compact?: boolean;
    onselect: () => void;
  }

  let { info, selected, compact = false, onselect }: Props = $props();
</script>

<button
  type="button"
  class="role-card role-{info.id}"
  class:selected
  class:compact
  role="radio"
  aria-checked={selected}
  onclick={onselect}
>
  <span class="icon"><info.icon size="1.6em" aria-hidden="true" /></span>
  <span class="text">
    <span class="title">{info.label}</span>
    <span class="desc">{info.description}</span>
  </span>
  <span class="check" aria-hidden="true"><Check size="1em" strokeWidth={3} /></span>
</button>

<style>
  .role-card {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 1rem;
    width: 100%;
    padding: 1.4rem;
    text-align: left;
    border-radius: var(--radius-l);
    border: 1px solid var(--border);
    background:
      radial-gradient(120% 90% at 0% 0%, color-mix(in srgb, var(--role) 14%, transparent), transparent 60%),
      var(--surface-2);
    box-shadow: var(--shadow);
    transition:
      transform var(--t) var(--ease-out),
      border-color var(--t-fast),
      box-shadow var(--t) var(--ease-out);
  }

  .role-card:hover {
    transform: translateY(-2px);
    border-color: color-mix(in srgb, var(--role) 45%, transparent);
  }

  .role-card.selected {
    border-color: var(--role);
    box-shadow:
      0 0 0 1px var(--role),
      0 20px 50px -24px color-mix(in srgb, var(--role) 70%, transparent);
  }

  .compact {
    flex-direction: row;
    align-items: center;
    padding: 0.9rem 1rem;
    gap: 0.9rem;
  }

  .icon {
    display: grid;
    place-items: center;
    width: calc(var(--target) * 1.25);
    aspect-ratio: 1;
    flex: none;
    border-radius: var(--radius);
    color: var(--role);
    background: color-mix(in srgb, var(--role) 16%, transparent);
    border: 1px solid color-mix(in srgb, var(--role) 30%, transparent);
  }

  .compact .icon {
    width: var(--target);
  }

  .text {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding-right: 1.5rem;
  }

  .title {
    font-size: 1.2rem;
    font-weight: 750;
    letter-spacing: -0.01em;
  }

  .compact .title {
    font-size: 1.05rem;
  }

  .desc {
    font-size: 0.9rem;
    color: var(--text-2);
  }

  .compact .desc {
    font-size: 0.8125rem;
  }

  .check {
    position: absolute;
    top: 1rem;
    right: 1rem;
    display: grid;
    place-items: center;
    width: 1.6rem;
    height: 1.6rem;
    border-radius: 50%;
    background: var(--role);
    color: var(--surface);
    opacity: 0;
    transform: scale(0.5);
    transition:
      opacity var(--t-fast),
      transform var(--t) var(--ease-spring);
  }

  .compact .check {
    top: 50%;
    margin-top: -0.8rem;
  }

  .selected .check {
    opacity: 1;
    transform: scale(1);
  }
</style>
