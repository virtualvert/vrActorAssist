<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";
  import { chatMessages } from "./stores";

  let inputText = $state("");
  let listEl: HTMLDivElement | undefined = $state();

  onMount(async () => {
    await listen<any>("protocol-message", (event) => {
      const msg = event.payload;
      if (msg.Msg) {
        chatMessages.update((m) => [...m, {
          sender: msg.Msg.sender, text: msg.Msg.text,
          timestamp: new Date().toLocaleTimeString(), isOwn: false,
        }]);
        queueScroll();
      }
    });
  });

  function queueScroll() {
    requestAnimationFrame(() => { if (listEl) listEl.scrollTop = listEl.scrollHeight; });
  }

  async function sendMessage() {
    if (!inputText.trim()) return;
    await invoke("send_chat", { text: inputText });
    chatMessages.update((m) => [...m, {
      sender: "Me", text: inputText, timestamp: new Date().toLocaleTimeString(), isOwn: true,
    }]);
    inputText = "";
    queueScroll();
  }
</script>

<div class="chat">
  <div class="messages" bind:this={listEl}>
    {#each $chatMessages as msg}
      <div class="message" class:own={msg.isOwn}>
        <span class="sender">{msg.sender}</span>
        <span class="text">{msg.text}</span>
        <span class="time">{msg.timestamp}</span>
      </div>
    {/each}
  </div>
  <div class="input-row">
    <input type="text" bind:value={inputText} onkeydown={(e) => e.key === "Enter" && sendMessage()} />
    <button onclick={sendMessage}>Send</button>
  </div>
</div>

<style>
  .chat { display: flex; flex-direction: column; height: 100%; }
  .messages { flex: 1; overflow-y: auto; }
  .message.own { text-align: right; }
  .input-row { display: flex; gap: 0.5rem; }
  .input-row input { flex: 1; }
</style>
