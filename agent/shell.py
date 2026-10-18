"""How the UI is shown: a pywebview desktop window, or the default browser."""

from __future__ import annotations

import logging
import sys
import webbrowser
from typing import Callable

log = logging.getLogger("vrcas")

# Microsoft's documented client id for the Evergreen WebView2 Runtime.
WEBVIEW2_CLIENT = r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_CLIENT_64 = r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"


def webview2_available() -> bool:
    """pywebview silently falls back to the IE engine without WebView2, which can't run the UI."""
    if sys.platform != "win32":
        return True
    import winreg

    for hive, key in ((winreg.HKEY_LOCAL_MACHINE, WEBVIEW2_CLIENT), (winreg.HKEY_LOCAL_MACHINE, WEBVIEW2_CLIENT_64), (winreg.HKEY_CURRENT_USER, WEBVIEW2_CLIENT_64)):
        try:
            with winreg.OpenKey(hive, key) as handle:
                version, _ = winreg.QueryValueEx(handle, "pv")
                if version and version != "0.0.0.0":
                    return True
        except OSError:
            continue
    return False


def window_reason() -> str | None:
    """None when a desktop window can be used, otherwise why not."""
    if sys.platform != "win32":
        # WebKitGTK windows are optional on Linux (directors only); the browser is the default.
        return "Linux uses the browser by default (pass --window to try a pywebview window)"
    try:
        import webview  # noqa: F401
    except ImportError:
        return "pywebview isn't installed"
    if not webview2_available():
        return "the Microsoft WebView2 Runtime isn't installed"
    return None


def linux_gui() -> str | None:
    """Prefer GTK (system WebKit2GTK via PyGObject); pywebview otherwise tries Qt first on KDE."""
    try:
        import gi  # noqa: F401
    except ImportError:
        return None
    return "gtk"


def run_window(url: str, storage_path: str, on_closed: Callable[[], None]) -> None:
    """Blocks on the GUI loop; pywebview requires the main thread."""
    import webview

    window = webview.create_window(
        "vrcActorSync",
        url,
        width=1320,
        height=860,
        min_size=(720, 560),
        background_color="#080a0f",
        text_select=True,
    )
    window.events.closed += on_closed
    gui = linux_gui() if sys.platform.startswith("linux") else None
    webview.start(gui=gui, private_mode=True, storage_path=storage_path)


def open_browser(url: str) -> None:
    if not webbrowser.open(url):
        log.warning("Couldn't open a browser. Open this address yourself: %s", url)
