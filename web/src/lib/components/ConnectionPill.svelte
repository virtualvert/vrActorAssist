<script lang="ts">
  import { app } from "../state.svelte";
  import StatusDot from "./StatusDot.svelte";

  interface Props {
    onclick: () => void;
  }

  let { onclick }: Props = $props();

  const view = $derived.by(() => {
    if (app.link === "closed") return { level: "bad" as const, pulse: true, text: "App not reachable — retrying" };
    if (app.link === "unauthorized") return { level: "bad" as const, pulse: false, text: "Session expired" };
    const c = app.state?.connection;
    if (!c) return { level: "idle" as const, pulse: true, text: "Starting…" };
    switch (c.status) {
      case "connected":
        return { level: "good" as const, pulse: false, text: c.host || "Connected" };
      case "connecting":
        return { level: "warn" as const, pulse: true, text: "Connecting…" };
      case "pending":
        return { level: "warn" as const, pulse: true, text: "Awaiting approval" };
      case "error":
        return { level: "bad" as const, pulse: false, text: c.detail || "Connection error" };
      default:
        return { level: "idle" as const, pulse: false, text: "Offline" };
    }
  });
</script>

<button class="pill" type="button" {onclick} title={app.state?.connection.detail}>
  <StatusDot level={view.level} pulse={view.pulse} />
  <span class="text">{view.text}</span>
  {#if app.state?.connection.legacy && app.state.connection.status === "connected"}
    <span class="tag">v{app.state.connection.serverVersion ?? "0.3"} relay</span>
  {/if}
</button>

<style>
  .pill {
    display: inline-flex;
    align-items: center;
    gap: 0.6rem;
    min-height: calc(var(--target) * 0.85);
    max-width: 26rem;
    padding: 0 0.95rem 0 0.8rem;
    border-radius: 999px;
    border: 1px solid var(--border);
    background: var(--surface-2);
    font-weight: 600;
    font-size: 0.9rem;
    transition: border-color var(--t-fast);
  }

  .pill:hover {
    border-color: var(--border-strong);
  }

  .text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .tag {
    font-size: 0.75rem;
    color: var(--text-3);
    font-weight: 600;
    white-space: nowrap;
  }
</style>
