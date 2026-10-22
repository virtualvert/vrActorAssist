<script lang="ts">
  // An actor's delay (spec §8.2.3): their scheduled cues start this much later (negative: earlier).
  // The relay stores it, so it survives reconnects of either side.
  import { app } from "../state.svelte";
  import { DELAY_LIMIT_MS, parseDelay } from "../timing";
  import Button from "./Button.svelte";

  interface Props {
    id: string;
    name: string;
    delayMs: number;
    /** Called after Set / Reset (e.g. to close a row editor). */
    ondone?: () => void;
  }

  let { id, name, delayMs, ondone }: Props = $props();
  let text = $state("");
  let touched = $state(false);
  const shown = $derived(touched ? text : String(delayMs));
  const parsed = $derived(parseDelay(shown));

  async function save(ms: number) {
    if (await app.call({ call: "setDelay", args: { id, ms } })) {
      touched = false;
      ondone?.();
    }
  }

  function submit(event: SubmitEvent) {
    event.preventDefault();
    if (parsed !== null) void save(parsed);
  }
</script>

<form class="delay" onsubmit={submit} aria-label="{name}'s delay">
  <label class="field">
    <span>Delay for {name}</span>
    <span class="with-unit">
      <input
        class="input mono"
        inputmode="numeric"
        aria-label="{name}'s delay in milliseconds"
        value={shown}
        aria-invalid={parsed === null}
        oninput={(e) => {
          text = e.currentTarget.value;
          touched = true;
        }}
      />
      <span class="unit faint">ms</span>
    </span>
  </label>
  <Button type="submit" size="s" variant="primary" disabled={parsed === null || parsed === delayMs}>Set</Button>
  {#if delayMs !== 0}
    <Button size="s" variant="ghost" onclick={() => save(0)}>Reset to 0</Button>
  {/if}
  <small class="faint">
    {parsed === null
      ? `Whole milliseconds, −${DELAY_LIMIT_MS} to ${DELAY_LIMIT_MS}.`
      : parsed === 0
        ? `${name} starts together with everyone.`
        : `GO and Play in 3s start ${Math.abs(parsed)} ms ${parsed > 0 ? "later" : "earlier"} for ${name}. Tune it by ear.`}
  </small>
</form>

<style>
  .delay {
    display: flex;
    flex-wrap: wrap;
    align-items: flex-end;
    gap: 0.5rem;
  }

  .field {
    flex: 0 1 9rem;
  }

  .with-unit {
    position: relative;
    display: block;
  }

  .with-unit input {
    padding-right: 2.4rem;
  }

  .unit {
    position: absolute;
    right: 0.8rem;
    top: 50%;
    transform: translateY(-50%);
    font-size: 0.8125rem;
    pointer-events: none;
  }

  input[aria-invalid="true"] {
    border-color: var(--bad);
  }

  small {
    flex-basis: 100%;
    font-size: 0.8125rem;
  }
</style>
