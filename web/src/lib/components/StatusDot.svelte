<script lang="ts">
  import type { LatencyLevel } from "../format";

  interface Props {
    level: LatencyLevel | "live" | "idle" | "warn" | "bad";
    pulse?: boolean;
  }

  let { level, pulse = false }: Props = $props();
</script>

<span class="dot {level}" class:pulse aria-hidden="true"></span>

<style>
  .dot {
    position: relative;
    display: inline-block;
    flex: none;
    width: 0.7rem;
    height: 0.7rem;
    border-radius: 50%;
    background: var(--c);
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--c) 22%, transparent);
  }

  .good,
  .unknown { --c: var(--ok); }
  .fair,
  .warn { --c: var(--warn); }
  .poor,
  .bad { --c: var(--bad); }
  .lost,
  .idle { --c: var(--idle); }
  .live { --c: var(--live); }

  .pulse::after {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: var(--c);
    animation: pulse-ring 1.6s var(--ease-out) infinite;
  }
</style>
