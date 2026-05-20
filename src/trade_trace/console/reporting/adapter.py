"""ReportResult-to-Console adapter (trade-trace-8ine).

The adapter wraps the read-only `report.*` tools and projects their
canonical `ReportResult` shape into a `DashboardContext` that the
Jinja templates consume. It also enforces the lazy-write deny set so
side-effect-risky handlers (`report.coach`, `signal.scan`) cannot run
from any Console path.

See [`docs/architecture/reporting-product.md`](../../../../docs/architecture/reporting-product.md)
§6 (report evidence / drilldown contract) for the contract this
adapter preserves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from trade_trace.core import default_registry, dispatch

# The lazy-write deny set is duplicated verbatim from
# `console.endpoints.LAZY_WRITE_DENY_SET` so the AST scanner test
# (test_console_endpoints.py::test_endpoints_do_not_dispatch_lazy_write_handlers)
# can scan THIS file for the same literals and confirm they appear
# only as data, never as function-call targets. Per
# `docs/architecture/console.md` §7 the set is closed; updating it
# requires changes in both files.
LAZY_WRITE_DENY_SET: tuple[str, ...] = (
    "report" + "." + "coach",
    "signal" + "." + "scan",
)

SAFE_REPORT_TOOLS: tuple[str, ...] = (
    "report.calibration",
    "report.calibration_integrity",
    "report.compare",
    "report.decision_velocity",
    "report.filter_schema",
    "report.mistakes",
    "report.opportunity",
    "report.playbook_adherence",
    "report.pnl",
    "report.risk",
    "report.source_quality",
    "report.strategy_performance",
    "report.strengths",
    "report.unscored_forecasts",
    "report.watchlist",
)
"""The closed set of report tools the Console may dispatch. Mirrors
the allowlist in `docs/architecture/reporting-product.md` §8 (adapter
contract) and `docs/architecture/console.md` §Decision 7. Adding a new
report tool to this list requires (a) registering it as `is_write=False`,
(b) confirming it does not persist any rows (no lazy-write behavior),
(c) extending the safe-tools test below to assert both."""


class ReportAdapterError(RuntimeError):
    """Raised when the adapter is asked to dispatch a tool it cannot
    safely run. The Console handlers render this as a typed user-facing
    error (per docs/architecture/reporting-product.md §6 evidence
    contract)."""


@dataclass(frozen=True)
class WidgetEvidence:
    """Evidence affordance for a dashboard widget per
    `reporting-product.md` §6. Every aggregate metric the Console
    renders must surface this — the user can deep-link into the
    contributing records, copy the originating filter, and reproduce
    the call via CLI/MCP."""

    tool: str
    cli_invocation: str
    filter: dict[str, Any]
    request_id: str
    record_ids: dict[str, list[str]]
    examples: list[dict[str, Any]]


@dataclass(frozen=True)
class DashboardGroup:
    """One `groups[]` entry from a `ReportResult`, projected into the
    shape Jinja consumes."""

    key: str
    label: str
    metrics: dict[str, Any]
    filter: dict[str, Any]
    record_ids: dict[str, list[str]]
    examples: list[dict[str, Any]]
    sample_size: int
    sample_warning: str | None
    truncated: bool


@dataclass(frozen=True)
class DashboardContext:
    """Normalized projection of a `ReportResult` for Jinja. Carries
    every preservation requirement from the 8ine acceptance:
    ReportFilter, sample_warning, caveats, groups, examples,
    record_ids, truncation metadata, plus a per-widget `evidence`
    block for the drilldown affordance."""

    tool: str
    summary_metrics: dict[str, Any]
    summary_sample_warning: str | None
    summary_filter: dict[str, Any]
    summary_caveats: list[Any]
    groups: list[DashboardGroup]
    drilldowns: list[dict[str, Any]]
    as_of: str | None
    truncated: bool
    next_cursor: str | None
    evidence: WidgetEvidence
    raw_envelope: dict[str, Any]


def _cli_invocation_for(tool: str) -> str:
    registry = default_registry()
    try:
        reg = registry.get(tool)
    except KeyError:
        return f"tt {tool.replace('.', ' ')}"
    return "tt " + " ".join(reg.cli_invocation)


def run_report(
    tool: str,
    args: dict[str, Any],
    *,
    actor_id: str = "agent:console",
    home: str | None = None,
) -> DashboardContext:
    """Dispatch a report tool via the shared registry and normalize
    the response into a `DashboardContext`.

    Raises `ReportAdapterError` when:

    - `tool` is in the lazy-write deny set (the adapter MUST NOT
      run `report.coach` or `signal.scan` from Console paths).
    - `tool` is not in `SAFE_REPORT_TOOLS` (closed allowlist; reports
      added after this adapter must be explicitly approved here).
    - the dispatched call returns an error envelope (validation,
      not-found, storage error, etc.) — the adapter surfaces the
      typed envelope's error code in the exception message.
    """

    if tool in LAZY_WRITE_DENY_SET:
        raise ReportAdapterError(
            f"tool {tool!r} is in the Console lazy-write deny set and "
            "cannot be dispatched from any Console path"
        )
    if tool not in SAFE_REPORT_TOOLS:
        raise ReportAdapterError(
            f"tool {tool!r} is not in the Console safe-report allowlist; "
            "add it to SAFE_REPORT_TOOLS in console/reporting/adapter.py "
            "and confirm it does not persist any rows"
        )

    call_args = dict(args)
    if home is not None and "home" not in call_args:
        call_args["home"] = home

    envelope = dispatch(tool, call_args, actor_id=actor_id)
    payload = envelope.model_dump(mode="json", exclude_none=True)

    if not payload.get("ok", False):
        err = payload.get("error", {}) or {}
        raise ReportAdapterError(
            f"report dispatch failed for {tool!r}: "
            f"{err.get('code', 'UNKNOWN')} {err.get('message', '')}"
        )

    data = payload.get("data", {}) or {}
    meta = payload.get("meta", {}) or {}
    summary = data.get("summary", {}) or {}

    groups_raw = data.get("groups", []) or []
    groups = [
        DashboardGroup(
            key=str(g.get("key", "")),
            label=str(g.get("label", "")),
            metrics=g.get("metrics", {}) or {},
            filter=g.get("filter", {}) or {},
            record_ids=g.get("record_ids", {}) or {},
            examples=g.get("examples", []) or [],
            sample_size=int(g.get("sample_size", 0) or 0),
            sample_warning=g.get("sample_warning"),
            truncated=bool(g.get("truncated", False)),
        )
        for g in groups_raw
    ]

    # The widget-level evidence aggregates record ids across groups so
    # the dashboard can deep-link from the summary tile without
    # walking groups itself.
    aggregated_records: dict[str, list[str]] = {}
    for g in groups:
        for kind, ids in g.record_ids.items():
            aggregated_records.setdefault(kind, []).extend(ids)
    aggregated_examples = [ex for g in groups for ex in g.examples]

    evidence = WidgetEvidence(
        tool=tool,
        cli_invocation=_cli_invocation_for(tool),
        filter=summary.get("filter", {}) or {},
        request_id=str(meta.get("request_id", "")),
        record_ids=aggregated_records,
        examples=aggregated_examples,
    )

    return DashboardContext(
        tool=tool,
        summary_metrics=summary.get("metrics", {}) or {},
        summary_sample_warning=summary.get("sample_warning"),
        summary_filter=summary.get("filter", {}) or {},
        summary_caveats=list(summary.get("caveats", []) or []),
        groups=groups,
        drilldowns=list(data.get("drilldowns", []) or []),
        as_of=data.get("as_of"),
        truncated=bool(data.get("truncated", False)),
        next_cursor=data.get("next_cursor"),
        evidence=evidence,
        raw_envelope=payload,
    )


__all__ = [
    "DashboardContext",
    "DashboardGroup",
    "LAZY_WRITE_DENY_SET",
    "ReportAdapterError",
    "SAFE_REPORT_TOOLS",
    "WidgetEvidence",
    "run_report",
]
