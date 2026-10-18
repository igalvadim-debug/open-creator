"""Pytest bootstrap: make the local-stack modules importable from any CWD.

Without an editable install, tests relied on ``sys.path`` hacks inside each
test module (only for the file that did it).  Adding the directory here once
covers every test module and mirrors what ``pip install -e ./local-stack``
provides in CI.
"""
import sys
from pathlib import Path

_LOCAL_STACK = str(Path(__file__).resolve().parent / "local-stack")
if _LOCAL_STACK not in sys.path:
    sys.path.insert(0, _LOCAL_STACK)
