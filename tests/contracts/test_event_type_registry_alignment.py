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

from trade_trace.events.semantic_keys import SEMANTIC_KEYS
from trade_trace.exporter import _STATIC_EVENT_TOOL_MAP


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
