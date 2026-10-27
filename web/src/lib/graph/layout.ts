// Pure layout helpers for the connection graph (no DOM), so they can be unit-tested.
//
// The relay sits in the middle. Each role gets its own band so the picture reads the same
// every time: directors along the top, actors along the bottom, camera operators on the sides.

import { latencyLevel, peerSubtitle, type LatencyLevel } from "../format";
import type { Activity, AppState, PeerStatus, Role } from "../protocol";

export const SERVER_ID = "server";

export type NodeKind = Role | "server";

export interface GraphNodeSpec {
  id: string;
  kind: NodeKind;
  label: string;
  sub: string;
  level: LatencyLevel;
  status: PeerStatus | "up" | "down" | "connecting";
  activity: Activity;
  self: boolean;
  /** Director view: receives Go / Stop. */
  targeted: boolean;
  /** Director view: clicking toggles `targeted`. */
  selectable: boolean;
}

export interface Point {
  x: number;
  y: number;
}

export interface Size {
  width: number;
  height: number;
}

/** Fields of the relay and pending-actor nodes: nothing happening, nothing to click. */
const INERT = { activity: "idle", self: false, targeted: false, selectable: false } as const;

const ROLE_ORDER: Role[] = ["director", "camera", "actor"];

/** Turn app state into the list of nodes to draw (server first). */
export function graphSpecs(state: AppState): GraphNodeSpec[] {
  const conn = state.connection;
  const serverStatus = conn.status === "connected" ? "up" : conn.status === "connecting" || conn.status === "pending" ? "connecting" : "down";
  const serverSub =
    conn.status === "connected" ? (conn.serverVersion ? `v${conn.serverVersion}` : "Online") : conn.status === "pending" ? "Awaiting approval" : conn.status === "connecting" ? "Connecting…" : "Offline";
  const specs: GraphNodeSpec[] = [
    {
      id: SERVER_ID,
      kind: "server",
      label: conn.host || "Relay",
      sub: serverSub,
      level: serverStatus === "up" ? "good" : "lost",
      status: serverStatus,
      ...INERT,
    },
  ];

  const isDirector = state.role === "director";
  const targets = new Set(state.targets);
  const peers = [...state.peers].sort((a, b) => ROLE_ORDER.indexOf(a.role) - ROLE_ORDER.indexOf(b.role));
  for (const p of peers) {
    const selectable = isDirector && !p.self && p.role === "actor" && p.status !== "pending";
    specs.push({
      id: p.self ? "self" : p.id,
      kind: p.role,
      label: p.name,
      sub: p.self && p.status === "online" && p.activity === "idle" ? (conn.status === "connected" ? "You" : "You · offline") : peerSubtitle(p),
      level: p.self && conn.status !== "connected" ? "lost" : latencyLevel(p.status, p.latencyMs),
      status: p.self && conn.status === "pending" ? "pending" : p.status,
      activity: p.activity,
      self: p.self,
      targeted: selectable && targets.has(p.id),
      selectable,
    });
  }

  if (isDirector) {
    for (const pending of state.pending) {
      specs.push({
        id: pending.id,
        kind: "actor",
        label: pending.name,
        sub: "Wants to join",
        level: "unknown",
        status: "pending",
        ...INERT,
      });
    }
  }
  return specs;
}

/** Order a role group so "you" sit in the middle of your sector. */
export function centerSelf<T extends { self: boolean }>(group: T[]): T[] {
  const selfIndex = group.findIndex((n) => n.self);
  if (selfIndex < 0 || group.length < 3) return group;
  const rest = group.filter((_, i) => i !== selfIndex);
  const mid = Math.floor(group.length / 2);
  return [...rest.slice(0, mid), group[selfIndex], ...rest.slice(mid)];
}

export interface Metrics {
  /** Node radius in px. */
  radius: number;
  /** 1rem in px (tracks the UI scale). */
  rem: number;
}

/** The numbers the actor rows and the camera columns share (px). */
function rowBand(w: number, m: Metrics, hasCameras: boolean) {
  const sideX = m.radius + m.rem * 3.2;
  const minGap = m.radius * 2 + m.rem * 4.2;
  // Rows leave the side columns to the camera operators when there's room for both.
  const rowLeft = hasCameras && w >= minGap * 5 ? sideX * 2 + m.rem : sideX * 0.6;
  return { sideX, minGap, rowWidth: Math.max(w - rowLeft * 2, 0) };
}

/**
 * Stage layout: directors along the top (the director's chair), actors along the bottom
 * (the stage), camera operators on the left and right, the relay in the middle.
 * Rows curve slightly, and long actor rows wrap into two staggered rows.
 */
export function anchorsFor(specs: GraphNodeSpec[], size: Size, m: Metrics): Map<string, Point> {
  const out = new Map<string, Point>();
  const { width: w, height: h } = size;
  const cx = w / 2;
  const cy = h / 2;
  const groups: Record<NodeKind, GraphNodeSpec[]> = { server: [], director: [], actor: [], camera: [] };
  for (const s of specs) groups[s.kind].push(s);

  const { sideX, minGap, rowWidth } = rowBand(w, m, groups.camera.length > 0);
  const topY = m.radius + m.rem * 2.2;
  const bottomY = h - m.radius - m.rem * 2.9;
  const rowGap = m.radius * 2 + m.rem * 3;

  // Spread a row centred on cx, never wider than the usable width.
  const spreadRow = (count: number): number[] => {
    if (count === 0) return [];
    if (count === 1) return [cx];
    const gap = Math.min(minGap * 1.35, rowWidth / (count - 1));
    const total = gap * (count - 1);
    return Array.from({ length: count }, (_, i) => cx - total / 2 + gap * i);
  };
  const curve = (x: number, depth: number) => {
    const t = (x - cx) / Math.max(w / 2, 1);
    return depth * t * t;
  };

  for (const s of groups.server) out.set(s.id, { x: cx, y: cy });

  const directors = centerSelf(groups.director);
  spreadRow(directors.length).forEach((x, i) => out.set(directors[i].id, { x, y: topY + curve(x, h * 0.08) }));

  // Actors fill rows from the front (bottom) backwards, as many per row as fit.
  const actors = centerSelf(groups.actor);
  const perRow = actorsPerRow(rowWidth, minGap);
  const rows = Math.max(1, Math.ceil(actors.length / perRow));
  // The canvas grows to fit the rows (minGraphHeight); if it can't, squeeze them below the relay.
  const band = bottomY - (cy + m.radius * 2.5);
  const gapY = rows > 1 ? Math.min(rowGap, Math.max(band / (rows - 1), m.radius)) : 0;
  const clampY = (y: number) => Math.min(Math.max(y, m.radius), h - m.radius);
  for (let r = 0; r < rows; r++) {
    const row = actors.filter((_, i) => i % rows === r);
    spreadRow(row.length).forEach((x, i) => out.set(row[i].id, { x, y: clampY(bottomY - r * gapY - curve(x, h * 0.08)) }));
  }

  const left = groups.camera.filter((_, i) => i % 2 === 0);
  const right = groups.camera.filter((_, i) => i % 2 === 1);
  const column = (list: GraphNodeSpec[], x: number) => {
    const span = Math.max(0, bottomY - (rows - 1) * gapY - topY - m.radius * 4);
    const gap = list.length > 1 ? Math.min(minGap, span / (list.length - 1)) : 0;
    const total = gap * (list.length - 1);
    list.forEach((s, i) => out.set(s.id, { x, y: cy - total / 2 + gap * i }));
  };
  column(left, sideX);
  column(right, w - sideX);
  return out;
}

function actorsPerRow(rowWidth: number, minGap: number): number {
  return Math.max(1, Math.floor(rowWidth / minGap) + 1);
}

/** How many actor rows the stage layout uses at this width (the canvas grows to fit them). */
export function actorRows(actorCount: number, width: number, m: Metrics, hasCameras: boolean): number {
  const { rowWidth, minGap } = rowBand(width, m, hasCameras);
  return Math.max(1, Math.ceil(actorCount / actorsPerRow(rowWidth, minGap)));
}

/** Smallest graph height that keeps the three bands (directors, relay, actors) apart. */
export function minGraphHeight(m: Metrics, rows = 1): number {
  return m.radius * 7 + m.rem * 9 + (rows - 1) * (m.radius * 2 + m.rem * 3);
}

/** Control point for a gently curved link from a to b. */
export function curveControl(a: Point, b: Point, bend = 0.12): Point {
  const mx = (a.x + b.x) / 2;
  const my = (a.y + b.y) / 2;
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  // Perpendicular, always bending the same way relative to the direction of travel.
  return { x: mx - dy * bend, y: my + dx * bend };
}

export function bezierPoint(p0: Point, c: Point, p1: Point, t: number): Point {
  const u = 1 - t;
  return {
    x: u * u * p0.x + 2 * u * t * c.x + t * t * p1.x,
    y: u * u * p0.y + 2 * u * t * c.y + t * t * p1.y,
  };
}

export function linkPath(a: Point, b: Point): string {
  const c = curveControl(a, b);
  return `M${a.x.toFixed(1)},${a.y.toFixed(1)} Q${c.x.toFixed(1)},${c.y.toFixed(1)} ${b.x.toFixed(1)},${b.y.toFixed(1)}`;
}

export function easeInOut(t: number): number {
  return t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
}
