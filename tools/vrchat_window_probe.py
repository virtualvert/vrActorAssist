#!/usr/bin/env python3
"""Probe whether the VRChat window can be matched to an OBS recording resolution.

Checks the Windows rows of Appendix C in
docs/superpowers/specs/2026-10-17-vrcActorSync-web-ui-agent-design.md (§8.5.8).
Windows only, standard library only (ctypes).

Only window-manager calls are used. VRChat runs Easy Anti-Cheat, so this script never opens
the VRChat process, never reads or writes its memory and never injects anything: VRChat.exe is
found through a Toolhelp process snapshot (names and ids only) and EnumWindows.

The default run is read-only: it finds VRChat's window and reports its class, title, window
and client size, styles (bordered / borderless), DPI awareness, and the monitor it's on.

  --resize W H  set the window's client area to W x H physical pixels, keeping its position.
                The geometry from before the first resize is saved to
                tools/probe-results/window-restore.json (kept until --restore).
                Reads the size back right away, after 0.5 s and after 3 s.
                Don't use it while OBS is recording: resizing briefly stalls the game.
  --restore     put the saved geometry back and delete the restore file
  --json FILE   also write the results as JSON (includes the window title and monitor names)

Every run prints the matching Steam launch options for VRChat.

Examples:
  python tools\\vrchat_window_probe.py
  python tools\\vrchat_window_probe.py --resize 2560 1440 --json tools\\probe-results\\resize-monitor.json
  python tools\\vrchat_window_probe.py --restore
"""

import argparse
import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

PROCESS_NAME = "vrchat.exe"
UNITY_CLASS = "UnityWndClass"
RESTORE_FILE = Path(__file__).resolve().parent / "probe-results" / "window-restore.json"
SET_POS_TIMEOUT_S = 5.0
READBACK_AT_S = (0.0, 0.5, 3.0)

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    dwmapi = ctypes.WinDLL("dwmapi")
    try:
        shcore = ctypes.WinDLL("shcore")
    except OSError:
        shcore = None

    LONG_PTR = ctypes.c_ssize_t
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                         ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    class MONITORINFOEXW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]

    class DEVMODEW(ctypes.Structure):
        _fields_ = [
            ("dmDeviceName", wintypes.WCHAR * 32),
            ("dmSpecVersion", wintypes.WORD), ("dmDriverVersion", wintypes.WORD),
            ("dmSize", wintypes.WORD), ("dmDriverExtra", wintypes.WORD), ("dmFields", wintypes.DWORD),
            ("dmPositionX", wintypes.LONG), ("dmPositionY", wintypes.LONG),
            ("dmDisplayOrientation", wintypes.DWORD), ("dmDisplayFixedOutput", wintypes.DWORD),
            ("dmColor", wintypes.SHORT), ("dmDuplex", wintypes.SHORT), ("dmYResolution", wintypes.SHORT),
            ("dmTTOption", wintypes.SHORT), ("dmCollate", wintypes.SHORT),
            ("dmFormName", wintypes.WCHAR * 32), ("dmLogPixels", wintypes.WORD),
            ("dmBitsPerPel", wintypes.DWORD), ("dmPelsWidth", wintypes.DWORD), ("dmPelsHeight", wintypes.DWORD),
            ("dmDisplayFlags", wintypes.DWORD), ("dmDisplayFrequency", wintypes.DWORD),
            ("dmICMMethod", wintypes.DWORD), ("dmICMIntent", wintypes.DWORD), ("dmMediaType", wintypes.DWORD),
            ("dmDitherType", wintypes.DWORD), ("dmReserved1", wintypes.DWORD), ("dmReserved2", wintypes.DWORD),
            ("dmPanningWidth", wintypes.DWORD), ("dmPanningHeight", wintypes.DWORD),
        ]

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    def _fn(dll, name, restype, *argtypes):
        func = getattr(dll, name)
        func.restype = restype
        func.argtypes = argtypes
        return func

    EnumWindows = _fn(user32, "EnumWindows", wintypes.BOOL, WNDENUMPROC, wintypes.LPARAM)
    EnumDisplayMonitors = _fn(user32, "EnumDisplayMonitors", wintypes.BOOL,
                              wintypes.HDC, ctypes.POINTER(wintypes.RECT), MONITORENUMPROC, wintypes.LPARAM)
    GetWindowThreadProcessId = _fn(user32, "GetWindowThreadProcessId", wintypes.DWORD,
                                   wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    IsWindow = _fn(user32, "IsWindow", wintypes.BOOL, wintypes.HWND)
    IsWindowVisible = _fn(user32, "IsWindowVisible", wintypes.BOOL, wintypes.HWND)
    IsIconic = _fn(user32, "IsIconic", wintypes.BOOL, wintypes.HWND)
    IsZoomed = _fn(user32, "IsZoomed", wintypes.BOOL, wintypes.HWND)
    GetClassNameW = _fn(user32, "GetClassNameW", ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    GetWindowTextW = _fn(user32, "GetWindowTextW", ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    GetWindowRect = _fn(user32, "GetWindowRect", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    GetClientRect = _fn(user32, "GetClientRect", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    ClientToScreen = _fn(user32, "ClientToScreen", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.POINT))
    GetWindowLongPtrW = _fn(user32, "GetWindowLongPtrW" if ctypes.sizeof(ctypes.c_void_p) == 8 else "GetWindowLongW",
                            LONG_PTR, wintypes.HWND, ctypes.c_int)
    GetDpiForWindow = _fn(user32, "GetDpiForWindow", wintypes.UINT, wintypes.HWND)
    GetWindowDpiAwarenessContext = _fn(user32, "GetWindowDpiAwarenessContext", ctypes.c_void_p, wintypes.HWND)
    GetThreadDpiAwarenessContext = _fn(user32, "GetThreadDpiAwarenessContext", ctypes.c_void_p)
    GetAwarenessFromDpiAwarenessContext = _fn(user32, "GetAwarenessFromDpiAwarenessContext", ctypes.c_int,
                                              ctypes.c_void_p)
    SetProcessDpiAwarenessContext = _fn(user32, "SetProcessDpiAwarenessContext", wintypes.BOOL, ctypes.c_void_p)
    AdjustWindowRectExForDpi = _fn(user32, "AdjustWindowRectExForDpi", wintypes.BOOL,
                                   ctypes.POINTER(wintypes.RECT), wintypes.DWORD, wintypes.BOOL,
                                   wintypes.DWORD, wintypes.UINT)
    SetWindowPos = _fn(user32, "SetWindowPos", wintypes.BOOL, wintypes.HWND, wintypes.HWND,
                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
    MonitorFromWindow = _fn(user32, "MonitorFromWindow", wintypes.HMONITOR, wintypes.HWND, wintypes.DWORD)
    GetMonitorInfoW = _fn(user32, "GetMonitorInfoW", wintypes.BOOL, wintypes.HMONITOR,
                          ctypes.POINTER(MONITORINFOEXW))
    EnumDisplaySettingsW = _fn(user32, "EnumDisplaySettingsW", wintypes.BOOL, wintypes.LPCWSTR, wintypes.DWORD,
                               ctypes.POINTER(DEVMODEW))
    DwmGetWindowAttribute = _fn(dwmapi, "DwmGetWindowAttribute", ctypes.c_long, wintypes.HWND, wintypes.DWORD,
                                ctypes.c_void_p, wintypes.DWORD)
    CreateToolhelp32Snapshot = _fn(kernel32, "CreateToolhelp32Snapshot", wintypes.HANDLE,
                                   wintypes.DWORD, wintypes.DWORD)
    Process32FirstW = _fn(kernel32, "Process32FirstW", wintypes.BOOL, wintypes.HANDLE,
                          ctypes.POINTER(PROCESSENTRY32W))
    Process32NextW = _fn(kernel32, "Process32NextW", wintypes.BOOL, wintypes.HANDLE,
                         ctypes.POINTER(PROCESSENTRY32W))
    CloseHandle = _fn(kernel32, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)
    if shcore is not None:
        GetDpiForMonitor = _fn(shcore, "GetDpiForMonitor", ctypes.c_long, wintypes.HMONITOR, ctypes.c_int,
                               ctypes.POINTER(wintypes.UINT), ctypes.POINTER(wintypes.UINT))
        SetProcessDpiAwareness = _fn(shcore, "SetProcessDpiAwareness", ctypes.c_long, ctypes.c_int)

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MAXIMIZEBOX = 0x00010000
WS_EX_TOPMOST = 0x00000008
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
DWMWA_EXTENDED_FRAME_BOUNDS = 9
MONITOR_DEFAULTTONEAREST = 2
MONITORINFOF_PRIMARY = 1
ENUM_CURRENT_SETTINGS = -1
TH32CS_SNAPPROCESS = 0x2
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value if sys.platform == "win32" else -1
AWARENESS = {-1: "invalid", 0: "unaware", 1: "system aware", 2: "per-monitor aware"}


class Report:
    def __init__(self):
        self.data = {"probe_version": 1, "checks": {}, "notes": []}
        self.failures = 0

    def section(self, title):
        print(f"\n== {title} ==")

    def check(self, name, ok, detail, **extra):
        """ok: True = pass, False = fail, None = information only."""
        mark = {True: "OK  ", False: "FAIL", None: "INFO"}[ok]
        print(f"  [{mark}] {name}: {detail}")
        self.data["checks"][name] = dict(ok=ok, detail=detail, **extra)
        if ok is False:
            self.failures += 1

    def note(self, text):
        print(f"  NOTE: {text}")
        self.data["notes"].append(text)


def rect_list(rect):
    return [rect.left, rect.top, rect.right, rect.bottom]


def size_of(rect):
    return rect.right - rect.left, rect.bottom - rect.top


def make_dpi_aware(rep):
    """Per-monitor v2, so every size below is in physical pixels."""
    how = None
    if SetProcessDpiAwarenessContext(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)):
        how = "SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)"
    elif shcore is not None and SetProcessDpiAwareness(2) == 0:
        how = "SetProcessDpiAwareness(PROCESS_PER_MONITOR_DPI_AWARE)"
    awareness = GetAwarenessFromDpiAwarenessContext(GetThreadDpiAwarenessContext())
    rep.check("Probe DPI awareness", awareness == 2, f"{AWARENESS.get(awareness, awareness)} via {how or 'nothing (call failed)'}")


def process_ids(name):
    """Process ids by executable name, from a Toolhelp snapshot (never opens the processes)."""
    snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    ids = set()
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == name:
                ids.add(entry.th32ProcessID)
            ok = Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        CloseHandle(snapshot)
    return ids


def windows_of(pids):
    found = []

    @WNDENUMPROC
    def callback(hwnd, _):
        pid = wintypes.DWORD()
        GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids:
            found.append((hwnd, pid.value))
        return True

    EnumWindows(callback, 0)
    return found


def text_of(func, hwnd):
    buf = ctypes.create_unicode_buffer(512)
    func(hwnd, buf, len(buf))
    return buf.value


def monitor_info(hmonitor):
    info = MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(MONITORINFOEXW)
    if not GetMonitorInfoW(hmonitor, ctypes.byref(info)):
        return None
    mode = DEVMODEW()
    mode.dmSize = ctypes.sizeof(DEVMODEW)
    refresh = mode_size = None
    if EnumDisplaySettingsW(info.szDevice, ENUM_CURRENT_SETTINGS, ctypes.byref(mode)):
        refresh = mode.dmDisplayFrequency
        mode_size = [mode.dmPelsWidth, mode.dmPelsHeight]
    dpi = None
    if shcore is not None:
        dx, dy = wintypes.UINT(), wintypes.UINT()
        if GetDpiForMonitor(hmonitor, 0, ctypes.byref(dx), ctypes.byref(dy)) == 0:
            dpi = dx.value
    width, height = size_of(info.rcMonitor)
    return {
        "device": info.szDevice,
        "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
        "rect": rect_list(info.rcMonitor),
        "size": [width, height],
        "work_area": rect_list(info.rcWork),
        "mode_size": mode_size,
        "refresh_hz": refresh,
        "dpi": dpi,
        "scale_percent": round(dpi / 96 * 100) if dpi else None,
    }


def all_monitors():
    handles = []

    @MONITORENUMPROC
    def callback(hmonitor, hdc, rect, _):
        handles.append(hmonitor)
        return True

    EnumDisplayMonitors(None, None, callback, 0)
    return [m for m in (monitor_info(h) for h in handles) if m]


def describe_window(hwnd):
    rect, client, frame = wintypes.RECT(), wintypes.RECT(), wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(rect))
    GetClientRect(hwnd, ctypes.byref(client))
    origin = wintypes.POINT(0, 0)
    ClientToScreen(hwnd, ctypes.byref(origin))
    has_frame = DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(frame), ctypes.sizeof(frame)) == 0
    style = GetWindowLongPtrW(hwnd, GWL_STYLE) & 0xFFFFFFFF
    exstyle = GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
    awareness = GetAwarenessFromDpiAwarenessContext(GetWindowDpiAwarenessContext(hwnd))
    monitor = monitor_info(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST))
    client_w, client_h = size_of(client)
    window = {
        "hwnd": int(hwnd),
        "class": text_of(GetClassNameW, hwnd),
        "title": text_of(GetWindowTextW, hwnd),
        "visible": bool(IsWindowVisible(hwnd)),
        "minimized": bool(IsIconic(hwnd)),
        "maximized": bool(IsZoomed(hwnd)),
        "window_rect": rect_list(rect),
        "window_size": list(size_of(rect)),
        "visible_frame": rect_list(frame) if has_frame else None,
        "client_origin": [origin.x, origin.y],
        "client_size": [client_w, client_h],
        "style": f"0x{style:08X}",
        "exstyle": f"0x{exstyle:08X}",
        "style_value": style,
        "exstyle_value": exstyle,
        "popup": bool(style & WS_POPUP),
        "caption": (style & WS_CAPTION) == WS_CAPTION,
        "resizable_frame": bool(style & WS_THICKFRAME),
        "topmost": bool(exstyle & WS_EX_TOPMOST),
        "dpi": GetDpiForWindow(hwnd),
        "dpi_awareness": AWARENESS.get(awareness, str(awareness)),
        "monitor": monitor,
    }
    window["mode"] = window_mode(window)
    return window


def window_mode(w):
    if w["minimized"]:
        return "minimized"
    covers = w["monitor"] and w["window_rect"] == w["monitor"]["rect"]
    if w["popup"] and not w["caption"]:
        return "borderless fullscreen" if covers else "borderless window"
    if w["maximized"]:
        return "maximized window"
    return "bordered window"


def find_vrchat(rep, quiet=False):
    """The main VRChat window: visible, preferably Unity's class, the largest one."""
    pids = process_ids(PROCESS_NAME)
    if not pids:
        rep.check("VRChat.exe process", False, "not running (start VRChat in desktop mode)")
        return None
    candidates = [(hwnd, pid) for hwnd, pid in windows_of(pids) if IsWindowVisible(hwnd)]
    if not candidates:
        rep.check("VRChat window", False, f"VRChat.exe (pid {sorted(pids)}) has no visible window")
        return None
    described = [describe_window(hwnd) | {"pid": pid} for hwnd, pid in candidates]
    described.sort(key=lambda w: (w["class"] == UNITY_CLASS, w["client_size"][0] * w["client_size"][1]), reverse=True)
    main = described[0]
    if not quiet:
        rep.check("VRChat.exe process", True, f"pid {', '.join(map(str, sorted(pids)))} (from a process snapshot)")
        rep.check("Visible VRChat windows", None, ", ".join(f"{w['class']!r} {w['client_size'][0]}x{w['client_size'][1]}"
                                                           for w in described),
                  windows=[{k: w[k] for k in ("hwnd", "class", "title", "client_size")} for w in described])
    return main


def report_window(rep, w, label="VRChat window"):
    m = w["monitor"] or {}
    rep.check(f"{label}: class", w["class"] == UNITY_CLASS, f"{w['class']!r} (expected {UNITY_CLASS!r}), title {w['title']!r}")
    rep.check(f"{label}: client area", None,
              f"{w['client_size'][0]}x{w['client_size'][1]} physical px at ({w['client_origin'][0]}, {w['client_origin'][1]})",
              window=w)
    rep.check(f"{label}: window rect", None,
              f"{w['window_size'][0]}x{w['window_size'][1]} at {w['window_rect']}"
              + (f", visible frame {w['visible_frame']}" if w["visible_frame"] else ""))
    rep.check(f"{label}: mode", None,
              f"{w['mode']}; style {w['style']} (popup {w['popup']}, caption {w['caption']}, "
              f"resizable {w['resizable_frame']}), exstyle {w['exstyle']}")
    rep.check(f"{label}: DPI", None, f"window DPI {w['dpi']}, VRChat is {w['dpi_awareness']}")
    if w["dpi_awareness"] == "unaware" and m.get("dpi") and m["dpi"] != 96:
        rep.note("VRChat is DPI-unaware on a scaled monitor: Windows stretches its output, so the "
                 "render size is smaller than the client area.")
    if m:
        rep.check(f"{label}: monitor", None,
                  f"{m['device']} {m['size'][0]}x{m['size'][1]} at {m['rect'][:2]}, {m['refresh_hz']} Hz, "
                  f"{m['scale_percent']} % scaling{', primary' if m['primary'] else ''}")
        if m.get("mode_size") and m["mode_size"] != m["size"]:
            rep.note(f"Display mode {m['mode_size']} differs from the monitor rect {m['size']}.")


def launch_options(width, height):
    return f"-screen-width {width} -screen-height {height} -screen-fullscreen 0 -popupwindow"


def outer_size_for(w, width, height):
    rect = wintypes.RECT(0, 0, width, height)
    if not AdjustWindowRectExForDpi(ctypes.byref(rect), w["style_value"], False, w["exstyle_value"], w["dpi"]):
        raise ctypes.WinError(ctypes.get_last_error())
    return size_of(rect)


def set_window_pos(hwnd, x, y, cx, cy, flags):
    """SetWindowPos waits for VRChat's window thread; run it on a thread so a busy game can't hang us.
    Returns (ok, error, elapsed_ms) or None on timeout."""
    result = {}

    def worker():
        start = time.perf_counter()
        ok = SetWindowPos(hwnd, None, x, y, cx, cy, flags)
        result.update(ok=bool(ok), error=ctypes.get_last_error() if not ok else 0,
                      ms=(time.perf_counter() - start) * 1000)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(SET_POS_TIMEOUT_S)
    if thread.is_alive():
        return None
    return result["ok"], result["error"], result["ms"]


def read_back(rep, hwnd, target, label):
    readings = []
    start = time.perf_counter()
    for at in READBACK_AT_S:
        delay = start + at - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        if not IsWindow(hwnd):
            rep.check(f"{label} after {at:g} s", False, "the window is gone")
            return readings
        w = describe_window(hwnd)
        size = w["client_size"]
        readings.append({"after_s": at, "client_size": size, "window_rect": w["window_rect"], "mode": w["mode"]})
        ok = size == list(target) if target else None
        rep.check(f"{label} after {at:g} s", ok,
                  f"client {size[0]}x{size[1]}, window {w['window_size'][0]}x{w['window_size'][1]} at {w['window_rect'][:2]}"
                  + (f" (wanted {target[0]}x{target[1]})" if target and not ok else ""))
    return readings


def run_resize(rep, w, width, height):
    rep.section(f"Resize client area to {width}x{height}")
    if w["minimized"] or w["maximized"] or w["mode"] == "borderless fullscreen":
        rep.check("Resize", False, f"VRChat is a {w['mode']}; switch it to a normal window first")
        return
    if RESTORE_FILE.exists():
        saved = json.loads(RESTORE_FILE.read_text(encoding="utf-8"))
        rep.check("Restore point", None, f"keeping the one from {saved['saved_at']} "
                                         f"(client {saved['client_size'][0]}x{saved['client_size'][1]})")
    else:
        RESTORE_FILE.parent.mkdir(parents=True, exist_ok=True)
        saved = {k: w[k] for k in ("hwnd", "pid", "class", "title", "window_rect", "client_size", "style", "exstyle")}
        saved["saved_at"] = datetime.now().isoformat(timespec="seconds")
        RESTORE_FILE.write_text(json.dumps(saved, indent=2, ensure_ascii=False), encoding="utf-8")
        rep.check("Restore point", None, f"saved to {RESTORE_FILE}")

    outer_w, outer_h = outer_size_for(w, width, height)
    m = w["monitor"] or {}
    rep.check("Outer size for that client area", None,
              f"{outer_w}x{outer_h} (AdjustWindowRectExForDpi at DPI {w['dpi']})"
              + (f"; the monitor is {m['size'][0]}x{m['size'][1]}" if m else ""),
              outer_size=[outer_w, outer_h], bigger_than_monitor=bool(m) and (width > m["size"][0] or height > m["size"][1]))
    result = set_window_pos(w["hwnd"], 0, 0, outer_w, outer_h, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)
    if result is None:
        rep.check("SetWindowPos", False, f"didn't return within {SET_POS_TIMEOUT_S:g} s (VRChat busy?)")
        return
    ok, error, ms = result
    rep.check("SetWindowPos", ok, f"returned in {ms:.1f} ms" if ok else f"failed, error {error}", ms=round(ms, 1))
    readings = read_back(rep, w["hwnd"], (width, height), "Client size")
    rep.data["resize"] = {"target": [width, height], "outer": [outer_w, outer_h], "readings": readings}
    if readings:
        final = readings[-1]["client_size"]
        if final != [width, height]:
            rep.note(f"Wanted {width}x{height}, ended at {final[0]}x{final[1]}. Something clamped or reverted it.")
    rep.note("Run with --restore to put the window back.")


def run_restore(rep):
    rep.section("Restore saved geometry")
    if not RESTORE_FILE.exists():
        rep.check("Restore point", False, f"nothing saved at {RESTORE_FILE}")
        return
    saved = json.loads(RESTORE_FILE.read_text(encoding="utf-8"))
    w = find_vrchat(rep, quiet=True)
    if w is None:
        return
    if w["hwnd"] != saved["hwnd"]:
        rep.note("VRChat's window changed since the restore point (restarted?); applying it to the current one.")
    left, top, right, bottom = saved["window_rect"]
    result = set_window_pos(w["hwnd"], left, top, right - left, bottom - top, SWP_NOZORDER | SWP_NOACTIVATE)
    if result is None:
        rep.check("SetWindowPos", False, f"didn't return within {SET_POS_TIMEOUT_S:g} s")
        return
    ok, error, ms = result
    rep.check("SetWindowPos", ok, f"returned in {ms:.1f} ms" if ok else f"failed, error {error}")
    readings = read_back(rep, w["hwnd"], tuple(saved["client_size"]), "Restored client size")
    if readings and readings[-1]["client_size"] == saved["client_size"]:
        RESTORE_FILE.unlink()
        rep.check("Restore point", None, "used and removed")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        epilog=__doc__.split("\n\n", 3)[3],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--resize", nargs=2, type=int, metavar=("W", "H"), help="set the client area to W x H")
    mode.add_argument("--restore", action="store_true", help="put the saved geometry back")
    parser.add_argument("--json", metavar="FILE", help="write results as JSON")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("This probe is for Windows. On Linux see the KWin / gamescope rows of Appendix C.")
        return 2
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    if args.resize and (min(args.resize) < 320 or max(args.resize) > 7680):
        parser.error("W and H must be between 320 and 7680")

    rep = Report()
    rep.data["args"] = vars(args)
    print("VRChat window probe (window-manager calls only)")
    rep.section("Setup")
    make_dpi_aware(rep)
    monitors = all_monitors()
    rep.data["monitors"] = monitors
    for m in monitors:
        rep.check(f"Monitor {m['device']}", None,
                  f"{m['size'][0]}x{m['size'][1]} at {m['rect'][:2]}, {m['refresh_hz']} Hz, "
                  f"{m['scale_percent']} % scaling{', primary' if m['primary'] else ''}")

    if args.restore:
        run_restore(rep)
    rep.section("VRChat window")
    window = find_vrchat(rep)
    if window is not None:
        report_window(rep, window)
        if args.resize:
            run_resize(rep, window, *args.resize)

    rep.section("Steam launch options (VRChat → Properties → Launch options)")
    targets = []
    if args.resize:
        targets.append(("requested size", args.resize))
    if window is not None and window["monitor"]:
        targets.append(("this monitor", window["monitor"]["size"]))
        targets.append(("current client area", window["client_size"]))
    if not targets:
        targets.append(("1080p", [1920, 1080]))
    seen = set()
    options = {}
    for label, (width, height) in targets:
        if (width, height) in seen:
            continue
        seen.add((width, height))
        options[label] = launch_options(width, height)
        print(f"  {label + ':':22} {options[label]}")
    rep.data["launch_options"] = options

    print(f"\n{rep.failures} failed check(s).")
    if args.json:
        Path(args.json).write_text(json.dumps(rep.data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {args.json}")
    return 1 if rep.failures else 0


if __name__ == "__main__":
    sys.exit(main())
