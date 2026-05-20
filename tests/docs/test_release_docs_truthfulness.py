"""Release docs must not regress to stale audit/proof claims.

Bead trade-trace-5o27 fixed release docs that claimed tracked audit
artifacts were absent even though curated docs/audits evidence is
intentionally repo-public.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FINAL_GATE = ROOT / "docs" / "RELEASE_FINAL_GATE.md"
CHECKLIST = ROOT / "docs" / "RELEASE_CHECKLIST.md"


def test_release_final_gate_matches_tracked_audit_policy() -> None:
    text = FINAL_GATE.read_text(encoding="utf-8")

    assert "docs/audits/` is intentionally tracked" in text
    assert "curated audit evidence" in text
    assert "repo-public" in text
    assert "^docs/audits/'` | empty" not in text
    assert "Beads/audit artifacts not public" not in text


def test_release_docs_do_not_publish_stale_pytest_counts_as_current() -> None:
    checklist = CHECKLIST.read_text(encoding="utf-8")
    final_gate = FINAL_GATE.read_text(encoding="utf-8")

    assert "1059 passed expected" not in checklist
    assert "record the fresh current-HEAD result" in checklist
    assert "historical snapshot" in final_gate
    assert "not a live/current proof" in final_gate
