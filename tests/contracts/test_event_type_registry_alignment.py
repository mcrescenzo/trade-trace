"""Event-type registry alignment per trade-trace-yjvs / SIMP-004.

Two places hold event-type knowledge:

- `trade_trace.events.semantic_keys.SEMANTIC_KEYS` — the canonical
  registry of every event type the package emits. Drives idempotency
  replay equivalence + free-text secret scanning.
- `trade_trace.exporter._STATIC_EVENT_TOOL_MAP` — event-type → tool
  name for the JSONL exporter. Intentionally a subset: only bucket-A
  (replayable) events need a tool mapping; bucket-B/D events default
  to the event-type string per `docs/architecture/jsonl-replay-taxonomy.md`.

The lints below force a new event type to land in `SEMANTIC_KEYS`
(canonical) before any other surface references it, and they prevent
an exporter mapping from referencing a phantom event type.
"""

from __future__ import annotations

import re
from pathlib import Path

from trade_trace.events.semantic_keys import SEMANTIC_KEYS
from trade_trace.exporter import _STATIC_EVENT_TOOL_MAP
from trade_trace.tools.imports import _IMPORT_READY_WRITERS

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "trade_trace"
_EVENT_TYPE_LITERAL = re.compile(r"""event_type\s*=\s*["']([a-z_]+\.[a-z_]+)["']""")


def test_every_emitted_event_type_literal_is_registered():
    """Every `event_type="x.y"` string literal emitted anywhere in the
    package source must be in `SEMANTIC_KEYS`.

    The events log is default-deny: an unregistered event type hard-fails
    the write at runtime (`log.py`). market.refresh emitted
    `market.refreshed` for releases without it ever being registered, so
    EVERY cache-miss refresh raised KeyError and the tool was wholly
    non-functional — but no static test caught it because the alignment
    lints below only walk the exporter map, not the emit sites (AX-068).
    This walks the emit sites.
    """

    emitted: dict[str, str] = {}
    for path in _SRC_ROOT.rglob("*.py"):
        for match in _EVENT_TYPE_LITERAL.finditer(path.read_text(encoding="utf-8")):
            emitted.setdefault(match.group(1), str(path.relative_to(_SRC_ROOT)))
    unregistered = {
        event_type: where
        for event_type, where in emitted.items()
        if event_type not in SEMANTIC_KEYS
    }
    assert not unregistered, (
        "event_type literal(s) emitted in source but NOT registered in "
        f"SEMANTIC_KEYS (default-deny will hard-fail the write): {unregistered!r}. "
        "Register each in semantic_keys.py and classify it in "
        "jsonl-replay-taxonomy.md."
    )


def test_exporter_map_only_references_known_event_types():
    """`_STATIC_EVENT_TOOL_MAP.keys()` must be a subset of `SEMANTIC_KEYS`.
    A mapping for an event type that doesn't exist in the canonical
    registry is dead code at best, contract drift at worst — every
    entry should mean 'I emit this event and here is how the exporter
    should re-render it.'"""

    exporter_keys = set(_STATIC_EVENT_TOOL_MAP)
    semantic_keys = set(SEMANTIC_KEYS)
    unknown = exporter_keys - semantic_keys
    assert not unknown, (
        "exporter._STATIC_EVENT_TOOL_MAP references event type(s) that "
        f"are not in SEMANTIC_KEYS: {sorted(unknown)!r}. Either add the "
        "event type to semantic_keys.py or remove the exporter mapping."
    )


def test_exporter_map_values_are_known_write_tools():
    """Every value in `_STATIC_EVENT_TOOL_MAP` must be a registered
    tool name (subject.verb form). A typo here means the exporter
    renders a JSONL line that the importer can't replay."""

    from trade_trace.core import default_registry

    registry_names = set(default_registry().names())
    bogus = {
        event_type: tool
        for event_type, tool in _STATIC_EVENT_TOOL_MAP.items()
        if tool not in registry_names
    }
    assert not bogus, (
        "exporter._STATIC_EVENT_TOOL_MAP maps to tool(s) that are not "
        f"registered in the default tool registry: {bogus!r}. Update the "
        "exporter mapping or land the tool registration first."
    )


def test_forecast_anchor_to_snapshot_bucket_a_mapping_is_pinned():
    """Docs classify forecast anchor events as bucket-A replayable.

    Keep the event-type alias aligned with the user-callable writer so
    exported `forecast.anchored_to_snapshot` records replay through the
    canonical `forecast.anchor_to_snapshot` tool.
    """

    assert (
        _STATIC_EVENT_TOOL_MAP["forecast.anchored_to_snapshot"]
        == "forecast.anchor_to_snapshot"
    )


def test_static_event_tool_map_values_are_import_ready_writers():
    """Mapped bucket-A event aliases must resolve to import-ready writers."""

    not_import_ready = {
        event_type: tool
        for event_type, tool in _STATIC_EVENT_TOOL_MAP.items()
        if tool not in _IMPORT_READY_WRITERS
    }
    assert not not_import_ready, (
        "exporter._STATIC_EVENT_TOOL_MAP maps bucket-A event aliases to "
        f"tool(s) that imports reject as not import-ready: {not_import_ready!r}."
    )
