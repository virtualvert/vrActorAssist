<script lang="ts">
  import { invoke } from "@tauri-apps/api/core";
  import { onMount } from "svelte";
  import { listen } from "@tauri-apps/api/event";

  type LogKind = "chat" | "system" | "command" | "ack" | "file" | "error";

  interface LogEntry {
    kind: LogKind;
    text: string;
    sender: string;
    isOwn: boolean;
    timestamp: string;
  }

  let entries: LogEntry[] = $state([]);
  let inputText = $state("");
  let listEl: HTMLDivElement | undefined = $state();

  function addEntry(kind: LogKind, text: string, sender = "", isOwn = false) {
    entries.push({ kind, text, sender, isOwn, timestamp: new Date().toLocaleTimeString() });
    queueScroll();
  }

  function formatSize(bytes: number): string {
    if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${bytes} B`;
  }

  function handleProtocolMessage(msg: any) {
    if (msg.Msg) {
      const { sender, text } = msg.Msg;
      if (sender === "SERVER") {
        addEntry("system", `[System] ${text}`);
      } else {
        addEntry("chat", text, sender);
      }
    } else if (msg.Priv) {
      addEntry("command", `→ ${msg.Priv.text} sent to ${msg.Priv.target}`);
    } else if (msg.Cmd) {
      const args = msg.Cmd.args ? ` ${msg.Cmd.args}` : "";
      addEntry("command", `⚡ broadcast: ${msg.Cmd.command}${args}`);
    } else if (msg.Ack) {
      addEntry("ack", `✓ ${msg.Ack.actor}: ${msg.Ack.command} ${msg.Ack.status}`);
    } else if (msg.FileOk) {
      addEntry("file", `📁 ${msg.FileOk.filename} saved`);
    } else if (msg.FileErr) {
      addEntry("error", `✗ ${msg.FileErr.filename}: ${msg.FileErr.error}`);
    } else if (msg.File) {
      addEntry("file", `📁 ${msg.File.sender} sent ${msg.File.filename} (${formatSize(msg.File.size)})`);
    } else if (msg.Denied) {
      addEntry("error", `✗ Denied: ${msg.Denied.reason}`);
    }
  }

  onMount(() => {
    let unlisten: (() => void) | undefined;
    listen<any>("protocol-message", (event) => handleProtocolMessage(event.payload)).then((fn) => {
      unlisten = fn;
    });
    return () => { unlisten?.(); };
  });

  function queueScroll() {
    requestAnimationFrame(() => { if (listEl) listEl.scrollTop = listEl.scrollHeight; });
  }

  async function sendMessage() {
    const text = inputText.trim();
    if (!text) return;
    await invoke("send_chat", { text });
    addEntry("chat", text, "Me", true);
    inputText = "";
  }
</script>

<div class="log-panel">
  <div class="log-entries" bind:this={listEl}>
    {#if entries.length === 0}
      <p class="log-empty">No activity yet. Messages, cues, and file transfers will appear here.</p>
    {/if}
    {#each entries as entry}
      <div class="log-entry {entry.kind}" class:own={entry.isOwn}>
        <span class="timestamp">{entry.timestamp}</span>
        {#if entry.kind === "chat"}
          <span class="sender">{entry.sender}:</span>
        {/if}
        <span class="content">{entry.text}</span>
      </div>
    {/each}
  </div>
  <div class="input-row">
    <input
      type="text"
      bind:value={inputText}
      placeholder="Type a message..."
      onkeydown={(e) => e.key === "Enter" && sendMessage()}
    />
    <button onclick={sendMessage} disabled={!inputText.trim()}>Send</button>
  </div>
</div>

<style>
  .log-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 8px;
    overflow: hidden;
  }

  .log-entries {
    flex: 1;
    overflow-y: auto;
    min-height: 0;
    padding: 0.6rem 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 0.9rem;
  }

  .log-empty {
    margin: auto;
    padding: 2rem 1rem;
    color: var(--text-secondary);
    font-style: italic;
    text-align: center;
  }

  .log-entry {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
    padding: 0.2rem 0.4rem;
    border-radius: 4px;
    line-height: 1.45;
  }

  .timestamp {
    flex-shrink: 0;
    font-family: var(--mono);
    font-size: 0.72rem;
    color: var(--text-secondary);
    opacity: 0.8;
  }

  .sender {
    flex-shrink: 0;
    font-weight: 600;
    color: var(--accent);
  }

  .content {
    word-break: break-word;
    min-width: 0;
  }

  .log-entry.chat .content {
    color: var(--text-primary);
  }

  .log-entry.own {
    justify-content: flex-end;
  }

  .log-entry.own .sender {
    color: var(--accent-green);
  }

  .log-entry.system {
    color: var(--text-secondary);
    font-style: italic;
  }

  .log-entry.command {
    color: var(--accent-yellow);
  }

  .log-entry.ack {
    color: var(--accent-green);
  }

  .log-entry.file {
    color: var(--accent-blue);
  }

  .log-entry.error {
    color: var(--accent-red);
  }

  .input-row {
    display: flex;
    gap: 0.5rem;
    padding: 0.6rem 0.75rem;
    border-top: 1px solid var(--border);
    background: var(--bg-primary);
  }

  .input-row input {
    flex: 1;
    min-width: 0;
  }
</style>
