"""Every event type registered in `semantic_keys.py` must be classified
in `docs/architecture/jsonl-replay-taxonomy.md` (trade-trace-apgt).

Adding a new event type without filing it under one of the four buckets
(A/B/D/E) is a contract-drift bug: importers downstream of the export
surface can't tell whether to replay, skip-cascaded, skip-diagnostic,
or reject the new line. The test forces the taxonomy update to land
in the same PR as the new event type.
"""

from __future__ import annotations

from pathlib import Path

from trade_trace.events.semantic_keys import SEMANTIC_KEYS
from trade_trace.tools.imports import _CASCADED_EVENT_TOOLS, _DIAGNOSTIC_EVENT_TOOLS

ROOT = Path(__file__).resolve().parents[2]
TAXONOMY_DOC = ROOT / "docs" / "architecture" / "jsonl-replay-taxonomy.md"


def test_every_event_type_classified_in_taxonomy():
    """Walk `SEMANTIC_KEY_REGISTRY` (the canonical list of emitted
    event types) and assert each one appears either:

    - as a bucket-A replayable name (the `*.add` / write-tool alias),
    - in `_CASCADED_EVENT_TOOLS` (bucket B),
    - in `_DIAGNOSTIC_EVENT_TOOLS` (bucket D),
    - by-name in the taxonomy doc.
    """

    taxonomy_text = TAXONOMY_DOC.read_text(encoding="utf-8")
    missing: list[str] = []
    for event_type in SEMANTIC_KEYS:
        if event_type in _CASCADED_EVENT_TOOLS:
            continue
        if event_type in _DIAGNOSTIC_EVENT_TOOLS:
            continue
        # The taxonomy doc references each bucket-A event by its
        # exact event-type name in backticks.
        if f"`{event_type}`" in taxonomy_text:
            continue
        missing.append(event_type)
    assert not missing, (
        "event type(s) not classified in jsonl-replay-taxonomy.md or in "
        f"the import skip sets: {missing!r}. Add each to one of the "
        "four buckets (A/B/D/E) per the doc, plus the corresponding "
        "import skip set if the event is bucket B or D."
    )
