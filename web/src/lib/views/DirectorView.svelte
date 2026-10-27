<script lang="ts">
  import ConnectBanner from "../components/ConnectBanner.svelte";
  import NodeGraph from "../graph/NodeGraph.svelte";
  import type { AppState } from "../protocol";
  import { app } from "../state.svelte";
  import CastPanel from "./CastPanel.svelte";
  import CueDeck from "./CueDeck.svelte";

  interface Props {
    data: AppState;
  }

  let { data }: Props = $props();

  const online = $derived(data.peers.filter((p) => !p.self && p.status === "online").length);

  function toggleTarget(id: string) {
    const ids = data.targets.includes(id) ? data.targets.filter((t) => t !== id) : [...data.targets, id];
    void app.call({ call: "setTargets", args: { ids } });
  }
</script>

<div class="wrap">
  <div class="view">
    <div class="banner-slot"><ConnectBanner /></div>
    <section class="stage card">
      <header>
        <div>
          <h2>Stage</h2>
          <span class="faint">{online} online{data.pending.length ? ` · ${data.pending.length} waiting` : ""}</span>
        </div>
        <span class="faint hint">Click an actor to include or leave them out of cues</span>
      </header>
      <div class="graph-slot">
        <NodeGraph {data} ontoggle={toggleTarget} />
      </div>
    </section>
    <div class="deck-slot"><CueDeck {data} /></div>
    <div class="cast-slot"><CastPanel {data} /></div>
  </div>
</div>

<style>
  .wrap {
    container-type: inline-size;
    height: 100%;
  }

  .view {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(19rem, 25rem);
    grid-template-rows: auto minmax(0, 1fr) auto;
    grid-template-areas:
      "banner banner"
      "stage cast"
      "deck cast";
    gap: var(--gap);
    height: 100%;
    padding: var(--gap);
  }

  .stage {
    grid-area: stage;
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow: hidden;
  }

  .stage header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    padding: 1rem var(--pad) 0;
  }

  .stage h2 {
    font-size: 1.25rem;
  }

  .stage header .faint {
    font-size: 0.8125rem;
  }

  .graph-slot {
    flex: 1;
    min-height: 0;
  }

  .deck-slot {
    grid-area: deck;
  }

  .cast-slot {
    grid-area: cast;
    min-height: 0;
    display: flex;
  }

  .cast-slot > :global(*) {
    flex: 1;
  }

  @container (max-width: 60rem) {
    .view {
      grid-template-columns: minmax(0, 1fr);
      grid-template-rows: auto minmax(20rem, 1fr) auto auto;
      grid-template-areas:
        "banner"
        "stage"
        "cast"
        "deck";
      height: auto;
      min-height: 100%;
    }

    .deck-slot {
      position: sticky;
      bottom: var(--gap);
      z-index: 3;
    }

    .hint {
      display: none;
    }
  }
</style>
