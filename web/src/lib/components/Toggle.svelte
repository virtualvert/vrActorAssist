<script lang="ts">
  interface Props {
    checked: boolean;
    label: string;
    description?: string;
    disabled?: boolean;
    onchange: (value: boolean) => void;
  }

  let { checked, label, description, disabled = false, onchange }: Props = $props();
</script>

<button
  type="button"
  class="toggle"
  role="switch"
  aria-checked={checked}
  {disabled}
  onclick={() => onchange(!checked)}
>
  <span class="text">
    <span class="label">{label}</span>
    {#if description}<span class="desc">{description}</span>{/if}
  </span>
  <span class="track" class:on={checked} aria-hidden="true"><span class="thumb"></span></span>
</button>

<style>
  .toggle {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    width: 100%;
    min-height: var(--target);
    padding: 0.5rem 0.25rem;
    background: none;
    border: 0;
    text-align: left;
    border-radius: var(--radius);
  }

  .toggle:disabled {
    opacity: 0.5;
  }

  .text {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }

  .label {
    font-weight: 600;
  }

  .desc {
    font-size: 0.8125rem;
    color: var(--text-3);
  }

  .track {
    position: relative;
    flex: none;
    width: calc(var(--target) * 1.15);
    height: calc(var(--target) * 0.62);
    border-radius: 999px;
    background: var(--surface-3);
    border: 1px solid var(--border-strong);
    transition: background-color var(--t) var(--ease-out), border-color var(--t);
  }

  .track.on {
    background: color-mix(in srgb, var(--accent) 85%, transparent);
    border-color: transparent;
  }

  .thumb {
    position: absolute;
    top: 50%;
    left: 0.2rem;
    width: calc(var(--target) * 0.46);
    aspect-ratio: 1;
    border-radius: 50%;
    background: #fff;
    box-shadow: 0 2px 6px rgb(0 0 0 / 0.35);
    transform: translateY(-50%);
    transition: left var(--t) var(--ease-spring);
  }

  .on .thumb {
    left: calc(100% - var(--target) * 0.46 - 0.2rem);
  }
</style>
