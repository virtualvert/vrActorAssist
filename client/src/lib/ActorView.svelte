<script lang="ts">
  import ConnectionPanel from "./ConnectionPanel.svelte";
  import StatusBar from "./StatusBar.svelte";
  import Chat from "./Chat.svelte";
  import FileReceiver from "./FileReceiver.svelte";
</script>

<div class="actor-view">
  <header>
    <ConnectionPanel />
    <StatusBar mode="actor" />
  </header>
  <FileReceiver />
  <Chat />
</div>
