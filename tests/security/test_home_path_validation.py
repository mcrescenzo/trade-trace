"""Path-traversal rejection on the `--home` / `args["home"]` surface
per bead trade-trace-pqex.

`resolve_home` refuses any explicit value containing a `..` path
component, and the dispatcher translates the resulting
`HomePathValidationError` into a typed `VALIDATION_ERROR` envelope
regardless of which tool handler called `resolve_home`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.storage.paths import (
    HomePathValidationError,
    resolve_home,
)


@pytest.mark.parametrize(
    "value",
    [
        "../../etc/passwd",
        "../escape",
        "valid/../../escape",
        "foo/../../bar",
    ],
)
def test_resolve_home_rejects_dotdot_components(value: str) -> None:
    with pytest.raises(HomePathValidationError) as info:
        resolve_home(value)
    assert info.value.value == value


def test_resolve_home_accepts_clean_paths(tmp_path: Path) -> None:
    resolved = resolve_home(str(tmp_path / "clean"))
    assert resolved.name == "clean"


def test_dispatch_rejects_dotdot_home_with_validation_error(
    tmp_path: Path,
) -> None:
    """End-to-end: any tool handler that resolves `args["home"]` must
    surface a typed VALIDATION_ERROR envelope with field='home' and
    reason='path_traversal_rejected' when the caller passes a `..`
    value (bead trade-trace-pqex)."""

    env = _mcp(tmp_path, "journal.status", {
        "home": "../../etc/passwd",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "home"
    assert env.error.details["reason"] == "path_traversal_rejected"
    assert env.error.details["value"] == "../../etc/passwd"


def test_dispatch_rejects_dotdot_home_on_write_tool(tmp_path: Path) -> None:
    """The same protection applies to write tools that route through
    `open_db_for_args` (bead trade-trace-pqex)."""

    env = _mcp(tmp_path, "venue.add", {
        "home": "../../tmp/escape",
        "name": "PM",
        "kind": "prediction_market",
        "idempotency_key": "k-1",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "home"
    assert env.error.details["reason"] == "path_traversal_rejected"
