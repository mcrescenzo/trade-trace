"""Deterministic autonomous substrate fixture artifacts.

These fixtures are contract-level scaffolding for future autonomous substrate
migrations/projections. They intentionally do not create storage tables, tools,
network calls, schedules, or execution behavior.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from trade_trace.contracts.autonomous_substrate import (
    CONTRACT_VERSION,
    EVENT_TYPE_EXPECTATIONS,
    AutonomousRecordFamily,
    RedactionProfile,
)

ANCHOR: Final = "2026-01-01T12:00:00.000Z"


@dataclass(frozen=True)
class AutonomousFixtureRow:
    """One deterministic event fixture plus its projection delta semantics."""

    record_id: str
    event_type: str
    family: AutonomousRecordFamily
    record: Mapping[str, object]
    projection_deltas: Mapping[str, float]
    caveats: tuple[str, ...] = ()


def _canonical_hash(value: Mapping[str, object]) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _canonical_fixture_payload(record: Mapping[str, object]) -> dict[str, object]:
    """Return the final sanitized fixture payload covered by content_hash."""
    return {key: value for key, value in record.items() if key != "content_hash"}


def _finalize_content_hash(record: dict[str, object]) -> dict[str, object]:
    # Deterministic fixture hashing is contract-level until concrete storage lands.
    record["content_hash"] = _canonical_hash(_canonical_fixture_payload(record))
    return record


def _base_record(family: AutonomousRecordFamily, slug: str) -> dict[str, object]:
    semantic_key = f"{family.value}:fixture:{slug}"
    return {
        "source_kind": "fixture_import",
        "source_ref": f"fixture://autonomous-substrate/{slug}",
        "captured_at": ANCHOR,
        "effective_at": ANCHOR,
        "as_of": ANCHOR,
        "retrieved_at": ANCHOR,
        "imported_at": ANCHOR,
        "schema_version": CONTRACT_VERSION,
        "source_precedence": "fixture_canonical_over_adapter_cache",
        "confidence": "fixture-high",
        "staleness": "fresh",
        "content_hash": "sha256:pending-final-canonical-fixture-payload",
        "redacted_artifact_ref": f"artifact://redacted/autonomous-substrate/{slug}",
        "idempotency_key": f"idem-autonomous-fixture-{slug}",
        "semantic_key": semantic_key,
        "supersedes_record_id": None,
        "provenance": {
            "actor": "agent:fixture",
            "run_id": "autonomous-substrate-fixture-v1",
            "private_payload_ingested": False,
            "live_network_used": False,
        },
        "redaction_profile": RedactionProfile.INTERNAL_REVIEW.value,
    }


def autonomous_minimal_records() -> tuple[AutonomousFixtureRow, ...]:
    """Return one valid minimal deterministic record for every event family."""

    rows: list[AutonomousFixtureRow] = []
    for index, expectation in enumerate(EVENT_TYPE_EXPECTATIONS):
        slug = f"minimal-{expectation.record_family.value}-{index:02d}"
        record = _base_record(expectation.record_family, slug)
        record |= {
            "event_type": expectation.event_type,
            "intent_id": "intent_fixture_001",
            "risk_check_id": "risk_fixture_001",
            "policy_id": "policy_fixture_boundary",
            "policy_version": "v1",
            "expires_at": "2026-01-02T12:00:00.000Z",
        }
        _finalize_content_hash(record)
        rows.append(AutonomousFixtureRow(
            record_id=f"auto_fixture_{index:02d}",
            event_type=expectation.event_type,
            family=expectation.record_family,
            record=record,
            projection_deltas={},
        ))
    return tuple(rows)


def autonomous_lifecycle_rows() -> tuple[AutonomousFixtureRow, ...]:
    """Append-only lifecycle records with duplicate replay and correction rows.

    The duplicate row shares the original idempotency key and semantic key and
    carries zero projection deltas, proving replay must not double-count
    exposure, fills, P&L, or violations. The correction row is append-only and
    references the superseded record.
    """

    intent = _base_record(AutonomousRecordFamily.EXECUTION_INTENT, "intent-001")
    intent |= {"event_type": "execution_intent.recorded", "intent_id": "intent_fixture_001"}
    _finalize_content_hash(intent)
    risk = _base_record(AutonomousRecordFamily.RISK_CHECK, "risk-001")
    risk |= {
        "event_type": "risk_check.recorded",
        "intent_id": "intent_fixture_001",
        "policy_id": "policy_fixture_boundary",
        "policy_version": "v1",
        "violations_count": 1,
    }
    _finalize_content_hash(risk)
    fill = _base_record(AutonomousRecordFamily.PAPER_FILL, "paper-fill-001")
    fill |= {
        "event_type": "paper_fill.recorded",
        "intent_id": "intent_fixture_001",
        "quantity": 10,
        "price": 0.42,
        "paper_realized_pnl": 0.0,
    }
    _finalize_content_hash(fill)
    duplicate_fill = dict(fill)
    correction = dict(fill)
    correction |= {
        "idempotency_key": "idem-autonomous-fixture-paper-fill-001-correction",
        "semantic_key": "paper_fill:fixture:paper-fill-001:correction",
        "supersedes_record_id": "auto_lifecycle_fill_001",
        "quantity": 8,
    }
    _finalize_content_hash(correction)
    stale_snapshot = _base_record(AutonomousRecordFamily.ACCOUNT_SNAPSHOT, "stale-snapshot-001")
    stale_snapshot |= {
        "event_type": "account_snapshot.imported",
        "source_precedence": "external_statement_over_adapter_cache",
        "confidence": "fixture-medium",
        "staleness": "stale:PT48H",
        "missing_inputs": ["latest_settlement_statement"],
    }
    _finalize_content_hash(stale_snapshot)
    return (
        AutonomousFixtureRow("auto_lifecycle_intent_001", "execution_intent.recorded", AutonomousRecordFamily.EXECUTION_INTENT, intent, {}),
        AutonomousFixtureRow("auto_lifecycle_risk_001", "risk_check.recorded", AutonomousRecordFamily.RISK_CHECK, risk, {"violations": 1.0}),
        AutonomousFixtureRow("auto_lifecycle_fill_001", "paper_fill.recorded", AutonomousRecordFamily.PAPER_FILL, fill, {"fills": 1.0, "exposure": 4.2, "realized_pnl": 0.0}),
        AutonomousFixtureRow("auto_lifecycle_fill_001_replay", "paper_fill.recorded", AutonomousRecordFamily.PAPER_FILL, duplicate_fill, {"fills": 0.0, "exposure": 0.0, "realized_pnl": 0.0}, caveats=("duplicate_idempotency_replay",)),
        AutonomousFixtureRow("auto_lifecycle_fill_001_correction", "paper_fill.recorded", AutonomousRecordFamily.PAPER_FILL, correction, {"fills": 0.0, "exposure": -0.84, "realized_pnl": 0.0}, caveats=("append_only_correction",)),
        AutonomousFixtureRow("auto_lifecycle_stale_snapshot_001", "account_snapshot.imported", AutonomousRecordFamily.ACCOUNT_SNAPSHOT, stale_snapshot, {}, caveats=("stale_input", "missing_input")),
    )


def redaction_profile_examples() -> tuple[Mapping[str, object], ...]:
    return tuple(
        {
            "profile": profile.value,
            "visible_fields": ["schema_version", "source_kind", "content_hash", "public_polymarket_id"],
            "artifact_ref": f"artifact://redacted/profile/{profile.value}",
        }
        for profile in RedactionProfile
    )


def aggregate_projection_deltas(rows: Iterable[AutonomousFixtureRow]) -> dict[str, float]:
    totals: dict[str, float] = {}
    seen_idempotency_keys: set[str] = set()
    for row in rows:
        key = str(row.record["idempotency_key"])
        if key in seen_idempotency_keys:
            continue
        seen_idempotency_keys.add(key)
        for name, delta in row.projection_deltas.items():
            totals[name] = round(totals.get(name, 0.0) + float(delta), 12)
    return totals
