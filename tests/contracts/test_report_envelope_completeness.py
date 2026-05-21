"""Report envelope completeness + reliability bin policy per bead u5s.

Verifies contracts.md §1.2 / §3.2 and reports.md §3.1-§3.2:

- Every `report.*` success envelope carries the full standard meta field
  set (`bin_policy`, `cli_human_hint`, `mcp_transport_hints`, `truncated`,
  `next_cursor`, `sample_warning`); absent fields surface as JSON `null`.
- Reliability bin assignment is fixed at boundaries `p=0.0, 0.099, 0.1,
  0.5, 0.999, 1.0`.
- Empty bins are reported with `count=0` and null means; ECE excludes
  empty bins.
- Sample-size minimums per report kind emit `sample_warning` below
  threshold.
- `mcp_transport_hints` is a (possibly empty) dict on the MCP path;
  `cli_human_hint` is absent on the MCP path.
"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from trade_trace.contracts import REPORT_STANDARD_META_KEYS, dump_envelope
from trade_trace.mcp_server import mcp_call
from trade_trace.reports.calibration import _ece_and_bins, _ScoredRow

# -- fixtures -----------------------------------------------------------


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.ok
    return h


def _envelope_dict(home: Path, tool: str, args: dict) -> dict:
    payload = {"home": str(home), **args}
    env = mcp_call(tool, payload, actor_id="agent:default")
    return dump_envelope(env)


def _seed_scored_forecasts(
    home: Path, *, p_yes_list: list[float],
) -> list[str]:
    """Resolve N binary forecasts end-to-end via the public surface; return
    the list of forecast ids."""

    venue = _envelope_dict(home, "venue.add",
                           {"name": "PM", "kind": "prediction_market"})
    inst = _envelope_dict(home, "instrument.add", {
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "X",
    })
    fids: list[str] = []
    for i, p in enumerate(p_yes_list):
        thesis = _envelope_dict(home, "thesis.add", {
            "instrument_id": inst["data"]["id"],
            "side": "yes", "body": f"t{i}",
        })
        f = _envelope_dict(home, "forecast.add", {
            "thesis_id": thesis["data"]["id"], "kind": "binary",
            "yes_label": "yes",
            "outcomes": [
                {"outcome_label": "yes", "probability": p},
                {"outcome_label": "no", "probability": 1.0 - p},
            ],
        })
        _envelope_dict(home, "outcome.add", {
            "instrument_id": inst["data"]["id"],
            "resolved_at": f"2026-06-{i + 1:02d}T00:00:00Z",
            "outcome_label": "yes", "status": "resolved_final",
        })
        fids.append(f["data"]["id"])
    return fids


# -- 1. meta presence per report kind -----------------------------------


REPORT_TOOLS_AND_ARGS: list[tuple[str, dict[str, Any]]] = [
    ("report.calibration", {}),
    ("report.mistakes", {}),
    ("report.strengths", {}),
    ("report.pnl", {}),
    ("report.watchlist", {}),
    ("report.open_positions", {}),
    ("report.exposure_anomalies", {}),
    ("report.current_exposure", {}),
    ("report.unscored_forecasts", {}),
    ("report.decision_velocity", {}),
    ("report.coach", {}),
    ("report.filter_schema", {}),
]


@pytest.mark.parametrize("tool,extra", REPORT_TOOLS_AND_ARGS)
def test_report_meta_carries_full_standard_field_set(home, tool, extra):
    """contracts.md §3.2: every report.* envelope contains the standard
    meta keys, with absent fields surfacing as JSON null."""

    body = _envelope_dict(home, tool, extra)
    assert body["ok"] is True
    meta = body["meta"]
    # Always-present fields.
    assert meta["tool"] == tool
    assert meta["contract_version"] == "1.0"
    assert isinstance(meta["request_id"], str) and len(meta["request_id"]) > 0
    # Standard report meta surface (null when not populated).
    for key in REPORT_STANDARD_META_KEYS:
        assert key in meta, f"report meta missing {key!r} on {tool}"


def test_calibration_meta_bin_policy_is_set(home):
    """report.calibration sets meta.bin_policy to the active policy
    identifier; other reports leave it null."""

    body = _envelope_dict(home, "report.calibration", {})
    assert body["meta"]["bin_policy"] == "equal_width_0.1"

    body_other = _envelope_dict(home, "report.mistakes", {})
    assert body_other["meta"]["bin_policy"] is None


# -- 2. reliability bin boundary mapping -------------------------------


@pytest.mark.parametrize(
    "p,expected_bin",
    [
        (0.0, 0),
        (0.099, 0),
        (0.1, 1),
        (0.5, 5),
        (0.999, 9),
        (1.0, 9),
    ],
)
def test_reliability_bin_assignment_at_boundaries(p, expected_bin):
    """scoring.md §7.2 fixed boundary policy: lower edge belongs to the
    upper bin; the topmost bin is closed on the right (p=1.0 → bin 9)."""

    rows = [_ScoredRow(
        forecast_id="f", score_id="s", outcome_id="o",
        p_yes=p, y=1, late_recorded=False,
    )]
    _ece, panel = _ece_and_bins(rows)
    non_empty = [b for b in panel if b["count"] > 0]
    assert len(non_empty) == 1
    assert non_empty[0]["bin_index"] == expected_bin


# -- 3. empty bin handling --------------------------------------------


def test_empty_bin_has_count_zero_with_null_means():
    """Empty bins carry count=0 and null mean_probability /
    observed_frequency / gap per scoring.md §7.2."""

    rows = [_ScoredRow(
        forecast_id="f", score_id="s", outcome_id="o",
        p_yes=0.55, y=1, late_recorded=False,
    )]
    _ece, panel = _ece_and_bins(rows)
    assert len(panel) == 10
    bin5 = next(b for b in panel if b["bin_index"] == 5)
    assert bin5["count"] == 1  # 0.55 → bin 5
    bin0 = next(b for b in panel if b["bin_index"] == 0)
    assert bin0["count"] == 0
    assert bin0["mean_probability"] is None
    assert bin0["observed_frequency"] is None
    assert bin0["gap"] is None


def test_ece_excludes_empty_bins():
    """An empty bin contributes zero to ECE: a single forecast in bin 5
    yields ECE = |p-y| * 1 (only its bin matters) regardless of the nine
    empty bins surrounding it."""

    rows = [_ScoredRow(
        forecast_id="f", score_id="s", outcome_id="o",
        p_yes=0.7, y=1, late_recorded=False,
    )]
    ece, panel = _ece_and_bins(rows)
    # Only bin 7 has count>0; gap = 0.7 - 1.0 = -0.3; |gap|=0.3 * (1/1) = 0.3
    assert math.isclose(ece, 0.3, abs_tol=1e-9)
    empty_count = sum(1 for b in panel if b["count"] == 0)
    assert empty_count == 9


# -- 4. sample-size warnings per report kind -------------------------


def test_calibration_sample_warning_below_20(home):
    """report.calibration min_sample default is 20."""

    _seed_scored_forecasts(home, p_yes_list=[0.6, 0.7])  # 2 scored
    body = _envelope_dict(home, "report.calibration", {})
    warn = body["data"]["summary"]["sample_warning"]
    assert warn is not None
    assert "20" in warn
    # The meta surface mirrors the summary warning per contracts.md §3.2.
    assert body["meta"]["sample_warning"] == warn


def test_calibration_sample_warning_silent_above_threshold(home):
    """When sample_size >= min_sample, sample_warning is null on both the
    summary and the meta envelope."""

    _seed_scored_forecasts(home, p_yes_list=[0.6, 0.7, 0.5])
    body = _envelope_dict(home, "report.calibration", {"min_sample": 3})
    assert body["data"]["summary"]["sample_warning"] is None
    assert body["meta"]["sample_warning"] is None


# -- 5. mcp_transport_hints structure & cli_human_hint absence -------


def test_mcp_transport_hints_is_dict_on_mcp_path(home):
    """The MCP shim populates `meta.mcp_transport_hints` with a (possibly
    empty) dict so agents can branch on structure consistently."""

    body = _envelope_dict(home, "report.calibration", {})
    hints = body["meta"]["mcp_transport_hints"]
    assert isinstance(hints, dict), (
        f"mcp_transport_hints must be a dict on MCP path; got {type(hints)}"
    )


def test_cli_human_hint_absent_on_mcp_path(home):
    """`cli_human_hint` is a CLI-only affordance; on the MCP path it
    surfaces as null so the field is present but empty."""

    body = _envelope_dict(home, "report.calibration", {})
    assert body["meta"]["cli_human_hint"] is None


def test_cli_human_hint_populated_when_human_flag_passed(tmp_path):
    """End-to-end CLI exercise: --human surfaces a one-line hint string
    on meta.cli_human_hint AND prints it to stderr; stdout stays pure JSON."""

    home = tmp_path / "home"
    # Initialize via CLI subprocess for a real end-to-end check.
    import os
    env = {**dict(os.environ), "PYTHONPATH": "src"}
    init = subprocess.run(
        [sys.executable, "-m", "trade_trace.cli", "--actor-id", "cli:default",
         "journal", "init", "--home", str(home)],
        capture_output=True, text=True, env=env,
    )
    assert init.returncode == 0, init.stderr
    result = subprocess.run(
        [sys.executable, "-m", "trade_trace.cli", "--human",
         "--actor-id", "cli:default",
         "report", "calibration", "--home", str(home)],
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, result.stderr
    import json
    body = json.loads(result.stdout)
    assert body["ok"] is True
    # cli_human_hint is set on the CLI path when --human is passed.
    assert body["meta"]["cli_human_hint"] is not None
    assert "report.calibration" in body["meta"]["cli_human_hint"]
    # Stderr also carries the prose hint (--human goes to stderr).
    assert "report.calibration" in result.stderr


# -- 6. truncated / next_cursor default to null ---------------------


def test_truncated_and_next_cursor_null_by_default(home):
    body = _envelope_dict(home, "report.calibration", {})
    assert body["meta"]["truncated"] is None
    assert body["meta"]["next_cursor"] is None
