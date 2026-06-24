"""Decision-tag MVP for `report.process_analytics`.

The v1 implementation is intentionally decision_tags-only. Review tags,
review-derived dimensions, reviews-aware analytics, and cost-family metrics
are represented as unsupported/insufficient metadata rather than fabricated.
"""

from __future__ import annotations

import base64
import copy
import itertools
import sqlite3
from collections import defaultdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.reports._envelope import standard_report_result
from trade_trace.reports._filter_support import SUPPORTED_FILTER_FIELDS, process_filter

REPORT = "report.process_analytics"
DEFAULT_MIN_SAMPLE = 10
DEFAULT_MAX_GROUPS = 100
DEFAULT_MAX_RECORD_IDS_PER_GROUP = 1000
SUPPORTED_DIMENSIONS = {"tag_frequency", "tag_pair_cooccurrence"}
SUPPORTED_GROUP_BY = {"tag_frequency", "tag_pair_cooccurrence"}
SUPPORTED_METRICS = {"decision_count", "review_count", "tag_count", "pair_count", "support", "jaccard"}
SUPPORTED_FEATURES = {"coverage", "examples", "contributing_ids"}
_COST_METRICS = {"local_pnl_projection", "r_multiple", "fees_slippage", "opportunity_path_diagnostics"}


class ProcessAnalyticsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filter: dict[str, Any] | None = None
    dimensions: list[str] = Field(default_factory=lambda: ["tag_frequency", "tag_pair_cooccurrence"])
    group_by: list[str] = Field(default_factory=lambda: ["tag_frequency"])
    metrics: list[str] = Field(default_factory=lambda: ["decision_count", "tag_count", "support"])
    features: list[str] = Field(default_factory=lambda: ["coverage", "examples", "contributing_ids"])
    include_costs: bool = False
    min_sample: int = Field(default=DEFAULT_MIN_SAMPLE, ge=1)
    max_groups: int = Field(default=DEFAULT_MAX_GROUPS, ge=1)
    max_record_ids_per_group: int = Field(default=DEFAULT_MAX_RECORD_IDS_PER_GROUP, ge=1)
    cursor: str | None = None
    as_of: str | None = None


def report_process_analytics(conn: sqlite3.Connection, *, request: dict[str, Any] | None = None) -> dict[str, Any]:
    req = ProcessAnalyticsRequest.model_validate(request or {})
    rf = ReportFilter.model_validate(req.filter or {})
    applied_filter = process_filter(rf, report=REPORT)
    requested_filter = rf.model_dump()
    rows = _decision_tag_rows(conn, rf)
    by_decision: dict[str, dict[str, Any]] = {}
    for row in rows:
        did = row["decision_id"]
        item = by_decision.setdefault(did, {"id": did, "type": row["decision_type"], "tags": []})
        item["tags"].append(row["tag"])
    decisions = []
    for item in by_decision.values():
        tags = sorted(set(item["tags"]))
        if tags:
            item["tags"] = tags
            decisions.append(item)
    decisions.sort(key=lambda d: d["id"])
    eligible_count = len(decisions)

    unsupported_features = _unsupported_request_metadata(req)
    group_by = [g for g in req.group_by if g in SUPPORTED_GROUP_BY] or ["tag_frequency"]
    primary_grouping = group_by[0]
    all_groups = (
        _tag_frequency_groups(decisions, eligible_count, req)
        if primary_grouping == "tag_frequency"
        else _tag_pair_groups(decisions, eligible_count, req)
    )
    start_index = _cursor_start_index(all_groups, req.cursor, primary_grouping)
    groups = all_groups[start_index: start_index + req.max_groups]
    truncated = start_index + req.max_groups < len(all_groups)
    next_cursor = (
        _encode_group_cursor(primary_grouping, groups[-1]["key"])
        if truncated and groups
        else None
    )

    caveat_codes = ["LOCAL_ROWS_ONLY", "DIAGNOSTIC_ONLY_NO_CAUSAL_CLAIM"]
    if eligible_count < req.min_sample:
        caveat_codes.append("LOW_SAMPLE_SIZE")
    if unsupported_features:
        caveat_codes.append("PARTIAL_COVERAGE")
    sample_warning = None
    if eligible_count < req.min_sample:
        sample_warning = f"only {eligible_count} eligible decisions; process analytics is unreliable below min_sample={req.min_sample}"
    elif unsupported_features:
        sample_warning = "some requested metrics/features are unsupported by decision_tags-only v1"

    extra = {
        "contract_version": "1.0",
        "requested_scope": {
            "filter": requested_filter,
            "dimensions": req.dimensions,
            "group_by": req.group_by,
            "metrics": req.metrics,
            "features": req.features,
            "include_costs": req.include_costs,
            "min_sample": req.min_sample,
            "max_groups": req.max_groups,
            "max_record_ids_per_group": req.max_record_ids_per_group,
            "cursor": req.cursor,
            "as_of": req.as_of,
        },
        "applied_scope": {
            "filter": applied_filter,
            "dimensions": [d for d in req.dimensions if d in SUPPORTED_DIMENSIONS],
            "group_by": group_by[:1],
            "metrics": [m for m in req.metrics if m in SUPPORTED_METRICS and (primary_grouping != "tag_frequency" or m != "pair_count")],
            "include_costs": False,
            "as_of": None,
        },
        "supported_filter_paths": sorted(SUPPORTED_FILTER_FIELDS[REPORT]),
        "unsupported_filter_paths": [],
        "supported_features": sorted(SUPPORTED_DIMENSIONS | SUPPORTED_FEATURES),
        "unsupported_features": unsupported_features,
        "insufficient_data": _insufficient_data(req, eligible_count),
        "metric_definitions": _metric_definitions(),
        "coverage": _coverage(eligible_count, eligible_count, "decisions"),
        "caveat_codes": caveat_codes,
        "sample_warning": sample_warning,
    }
    summary = {
        "sample_size": eligible_count,
        "sample_warning": sample_warning,
        "filter": applied_filter,
        "metrics": {"eligible_decision_count": eligible_count, "grouping": primary_grouping},
    }
    return standard_report_result(summary=summary, groups=groups, truncated=truncated, next_cursor=next_cursor, extra=extra)


def _decision_tag_rows(conn: sqlite3.Connection, rf: ReportFilter) -> list[sqlite3.Row]:
    previous_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    where: list[str] = []
    params: list[Any] = []
    if rf.time_window.decision_at_gte:
        where.append("d.created_at >= ?")
        params.append(rf.time_window.decision_at_gte)
    if rf.time_window.decision_at_lt:
        where.append("d.created_at < ?")
        params.append(rf.time_window.decision_at_lt)
    if rf.strategy.strategy_id:
        if rf.strategy.strategy_id == "__none__":
            where.append("d.strategy_id IS NULL")
        else:
            where.append("d.strategy_id = ?")
            params.append(rf.strategy.strategy_id)
    if rf.decision.tags_any:
        placeholders = ",".join("?" for _ in rf.decision.tags_any)
        where.append(f"EXISTS (SELECT 1 FROM decision_tags x WHERE x.decision_id=d.id AND x.tag IN ({placeholders}))")
        params.extend(rf.decision.tags_any)
    for tag in rf.decision.tags_all:
        where.append("EXISTS (SELECT 1 FROM decision_tags y WHERE y.decision_id=d.id AND y.tag = ?)")
        params.append(tag)
    sql = """
        SELECT d.id AS decision_id, d.type AS decision_type, dt.tag AS tag
        FROM decisions d JOIN decision_tags dt ON dt.decision_id = d.id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY d.id ASC, dt.tag ASC"
    try:
        return list(conn.execute(sql, params).fetchall())
    finally:
        conn.row_factory = previous_row_factory


def _cursor_start_index(groups: list[dict[str, Any]], cursor: str | None, grouping: str) -> int:
    if not cursor:
        return 0
    after_key = _decode_group_cursor(grouping, cursor)
    if after_key is None:
        return 0
    for index, group in enumerate(groups):
        if group["key"] == after_key:
            return index + 1
    return 0


def _encode_group_cursor(grouping: str, key: str) -> str:
    raw = f"{grouping}\n{key}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_group_cursor(grouping: str, cursor: str) -> str | None:
    try:
        padding = "=" * ((4 - len(cursor) % 4) % 4)
        raw = base64.urlsafe_b64decode(cursor + padding).decode("utf-8")
        cursor_grouping, key = raw.split("\n", 1)
    except (ValueError, UnicodeDecodeError):
        return None
    if cursor_grouping != grouping:
        return None
    return key


def _merge_group_filter(base_filter: dict[str, Any] | None, group_filter: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base_filter or {})
    for section, values in group_filter.items():
        target = merged.setdefault(section, {})
        for key, value in values.items():
            if isinstance(value, list) and isinstance(target.get(key), list):
                target[key] = list(dict.fromkeys([*target[key], *value]))
            else:
                target[key] = copy.deepcopy(value)
    return merged


def _tag_frequency_groups(decisions: list[dict[str, Any]], eligible_count: int, req: ProcessAnalyticsRequest) -> list[dict[str, Any]]:
    ids_by_tag: dict[str, list[str]] = defaultdict(list)
    for d in decisions:
        for tag in d["tags"]:
            ids_by_tag[tag].append(d["id"])
    groups = []
    for tag, ids in ids_by_tag.items():
        ids = sorted(set(ids))
        metrics = {"decision_count": len(ids), "review_count": 0, "tag_count": len(ids), "pair_count": None, "support": _ratio(len(ids), eligible_count), "jaccard": None}
        groups.append(_group(tag, f"Decisions tagged {tag!r}", {"tag": tag}, metrics, _merge_group_filter(req.filter, {"decision": {"tags_all": [tag]}}), ids, eligible_count, req))
    groups.sort(key=lambda g: (-g["metrics"]["tag_count"], g["key"]))
    return groups


def _tag_pair_groups(decisions: list[dict[str, Any]], eligible_count: int, req: ProcessAnalyticsRequest) -> list[dict[str, Any]]:
    ids_by_pair: dict[tuple[str, str], list[str]] = defaultdict(list)
    ids_by_tag = defaultdict(set)
    for d in decisions:
        for tag in d["tags"]:
            ids_by_tag[tag].add(d["id"])
        for a, b in itertools.combinations(d["tags"], 2):
            ids_by_pair[(a, b)].append(d["id"])
    groups = []
    for (a, b), ids in ids_by_pair.items():
        ids = sorted(set(ids))
        union_count = len(ids_by_tag[a] | ids_by_tag[b])
        metrics = {"decision_count": len(ids), "review_count": 0, "tag_count": None, "pair_count": len(ids), "support": _ratio(len(ids), eligible_count), "jaccard": _ratio(len(ids), union_count)}
        groups.append(_group(f"{a}|{b}", f"Tag pair {a} + {b}", {"tag_a": a, "tag_b": b}, metrics, _merge_group_filter(req.filter, {"decision": {"tags_all": [a, b]}}), ids, eligible_count, req))
    groups.sort(key=lambda g: (-g["metrics"]["pair_count"], g["key"]))
    return groups


def _group(key: str, label: str, dimensions: dict[str, str], metrics: dict[str, Any], filter_: dict[str, Any], ids: list[str], eligible_count: int, req: ProcessAnalyticsRequest) -> dict[str, Any]:
    truncated = len(ids) > req.max_record_ids_per_group
    sample_warning = None
    caveats = ["LOCAL_ROWS_ONLY", "DIAGNOSTIC_ONLY_NO_CAUSAL_CLAIM"]
    if len(ids) < req.min_sample:
        caveats.append("LOW_SAMPLE_SIZE")
        sample_warning = f"only {len(ids)} records; process analytics is unreliable below min_sample={req.min_sample}"
    return {"key": key, "label": label, "dimensions": dimensions, "metrics": metrics, "filter": filter_, "coverage": _coverage(eligible_count, len(ids), "decisions"), "record_ids": {"decisions": ids[: req.max_record_ids_per_group], "reviews": [], "forecasts": [], "outcomes": [], "sources": []}, "examples": [{"kind": "decision", "id": did, "summary": f"decision tag group {key}"} for did in ids[:3]], "sample_size": len(ids), "sample_warning": sample_warning, "caveat_codes": caveats, "unsupported_features": [], "truncated": truncated}


def _unsupported_request_metadata(req: ProcessAnalyticsRequest) -> list[dict[str, Any]]:
    out = []
    for dim in req.dimensions:
        if dim not in SUPPORTED_DIMENSIONS:
            reason = "review_tags_storage_not_available" if dim == "review_classification" else "dimension_not_supported_by_decision_tags_v1"
            out.append({"unsupported_feature": f"dimension.{dim}", "path": f"dimensions.{dim}", "reason_code": reason, "message": f"{dim} is unsupported by decision_tags-only process_analytics v1", "requested_value": dim, "applied": False})
    for group in req.group_by:
        if group not in SUPPORTED_GROUP_BY:
            out.append({"unsupported_feature": f"group_by.{group}", "path": f"group_by.{group}", "reason_code": "grouping_not_supported_by_decision_tags_v1", "requested_value": group, "applied": False})
    seen_cost_metrics: set[str] = set()
    for metric in req.metrics:
        if metric in _COST_METRICS:
            seen_cost_metrics.add(metric)
            out.append({"unsupported_feature": f"cost_family.{metric}", "path": f"metrics.{metric}", "reason_code": "cost_read_model_not_available", "message": "cost-family metrics are unavailable in decision_tags-only v1", "requested_value": metric, "applied": False})
        elif metric not in SUPPORTED_METRICS:
            out.append({"unsupported_feature": f"metric.{metric}", "path": f"metrics.{metric}", "reason_code": "metric_not_supported_by_decision_tags_v1", "requested_value": metric, "applied": False})
    if req.include_costs:
        for metric in sorted(_COST_METRICS - seen_cost_metrics):
            out.append({"unsupported_feature": f"cost_family.{metric}", "path": f"metrics.{metric}", "reason_code": "cost_read_model_not_available", "message": "cost-family metrics are unavailable in decision_tags-only v1", "requested_value": metric, "applied": False})
    for feature in req.features:
        if feature == "cost_family" or feature not in SUPPORTED_FEATURES:
            out.append({"unsupported_feature": feature, "path": f"features.{feature}", "reason_code": "cost_read_model_not_available" if feature == "cost_family" else "feature_not_supported_by_decision_tags_v1", "requested_value": feature, "applied": False})
    if req.as_of is not None:
        out.append({"unsupported_feature": "as_of", "path": "as_of", "reason_code": "as_of_not_required_for_append_only_decision_tags_v1", "requested_value": req.as_of, "applied": False})
    return out


def _insufficient_data(req: ProcessAnalyticsRequest, eligible_count: int) -> list[dict[str, Any]]:
    return [] if eligible_count >= req.min_sample else [{"path": "summary.sample_size", "reason_code": "low_sample_size", "minimum": req.min_sample, "actual": eligible_count, "applied": True}]


def _coverage(eligible: int, included: int, denominator_kind: str) -> dict[str, Any]:
    return {"eligible_count": eligible, "included_count": included, "missing_count": 0, "coverage_pct": round((included / eligible * 100.0), 1) if eligible else 100.0, "denominator_kind": denominator_kind}


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 6) if den else None


def _metric_definitions() -> dict[str, str]:
    return {"decision_count": "count of distinct decisions in the applied group", "review_count": "always 0 in decision_tags-only v1; review analytics unsupported", "tag_count": "count of decision tag occurrences contributing to a tag-frequency group", "pair_count": "count of eligible decisions containing both normalized tags", "support": "group count divided by eligible decision denominator", "jaccard": "pair_count divided by decisions containing either tag in the eligible denominator"}
