"""Import-path hardening: resource bounds + credential-target source of
truth (bead trade-trace-g86k).

Two low-severity import-surface findings are pinned here:

1. JSONL (`import.commit` / `import.validate`) and CSV (`import.csv_fills`)
   loaded their entire input into memory before dispatch with no row-count
   or file-size cap — an unbounded-in-memory-load foot-gun for an automated
   agent pointed at an arbitrary path. Both paths now reject oversized
   inputs with a typed VALIDATION_ERROR.

2. `csv_import._FORBIDDEN_MAPPING_TARGETS` was a hand-maintained copy that
   had silently dropped `oauth_token` from the canonical
   `PROJECT_CREDENTIAL_KEYS` set. It now derives from the single source of
   truth so the credential boundary can never drift behind it again.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trade_trace.mcp_server import mcp_call
from trade_trace.security.credential_keys import PROJECT_CREDENTIAL_KEYS
from trade_trace.tools import csv_import, imports


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    assert mcp_call("journal.init", {"home": str(h)}, actor_id="agent:default").ok
    return h


# -- finding 2: credential-target source of truth ----------------------


def test_forbidden_mapping_targets_match_canonical_credential_keys():
    """The CSV adapter's forbidden mapping-target set must BE the canonical
    PROJECT_CREDENTIAL_KEYS vocabulary, not a drifting hand-maintained
    copy. Regression for the dropped `oauth_token` (bead trade-trace-g86k)."""

    assert csv_import._FORBIDDEN_MAPPING_TARGETS == set(PROJECT_CREDENTIAL_KEYS)
    # The specific token that the prior hand-maintained copy dropped.
    assert "oauth_token" in csv_import._FORBIDDEN_MAPPING_TARGETS


# -- finding 1a: JSONL import row-count cap -----------------------------


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(line, sort_keys=True) + "\n" for line in lines),
        encoding="utf-8",
    )


def test_jsonl_import_rejects_row_count_over_max_rows(tmp_path, home):
    """import.commit must refuse an input whose row count exceeds max_rows
    with a typed VALIDATION_ERROR rather than building the full in-memory
    row list (bead trade-trace-g86k)."""

    artifact = tmp_path / "rows.jsonl"
    _write_jsonl(
        artifact,
        [{"tool": "venue.add", "args": {"name": f"v{i}", "kind": "broker"}} for i in range(5)],
    )
    env = mcp_call(
        "import.commit",
        {"home": str(home), "path": str(artifact), "transaction_mode": "single",
         "max_rows": 2, "idempotency_key": "g86k-jsonl-rows"},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "max_rows"
    assert env["error"]["details"]["max_rows"] == 2


def test_jsonl_import_validate_respects_max_rows(tmp_path, home):
    """The same cap applies to the read-only import.validate path so an
    agent cannot blow up memory via a dry-run either."""

    artifact = tmp_path / "rows.jsonl"
    _write_jsonl(
        artifact,
        [{"tool": "venue.add", "args": {"name": f"v{i}", "kind": "broker"}} for i in range(4)],
    )
    env = mcp_call(
        "import.validate",
        {"home": str(home), "path": str(artifact), "max_rows": 1},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "max_rows"


def test_jsonl_import_within_max_rows_is_accepted(tmp_path, home):
    """A small import under the default cap still validates cleanly — the
    guard must not regress the normal path."""

    artifact = tmp_path / "rows.jsonl"
    _write_jsonl(
        artifact,
        [{"tool": "venue.add", "args": {"name": "v0", "kind": "broker"}}],
    )
    env = mcp_call(
        "import.validate",
        {"home": str(home), "path": str(artifact)},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is True, env


def test_jsonl_import_rejects_oversized_file(tmp_path, home, monkeypatch):
    """A file larger than the aggregate byte cap is rejected before any
    line is parsed. The cap is patched tiny so the test stays fast."""

    monkeypatch.setattr(imports, "_MAX_IMPORT_FILE_BYTES", 16)
    artifact = tmp_path / "big.jsonl"
    _write_jsonl(
        artifact,
        [{"tool": "venue.add", "args": {"name": "verylongname", "kind": "broker"}}],
    )
    env = mcp_call(
        "import.validate",
        {"home": str(home), "path": str(artifact)},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "path"
    assert env["error"]["details"]["max_bytes"] == 16


# -- finding 1b: CSV import row-count cap -------------------------------


def _init_instrument(home: Path) -> str:
    ven = mcp_call(
        "venue.add",
        {"home": str(home), "name": "CSV Venue", "kind": "broker",
         "idempotency_key": "g86k-ven"},
        actor_id="agent:default",
    )
    assert ven.ok, ven
    inst = mcp_call(
        "instrument.add",
        {"home": str(home), "venue_id": ven.data["id"], "asset_class": "equity",
         "symbol": "AAPL", "title": "Apple Inc.", "idempotency_key": "g86k-inst"},
        actor_id="agent:default",
    )
    assert inst.ok, inst
    return inst.data["id"]


def _write_csv_rows(tmp_path: Path, instrument_id: str, n_rows: int) -> tuple[Path, Path]:
    header = "DateTime,Action,Quantity,Price\n"
    body = "".join(
        f"05/19/2026 09:30:0{i % 10},BTO,10,100.5\n" for i in range(n_rows)
    )
    csv_path = tmp_path / "fills.csv"
    csv_path.write_text(header + body, encoding="utf-8")
    mapping = {
        "instrument_id": {"static": instrument_id},
        "executed_at": {"column": "DateTime", "format": "%m/%d/%Y %H:%M:%S"},
        "side": {"column": "Action", "values": {"BTO": "long"}},
        "quantity": "Quantity",
        "price": "Price",
    }
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
    return csv_path, mapping_path


def test_csv_import_rejects_row_count_over_max_rows(tmp_path, home):
    """import.csv_fills must refuse a CSV whose row count exceeds max_rows
    BEFORE writing the JSONL artifact (bead trade-trace-g86k)."""

    instrument_id = _init_instrument(home)
    csv_path, mapping_path = _write_csv_rows(tmp_path, instrument_id, 5)
    env = mcp_call(
        "import.csv_fills",
        {"home": str(home), "csv_path": str(csv_path),
         "mapping_path": str(mapping_path), "max_rows": 2,
         "import_run_id": "g86k-csv-rows",
         "idempotency_key": "g86k-csv-rows-idem"},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "max_rows"
    assert env["error"]["details"]["max_rows"] == 2


def test_csv_import_rejects_oversized_file(tmp_path, home, monkeypatch):
    """A CSV larger than the byte cap is rejected up front."""

    monkeypatch.setattr(csv_import, "_MAX_CSV_FILE_BYTES", 8)
    instrument_id = _init_instrument(home)
    csv_path, mapping_path = _write_csv_rows(tmp_path, instrument_id, 3)
    env = mcp_call(
        "import.csv_fills",
        {"home": str(home), "csv_path": str(csv_path),
         "mapping_path": str(mapping_path),
         "import_run_id": "g86k-csv-bytes",
         "idempotency_key": "g86k-csv-bytes-idem"},
        actor_id="agent:default",
    ).model_dump(mode="json", exclude_none=True)
    assert env["ok"] is False, env
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "csv_path"
    assert env["error"]["details"]["max_bytes"] == 8
