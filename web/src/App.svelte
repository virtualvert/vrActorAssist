<script lang="ts">
  import { KeyRound, Sparkles } from "@lucide/svelte";
  import { onMount } from "svelte";
  import LogDrawer from "./lib/components/LogDrawer.svelte";
  import Logo from "./lib/components/Logo.svelte";
  import Onboarding from "./lib/components/Onboarding.svelte";
  import SettingsPanel from "./lib/components/SettingsPanel.svelte";
  import Toasts from "./lib/components/Toasts.svelte";
  import TopBar from "./lib/components/TopBar.svelte";
  import { SCALE_STEP } from "./lib/prefs";
  import { clampScale } from "./lib/protocol";
  import { ROLE_INFO, ROLE_ORDER } from "./lib/roles";
  import { app } from "./lib/state.svelte";
  import { chooseTransport } from "./lib/transport";
  import ActorView from "./lib/views/ActorView.svelte";
  import CameraView from "./lib/views/CameraView.svelte";
  import DirectorView from "./lib/views/DirectorView.svelte";
  import NormalizePanel from "./lib/views/NormalizePanel.svelte";
  import SendFilesPanel from "./lib/views/SendFilesPanel.svelte";

  onMount(async () => {
    app.attach(await chooseTransport());
  });

  // Ctrl/Cmd + / − / 0 scale the whole UI (the desktop window disables browser zoom).
  function onkeydown(e: KeyboardEvent) {
    if (!app.state || !(e.ctrlKey || e.metaKey)) return;
    const scale = app.state.prefs.scale;
    if (e.key === "=" || e.key === "+") app.setPrefs({ scale: clampScale(scale + SCALE_STEP) });
    else if (e.key === "-" || e.key === "_") app.setPrefs({ scale: clampScale(scale - SCALE_STEP) });
    else if (e.key === "0") app.setPrefs({ scale: 1 });
    else return;
    e.preventDefault();
  }
</script>

<svelte:window {onkeydown} />

{#if app.link === "unauthorized"}
  <main class="center">
    <div class="card card-pad notice">
      <KeyRound size="2rem" />
      <h1>This window's session has ended</h1>
      <p class="muted">For safety the app hands out a new link each time it opens a window. Use <strong>Open window</strong> or <strong>Open in browser</strong> from the vrcActorSync app.</p>
    </div>
  </main>
{:else if !app.state}
  <main class="center splash">
    <Logo />
    <span class="faint">Starting…</span>
  </main>
{:else if app.state.role === null || app.onboarding}
  <Onboarding />
{:else}
  <div class="shell">
    <TopBar />
    {#if app.state.demo}
      <div class="demo-ribbon" role="note">
        <Sparkles size="1em" aria-hidden="true" />
        <span>Demo mode — a simulated session. Start the vrcActorSync app to connect for real.</span>
        <span class="switch">
          Try:
          {#each ROLE_ORDER as id (id)}
            <a href="?demo={id}" class:current={app.state.role === id}>{ROLE_INFO[id].short}</a>
          {/each}
        </span>
      </div>
    {/if}
    <main class="content">
      {#if app.state.role === "director"}
        <DirectorView data={app.state} />
      {:else if app.state.role === "actor"}
        <ActorView data={app.state} />
      {:else}
        <CameraView data={app.state} />
      {/if}
    </main>
  </div>
  <SettingsPanel />
  <LogDrawer />
  {#if app.state.role === "director"}<NormalizePanel /><SendFilesPanel />{/if}
{/if}

<Toasts />

<style>
  .shell {
    display: flex;
    flex-direction: column;
    height: 100%;
  }

  .content {
    flex: 1;
    min-height: 0;
    overflow: auto;
  }

  .center {
    height: 100%;
    display: grid;
    place-items: center;
    padding: 1rem;
  }

  .splash {
    align-content: center;
    gap: 1rem;
    animation: breathe 1.6s ease-in-out infinite;
  }

  .splash :global(.logo) {
    width: 4.5rem;
    height: 4.5rem;
  }

  .notice {
    max-width: 32rem;
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
    color: var(--warn);
  }

  .notice h1 {
    color: var(--text);
    font-size: 1.4rem;
  }

  .demo-ribbon {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    flex-wrap: wrap;
    padding: 0.45rem 1rem;
    font-size: 0.8125rem;
    font-weight: 600;
    color: var(--text-2);
    background: linear-gradient(90deg, color-mix(in srgb, var(--accent) 16%, transparent), color-mix(in srgb, var(--accent-2) 10%, transparent));
    border-bottom: 1px solid var(--border);
  }

  .demo-ribbon :global(svg) {
    color: var(--accent);
  }

  .switch {
    margin-left: auto;
    display: flex;
    gap: 0.6rem;
    color: var(--text-3);
  }

  .switch a {
    color: var(--text-2);
  }

  .switch a.current {
    color: var(--accent);
    text-decoration: none;
    font-weight: 800;
  }
</style>
