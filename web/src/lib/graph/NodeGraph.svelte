<script lang="ts">
  import { Check, Server } from "@lucide/svelte";
  import {
    forceCollide,
    forceManyBody,
    forceSimulation,
    forceX,
    forceY,
    type Simulation,
    type SimulationNodeDatum,
  } from "d3-force";
  import { onDestroy, onMount, type Component } from "svelte";
  import type { AppState, Traffic, TrafficKind } from "../protocol";
  import { ROLE_INFO } from "../roles";
  import { app } from "../state.svelte";
  import {
    anchorsFor,
    bezierPoint,
    curveControl,
    easeInOut,
    graphSpecs,
    actorRows,
    linkPath,
    minGraphHeight,
    SERVER_ID,
    type GraphNodeSpec,
    type NodeKind,
    type Point,
  } from "./layout";

  interface Props {
    data: AppState;
    compact?: boolean;
    ontoggle?: (id: string) => void;
  }

  let { data, compact = false, ontoggle }: Props = $props();

  interface SimNode extends SimulationNodeDatum {
    id: string;
    spec: GraphNodeSpec;
    anchor: Point;
    leaving: boolean;
    phase: number;
  }

  interface Packet {
    id: number;
    from: string;
    to: string;
    kind: TrafficKind;
    start: number;
    dur: number;
  }

  const HOP_MS = 520;
  const KINDS: NodeKind[] = ["director", "actor", "camera", "server"];

  let box: HTMLDivElement | undefined = $state();
  let width = $state(0);
  let height = $state(0);
  let frame = $state(0);
  let list = $state.raw<SimNode[]>([]);
  let packets = $state.raw<Packet[]>([]);
  let now = $state(0);
  let arrivals = $state.raw<Record<string, number>>({});
  let hovered = $state<string | null>(null);

  const nodes = new Map<string, SimNode>();
  let sim: Simulation<SimNode, undefined> | null = null;
  let frameCounter = 0;
  let packetId = 1;
  let raf = 0;

  const remPx = $derived(16 * data.prefs.scale);
  const radius = $derived(remPx * (data.prefs.vrMode ? 1.95 : 1.6) * (compact ? 0.8 : 1));
  const serverRadius = $derived(radius * 1.4);
  const reduceMotion = $derived(
    data.prefs.reduceMotion || (typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches),
  );

  function bump() {
    frameCounter += 1;
    frame = frameCounter;
  }

  function publish() {
    list = [...nodes.values()];
    bump();
  }

  function sizeOf(n: SimNode) {
    return n.spec.kind === "server" ? serverRadius : radius;
  }

  function restartSim(alpha: number) {
    if (!sim) {
      sim = forceSimulation<SimNode>().alphaDecay(0.035).velocityDecay(0.3).on("tick", bump);
    }
    sim.nodes([...nodes.values()]);
    sim
      .force("x", forceX<SimNode>((n) => n.anchor.x).strength((n) => (n.spec.kind === "server" ? 0 : 0.085)))
      .force("y", forceY<SimNode>((n) => n.anchor.y).strength((n) => (n.spec.kind === "server" ? 0 : 0.085)))
      .force("collide", forceCollide<SimNode>((n) => sizeOf(n) + remPx * 1.5).strength(0.9))
      .force("charge", forceManyBody<SimNode>().strength(-radius * 2.5).distanceMax(radius * 7))
      .force("bounds", keepInside);
    if (alpha === 0) {
      for (const n of nodes.values()) {
        n.x = n.anchor.x;
        n.y = n.anchor.y;
        n.vx = 0;
        n.vy = 0;
      }
      sim.stop();
      bump();
      return;
    }
    sim.alpha(Math.max(sim.alpha(), alpha)).restart();
  }

  // Custom force: collisions must never push a node (or its label) off the canvas.
  function keepInside() {
    const pad = remPx * 0.5;
    for (const n of nodes.values()) {
      const r = sizeOf(n);
      n.x = Math.min(Math.max(n.x ?? 0, r + pad), width - r - pad);
      n.y = Math.min(Math.max(n.y ?? 0, r + remPx * 1.6), height - r - remPx * 2.6);
    }
  }

  // Reconcile the drawn nodes with the latest state. Positions survive updates; only joins,
  // leaves and resizes reheat the simulation, so the picture stays calm.
  $effect(() => {
    const specs = graphSpecs(data);
    if (!width || !height) return;
    const targets = anchorsFor(specs, { width, height }, { radius, rem: remPx });
    const seen = new Set<string>();
    let structural = false;

    for (const spec of specs) {
      seen.add(spec.id);
      const anchor = targets.get(spec.id)!;
      let n = nodes.get(spec.id);
      if (!n) {
        const fromCenter = !reduceMotion && spec.kind !== "server";
        const start = fromCenter
          ? { x: width / 2 + (Math.random() - 0.5) * 24, y: height / 2 + (Math.random() - 0.5) * 24 }
          : anchor;
        n = { id: spec.id, spec, anchor, leaving: false, phase: Math.random() * 7, x: start.x, y: start.y };
        nodes.set(spec.id, n);
        structural = true;
      } else {
        if (n.leaving) {
          n.leaving = false;
          structural = true;
        }
        if (Math.abs(n.anchor.x - anchor.x) > 0.5 || Math.abs(n.anchor.y - anchor.y) > 0.5) structural = true;
        n.spec = spec;
        n.anchor = anchor;
      }
      if (spec.kind === "server") {
        n.fx = anchor.x;
        n.fy = anchor.y;
      }
    }

    for (const n of nodes.values()) {
      if (seen.has(n.id) || n.leaving) continue;
      n.leaving = true;
      structural = true;
      setTimeout(() => {
        if (!nodes.get(n.id)?.leaving) return;
        nodes.delete(n.id);
        publish();
      }, 420);
    }

    publish();
    if (structural) restartSim(reduceMotion ? 0 : 0.7);
  });

  function onTraffic(t: Traffic) {
    if (!nodes.size) return;
    const start = performance.now();
    const fromId = nodes.has(t.from) ? t.from : SERVER_ID;
    const out: Packet[] = [];
    let delay = 0;
    if (fromId !== SERVER_ID) {
      out.push({ id: packetId++, from: fromId, to: SERVER_ID, kind: t.kind, start, dur: HOP_MS });
      delay = HOP_MS;
    }
    for (const target of t.to) {
      if (!nodes.has(target) || target === SERVER_ID || target === fromId) continue;
      out.push({ id: packetId++, from: SERVER_ID, to: target, kind: t.kind, start: start + delay, dur: HOP_MS });
    }
    if (reduceMotion) {
      // No travelling dots; just flash the receivers.
      const next = { ...arrivals };
      for (const p of out) if (p.to !== SERVER_ID) next[p.to] = (next[p.to] ?? 0) + 1;
      arrivals = next;
      return;
    }
    packets = [...packets, ...out];
    if (!raf) raf = requestAnimationFrame(step);
  }

  function step(ts: number) {
    now = ts;
    const done = packets.filter((p) => ts >= p.start + p.dur);
    if (done.length) {
      const next = { ...arrivals };
      for (const p of done) next[p.to] = (next[p.to] ?? 0) + 1;
      arrivals = next;
      packets = packets.filter((p) => ts < p.start + p.dur);
    }
    raf = packets.length ? requestAnimationFrame(step) : 0;
  }

  const pt = (n: SimNode): Point => ({ x: n.x ?? 0, y: n.y ?? 0 });

  function packetPos(p: Packet, ts: number): Point | null {
    const t = (ts - p.start) / p.dur;
    if (t < 0 || t > 1) return null;
    const server = nodes.get(SERVER_ID);
    const other = nodes.get(p.from === SERVER_ID ? p.to : p.from);
    if (!server || !other) return null;
    const a = pt(server);
    const b = pt(other);
    const e = easeInOut(t);
    return bezierPoint(a, curveControl(a, b), b, p.from === SERVER_ID ? e : 1 - e);
  }

  // Nodes are mutable objects shared with d3; passing `frame` makes the template re-read them.
  function specOf(n: SimNode, _frame: number): GraphNodeSpec {
    return n.spec;
  }

  function nodeTransform(n: SimNode, _frame: number): string {
    return `translate(${(n.x ?? 0).toFixed(1)},${(n.y ?? 0).toFixed(1)})`;
  }

  function linkD(n: SimNode, _frame: number): string {
    const server = nodes.get(SERVER_ID);
    if (!server) return "";
    return linkPath(pt(server), pt(n));
  }

  function iconFor(kind: NodeKind): Component {
    return kind === "server" ? (Server as unknown as Component) : ROLE_INFO[kind].icon;
  }

  function kindLabel(kind: NodeKind): string {
    return kind === "server" ? "Relay server" : ROLE_INFO[kind].label;
  }

  function ariaFor(s: GraphNodeSpec): string {
    const who = s.self ? `${s.label} (you)` : s.label;
    const cue = s.selectable ? (s.targeted ? ", receives cues" : ", excluded from cues") : "";
    return `${who}, ${kindLabel(s.kind)}, ${s.sub}${cue}`;
  }

  function toggle(s: GraphNodeSpec) {
    if (s.selectable) ontoggle?.(s.id);
  }

  // Links that are carrying a command right now. Only these animate; idle links stay still.
  const busy = $derived.by(() => {
    const ids = new Set<string>();
    for (const p of packets) {
      if (now >= p.start - 40 && now <= p.start + p.dur + 120) ids.add(p.from === SERVER_ID ? p.to : p.from);
    }
    return ids;
  });

  const tip = $derived.by(() => {
    void frame;
    if (!hovered || data.prefs.vrMode || compact) return null;
    const n = nodes.get(hovered);
    if (!n || n.leaving) return null;
    return { n, R: sizeOf(n) };
  });

  // The card goes above the node, or below its name when there's no room above (the top row of
  // directors), and stays inside the canvas, which clips. Measured, so it doesn't jump.
  let tipW = $state(0);
  let tipH = $state(0);
  const tipAt = $derived.by(() => {
    if (!tip) return null;
    const pad = remPx * 0.5;
    const x = tip.n.x ?? 0;
    const y = tip.n.y ?? 0;
    const above = y - tip.R - remPx * 0.8 - tipH;
    const below = y + tip.R + remPx * 2.9;
    const top = above >= pad || below + tipH > height - pad ? Math.max(pad, above) : below;
    const half = tipW / 2;
    const left = Math.max(pad + half, Math.min(x, width - pad - half));
    return { left, top };
  });

  const minHeight = $derived.by(() => {
    const actors = data.peers.filter((p) => p.role === "actor").length + data.pending.length;
    const cameras = data.peers.some((p) => p.role === "camera");
    const rows = width ? actorRows(actors, width, { radius, rem: remPx }, cameras) : 1;
    return minGraphHeight({ radius, rem: remPx }, rows) * (compact ? 0.85 : 1);
  });

  const counts = $derived.by(() => {
    const c = { director: 0, actor: 0, camera: 0 };
    for (const p of data.peers) c[p.role] += 1;
    return c;
  });

  onMount(() => {
    const ro = new ResizeObserver(([entry]) => {
      width = Math.round(entry.contentRect.width);
      height = Math.round(entry.contentRect.height);
    });
    if (box) ro.observe(box);
    const off = app.onTraffic(onTraffic);
    return () => {
      ro.disconnect();
      off();
    };
  });

  onDestroy(() => {
    sim?.stop();
    if (raf) cancelAnimationFrame(raf);
  });
</script>

<div class="graph" class:compact>
  <div class="canvas" bind:this={box} style="min-height: {Math.round(minHeight)}px">
  {#if width && height}
    <svg {width} {height} viewBox="0 0 {width} {height}" role="group" aria-label="Connected clients">
      <defs>
        {#each KINDS as k (k)}
          <radialGradient id="core-{k}" cx="35%" cy="30%" r="80%">
            <stop offset="0%" style="stop-color: color-mix(in srgb, var(--{k}) 50%, white)" />
            <stop offset="55%" style="stop-color: var(--{k})" />
            <stop offset="100%" style="stop-color: color-mix(in srgb, var(--{k}) 62%, black)" />
          </radialGradient>
        {/each}
        <pattern id="grid-dots" width="26" height="26" patternUnits="userSpaceOnUse">
          <circle cx="2" cy="2" r="1.2" fill="var(--graph-grid)" />
        </pattern>
        <filter id="packet-glow" x="-200%" y="-200%" width="500%" height="500%">
          <feGaussianBlur stdDeviation="3.5" result="blur" />
          <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
        </filter>
      </defs>

      <rect class="grid" {width} {height} fill="url(#grid-dots)" />

      <g class="links">
        {#each list as n (n.id)}
          {@const ls = specOf(n, frame)}
          {#if ls.kind !== "server"}
            {@const d = linkD(n, frame)}
            <g
              class="link lvl-{ls.level} st-{ls.status} act-{ls.activity}"
              class:leaving={n.leaving}
              class:dim={ls.selectable && !ls.targeted}
              class:busy={busy.has(n.id)}
            >
              <path class="base" {d} />
              <path class="flow" {d} />
            </g>
          {/if}
        {/each}
      </g>

      <g class="packets">
        {#each packets as p (p.id)}
          {@const pos = packetPos(p, now)}
          {#if pos}
            <circle class="packet k-{p.kind}" cx={pos.x} cy={pos.y} r={remPx * 0.36} />
          {/if}
        {/each}
      </g>

      <g class="nodes">
        {#each list as n (n.id)}
          {@const s = specOf(n, frame)}
          {@const R = sizeOf(n)}
          {@const Icon = iconFor(s.kind)}
          <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
          <g
            class="node role-{s.kind} lvl-{s.level} st-{s.status} act-{s.activity}"
            class:self={s.self}
            class:targeted={s.targeted}
            class:untargeted={s.selectable && !s.targeted}
            class:selectable={s.selectable}
            class:leaving={n.leaving}
            transform={nodeTransform(n, frame)}
            role={s.selectable ? "button" : "img"}
            tabindex={s.selectable ? 0 : undefined}
            aria-pressed={s.selectable ? s.targeted : undefined}
            aria-label={ariaFor(s)}
            onclick={() => toggle(s)}
            onkeydown={(e) => {
              if (s.selectable && (e.key === "Enter" || e.key === " ")) {
                e.preventDefault();
                toggle(s);
              }
            }}
            onpointerenter={() => (hovered = s.id)}
            onpointerleave={() => hovered === s.id && (hovered = null)}
            onfocus={() => (hovered = s.id)}
            onblur={() => hovered === s.id && (hovered = null)}
          >
            <g class="float" style="animation-delay: -{n.phase}s">
              <g class="pop">
                {#if s.activity !== "idle" || s.status === "up"}
                  <circle class="halo" r={R + 3} />
                {/if}
                {#key arrivals[s.id]}
                  {#if arrivals[s.id]}<circle class="arrive" r={R + 2} />{/if}
                {/key}
                <circle class="ring" r={R + remPx * 0.24} />
                <circle class="core" r={R} fill="url(#core-{s.kind})" />
                <Icon x={-R * 0.52} y={-R * 0.52} size={R * 1.04} color="white" strokeWidth={1.9} aria-hidden="true" />
              </g>
              {#if s.targeted}
                <g class="badge" transform="translate({R * 0.74},{-R * 0.74})">
                  <circle r={remPx * 0.62} />
                  <Check x={-remPx * 0.4} y={-remPx * 0.4} size={remPx * 0.8} color="white" strokeWidth={3.2} aria-hidden="true" />
                </g>
              {/if}
              {#if s.self}
                <g class="you" transform="translate(0,{-R - remPx * 0.95})">
                  <rect x={-remPx * 1.35} y={-remPx * 0.55} width={remPx * 2.7} height={remPx * 1.1} rx={remPx * 0.55} />
                  <text y={remPx * 0.06} dominant-baseline="middle">YOU</text>
                </g>
              {/if}
            </g>
            <text class="label" y={R + remPx * 1.35}>{s.label}</text>
            <text class="sub" y={R + remPx * 2.35}>{s.sub}</text>
          </g>
        {/each}
      </g>
    </svg>

    {#if tip && tipAt}
      <div
        class="tip role-{tip.n.spec.kind}"
        style="left: {tipAt.left}px; top: {tipAt.top}px"
        bind:offsetWidth={tipW}
        bind:offsetHeight={tipH}
      >
        <strong>{tip.n.spec.label}{tip.n.spec.self ? " (you)" : ""}</strong>
        <span class="kind">{kindLabel(tip.n.spec.kind)}</span>
        <span>{tip.n.spec.sub}</span>
        {#if tip.n.spec.selectable}
          <span class="hint">{tip.n.spec.targeted ? "Click to leave out of cues" : "Click to include in cues"}</span>
        {/if}
      </div>
    {/if}

  {/if}
  </div>

  {#if !compact && width}
      <div class="legend" aria-hidden="true">
        <span class="chip"><i class="sw role-director"></i>Directors {counts.director}</span>
        <span class="chip"><i class="sw role-actor"></i>Actors {counts.actor}</span>
        <span class="chip"><i class="sw role-camera"></i>Cameras {counts.camera}</span>
        <span class="chip lat"><i class="ln lvl-good"></i>&lt;100 ms <i class="ln lvl-fair"></i>≤300 <i class="ln lvl-poor"></i>slow <i class="ln lvl-lost"></i>lost</span>
      </div>
  {/if}
</div>

<style>
  .graph {
    display: flex;
    flex-direction: column;
    width: 100%;
    height: 100%;
    border-radius: inherit;
  }

  .canvas {
    position: relative;
    flex: 1;
    overflow: hidden;
  }

  svg {
    display: block;
    user-select: none;
  }

  /* ---- links ---- */
  .link .base {
    fill: none;
    stroke: var(--lvl);
    stroke-width: 2;
    opacity: 0.32;
    transition: opacity var(--t), stroke-width var(--t);
  }

  /* Moving dots only while a command travels the link (see `busy`); idle links are still. */
  .link .flow {
    fill: none;
    stroke: var(--lvl);
    stroke-width: 3;
    stroke-linecap: round;
    stroke-dasharray: 0.5 15;
    opacity: 0;
    transition: opacity 200ms var(--ease-out);
  }

  .link.busy .flow {
    opacity: 0.9;
    animation: flow 0.45s linear infinite;
  }

  .link.busy .base {
    opacity: 0.7;
    stroke-width: 3;
  }

  .link.dim .base {
    opacity: 0.16;
  }

  .link.act-playing .base,
  .link.act-rolling .base {
    opacity: 0.6;
    stroke-width: 2.5;
  }

  .link.st-pending .base {
    stroke: var(--warn);
    stroke-dasharray: 4 7;
    opacity: 0.55;
  }

  .link.st-pending .flow,
  .link.lvl-lost .flow {
    display: none;
  }

  .link.lvl-lost .base {
    stroke-dasharray: 3 8;
    opacity: 0.4;
  }

  .link.leaving,
  .node.leaving {
    opacity: 0;
    transition: opacity 380ms var(--ease-out);
  }

  @keyframes flow {
    to {
      stroke-dashoffset: -15.5;
    }
  }

  /* ---- packets ---- */
  .packet {
    filter: url(#packet-glow);
  }

  .k-cue { fill: var(--go); }
  .k-stop { fill: var(--stop); }
  .k-chat { fill: var(--accent); }
  .k-approve { fill: var(--ok); }

  /* ---- nodes ---- */
  .node {
    outline: none;
  }

  .selectable {
    cursor: pointer;
  }

  .float {
    animation: float 7s ease-in-out infinite;
  }

  .pop,
  .halo,
  .arrive,
  .ring {
    transform-box: fill-box;
    transform-origin: center;
  }

  .pop {
    animation: pop-in 560ms var(--ease-spring) both;
  }

  .ring {
    fill: none;
    stroke: var(--lvl);
    stroke-width: 3;
    opacity: 0.95;
    transition: stroke-width var(--t), stroke var(--t);
  }

  .core {
    stroke: rgb(255 255 255 / 0.18);
    stroke-width: 1;
    transition: filter var(--t), opacity var(--t);
  }

  .role-server .core {
    stroke: color-mix(in srgb, var(--accent) 60%, transparent);
    stroke-width: 2;
  }

  .self .core {
    stroke: var(--text);
    stroke-width: 2.5;
  }

  .halo {
    fill: none;
    stroke: var(--role);
    stroke-width: 3;
    animation: pulse-ring 1.7s var(--ease-out) infinite;
  }

  .act-rolling .halo {
    stroke: var(--live);
  }

  .role-server .halo {
    stroke: var(--accent);
    stroke-width: 2;
    animation-duration: 3.2s;
  }

  .arrive {
    fill: none;
    stroke: var(--text);
    stroke-width: 3;
    animation: arrive 650ms var(--ease-out) forwards;
  }

  .st-pending .ring,
  .st-connecting .ring {
    stroke: var(--warn);
    stroke-dasharray: 5 6;
    animation: spin 7s linear infinite;
  }

  .st-down .core,
  .st-timeout .core,
  .lvl-lost .core {
    filter: grayscale(0.85) brightness(0.75);
  }

  .st-pending .core {
    opacity: 0.6;
  }

  .untargeted .core {
    filter: saturate(0.3) brightness(0.72);
  }

  .untargeted .label {
    opacity: 0.6;
  }

  .targeted .ring {
    stroke-width: 4;
  }

  .selectable:hover .core {
    filter: brightness(1.15);
  }

  .selectable.untargeted:hover .core {
    filter: saturate(0.7) brightness(0.95);
  }

  .node:focus-visible .ring {
    stroke: var(--focus);
    stroke-width: 5;
  }

  .badge circle {
    fill: var(--go);
    stroke: var(--surface);
    stroke-width: 2.5;
  }

  .you rect {
    fill: var(--text);
  }

  .you text {
    fill: var(--bg);
    font-size: 0.66rem;
    font-weight: 800;
    letter-spacing: 0.08em;
    text-anchor: middle;
  }

  .label,
  .sub {
    text-anchor: middle;
    paint-order: stroke;
    stroke: var(--bg);
    stroke-width: 5px;
    stroke-linejoin: round;
  }

  .label {
    font-size: 0.9rem;
    font-weight: 700;
    fill: var(--text);
  }

  .role-server .label {
    font-size: 0.95rem;
  }

  .sub {
    font-size: 0.75rem;
    font-weight: 600;
    fill: var(--text-3);
  }

  .lvl-fair .sub { fill: var(--warn); }
  .lvl-poor .sub { fill: var(--bad); }
  .st-pending .sub { fill: var(--warn); }
  .act-playing .sub { fill: var(--role); }
  .act-rolling .sub { fill: var(--live); }

  @keyframes float {
    0%,
    100% { transform: translateY(0); }
    50% { transform: translateY(-3px); }
  }

  @keyframes pop-in {
    from { transform: scale(0.3); opacity: 0; }
    to { transform: scale(1); opacity: 1; }
  }

  @keyframes arrive {
    from { transform: scale(1); opacity: 0.9; }
    to { transform: scale(1.75); opacity: 0; }
  }

  /* ---- overlays ---- */
  .tip {
    position: absolute;
    z-index: 2;
    /* `translate`, not `transform`: rise-in animates transform, which used to drop the centring
       for its 160 ms, so the card showed beside the node and then jumped */
    translate: -50% 0;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 10rem;
    padding: 0.65rem 0.85rem;
    border-radius: var(--radius);
    background: var(--surface-glass);
    border: 1px solid color-mix(in srgb, var(--role) 40%, var(--border));
    backdrop-filter: blur(12px);
    box-shadow: var(--shadow-pop);
    font-size: 0.8125rem;
    pointer-events: none;
    animation: rise-in 160ms var(--ease-out);
  }

  .tip strong {
    font-size: 0.95rem;
  }

  .tip .kind {
    color: var(--role);
    font-weight: 650;
  }

  .tip .hint {
    color: var(--text-3);
    margin-top: 0.2rem;
  }

  .legend {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
    padding: 0.25rem 0.9rem 0.9rem;
  }

  .legend .chip {
    font-size: 0.75rem;
    min-height: 1.6rem;
  }

  .sw {
    width: 0.65rem;
    height: 0.65rem;
    border-radius: 50%;
    background: var(--role);
  }

  .ln {
    width: 0.9rem;
    height: 0.2rem;
    border-radius: 2px;
    background: var(--lvl);
    margin-left: 0.25rem;
  }
</style>
