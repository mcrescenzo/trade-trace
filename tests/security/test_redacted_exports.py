"""Export-time secret scanning per trade-trace-b2r + operability.md §7.

The export-time scanner is documented as a "did you mean to ship these out?"
check, not a block. It surfaces matches in the drain result so the operator
can decide whether to redact and resubmit; the export still proceeds so the
on-disk JSONL stays an accurate audit of what the journal contains.

`sources.redaction_status = sensitive` is excluded from `review.bundle`
unconditionally (a separate surface tested elsewhere). The export path
deliberately does NOT filter on that field — full-local export preserves
every event for backup/replay parity.

Covers the b2r acceptance:
- "Redacted/shareable vs full-local export behavior is explicit and tested
  or explicitly deferred with final verification notes."
"""

from __future__ import annotations

import json
from pathlib import Path

from trade_trace.events import EventWriter
from trade_trace.exporter import (
    SECRET_PATTERNS,
    drain_outbox,
    scan_for_secrets,
)
from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path


def _journal(tmp_path: Path):
    home = tmp_path / "home"
    db = open_database(db_path(home))
    apply_pending_migrations(db.connection)
    writer = EventWriter(db.connection)
    writer.set_outbox_jsonl_enabled()
    return home, db, writer


# -- scan primitive ----------------------------------------------------------


def test_scan_detects_each_documented_pattern():
    """operability.md §6.3 lists four patterns. The scanner detects each."""

    fixtures = {
        "api_key": "talking about sk-ABCDEFGH1234567890abcdef in a note",
        "slack_token": "leaked xoxb-12345-67890-abcdef in chat",
        "ethereum_address": "address 0x1234567890abcdef1234567890abcdef12345678",
        "jwt": (
            "header eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "abcdef1234567890ABCDEF"
        ),
    }
    for pattern_name, text in fixtures.items():
        matches = scan_for_secrets(text)
        names = [m["pattern"] for m in matches]
        assert pattern_name in names, (
            f"scanner missed {pattern_name}; matches={matches}"
        )


def test_scan_clean_text_returns_empty():
    assert scan_for_secrets("nothing secret here") == []
    assert scan_for_secrets("instrument_id=i_1 type=skip") == []


def test_scan_pattern_set_matches_operability_md_section_6_3():
    """If a pattern is removed without bumping the contract version,
    operability.md drifts. Pin the canonical set here."""

    assert set(SECRET_PATTERNS) == {
        "api_key",
        "slack_token",
        "ethereum_address",
        "jwt",
    }


# -- drain-time behavior -----------------------------------------------------


def test_drain_emits_warning_for_secret_shaped_payload(tmp_path: Path):
    home, db, writer = _journal(tmp_path)
    try:
        # `reason` is a free-text decision field; a careless agent might paste
        # a token into it. The drain must surface the match without blocking.
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload={
                "instrument_id": "i_1",
                "type": "skip",
                "reason": "skipping; openai key was sk-ABCDEFGHIJKLMNOP1234",
            },
            actor_id="agent:default",
            idempotency_key="dec-with-secret",
        )
        result = drain_outbox(db.connection, home)
    finally:
        db.close()

    # Warning surfaced but the export still wrote the file (full-local
    # behavior per operability.md §7).
    assert len(result.exported_files) == 1
    assert len(result.secret_warnings) == 1
    warning = result.secret_warnings[0]
    assert warning["event_type"] == "decision.created"
    assert "api_key" in warning["patterns"]
    # The file on disk contains the raw payload — the export does NOT
    # silently redact (operability.md §7 calls this an "audit warning"
    # not a filter).
    line = json.loads(result.exported_files[0].read_text())
    assert "sk-ABCDEFGHIJKLMNOP1234" in line["args"]["reason"]


def test_drain_does_not_block_on_secrets(tmp_path: Path):
    """A payload with secrets still drains; outbox state flips to exported."""

    home, db, writer = _journal(tmp_path)
    try:
        record = writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload={
                "instrument_id": "i_1",
                "type": "skip",
                "reason": "wallet 0x1234567890abcdef1234567890abcdef12345678",
            },
            actor_id="agent:default",
            idempotency_key="dec-eth",
        )
        result = drain_outbox(db.connection, home)
        state = db.connection.execute(
            "SELECT state FROM outbox WHERE event_id = ?", (record.id,)
        ).fetchone()[0]
    finally:
        db.close()

    assert state == "exported"
    assert len(result.exported_files) == 1
    assert any(
        "ethereum_address" in w["patterns"] for w in result.secret_warnings
    )


def test_drain_does_not_emit_warnings_for_clean_payload(tmp_path: Path):
    home, db, writer = _journal(tmp_path)
    try:
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload={"instrument_id": "i_1", "type": "skip", "reason": "spread"},
            actor_id="agent:default",
            idempotency_key="clean-1",
        )
        result = drain_outbox(db.connection, home)
    finally:
        db.close()

    assert result.secret_warnings == []
    assert len(result.exported_files) == 1


def test_export_is_full_local_not_redacted(tmp_path: Path):
    """Documented decision: MVP export mode is full-local. No automatic
    redaction or `sources.redaction_status` filtering happens at drain
    time; both behaviors live on `review.bundle` instead. Pin this so a
    future "redacted-by-default" toggle is a deliberate contract change,
    not an accident."""

    home, db, writer = _journal(tmp_path)
    try:
        writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload={
                "instrument_id": "i_1",
                "type": "skip",
                "reason": "leaked sk-ABCDEFGHIJKL12345678 in journal",
                "tags": ["secrets-paste"],
            },
            actor_id="agent:default",
            idempotency_key="full-local-1",
        )
        result = drain_outbox(db.connection, home)
    finally:
        db.close()

    line = json.loads(result.exported_files[0].read_text())
    # The reason field still contains the raw secret (full-local export).
    assert "sk-ABCDEFGHIJKL12345678" in line["args"]["reason"]
    # And the operator got a stderr-equivalent surface via the result.
    assert result.secret_warnings, "expected the drain to surface the warning"
