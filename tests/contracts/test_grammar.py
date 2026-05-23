"""actor_id and idempotency_key grammar enforcement per PRD §2 (trade-trace-3mp)."""

from __future__ import annotations

import json

import pytest

from trade_trace import core as _core_module
from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.grammar import (
    validate_actor_id,
    validate_idempotency_key,
)
from trade_trace.core import dispatch
from trade_trace.tools.errors import ToolError

# -- actor_id positive cases ----------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "agent:default",
        "cli:user",
        "import:csv-fills",
        "system:report.coach",
        "agent:polymarket-scout",
        "import:polymarket-csv-2026-05",
        "agent:a",  # min length
        "agent:" + "a" * 64,  # max length
    ],
)
def test_valid_actor_id_accepted(value: str):
    assert validate_actor_id(value) == value


# -- actor_id negative cases ----------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "foo:bar",  # bad role
        ":default",  # empty role
        "agent",  # missing colon
        "agent:",  # missing name
        "agent: leading-space",  # space
        "agent:-leading-dash",  # name must start with [A-Za-z0-9]
        "agent:" + "a" * 65,  # too long
        "agent:has spaces",
        "agent:tab\there",
        "AGENT:Mixed",  # uppercase role rejected
    ],
)
def test_invalid_actor_id_rejected(value: str):
    with pytest.raises(ToolError) as exc:
        validate_actor_id(value)
    assert exc.value.code == ErrorCode.VALIDATION_ERROR
    assert exc.value.details["field"] == "actor_id"
    assert "expected_format" in exc.value.details


def test_dispatch_rejects_invalid_actor_id():
    """Validation runs at the dispatcher boundary — the tool handler never
    sees a malformed actor."""

    envelope = dispatch("journal.status", {}, actor_id="not-an-actor")
    body = envelope.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["field"] == "actor_id"


# -- idempotency_key positive cases ---------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "decision-2026-05-18T14:32:00Z-abc123",
        "_abc.def-XYZ",
        "a",  # min length
        "a" * 128,  # max length
        "ABC:def-123_xyz.foo",
        "  trim-me  ",  # leading/trailing whitespace tolerated and trimmed
    ],
)
def test_valid_idempotency_key_accepted(value: str):
    out = validate_idempotency_key(value)
    assert out is not None
    assert out == value.strip()


def test_idempotency_key_none_passes_through():
    assert validate_idempotency_key(None) is None


# -- idempotency_key negative cases ---------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "",  # empty after no-trim
        "   ",  # empty after trim
        "has spaces",
        "tab\tinside",
        "a" * 129,  # too long
        "bad/char",  # `/` outside allowed set
        "bad?char",
        "smiley☃",  # non-ASCII
    ],
)
def test_invalid_idempotency_key_rejected(value: str):
    with pytest.raises(ToolError) as exc:
        validate_idempotency_key(value)
    assert exc.value.code == ErrorCode.VALIDATION_ERROR
    assert exc.value.details["field"] == "idempotency_key"


def test_idempotency_key_non_string_rejected():
    with pytest.raises(ToolError):
        validate_idempotency_key(123)  # type: ignore[arg-type]


# -- write-path grammar enforcement ---------------------------------------


def test_write_path_rejects_malformed_actor(tmp_path):
    """An EventWriter.write() call with a bad actor_id raises ToolError too,
    so the grammar is enforced regardless of which path called write."""

    from trade_trace.events import EventWriter
    from trade_trace.storage import apply_pending_migrations, open_database
    from trade_trace.storage.paths import db_path

    db = open_database(db_path(tmp_path / "home"))
    try:
        apply_pending_migrations(db.connection)
        writer = EventWriter(db.connection)
        with pytest.raises(ToolError) as exc:
            writer.write(
                event_type="decision.created",
                subject_kind="decision",
                subject_id="d_1",
                payload={"instrument_id": "i_1", "type": "skip"},
                actor_id="badactor",  # missing role
                idempotency_key="abc",
            )
        assert exc.value.details["field"] == "actor_id"
    finally:
        db.close()


def test_write_path_rejects_malformed_idempotency_key(tmp_path):
    from trade_trace.events import EventWriter
    from trade_trace.storage import apply_pending_migrations, open_database
    from trade_trace.storage.paths import db_path

    db = open_database(db_path(tmp_path / "home"))
    try:
        apply_pending_migrations(db.connection)
        writer = EventWriter(db.connection)
        with pytest.raises(ToolError) as exc:
            writer.write(
                event_type="decision.created",
                subject_kind="decision",
                subject_id="d_1",
                payload={"instrument_id": "i_1", "type": "skip"},
                actor_id="agent:default",
                idempotency_key="has spaces",
            )
        assert exc.value.details["field"] == "idempotency_key"
    finally:
        db.close()


def test_allow_no_idempotency_meta_flag_via_dispatch():
    """Passing `_allow_no_idempotency: true` in args surfaces
    meta.idempotency_disabled=true on the response — the contract surface
    PRD §2 promises for the opt-out path."""

    envelope = dispatch(
        "journal.status",
        {"_allow_no_idempotency": True},
        actor_id="agent:default",
    )
    body = envelope.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    assert body["meta"].get("idempotency_disabled") is True


def test_cli_allow_no_idempotency_sets_meta_flag(capsys):
    """`tt --allow-no-idempotency journal status` surfaces the meta flag."""

    from trade_trace.cli import main as cli_main

    rc = cli_main(["--allow-no-idempotency", "journal", "status"])
    out = capsys.readouterr()
    assert rc == 0
    body = json.loads(out.out.strip().splitlines()[-1])
    assert body["meta"]["idempotency_disabled"] is True


def test_write_path_trims_whitespace_on_idempotency_key(tmp_path):
    """Per PRD §2 grammar block: 'server compares post-trim, case-sensitive'.
    Two writes with the same key but different surrounding whitespace must
    replay as the same logical key."""

    from trade_trace.events import EventWriter
    from trade_trace.storage import apply_pending_migrations, open_database
    from trade_trace.storage.paths import db_path

    db = open_database(db_path(tmp_path / "home"))
    try:
        apply_pending_migrations(db.connection)
        writer = EventWriter(db.connection)
        first = writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload={"instrument_id": "i_1", "type": "skip"},
            actor_id="agent:default",
            idempotency_key="abc",
        )
        second = writer.write(
            event_type="decision.created",
            subject_kind="decision",
            subject_id="d_1",
            payload={"instrument_id": "i_1", "type": "skip"},
            actor_id="agent:default",
            idempotency_key="  abc  ",  # whitespace gets trimmed
        )
        assert second.id == first.id
        assert second.idempotent_replay is True
    finally:
        db.close()



# -- write-tool idempotency_key enforcement (trade-trace-cpz2) ------------


@pytest.mark.strict_idempotency
def test_dispatch_rejects_write_without_idempotency_key(tmp_path):
    """A retryable write tool called without `idempotency_key` and without
    the `_allow_no_idempotency` opt-in must fail at the dispatch boundary
    with VALIDATION_ERROR and `details.field == "idempotency_key"`. Before
    this enforcement, the M1 ledger tools tolerated missing keys despite
    docs/schema advertising the opposite (trade-trace-cpz2).

    Per bead trade-trace-t7hi, write tools whose semantic identity is
    in `TOOL_PRIMARY_EVENT_TYPE` get an auto-derived key instead of a
    rejection. This test uses `journal.backup` — an administrative
    capability that is intentionally excluded from auto-derivation —
    so the strict cpz2 rejection path stays exercised.
    """

    home = tmp_path / "home"
    init = _core_module.dispatch("journal.init", {"home": str(home)}, actor_id="agent:default")
    assert init.ok is True

    envelope = _core_module.dispatch(
        "journal.backup",
        {"home": str(home), "dest": str(tmp_path / "backup"), "_confirm": True},
        actor_id="agent:default",
    )
    body = envelope.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["field"] == "idempotency_key"
    assert body["error"]["details"]["auto_derivation_available"] is False


@pytest.mark.strict_idempotency
def test_dispatch_accepts_write_with_explicit_opt_out(tmp_path):
    """The `_allow_no_idempotency: true` escape hatch for batch importers and
    admin tools accepts a missing key AND surfaces `meta.idempotency_disabled
    = true` so agents can branch on at-least-once semantics."""

    home = tmp_path / "home"
    _core_module.dispatch("journal.init", {"home": str(home)}, actor_id="agent:default")

    envelope = _core_module.dispatch(
        "venue.add",
        {
            "home": str(home),
            "name": "OptOut",
            "kind": "manual",
            "_allow_no_idempotency": True,
        },
        actor_id="agent:default",
    )
    body = envelope.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    assert body["meta"].get("idempotency_disabled") is True


@pytest.mark.strict_idempotency
def test_dispatch_accepts_write_with_idempotency_key(tmp_path):
    """The strict default path: a supplied key succeeds and the response
    envelope does NOT carry meta.idempotency_disabled."""

    home = tmp_path / "home"
    _core_module.dispatch("journal.init", {"home": str(home)}, actor_id="agent:default")

    envelope = _core_module.dispatch(
        "venue.add",
        {
            "home": str(home),
            "name": "WithKey",
            "kind": "manual",
            "idempotency_key": "cpz2:venue:withkey:v1",
        },
        actor_id="agent:default",
    )
    body = envelope.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    assert "idempotency_disabled" not in body["meta"]


@pytest.mark.strict_idempotency
def test_cli_rejects_write_without_idempotency_key(tmp_path, capsys):
    """CLI parity: an administrative write tool that is intentionally
    out of the auto-derivation registry (`journal.backup` here per
    bead trade-trace-t7hi) still requires `--idempotency-key` or
    `--allow-no-idempotency`."""

    from trade_trace.cli import main as cli_main

    home = tmp_path / "home"
    rc_init = cli_main([
        "--actor-id", "agent:default",
        "journal", "init",
        "--home", str(home),
    ])
    assert rc_init == 0
    capsys.readouterr()

    rc = cli_main([
        "--actor-id", "agent:default",
        "journal", "backup",
        "--home", str(home),
        "--dest", str(tmp_path / "backup"),
        "--confirm",
    ])
    out = capsys.readouterr().out.strip().splitlines()[-1]
    body = json.loads(out)
    assert rc == 2  # VALIDATION_ERROR maps to exit 2
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["field"] == "idempotency_key"


@pytest.mark.strict_idempotency
def test_cli_accepts_write_with_allow_no_idempotency(tmp_path, capsys):
    """CLI parity: `tt --allow-no-idempotency venue add` succeeds with
    `meta.idempotency_disabled=true`."""

    from trade_trace.cli import main as cli_main

    home = tmp_path / "home"
    cli_main([
        "--actor-id", "agent:default",
        "journal", "init",
        "--home", str(home),
    ])
    capsys.readouterr()

    rc = cli_main([
        "--actor-id", "agent:default",
        "--allow-no-idempotency",
        "venue", "add",
        "--home", str(home),
        "--name", "OptOut",
        "--kind", "manual",
    ])
    out = capsys.readouterr().out.strip().splitlines()[-1]
    body = json.loads(out)
    assert rc == 0
    assert body["ok"] is True
    assert body["meta"]["idempotency_disabled"] is True
