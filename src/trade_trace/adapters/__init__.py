"""Opt-in external market adapters.

Adapters are fail-closed and must not be imported by default journal/status paths
unless they are pure configuration helpers with no network side effects.
"""

from __future__ import annotations
