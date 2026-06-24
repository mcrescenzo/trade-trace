from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_active_scoring_docs_do_not_claim_non_binary_autoscoring_ships():
    text = "\n".join(
        [
            (ROOT / "docs" / "PRD.md").read_text(encoding="utf-8"),
            (ROOT / "docs" / "architecture" / "scoring.md").read_text(encoding="utf-8"),
        ]
    ).lower()

    forbidden = [
        "categorical and normalized scalar auto-scoring now ship",
        "supported scoring scope is binary, categorical/multiclass, and normalized scalar",
        "categorical and normalized scalar auto-scoring were added",
        "multi-class/categorical and normalized scalar scoring shipped",
        "normalized scalar auto-scoring shipped",
    ]
    offenders = [phrase for phrase in forbidden if phrase in text]
    assert offenders == []
