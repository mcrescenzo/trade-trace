from __future__ import annotations

import json
import socket
from pathlib import Path

from tests._mcp_helpers import with_legacy_idempotency_key
from trade_trace.core import default_registry, dispatch
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path


def _env(tool: str, args: dict, *, actor_id: str = "import:test") -> dict:
    return dispatch(tool, with_legacy_idempotency_key(tool, args), actor_id=actor_id).model_dump(mode="json", exclude_none=True)


def _init_with_instrument(home: Path) -> str:
    assert _env("journal.init", {"home": str(home)})["ok"] is True
    ven = _env("venue.add", {"home": str(home), "name": "CSV Venue", "kind": "broker", "idempotency_key": "ven"})
    assert ven["ok"] is True
    inst = _env(
        "instrument.add",
        {
            "home": str(home),
            "venue_id": ven["data"]["id"],
            "asset_class": "equity",
            "symbol": "AAPL",
            "title": "Apple Inc.",
            "idempotency_key": "inst",
        },
    )
    assert inst["ok"] is True
    return inst["data"]["id"]


def _write_csv_and_mapping(tmp_path: Path, instrument_id: str, *, side_rule=None) -> tuple[Path, Path]:
    csv_path = tmp_path / "fills.csv"
    csv_path.write_text(
        "Symbol,DateTime,Action,Quantity,Price,Commission,Account,Tags\n"
        "AAPL,05/19/2026 09:30:00,BTO,10,100.5,1.25,main,alpha;ignored\n",
        encoding="utf-8",
    )
    mapping = {
        "instrument_id": {"static": instrument_id},
        "executed_at": {"column": "DateTime", "format": "%m/%d/%Y %H:%M:%S", "timezone": "America/New_York"},
        "side": side_rule or {"column": "Action", "values": {"BTO": "long", "STC": "long"}},
        "quantity": "Quantity",
        "price": "Price",
        "fees": {"column": "Commission", "default": 0},
        "account_label": "Account",
        "strategy_slug": {"static": "mean-reversion"},
        "tags": {"static": ["import:csv", "broker:test"]},
    }
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps(mapping), encoding="utf-8")
    return csv_path, mapping_path


def test_csv_import_registered_and_schema_discoverable():
    reg = default_registry()
    assert "import.csv_fills" in reg.names()
    registration = reg.get("import.csv_fills")
    assert registration.name == "import.csv_fills"
    assert "mapping" in registration.description


def test_csv_import_commits_via_jsonl_artifact_and_replays_idempotently(tmp_path: Path):
    home = tmp_path / "home"
    instrument_id = _init_with_instrument(home)
    csv_path, mapping_path = _write_csv_and_mapping(tmp_path, instrument_id)

    args = {"home": str(home), "csv_path": str(csv_path), "mapping_path": str(mapping_path), "import_run_id": "run-001"}
    first = _env("import.csv_fills", args)
    assert first["ok"] is True
    assert first["data"]["row_count"] == 1
    assert first["data"]["commit_result"]["committed_count"] == 1
    artifact = Path(first["data"]["artifact_path"])
    assert artifact.exists()
    assert home in artifact.parents
    line = json.loads(artifact.read_text(encoding="utf-8"))
    assert line["tool"] == "decision.add"
    assert line["args"]["type"] == "add"
    assert line["args"]["side"] == "long"
    assert line["args"]["quantity"] == 10.0
    assert line["args"]["fees"] == 1.25
    assert len(line["args"]["idempotency_key"]) == 32
    assert line["args"]["metadata_json"]["executed_at"] == "2026-05-19T13:30:00.000Z"
    assert line["args"]["metadata_json"]["account_label"] == "main"
    assert line["args"]["metadata_json"]["strategy_slug"] == "mean-reversion"
    assert line["args"]["tags"] == ["import:csv", "broker:test"]

    second = _env("import.csv_fills", args)
    assert second["ok"] is True
    assert second["data"]["commit_result"]["would_replay"] == 1
    assert second["data"]["commit_result"]["committed_count"] == 1

    db = open_database(db_path(home), create_parent=False)
    try:
        count = db.connection.execute("SELECT count(*) FROM decisions").fetchone()[0]
    finally:
        db.close()
    assert count == 1


def test_mapping_validation_rejects_missing_mapping_and_required_target(tmp_path: Path):
    home = tmp_path / "home"
    instrument_id = _init_with_instrument(home)
    csv_path, mapping_path = _write_csv_and_mapping(tmp_path, instrument_id)
    missing = _env("import.csv_fills", {"home": str(home), "csv_path": str(csv_path), "mapping_path": str(tmp_path / "absent.json")})
    assert missing["ok"] is False
    assert missing["error"]["code"] == "NOT_FOUND"

    bad_mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    del bad_mapping["price"]
    mapping_path.write_text(json.dumps(bad_mapping), encoding="utf-8")
    env = _env("import.csv_fills", {"home": str(home), "csv_path": str(csv_path), "mapping_path": str(mapping_path)})
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "price"


def test_no_broker_auto_inference_external_symbol_is_not_resolved(tmp_path: Path):
    home = tmp_path / "home"
    _init_with_instrument(home)
    csv_path = tmp_path / "fills.csv"
    csv_path.write_text("Symbol,DateTime,Action,Quantity,Price\nAAPL,2026-05-19T13:30:00Z,buy,1,10\n", encoding="utf-8")
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(json.dumps({
        "instrument_external_id": "Symbol",
        "executed_at": "DateTime",
        "side": "Action",
        "quantity": "Quantity",
        "price": "Price",
    }), encoding="utf-8")
    env = _env("import.csv_fills", {"home": str(home), "csv_path": str(csv_path), "mapping_path": str(mapping_path)})
    assert env["ok"] is False
    assert env["error"]["code"] == "UNSUPPORTED_CAPABILITY"
    assert env["error"]["details"]["field"] == "instrument_external_id"


def test_absolute_import_run_id_cannot_escape_home(tmp_path: Path):
    """Security regression (bead trade-trace-yuyk): an absolute
    `import_run_id` must NOT re-root the JSONL artifact outside
    `$TRADE_TRACE_HOME`. Before the fix, the run-id-derived directory
    segment was joined onto `$HOME/import/csv` without stripping `/`, so
    `import_run_id='/tmp/...'` resolved the target dir to `/tmp/...` and
    wrote the artifact + parents outside home."""

    home = tmp_path / "home"
    instrument_id = _init_with_instrument(home)
    csv_path, mapping_path = _write_csv_and_mapping(tmp_path, instrument_id)

    escape_dir = tmp_path / "escape"
    evil_run_id = str(escape_dir / "evil")
    assert not escape_dir.exists()

    env = _env(
        "import.csv_fills",
        {
            "home": str(home),
            "csv_path": str(csv_path),
            "mapping_path": str(mapping_path),
            "import_run_id": evil_run_id,
        },
    )

    # The import still succeeds — the run id is sanitized, not rejected —
    # but the artifact stays under $HOME/import/csv.
    assert env["ok"] is True, env
    artifact = Path(env["data"]["artifact_path"])
    assert artifact.exists()
    assert home in artifact.parents
    csv_root = home / "import" / "csv"
    assert csv_root in artifact.parents
    # The single sanitized segment carries no path separators.
    segment = artifact.parent.relative_to(csv_root)
    assert len(segment.parts) == 1
    # Nothing was written to the would-be escape location.
    assert not escape_dir.exists()


def test_traversal_import_run_id_cannot_escape_home(tmp_path: Path):
    """Security regression (bead trade-trace-yuyk): a `..`-laden
    `import_run_id` cannot climb out of `$HOME/import/csv` either."""

    home = tmp_path / "home"
    instrument_id = _init_with_instrument(home)
    csv_path, mapping_path = _write_csv_and_mapping(tmp_path, instrument_id)

    env = _env(
        "import.csv_fills",
        {
            "home": str(home),
            "csv_path": str(csv_path),
            "mapping_path": str(mapping_path),
            "import_run_id": "../../../../tmp/escape",
        },
    )
    assert env["ok"] is True, env
    artifact = Path(env["data"]["artifact_path"])
    assert artifact.exists()
    assert (home / "import" / "csv") in artifact.parents
    assert ".." not in artifact.parent.relative_to(home / "import" / "csv").parts


def test_csv_import_does_not_use_socket_network(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    instrument_id = _init_with_instrument(home)
    csv_path, mapping_path = _write_csv_and_mapping(tmp_path, instrument_id, side_rule={"column": "Action", "values": {"BTO": "long"}})

    def fail_socket(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("network/socket use is forbidden")

    monkeypatch.setattr(socket, "socket", fail_socket)
    env = _env("import.csv_fills", {"home": str(home), "csv_path": str(csv_path), "mapping_path": str(mapping_path), "import_run_id": "no-net"})
    assert env["ok"] is True
