"""Closed-set playbook predicate metadata and evaluator.

This module is an audit-only substrate for explicit ``playbook_rule``
``meta_json`` predicate metadata. It deliberately does not parse rule prose,
evaluate arbitrary expressions, execute code, run SQL supplied by callers, or
fetch external data.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Literal

PredicateStatus = Literal["pass", "fail", "not_computable", "ambiguous", "not_applicable"]
PredicateFamily = Literal[
    "field_exists",
    "field_equals",
    "decision_type_in",
    "link_exists",
    "source_count_at_least",
    "timestamp_present",
    "forecast_resolution_rule_present",
]

PREDICATE_STATUSES: tuple[str, ...] = (
    "pass",
    "fail",
    "not_computable",
    "ambiguous",
    "not_applicable",
)
ALLOWED_PREDICATE_FAMILIES: tuple[str, ...] = (
    "field_exists",
    "field_equals",
    "decision_type_in",
    "link_exists",
    "source_count_at_least",
    "timestamp_present",
    "forecast_resolution_rule_present",
)

_DECISION_FIELDS = frozenset(
    {
        "id",
        "instrument_id",
        "thesis_id",
        "forecast_id",
        "snapshot_id",
        "type",
        "side",
        "quantity",
        "price",
        "fees",
        "slippage",
        "reason",
        "playbook_version_id",
        "review_by",
        "strategy_id",
        "agent_id",
        "model_id",
        "environment",
        "run_id",
        "created_at",
        "actor_id",
    }
)
_TIMESTAMP_FIELDS = frozenset({"created_at", "review_by"})
_EDGE_KINDS = frozenset(
    {
        "decision",
        "thesis",
        "forecast",
        "outcome",
        "snapshot",
        "instrument",
        "venue",
        "source",
        "review",
        "playbook_version",
        "memory_node",
        "signal",
        "strategy",
    }
)
_EDGE_TYPES = frozenset({"about", "supports", "contradicts", "supersedes", "derived_from", "violates", "follows"})


@dataclass(frozen=True)
class PredicateEvaluation:
    """Machine evaluation result for one closed playbook predicate."""

    status: PredicateStatus
    family: str | None = None
    decision_id: str | None = None
    rule_node_id: str | None = None
    source_refs: list[dict[str, Any]] = field(default_factory=list)
    record_refs: list[dict[str, Any]] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "family": self.family,
            "decision_id": self.decision_id,
            "rule_node_id": self.rule_node_id,
            "source_refs": self.source_refs,
            "record_refs": self.record_refs,
            "caveats": self.caveats,
        }


class PredicateValidationError(ValueError):
    """Raised when predicate metadata is not in the closed supported shape."""


def predicate_from_rule_meta(meta_json: str | dict[str, Any] | None) -> dict[str, Any]:
    """Return the explicit predicate object from a playbook rule meta_json.

    Missing predicate metadata is a validation error for metadata validation;
    callers that evaluate by rule id convert it to ``not_computable`` because
    self-reported prose rules remain valid playbook rules.
    """

    if meta_json in (None, ""):
        raise PredicateValidationError("playbook_rule meta_json has no predicate object")
    if isinstance(meta_json, str):
        try:
            meta = json.loads(meta_json)
        except json.JSONDecodeError as exc:
            raise PredicateValidationError("playbook_rule meta_json is malformed JSON") from exc
    elif isinstance(meta_json, dict):
        meta = meta_json
    else:
        raise PredicateValidationError("playbook_rule meta_json must be an object")
    if not isinstance(meta, dict):
        raise PredicateValidationError("playbook_rule meta_json must be an object")
    predicate = meta.get("predicate")
    if not isinstance(predicate, dict):
        raise PredicateValidationError("playbook_rule meta_json has no predicate object")
    validate_predicate(predicate)
    return predicate


def validate_predicate(predicate: dict[str, Any]) -> None:
    if not isinstance(predicate, dict):
        raise PredicateValidationError("predicate must be an object")
    family = predicate.get("family")
    if family not in ALLOWED_PREDICATE_FAMILIES:
        raise PredicateValidationError(f"unsupported predicate family: {family!r}")
    if "code" in predicate or "sql" in predicate or "expression" in predicate or "prompt" in predicate:
        raise PredicateValidationError("arbitrary code, SQL, expressions, and prose prompts are not supported")
    _validate_scope(predicate.get("scope", {}))
    if family in {"field_exists", "field_equals"}:
        if predicate.get("table", "decisions") != "decisions" or predicate.get("field") not in _DECISION_FIELDS:
            raise PredicateValidationError("field predicate must target an allowed decisions field")
        if family == "field_equals" and "value" not in predicate:
            raise PredicateValidationError("field_equals requires value")
    elif family == "decision_type_in":
        if not _nonempty_str_list(predicate.get("values")):
            raise PredicateValidationError("decision_type_in requires non-empty string values")
    elif family == "timestamp_present":
        if predicate.get("field") not in _TIMESTAMP_FIELDS:
            raise PredicateValidationError("timestamp_present requires an allowed timestamp field")
    elif family == "link_exists":
        if predicate.get("target_kind") not in _EDGE_KINDS or predicate.get("edge_type") not in _EDGE_TYPES:
            raise PredicateValidationError("link_exists requires closed target_kind and edge_type")
    elif family == "source_count_at_least":
        minimum = predicate.get("minimum")
        if not isinstance(minimum, int) or minimum < 0:
            raise PredicateValidationError("source_count_at_least requires non-negative integer minimum")
        edge_type = predicate.get("edge_type", "supports")
        if edge_type not in _EDGE_TYPES:
            raise PredicateValidationError("source_count_at_least requires a closed edge_type")


def evaluate_predicate(
    conn: sqlite3.Connection,
    *,
    decision_id: str,
    predicate: dict[str, Any] | None = None,
    rule_node_id: str | None = None,
) -> PredicateEvaluation:
    """Evaluate one closed predicate over recorded local SQLite fields only."""

    try:
        if predicate is None:
            if rule_node_id is None:
                raise PredicateValidationError("predicate or rule_node_id is required")
            row = conn.execute("SELECT node_type, meta_json FROM memory_nodes WHERE id = ?", (rule_node_id,)).fetchone()
            if row is None or row[0] != "playbook_rule":
                return PredicateEvaluation("not_computable", decision_id=decision_id, rule_node_id=rule_node_id, caveats=["rule_node_id is missing or not a playbook_rule"])
            try:
                predicate = predicate_from_rule_meta(row[1])
            except PredicateValidationError as exc:
                return PredicateEvaluation("not_computable", decision_id=decision_id, rule_node_id=rule_node_id, caveats=[str(exc)])
        validate_predicate(predicate)
    except PredicateValidationError as exc:
        return PredicateEvaluation("ambiguous", decision_id=decision_id, rule_node_id=rule_node_id, caveats=[str(exc)])

    family = str(predicate["family"])
    rows = conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).fetchall()
    if not rows:
        return PredicateEvaluation("not_computable", family=family, decision_id=decision_id, rule_node_id=rule_node_id, caveats=["decision_id not found"])
    if len(rows) > 1:
        return PredicateEvaluation("ambiguous", family=family, decision_id=decision_id, rule_node_id=rule_node_id, caveats=["multiple decision rows found"])
    row = rows[0]
    names = [d[0] for d in conn.execute("SELECT * FROM decisions WHERE id = ?", (decision_id,)).description]
    decision = dict(zip(names, row, strict=True))
    scope_status = _scope_status(decision, predicate.get("scope", {}))
    if scope_status is not None:
        return PredicateEvaluation(scope_status, family=family, decision_id=decision_id, rule_node_id=rule_node_id, record_refs=[{"table": "decisions", "id": decision_id}], caveats=["predicate scope does not apply to this decision"])

    if family == "field_exists":
        value = decision.get(str(predicate["field"]))
        status: PredicateStatus = "pass" if value not in (None, "") else "not_computable"
    elif family == "field_equals":
        value = decision.get(str(predicate["field"]))
        status = "not_computable" if value is None else ("pass" if value == predicate["value"] else "fail")
    elif family == "decision_type_in":
        status = "pass" if decision["type"] in predicate["values"] else "fail"
    elif family == "timestamp_present":
        value = decision.get(str(predicate["field"]))
        status = "pass" if value not in (None, "") else "not_computable"
    elif family == "link_exists":
        return _eval_link_exists(conn, decision_id, predicate, rule_node_id)
    elif family == "source_count_at_least":
        return _eval_source_count(conn, decision_id, predicate, rule_node_id)
    elif family == "forecast_resolution_rule_present":
        return _eval_forecast_resolution(conn, decision, rule_node_id)
    else:  # guarded by validate_predicate
        status = "ambiguous"
    return PredicateEvaluation(status, family=family, decision_id=decision_id, rule_node_id=rule_node_id, record_refs=[{"table": "decisions", "id": decision_id, "field": predicate.get("field")}])


def _validate_scope(scope: Any) -> None:
    if scope in (None, {}):
        return
    if not isinstance(scope, dict):
        raise PredicateValidationError("scope must be an object")
    for key in scope:
        if key not in {"decision_types", "strategy_ids", "playbook_version_ids"}:
            raise PredicateValidationError(f"unsupported scope key: {key}")
    for key in ("decision_types", "strategy_ids", "playbook_version_ids"):
        if key in scope and not _nonempty_str_list(scope[key]):
            raise PredicateValidationError(f"scope.{key} must be a non-empty string list")


def _nonempty_str_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, str) for v in value)


def _scope_status(decision: dict[str, Any], scope: Any) -> PredicateStatus | None:
    if not scope:
        return None
    if "decision_types" in scope and decision.get("type") not in scope["decision_types"]:
        return "not_applicable"
    if "strategy_ids" in scope and decision.get("strategy_id") not in scope["strategy_ids"]:
        return "not_applicable"
    if "playbook_version_ids" in scope and decision.get("playbook_version_id") not in scope["playbook_version_ids"]:
        return "not_applicable"
    return None


def _eval_link_exists(conn: sqlite3.Connection, decision_id: str, predicate: dict[str, Any], rule_node_id: str | None) -> PredicateEvaluation:
    target_kind = str(predicate["target_kind"])
    edge_type = str(predicate["edge_type"])
    if target_kind == "source":
        # ``source.attach_to_decision`` records local source attachments as
        # source -> decision edges, not decision -> source.  Source predicates
        # therefore follow the canonical attachment direction.  Other target
        # kinds keep the deterministic decision -> target link semantics.
        rows = conn.execute(
            """
            SELECT id, source_id AS linked_id
            FROM edges
            WHERE source_kind = 'source'
              AND target_kind = 'decision'
              AND target_id = ?
              AND edge_type = ?
            """,
            (decision_id, edge_type),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, target_id AS linked_id
            FROM edges
            WHERE source_kind = 'decision'
              AND source_id = ?
              AND target_kind = ?
              AND edge_type = ?
            """,
            (decision_id, target_kind, edge_type),
        ).fetchall()
    return PredicateEvaluation(
        "pass" if rows else "fail",
        family="link_exists",
        decision_id=decision_id,
        rule_node_id=rule_node_id,
        record_refs=[{"table": "edges", "id": r[0], "target_kind": target_kind, "target_id": r[1]} for r in rows],
    )


def _eval_source_count(conn: sqlite3.Connection, decision_id: str, predicate: dict[str, Any], rule_node_id: str | None) -> PredicateEvaluation:
    rows = conn.execute(
        """
        SELECT id, source_id
        FROM edges
        WHERE source_kind = 'source'
          AND target_kind = 'decision'
          AND target_id = ?
          AND edge_type = ?
        """,
        (decision_id, predicate.get("edge_type", "supports")),
    ).fetchall()
    status: PredicateStatus = "pass" if len(rows) >= predicate["minimum"] else "fail"
    return PredicateEvaluation(status, family="source_count_at_least", decision_id=decision_id, rule_node_id=rule_node_id, source_refs=[{"source_id": r[1], "edge_id": r[0]} for r in rows])


def _eval_forecast_resolution(conn: sqlite3.Connection, decision: dict[str, Any], rule_node_id: str | None) -> PredicateEvaluation:
    forecast_id = decision.get("forecast_id")
    if not forecast_id:
        return PredicateEvaluation("not_computable", family="forecast_resolution_rule_present", decision_id=decision["id"], rule_node_id=rule_node_id, caveats=["decision.forecast_id is missing"])
    rows = conn.execute("SELECT resolution_rule_text FROM forecasts WHERE id = ?", (forecast_id,)).fetchall()
    if not rows:
        return PredicateEvaluation("not_computable", family="forecast_resolution_rule_present", decision_id=decision["id"], rule_node_id=rule_node_id, caveats=["forecast_id not found"])
    if len(rows) > 1:
        return PredicateEvaluation("ambiguous", family="forecast_resolution_rule_present", decision_id=decision["id"], rule_node_id=rule_node_id, caveats=["multiple forecast rows found"])
    value = rows[0][0]
    return PredicateEvaluation("pass" if value not in (None, "") else "not_computable", family="forecast_resolution_rule_present", decision_id=decision["id"], rule_node_id=rule_node_id, record_refs=[{"table": "forecasts", "id": forecast_id, "field": "resolution_rule_text"}])
