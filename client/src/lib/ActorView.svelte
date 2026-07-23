<script lang="ts">
  import ConnectionPanel from "./ConnectionPanel.svelte";
  import StatusBar from "./StatusBar.svelte";
  import Chat from "./Chat.svelte";
  import FileReceiver from "./FileReceiver.svelte";
  import OscConfig from "./OscConfig.svelte";
  import SoundpadConfig from "./SoundpadConfig.svelte";
</script>

<div class="actor-view">
  <header>
    <ConnectionPanel />
    <StatusBar mode="actor" />
  </header>
  <div class="main-area">
    <aside class="left-panel">
      <SoundpadConfig />
      <OscConfig />
      <FileReceiver />
    </aside>
    <section class="chat-area">
      <Chat />
    </section>
  </div>
</div>

<style>
  .main-area { display: flex; gap: 1rem; height: calc(100% - 3rem); }
  .left-panel { width: 320px; display: flex; flex-direction: column; gap: 1rem; overflow-y: auto; }
  .chat-area { flex: 1; }
</style>
