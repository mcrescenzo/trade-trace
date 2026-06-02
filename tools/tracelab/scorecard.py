"""TraceLab run scorecard assembler.

Builds a deterministic, local-only Markdown report from TraceLab sidecar JSON
artifacts. The scorecard is intentionally human-readable and preserves caveats
needed for final-gate review: substrate pass/fail checks, descriptive agent-skill
metrics, rail-adoption call counts, dispatch reconciliation, minimum-N outcome,
and known findings that are expected observations rather than product bugs.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_RUN_CONFIG = Path("docs/tracelab/run-config.json")
DEFAULT_MINIMUM_N = 20
B22_CITATION = "tests/integration/test_manual_ledger_flow.py::test_resolved_final_does_not_close_open_paper_position"


@dataclass(frozen=True)
class ScorecardInputs:
    substrate: dict[str, Any] | None = None
    metric_rollup: dict[str, Any] | None = None
    skill_metrics: dict[str, Any] | None = None
    reconcile: dict[str, Any] | None = None
    health: dict[str, Any] | None = None
    run_config: dict[str, Any] | None = None
    db_path: str | Path | None = None
    minimum_n: int | None = None
    resolved_but_unfed: int | None = None
    resolved_but_no_forecast: int | None = None
    input_paths: dict[str, str] | None = None


def _load_json(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    with Path(path).open("r", encoding="utf-8") as fh:
        value = json.load(fh)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def _first_int(*values: Any) -> int | None:
    for value in values:
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
    return None


def _metric_rollup_n(metric_rollup: dict[str, Any] | None) -> int | None:
    if not metric_rollup:
        return None
    reports = metric_rollup.get("reports") or {}
    calibration = reports.get("calibration") or metric_rollup.get("calibration") or {}
    summary = calibration.get("summary") or {}
    metrics = summary.get("metrics") or {}
    return _first_int(
        summary.get("resolved_auto_scored_forecasts"),
        summary.get("resolved_scored_forecasts"),
        summary.get("sample_size"),
        summary.get("n"),
        metrics.get("resolved_auto_scored_forecasts"),
        metrics.get("resolved_scored_forecasts"),
        metrics.get("sample_size"),
        metrics.get("n"),
    )


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def count_resolved_auto_scored_forecasts(db_path: str | Path) -> int:
    """Count distinct resolved forecasts with score rows from a read-only DB."""
    uri = f"{Path(db_path).resolve().as_uri()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        if not (_has_table(conn, "forecast_scores") and _has_table(conn, "forecasts")):
            return 0
        if _has_table(conn, "outcomes") and "outcome_id" in _column_names(conn, "forecast_scores"):
            return int(conn.execute(
                """
                SELECT COUNT(DISTINCT fs.forecast_id)
                FROM forecast_scores fs
                JOIN outcomes o ON o.id = fs.outcome_id
                WHERE o.status IN ('resolved_final','resolved_provisional')
                """
            ).fetchone()[0])
        return int(conn.execute("SELECT COUNT(DISTINCT forecast_id) FROM forecast_scores").fetchone()[0])


def _minimum_n(inputs: ScorecardInputs) -> int:
    if inputs.minimum_n is not None:
        return inputs.minimum_n
    cfg = inputs.run_config or {}
    scorecard = cfg.get("scorecard") or {}
    return int(scorecard.get("minimum_resolved_auto_scored_forecasts", DEFAULT_MINIMUM_N))


def _final_n(inputs: ScorecardInputs) -> tuple[int | None, str]:
    n = _metric_rollup_n(inputs.metric_rollup)
    if n is not None:
        return n, "metric_rollup.calibration"
    if inputs.db_path is not None:
        return count_resolved_auto_scored_forecasts(inputs.db_path), "read-only sqlite forecast_scores"
    return None, "unavailable"


def _line_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join("" if v is None else str(v) for v in row) + " |")
    return out


def _fmt_json(value: Any) -> str:
    if value in ({}, [], None):
        return ""
    return "`" + json.dumps(value, sort_keys=True) + "`"


def _substrate_section(report: dict[str, Any] | None) -> list[str]:
    lines = ["## Substrate invariants"]
    if not report:
        return lines + ["Substrate invariant artifact: **missing**."]
    lines.append(f"Overall status: **{report.get('overall_status', 'UNKNOWN')}**. Throughput scored here: `{report.get('throughput_scored')}`.")
    rows = []
    for inv in report.get("invariants") or []:
        rows.append([inv.get("name"), f"**{inv.get('status')}**", inv.get("reason"), _fmt_json(inv.get("evidence"))])
    return lines + _line_table(["Invariant", "Status", "Reason", "Evidence"], rows)


def _skill_section(report: dict[str, Any] | None) -> list[str]:
    lines = ["## Agent skill metrics"]
    if not report:
        return lines + ["Agent-skill metric artifact: **missing**."]
    rows = []
    for actor, metrics in sorted((report.get("skill_metrics") or {}).items()):
        for name, values in sorted((metrics or {}).items()):
            rows.append([actor, name, _fmt_json(values)])
    return lines + _line_table(["Actor", "Metric", "Values"], rows)


def _rail_section(report: dict[str, Any] | None) -> list[str]:
    lines = ["## Rail adoption"]
    if not report:
        return lines + ["Rail-adoption artifact: **missing**."]
    read = report.get("read_rail_adoption") or {}
    write = report.get("write_rail_adoption") or {}
    lines.append(f"Read rail caveat: {read.get('caveat', '')}")
    rows = [["read", "totals", _fmt_json(read.get("totals"))], ["write", "totals", _fmt_json(write.get("totals"))]]
    for actor, counts in sorted((read.get("per_actor") or {}).items()):
        rows.append(["read", actor, _fmt_json(counts)])
    for actor, counts in sorted((write.get("per_actor") or {}).items()):
        rows.append(["write", actor, _fmt_json(counts)])
    return lines + _line_table(["Rail", "Actor/scope", "Call counts / adoption"], rows)


def _reconcile_section(report: dict[str, Any] | None) -> list[str]:
    lines = ["## Dispatch reconciliation"]
    if not report:
        return lines + ["Dispatch reconciliation artifact: **missing**."]
    return lines + [f"Trace records: **{report.get('trace_count', 'UNKNOWN')}**."] + _line_table(["Bucket", "Count"], [[k, v] for k, v in (report.get("buckets") or {}).items()])


def _health_lag_counts(inputs: ScorecardInputs) -> tuple[int | None, int | None]:
    health = inputs.health or {}
    counts = health.get("counts") or {}
    unfed = inputs.resolved_but_unfed if inputs.resolved_but_unfed is not None else _first_int(counts.get("resolved_but_unfed"), counts.get("resolved_but_unclosed_forecasts"))
    no_forecast = inputs.resolved_but_no_forecast if inputs.resolved_but_no_forecast is not None else _first_int(counts.get("resolved_but_no_forecast"))
    return unfed, no_forecast


def _findings(inputs: ScorecardInputs, n: int | None, min_n: int) -> list[str]:
    lines = ["## FINDINGS"]
    lines.append(f"- **paper_exit / resolution-does-not-close-position**: expected finding, not a bug. B22 evidence `{B22_CITATION}` proves a `resolved_final` resolution leaves a `paper_enter` position `status='open'` and `resolved_at NULL`; position closure requires explicit close evidence, not merely resolution/today arrival.")
    if n is None:
        lines.append(f"- **Minimum-N outcome**: final N unavailable; extend/abort decision cannot be made. Required threshold is N>={min_n}.")
    elif n >= min_n:
        lines.append(f"- **Minimum-N outcome**: final N={n}; N>={min_n} met.")
    else:
        lines.append(f"- **Minimum-N outcome**: final N={n}; N>={min_n} not met, so extend/abort rule fired per TraceLab run config/charter.")
    unfed, no_forecast = _health_lag_counts(inputs)
    lines.append(f"- **Resolved-but-unfed lag**: {unfed if unfed is not None else 'not provided'}.")
    lines.append(f"- **Resolved-but-no-forecast lag**: {no_forecast if no_forecast is not None else 'not provided'}.")
    canary = (inputs.health or {}).get("canary")
    alarms = (inputs.health or {}).get("alarms") or []
    gamma_alarm = [a for a in alarms if str(a.get("code")) == "GAMMA_SCHEMA_CANARY"]
    if canary is None and not gamma_alarm:
        gamma = "not provided"
    elif gamma_alarm or (isinstance(canary, dict) and canary.get("ok") is False):
        gamma = f"schema drift/alarm observed: {_fmt_json(canary or gamma_alarm)}"
    else:
        gamma = f"ok: {_fmt_json(canary)}"
    lines.append(f"- **Gamma schema drift status**: {gamma}.")
    buckets = (inputs.reconcile or {}).get("buckets") or {}
    val_count = buckets.get("expected_validation_error_pattern", 0)
    lines.append(f"- **Secret-scanner VALIDATION_ERROR handling**: expected events, not scorecard failures; reconciler bucket `expected_validation_error_pattern` count={val_count}.")
    return lines


def build_scorecard(inputs: ScorecardInputs) -> str:
    min_n = _minimum_n(inputs)
    n, n_source = _final_n(inputs)
    n_status = "UNKNOWN" if n is None else ("PASS" if n >= min_n else "EXTEND_OR_ABORT")
    lines = [
        "# TraceLab run scorecard",
        "",
        "## Summary",
        f"- Substrate status: **{(inputs.substrate or {}).get('overall_status', 'MISSING')}**",
        f"- Final N (resolved auto-scored forecasts): **{n if n is not None else 'UNKNOWN'}** (source: {n_source})",
        f"- Minimum-N threshold: **N>={min_n}**; outcome: **{n_status}**",
        "- Result classes rendered: substrate invariants pass/fail; agent-skill descriptive metrics; rail-adoption call-counts.",
        "",
    ]
    for section in (_substrate_section(inputs.substrate), _skill_section(inputs.skill_metrics), _rail_section(inputs.skill_metrics), _reconcile_section(inputs.reconcile), _findings(inputs, n, min_n)):
        lines.extend(section)
        lines.append("")
    lines.append("## Caveats / inputs")
    cfg_statement = (((inputs.run_config or {}).get("scorecard") or {}).get("late_recorded_policy") or {}).get("statement")
    if cfg_statement:
        lines.append(f"- Late-recorded policy: {cfg_statement}")
    replay_caveat = ((inputs.run_config or {}).get("replay_caveat") or {}).get("statement")
    if replay_caveat:
        lines.append(f"- Replay caveat: {replay_caveat}")
    if inputs.input_paths:
        for key, value in sorted(inputs.input_paths.items()):
            lines.append(f"- {key}: `{value}`")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble a TraceLab Markdown run scorecard.")
    parser.add_argument("--substrate-json")
    parser.add_argument("--metric-rollup-json")
    parser.add_argument("--skill-metrics-json")
    parser.add_argument("--reconcile-json")
    parser.add_argument("--health-json")
    parser.add_argument("--run-config-json", default=str(DEFAULT_RUN_CONFIG))
    parser.add_argument("--db")
    parser.add_argument("--minimum-n", type=int)
    parser.add_argument("--resolved-but-unfed", type=int)
    parser.add_argument("--resolved-but-no-forecast", type=int)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    paths = {k: v for k, v in {
        "substrate_json": args.substrate_json,
        "metric_rollup_json": args.metric_rollup_json,
        "skill_metrics_json": args.skill_metrics_json,
        "reconcile_json": args.reconcile_json,
        "health_json": args.health_json,
        "run_config_json": args.run_config_json,
        "db": args.db,
    }.items() if v}
    run_config = _load_json(args.run_config_json) if args.run_config_json and Path(args.run_config_json).exists() else None
    markdown = build_scorecard(ScorecardInputs(
        substrate=_load_json(args.substrate_json),
        metric_rollup=_load_json(args.metric_rollup_json),
        skill_metrics=_load_json(args.skill_metrics_json),
        reconcile=_load_json(args.reconcile_json),
        health=_load_json(args.health_json),
        run_config=run_config,
        db_path=args.db,
        minimum_n=args.minimum_n,
        resolved_but_unfed=args.resolved_but_unfed,
        resolved_but_no_forecast=args.resolved_but_no_forecast,
        input_paths=paths,
    ))
    if args.output:
        Path(args.output).write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
