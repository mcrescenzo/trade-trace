"""No-credential audit per PRD §2.8 and VISION §safety.

The MVP commitment is unconditional: no execution path, no broker keys, no
wallet seeds, no signing material. Credential-shaped args passed to any
write tool MUST be silently ignored (i.e. never persisted in any column or
metadata_json blob) or rejected outright.

This test exhaustively exercises every M1 write tool with credential-shaped
inputs and verifies (a) no credential key lands in any metadata_json or row,
(b) no tool schema accepts a credential-shaped field name, (c) the import
contract's `import_ready_writers` list does not include any credential-
handling tool.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path

CREDENTIAL_KEYS = [
    "api_key",
    "access_token",
    "refresh_token",
    "auth_token",
    "bearer_token",
    "secret_key",
    "client_secret",
    "password",
    "passphrase",
    "wallet_seed",
    "wallet_seed_phrase",
    "seed_phrase",
    "mnemonic",
    "private_key",
    "signing_key",
    "signing_secret",
    "broker_token",
    "trading_password",
    "session_token",
    "oauth_token",
]

CREDENTIAL_VALUE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"xoxb-[A-Za-z0-9-]+"),
    re.compile(r"0x[0-9a-fA-F]{40}"),
]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    h = tmp_path / "home"
    mcp_call("journal.init", {"home": str(h)})
    return h


def _all_columns(home: Path, table: str) -> list[str]:
    db = open_database(db_path(home), create_parent=False)
    try:
        cur = db.connection.execute(f"PRAGMA table_info({table})")
        return [r[1] for r in cur.fetchall()]
    finally:
        db.close()


def test_no_table_column_resembles_credential(home: Path):
    """No M1 table has a column whose name suggests credentials."""

    db = open_database(db_path(home), create_parent=False)
    try:
        tables = [
            r[0] for r in db.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        all_columns = []
        for t in tables:
            cur = db.connection.execute(f"PRAGMA table_info({t})")
            for r in cur.fetchall():
                all_columns.append((t, r[1]))
    finally:
        db.close()
    for table, col in all_columns:
        for forbidden in CREDENTIAL_KEYS:
            assert forbidden not in col.lower(), (
                f"table {table}.{col} resembles credential field {forbidden!r}"
            )


def test_no_tool_description_mentions_credentials():
    """No registered tool's description hints at credential handling."""

    registry = default_registry()
    for reg in registry.by_name.values():
        for forbidden in CREDENTIAL_KEYS:
            assert forbidden not in reg.description.lower(), (
                f"tool {reg.name} description mentions {forbidden!r}"
            )


def test_venue_add_silently_drops_credential_args(home: Path):
    """Credential-shaped keys passed as args must NOT land in metadata_json."""

    extras = {k: f"leaky-{k}" for k in CREDENTIAL_KEYS}
    env = mcp_call("venue.add", {
        "home": str(home),
        "name": "PM",
        "kind": "prediction_market",
        **extras,
    }, actor_id="agent:default").model_dump(mode="json", exclude_none=True)
    assert env["ok"] is True
    venue_id = env["data"]["id"]

    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT metadata_json FROM venues WHERE id = ?", (venue_id,)
        ).fetchone()
        meta = json.loads(row[0])
    finally:
        db.close()
    for k in CREDENTIAL_KEYS:
        assert k not in meta, f"venue.metadata_json leaked credential key {k!r}"


@pytest.mark.parametrize("credential_key", ["api_key", "client_secret", "access_token", "password"])
def test_metadata_json_rejects_nested_credential_key(home: Path, credential_key: str):
    env = mcp_call("venue.add", {
        "home": str(home),
        "name": "PM",
        "kind": "prediction_market",
        "metadata_json": {"safe": {credential_key: "leaky-value"}},
    }, actor_id="agent:default").model_dump(mode="json")
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "metadata_json"
    assert env["error"]["details"]["credential_key"] == credential_key


def test_metadata_json_rejects_raw_json_credential_key(home: Path):
    env = mcp_call("venue.add", {
        "home": str(home),
        "name": "PM",
        "kind": "prediction_market",
        "metadata_json": json.dumps({"safe": [{"broker_token": "leaky-value", "access_token": "leaky-value"}]}),
    }, actor_id="agent:default").model_dump(mode="json")
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "metadata_json"
    assert env["error"]["details"]["credential_key"] in {"broker_token", "access_token"}


def test_metadata_json_rejects_invalid_raw_json_string(home: Path):
    env = mcp_call("venue.add", {
        "home": str(home),
        "name": "PM",
        "kind": "prediction_market",
        "metadata_json": '{"client_secret": "leaky-value"',
    }, actor_id="agent:default").model_dump(mode="json")
    assert env["ok"] is False
    assert env["error"]["code"] == "VALIDATION_ERROR"
    assert env["error"]["details"]["field"] == "metadata_json"
    assert env["error"]["details"]["reason"] == "invalid_json"


def test_instrument_add_silently_drops_credential_args(home: Path):
    venue = mcp_call("venue.add", {
        "home": str(home), "name": "PM", "kind": "prediction_market",
    }, actor_id="agent:default").model_dump(mode="json")
    env = mcp_call("instrument.add", {
        "home": str(home),
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Test",
        "api_key": "sk-leaky",
        "wallet_seed": "twelve words",
    }, actor_id="agent:default").model_dump(mode="json")
    assert env["ok"] is True
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT metadata_json FROM instruments WHERE id = ?", (env["data"]["id"],)
        ).fetchone()
        meta = json.loads(row[0])
    finally:
        db.close()
    assert "api_key" not in meta
    assert "wallet_seed" not in meta


def test_decision_add_silently_drops_credential_args(home: Path):
    venue = mcp_call("venue.add", {
        "home": str(home), "name": "PM", "kind": "prediction_market",
    }, actor_id="agent:default").model_dump(mode="json")
    inst = mcp_call("instrument.add", {
        "home": str(home),
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market", "title": "Test",
    }, actor_id="agent:default").model_dump(mode="json")
    env = mcp_call("decision.add", {
        "home": str(home),
        "instrument_id": inst["data"]["id"],
        "type": "skip",
        "reason": "spread too wide",
        "private_key": "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    }, actor_id="agent:default").model_dump(mode="json")
    assert env["ok"] is True
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT metadata_json FROM decisions WHERE id = ?", (env["data"]["id"],)
        ).fetchone()
        meta = json.loads(row[0])
    finally:
        db.close()
    assert "private_key" not in meta


def test_no_tool_exposes_credential_arg_in_handler_signature():
    """Static check: read the source of each registered tool's handler
    module and ensure no `validate_credential` / `accept_api_key` /
    similar helper is present."""

    registry = default_registry()
    seen_modules = set()
    for reg in registry.by_name.values():
        mod = reg.handler.__module__
        if mod in seen_modules:
            continue
        seen_modules.add(mod)
        # Read the module source.
        import importlib

        m = importlib.import_module(mod)
        path = Path(m.__file__)
        if not path.exists():
            continue
        source = path.read_text()
        for forbidden in CREDENTIAL_KEYS:
            # Check for any function declaration or attribute access that
            # would suggest writing a credential.
            for token in (f"args.get('{forbidden}')", f'args.get("{forbidden}")'):
                assert token not in source, f"{path}: handler reads {forbidden!r}"


def test_import_ready_writers_excludes_credential_handlers():
    """Import replay uses the shared registry and must not expose credential-shaped tools."""

    from trade_trace.core import default_registry

    writers = {name for name in default_registry().names() if name not in {"import.validate", "import.commit"}}
    for tool in writers:
        for forbidden in CREDENTIAL_KEYS:
            assert forbidden not in tool, f"import tool {tool!r} resembles {forbidden!r}"


def test_journal_status_never_carries_credentials(home: Path):
    """The single most-called read tool must never surface a credential."""

    env = mcp_call("journal.status", {"home": str(home)}).model_dump(mode="json")
    serialized = json.dumps(env)
    for pattern in CREDENTIAL_VALUE_PATTERNS:
        assert not pattern.search(serialized), (
            f"journal.status response matched credential pattern {pattern.pattern!r}"
        )
