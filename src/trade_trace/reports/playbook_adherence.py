"""`report.playbook_adherence` per bead trade-trace-fbq + reports.md §4.6.

Aggregates from `decision_playbook_rules` (no JSON parsing). Per-group
metrics: counts of considered / followed / overridden / not_applicable;
override-outcome breakdown when an outcome row exists on the linked
decision's instrument.

The group key is `playbook_version_id`; the agent can drill from a
group → contributing decision ids → the decisions themselves via the
existing list tools.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.playbook_predicates import PREDICATE_STATUSES, evaluate_predicate
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import process_filter

DEFAULT_ADHERENCE_MIN_SAMPLE = 10
"""reports.md §3.2: min 10 decisions with adherence rows."""


_STATUSES = ("considered", "followed", "overridden", "not_applicable")


def _predicate_alignment(self_reported_status: str, predicate_status: str) -> str:
    """Describe audit-only alignment without implying execution blocking."""

    if predicate_status in {"not_computable", "ambiguous"}:
        return "missing_or_unresolved_machine_audit"
    if predicate_status == "not_applicable":
        return "predicate_not_applicable"
    if self_reported_status == "followed" and predicate_status == "pass":
        return "self_report_followed_matches_predicate_pass"
    if self_reported_status == "followed" and predicate_status == "fail":
        return "mismatch_self_report_followed_predicate_fail"
    if self_reported_status == "overridden" and predicate_status == "pass":
        return "mismatch_self_report_overridden_predicate_pass"
    if self_reported_status == "overridden" and predicate_status == "fail":
        return "self_report_overridden_matches_predicate_fail"
    return "self_report_not_a_binary_adherence_claim"


def _audit_predicates(conn: sqlite3.Connection, rows: list[tuple]) -> dict[str, Any]:
    """Evaluate explicit playbook-rule predicates for report-only audit fields."""

    status_counts = {status: 0 for status in PREDICATE_STATUSES}
    alignment_counts: dict[str, int] = {}
    evaluations: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    missing_data: list[dict[str, Any]] = []
    caveats: list[str] = [
        "Predicate audit is deterministic, read-only, and report-only; it does not block execution, place trades, mutate playbooks, or provide advice.",
        "Only explicit memory_nodes.meta_json.predicate metadata is evaluated; rule body/prose is not parsed.",
    ]

    for row in rows:
        adherence_id, decision_id, _version_id, rule_node_id, self_status = row[:5]
        result = evaluate_predicate(conn, decision_id=decision_id, rule_node_id=rule_node_id)
        predicate_status = result.status
        alignment = _predicate_alignment(str(self_status), predicate_status)
        status_counts[predicate_status] += 1
        alignment_counts[alignment] = alignment_counts.get(alignment, 0) + 1

        item = {
            "adherence_row_id": adherence_id,
            "decision_id": decision_id,
            "rule_node_id": rule_node_id,
            "self_reported_status": self_status,
            "predicate_status": predicate_status,
            "predicate_family": result.family,
            "alignment": alignment,
            "record_refs": result.record_refs,
            "source_refs": result.source_refs,
            "caveats": result.caveats,
        }
        evaluations.append(item)
        if alignment.startswith("mismatch_"):
            mismatches.append(item)
        if predicate_status in {"not_computable", "ambiguous"}:
            missing_data.append(item)

    return {
        "metrics": {
            "predicate_status_counts": status_counts,
            "alignment_counts": alignment_counts,
            "mismatch_count": len(mismatches),
            "missing_or_unresolved_count": len(missing_data),
            "evaluated_adherence_rows": len(rows),
        },
        "evaluations": evaluations,
        "mismatches": mismatches,
        "missing_data": missing_data,
        "caveats": caveats,
    }


def report_playbook_adherence(
    conn: sqlite3.Connection,
    *,
    raw_filter: dict[str, Any] | None = None,
    playbook_id: str | None = None,
    strategy_id: str | None = None,
    min_sample: int = DEFAULT_ADHERENCE_MIN_SAMPLE,
) -> dict[str, Any]:
    """Compute the playbook-adherence panel.

    `raw_filter` accepts the standard ReportFilter shape but no
    ReportFilter leaves are joined into the underlying SQL today — any
    non-default value is rejected with VALIDATION_ERROR via
    `enforce_supported_filter` (bead trade-trace-d4k) so the result
    cannot silently broaden past the agent's intent. `playbook_id` and
    `strategy_id` are top-level scoping knobs (not part of
    ReportFilter) used by the playbook.adherence wrapper and are
    honored here.
    """

    rf = ReportFilter.model_validate(raw_filter or {})
    filter_dict = process_filter(rf, report="report.playbook_adherence")

    sql = (
        "SELECT dpr.id, dpr.decision_id, dpr.playbook_version_id, "
        "dpr.rule_node_id, dpr.status, d.strategy_id, d.created_at "
        "FROM decision_playbook_rules dpr "
        "JOIN decisions d ON d.id = dpr.decision_id "
        "JOIN playbook_versions pv ON pv.id = dpr.playbook_version_id "
        "WHERE 1=1"
    )
    params: list[Any] = []
    if playbook_id is not None:
        sql += " AND pv.playbook_id = ?"
        params.append(playbook_id)
    if strategy_id is not None:
        sql += " AND d.strategy_id = ?"
        params.append(strategy_id)
    sql += " ORDER BY dpr.playbook_version_id, d.created_at, dpr.id"
    rows = conn.execute(sql, tuple(params)).fetchall()

    by_version: dict[str, list[tuple]] = {}
    for row in rows:
        by_version.setdefault(row[2], []).append(row)

    groups: list[dict[str, Any]] = []
    for version_id, items in by_version.items():
        predicate_audit = _audit_predicates(conn, items)
        status_counts = {status: 0 for status in _STATUSES}
        for item in items:
            status_counts[item[4]] += 1
        decision_ids = sorted({item[1] for item in items})
        rule_node_ids = sorted({item[3] for item in items})
        adherence_ids = [item[0] for item in items]
        sample_size = len(decision_ids)
        sample_warning = (
            f"only {sample_size} decisions with adherence rows on "
            f"version {version_id!r}; unreliable below {min_sample}"
        ) if sample_size and sample_size < min_sample else None
        groups.append({
            "key": version_id,
            "label": f"Adherence on playbook_version {version_id!r}",
            "metrics": {
                "considered": status_counts["considered"],
                "followed": status_counts["followed"],
                "overridden": status_counts["overridden"],
                "not_applicable": status_counts["not_applicable"],
                "total_adherence_rows": len(items),
                "decision_count": sample_size,
                "predicate_audit": predicate_audit["metrics"],
            },
            "filter": filter_dict,
            "record_ids": {
                "decisions": decision_ids,
                "rule_nodes": rule_node_ids,
                "adherence_rows": adherence_ids,
                "playbook_version_id": [version_id],
            },
            "examples": [
                {"kind": "adherence", "id": item[0],
                 "summary": f"{item[4]} on decision {item[1]!r}"}
                for item in items[:3]
            ],
            "sample_size": sample_size,
            "sample_warning": sample_warning,
            "predicate_audit": predicate_audit,
            "truncated": False,
        })

    summary_counts = {status: 0 for status in _STATUSES}
    for row in rows:
        summary_counts[row[4]] += 1

    # Per bead trade-trace-9gs / DEBT-029: `summary.sample_size`
    # previously counted adherence rows (the same number reported as
    # `metrics.total_adherence_rows`), while every group's
    # `sample_size` counted distinct decisions. Same name with two
    # different meanings inside one envelope was a footgun. Summary
    # now counts distinct decisions to match the per-group field; the
    # raw row count stays available under
    # `metrics.total_adherence_rows`.
    all_decision_ids = {row[1] for row in rows}
    summary_predicate_audit = _audit_predicates(conn, rows)

    summary: dict[str, Any] = {
        "sample_size": len(all_decision_ids),
        "sample_warning": None,
        "filter": filter_dict,
        "metrics": {
            **summary_counts,
            "total_versions_with_rows": len(by_version),
            "total_adherence_rows": len(rows),
            "playbook_id_filter": playbook_id,
            "strategy_id_filter": strategy_id,
            "predicate_audit": summary_predicate_audit["metrics"],
        },
        "predicate_audit": summary_predicate_audit,
        "caveats": summary_predicate_audit["caveats"],
    }
    return standard_report_result(summary=summary, groups=groups)


__all__ = ["DEFAULT_ADHERENCE_MIN_SAMPLE", "report_playbook_adherence"]
