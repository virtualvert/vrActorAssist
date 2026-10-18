import { Clapperboard, Drama, Video } from "@lucide/svelte";
import type { Component } from "svelte";
import type { Role } from "./protocol";

export interface RoleInfo {
  id: Role;
  label: string;
  short: string;
  description: string;
  icon: Component;
}

export const ROLE_INFO: Record<Role, RoleInfo> = {
  director: {
    id: "director",
    label: "Director",
    short: "Director",
    description: "Run the scene: approve the cast, call cues and see everyone at a glance.",
    icon: Clapperboard as unknown as Component,
  },
  actor: {
    id: "actor",
    label: "Actor",
    short: "Actor",
    description: "Receive cues, play your sounds in Soundpad and fire avatar parameters on time.",
    icon: Drama as unknown as Component,
  },
  camera: {
    id: "camera",
    label: "Camera Operator",
    short: "Camera",
    description: "Keep your OBS in sync with the director and roll on cue.",
    icon: Video as unknown as Component,
  },
};

export const ROLE_ORDER: Role[] = ["director", "actor", "camera"];
