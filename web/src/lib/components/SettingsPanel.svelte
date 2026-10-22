<script lang="ts">
  import { ExternalLink, FolderOpen, Glasses, Monitor, Moon, Sun } from "@lucide/svelte";
  import { clampScale, SCALE_MAX, SCALE_MIN, VR_SCALE, type Theme } from "../protocol";
  import { ROLE_INFO, ROLE_ORDER } from "../roles";
  import { OWN_LINE_HELP, OWN_LINE_OPTIONS } from "../soundpad";
  import { app } from "../state.svelte";
  import Button from "./Button.svelte";
  import ConnectForm from "./ConnectForm.svelte";
  import Drawer from "./Drawer.svelte";
  import RoleCard from "./RoleCard.svelte";
  import Segmented from "./Segmented.svelte";
  import Toggle from "./Toggle.svelte";

  const data = $derived(app.state!);
  const prefs = $derived(data.prefs);

  const THEMES: { value: Theme; label: string; icon: typeof Sun }[] = [
    { value: "system", label: "System", icon: Monitor },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "light", label: "Light", icon: Sun },
  ];

  const PRESETS = [
    { label: "Compact", scale: 0.9 },
    { label: "Desktop", scale: 1 },
    { label: "Large", scale: 1.2 },
    { label: "VR", scale: VR_SCALE },
  ];

  function setVr(on: boolean) {
    app.setPrefs(on ? { vrMode: true, scale: Math.max(prefs.scale, VR_SCALE) } : { vrMode: false });
  }

  const LEADS = [0, 150, 300, 500, 1000];

  function setLead(value: number) {
    if (Number.isFinite(value)) void app.call({ call: "setDirectorLocal", args: { leadMs: Math.round(value) } });
  }
</script>

<Drawer open={app.settingsOpen} title="Settings" onclose={() => (app.settingsOpen = false)}>
  <div class="sections">
    <section>
      <h3 class="eyebrow">Appearance</h3>
      <Segmented label="Theme" options={THEMES} value={prefs.theme} onchange={(theme) => app.setPrefs({ theme })} />

      <div class="field scale">
        <span>UI size <span class="mono faint">{Math.round(prefs.scale * 100)}%</span></span>
        <input
          type="range"
          min={SCALE_MIN}
          max={SCALE_MAX}
          step="0.05"
          value={prefs.scale}
          aria-label="UI size"
          oninput={(e) => app.setPrefs({ scale: clampScale(Number(e.currentTarget.value)) })}
        />
        <div class="presets">
          {#each PRESETS as p (p.label)}
            <Button size="s" variant={Math.abs(prefs.scale - p.scale) < 0.01 ? "primary" : "subtle"} onclick={() => app.setPrefs({ scale: p.scale })}>
              {p.label}
            </Button>
          {/each}
        </div>
        <small>Shortcut: Ctrl + / Ctrl − / Ctrl 0</small>
      </div>

      <Toggle
        checked={prefs.vrMode}
        label="VR mode"
        description="Bigger buttons and spacing for laser pointers and desktop overlays. Labels stay visible instead of hover tips."
        onchange={setVr}
      />
      <Toggle
        checked={prefs.reduceMotion}
        label="Reduce motion"
        description="Calms the node graph and turns off pulsing. Your system setting is respected too."
        onchange={(reduceMotion) => app.setPrefs({ reduceMotion })}
      />
    </section>

    <section>
      <h3 class="eyebrow">Your role</h3>
      <p class="faint small">The app opens straight into this role next time. Switching reconnects to the relay.</p>
      <div class="roles" role="radiogroup" aria-label="Role">
        {#each ROLE_ORDER as id (id)}
          <RoleCard
            info={ROLE_INFO[id]}
            compact
            selected={data.role === id}
            onselect={() => data.role !== id && app.call({ call: "setRole", args: { role: id } })}
          />
        {/each}
      </div>
    </section>

    <section>
      <h3 class="eyebrow">Connection</h3>
      {#if data.connection.legacy && data.connection.status === "connected"}
        <p class="note">Connected to a v0.3 relay. Cast list and cues work; camera operators and file transfer need the v0.4 relay.</p>
      {/if}
      {#key data.role}
        <ConnectForm />
      {/key}
    </section>

    {#if data.director}
      <section>
        <h3 class="eyebrow">Director</h3>
        <div class="field">
          <span>GO lead time</span>
          <div class="with-button">
            <input
              class="input mono lead"
              type="number"
              min="0"
              max="2000"
              step="10"
              aria-label="GO lead time in milliseconds"
              value={data.director.leadMs}
              onchange={(e) => setLead(Number(e.currentTarget.value))}
            />
            <span class="faint">ms</span>
          </div>
          <div class="presets">
            {#each LEADS as ms (ms)}
              <Button size="s" variant={data.director.leadMs === ms ? "primary" : "subtle"} onclick={() => setLead(ms)}>{ms ? `${ms} ms` : "At once"}</Button>
            {/each}
          </div>
          <small>
            GO goes out for the relay's time now + this, so every actor starts together. It has to cover the slowest
            actor's trip; 0 sends GO at once, as the v0.3 director did. Play in 3s always uses 3 s.
          </small>
        </div>
      </section>
    {/if}

    {#if data.actor}
      <section>
        <h3 class="eyebrow">Actor</h3>
        <Toggle
          checked={data.actor.soundpad.enabled}
          label="Soundpad"
          description={data.actor.soundpad.detail}
          onchange={(soundpadEnabled) => app.call({ call: "setActorLocal", args: { soundpadEnabled } })}
        />
        <div class="field">
          <span>Soundpad.exe location</span>
          <div class="with-button">
            <input
              class="input mono"
              aria-label="Soundpad.exe location"
              value={data.actor.soundpad.path}
              placeholder="Found automatically when empty"
              spellcheck="false"
              onchange={(e) => app.call({ call: "setActorLocal", args: { soundpadPath: e.currentTarget.value } })}
            />
            <Button variant="subtle" onclick={() => app.call({ call: "detectSoundpad" })}>Detect</Button>
          </div>
          <small>Only needed when Soundpad lives outside Program Files or Steam. Detect looks there and fills it in.</small>
        </div>
        <div class="field">
          <span>Default output line</span>
          <Segmented
            label="Default output line"
            options={OWN_LINE_OPTIONS}
            value={data.actor.soundpad.defaultLines}
            onchange={(defaultLines) => app.call({ call: "setActorLocal", args: { defaultLines } })}
          />
          <small>For sounds the director plays without picking a line: {OWN_LINE_HELP[data.actor.soundpad.defaultLines].toLowerCase()}. Go and sound numbers always play on both.</small>
        </div>
        <Toggle
          checked={data.actor.soundpad.autoAddReceived}
          label="Add received files to Soundpad"
          description="So the director can play them right after sending. Needs the full version of Soundpad."
          onchange={(autoAddReceived) => app.call({ call: "setActorLocal", args: { autoAddReceived } })}
        />
        <Toggle
          checked={data.actor.soundpad.autoLaunch}
          label="Start Soundpad when it isn't running"
          description="If Soundpad is closed, the app starts it (once per run)."
          onchange={(autoLaunch) => app.call({ call: "setActorLocal", args: { autoLaunch } })}
        />
        <Toggle
          checked={data.actor.timing.autoCompensate}
          label="Start sounds early by Soundpad's start latency"
          description="Scheduled cues go to Soundpad {data.actor.timing.startLatencyMs} ms early{data.actor.timing.measured ? '' : ' (assumed until measured)'}, so the sound starts on the director's time."
          onchange={(autoCompensateLatency) => app.call({ call: "setActorLocal", args: { autoCompensateLatency } })}
        />
        <Toggle
          checked={data.actor.osc.enabled}
          label="VRChat OSC"
          description="Sends avatar parameters to {data.actor.osc.host}:{data.actor.osc.port}"
          onchange={(oscEnabled) => app.call({ call: "setActorLocal", args: { oscEnabled } })}
        />
        <div class="field">
          <span>Received files folder</span>
          <div class="with-button">
            <input
              class="input mono"
              aria-label="Received files folder"
              value={data.actor.files.receiveDir}
              spellcheck="false"
              onchange={(e) => app.call({ call: "setActorLocal", args: { receiveDir: e.currentTarget.value } })}
            />
            {#if app.kind === "agent"}
              <Button variant="subtle" onclick={() => app.call({ call: "pickReceiveDir" })}>Browse…</Button>
            {/if}
          </div>
          <small>Files from the director are saved here. Empty it to go back to Documents\vrcActorSync.</small>
        </div>
        <Toggle
          checked={data.actor.files.autoAccept}
          label="Accept files automatically"
          description="Without asking, and replacing files that have the same name"
          onchange={(autoAcceptFiles) => app.call({ call: "setActorLocal", args: { autoAcceptFiles } })}
        />
      </section>
    {/if}

    <section>
      <h3 class="eyebrow">About</h3>
      <dl class="about">
        <dt>Version</dt>
        <dd class="mono">{data.appVersion}</dd>
        <dt>Running as</dt>
        <dd>{app.kind === "demo" ? "Demo (simulated session)" : "vrcActorSync app"}</dd>
        <dt>Relay</dt>
        <dd>{data.connection.serverVersion ? `v${data.connection.serverVersion}` : "—"}{data.connection.legacy ? " (v0.3 protocol)" : ""}</dd>
        {#if data.logDir}
          <dt>Logs</dt>
          <dd class="mono path">{data.logDir}</dd>
        {/if}
      </dl>
      {#if app.kind === "agent"}
        <small>Reporting a problem? Send the version above and <span class="mono">agent.log</span> from the log folder.</small>
        <div class="about-actions">
          <Button variant="subtle" onclick={() => app.call({ call: "openLogFolder" })}>
            <FolderOpen size="1.1em" /> Open log folder
          </Button>
          <Button variant="subtle" onclick={() => app.call({ call: "openBrowser" })}>
            <ExternalLink size="1.1em" /> Open in browser
          </Button>
        </div>
      {/if}
      {#if prefs.vrMode}
        <p class="faint small"><Glasses size="1em" /> VR mode is on.</p>
      {/if}
    </section>
  </div>
</Drawer>

<style>
  .sections {
    display: flex;
    flex-direction: column;
    gap: 2rem;
  }

  section {
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
  }

  .small {
    font-size: 0.875rem;
  }

  .scale input[type="range"] {
    width: 100%;
    height: var(--target);
    accent-color: var(--accent);
  }

  .presets {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
  }

  .roles {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .note {
    padding: 0.75rem 0.9rem;
    border-radius: var(--radius);
    background: color-mix(in srgb, var(--warn) 12%, transparent);
    border: 1px solid color-mix(in srgb, var(--warn) 35%, transparent);
    font-size: 0.875rem;
  }

  .about {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 0.4rem 1rem;
    margin: 0;
  }

  .about dt {
    color: var(--text-3);
  }

  .about dd {
    margin: 0;
    min-width: 0;
  }

  .about .path {
    overflow-wrap: anywhere;
    user-select: all;
  }

  .about-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }

  .with-button {
    display: flex;
    gap: 0.5rem;
  }

  .with-button input {
    flex: 1;
    min-width: 0;
  }

  .with-button input.lead {
    flex: 0 1 8rem;
  }

  .with-button:has(.lead) {
    align-items: center;
  }
</style>
