"""TraceLab metric-rollup sidecar.

Builds a deterministic JSON-serializable rollup from public report surfaces.
The sidecar intentionally dispatches every report through the public MCP-style
call function so B1 dispatch trace captures the same reads a live agent would
perform.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tools.tracelab.run_config import include_late_recorded_default
from trade_trace.mcp_server import mcp_call

ACTOR_ID = "system:tracelab.metric_rollup"
REPORTS = (
    "report.calibration",
    "report.pnl",
    "report.coach",
    "report.recall_receipts",
)

CallFn = Callable[..., Any]


def _dump_envelope(envelope: Any) -> dict[str, Any]:
    if hasattr(envelope, "model_dump"):
        return envelope.model_dump(mode="json", exclude_none=True)
    if isinstance(envelope, dict):
        return envelope
    raise TypeError(f"unsupported call envelope type: {type(envelope)!r}")


def _call_report(call: CallFn, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    envelope = _dump_envelope(call(tool, args, actor_id=ACTOR_ID))
    if envelope.get("ok") is not True:
        raise RuntimeError(f"{tool} failed: {envelope.get('error')}")
    return envelope.get("data") or {}


def _filter_for_late_policy(include_late_recorded: bool) -> dict[str, Any]:
    return {"outcome": {"include_late_recorded": include_late_recorded}}


def _late_excluded_count(calibration: dict[str, Any]) -> int | None:
    summary = calibration.get("summary") or {}
    metrics = summary.get("metrics") or {}
    for value in (summary.get("late_recorded_excluded"), metrics.get("late_recorded_excluded")):
        if isinstance(value, int):
            return value
    return None


def _pnl_annotation(pnl: dict[str, Any]) -> dict[str, Any]:
    metrics = ((pnl.get("summary") or {}).get("metrics") or {})
    closed_count = metrics.get("closed_position_count")
    open_count = metrics.get("open_position_count")
    expected = closed_count == 0
    return {
        "zero_close_interpretation": "expected-given-resolution-only-close" if expected else "closed-positions-present",
        "reason": (
            "TraceLab positions close only from resolution evidence; open positions never close merely because 'today' arrives. "
            "A zero closed-position count is therefore expected, not a substrate bug."
        ),
        "closed_position_count": closed_count,
        "open_position_count": open_count,
    }


def build_metric_rollup(
    home: str | Path,
    *,
    include_late_recorded: bool | None = None,
    call: CallFn = mcp_call,
) -> dict[str, Any]:
    """Return a JSON-serializable TraceLab report rollup.

    If ``include_late_recorded`` is omitted, the decided TraceLab run-config
    default is consumed. The policy is passed through to reports that accept a
    ReportFilter. Recall evidence is read via ``report.recall_receipts`` only.
    """

    decided_include_late = (
        include_late_recorded if include_late_recorded is not None else include_late_recorded_default()
    )
    home_s = str(home)
    report_filter = _filter_for_late_policy(decided_include_late)

    calibration = _call_report(
        call,
        "report.calibration",
        {"home": home_s, "filter": report_filter},
    )
    pnl = _call_report(call, "report.pnl", {"home": home_s, "filter": report_filter})
    coach = _call_report(call, "report.coach", {"home": home_s, "filter": report_filter})
    recall_receipts = _call_report(call, "report.recall_receipts", {"home": home_s})
    calibration_integrity = calibration.get("integrity_diagnostics") or {}

    late_excluded = _late_excluded_count(calibration) if not decided_include_late else 0

    return {
        "schema": "trade-trace.tracelab.metric-rollup.v1",
        "home": home_s,
        "actor_id": ACTOR_ID,
        "late_recorded_policy": {
            "include_late_recorded": decided_include_late,
            "source": "argument" if include_late_recorded is not None else "docs/tracelab/run-config.json",
            "excluded_late_scored_forecasts": late_excluded,
        },
        "reports": {
            "calibration": calibration,
            "calibration_integrity": calibration_integrity,
            "pnl": pnl,
            "coach": coach,
            "recall_receipts": recall_receipts,
        },
        "pnl_annotation": _pnl_annotation(pnl),
        "recall_evidence_source": "report.recall_receipts",
        "dispatch_contract": {
            "distinct_public_report_calls": list(REPORTS),
            "forbidden_writer_calls": ["memory.recall"],
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build TraceLab metric rollup from public reports.")
    parser.add_argument("--home", required=True, help="TRADE_TRACE_HOME to read")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--include-late-recorded", action="store_true", help="Include late-recorded scored forecasts")
    group.add_argument("--exclude-late-recorded", action="store_true", help="Exclude late-recorded scored forecasts")
    args = parser.parse_args(argv)
    include = None
    if args.include_late_recorded:
        include = True
    elif args.exclude_late_recorded:
        include = False
    print(json.dumps(build_metric_rollup(args.home, include_late_recorded=include), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
