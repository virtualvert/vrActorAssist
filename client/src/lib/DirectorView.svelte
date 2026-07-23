<script lang="ts">
  import ConnectionPanel from "./ConnectionPanel.svelte";
  import StatusBar from "./StatusBar.svelte";
  import Chat from "./Chat.svelte";
  import ActorList from "./ActorList.svelte";
  import CueControls from "./CueControls.svelte";
  import Settings from "./Settings.svelte";
</script>

<div class="director-view">
  <header>
    <ConnectionPanel />
    <StatusBar mode="director" />
  </header>
  <div class="main-area">
    <aside class="left-panel">
      <ActorList />
      <CueControls />
      <Settings />
    </aside>
    <section class="chat-area">
      <Chat />
    </section>
  </div>
</div>

<style>
  .director-view { display: flex; flex-direction: column; height: 100%; }
  .main-area { display: flex; gap: 1rem; height: calc(100% - 3rem); }
  .left-panel { width: 320px; display: flex; flex-direction: column; gap: 1rem; overflow-y: auto; }
  .chat-area { flex: 1; }
</style>
