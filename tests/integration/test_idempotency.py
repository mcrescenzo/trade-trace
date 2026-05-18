"""Idempotency contract tests per docs/architecture/persistence.md §5."""

from __future__ import annotations

import json

import pytest

from trade_trace.events import EventWriter, IdempotencyConflictError, payloads_equivalent
from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path


def _db(tmp_path):
    db = open_database(db_path(tmp_path / "home"))
    apply_pending_migrations(db.connection)
    return db


def _decision_payload(**overrides):
    base = {
        "instrument_id": "i_1",
        "type": "skip",
        "reason": "spread too wide",
        "tags": ["liquidity-ignored"],
    }
    base.update(overrides)
    return base


def test_pure_replay_returns_original(tmp_path):
    db = _db(tmp_path)
    try:
        writer = EventWriter(db.connection)
        first = writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload=_decision_payload(),
            actor_id="agent:default",
            idempotency_key="abc",
        )
        # Same key, semantically equivalent payload (free-text `reason`
        # rephrased) → replay returns the original record.
        second = writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload=_decision_payload(reason="the spread was too wide for the expected edge"),
            actor_id="agent:default",
            idempotency_key="abc",
        )
        assert second.id == first.id
        assert second.idempotent_replay is True
        count = db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 1
    finally:
        db.close()


def test_incompatible_payload_raises_conflict(tmp_path):
    db = _db(tmp_path)
    try:
        writer = EventWriter(db.connection)
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload=_decision_payload(type="skip"),
            actor_id="agent:default",
            idempotency_key="abc",
        )
        # Structural field changed (`type` skip → paper_enter). Must raise.
        with pytest.raises(IdempotencyConflictError) as exc:
            writer.write(
                event_type="decision.created",
                subject_kind="decision",
                subject_id="d_1",
                payload=_decision_payload(type="paper_enter"),
                actor_id="agent:default",
                idempotency_key="abc",
            )
        # diff_summary must include `type` as a changed key WITHOUT exposing
        # raw payload values.
        assert "type" in exc.value.diff_summary["diff_keys"]
        assert exc.value.original_event_id is not None
        # Only the original event row exists; the conflict did not double-write.
        count = db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 1
    finally:
        db.close()


def test_missing_idempotency_key_raises_value_error(tmp_path):
    db = _db(tmp_path)
    try:
        writer = EventWriter(db.connection)
        with pytest.raises(ValueError):
            writer.write(
                event_type="decision.created",
                subject_kind="decision",
                subject_id="d_1",
                payload=_decision_payload(),
                actor_id="agent:default",
                idempotency_key=None,
            )
    finally:
        db.close()


def test_allow_no_idempotency_opt_in(tmp_path):
    db = _db(tmp_path)
    try:
        writer = EventWriter(db.connection)
        # Two writes without idempotency_key produce two distinct events.
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload=_decision_payload(),
            actor_id="import:run-1",
            idempotency_key=None,
            allow_no_idempotency=True,
        )
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_2",
            payload=_decision_payload(),
            actor_id="import:run-1",
            idempotency_key=None,
            allow_no_idempotency=True,
        )
        count = db.connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 2
    finally:
        db.close()


def test_unknown_event_type_rejected(tmp_path):
    db = _db(tmp_path)
    try:
        writer = EventWriter(db.connection)
        with pytest.raises(KeyError):
            writer.write(
                event_type="totally.unknown_event",
                subject_kind="decision",
                subject_id="d_1",
                payload={"any": "thing"},
                actor_id="agent:default",
                idempotency_key="abc",
            )
    finally:
        db.close()


def test_different_actors_share_key_safely(tmp_path):
    """`idempotency_key` is unique within `(event_type, actor_id)`. Two
    actors with the same key produce two distinct events."""

    db = _db(tmp_path)
    try:
        writer = EventWriter(db.connection)
        first = writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload=_decision_payload(),
            actor_id="agent:a",
            idempotency_key="abc",
        )
        second = writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_2",
            payload=_decision_payload(),
            actor_id="agent:b",
            idempotency_key="abc",
        )
        assert first.id != second.id
    finally:
        db.close()


def test_free_text_diff_is_not_a_conflict():
    """payloads_equivalent ignores free-text fields per persistence.md §5.2.1."""

    old = {"instrument_id": "i_1", "type": "skip", "reason": "Spread too wide"}
    new = {"instrument_id": "i_1", "type": "skip", "reason": "spread was wide!"}
    equivalent, summary = payloads_equivalent("decision.created", old, new)
    assert equivalent is True
    assert "reason" not in summary.get("diff_keys", [])


def test_array_order_irrelevant_for_idempotency():
    """`tags` is structurally compared after deterministic sort, so the
    agent can reorder tags on retry without triggering a conflict."""

    old = {"instrument_id": "i_1", "type": "skip", "tags": ["a", "b", "c"]}
    new = {"instrument_id": "i_1", "type": "skip", "tags": ["c", "b", "a"]}
    equivalent, _ = payloads_equivalent("decision.created", old, new)
    assert equivalent is True


def test_outbox_inserted_when_enabled(tmp_path):
    """When config['outbox.jsonl_enabled'] = 'true', a successful event
    write also appends an outbox row."""

    db = _db(tmp_path)
    try:
        writer = EventWriter(db.connection)
        writer.set_outbox_jsonl_enabled()
        record = writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload=_decision_payload(),
            actor_id="agent:default",
            idempotency_key="abc",
        )
        cur = db.connection.execute(
            "SELECT event_id, state FROM outbox WHERE event_id = ?", (record.id,)
        )
        row = cur.fetchone()
        assert row is not None
        assert row[1] == "pending"
    finally:
        db.close()


def test_outbox_skipped_when_disabled(tmp_path):
    """The default is outbox-disabled; events are written but no outbox row."""

    db = _db(tmp_path)
    try:
        writer = EventWriter(db.connection)
        # config.outbox.jsonl_enabled NOT set → false.
        record = writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload=_decision_payload(),
            actor_id="agent:default",
            idempotency_key="abc",
        )
        cur = db.connection.execute("SELECT COUNT(*) FROM outbox WHERE event_id = ?", (record.id,))
        assert cur.fetchone()[0] == 0
    finally:
        db.close()


def test_jsonl_export_line_has_transport_metadata(tmp_path):
    """An EventRecord's to_jsonl_line() carries the imports.md §2.1 superset
    shape: a `{tool, args}` envelope plus the underscore-prefixed transport
    metadata per operability.md §9.2."""

    db = _db(tmp_path)
    try:
        writer = EventWriter(db.connection)
        record = writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload=_decision_payload(),
            actor_id="agent:default",
            idempotency_key="abc",
        )
        line = record.to_jsonl_line()
        for key in ("_event_id", "_event_type", "_actor_id", "_created_at", "_contract_version"):
            assert key in line, f"jsonl line missing transport key {key!r}"
        # Importer envelope: tool + args. Domain fields live inside args.
        assert line["tool"] == "decision.add"
        assert "instrument_id" in line["args"]
        assert line["_event_type"] == "decision.created"
        assert line["_contract_version"] == "1.0"
    finally:
        db.close()
