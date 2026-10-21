import { describe, expect, test } from "bun:test";
import type { AppState, Peer } from "../protocol";
import { anchorsFor, bezierPoint, centerSelf, curveControl, graphSpecs, minGraphHeight, SERVER_ID } from "./layout";

function peer(id: string, role: Peer["role"], extra: Partial<Peer> = {}): Peer {
  return { id, name: id, role, status: "online", latencyMs: 40, activity: "idle", self: false, caps: [], ...extra };
}

function baseState(extra: Partial<AppState> = {}): AppState {
  return {
    appVersion: "test",
    demo: true,
    role: "director",
    prefs: { theme: "dark", scale: 1, vrMode: false, reduceMotion: false },
    profile: { name: "Dir", serverUrl: "ws://x", hasSecret: true },
    connection: { status: "connected", detail: "", host: "relay", serverVersion: "0.4.0", legacy: false },
    peers: [],
    pending: [],
    targets: [],
    countdown: null,
    actor: null,
    camera: null,
    director: null,
    ...extra,
  };
}

describe("graphSpecs", () => {
  test("server first, then peers sorted director → camera → actor", () => {
    const state = baseState({
      peers: [peer("a1", "actor"), peer("self", "director", { self: true }), peer("c1", "camera")],
    });
    const ids = graphSpecs(state).map((s) => s.id);
    expect(ids).toEqual([SERVER_ID, "self", "c1", "a1"]);
  });

  test("director can target online actors only; pending actors are drawn but not selectable", () => {
    const state = baseState({
      peers: [peer("self", "director", { self: true }), peer("a1", "actor"), peer("c1", "camera")],
      pending: [{ id: "p1", name: "Nova" }],
      targets: ["a1"],
    });
    const byId = Object.fromEntries(graphSpecs(state).map((s) => [s.id, s]));
    expect(byId.a1.selectable).toBe(true);
    expect(byId.a1.targeted).toBe(true);
    expect(byId.c1.selectable).toBe(false);
    expect(byId.p1.status).toBe("pending");
    expect(byId.p1.selectable).toBe(false);
  });

  test("actors never get selectable nodes", () => {
    const state = baseState({ role: "actor", peers: [peer("self", "actor", { self: true }), peer("a2", "actor")] });
    expect(graphSpecs(state).some((s) => s.selectable)).toBe(false);
  });

  test("server reflects the connection", () => {
    const down = graphSpecs(baseState({ connection: { status: "disconnected", detail: "", host: "h", serverVersion: null, legacy: false } }));
    expect(down[0].status).toBe("down");
    const pending = graphSpecs(baseState({ connection: { status: "pending", detail: "", host: "h", serverVersion: null, legacy: true } }));
    expect(pending[0].status).toBe("connecting");
  });

  test("timed-out peers read as lost", () => {
    const state = baseState({ peers: [peer("a1", "actor", { status: "timeout", latencyMs: null })] });
    const a1 = graphSpecs(state).find((s) => s.id === "a1")!;
    expect(a1.level).toBe("lost");
    expect(a1.sub).toBe("No response");
  });
});

describe("anchorsFor", () => {
  const size = { width: 1000, height: 600 };
  const m = { radius: 26, rem: 16 };
  const layout = (peers: Peer[], sz = size) => anchorsFor(graphSpecs(baseState({ peers })), sz, m);

  test("relay in the middle, directors on top, actors at the bottom, cameras on the sides", () => {
    const pts = layout([peer("d0", "director"), peer("a0", "actor"), peer("c0", "camera"), peer("c1", "camera")]);
    expect(pts.get(SERVER_ID)).toEqual({ x: 500, y: 300 });
    expect(pts.get("d0")!.y).toBeLessThan(300);
    expect(pts.get("a0")!.y).toBeGreaterThan(300);
    expect(pts.get("c0")!.x).toBeLessThan(500);
    expect(pts.get("c1")!.x).toBeGreaterThan(500);
  });

  test("every anchor stays inside the box, even with a big cast", () => {
    const peers = Array.from({ length: 14 }, (_, i) => peer(`a${i}`, "actor"))
      .concat([peer("c0", "camera"), peer("c1", "camera"), peer("c2", "camera"), peer("d0", "director"), peer("d1", "director")]);
    for (const sz of [size, { width: 640, height: 420 }, { width: 1600, height: 500 }]) {
      for (const p of layout(peers, sz).values()) {
        expect(p.x).toBeGreaterThanOrEqual(0);
        expect(p.x).toBeLessThanOrEqual(sz.width);
        expect(p.y).toBeGreaterThanOrEqual(0);
        expect(p.y).toBeLessThanOrEqual(sz.height);
      }
    }
  });

  test("actors keep a minimum gap, wrapping into a second row when crowded", () => {
    const pts = [...layout(Array.from({ length: 12 }, (_, i) => peer(`a${i}`, "actor")), { width: 700, height: 600 }).entries()]
      .filter(([id]) => id.startsWith("a"))
      .map(([, p]) => p);
    const rows = new Set(pts.map((p) => Math.round(p.y / 40)));
    expect(rows.size).toBeGreaterThan(1);
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        expect(Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y)).toBeGreaterThan(m.radius * 2);
      }
    }
  });

  test("minimum height leaves room for three bands", () => {
    expect(minGraphHeight(m)).toBeGreaterThan(m.radius * 6);
  });
});

describe("geometry", () => {
  test("centerSelf moves you to the middle of your group", () => {
    const group = [{ id: "me", self: true }, { id: "b", self: false }, { id: "c", self: false }, { id: "d", self: false }];
    expect(centerSelf(group).map((g) => g.id)).toEqual(["b", "c", "me", "d"]);
  });

  test("bezier endpoints hit the link ends", () => {
    const a = { x: 0, y: 0 };
    const b = { x: 100, y: 50 };
    const c = curveControl(a, b);
    expect(bezierPoint(a, c, b, 0)).toEqual(a);
    expect(bezierPoint(a, c, b, 1)).toEqual(b);
  });
});
