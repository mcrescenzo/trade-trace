from __future__ import annotations

from pathlib import Path


def test_terminal_calibration_uses_set_based_latest_snapshot_query():
    source = Path("src/trade_trace/reports/calibration.py").read_text(encoding="utf-8")
    assert "ROW_NUMBER() OVER" in source
    assert "terminal_candidates" in source
    assert "WHERE fs.id = ?" not in source
