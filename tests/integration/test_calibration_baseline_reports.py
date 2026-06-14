"""Functional coverage for `report.calibration_anchored` and
`report.calibration_terminal` (bead trade-trace-rttu).

Before this file these two market-baseline reports appeared only as
registration-only string checks in
`tests/security/test_mvp_boundary_audit.py`. No test seeded a
`forecast_snapshot_anchor` row, exercised the `unanchored_forecast_count`
caveat path (`calibration.py:373-375`), or distinguished the anchored vs
terminal branch in `_load_market_baseline_rows` (`calibration.py:388-424`).

Each scenario drives the public MCP surface end-to-end:
`market.bind` -> `snapshot.add` -> `forecast.add` -> `outcome.add` (which
auto-scores the resolved forecast), then reads the report. `market.bind`
returns an id that doubles as both `market_id` and `instrument_id`, so:

- anchoring a forecast to the latest snapshot writes the
  `forecast_snapshot_anchor.market_implied_probability` the anchored report
  reads, and
- `snapshots.instrument_id == forecasts.market_id`, so the terminal-mode
  join (`snapshots s ON s.instrument_id = f.market_id`) resolves.
"""

from __future__ import annotations

import sqlite3
from itertools import count
from pathlib import Path

import pytest

from tests._mcp_helpers import envelope_default as _envelope
from trade_trace.contracts.report_filter import ReportFilter
from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.reports.calibration import _load_market_baseline_rows
from trade_trace.storage.paths import db_path


class _QueryTrace:
    """Capture every SQL statement a connection executes via the sqlite trace
    callback so a test can assert the per-row N+1 pattern is absent on the
    market-baseline load path (trade-trace-wjip)."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, sql: str) -> None:
        self.statements.append(" ".join(sql.split()))

    def count_substr(self, needle: str) -> int:
        return sum(1 for s in self.statements if needle in s)


@pytest.fixture
def home(tmp_path) -> Path:
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)}).model_dump(mode="json")
    assert env["ok"] is True
    return h


def _bind_market(home: Path, *, suffix: str) -> str:
    """Bind a manual prediction market; return its id (== instrument_id)."""

    env = _envelope(home, "market.bind", {
        "source": "polymarket",
        "external_id": f"baseline-report-{suffix}",
        "title": f"Baseline market {suffix}",
        "question": f"Will baseline market {suffix} resolve YES?",
        "state": "open",
        "mechanism": "clob",
        "bound_via": "manual",
        "idempotency_key": f"test:baseline-bind-{suffix}",
    })
    assert env["ok"] is True, env
    return env["data"]["id"]


def _add_snapshot(
    home: Path, *, market_id: str, captured_at: str, implied_probability: float,
    suffix: str,
) -> str:
    env = _envelope(home, "snapshot.add", {
        "instrument_id": market_id,
        "captured_at": captured_at,
        "implied_probability": implied_probability,
        "idempotency_key": f"test:baseline-snap-{suffix}",
    })
    assert env["ok"] is True, env
    return env["data"]["id"]


def _add_binary_forecast(
    home: Path, *, market_id: str, p_yes: float, suffix: str,
    anchor_to_latest_snapshot: bool = False,
) -> str:
    args = {
        "market_id": market_id,
        "kind": "binary",
        "yes_label": "yes",
        "side": "yes",
        "rationale_body": "baseline-report seed forecast",
        "outcomes": [
            {"outcome_label": "yes", "probability": p_yes},
            {"outcome_label": "no", "probability": 1.0 - p_yes},
        ],
        "idempotency_key": f"test:baseline-forecast-{suffix}",
    }
    if anchor_to_latest_snapshot:
        args["_anchor_to_latest_snapshot"] = True
    env = _envelope(home, "forecast.add", args)
    assert env["ok"] is True, env
    return env["data"]["id"]


def _resolve(
    home: Path, *, market_id: str, resolved_label: str, resolved_at: str,
    suffix: str,
) -> None:
    """Append a resolved_final outcome; the auto-scorer scores the forecast."""

    env = _envelope(home, "outcome.add", {
        "instrument_id": market_id,
        "resolved_at": resolved_at,
        "outcome_label": resolved_label,
        "status": "resolved_final",
        "confidence": 0.99,
        "idempotency_key": f"test:baseline-outcome-{suffix}",
    })
    assert env["ok"] is True, env


# -- registration ---------------------------------------------------------


def test_baseline_reports_registered():
    names = default_registry().names()
    assert "report.calibration_anchored" in names
    assert "report.calibration_terminal" in names


# -- (a) empty-DB smoke ---------------------------------------------------


@pytest.mark.parametrize(
    "tool, mode",
    [
        ("report.calibration_anchored", "anchored"),
        ("report.calibration_terminal", "terminal"),
    ],
)
def test_empty_db_smoke(home, tool, mode):
    """Empty DB: ok=True, sample_size=0, sample_warning set, empty metrics,
    and unanchored=0 (no scored rows to drop)."""

    env = _envelope(home, tool, {})
    assert env["ok"] is True
    data = env["data"]
    summary = data["summary"]
    assert summary["sample_size"] == 0
    assert summary["sample_warning"] is not None
    assert "20" in summary["sample_warning"]
    assert summary["unanchored_forecast_count"] == 0
    assert summary["metrics"]["brier"] is None
    assert summary["metrics"]["sample_size"] == 0
    assert data["baseline_mode"] == mode


# -- (b) anchored report with a valid anchor row --------------------------


def test_anchored_with_anchor_row_returns_sample_and_brier(home):
    """A scored forecast carrying a forecast_snapshot_anchor row contributes
    one row to the anchored report with the reference Brier (p=0.6, y=1 ->
    0.16) and the anchor's market probability as the baseline."""

    market_id = _bind_market(home, suffix="anchored-b")
    _add_snapshot(
        home, market_id=market_id, captured_at="2026-06-10T00:00:00Z",
        implied_probability=0.55, suffix="anchored-b",
    )
    fid = _add_binary_forecast(
        home, market_id=market_id, p_yes=0.6, suffix="anchored-b",
        anchor_to_latest_snapshot=True,
    )
    _resolve(
        home, market_id=market_id, resolved_label="yes",
        resolved_at="2026-06-30T00:00:00Z", suffix="anchored-b",
    )

    env = _envelope(home, "report.calibration_anchored", {"min_sample": 1})
    assert env["ok"] is True
    summary = env["data"]["summary"]
    assert summary["sample_size"] == 1
    assert summary["unanchored_forecast_count"] == 0
    assert summary["caveats"] == []
    assert summary["sample_warning"] is None
    metrics = summary["metrics"]
    assert metrics["brier"] == pytest.approx(0.16)
    # The anchored market-implied probability (0.55) is the baseline.
    assert metrics["baseline"] == pytest.approx(0.55)
    # Drill-down enumerates the contributing forecast.
    assert fid in env["data"]["groups"][0]["record_ids"]["forecasts"]


# -- (c) same forecast WITHOUT an anchor row -> unanchored ---------------


def test_anchored_without_anchor_row_is_unanchored(home):
    """A scored forecast with no forecast_snapshot_anchor row drops out of the
    sample and surfaces as unanchored_forecast_count=1 with a caveat
    (exercises calibration.py:373-375 and the missing branch at 426-432)."""

    market_id = _bind_market(home, suffix="unanchored-c")
    # No snapshot, no anchor.
    _add_binary_forecast(
        home, market_id=market_id, p_yes=0.6, suffix="unanchored-c",
    )
    _resolve(
        home, market_id=market_id, resolved_label="yes",
        resolved_at="2026-06-30T00:00:00Z", suffix="unanchored-c",
    )

    env = _envelope(home, "report.calibration_anchored", {"min_sample": 20})
    assert env["ok"] is True
    summary = env["data"]["summary"]
    assert summary["sample_size"] == 0
    assert summary["unanchored_forecast_count"] == 1
    assert summary["metrics"]["unanchored_forecast_count"] == 1
    assert summary["sample_warning"] is not None
    assert any("anchored market baseline" in c for c in summary["caveats"])


def test_terminal_without_snapshot_is_unanchored(home):
    """Terminal mode with a scored forecast but no pre-resolution snapshot
    also reports unanchored_forecast_count=1 with a terminal-mode caveat."""

    market_id = _bind_market(home, suffix="unanchored-term")
    _add_binary_forecast(
        home, market_id=market_id, p_yes=0.6, suffix="unanchored-term",
    )
    _resolve(
        home, market_id=market_id, resolved_label="yes",
        resolved_at="2026-06-30T00:00:00Z", suffix="unanchored-term",
    )

    env = _envelope(home, "report.calibration_terminal", {"min_sample": 20})
    assert env["ok"] is True
    summary = env["data"]["summary"]
    assert summary["sample_size"] == 0
    assert summary["unanchored_forecast_count"] == 1
    assert any("terminal market baseline" in c for c in summary["caveats"])


# -- (d) terminal mode uses the latest PRE-resolution snapshot -----------


def test_terminal_uses_latest_pre_resolution_snapshot(home):
    """Terminal mode picks the latest snapshot captured at or before
    resolved_at, ignoring a later post-resolution snapshot. With an early
    (0.40), a late-but-pre-resolution (0.70), and a post-resolution (0.99)
    snapshot, terminal baseline == 0.70 while the anchored baseline (the
    snapshot the forecast was anchored to, captured last before the forecast)
    == 0.99 — proving the anchored vs terminal branch divergence in
    _load_market_baseline_rows (calibration.py:388-424)."""

    market_id = _bind_market(home, suffix="terminal-d")
    _add_snapshot(
        home, market_id=market_id, captured_at="2026-06-01T00:00:00Z",
        implied_probability=0.40, suffix="terminal-d-early",
    )
    _add_snapshot(
        home, market_id=market_id, captured_at="2026-06-29T00:00:00Z",
        implied_probability=0.70, suffix="terminal-d-late",
    )
    _add_snapshot(
        home, market_id=market_id, captured_at="2026-07-05T00:00:00Z",
        implied_probability=0.99, suffix="terminal-d-post",
    )
    # Anchored to the latest snapshot at forecast time (0.99, the post-res one).
    _add_binary_forecast(
        home, market_id=market_id, p_yes=0.6, suffix="terminal-d",
        anchor_to_latest_snapshot=True,
    )
    _resolve(
        home, market_id=market_id, resolved_label="yes",
        resolved_at="2026-06-30T00:00:00Z", suffix="terminal-d",
    )

    terminal = _envelope(home, "report.calibration_terminal", {"min_sample": 1})
    assert terminal["ok"] is True
    t_summary = terminal["data"]["summary"]
    assert t_summary["sample_size"] == 1
    assert t_summary["unanchored_forecast_count"] == 0
    # Latest pre-resolution snapshot (0.70), NOT the 0.99 post-resolution one.
    assert t_summary["metrics"]["baseline"] == pytest.approx(0.70)

    anchored = _envelope(home, "report.calibration_anchored", {"min_sample": 1})
    assert anchored["ok"] is True
    a_summary = anchored["data"]["summary"]
    assert a_summary["sample_size"] == 1
    # Anchored uses the snapshot probability copied at anchor time (0.99),
    # diverging from terminal's pre-resolution choice.
    assert a_summary["metrics"]["baseline"] == pytest.approx(0.99)


# -- (e) min_sample warning fires below threshold ------------------------


def test_min_sample_warning_fires_below_threshold(home):
    """One anchored scored forecast under the default min_sample (20) fires
    the sample_warning; raising min_sample keeps it firing, lowering it to 1
    silences it."""

    market_id = _bind_market(home, suffix="warn-e")
    _add_snapshot(
        home, market_id=market_id, captured_at="2026-06-10T00:00:00Z",
        implied_probability=0.55, suffix="warn-e",
    )
    _add_binary_forecast(
        home, market_id=market_id, p_yes=0.6, suffix="warn-e",
        anchor_to_latest_snapshot=True,
    )
    _resolve(
        home, market_id=market_id, resolved_label="yes",
        resolved_at="2026-06-30T00:00:00Z", suffix="warn-e",
    )

    # Default min_sample=20, sample_size=1 -> warning fires.
    env_default = _envelope(home, "report.calibration_anchored", {})
    assert env_default["data"]["summary"]["sample_warning"] is not None

    # min_sample=1, sample_size=1 -> warning silent.
    env_low = _envelope(home, "report.calibration_anchored", {"min_sample": 1})
    assert env_low["data"]["summary"]["sample_warning"] is None


# -- (f) bulk-lookup / no-N+1 on the market-baseline path (trade-trace-wjip) --


def _seed_anchored_forecast(home: Path, *, p_yes: float, suffix: str) -> str:
    """Seed one fully-resolved, anchored, scored forecast end to end. The
    snapshot gives both anchored mode (the anchor row) and terminal mode (the
    pre-resolution snapshot) a market baseline to resolve against."""

    market_id = _bind_market(home, suffix=suffix)
    _add_snapshot(
        home, market_id=market_id, captured_at="2026-06-10T00:00:00Z",
        implied_probability=0.55, suffix=suffix,
    )
    fid = _add_binary_forecast(
        home, market_id=market_id, p_yes=p_yes, suffix=suffix,
        anchor_to_latest_snapshot=True,
    )
    _resolve(
        home, market_id=market_id, resolved_label="yes",
        resolved_at="2026-06-30T00:00:00Z", suffix=suffix,
    )
    return fid


_WJIP_SEED_COUNTER = count(1)


def _seed_n_anchored(home: Path, n: int) -> None:
    for i in range(n):
        # Globally-unique suffix so the count-stability test can seed the same
        # home twice without idempotency-key collisions deduping the second batch.
        seed = next(_WJIP_SEED_COUNTER)
        _seed_anchored_forecast(
            home, p_yes=0.6 if i % 2 == 0 else 0.3, suffix=f"wjip-{seed}",
        )


@pytest.mark.parametrize("mode", ["anchored", "terminal"])
def test_baseline_load_has_no_per_row_queries(home, mode):
    """`_load_market_baseline_rows` must fire zero per-row round-trips: no
    per-row `forecast_outcomes WHERE forecast_id = ?` / `forecasts WHERE id =
    ?` (the upstream `_load_scored_rows` N+1, fixed under trade-trace-u7j3) and
    exactly one bulk baseline lookup over the already-known id set — one
    IN-list anchor query (anchored) or one window-function CTE (terminal),
    never re-running the full scored-row load (trade-trace-wjip)."""

    _seed_n_anchored(home, 6)
    with sqlite3.connect(db_path(home)) as conn:
        trace = _QueryTrace()
        conn.set_trace_callback(trace)
        rows, unanchored = _load_market_baseline_rows(
            conn, ReportFilter.model_validate({}), mode=mode,
        )
        conn.set_trace_callback(None)

    assert len(rows) >= 6
    assert unanchored == 0
    # Upstream N+1 (per-row) is gone on this path.
    assert trace.count_substr("forecast_outcomes WHERE forecast_id = ?") == 0
    assert trace.count_substr("FROM forecasts WHERE id = ?") == 0
    # Exactly one bulk forecast_outcomes IN-list fetch (from _load_scored_rows).
    assert trace.count_substr("forecast_outcomes WHERE forecast_id IN") == 1
    # Exactly one baseline lookup over the known id set, mode-specific.
    if mode == "anchored":
        assert trace.count_substr("FROM forecast_snapshot_anchor") == 1
        # The anchored lookup is a single IN-list, not a re-loaded scored set.
        assert trace.count_substr("forecast_id IN (") >= 1
    else:
        # Terminal baseline is one window-function CTE keyed on the score-id set.
        assert trace.count_substr("terminal_candidates") == 1
        assert trace.count_substr("fs.id IN (") == 1


@pytest.mark.parametrize("mode", ["anchored", "terminal"])
def test_baseline_query_count_does_not_grow_with_n(home, mode):
    """The whole point of trade-trace-wjip: the statement count on the
    market-baseline path is independent of the scored-row population. Doubling
    (and more) the anchored forecasts must not scale the number of statements
    `_load_market_baseline_rows` issues."""

    _seed_n_anchored(home, 3)
    with sqlite3.connect(db_path(home)) as conn:
        trace_small = _QueryTrace()
        conn.set_trace_callback(trace_small)
        _load_market_baseline_rows(
            conn, ReportFilter.model_validate({}), mode=mode,
        )
        conn.set_trace_callback(None)
    small = len(trace_small.statements)

    _seed_n_anchored(home, 9)  # population now 12
    with sqlite3.connect(db_path(home)) as conn:
        trace_big = _QueryTrace()
        conn.set_trace_callback(trace_big)
        _load_market_baseline_rows(
            conn, ReportFilter.model_validate({}), mode=mode,
        )
        conn.set_trace_callback(None)
    big = len(trace_big.statements)

    # Constant query count (scored-row load + one bulk baseline lookup) — not O(N).
    assert small == big
