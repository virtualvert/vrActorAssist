"""The camera operator's side (spec §8.5): OBS read over obs-websocket, and the VRChat window
matched to OBS's base resolution (§8.5.8, method A, Windows).

Read-only towards OBS so far: video settings and whether it records, polled every POLL_S. The
window is only resized when the operator allowed it, never while OBS records, and put back
when the app closes (or the role changes).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

from . import vrchat_window
from .obs import ObsClient, ObsError
from .vrchat_window import WindowError

POLL_S = 2.0
RETRY_S = 5.0


class CameraError(Exception):
    """A Match / Restore that can't be done; the message is shown to the operator."""


class CameraRuntime:
    def __init__(self, config, changed: Callable[[], None], log: Callable[[str, str], None],
                 window: Any = vrchat_window, open_obs: Callable = ObsClient.open):
        self._config = config
        self._changed = changed
        self._log = log
        self._win = window
        self._open_obs = open_obs
        self._task: asyncio.Task | None = None
        self.obs: ObsClient | None = None
        self.obs_detail = "Not connected"
        self.obs_version: str | None = None
        # {"base": (w, h), "output": (w, h), "fps": float} from GetVideoSettings
        self.video: dict | None = None
        self.recording = False
        self.recording_since: int | None = None
        self.window: vrchat_window.Window | None = None
        # (hwnd, outer rect) from before this app's first resize, for Restore
        self._saved: tuple[int, tuple[int, int, int, int]] | None = None
        self._last_view: dict | None = None

    # ---- lifecycle ------------------------------------------------------------

    async def refresh(self) -> None:
        """Start or stop with the camera role; reconnect when the OBS address or password changed."""
        if self._config.role != "camera":
            await self.close()
            return
        if self.obs is not None:
            await self._drop("Reconnecting with the new settings…")
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._poll())

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
            self._task = None
        if self._saved is not None:
            try:
                await self.restore()
            except CameraError as exc:
                self._log("warning", f"The VRChat window wasn't put back: {exc}")
        if self.obs is not None:
            await self._drop("Not connected")

    # ---- state for the UI -------------------------------------------------------

    def view(self) -> dict:
        """The UI's camera state (CameraLocal in web/src/lib/protocol.ts)."""
        cfg = self._config.obs
        video = self.video or {}
        base = video.get("base")
        win = self.window
        if not self._win.SUPPORTED:
            state = "unsupported"
        elif win is None:
            state = "not_found"
        elif base is None:
            state = "unknown"
        else:
            state = "matched" if win.client == base else "mismatch"
        return {
            "obs": {
                "connected": self.obs is not None,
                "detail": self.obs_detail,
                "url": cfg.url,
                "hasPassword": bool(cfg.password),
                "base": list(base) if base else None,
                "output": list(video["output"]) if video.get("output") else None,
                "fps": video.get("fps"),
            },
            "window": {
                "state": state,
                "size": list(win.client) if win else None,
                "mode": win.mode if win else None,
                "allowResize": cfg.allow_window_resize,
                "canRestore": self._saved is not None,
            },
            "recording": self.recording,
            "recordingSince": self.recording_since,
        }

    # ---- operator actions ---------------------------------------------------------

    async def match(self) -> None:
        """Resize VRChat's client area to OBS's base resolution (Match now)."""
        if not self._win.SUPPORTED:
            raise CameraError("Resizing the VRChat window works on Windows only so far")
        if not self._config.obs.allow_window_resize:
            raise CameraError("Turn on “Let vrcActorSync resize the VRChat window” first")
        if self.obs is None or not self.video:
            raise CameraError("Connect to OBS first: the size comes from its base resolution")
        await self._refuse_while_recording()
        win = await asyncio.to_thread(self._win.find)
        if win is None:
            self.window = None
            raise CameraError("VRChat isn't running, or it has no window")
        width, height = self.video["base"]
        if win.client == (width, height):
            self.window = win
            return
        if self._saved is None or self._saved[0] != win.hwnd:  # a restarted VRChat has a new window
            self._saved = (win.hwnd, win.rect)
        try:
            self.window = await asyncio.to_thread(self._win.resize, win, width, height)
        except WindowError as exc:
            raise CameraError(str(exc)) from exc
        got = self.window.client
        if got == (width, height):
            self._log("success", f"VRChat window resized to {width}×{height} (was {win.client[0]}×{win.client[1]})")
        else:
            self._log("warning", f"Asked for {width}×{height}, VRChat's window ended at {got[0]}×{got[1]}")

    async def restore(self) -> None:
        """Put the window back the way it was before this app's first resize."""
        if self._saved is None:
            raise CameraError("This app didn't resize the VRChat window, so there's nothing to put back")
        await self._refuse_while_recording()
        hwnd, rect = self._saved
        try:
            win = await asyncio.to_thread(self._win.place, hwnd, rect)
        except WindowError as exc:
            raise CameraError(str(exc)) from exc
        self._saved = None
        if win is None:
            self._log("info", "VRChat was restarted since the resize, so there's nothing to put back")
            return
        self.window = win
        self._log("info", f"VRChat window put back to {win.client[0]}×{win.client[1]}")

    async def ready_checks(self) -> list[dict]:
        """This camera's part of a ready check (§8.8.2): set up first, then report. The window is
        matched when the operator allowed resizing (the spec's profile `vrchat_window.match` isn't
        built yet). Whatever couldn't be fixed comes back as a red check, never as an error."""
        problem = ""
        try:
            if self._win.SUPPORTED:
                self.window = await asyncio.to_thread(self._win.find)
            if self.view()["window"]["state"] == "mismatch":
                if self._config.obs.allow_window_resize:
                    await self.match()
                else:
                    problem = "resizing isn't allowed on that PC"
        except (CameraError, WindowError, OSError) as exc:
            problem = str(exc)
        view = self.view()
        win, base = view["window"], view["obs"]["base"]
        if win["state"] in ("matched", "mismatch"):
            detail = f"window {win['size'][0]}×{win['size'][1]}"
            if win["state"] == "mismatch":
                detail += f", recording {base[0]}×{base[1]}" + (f" — {problem}" if problem else "")
        else:
            detail = {
                "unknown": "No recording size to compare with: OBS isn't connected",
                "not_found": "VRChat isn't running, or it has no window",
                "unsupported": "The window check works on Windows only so far",
            }[win["state"]]
        return [
            {"id": "obs", "ok": self.obs is not None, "detail": self.obs_detail},
            {"id": "window", "ok": win["state"] == "matched", "detail": detail},
        ]

    async def _refuse_while_recording(self) -> None:
        """Resizing stalls the game for a moment: ask OBS now rather than trusting the last poll."""
        recording = self.recording
        if self.obs is not None:
            try:
                recording = bool((await self.obs.request("GetRecordStatus")).get("outputActive"))
            except ObsError:
                pass
        if recording:
            raise CameraError("OBS is recording; resizing VRChat now would stall the take")

    # ---- polling ----------------------------------------------------------------------

    async def _poll(self) -> None:
        while True:
            try:
                if self.obs is None:
                    await self._connect()
                if self.obs is not None:
                    await self._read_obs()
                self.window = await asyncio.to_thread(self._win.find) if self._win.SUPPORTED else None
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # keep polling: a dead loop would freeze the camera view
                self._log("warning", f"Camera check failed: {exc}")
            view = self.view()
            if view != self._last_view:
                self._last_view = view
                self._changed()
            await asyncio.sleep(POLL_S if self.obs is not None else RETRY_S)

    async def _connect(self) -> None:
        cfg = self._config.obs
        try:
            client = await self._open_obs(cfg.url, cfg.password)
        except ObsError as exc:
            if str(exc) != self.obs_detail:
                self.obs_detail = str(exc)
                self._log("warning", f"OBS: {exc}")
            return
        try:
            version = await client.request("GetVersion")
        except ObsError as exc:
            await client.close()
            self.obs_detail = str(exc)
            return
        self.obs = client
        self.obs_version = str(version.get("obsVersion") or "")
        self.obs_detail = f"OBS {self.obs_version} · obs-websocket {client.version}"
        self._log("success", f"Connected to {self.obs_detail}")

    async def _read_obs(self) -> None:
        try:
            video = await self.obs.request("GetVideoSettings")
            record = await self.obs.request("GetRecordStatus")
        except ObsError as exc:
            self._log("warning", f"OBS: {exc}")
            await self._drop(str(exc))
            return
        fps = (video.get("fpsNumerator") or 0) / (video.get("fpsDenominator") or 1)
        self.video = {
            "base": (video.get("baseWidth"), video.get("baseHeight")),
            "output": (video.get("outputWidth"), video.get("outputHeight")),
            "fps": round(fps, 2),
        }
        active = bool(record.get("outputActive"))
        if active and not self.recording:
            self.recording_since = int(time.time() * 1000) - int(record.get("outputDuration") or 0)
        self.recording = active
        if not active:
            self.recording_since = None

    async def _drop(self, detail: str) -> None:
        client, self.obs = self.obs, None
        self.video = None
        self.recording, self.recording_since = False, None
        self.obs_detail = detail
        if client is not None:
            await client.close()
