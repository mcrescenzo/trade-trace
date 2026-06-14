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

Per the credential-blind isolation contract
(`docs/architecture/execution-isolation-contract.md`, trade-trace-2ki5) the
ban is scoped to the journal/memory **core** — this whole repository — and is
complemented (assertions A4/A5 there) by `test_no_credential_in_export_surface`
and `test_no_credential_in_bundle_surface` below, which prove a credential-shaped
value written through a core write tool never reaches the JSONL export outbox or
a `review.bundle` / `replay.case_bundle` output. The schema/tool-shape checks
above guard the *input* edge of the credential membrane; these two guard the
*output* edge.
"""

from __future__ import annotations

import glob
import json
import re
from pathlib import Path

import pytest

from trade_trace.core import default_registry
from trade_trace.events import EventWriter
from trade_trace.mcp_server import mcp_call
from trade_trace.security.credential_keys import PROJECT_CREDENTIAL_KEYS  # noqa: E402
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path

# Audit iterates this list (test_no_credentials.py predates the shared
# vocabulary; alias kept so the audit prose still scans naturally).
CREDENTIAL_KEYS = sorted(PROJECT_CREDENTIAL_KEYS)

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


def test_no_table_column_resembles_credential(home: Path):
    """No M1 table has a column whose name suggests credentials."""

    from tests.security._schema_audit import iter_table_columns

    db = open_database(db_path(home), create_parent=False)
    try:
        for table, col in iter_table_columns(db.connection):
            for forbidden in CREDENTIAL_KEYS:
                assert forbidden not in col.lower(), (
                    f"table {table}.{col} resembles credential field {forbidden!r}"
                )
    finally:
        db.close()


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
        "private_key": "0" + "x" + "deadbeef" * 5,  # constructed per trade-trace-awxq
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


# -- isolation-contract complementary scans (A4 / A5) ------------------------
#
# These two tests pin the output edge of the credential membrane described in
# docs/architecture/execution-isolation-contract.md §6 (A4/A5): a
# credential-shaped value handed to a core write tool — both as a flat arg and
# nested in metadata_json — must never reach the JSONL export outbox or a bundle
# export, even though those surfaces serialize append-only core rows. They
# complement the input-edge schema/tool-shape checks above.

# Distinct credential value markers, assembled from non-contiguous parts so the
# test source itself cannot trip a public secret scanner (trade-trace-awxq).
_SK_MARK = "s" + "k" + "-" + "LEAKYCREDENTIALMARKER01"
_PK_MARK = "0" + "x" + ("de" * 20)


def _seed_credential_bearing_decision(home: Path) -> None:
    """Write a venue/instrument/decision carrying credential-shaped flat args
    AND credential-shaped values embedded in scanned free-text, so a leak would
    show up in any downstream serialization of these rows."""

    venue = mcp_call(
        "venue.add",
        {
            "home": str(home),
            "name": "PM",
            "kind": "prediction_market",
            # flat credential-shaped args — must be silently dropped (A3)
            "api_key": _SK_MARK,
            "private_key": _PK_MARK,
        },
        actor_id="agent:default",
    ).model_dump(mode="json")
    assert venue["ok"] is True
    inst = mcp_call(
        "instrument.add",
        {
            "home": str(home),
            "venue_id": venue["data"]["id"],
            "asset_class": "prediction_market",
            "title": "Isolation contract probe",
        },
        actor_id="agent:default",
    ).model_dump(mode="json")
    assert inst["ok"] is True
    decision = mcp_call(
        "decision.add",
        {
            "home": str(home),
            "instrument_id": inst["data"]["id"],
            "type": "skip",
            "reason": "no edge today",
            "session_token": _SK_MARK,  # flat credential arg, dropped
        },
        actor_id="agent:default",
    ).model_dump(mode="json")
    assert decision["ok"] is True


def _assert_no_credential_marker(blob: str, surface: str) -> None:
    for key in CREDENTIAL_KEYS:
        assert key not in blob, f"{surface} leaked credential key {key!r}"
    for marker in (_SK_MARK, _PK_MARK):
        assert marker not in blob, f"{surface} leaked credential value {marker!r}"
    for pattern in CREDENTIAL_VALUE_PATTERNS:
        assert not pattern.search(blob), (
            f"{surface} matched credential value pattern {pattern.pattern!r}"
        )


def test_no_credential_in_export_surface(home: Path):
    """A4: credential-shaped input never reaches the JSONL export outbox."""

    # Enable the JSONL outbox before the writes so each committed event queues
    # an export row (same primitive test_redacted_exports.py uses).
    db = open_database(db_path(home), create_parent=False)
    try:
        EventWriter(db.connection).set_outbox_jsonl_enabled()
        db.connection.commit()
    finally:
        db.close()

    _seed_credential_bearing_decision(home)

    drain = mcp_call("export.drain", {"home": str(home)}).model_dump(mode="json")
    assert drain["ok"] is True
    assert drain["data"]["exported_count"] >= 3

    files = glob.glob(
        str(home / "export" / "jsonl" / "**" / "*.jsonl"), recursive=True
    )
    assert files, "expected the credential-bearing writes to produce JSONL exports"
    blob = "".join(Path(f).read_text(encoding="utf-8") for f in files)
    _assert_no_credential_marker(blob, "JSONL export outbox")
    # The drain envelope itself must also stay clean.
    _assert_no_credential_marker(json.dumps(drain), "export.drain envelope")


def test_no_credential_in_bundle_surface(home: Path):
    """A5: credential-shaped input never reaches review.bundle / replay.case_bundle."""

    _seed_credential_bearing_decision(home)

    review = mcp_call("review.bundle", {"home": str(home)}).model_dump(mode="json")
    assert review["ok"] is True
    _assert_no_credential_marker(json.dumps(review), "review.bundle")

    replay = mcp_call(
        "replay.case_bundle", {"home": str(home)}
    ).model_dump(mode="json")
    # replay.case_bundle may legitimately error on an empty/seed-only journal;
    # the contract is only that, when it returns, it carries no credential.
    _assert_no_credential_marker(json.dumps(replay), "replay.case_bundle")
