"""Pytest configuration.

Adds `src/` to sys.path for in-tree imports without requiring `pip install -e .`
to land before tests can run.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
