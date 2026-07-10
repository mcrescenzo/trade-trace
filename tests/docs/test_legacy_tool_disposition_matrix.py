from __future__ import annotations

import re
from pathlib import Path

from trade_trace.core import build_registry

REPO = Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "architecture" / "legacy-tool-disposition.md"
ALLOWED_DECISIONS = {"keep", "defer", "remove"}


def _matrix_rows() -> dict[str, str]:
    text = DOC.read_text(encoding="utf-8")
    match = re.search(
        r"<!-- legacy-tool-disposition-matrix:start -->(.*?)"
        r"<!-- legacy-tool-disposition-matrix:end -->",
        text,
        re.DOTALL,
    )
    assert match is not None, "legacy disposition matrix markers missing"

    rows: dict[str, str] = {}
    for row_match in re.finditer(
        r"^\|\s*`([^`]+)`\s*\|\s*([^|\s]+)\s*\|",
        match.group(1),
        re.MULTILINE,
    ):
        name, decision = row_match.groups()
        assert decision in ALLOWED_DECISIONS, f"{name}: unexpected decision {decision!r}"
        assert name not in rows, f"duplicate legacy disposition row for {name}"
        rows[name] = decision
    return rows


def test_legacy_tool_disposition_matrix_covers_runtime_legacy_registry() -> None:
    registry = build_registry()
    runtime_legacy = {
        name
        for name in registry.names()
        if registry.get(name).metadata().get("catalog_visibility") == "legacy"
    }
    matrix = set(_matrix_rows())

    assert matrix == runtime_legacy, (
        "legacy disposition matrix drifted from runtime registry; "
        f"missing: {sorted(runtime_legacy - matrix)}; "
        f"extra: {sorted(matrix - runtime_legacy)}"
    )


def test_legacy_tool_disposition_matrix_has_no_unexecuted_removals() -> None:
    rows = _matrix_rows()
    removals = sorted(name for name, decision in rows.items() if decision == "remove")
    assert removals == [], (
        "This review did not execute hard deletions. Add the runtime removal, "
        "tests/docs updates, and release-note entry before marking rows remove: "
        f"{removals}"
    )
