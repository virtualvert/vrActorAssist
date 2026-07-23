import { writable, type Writable } from "svelte/store";

export type ConnectionState = "Disconnected" | "Connecting" | "Connected" | { Failed: string };

export interface ChatMessage {
  sender: string;
  text: string;
  timestamp: string;
  isOwn: boolean;
}

export interface AppConfig {
  server_url: string;
  mode: string;
  remember_mode: boolean;
  machine_id: string;
  actor_name: string;
  auto_reconnect: boolean;
  osc_enabled: boolean;
  osc_host: string;
  osc_port: number;
  soundpad_enabled: boolean;
  soundpad_path: string;
  auto_accept_files: boolean;
  receive_dir: string;
  theme: string;
}

export const connectionState: Writable<ConnectionState> = writable("Disconnected");
export const chatMessages: Writable<ChatMessage[]> = writable([]);
export const appConfig: Writable<AppConfig | null> = writable(null);
export const latencyMs: Writable<number> = writable(0);
