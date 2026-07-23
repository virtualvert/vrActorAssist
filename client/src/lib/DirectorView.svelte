<script lang="ts">
  import ConnectionPanel from "./ConnectionPanel.svelte";
  import StatusBar from "./StatusBar.svelte";
  import LogPanel from "./LogPanel.svelte";
  import ActorList from "./ActorList.svelte";
  import CueControls from "./CueControls.svelte";
  import FileSender from "./FileSender.svelte";
  import Settings from "./Settings.svelte";
</script>

<div class="director-view">
  <header class="top-bar">
    <div class="conn">
      <ConnectionPanel />
    </div>
    <StatusBar mode="director" />
  </header>
  <div class="main-area">
    <aside class="left-panel">
      <section class="panel-section">
        <ActorList />
      </section>
      <section class="panel-section">
        <CueControls />
      </section>
      <section class="panel-section">
        <FileSender />
      </section>
      <section class="panel-section">
        <Settings />
      </section>
    </aside>
    <section class="log-area">
      <LogPanel />
    </section>
  </div>
</div>

<style>
  .director-view {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    padding: 0.75rem;
    gap: 0.75rem;
    box-sizing: border-box;
  }

  .top-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.5rem 0.75rem;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
  }

  .conn {
    flex: 1;
    min-width: 0;
    display: flex;
  }

  .conn :global(.connection-panel) {
    flex: 1;
    min-width: 0;
  }

  .main-area {
    flex: 1;
    display: grid;
    grid-template-columns: 250px minmax(0, 1fr);
    gap: 0.75rem;
    min-height: 0;
  }

  .left-panel {
    display: flex;
    flex-direction: column;
    min-height: 0;
    overflow-y: auto;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
  }

  .panel-section {
    padding: 0.75rem;
  }

  .panel-section + .panel-section {
    border-top: 1px solid var(--border);
  }

  .log-area {
    display: flex;
    flex-direction: column;
    min-height: 0;
    min-width: 0;
  }
</style>
