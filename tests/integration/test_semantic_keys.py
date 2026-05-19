"""Semantic-equivalence registry tests per docs/architecture/persistence.md §5.2.1
(trade-trace-kvn).

The registry surface is in src/trade_trace/events/semantic_keys.py; this test
file exercises the registry properties the rest of the system depends on.
"""

from __future__ import annotations

import json

import pytest

from trade_trace.events.semantic_keys import (
    SEMANTIC_KEYS,
    SemanticKeySpec,
    canonicalize_payload,
    payloads_equivalent,
)

EXPECTED_EVENT_TYPES = {
    "decision.created",
    "outcome.recorded",
    "forecast.created",
    "forecast.scored",
    "forecast.superseded",
    "playbook.proposed_version",
    "playbook_rule.followed",
    "playbook_rule.overridden",
    "memory_node.retained",
    "memory_node.invalidated",
    "edge.created",
    "source.attached",
    "strategy.created",
    "strategy.updated",
    "signal.emitted",
    "import.row_committed",
}


def test_registry_covers_persistence_md_event_types():
    """The 15 event types listed in persistence.md §5.2.1 plus
    `forecast.created` (16 total, since forecast.created is in §3.1's
    taxonomy and the persistence.md §5.2.1 table lists it too) MUST be
    present in the registry."""

    assert set(SEMANTIC_KEYS) >= EXPECTED_EVENT_TYPES


def test_every_spec_lists_structural_fields():
    """An event type with empty structural_fields would be meaningless —
    the comparison would always succeed."""

    for event_type, spec in SEMANTIC_KEYS.items():
        assert isinstance(spec, SemanticKeySpec), event_type
        assert spec.structural_fields, f"empty structural set for {event_type}"


def test_canonicalize_strips_free_text():
    """Free-text fields are dropped before canonicalization."""

    payload = {
        "instrument_id": "i_1",
        "type": "skip",
        "reason": "very long agent rationalization here",
        "tags": ["liquidity-ignored"],
    }
    canonical = canonicalize_payload("decision.created", payload)
    parsed = json.loads(canonical)
    assert "reason" not in parsed
    assert parsed["instrument_id"] == "i_1"


def test_canonicalize_sorts_arrays_deterministically():
    """`tags` is a structural array; output order must be deterministic
    regardless of input order."""

    payload_a = {"instrument_id": "i_1", "type": "skip", "tags": ["c", "a", "b"]}
    payload_b = {"instrument_id": "i_1", "type": "skip", "tags": ["a", "b", "c"]}
    assert canonicalize_payload("decision.created", payload_a) == canonicalize_payload(
        "decision.created", payload_b
    )


def test_canonicalize_unknown_event_type_raises():
    """Default-deny: an unregistered event type cannot be canonicalized."""

    with pytest.raises(KeyError):
        canonicalize_payload("totally.unknown_event", {"x": 1})


# -- equivalence checks ---------------------------------------------------


def test_equivalence_positive_structural_match():
    old = {"instrument_id": "i_1", "type": "skip", "reason": "first take", "tags": ["a"]}
    new = {"instrument_id": "i_1", "type": "skip", "reason": "rephrased take", "tags": ["a"]}
    equivalent, summary = payloads_equivalent("decision.created", old, new)
    assert equivalent is True
    assert "diff_keys" not in summary


def test_equivalence_negative_structural_mismatch():
    """Changing a structural field returns equivalent=False with diff_keys
    listing the changed key — and NEVER the raw payload values."""

    old = {"instrument_id": "i_1", "type": "skip", "tags": ["a"]}
    new = {"instrument_id": "i_1", "type": "paper_enter", "tags": ["a"]}
    equivalent, summary = payloads_equivalent("decision.created", old, new)
    assert equivalent is False
    assert "type" in summary["diff_keys"]
    # No raw values leaked.
    for value in summary.values():
        if isinstance(value, str):
            assert "paper_enter" not in value
            assert "skip" not in value


def test_equivalence_free_text_variance_tolerated():
    """Whitespace and rephrasing in free-text fields are tolerated."""

    old = {"instrument_id": "i_1", "type": "skip", "reason": "spread too wide"}
    new = {"instrument_id": "i_1", "type": "skip", "reason": "the spread was wider than the expected edge"}
    equivalent, _ = payloads_equivalent("decision.created", old, new)
    assert equivalent is True


# -- per-event-type targeted checks ---------------------------------------


def test_forecast_created_outcomes_sorted_by_label():
    """`forecasts.outcomes` is a structural array sorted by outcome_label
    so two writes that order YES/NO differently still compare equal."""

    old = {
        "thesis_id": "t_1",
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "YES", "probability": 0.48},
            {"outcome_label": "NO", "probability": 0.52},
        ],
    }
    new = {
        "thesis_id": "t_1",
        "kind": "binary",
        "outcomes": [
            {"outcome_label": "NO", "probability": 0.52},
            {"outcome_label": "YES", "probability": 0.48},
        ],
    }
    equivalent, _ = payloads_equivalent("forecast.created", old, new)
    assert equivalent is True


def test_strategy_created_description_change_tolerated():
    """`description` and `hypothesis` are free-text on strategy.created; a
    rephrase replays cleanly."""

    old = {"slug": "earnings-momentum", "name": "Earnings momentum", "status": "active",
           "description": "post-earnings price drift in liquid names"}
    new = {"slug": "earnings-momentum", "name": "Earnings momentum", "status": "active",
           "description": "the post-earnings drift in liquid names"}
    equivalent, _ = payloads_equivalent("strategy.created", old, new)
    assert equivalent is True


def test_import_row_committed_identity_only():
    """Importer writes per persistence.md §5.2 row 3: compared on
    (import_run_id, source_row_number) only."""

    old = {
        "import_run_id": "run-1",
        "source_row_number": 42,
        "some_other_field": "completely different value",
    }
    new = {
        "import_run_id": "run-1",
        "source_row_number": 42,
        "some_other_field": "yet another different value",
    }
    equivalent, _ = payloads_equivalent("import.row_committed", old, new)
    assert equivalent is True


def test_signal_emitted_related_refs_sorted():
    """`related_refs_json` is sorted by `kind` so the agent can reorder."""

    old = {
        "kind": "calibration_drift",
        "severity": "warn",
        "actor_id": "system:report.coach",
        "related_refs_json": [
            {"kind": "decision", "id": "d_1"},
            {"kind": "forecast", "id": "f_1"},
        ],
    }
    new = {
        "kind": "calibration_drift",
        "severity": "warn",
        "actor_id": "system:report.coach",
        "related_refs_json": [
            {"kind": "forecast", "id": "f_1"},
            {"kind": "decision", "id": "d_1"},
        ],
    }
    equivalent, _ = payloads_equivalent("signal.emitted", old, new)
    assert equivalent is True


# -- canonical JSON sort consistency --------------------------------------


def test_canonical_json_uses_sorted_keys():
    """The canonical form is `json.dumps(sort_keys=True)` so per-byte
    comparison is deterministic across Python versions."""

    payload = {"instrument_id": "i_1", "type": "skip", "tags": ["a"]}
    canonical = canonicalize_payload("decision.created", payload)
    # Re-serialize in a different starting order; should produce the same
    # canonical string.
    payload2 = {"tags": ["a"], "type": "skip", "instrument_id": "i_1"}
    canonical2 = canonicalize_payload("decision.created", payload2)
    assert canonical == canonical2


# -- default-deny safety -------------------------------------------------


def test_default_deny_at_writer_layer(tmp_path):
    """If an event_type is removed from the registry, the EventWriter
    refuses to write events of that type. This is the runtime guard that
    prevents silent contract drift."""

    from trade_trace.events import EventWriter
    from trade_trace.storage import apply_pending_migrations, open_database
    from trade_trace.storage.paths import db_path

    db = open_database(db_path(tmp_path / "home"))
    try:
        apply_pending_migrations(db.connection)
        writer = EventWriter(db.connection)
        with pytest.raises(KeyError) as exc:
            writer.write(
                event_type="not.registered",
                subject_kind="x",
                subject_id="y",
                payload={"a": 1},
                actor_id="agent:default",
                idempotency_key="abc",
            )
        assert "not registered" in str(exc.value)
    finally:
        db.close()
