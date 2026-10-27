import { clampScale, type Prefs } from "./protocol";

const MIRROR_KEY = "vrcas.prefs";

/**
 * Push preferences onto <html>: theme, UI scale, VR mode and motion. index.html reads the
 * localStorage mirror before first paint, so reopening the window doesn't flash.
 */
export function applyPrefs(prefs: Prefs): void {
  const root = document.documentElement;
  if (prefs.theme === "system") delete root.dataset.theme;
  else root.dataset.theme = prefs.theme;
  root.style.setProperty("--ui-scale", String(clampScale(prefs.scale)));
  if (prefs.vrMode) root.dataset.vr = "on";
  else delete root.dataset.vr;
  const systemReduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (prefs.reduceMotion || systemReduce) root.dataset.motion = "reduce";
  else delete root.dataset.motion;
  try {
    localStorage.setItem(MIRROR_KEY, JSON.stringify(prefs));
  } catch {
    // Storage can be unavailable (private window); the agent still remembers the prefs.
  }
}

export const SCALE_STEP = 0.1;
