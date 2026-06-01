"""Contract tests for the TraceLab human run-config decisions."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN_CONFIG_DOC = ROOT / "docs" / "tracelab" / "run-config.md"
LIVE_TEST_CHARTER = ROOT / "docs" / "LIVE_TEST_CHARTER.md"


def _doc() -> str:
    return RUN_CONFIG_DOC.read_text(encoding="utf-8")


def test_run_config_references_locked_charter_without_redefining_retry_contract() -> None:
    doc = _doc()
    charter = LIVE_TEST_CHARTER.read_text(encoding="utf-8")

    assert "docs/LIVE_TEST_CHARTER.md" in doc
    assert "locked charter" in doc
    assert "does not redefine" in doc
    assert "does not redefine, broaden, or extend" in doc
    assert "recovery-in-one-retry" in doc
    assert "Every single_writer_lock emission recovers within ONE documented retry" in charter


def test_run_config_pins_operator_decisions_and_budgets() -> None:
    doc = _doc()

    required_phrases = [
        "network.polymarket.enabled=false",
        "ADAPTER_DISABLED",
        "Do **not** use process kills such as `kill -9`",
        "hex-free `risk_unit_label`",
        "bare 40-hex tokens",
        "Minimum scoreable sample size is **N=20**",
        "`MIN_N_NOT_MET`",
        "over-seed **40-50** candidate markets",
        "**500 requests per day**",
        "previous 100-request discovery cap was superseded",
        "human-in-the-loop sign-off checkpoint",
        "`/tmp/trade-trace-tracelab/$RUN_ID`",
        "directory mode `0700`",
        "record `df -i`",
        "Follow the B20 teardown bead/runbook",
        "exclude late-recorded records",
        "`include_late_recorded=true`",
        "resolution-feeder cadence",
        "consumed by B6 scorecard work",
        "`report.watchlist` and `report.work_queue`",
        "covered by the locked charter's retry policy",
    ]
    for phrase in required_phrases:
        assert phrase in doc
