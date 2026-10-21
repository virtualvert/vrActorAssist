<script lang="ts">
  import { AudioLines, FileUp, Minus, Monitor, Moon, Plus, ScrollText, Settings, Sun } from "@lucide/svelte";
  import { SCALE_STEP } from "../prefs";
  import { clampScale, type Theme } from "../protocol";
  import { ROLE_INFO } from "../roles";
  import { app } from "../state.svelte";
  import Button from "./Button.svelte";
  import ConnectionPill from "./ConnectionPill.svelte";
  import Logo from "./Logo.svelte";

  const data = $derived(app.state!);
  const role = $derived(data.role ? ROLE_INFO[data.role] : null);
  const NEXT_THEME: Record<Theme, Theme> = { system: "dark", dark: "light", light: "system" };
  const THEME_LABEL: Record<Theme, string> = { system: "Theme: follows system", dark: "Theme: dark", light: "Theme: light" };

  const sending = $derived(
    (data.director?.files.batches ?? []).filter((b) => b.state === "waiting" || b.state === "sending").length,
  );

  function bump(delta: number) {
    app.setPrefs({ scale: clampScale(data.prefs.scale + delta) });
  }
</script>

<div class="tb-wrap">
<header class="topbar">
  <div class="brand">
    <Logo />
    <div class="name">
      <strong>vrcActorSync</strong>
      <span class="faint">v{data.appVersion}{data.demo ? " · demo" : ""}</span>
    </div>
  </div>

  {#if role}
    <button class="role role-{role.id}" type="button" onclick={() => (app.settingsOpen = true)} title="Change role in Settings" aria-label="Role: {role.short}">
      <role.icon size="1.15em" aria-hidden="true" />
      <span>{role.short}</span>
    </button>
  {/if}

  <div class="spacer"></div>

  <ConnectionPill onclick={() => (app.settingsOpen = true)} />

  <div class="tools">
    <div class="scale" role="group" aria-label="UI size">
      <Button icon size="s" variant="ghost" aria-label="Smaller UI" onclick={() => bump(-SCALE_STEP)}><Minus size="1.1em" /></Button>
      <span class="mono pct" aria-live="polite">{Math.round(data.prefs.scale * 100)}%</span>
      <Button icon size="s" variant="ghost" aria-label="Larger UI" onclick={() => bump(SCALE_STEP)}><Plus size="1.1em" /></Button>
    </div>
    <Button
      icon
      variant="ghost"
      class="theme"
      aria-label={THEME_LABEL[data.prefs.theme]}
      title={THEME_LABEL[data.prefs.theme]}
      onclick={() => app.setPrefs({ theme: NEXT_THEME[data.prefs.theme] })}
    >
      {#if data.prefs.theme === "dark"}<Moon size="1.25em" />{:else if data.prefs.theme === "light"}<Sun size="1.25em" />{:else}<Monitor size="1.25em" />{/if}
    </Button>
    {#if data.role === "director"}
      <Button icon variant="ghost" aria-label="Send files" title="Send files" onclick={() => (app.sendOpen = true)}>
        <FileUp size="1.25em" />
        {#if sending > 0}<span class="badge">{sending}</span>{/if}
      </Button>
      <Button icon variant="ghost" aria-label="Normalize folder" title="Normalize folder" onclick={() => (app.normalizeOpen = true)}>
        <AudioLines size="1.25em" />
      </Button>
    {/if}
    <Button icon variant="ghost" aria-label="Activity and chat" title="Activity and chat" onclick={() => app.openLog(true)}>
      <ScrollText size="1.25em" />
      {#if app.unreadLogs > 0}<span class="badge">{app.unreadLogs > 9 ? "9+" : app.unreadLogs}</span>{/if}
    </Button>
    <Button icon variant="ghost" aria-label="Settings" title="Settings" onclick={() => (app.settingsOpen = true)}>
      <Settings size="1.25em" />
    </Button>
  </div>
</header>
</div>

<style>
  /* A container, so the collapse points follow the scaled UI (rem here tracks --ui-scale). */
  .tb-wrap {
    container-type: inline-size;
    position: relative;
    z-index: 10;
  }

  .topbar {
    position: relative;
    z-index: 10;
    display: flex;
    align-items: center;
    gap: 0.9rem;
    min-height: calc(var(--target) * 1.6);
    padding: 0.5rem 1rem;
    border-bottom: 1px solid var(--border);
    background: var(--surface-glass);
    backdrop-filter: blur(16px) saturate(1.4);
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    flex: none;
  }

  .name {
    display: flex;
    flex-direction: column;
    line-height: 1.15;
  }

  .name strong {
    font-size: 1.05rem;
    letter-spacing: -0.01em;
  }

  .name span {
    font-size: 0.75rem;
  }

  .role {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    min-height: calc(var(--target) * 0.85);
    padding: 0 0.95rem;
    border-radius: 999px;
    border: 1px solid color-mix(in srgb, var(--role) 45%, transparent);
    background: color-mix(in srgb, var(--role) 14%, transparent);
    color: var(--role);
    font-weight: 700;
    letter-spacing: 0.01em;
  }

  .spacer {
    flex: 1;
  }

  /* The connection pill gives way first (its text ends in "…") so the buttons stay on screen. */
  .topbar > :global(.pill) {
    min-width: 0;
  }

  .tools {
    display: flex;
    align-items: center;
    gap: 0.25rem;
  }

  .scale {
    display: flex;
    align-items: center;
    gap: 0.1rem;
    padding: 0 0.25rem;
    margin-right: 0.25rem;
    border-radius: var(--radius);
    border: 1px solid var(--border);
  }

  .pct {
    min-width: 3.2em;
    text-align: center;
    font-size: 0.8125rem;
    color: var(--text-2);
  }

  .badge {
    position: absolute;
    top: 0.2rem;
    right: 0.2rem;
    min-width: 1.2rem;
    height: 1.2rem;
    padding: 0 0.3rem;
    border-radius: 999px;
    background: var(--live);
    color: #fff;
    font-size: 0.6875rem;
    font-weight: 800;
    display: grid;
    place-items: center;
  }

  @container (max-width: 52rem) {
    .name span,
    .scale {
      display: none;
    }
  }

  @container (max-width: 36rem) {
    .name {
      display: none;
    }
  }

  /* Phone width: the role shows as its icon and the theme lives in Settings only. */
  @container (max-width: 34rem) {
    .topbar {
      gap: 0.5rem;
      padding: 0.5rem 0.75rem;
    }

    .role {
      padding: 0 0.7rem;
    }

    .role span,
    .tools :global(.theme) {
      display: none;
    }
  }
</style>
