"""The VRChat window on Windows (spec §8.5.8, method A): find it, set its client area, put it back.

Window-manager calls only. VRChat runs Easy Anti-Cheat, so the app never opens the VRChat
process: VRChat.exe is found through a Toolhelp snapshot (names and ids only) and EnumWindows.
Ported from tools/vrchat_window_probe.py, where these calls were tested (Appendix C).

Every function blocks (SetWindowPos waits for VRChat's window thread, up to SET_POS_TIMEOUT_S),
so call them off the event loop. Sizes are physical pixels: each call makes its thread
per-monitor DPI aware, whatever the window toolkit set for the process.
"""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass

SUPPORTED = sys.platform == "win32"
PROCESS_NAME = "vrchat.exe"
UNITY_CLASS = "UnityWndClass"
SET_POS_TIMEOUT_S = 5.0

GWL_STYLE = -16
GWL_EXSTYLE = -20
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
MONITOR_DEFAULTTONEAREST = 2
TH32CS_SNAPPROCESS = 0x2

if SUPPORTED:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                    ("dwFlags", wintypes.DWORD)]

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
    GetWindowThreadProcessId = _fn(user32, "GetWindowThreadProcessId", wintypes.DWORD,
                                   wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    IsWindow = _fn(user32, "IsWindow", wintypes.BOOL, wintypes.HWND)
    IsWindowVisible = _fn(user32, "IsWindowVisible", wintypes.BOOL, wintypes.HWND)
    IsIconic = _fn(user32, "IsIconic", wintypes.BOOL, wintypes.HWND)
    IsZoomed = _fn(user32, "IsZoomed", wintypes.BOOL, wintypes.HWND)
    GetClassNameW = _fn(user32, "GetClassNameW", ctypes.c_int, wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    GetWindowRect = _fn(user32, "GetWindowRect", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    GetClientRect = _fn(user32, "GetClientRect", wintypes.BOOL, wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    GetWindowLongPtrW = _fn(user32, "GetWindowLongPtrW" if ctypes.sizeof(ctypes.c_void_p) == 8 else "GetWindowLongW",
                            ctypes.c_ssize_t, wintypes.HWND, ctypes.c_int)
    GetDpiForWindow = _fn(user32, "GetDpiForWindow", wintypes.UINT, wintypes.HWND)
    SetThreadDpiAwarenessContext = _fn(user32, "SetThreadDpiAwarenessContext", ctypes.c_void_p, ctypes.c_void_p)
    AdjustWindowRectExForDpi = _fn(user32, "AdjustWindowRectExForDpi", wintypes.BOOL,
                                   ctypes.POINTER(wintypes.RECT), wintypes.DWORD, wintypes.BOOL,
                                   wintypes.DWORD, wintypes.UINT)
    SetWindowPos = _fn(user32, "SetWindowPos", wintypes.BOOL, wintypes.HWND, wintypes.HWND,
                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)
    MonitorFromWindow = _fn(user32, "MonitorFromWindow", wintypes.HMONITOR, wintypes.HWND, wintypes.DWORD)
    GetMonitorInfoW = _fn(user32, "GetMonitorInfoW", wintypes.BOOL, wintypes.HMONITOR, ctypes.POINTER(MONITORINFO))
    CreateToolhelp32Snapshot = _fn(kernel32, "CreateToolhelp32Snapshot", wintypes.HANDLE,
                                   wintypes.DWORD, wintypes.DWORD)
    Process32FirstW = _fn(kernel32, "Process32FirstW", wintypes.BOOL, wintypes.HANDLE,
                          ctypes.POINTER(PROCESSENTRY32W))
    Process32NextW = _fn(kernel32, "Process32NextW", wintypes.BOOL, wintypes.HANDLE,
                         ctypes.POINTER(PROCESSENTRY32W))
    CloseHandle = _fn(kernel32, "CloseHandle", wintypes.BOOL, wintypes.HANDLE)


class WindowError(Exception):
    """A resize or restore that didn't happen; the message is shown to the operator."""


@dataclass(frozen=True)
class Window:
    hwnd: int
    cls: str
    # Client area (what VRChat renders), physical px
    client: tuple[int, int]
    # Outer window rect: left, top, right, bottom
    rect: tuple[int, int, int, int]
    style: int
    exstyle: int
    dpi: int
    # "window", "minimized", "maximized" or "fullscreen"
    mode: str


def find() -> Window | None:
    """VRChat's main window: visible, Unity's class first, then the largest. None when VRChat
    isn't running or shows no window."""
    _per_monitor_aware()
    pids = _process_ids()
    if not pids:
        return None
    windows = [w for w in (_describe(hwnd) for hwnd in _windows_of(pids) if IsWindowVisible(hwnd)) if w]
    if not windows:
        return None
    return max(windows, key=lambda w: (w.cls == UNITY_CLASS, w.client[0] * w.client[1]))


def resize(win: Window, width: int, height: int) -> Window:
    """Set the client area to width × height, keeping the position. Returns the window as read back."""
    if win.mode != "window":
        raise WindowError(f"VRChat is {win.mode}; switch it to a normal window first")
    _per_monitor_aware()
    rect = wintypes.RECT(0, 0, width, height)
    if not AdjustWindowRectExForDpi(ctypes.byref(rect), win.style, False, win.exstyle, win.dpi):
        raise WindowError(f"Couldn't work out the window size (Windows error {ctypes.get_last_error()})")
    _set_pos(win.hwnd, 0, 0, rect.right - rect.left, rect.bottom - rect.top, SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE)
    after = _describe(win.hwnd)
    if after is None:
        raise WindowError("VRChat's window closed during the resize")
    return after


def place(hwnd: int, rect: tuple[int, int, int, int]) -> Window | None:
    """Put a VRChat window back at rect. None when that window is gone (VRChat was restarted)."""
    _per_monitor_aware()
    if not IsWindow(hwnd) or _pid_of(hwnd) not in _process_ids():
        return None
    left, top, right, bottom = rect
    _set_pos(hwnd, left, top, right - left, bottom - top, SWP_NOZORDER | SWP_NOACTIVATE)
    return _describe(hwnd)


def _per_monitor_aware() -> None:
    SetThreadDpiAwarenessContext(ctypes.c_void_p(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))


def _process_ids() -> set[int]:
    """VRChat.exe's process ids, from a Toolhelp snapshot (never opens the processes)."""
    snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID_HANDLE_VALUE:
        raise WindowError(f"Couldn't list processes (Windows error {ctypes.get_last_error()})")
    ids = set()
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = Process32FirstW(snapshot, ctypes.byref(entry))
        while ok:
            if entry.szExeFile.lower() == PROCESS_NAME:
                ids.add(entry.th32ProcessID)
            ok = Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        CloseHandle(snapshot)
    return ids


def _pid_of(hwnd) -> int:
    pid = wintypes.DWORD()
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _windows_of(pids: set[int]) -> list[int]:
    found = []

    @WNDENUMPROC
    def callback(hwnd, _):
        if _pid_of(hwnd) in pids:
            found.append(hwnd)
        return True

    EnumWindows(callback, 0)
    return found


def _describe(hwnd) -> Window | None:
    rect, client = wintypes.RECT(), wintypes.RECT()
    if not (GetWindowRect(hwnd, ctypes.byref(rect)) and GetClientRect(hwnd, ctypes.byref(client))):
        return None
    style = GetWindowLongPtrW(hwnd, GWL_STYLE) & 0xFFFFFFFF
    exstyle = GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
    cls = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, cls, len(cls))
    outer = (rect.left, rect.top, rect.right, rect.bottom)
    if IsIconic(hwnd):
        mode = "minimized"
    elif style & WS_POPUP and (style & WS_CAPTION) != WS_CAPTION and outer == _monitor_rect(hwnd):
        mode = "fullscreen"
    elif IsZoomed(hwnd):
        mode = "maximized"
    else:
        mode = "window"
    return Window(int(hwnd), cls.value, (client.right, client.bottom), outer, style, exstyle, GetDpiForWindow(hwnd), mode)


def _monitor_rect(hwnd) -> tuple[int, int, int, int] | None:
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if not GetMonitorInfoW(MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST), ctypes.byref(info)):
        return None
    r = info.rcMonitor
    return (r.left, r.top, r.right, r.bottom)


def _set_pos(hwnd, x, y, cx, cy, flags) -> None:
    """SetWindowPos waits for VRChat's window thread: run it on a daemon thread with a timeout, so a
    busy game can't hang the app (or its exit)."""
    result = []

    def worker():
        _per_monitor_aware()
        ok = SetWindowPos(hwnd, None, x, y, cx, cy, flags)
        result.append(0 if ok else ctypes.get_last_error())

    thread = threading.Thread(target=worker, daemon=True, name="vrchat-window")
    thread.start()
    thread.join(SET_POS_TIMEOUT_S)
    if not result:
        raise WindowError(f"VRChat didn't answer within {SET_POS_TIMEOUT_S:g} s")
    if result[0]:
        raise WindowError(f"Windows refused to move the window (error {result[0]})")
