// What Send files and Normalize folder share: remembered fields, error text, the Browse button.
import { app } from "../state.svelte";

/** Per-viewer conveniences only; storage can be unavailable (private windows), so both ends swallow errors. */
export function recall<T extends object>(key: string): T {
  try {
    return JSON.parse(localStorage.getItem(key) ?? "{}") ?? {};
  } catch {
    return {} as T;
  }
}

export function remember(key: string, value: object) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // The panel works without it.
  }
}

export const message = (err: unknown) => (err instanceof Error ? err.message : String(err));

/** Asks for a folder and hands the path to `open`; a failed dialog shows through `setError`. */
export async function browseFolder(open: (path: string) => Promise<void>, setError: (text: string) => void) {
  const folders = app.folders;
  if (!folders) return;
  setError("");
  try {
    const path = await folders.pick();
    if (path) await open(path);
  } catch (err) {
    setError(message(err));
  }
}
