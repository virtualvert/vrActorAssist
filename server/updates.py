"""Version checks and the update manifest (moved from the v0.3 server_ws.py, unchanged)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable, Optional


def compare_versions(client_ver: str, server_ver: str) -> tuple:
    """Compare client and server versions. Returns (status, message).
    status: 'ok', 'warning', 'unsupported'
    """
    try:
        c_parts = [int(x) for x in client_ver.split('.')]
        s_parts = [int(x) for x in server_ver.split('.')]
    except (ValueError, AttributeError):
        return 'warning', f'Cannot parse version (client={client_ver}, server={server_ver})'

    # Pad to 3 parts
    while len(c_parts) < 3: c_parts.append(0)
    while len(s_parts) < 3: s_parts.append(0)

    if c_parts[0] != s_parts[0]:
        return 'unsupported', f'Client v{client_ver} is incompatible with server v{server_ver}'
    if c_parts[1:] != s_parts[1:]:
        return 'warning', f'Client v{client_ver} may have issues with server v{server_ver}. Some features may not work.'
    return 'ok', ''


def compare_versions_v2(client_ver: str, server_ver: str) -> tuple:
    """compare_versions for v2 clients, which send versions like '0.4.0-dev': suffixes are
    ignored, and only the major and minor numbers have to match."""
    client, server = parse_version(client_ver), parse_version(server_ver)
    if client is None or server is None:
        return 'warning', f'Cannot parse version (client={client_ver}, server={server_ver})'
    if client[0] != server[0]:
        return 'unsupported', f'Client v{client_ver} is incompatible with relay v{server_ver}'
    if client[1] != server[1]:
        return 'warning', f'Client v{client_ver} may have issues with relay v{server_ver}. Some features may not work.'
    return 'ok', ''


def parse_version(version: str) -> Optional[tuple]:
    """Parse MAJOR.MINOR.PATCH into an int tuple, ignoring suffixes like '-dev'.
    Missing parts count as 0. Returns None if no leading number is found.
    """
    match = re.match(r'\s*v?(\d+)(?:\.(\d+))?(?:\.(\d+))?', version or "")
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())


def load_manifest(path: Path, log: Callable[[str], None] = print) -> dict:
    """Load update manifest from file. Returns empty dict if missing or invalid."""
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception as e:
        log(f"Error loading manifest: {e}")
    return {}


def find_update(manifest: dict, role: str, platform_id: str, client_version: str) -> dict:
    """Check if an update is available for this client.
    Returns dict with latest_version, download_url, sha256, release_notes
    or empty dict if no update available.
    """
    if not manifest:
        return {}

    latest = manifest.get("latest_version", "")
    if not latest:
        return {}

    # Only offer strictly newer versions (never a downgrade or same-version reinstall)
    latest_parts = parse_version(latest)
    client_parts = parse_version(client_version)
    if latest_parts is None or client_parts is None or latest_parts <= client_parts:
        return {}

    # Look up the asset key: e.g. "actor-windows-x64"
    asset_key = f"{role}-{platform_id}"
    assets = manifest.get("assets", {})
    asset = assets.get(asset_key, {})

    download_url = asset.get("url", "")
    sha256 = asset.get("sha256", "")

    if not download_url:
        return {}

    return {
        "latest_version": latest,
        "download_url": download_url,
        "sha256": sha256,
        "release_notes": manifest.get("release_notes", "")
    }
