from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCORECARD = ROOT / "docs" / "architecture" / "agent-continuity-scorecard.md"

REQUIRED_METRIC_IDS = {
    "AC-01": "Missed obligations recovered",
    "AC-02": "Stale ideas recovered",
    "AC-03": "Memory usefulness evidenced",
    "AC-04": "False-confidence/advice incidents surfaced or absent",
    "AC-05": "Hidden writes absent from read reports",
    "AC-06": "No-network/default-off proof",
    "AC-07": "Token/truncation behavior explicit",
    "AC-08": "Replay/evaluation labels kept separate",
    "AC-09": "Policy changes quarantined before activation",
}

FORBIDDEN_CRITERIA_PATTERNS = re.compile(
    r"\b("
    r"trading profit|profit ranking|ranked by profit|guaranteed profit|"
    r"live performance|live-market performance|market accuracy|"
    r"buy now|sell now|best trade|recommended trade|financial advice"
    r")\b",
    re.IGNORECASE,
)


def _metric_rows(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("| AC-"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        rows[cells[0]] = line
    return rows


def test_agent_continuity_scorecard_locks_required_metric_rows_and_evidence() -> None:
    text = SCORECARD.read_text(encoding="utf-8")
    rows = _metric_rows(text)

    assert rows.keys() >= REQUIRED_METRIC_IDS.keys()
    for metric_id, label in REQUIRED_METRIC_IDS.items():
        row = rows[metric_id]
        assert label in row
        assert "tests/" in row

    assert text.count("agent-continuity-loop") >= 3
    assert (
        "journal fixture_seed --home \"$TT_HOME\" --target agent-continuity-loop "
        "--allow-no-idempotency"
    ) in text
    assert "PYTHONPATH=src pytest tests/integration/test_agent_continuity_fixture.py" in text
    assert "rec_agent_continuity_0001" in text


def test_agent_continuity_scorecard_criteria_avoid_trading_results_or_advice_claims() -> None:
    text = SCORECARD.read_text(encoding="utf-8")
    rows = _metric_rows(text)

    offenders = [row for row in rows.values() if FORBIDDEN_CRITERIA_PATTERNS.search(row)]
    assert not offenders, "scorecard metric rows must not use trading-results/advice criteria:\n" + "\n".join(offenders)

    boundary_section = text.split("## Boundary rules for evaluators", maxsplit=1)[1]
    assert "Do not add pass criteria" in boundary_section
    assert "live performance" in boundary_section
    assert "financial advice" in boundary_section
    assert "caller-supplied data only" in text
