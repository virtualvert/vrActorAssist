<script lang="ts">
  import ConnectionPanel from "./ConnectionPanel.svelte";
  import StatusBar from "./StatusBar.svelte";
  import Chat from "./Chat.svelte";
</script>

<div class="director-view">
  <header>
    <ConnectionPanel />
    <StatusBar mode="director" />
  </header>
  <Chat />
</div>
