"""PyInstaller entry point for the vrcActorSync agent (built by build_agent.py).

From a source checkout run `python -m agent` instead. PyInstaller needs a plain script, and
agent/__main__.py uses relative imports, so this file imports it as a package module.
"""

import os
import sys

# A --windowed build (Windows) has no console: sys.stdout / sys.stderr are None, and uvicorn's
# log formatter calls sys.stdout.isatty() at startup. Give them somewhere harmless to write;
# the log file in the data dir still gets everything.
for _name in ("stdout", "stderr"):
    if getattr(sys, _name) is None:
        setattr(sys, _name, open(os.devnull, "w", encoding="utf-8"))

from agent.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
