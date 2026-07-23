<script lang="ts">
  import ConnectionPanel from "./ConnectionPanel.svelte";
  import StatusBar from "./StatusBar.svelte";
  import LogPanel from "./LogPanel.svelte";
  import FileReceiver from "./FileReceiver.svelte";
  import OscConfig from "./OscConfig.svelte";
  import SoundpadConfig from "./SoundpadConfig.svelte";
</script>

<div class="actor-view">
  <header class="top-bar">
    <div class="conn">
      <ConnectionPanel />
    </div>
    <StatusBar mode="actor" />
  </header>
  <div class="main-area">
    <aside class="left-panel">
      <section class="panel-section">
        <SoundpadConfig />
      </section>
      <section class="panel-section">
        <OscConfig />
      </section>
      <section class="panel-section">
        <FileReceiver />
      </section>
    </aside>
    <section class="log-area">
      <LogPanel />
    </section>
  </div>
</div>

<style>
  .actor-view {
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
