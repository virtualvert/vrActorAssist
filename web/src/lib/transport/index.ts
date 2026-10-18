import type { Role } from "../protocol";
import { AgentTransport } from "./agent";
import { DemoTransport } from "./demo";
import type { Transport } from "./types";

const ROLES: Role[] = ["director", "actor", "camera"];

/**
 * Pick how this page is driven:
 *  - `?demo` or `?demo=<role>` forces the simulated session;
 *  - otherwise use the local agent when it is serving this page (/api/ping answers);
 *  - otherwise fall back to the demo so the UI is still explorable.
 */
export async function chooseTransport(): Promise<Transport> {
  const params = new URLSearchParams(location.search);
  if (params.has("demo")) {
    const role = params.get("demo") as Role | null;
    return new DemoTransport(role && ROLES.includes(role) ? role : undefined);
  }
  const ping = await fetch("/api/ping", { cache: "no-store" })
    .then((res) => (res.ok ? (res.json() as Promise<{ app?: string }>) : null))
    .catch(() => null);
  if (ping?.app === "vrcActorSync") return new AgentTransport();
  return new DemoTransport();
}

export type { Transport, LinkState } from "./types";
