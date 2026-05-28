from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from trade_trace.contracts.autonomous_fixtures import (
    aggregate_projection_deltas,
    autonomous_lifecycle_rows,
    autonomous_minimal_records,
    redaction_profile_examples,
)
from trade_trace.contracts.autonomous_substrate import (
    ALL_AUTONOMOUS_RECORD_FAMILIES,
    RedactionProfile,
    assert_no_boundary_violations,
    validate_event_expectation,
)


def _canonical_fixture_hash(record: Mapping[str, object]) -> str:
    payload = {key: value for key, value in record.items() if key != "content_hash"}
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def test_autonomous_minimal_fixture_records_validate_for_every_family():
    rows = autonomous_minimal_records()

    assert {row.family for row in rows} == set(ALL_AUTONOMOUS_RECORD_FAMILIES)
    assert len({row.record_id for row in rows}) == len(rows)
    assert len({row.record["content_hash"] for row in rows}) == len(rows)

    for row in rows:
        validate_event_expectation(row.event_type, row.record)
        assert row.record["schema_version"] == "autonomous-substrate.v1"
        assert row.record["provenance"]["private_payload_ingested"] is False  # type: ignore[index]
        assert row.record["provenance"]["live_network_used"] is False  # type: ignore[index]


def test_autonomous_minimal_content_hash_covers_final_sanitized_fixture_payload():
    rows = autonomous_minimal_records()

    for row in rows:
        assert row.record["content_hash"] == _canonical_fixture_hash(row.record)

    changed = dict(rows[0].record)
    changed["event_type"] = "execution_intent.changed_for_hash_probe"
    assert changed["content_hash"] != _canonical_fixture_hash(changed)


def test_autonomous_lifecycle_fixture_covers_replay_corrections_precedence_and_caveats():
    rows = autonomous_lifecycle_rows()

    for row in rows:
        validate_event_expectation(row.event_type, row.record)

    replay_rows = [row for row in rows if "duplicate_idempotency_replay" in row.caveats]
    correction_rows = [row for row in rows if "append_only_correction" in row.caveats]
    caveat_rows = [row for row in rows if {"stale_input", "missing_input"} <= set(row.caveats)]

    assert len(replay_rows) == 1
    assert len(correction_rows) == 1
    assert len(caveat_rows) == 1
    assert correction_rows[0].record["supersedes_record_id"] == "auto_lifecycle_fill_001"
    assert caveat_rows[0].record["source_precedence"] == "external_statement_over_adapter_cache"
    assert caveat_rows[0].record["missing_inputs"] == ["latest_settlement_statement"]


def test_autonomous_lifecycle_content_hash_covers_final_replay_and_correction_payloads():
    rows = autonomous_lifecycle_rows()

    for row in rows:
        assert row.record["content_hash"] == _canonical_fixture_hash(row.record)

    original = next(row for row in rows if row.record_id == "auto_lifecycle_fill_001")
    replay = next(row for row in rows if "duplicate_idempotency_replay" in row.caveats)
    correction = next(row for row in rows if "append_only_correction" in row.caveats)

    assert replay.record["content_hash"] == original.record["content_hash"]
    assert correction.record["content_hash"] != original.record["content_hash"]

    changed_correction = dict(correction.record)
    changed_correction["quantity"] = 9
    assert changed_correction["content_hash"] != _canonical_fixture_hash(changed_correction)


def test_autonomous_lifecycle_duplicate_replay_does_not_double_count_projection_totals():
    rows = autonomous_lifecycle_rows()
    duplicate = next(row for row in rows if "duplicate_idempotency_replay" in row.caveats)
    original = next(row for row in rows if row.record_id == "auto_lifecycle_fill_001")

    assert duplicate.record["idempotency_key"] == original.record["idempotency_key"]
    assert duplicate.record["semantic_key"] == original.record["semantic_key"]

    totals = aggregate_projection_deltas(rows)
    without_duplicate_totals = aggregate_projection_deltas(
        row for row in rows if "duplicate_idempotency_replay" not in row.caveats
    )

    assert totals == without_duplicate_totals
    assert totals == {
        "violations": 1.0,
        "fills": 1.0,
        "exposure": 3.36,
        "realized_pnl": 0.0,
    }


def test_autonomous_redaction_profile_fixtures_are_safe_and_complete():
    examples = redaction_profile_examples()

    assert {example["profile"] for example in examples} == {profile.value for profile in RedactionProfile}
    assert_no_boundary_violations((f"redaction_profile.{example['profile']}", example) for example in examples)
