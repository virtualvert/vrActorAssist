#!/usr/bin/env python3
"""Probe Soundpad's remote-control interface on this machine.

Checks the Soundpad assumptions in
docs/superpowers/specs/2026-10-17-vrcActorSync-web-ui-agent-design.md (§8.1, Appendix A)
and measures latency. Windows only, standard library only. Soundpad must be running.

The default run is read-only. Options that change Soundpad state are opt-in:
  --play N      play sound N (index in Soundpad's "All sounds" list), time how fast it
                starts, then test pause, seek and stop
  --line LINE   where --play plays: speakers (default, only you hear it), mic, or both
  --volume      change the volume, try the 0.0-1.0 form soundpad.py sends today, then restore it
  --add PATH    add PATH to Soundpad's sound list (full version only; remove it by hand afterwards)
  --cli         time "Soundpad.exe -rc DoResetSearch()" (the method soundpad.py uses today;
                closes Soundpad's search panel if open)
  --json FILE   also write the results as JSON. Includes the first 5 sound titles and paths.

Examples:
  python tools\\soundpad_probe.py --json probe.json
  python tools\\soundpad_probe.py --play 1 --line speakers --volume --cli --json probe-full.json
"""

import argparse
import json
import os
import statistics
import subprocess
import sys
import threading
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

PIPE_PATH = r"\\.\pipe\sp_remote_control"
REFERENCE_RC_VERSION = "1.1.2"
# Leppsoft's reference client warns that requests sent back-to-back can break the pipe
MIN_REQUEST_GAP_S = 0.002
PLAY_STATUSES = {"STOPPED", "PLAYING", "PAUSED", "SEEKING"}

if sys.platform == "win32":
    import ctypes
    import msvcrt
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _PeekNamedPipe = _kernel32.PeekNamedPipe
    _PeekNamedPipe.argtypes = [
        wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
    ]
    _PeekNamedPipe.restype = wintypes.BOOL


class SoundpadPipe:
    """Minimal client that mirrors Leppsoft's SoundpadRemoteControl.java (RC 1.1.2)."""

    def __init__(self):
        self._pipe = open(PIPE_PATH, "r+b", buffering=0)
        self._handle = msvcrt.get_osfhandle(self._pipe.fileno())
        self._last_request = 0.0

    def close(self):
        self._pipe.close()

    def _available(self):
        avail = wintypes.DWORD(0)
        if not _PeekNamedPipe(self._handle, None, 0, None, ctypes.byref(avail), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return avail.value

    def _read_response(self):
        # Same approach as the Java client: the first byte blocks until Soundpad answers,
        # after that the rest of the answer is already in the pipe.
        data = bytearray(self._pipe.read(1))
        if not data:
            return b""
        while True:
            pending = self._available()
            if not pending:
                if data[:1] == b"<":
                    # A large XML answer might arrive in more than one write; wait briefly for more.
                    time.sleep(0.005)
                    if self._available():
                        continue
                break
            data += self._pipe.read(pending)
        return bytes(data)

    def request(self, command, timeout=3.0):
        """Send one command. Returns (response_text, elapsed_ms)."""
        gap = self._last_request + MIN_REQUEST_GAP_S - time.perf_counter()
        if gap > 0:
            time.sleep(gap)
        result = {}

        def worker():
            try:
                start = time.perf_counter()
                self._pipe.write(command.encode("utf-8"))
                result["data"] = self._read_response()
                result["ms"] = (time.perf_counter() - start) * 1000
            except OSError as exc:
                result["error"] = exc

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        thread.join(timeout)
        self._last_request = time.perf_counter()
        if thread.is_alive():
            raise TimeoutError(f"no answer to {command} within {timeout:.0f}s")
        if "error" in result:
            raise result["error"]
        return result["data"].decode("utf-8", errors="replace").strip(), result["ms"]


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


def as_int(text):
    try:
        return int(text)
    except ValueError:
        return None


def parse_xml(text):
    """Returns (root, error)."""
    try:
        return ET.fromstring(text), None
    except ET.ParseError as exc:
        return None, str(exc)


def describe_elements(root, limit):
    """Tag names, the union of attribute names, and the attributes of the first `limit` elements."""
    elements = [el for el in root.iter() if el is not root]
    attr_names = sorted({name for el in elements for name in el.attrib})
    tags = dict(Counter(el.tag for el in elements))
    sample = [dict(el.attrib, _tag=el.tag) for el in elements[:limit]]
    return tags, attr_names, sample


def run_basic(sp, rep):
    """Read-only checks. Returns True when Soundpad reports the trial version."""
    rep.section("Connection and version")
    resp, ms = sp.request("IsAlive()")
    rep.check("IsAlive()", resp.startswith("R-200"), f"{resp!r} in {ms:.1f} ms")

    resp, _ = sp.request("GetVersion()")
    rep.check("GetVersion()", bool(resp) and not resp.startswith("R-"), resp)

    resp, _ = sp.request("GetRemoteControlVersion()")
    rep.check("GetRemoteControlVersion()", bool(resp) and not resp.startswith("R-"), resp)
    if resp and resp != REFERENCE_RC_VERSION:
        rep.note(f"Probe was written against RC {REFERENCE_RC_VERSION}; this Soundpad reports {resp}.")

    resp, _ = sp.request("IsTrial()")
    trial = resp == "1"
    rep.check("IsTrial()", resp in ("0", "1"), "trial version" if trial else f"full version ({resp!r})")
    if trial:
        rep.note("Trial version: DoAddSound is not allowed, so auto-adding received files to Soundpad won't work.")

    rep.section("State")
    resp, _ = sp.request("GetVolume()")
    volume = as_int(resp)
    rep.check("GetVolume()", volume is not None and 0 <= volume <= 100, resp)

    resp, _ = sp.request("IsMuted()")
    rep.check("IsMuted()", resp in ("0", "1"), resp)

    resp, _ = sp.request("GetPlayStatus()")
    rep.check("GetPlayStatus()", resp in PLAY_STATUSES, resp)

    for cmd in ("GetPlaybackPositionInMs()", "GetPlaybackDurationInMs()"):
        resp, _ = sp.request(cmd)
        rep.check(cmd, as_int(resp) is not None, resp)

    rep.section("Sound list and categories")
    resp, _ = sp.request("GetSoundFileCount()")
    count = as_int(resp)
    rep.check("GetSoundFileCount()", count is not None, resp)

    resp, ms = sp.request("GetSoundlist()", timeout=10.0)
    root, error = parse_xml(resp)
    if root is None:
        rep.check("GetSoundlist()", False, f"not XML ({error}); starts with {resp[:80]!r}")
    else:
        tags, attr_names, sample = describe_elements(root, 5)
        rep.check("GetSoundlist()", True,
                  f"root <{root.tag}>, elements {tags}, {len(resp)} chars in {ms:.1f} ms",
                  root_tag=root.tag, element_tags=tags, attribute_names=attr_names, first_entries=sample)
        rep.check("GetSoundlist() attribute names", None, ", ".join(attr_names) or "(none)")
        for entry in sample:
            rep.check("  sound", None, json.dumps(entry, ensure_ascii=False))

    resp, ms = sp.request("GetCategories(false, false)", timeout=10.0)
    root, error = parse_xml(resp)
    if root is None:
        rep.check("GetCategories(false, false)", False, f"not XML ({error}); starts with {resp[:80]!r}")
    else:
        tags, attr_names, sample = describe_elements(root, 10)
        rep.check("GetCategories(false, false)", True, f"root <{root.tag}>, elements {tags} in {ms:.1f} ms",
                  root_tag=root.tag, element_tags=tags, attribute_names=attr_names, first_entries=sample)
        rep.check("GetCategories attribute names", None, ", ".join(attr_names) or "(none)")
    return trial


def run_latency(sp, rep, rounds=50):
    rep.section(f"Pipe round trip ({rounds} x IsAlive)")
    samples = [sp.request("IsAlive()")[1] for _ in range(rounds)]
    p95 = statistics.quantiles(samples, n=20)[18]
    rep.check("IsAlive() round trip", None,
              f"min {min(samples):.2f} ms, median {statistics.median(samples):.2f} ms, "
              f"p95 {p95:.2f} ms, max {max(samples):.2f} ms",
              samples_ms=[round(s, 3) for s in samples])


def get_position(sp):
    return as_int(sp.request("GetPlaybackPositionInMs()")[0])


def sample_positions(sp, seconds, t0):
    """Poll status and position for `seconds`. Returns ([ms since t0, status, position] at each
    change, number of polls)."""
    rows, last, polls = [], None, 0
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        status, _ = sp.request("GetPlayStatus()")
        position = get_position(sp)
        polls += 1
        if (status, position) != last:
            rows.append([round((time.perf_counter() - t0) * 1000, 1), status, position])
            last = (status, position)
    return rows, polls


def run_play(sp, rep, index, line):
    render, capture = {"speakers": (True, False), "mic": (False, True), "both": (True, True)}[line]
    cmd = f"DoPlaySound({index}, {str(render).lower()}, {str(capture).lower()})"
    rep.section(f"Play test: sound {index} on {line}")

    # Soundpad keeps reporting the last position after a stop, so positions only count once
    # the status says PLAYING.
    stale_position = get_position(sp)
    start = time.perf_counter()
    resp, ms = sp.request(cmd)
    rep.check(cmd, resp.startswith("R-200"), f"{resp!r} in {ms:.1f} ms")
    if not resp.startswith("R-200"):
        return

    playing_at = position_at = first_position = None
    trace = []
    deadline = start + 3.0
    while time.perf_counter() < deadline and position_at is None:
        status, _ = sp.request("GetPlayStatus()")
        now = time.perf_counter()
        if status == "PLAYING" and playing_at is None:
            playing_at = now
        position = get_position(sp) if playing_at else None
        if len(trace) < 100:
            trace.append([round((now - start) * 1000, 2), status, position])
        if position is not None and position > 0:
            position_at = time.perf_counter()
            first_position = position
    rep.check("Position before the command", None, f"{stale_position} ms", trace=trace)

    def since_start(t):
        return f"{(t - start) * 1000:.1f} ms" if t else "not reached within 3 s"

    rep.check("Command -> status PLAYING", playing_at is not None, since_start(playing_at),
              ms=round((playing_at - start) * 1000, 1) if playing_at else None)
    rep.check("Command -> playback position > 0", position_at is not None,
              f"{since_start(position_at)} (first position read: {first_position} ms)",
              ms=round((position_at - start) * 1000, 1) if position_at else None,
              first_position_ms=first_position)
    if position_at is None:
        sp.request("DoStopSound()")
        return

    duration = as_int(sp.request("GetPlaybackDurationInMs()")[0]) or 0
    rep.check("GetPlaybackDurationInMs() while playing", duration > 0, f"{duration} ms")

    if duration > 2500:
        rows, polls = sample_positions(sp, 0.5, start)
        playing = [r for r in rows if r[1] == "PLAYING" and r[2]]
        gaps = [b[0] - a[0] for a, b in zip(playing, playing[1:])]
        # t - position = when position 0 was, i.e. when the audio actually started
        starts = [r[0] - r[2] for r in playing]
        rep.check("Position updates while playing", None,
                  f"{len(playing)} distinct positions in {polls} polls over 0.5 s"
                  + (f", median {statistics.median(gaps):.1f} ms apart" if gaps else "")
                  + (f"; positions imply audio started {statistics.median(starts):.0f} ms after the command"
                     if starts else ""),
                  trace=rows, implied_start_ms=round(statistics.median(starts), 1) if starts else None)

        resp, _ = sp.request("DoTogglePause()")
        status, _ = sp.request("GetPlayStatus()")
        paused_pos = get_position(sp)
        time.sleep(0.5)
        later_pos = get_position(sp)
        rep.check("DoTogglePause() -> PAUSED", status == "PAUSED" and paused_pos == later_pos,
                  f"{resp!r}, status {status}, position {paused_pos} -> {later_pos} ms after 0.5 s")

        resp, _ = sp.request("DoTogglePause()")
        status, _ = sp.request("GetPlayStatus()")
        rep.check("DoTogglePause() -> PLAYING again", status == "PLAYING", f"{resp!r}, status {status}")

        # Far from the paused position, so a stale read can't pass
        seek_to = min(5000, duration - 1000)
        resp, _ = sp.request(f"DoSeekMs({seek_to})")
        rows, _ = sample_positions(sp, 0.3, time.perf_counter())
        landed = next((r for r in rows if r[2] is not None and seek_to - 100 <= r[2] <= seek_to + 600), None)
        rep.check(f"DoSeekMs({seek_to})", resp.startswith("R-200") and landed is not None,
                  f"{resp!r}, position {landed[2]} ms read {landed[0]} ms after the seek" if landed
                  else f"{resp!r}, position never near {seek_to} ms within 0.3 s", trace=rows)
    else:
        rep.note("Sound is shorter than 2.5 s, so pause and seek were skipped. Use a longer sound to test them.")

    resp, _ = sp.request("DoStopSound()")
    status, _ = sp.request("GetPlayStatus()")
    rep.check("DoStopSound()", status == "STOPPED", f"{resp!r}, status {status}")
    if line != "speakers":
        rep.note("Ask someone in VRChat whether they heard the sound on the mic line.")
    else:
        rep.note("Ask someone in VRChat to confirm they did NOT hear this speakers-only sound.")


def run_volume(sp, rep):
    rep.section("Volume test (restores the original volume)")
    original = as_int(sp.request("GetVolume()")[0])
    if original is None:
        rep.check("GetVolume()", False, "no numeric volume; skipped")
        return
    target = 40 if original != 40 else 60

    resp, _ = sp.request(f"SetVolume({target})")
    after = as_int(sp.request("GetVolume()")[0])
    rep.check(f"SetVolume({target})", after == target, f"{resp!r}, volume now {after} (was {original})")

    resp, _ = sp.request("SetVolume(0.5)")
    after = as_int(sp.request("GetVolume()")[0])
    rep.check("SetVolume(0.5) (the form soundpad.py sends today)", None, f"{resp!r}, volume now {after}")

    sp.request(f"SetVolume({original})")
    final = as_int(sp.request("GetVolume()")[0])
    rep.check("Volume restored", final == original, f"{final} (original {original})")
    rep.note("Listen test: play a sound on 'both' at two volumes. Does SetVolume change what others hear "
             "in VRChat, or only your speakers?")


def run_add(sp, rep, path, trial):
    rep.section("Add-sound test")
    file_path = Path(path).resolve()
    if not file_path.is_file():
        rep.check("DoAddSound", False, f"file not found: {file_path}")
        return
    if trial:
        rep.check("DoAddSound", None, "skipped: not allowed in the trial version")
        return
    before = as_int(sp.request("GetSoundFileCount()")[0])
    start = time.perf_counter()
    resp, ms = sp.request(f'DoAddSound("{file_path}")')
    # Soundpad answers before the sound is in the list, so wait for the count to change
    after = before
    while after == before and time.perf_counter() - start < 5.0:
        time.sleep(0.05)
        after = as_int(sp.request("GetSoundFileCount()")[0])
    listed_ms = (time.perf_counter() - start) * 1000
    detail = f"{resp!r} in {ms:.1f} ms, sound count {before} -> {after} after {listed_ms:.0f} ms"
    entry = {}
    if after:
        root, _ = parse_xml(sp.request(f"GetSoundlist({after},{after})")[0])
        if root is not None:
            _, _, sample = describe_elements(root, 1)
            entry = sample[0] if sample else {}
            detail += f", last entry: {json.dumps(entry, ensure_ascii=False)}"
    ok = resp.startswith("R-200") and before is not None and after == before + 1
    rep.check(f"DoAddSound(\"{file_path.name}\")", ok, detail, added_entry=entry)
    rep.note("Remove the test sound from Soundpad by hand.")


def run_cli(rep, rounds=5):
    rep.section(f"Command-line test ({rounds} x Soundpad.exe -rc DoResetSearch())")
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    try:
        from soundpad import find_soundpad_exe
    except ImportError as exc:
        rep.check("Import soundpad.py", False, str(exc))
        return
    exe = find_soundpad_exe()
    if not exe:
        rep.check("Find Soundpad.exe", False, "not found (set SOUNDPAD_PATH to its full path)")
        return
    times = []
    for _ in range(rounds):
        start = time.perf_counter()
        subprocess.run([exe, "-rc", "DoResetSearch()"], capture_output=True, timeout=15)
        times.append((time.perf_counter() - start) * 1000)
    rep.check("Soundpad.exe -rc round trip", None,
              f"median {statistics.median(times):.1f} ms, max {max(times):.1f} ms ({exe})",
              samples_ms=[round(t, 1) for t in times])


def run_vrchat(rep):
    rep.section("VRChat OSC avatar configs (read-only)")
    base = Path(os.environ.get("USERPROFILE", "")) / "AppData" / "LocalLow" / "VRChat" / "VRChat" / "OSC"
    if not base.is_dir():
        rep.check("OSC config folder", None, f"not found at {base}")
        return
    files = sorted(base.glob("*/Avatars/*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
    rep.check("Avatar config files", None, f"{len(files)} in {base}")
    if not files:
        return
    newest = files[0]
    try:
        config = json.loads(newest.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        rep.check("Newest avatar config", False, f"{newest.name}: {exc}")
        return
    params = config.get("parameters", [])
    settable = [p for p in params if p.get("input")]
    types = Counter((p.get("input") or p.get("output") or {}).get("type", "?") for p in params)
    sample = [{"name": p.get("name"), "address": p["input"].get("address"), "type": p["input"].get("type")}
              for p in settable[:5]]
    rep.check("Newest avatar config", True,
              f"{config.get('name')!r} ({newest.name}): {len(params)} parameters, "
              f"{len(settable)} settable over OSC, types {dict(types)}",
              top_level_keys=sorted(config), sample_inputs=sample)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        epilog=__doc__.split("\n\n", 2)[2],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--play", type=int, metavar="N", help="play sound N and time it")
    parser.add_argument("--line", choices=("speakers", "mic", "both"), default="speakers")
    parser.add_argument("--volume", action="store_true", help="change and restore the volume")
    parser.add_argument("--add", metavar="PATH", help="add a sound file to Soundpad")
    parser.add_argument("--cli", action="store_true", help="time Soundpad.exe -rc")
    parser.add_argument("--json", metavar="FILE", help="write results as JSON")
    args = parser.parse_args()

    if sys.platform != "win32":
        print("Soundpad remote control is Windows-only. Run this on the Windows test box.")
        return 2
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass

    rep = Report()
    rep.data["args"] = vars(args)
    print(f"Soundpad probe — pipe {PIPE_PATH}")
    try:
        sp = SoundpadPipe()
    except OSError as exc:
        rep.check("Open pipe", False, f"{exc}. Is Soundpad running?")
        sp = None

    if sp:
        try:
            trial = run_basic(sp, rep)
            run_latency(sp, rep)
            if args.play is not None:
                run_play(sp, rep, args.play, args.line)
            if args.volume:
                run_volume(sp, rep)
            if args.add:
                run_add(sp, rep, args.add, trial)
        except (OSError, TimeoutError) as exc:
            rep.check("Pipe communication", False, f"{exc}; remaining pipe tests skipped")
        finally:
            sp.close()

    if args.cli:
        run_cli(rep)
    run_vrchat(rep)

    print(f"\n{rep.failures} failed check(s).")
    if args.json:
        Path(args.json).write_text(json.dumps(rep.data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {args.json}")
    return 1 if rep.failures else 0


if __name__ == "__main__":
    sys.exit(main())
