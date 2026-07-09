"""`review.bundle` per PRD §4.2 + reports.md §5 (bead trade-trace-yai).

Bounded, deterministic external-review package. Selects decisions
matching the supported ReportFilter subset, walks out to attached
sources / reflections / playbook versions, applies the redaction rules
from reports.md §5.3 + security.md §8, and returns a canonical-JSON
bundle whose `bundle_hash` (sha-256 of the canonical bytes of `data`
minus the hash itself) is stable across runs for an identical DB state
plus identical input.

The output explicitly omits LLM-generated commentary and trade
recommendations per reports.md §5.4 — the system emits data, not
opinion.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from trade_trace.contracts.autonomous_substrate import RedactionProfile
from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.report_filter import STRATEGY_NONE_SENTINEL, ReportFilter
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.logging import get_logger
from trade_trace.projections import remark_open_positions
from trade_trace.reports._filter_support import (
    UnsupportedFilterError,
    _placeholders,
    applied_filter_view,
    enforce_supported_filter,
)
from trade_trace.reports.calibration import report_calibration
from trade_trace.reports.recall_receipts import (
    ATTRIBUTION_CONVENTIONS,
    report_recall_receipts,
)
from trade_trace.security.patterns import redact_for_log
from trade_trace.tools._helpers import db_for_args
from trade_trace.tools._report_filter_errors import (
    report_filter_validation_to_tool_error,
    unsupported_filter_to_tool_error,
)
from trade_trace.tools.errors import ToolError

REVIEW_BUNDLE_REPORT = "review.bundle"
REPORT_NAME = REVIEW_BUNDLE_REPORT
REPORT_FILTER_SUPPORT = frozenset({
    # The bundle scopes its decision selection through the same
    # actor/instrument/strategy spine as calibration, plus the decision_at time
    # window (the selection ordering uses decisions.created_at).
    "actors.actor_id",
    "instrument.venue_id",
    "strategy.strategy_id",
    "time_window.decision_at_gte",
    "time_window.decision_at_lt",
})
CONTRACT_VERSION = "1.0"
RECALL_RECEIPTS_MAX_BLOCKS = 50
DEFAULT_REDACTION_PROFILE = RedactionProfile.AUDIT_EXPORT.value

_SOURCE_REDACTED_DROPPED_FIELDS = ("body", "extracted_text", "excerpt",
                                   "summary", "note")
"""Per reports.md §5.3: content-bearing columns dropped when a source
is `redaction_status='redacted'`. `body` is listed for forward
compatibility with the documented field; the M1 sources schema does
not currently have a `body` column but the doc references it for the
contract."""


class ReviewBundleInput(BaseModel):
    """Input contract for review.bundle (reports.md §5.1)."""

    model_config = ConfigDict(extra="forbid")

    filter: dict[str, Any] = Field(default_factory=dict,
                                   description="ReportFilter (reports.md §2)")
    max_records: int = Field(default=25, ge=1, le=200)
    include_sources: bool = True
    include_reflections: bool = True
    include_playbook: bool = True
    include_recall_receipts: bool = True
    include_autonomous_lifecycle: bool = True
    redaction_profile: RedactionProfile = RedactionProfile.AUDIT_EXPORT
    max_examples_per_record: int = Field(default=3, ge=0, le=20)
    home: str | None = None  # forwarded to db_for_args


class ReviewBundleOutput(BaseModel):
    """Output contract for review.bundle (reports.md §5.2)."""

    model_config = ConfigDict(extra="forbid")

    filter: dict[str, Any]
    selected: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    reflections: list[dict[str, Any]] = Field(default_factory=list)
    playbook_versions: list[dict[str, Any]] = Field(default_factory=list)
    report_summaries: dict[str, Any] = Field(default_factory=dict)
    recall_receipts: dict[str, Any] = Field(default_factory=dict)
    autonomous_lifecycle: dict[str, Any] = Field(default_factory=dict)
    redaction_profile: str = DEFAULT_REDACTION_PROFILE
    redaction_summary: dict[str, Any] = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)
    suggested_prompts: list[str] = Field(default_factory=list)
    bundle_hash: str
    contract_version: str = CONTRACT_VERSION


# -- selection ----------------------------------------------------------


def _select_decision_ids(
    conn: sqlite3.Connection, rf: ReportFilter, *, max_records: int,
) -> list[str]:
    """Return up to `max_records` decision ids matching `rf`, ordered by
    `(created_at ASC, id ASC)` so the same DB + same filter yields the
    same bundle."""

    where: list[str] = []
    params: list[Any] = []
    if rf.time_window.decision_at_gte is not None:
        where.append("d.created_at >= ?")
        params.append(rf.time_window.decision_at_gte)
    if rf.time_window.decision_at_lt is not None:
        where.append("d.created_at < ?")
        params.append(rf.time_window.decision_at_lt)
    if rf.actors.actor_id:
        where.append(f"d.actor_id IN ({_placeholders(len(rf.actors.actor_id))})")
        params.extend(rf.actors.actor_id)
    if rf.instrument.venue_id:
        where.append(
            f"i.venue_id IN ({_placeholders(len(rf.instrument.venue_id))})"
        )
        params.extend(rf.instrument.venue_id)
    if rf.strategy.strategy_id is not None:
        if rf.strategy.strategy_id == STRATEGY_NONE_SENTINEL:
            where.append("d.strategy_id IS NULL")
        else:
            where.append("d.strategy_id = ?")
            params.append(rf.strategy.strategy_id)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sql = (
        f"SELECT d.id FROM decisions d "
        f"JOIN instruments i ON i.id = d.instrument_id "
        f"{where_sql} "
        f"ORDER BY d.created_at ASC, d.id ASC LIMIT ?"
    )
    return [row[0] for row in conn.execute(sql, [*params, max_records])]


# -- row fetchers --------------------------------------------------------
#
# Each helper returns a list of plain dicts with deterministic key
# ordering and stable row ordering so the canonical JSON above hashes
# stably across runs.


def _decision_rows(
    conn: sqlite3.Connection, decision_ids: list[str],
) -> list[dict[str, Any]]:
    if not decision_ids:
        return []
    placeholders = _placeholders(len(decision_ids))
    sql = (
        "SELECT id, instrument_id, thesis_id, forecast_id, snapshot_id, "
        "type, side, quantity, price, fees, slippage, reason, "
        "playbook_version_id, review_by, strategy_id, agent_id, model_id, "
        "environment, run_id, metadata_json, created_at, actor_id "
        f"FROM decisions WHERE id IN ({placeholders}) "
        "ORDER BY created_at ASC, id ASC"
    )
    cols = [
        "id", "instrument_id", "thesis_id", "forecast_id", "snapshot_id",
        "type", "side", "quantity", "price", "fees", "slippage", "reason",
        "playbook_version_id", "review_by", "strategy_id", "agent_id",
        "model_id", "environment", "run_id", "metadata_json", "created_at",
        "actor_id",
    ]
    rows = conn.execute(sql, decision_ids).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def _fetch_by_ids(
    conn: sqlite3.Connection, table: str, ids: list[str], cols: list[str],
) -> list[dict[str, Any]]:
    if not ids:
        return []
    placeholders = _placeholders(len(ids))
    select = ", ".join(cols)
    rows = conn.execute(
        f"SELECT {select} FROM {table} WHERE id IN ({placeholders}) "
        f"ORDER BY {cols[0]}",
        ids,
    ).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def _forecast_score_rows(
    conn: sqlite3.Connection, forecast_ids: list[str],
) -> list[dict[str, Any]]:
    if not forecast_ids:
        return []
    placeholders = _placeholders(len(forecast_ids))
    rows = conn.execute(
        f"SELECT {', '.join(_FORECAST_SCORE_COLS)} FROM forecast_scores "
        f"WHERE forecast_id IN ({placeholders}) "
        "ORDER BY scored_at ASC, id ASC",
        forecast_ids,
    ).fetchall()
    return [dict(zip(_FORECAST_SCORE_COLS, row, strict=True)) for row in rows]


_THESIS_COLS = ["id", "instrument_id", "side", "body", "confidence_label",
                "strategy_id", "risk_unit_label", "max_loss_budget",
                "invalidation_condition", "valid_from", "valid_to",
                "created_at", "actor_id"]
_FORECAST_COLS = ["id", "thesis_id", "kind", "yes_label", "scoring_state",
                  "scoring_support", "resolution_at", "metadata_json",
                  "created_at", "actor_id"]
_OUTCOME_COLS = ["id", "instrument_id", "resolved_at", "outcome_label",
                 "outcome_value", "status", "metadata_json", "created_at",
                 "actor_id"]
_POSITION_COLS = ["id", "instrument_id", "kind", "side", "status",
                  "opened_at", "closed_at", "resolved_at", "realized_pnl",
                  "unrealized_pnl", "avg_entry_price", "updated_at"]
_FORECAST_SCORE_COLS = ["id", "forecast_id", "outcome_id", "metric", "score",
                        "scored_at", "actor_id", "metadata_json"]


def _related_record_rows(
    conn: sqlite3.Connection, decisions: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Walk from decisions to theses / forecasts / outcomes / positions.

    Outcomes and positions are joined via instrument_id so the reviewer
    sees the full context behind each selected decision.
    """

    instrument_ids = sorted({d["instrument_id"] for d in decisions
                             if d["instrument_id"]})
    thesis_ids = sorted({d["thesis_id"] for d in decisions if d["thesis_id"]})
    forecast_ids = sorted({d["forecast_id"] for d in decisions
                           if d["forecast_id"]})

    theses = _fetch_by_ids(conn, "theses", thesis_ids, _THESIS_COLS)
    forecasts = _fetch_by_ids(conn, "forecasts", forecast_ids, _FORECAST_COLS)
    forecast_scores = _forecast_score_rows(conn, forecast_ids)

    outcomes: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    if instrument_ids:
        placeholders = _placeholders(len(instrument_ids))
        outcome_rows = conn.execute(
            f"SELECT {', '.join(_OUTCOME_COLS)} FROM outcomes "
            f"WHERE instrument_id IN ({placeholders}) "
            "ORDER BY resolved_at ASC, id ASC",
            instrument_ids,
        ).fetchall()
        outcomes = [
            dict(zip(_OUTCOME_COLS, row, strict=True)) for row in outcome_rows
        ]
        position_rows = conn.execute(
            f"SELECT {', '.join(_POSITION_COLS)} FROM positions "
            f"WHERE instrument_id IN ({placeholders}) "
            "ORDER BY id ASC",
            instrument_ids,
        ).fetchall()
        positions = [
            dict(zip(_POSITION_COLS, row, strict=True))
            for row in position_rows
        ]
        # Re-mark open positions from the latest snapshot so the bundle's
        # positions agree with report.pnl / report.open_positions
        # (trade-trace-pr2j) instead of carrying the stale rebuild-time
        # projection column. Single shared read-layer source of truth.
        remark = remark_open_positions(conn)
        for position in positions:
            if position.get("status") == "open" and position["id"] in remark:
                position["unrealized_pnl"] = remark[position["id"]]

    return {
        "decisions": decisions,
        "theses": theses,
        "forecasts": forecasts,
        "outcomes": outcomes,
        "positions": positions,
        "forecast_scores": forecast_scores,
    }


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,),
    ).fetchone()
    return row is not None


def _fetch_table(
    conn: sqlite3.Connection, table: str, cols: list[str], where: str,
    params: list[Any], *, order_by: str,
) -> list[dict[str, Any]]:
    if not _table_exists(conn, table):
        return []
    rows = conn.execute(
        f"SELECT {', '.join(cols)} FROM {table} WHERE {where} ORDER BY {order_by}",
        params,
    ).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


def _or_in(field: str, values: list[str], params: list[Any]) -> str | None:
    if not values:
        return None
    params.extend(values)
    return f"{field} IN ({_placeholders(len(values))})"


_JSON_SCOPE_CANDIDATE_LIMIT = 1000


def _json_value_has_exact_token(value: Any, tokens: set[str]) -> bool:
    """Return true only when a parsed JSON scalar exactly equals a token.

    This intentionally does not perform substring matching. It also avoids
    SQL LIKE semantics entirely, so token values containing '%', '_' or other
    LIKE metacharacters cannot broaden lifecycle scoping.
    """

    if isinstance(value, str):
        return value in tokens
    if isinstance(value, int | float | bool) or value is None:
        return str(value) in tokens
    if isinstance(value, list):
        return any(_json_value_has_exact_token(item, tokens) for item in value)
    if isinstance(value, dict):
        return any(
            _json_value_has_exact_token(nested, tokens)
            for nested in value.values()
        )
    return False


def _json_field_has_exact_token(raw: Any, tokens: set[str]) -> bool:
    if not tokens or raw in (None, "") or not isinstance(raw, str):
        return False
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return False
    return _json_value_has_exact_token(decoded, tokens)


def _fetch_json_scoped_table(
    conn: sqlite3.Connection,
    table: str,
    cols: list[str],
    direct_clauses: list[str],
    direct_params: list[Any],
    json_fields: list[str],
    json_tokens: list[str],
    *,
    order_by: str,
    omissions: list[str],
    omission: str,
) -> list[dict[str, Any]]:
    if not _table_exists(conn, table):
        return []
    direct_scopes = [clause for clause in direct_clauses if clause]
    token_set = set(json_tokens)
    if not direct_scopes and not token_set:
        omissions.append(omission)
        return []

    selected_by_id: dict[Any, dict[str, Any]] = {}
    select = ", ".join(cols)
    if direct_scopes:
        direct_rows = conn.execute(
            f"SELECT {select} FROM {table} WHERE {' OR '.join(direct_scopes)} "
            f"ORDER BY {order_by}",
            direct_params,
        ).fetchall()
        for row in direct_rows:
            record = dict(zip(cols, row, strict=True))
            selected_by_id[record["id"]] = record

    if token_set:
        candidate_rows = conn.execute(
            f"SELECT {select} FROM {table} ORDER BY {order_by} LIMIT ?",
            (_JSON_SCOPE_CANDIDATE_LIMIT,),
        ).fetchall()
        for row in candidate_rows:
            record = dict(zip(cols, row, strict=True))
            if record["id"] in selected_by_id:
                continue
            if any(
                _json_field_has_exact_token(record.get(field), token_set)
                for field in json_fields
            ):
                selected_by_id[record["id"]] = record

    return sorted(selected_by_id.values(), key=lambda record: tuple(record.get(part.strip().split()[0]) for part in order_by.split(",")))


def _gather_autonomous_lifecycle(
    conn: sqlite3.Connection, selected: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    decisions = selected.get("decisions", [])
    decision_ids = sorted({d["id"] for d in decisions if d.get("id")})
    instrument_ids = sorted({d["instrument_id"] for d in decisions if d.get("instrument_id")})
    forecast_ids = sorted({d["forecast_id"] for d in decisions if d.get("forecast_id")})
    thesis_ids = sorted({d["thesis_id"] for d in decisions if d.get("thesis_id")})
    strategy_ids = sorted({d["strategy_id"] for d in decisions if d.get("strategy_id")})
    run_ids = sorted({d["run_id"] for d in decisions if d.get("run_id")})
    out: dict[str, Any] = {
        "scope": {"decision_ids": decision_ids, "instrument_ids": instrument_ids,
                  "forecast_ids": forecast_ids, "thesis_ids": thesis_ids,
                  "strategy_ids": strategy_ids, "run_ids": run_ids},
        "records": {}, "record_counts": {}, "omissions": [],
        "notice": "Audit/replay evidence only; not trading advice or an execution instruction.",
    }
    rec = out["records"]
    p: list[Any] = []
    clauses = [c for c in (_or_in("decision_id", decision_ids, p), _or_in("instrument_id", instrument_ids, p), _or_in("forecast_id", forecast_ids, p), _or_in("thesis_id", thesis_ids, p), _or_in("strategy_id", strategy_ids, p), _or_in("run_id", run_ids, p)) if c]
    rec["pretrade_intents"] = _fetch_table(conn, "pretrade_intents", ["id", "semantic_key", "material_hash", "market_id", "instrument_id", "snapshot_id", "thesis_id", "forecast_id", "decision_id", "risk_check_receipt_id", "strategy_id", "playbook_version_id", "proposed_shape_json", "risk_budget_json", "evidence_refs_json", "source_ids_json", "caveats_json", "approval_state", "approval_ref_id", "as_of", "run_id", "idempotency_key", "provenance_json", "created_at", "actor_id"], " OR ".join(clauses) or "0", p, order_by="created_at ASC, id ASC")
    intent_ids = sorted({r["id"] for r in rec["pretrade_intents"]})
    risk_link_ids = sorted({r.get("risk_check_receipt_id") for r in rec["pretrade_intents"] if r.get("risk_check_receipt_id")})
    p = []
    clauses = [c for c in (_or_in("decision_id", decision_ids, p), _or_in("instrument_id", instrument_ids, p), _or_in("strategy_id", strategy_ids, p), _or_in("id", risk_link_ids, p)) if c]
    rec["risk_check_receipts"] = _fetch_table(conn, "risk_check_receipts", ["id", "receipt_hash", "policy_version_id", "status", "outcome", "intended_action", "proposed_intent_hash", "decision_id", "market_id", "instrument_id", "strategy_id", "snapshot_id", "exposure_input_ids_json", "evidence_input_ids_json", "input_provenance_json", "as_of", "waived_by", "waiver_reason", "created_at", "actor_id"], " OR ".join(clauses) or "0", p, order_by="created_at ASC, id ASC")
    risk_ids = sorted({r["id"] for r in rec["risk_check_receipts"]})
    rec["risk_check_rule_results"] = _fetch_table(conn, "risk_check_rule_results", ["id", "receipt_id", "rule_id", "reason_code", "severity", "observed_value_json", "threshold_json", "contributing_record_ids_json", "waiver_required", "caveat", "missing_data", "stale_data"], f"receipt_id IN ({_placeholders(len(risk_ids))})" if risk_ids else "0", risk_ids, order_by="receipt_id ASC, rule_id ASC")
    p = []
    clauses = [c for c in (_or_in("pretrade_intent_id", intent_ids, p), _or_in("risk_check_receipt_id", risk_ids, p), _or_in("instrument_id", instrument_ids, p), _or_in("strategy_id", strategy_ids, p), _or_in("run_id", run_ids, p)) if c]
    rec["approval_waiver_records"] = _fetch_table(conn, "approval_waiver_records", ["id", "semantic_key", "material_hash", "record_type", "decision", "pretrade_intent_id", "risk_check_receipt_id", "strategy_id", "instrument_id", "market_id", "actor_mode", "decision_actor_id", "decision_at", "reason", "modifications_json", "scope_json", "limits_json", "expires_at", "revoked_at", "revocation_reason", "waiver_class", "policy_version_id", "policy_version", "policy_evidence_json", "environment_label", "account_label", "external_receipt_refs_json", "caveats_json", "run_id", "idempotency_key", "provenance_json", "created_at", "actor_id"], " OR ".join(clauses) or "0", p, order_by="created_at ASC, id ASC")
    p = []
    clauses = [c for c in (_or_in("pretrade_intent_id", intent_ids, p), _or_in("instrument_id", instrument_ids, p), _or_in("source_run_id", run_ids, p)) if c]
    rec["external_execution_receipts"] = _fetch_table(conn, "external_execution_receipts", ["id", "schema_version", "semantic_key", "material_hash", "lifecycle_state", "external_event_type", "pretrade_intent_id", "approval_ref_id", "market_id", "instrument_id", "external_order_ref", "external_fill_ref", "external_event_ref", "source_system", "source_run_id", "retrieved_at", "as_of", "imported_at", "artifact_hash", "redacted_artifact_ref", "sanitized_facts_json", "caveats_json", "provenance_json", "quarantine_reason", "idempotency_key", "actor_id"], " OR ".join(clauses) or "0", p, order_by="imported_at ASC, id ASC")
    account_cols = ["id", "schema_version", "semantic_key", "material_hash", "source_system", "source_run_id", "source_precedence", "confidence_label", "staleness_status", "environment_label", "account_label", "venue_label", "captured_at", "effective_at", "as_of", "retrieved_at", "imported_at", "artifact_hash", "redacted_artifact_ref", "balances_json", "collateral_json", "open_orders_json", "positions_json", "fills_trades_json", "unsettled_claims_json", "public_allowance_facts_json", "caveats_json", "provenance_json", "quarantine_reason", "idempotency_key", "actor_id"]
    scoped_ids = sorted(set(decision_ids) | set(instrument_ids) | set(forecast_ids) | set(thesis_ids) | set(intent_ids) | set(risk_ids))
    p = []
    account_json_fields = ["balances_json", "collateral_json", "open_orders_json", "positions_json", "fills_trades_json", "unsettled_claims_json", "public_allowance_facts_json", "caveats_json", "provenance_json"]
    account_clauses = [c for c in (_or_in("source_run_id", run_ids, p),) if c]
    rec["account_snapshots"] = _fetch_json_scoped_table(conn, "account_snapshots", account_cols, account_clauses, p, account_json_fields, scoped_ids, order_by="as_of ASC, id ASC", omissions=out["omissions"], omission="account_snapshots omitted when no safe scoped account snapshot relation matched selected run IDs or exact lifecycle identifier JSON tokens")
    p = []
    clauses = [c for c in (_or_in("pretrade_intent_id", intent_ids, p), _or_in("instrument_id", instrument_ids, p)) if c]
    rec["paper_fill_records"] = _fetch_table(conn, "paper_fill_records", ["id", "schema_version", "semantic_key", "material_hash", "environment_label", "account_label", "market_id", "instrument_id", "pretrade_intent_id", "side", "outcome_side", "requested_quantity", "filled_quantity", "remaining_quantity", "limit_price", "average_fill_price", "fee_amount", "slippage_cap_bps", "quote_id", "book_id", "snapshot_id", "snapshot_as_of", "order_as_of", "freshness_status", "fill_status", "conservative_fill_model", "mark_source", "mark_as_of", "confidence_label", "staleness_status", "source_precedence", "caveats_json", "evidence_json", "provenance_json", "recorded_at", "idempotency_key", "actor_id"], " OR ".join(clauses) or "0", p, order_by="recorded_at ASC, id ASC")
    fill_ids = sorted({r["id"] for r in rec["paper_fill_records"]})
    snapshot_ids = sorted({d["snapshot_id"] for d in decisions if d.get("snapshot_id")})
    reconciliation_cols = ["id", "schema_version", "semantic_key", "material_hash", "as_of", "source", "source_precedence_json", "expected_state_json", "observed_imported_state_json", "diff_json", "diff_severity", "mismatch_codes_json", "resolution_status", "contributing_ids_json", "caveats_json", "provenance_json", "imported_at", "recorded_at", "idempotency_key", "actor_id"]
    reconciliation_ids = sorted(set(scoped_ids) | set(fill_ids) | set(snapshot_ids))
    p = []
    reconciliation_json_fields = ["source_precedence_json", "expected_state_json", "observed_imported_state_json", "diff_json", "contributing_ids_json", "caveats_json", "provenance_json"]
    rec["reconciliation_records"] = _fetch_json_scoped_table(conn, "reconciliation_records", reconciliation_cols, [], p, reconciliation_json_fields, reconciliation_ids, order_by="as_of ASC, id ASC", omissions=out["omissions"], omission="reconciliation_records omitted when no safe scoped reconciliation relation matched selected exact lifecycle identifier JSON tokens")
    rec["autonomous_run_records"] = _fetch_table(conn, "autonomous_run_records", ["id", "schema_version", "semantic_key", "material_hash", "mode", "run_status", "run_id", "session_id", "actor_id_recorded", "model_id", "provider_id", "environment_label", "policy_version", "started_at", "ended_at", "as_of", "config_json", "provenance_json", "caveats_json", "recorded_at", "idempotency_key", "recorder_actor_id"], f"run_id IN ({_placeholders(len(run_ids))})" if run_ids else "0", run_ids, order_by="started_at ASC, id ASC")
    rec["autonomous_incident_records"] = _fetch_table(conn, "autonomous_incident_records", ["id", "schema_version", "semantic_key", "material_hash", "incident_type", "severity", "resolution_status", "run_record_id", "run_id", "session_id", "occurred_at", "as_of", "summary", "imported_fact_only", "evidence_state", "link_ids_json", "evidence_refs_json", "caveats_json", "provenance_json", "recorded_at", "idempotency_key", "recorder_actor_id"], f"run_id IN ({_placeholders(len(run_ids))})" if run_ids else "0", run_ids, order_by="occurred_at ASC, id ASC")
    out["record_counts"] = {k: len(v) for k, v in rec.items()}
    return out


# -- sources, reflections, playbooks ------------------------------------


_SOURCE_COLS = [
    "id", "kind", "ref", "title", "note", "stance", "freshness_at",
    "content_hash", "captured_at", "uri", "media_type", "storage_kind",
    "retrieved_at", "source_author", "publisher", "excerpt",
    "extracted_text", "summary", "hash_algorithm", "redaction_status",
    "license_or_terms_note", "metadata_json", "created_at", "actor_id",
]


def _gather_attached_sources(
    conn: sqlite3.Connection, *, target_kinds: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], int, int]:
    """Return the deduped list of sources attached to any of the given
    `target_kind→target_ids` groups via `edges` with source_kind='source'.

    Applies the §5.3 redaction rules:
    - `sensitive` rows are omitted entirely; the omitted count is
      returned for the caller's caveat list.
    - `redacted` rows are included but their content-bearing columns
      (`body`/`extracted_text`/`excerpt`/`summary`/`note`) are nulled
      out; the redacted count is returned alongside.
    - `none` rows pass through untouched.
    """

    edge_filters: list[str] = []
    params: list[Any] = []
    for kind, ids in target_kinds.items():
        if not ids:
            continue
        edge_filters.append(
            f"(e.target_kind = ? AND e.target_id IN ({_placeholders(len(ids))}))"
        )
        params.append(kind)
        params.extend(ids)
    if not edge_filters:
        return [], 0, 0

    sql = (
        "SELECT DISTINCT e.source_id FROM edges e "
        "WHERE e.source_kind = 'source' AND ("
        + " OR ".join(edge_filters)
        + ")"
    )
    source_ids = sorted({row[0] for row in conn.execute(sql, params)})
    if not source_ids:
        return [], 0, 0

    sources = _fetch_by_ids(conn, "sources", source_ids, _SOURCE_COLS)

    included: list[dict[str, Any]] = []
    omitted_sensitive = 0
    redacted_count = 0
    for src in sources:
        status = src.get("redaction_status") or "none"
        if status == "sensitive":
            omitted_sensitive += 1
            continue
        if status == "redacted":
            for field in _SOURCE_REDACTED_DROPPED_FIELDS:
                if field in src:
                    src[field] = None
            redacted_count += 1
        included.append(src)
    return included, omitted_sensitive, redacted_count


_REFLECTION_COLS = ["id", "node_type", "body", "title", "importance",
                    "confidence_base", "valid_from", "valid_to",
                    "metadata_json", "created_at", "actor_id"]


def _gather_reflections(
    conn: sqlite3.Connection, *, target_kinds: dict[str, list[str]],
) -> list[dict[str, Any]]:
    """Return memory_node rows of type='reflection' attached via an
    `about` edge to any selected target."""

    edge_filters: list[str] = []
    params: list[Any] = []
    for kind, ids in target_kinds.items():
        if not ids:
            continue
        edge_filters.append(
            f"(e.target_kind = ? AND e.target_id IN ({_placeholders(len(ids))}))"
        )
        params.append(kind)
        params.extend(ids)
    if not edge_filters:
        return []

    sql = (
        "SELECT m.id, m.node_type, m.body, m.title, m.importance, "
        "m.confidence_base, m.valid_from, m.valid_to, m.meta_json, "
        "m.created_at, m.actor_id "
        "FROM memory_nodes m JOIN edges e ON e.source_id = m.id "
        "WHERE e.source_kind = 'memory_node' AND m.node_type = 'reflection' "
        "AND e.edge_type = 'about' AND ("
        + " OR ".join(edge_filters)
        + ") ORDER BY m.created_at ASC, m.id ASC"
    )
    rows = conn.execute(sql, params).fetchall()
    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        node_id = row[0]
        if node_id in deduped:
            continue
        deduped[node_id] = dict(zip(
            ["id", "node_type", "body", "title", "importance",
             "confidence_base", "valid_from", "valid_to", "metadata_json",
             "created_at", "actor_id"],
            row, strict=True,
        ))
    return list(deduped.values())


def _gather_playbook_versions(
    conn: sqlite3.Connection, decision_ids: list[str],
) -> list[dict[str, Any]]:
    if not decision_ids:
        return []
    placeholders = _placeholders(len(decision_ids))
    cols = ["id", "playbook_id", "version", "parent_version_id",
            "provenance_reflection_node_id", "description",
            "metadata_json", "created_at", "actor_id"]
    sql = (
        "SELECT DISTINCT pv.id, pv.playbook_id, pv.version, "
        "pv.parent_version_id, pv.provenance_reflection_node_id, "
        "pv.description, pv.metadata_json, pv.created_at, pv.actor_id "
        "FROM playbook_versions pv "
        "JOIN decision_playbook_rules dpr "
        "  ON dpr.playbook_version_id = pv.id "
        f"WHERE dpr.decision_id IN ({placeholders}) "
        "ORDER BY pv.created_at ASC, pv.id ASC"
    )
    rows = conn.execute(sql, decision_ids).fetchall()
    return [dict(zip(cols, row, strict=True)) for row in rows]


# -- redaction sweep ---------------------------------------------------

_REDACTED = "[REDACTED]"
_SENSITIVE_KEY_FRAGMENTS = (
    "account_label", "address", "wallet", "strategy_id", "source_text",
    "note", "notes", "summary", "excerpt", "extracted_text", "body",
    "external_order_ref", "external_order_id", "external_fill_ref",
    "external_event_ref", "raw_payload_ref", "redacted_artifact_ref",
    "actor_id_recorded", "decision_actor_id", "recorder_actor_id",
)
_PUBLIC_PM_KEYS = {"condition_id", "outcome_token_ids", "gamma_market_id", "gamma_event_id"}


def _apply_profile_redaction(value: Any, *, counter: dict[str, int]) -> Any:
    if isinstance(value, list):
        return [_apply_profile_redaction(item, counter=counter) for item in value]
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, nested in value.items():
            key_lower = str(key).lower()
            if key_lower in _PUBLIC_PM_KEYS:
                redacted[key] = nested
            elif any(fragment in key_lower for fragment in _SENSITIVE_KEY_FRAGMENTS):
                if nested not in (None, "", [], {}):
                    counter["profile_replacements"] += 1
                redacted[key] = _REDACTED if nested is not None else None
            else:
                redacted[key] = _apply_profile_redaction(nested, counter=counter)
        return redacted
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith(('{', '[')):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return value
            redacted = _apply_profile_redaction(decoded, counter=counter)
            return json.dumps(redacted, sort_keys=True, separators=(",", ":"))
        return value
    return value

def _redact_strings_in_place(value: Any, *, counter: dict[str, int]) -> Any:
    """Recursively walk `value`, replacing any secret-shaped substring in
    a string with `REDACTED-<pattern_kind>` via `redact_for_log`. The
    counter tracks how many strings were actually modified so the
    bundle's `caveats` can surface the number.

    Defense in depth: write-time scanning already rejects secret-shaped
    free text, but the bundle runs the pass anyway per security.md §8.
    """

    if isinstance(value, str):
        redacted = redact_for_log(value)
        if redacted != value:
            counter["replacements"] += 1
        return redacted
    if isinstance(value, list):
        return [_redact_strings_in_place(item, counter=counter)
                for item in value]
    if isinstance(value, dict):
        return {k: _redact_strings_in_place(v, counter=counter)
                for k, v in value.items()}
    return value


# -- bundle hash -------------------------------------------------------


def _canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str).encode("utf-8")


def _bundle_hash(payload: dict[str, Any]) -> str:
    """Return the canonical sha-256 hash of `payload` (without the
    `bundle_hash` field itself)."""

    body = {k: v for k, v in payload.items() if k != "bundle_hash"}
    digest = hashlib.sha256(_canonical_json(body)).hexdigest()
    return f"sha256:{digest}"


# -- main handler ------------------------------------------------------


def _prepare_bundle_filter(
    args: dict[str, Any],
) -> tuple[ReviewBundleInput, ReportFilter, dict[str, Any]]:
    try:
        parsed = ReviewBundleInput.model_validate(args)
    except ValidationError as exc:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"review.bundle input validation failed: {exc.errors()}",
            details={"validation_errors": exc.errors()},
        ) from exc

    try:
        rf = ReportFilter.model_validate(parsed.filter)
    except ValidationError as exc:
        raise report_filter_validation_to_tool_error(exc) from exc

    try:
        enforce_supported_filter(rf, report=REVIEW_BUNDLE_REPORT)
    except UnsupportedFilterError as exc:
        raise unsupported_filter_to_tool_error(exc) from exc
    filter_view = applied_filter_view(rf, report=REVIEW_BUNDLE_REPORT)

    return parsed, rf, filter_view


def _gather_selected_context(
    conn: sqlite3.Connection, rf: ReportFilter, *, max_records: int,
) -> tuple[list[str], dict[str, list[dict[str, Any]]], dict[str, list[str]]]:
    decision_ids = _select_decision_ids(
        conn, rf, max_records=max_records,
    )
    decisions = _decision_rows(conn, decision_ids)
    selected = _related_record_rows(conn, decisions)

    target_kinds = {
        "decision": [d["id"] for d in selected["decisions"]],
        "thesis": [t["id"] for t in selected["theses"]],
        "forecast": [f["id"] for f in selected["forecasts"]],
        "outcome": [o["id"] for o in selected["outcomes"]],
    }

    return decision_ids, selected, target_kinds


def _gather_optional_attachments(
    conn: sqlite3.Connection,
    parsed: ReviewBundleInput,
    *,
    decision_ids: list[str],
    target_kinds: dict[str, list[str]],
) -> tuple[list[dict[str, Any]], int, int,
           list[dict[str, Any]], list[dict[str, Any]]]:
    sources: list[dict[str, Any]] = []
    omitted_sensitive = 0
    redacted_sources = 0
    if parsed.include_sources:
        sources, omitted_sensitive, redacted_sources = (
            _gather_attached_sources(conn, target_kinds=target_kinds)
        )

    reflections: list[dict[str, Any]] = []
    if parsed.include_reflections:
        reflections = _gather_reflections(conn, target_kinds=target_kinds)

    playbook_versions: list[dict[str, Any]] = []
    if parsed.include_playbook:
        playbook_versions = _gather_playbook_versions(
            conn, decision_ids=decision_ids,
        )

    return (sources, omitted_sensitive, redacted_sources, reflections,
            playbook_versions)


def _report_summaries(
    conn: sqlite3.Connection, *, filter_view: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        calibration = report_calibration(conn, raw_filter=filter_view)
        calibration_summary = calibration["summary"]
    except Exception as _exc:  # noqa: BLE001 - bundle continues with empty summary
        get_logger(__name__).warning(
            "calibration report failed inside review bundle",
            extra={"error": str(_exc)},
        )
        calibration_summary = {"sample_size": 0, "sample_warning": None}

    report_summaries = {"calibration": calibration_summary}
    return report_summaries, calibration_summary


def _gather_recall_receipt_blocks(
    conn: sqlite3.Connection,
    *,
    decision_ids: list[str],
    include_recall_receipts: bool,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": "included",
        "consumer_scope": "selected_decisions",
        "receipt_refs": [],
        "blocks": [],
        "caveat_codes": [],
        "omissions": [],
        "truncated": False,
        "attribution_conventions": ATTRIBUTION_CONVENTIONS,
    }
    if not include_recall_receipts:
        return {**base, "status": "omitted", "omissions": ["omitted_by_input_flag"]}
    if not decision_ids:
        return {**base, "status": "omitted", "omissions": ["omitted_no_selected_consumers"]}

    blocks_by_receipt_id: dict[str, dict[str, Any]] = {}
    caveat_codes: set[str] = set()
    truncated = False
    for decision_id in decision_ids:
        remaining = RECALL_RECEIPTS_MAX_BLOCKS - len(blocks_by_receipt_id)
        if remaining <= 0:
            truncated = True
            break
        report = report_recall_receipts(
            conn,
            consumer_kind="decision",
            consumer_id=decision_id,
            limit=remaining + 1,
        )
        receipts = report.get("recall_receipts", [])
        if len(receipts) > remaining:
            truncated = True
            receipts = receipts[:remaining]
        for receipt in receipts:
            block = _recall_receipt_block(receipt, consumer_id=decision_id)
            blocks_by_receipt_id.setdefault(block["receipt_id"], block)
            caveat_codes.update(block["caveat_codes"])

    blocks = [blocks_by_receipt_id[key] for key in sorted(blocks_by_receipt_id)]
    omissions: list[str] = []
    if not blocks:
        omissions.append("no_recall_receipts")
    if truncated:
        omissions.append("truncated")
        caveat_codes.add("RECALL_RECEIPTS_TRUNCATED")
    return {
        **base,
        "status": "included" if blocks else "omitted",
        "receipt_refs": [
            {"receipt_id": block["receipt_id"], "recall_id": block["recall_id"]}
            for block in blocks
        ],
        "blocks": blocks,
        "caveat_codes": sorted(caveat_codes),
        "omissions": omissions,
        "truncated": truncated,
    }


def _recall_receipt_block(receipt: dict[str, Any], *, consumer_id: str) -> dict[str, Any]:
    item_caveats = sorted({
        code
        for item in receipt.get("items", [])
        for code in item.get("caveat_codes", [])
    })
    caveats = sorted(set(receipt.get("caveat_codes", [])) | set(item_caveats))
    return {
        "receipt_id": receipt["receipt_id"],
        "recall_id": receipt["recall_id"],
        "consumer": {"kind": "decision", "id": consumer_id},
        "node_ids_returned": receipt.get("node_ids_returned", []),
        "node_ids_used": receipt.get("node_ids_used", []),
        "node_ids_ignored_or_unattributed": receipt.get("node_ids_ignored_or_unattributed", []),
        "caveat_codes": caveats,
        "item_caveats": [
            {
                "node_id": item.get("id"),
                "status": item.get("status"),
                "attribution_status": item.get("attribution_status"),
                "caveat_codes": item.get("caveat_codes", []),
            }
            for item in receipt.get("items", [])
            if item.get("caveat_codes")
        ],
        "source_refs": receipt.get("source_refs", []),
    }


def _build_caveats(
    *,
    calibration_summary: dict[str, Any],
    omitted_sensitive: int,
    redacted_sources: int,
) -> list[str]:
    caveats: list[str] = []
    sample_warning = (calibration_summary or {}).get("sample_warning")
    if sample_warning:
        caveats.append(sample_warning)
    if omitted_sensitive:
        caveats.append(
            f"{omitted_sensitive} source(s) omitted (redaction_status=sensitive)"
        )
    if redacted_sources:
        caveats.append(
            f"{redacted_sources} source(s) included with content stripped "
            f"(redaction_status=redacted)"
        )
    return caveats


def _apply_redaction_sweep(
    *,
    selected: dict[str, list[dict[str, Any]]],
    sources: list[dict[str, Any]],
    reflections: list[dict[str, Any]],
    playbook_versions: list[dict[str, Any]],
    recall_receipts: dict[str, Any],
    autonomous_lifecycle: dict[str, Any],
    caveats: list[str],
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]],
           list[dict[str, Any]], list[dict[str, Any]], dict[str, Any],
           dict[str, Any], dict[str, Any]]:
    profile_counter = {"profile_replacements": 0}
    selected = _apply_profile_redaction(selected, counter=profile_counter)
    sources = _apply_profile_redaction(sources, counter=profile_counter)
    reflections = _apply_profile_redaction(reflections, counter=profile_counter)
    playbook_versions = _apply_profile_redaction(playbook_versions, counter=profile_counter)
    recall_receipts = _apply_profile_redaction(recall_receipts, counter=profile_counter)
    autonomous_lifecycle = _apply_profile_redaction(
        autonomous_lifecycle, counter=profile_counter,
    )

    secret_counter = {"replacements": 0}
    selected = _redact_strings_in_place(selected, counter=secret_counter)
    sources = _redact_strings_in_place(sources, counter=secret_counter)
    reflections = _redact_strings_in_place(reflections, counter=secret_counter)
    playbook_versions = _redact_strings_in_place(
        playbook_versions, counter=secret_counter,
    )
    recall_receipts = _redact_strings_in_place(recall_receipts, counter=secret_counter)
    autonomous_lifecycle = _redact_strings_in_place(
        autonomous_lifecycle, counter=secret_counter,
    )
    if secret_counter["replacements"]:
        caveats.append(
            f"{secret_counter['replacements']} secret-shaped value(s) "
            f"replaced with REDACTED-* tokens (security.md §8)"
        )
    redaction_summary = {
        "profile_replacements": profile_counter["profile_replacements"],
        "secret_pattern_replacements": secret_counter["replacements"],
        "profile_scope": "profile labels currently share the conservative audit-export minimum redaction: labels, addresses, strategy IDs, source text/notes, external order refs, raw artifact refs, and sensitive actor metadata are redacted while public PM IDs are preserved.",
        "profile_semantics": "redaction_profile values are accepted as compatibility labels; evaluator_only and audit_export currently apply identical conservative audit-export minimum redaction.",
    }
    return (selected, sources, reflections, playbook_versions, recall_receipts,
            autonomous_lifecycle, redaction_summary)


def _assemble_bundle(
    *,
    filter_view: dict[str, Any],
    selected: dict[str, list[dict[str, Any]]],
    sources: list[dict[str, Any]],
    reflections: list[dict[str, Any]],
    playbook_versions: list[dict[str, Any]],
    report_summaries: dict[str, Any],
    recall_receipts: dict[str, Any],
    autonomous_lifecycle: dict[str, Any],
    redaction_profile: str,
    redaction_summary: dict[str, Any],
    caveats: list[str],
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "filter": filter_view,
        "selected": selected,
        "sources": sources,
        "reflections": reflections,
        "playbook_versions": playbook_versions,
        "report_summaries": report_summaries,
        "recall_receipts": recall_receipts,
        "autonomous_lifecycle": autonomous_lifecycle,
        "redaction_profile": redaction_profile,
        "redaction_summary": redaction_summary,
        "caveats": caveats,
        "suggested_prompts": _suggested_prompts(selected),
        "contract_version": CONTRACT_VERSION,
    }
    data["bundle_hash"] = _bundle_hash(data)
    return data


def _review_bundle_handler(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    parsed, rf, filter_view = _prepare_bundle_filter(args)

    with db_for_args(args) as db:
        conn = db.connection
        decision_ids, selected, target_kinds = _gather_selected_context(
            conn, rf, max_records=parsed.max_records,
        )
        (sources, omitted_sensitive, redacted_sources, reflections,
         playbook_versions) = _gather_optional_attachments(
            conn, parsed, decision_ids=decision_ids, target_kinds=target_kinds,
        )
        report_summaries, calibration_summary = _report_summaries(
            conn, filter_view=filter_view,
        )
        recall_receipts = _gather_recall_receipt_blocks(
            conn,
            decision_ids=decision_ids,
            include_recall_receipts=parsed.include_recall_receipts,
        )
        autonomous_lifecycle = (
            _gather_autonomous_lifecycle(conn, selected)
            if parsed.include_autonomous_lifecycle else {}
        )

    caveats = _build_caveats(
        calibration_summary=calibration_summary,
        omitted_sensitive=omitted_sensitive,
        redacted_sources=redacted_sources,
    )
    (selected, sources, reflections, playbook_versions, recall_receipts,
     autonomous_lifecycle, redaction_summary) = _apply_redaction_sweep(
        selected=selected,
        sources=sources,
        reflections=reflections,
        playbook_versions=playbook_versions,
        recall_receipts=recall_receipts,
        autonomous_lifecycle=autonomous_lifecycle,
        caveats=caveats,
    )
    data = _assemble_bundle(
        filter_view=filter_view,
        selected=selected,
        sources=sources,
        reflections=reflections,
        playbook_versions=playbook_versions,
        report_summaries=report_summaries,
        recall_receipts=recall_receipts,
        autonomous_lifecycle=autonomous_lifecycle,
        redaction_profile=parsed.redaction_profile.value,
        redaction_summary=redaction_summary,
        caveats=caveats,
    )

    ctx.meta_hints["bundle_hash"] = data["bundle_hash"]
    ctx.meta_hints["contract_version"] = CONTRACT_VERSION
    return data


def _suggested_prompts(selected: dict[str, list[dict[str, Any]]]) -> list[str]:
    """Static, deterministic prompt suggestions per reports.md §5.2.

    The bundle is NOT an LLM call; these are template prompts the
    reviewer's own model can pick up. Order is fixed so the bundle hash
    stays stable.
    """

    if not selected.get("decisions"):
        return []
    return [
        "Which decisions reflect the same root-cause mistake?",
        "Is the agent over-using any single tag?",
        "What sources tend to anchor over-confident forecasts?",
    ]


# AX-057: review.bundle was registered with neither an explicit json_schema
# nor an example_minimal, so tool.schema advertised json_schema=null and the
# MCP input_schema exposed ZERO properties — yet the runtime ReviewBundleInput
# contract accepts a full ReportFilter `filter` plus several knobs. An MCP bot
# therefore could not discover how to scope the reviewer bundle, and passing a
# `filter` even failed with a dict_type error because the undeclared param was
# stringified by the bridge. This explicit schema mirrors ReviewBundleInput so
# the scoping surface is discoverable and `filter` is passed through as an
# object; the handler/redaction logic is unchanged.
_REVIEW_BUNDLE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "filter": {"type": "object", "description": "ReportFilter object selecting the decisions to bundle. Defaults to {} (an unscoped, max_records-bounded sweep)."},
        "max_records": {"type": "integer", "minimum": 1, "maximum": 200, "description": "Max decision cases to include (default 25)."},
        "include_sources": {"type": "boolean", "description": "Include attached sources (default true)."},
        "include_reflections": {"type": "boolean", "description": "Include attached reflections (default true)."},
        "include_playbook": {"type": "boolean", "description": "Include attached playbook versions (default true)."},
        "include_recall_receipts": {"type": "boolean", "description": "Include recall-receipt attribution blocks (default true)."},
        "include_autonomous_lifecycle": {"type": "boolean", "description": "Include autonomous-lifecycle audit records (default true)."},
        "redaction_profile": {"type": "string", "enum": [m.value for m in RedactionProfile], "description": "Redaction profile label; values are accepted as compatibility labels and currently apply the conservative audit-export minimum redaction. Defaults to 'audit_export'."},
        "max_examples_per_record": {"type": "integer", "minimum": 0, "maximum": 20, "description": "Cap on attached example rows per record (default 3)."},
        "home": {"type": "string"},
    },
    "required": [],
}


def register_review_bundle(registry: ToolRegistry) -> None:
    registry.register(
        "review.bundle",
        _review_bundle_handler,
        description=(
            "Bundle a bounded case set (decisions + theses + forecasts + "
            "outcomes + positions + attached sources/reflections/playbook "
            "versions) as deterministic JSON for an external reviewer per "
            "reports.md §5. Applies the security.md §8 redaction rules: "
            "sensitive sources are omitted with a caveat, redacted sources "
            "are included with content stripped. The output's "
            "bundle_hash is sha-256 over the canonical JSON of `data` "
            "(minus the hash itself) so the same DB state + same input "
            "yields the same hash. Scope the bundle with `filter` "
            "(ReportFilter) and bound it with `max_records`."
        ),
        json_schema=_REVIEW_BUNDLE_SCHEMA,
    )
