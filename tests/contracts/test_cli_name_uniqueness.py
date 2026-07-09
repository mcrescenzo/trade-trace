"""CLI name-collision detection per contracts.md §2.1.

Two MCP tool names cannot map to the same CLI invocation. Detection runs at
registration time AND at process startup AND in CI via this test.
"""

from __future__ import annotations

import pytest

from trade_trace.contracts.tool_registry import (
    CLINameCollisionError,
    ToolRegistration,
    ToolRegistry,
    cli_invocation_for,
)
from trade_trace.core import build_registry


def _noop(args, ctx):  # pragma: no cover - fixture only
    return {}


def test_dot_to_space_mapping():
    assert cli_invocation_for("decision.add") == ("decision", "add")
    assert cli_invocation_for("report.calibration") == ("report", "calibration")
    assert cli_invocation_for("journal.rebuild_projections") == (
        "journal",
        "rebuild_projections",
    )


def test_collision_detected_via_validate():
    """Inject two distinct registrations whose CLI invocations collide and
    confirm validate() catches them. This is the defense-in-depth path that
    runs at every process startup.
    """

    reg = ToolRegistry()
    reg.register("decision.add", _noop)
    # Build a colliding registration with a different `name` but the same
    # invocation tuple — possible only via direct registry manipulation,
    # which would only happen if a future custom transport added a registry
    # entry without going through `register()`. The startup validate() must
    # catch it.
    impostor = ToolRegistration(
        name="decision.foo",
        cli_invocation=("decision", "add"),
        handler=_noop,
    )
    reg.by_name["decision.foo"] = impostor
    with pytest.raises(CLINameCollisionError) as exc:
        reg.validate()
    assert ("decision.add", "decision.foo") in exc.value.colliding or (
        "decision.foo",
        "decision.add",
    ) in exc.value.colliding


def test_double_registration_raises():
    """Calling `register` twice for the same name is also an error.

    The error must be CLINameCollisionError (with conflict_kind=duplicate_name)
    rather than a generic ValueError so callers can branch on a single typed
    exception."""

    reg = ToolRegistry()
    reg.register("decision.add", _noop)
    with pytest.raises(CLINameCollisionError) as exc:
        reg.register("decision.add", _noop)
    assert exc.value.conflict_kind == "duplicate_name"
    assert exc.value.suggested_renames[0]["suggested_rename"] == "decision.add_alt"


def test_injected_duplicate_invocation_during_register():
    """Two distinct dotted names whose CLI invocations collide must be caught
    at `register()` time, before they reach the runtime registry."""

    reg = ToolRegistry()
    reg.register("report.calibration", _noop)
    # Same invocation tuple — should be impossible by construction because
    # we tokenize at registration time. But test the guard works if someone
    # subclasses and overrides `cli_invocation_for`.
    # Inject a registration with the same tuple but different name; the guard
    # in `register()` for `prior != name` catches it.
    reg.by_cli[("report", "calibration_alias")] = "report.calibration"
    with pytest.raises(CLINameCollisionError) as exc:
        # This tries to register a new name whose computed CLI tokens match
        # an existing entry we manually injected.
        reg.register("report.calibration_alias", _noop)
    assert exc.value.conflict_kind == "duplicate_invocation"


def test_cli_main_emits_storage_error_envelope_on_collision(monkeypatch, capsys):
    """When the registry construction itself fails with a collision, the CLI
    must emit a STORAGE_ERROR envelope to stdout (not a Python traceback) and
    exit non-zero."""

    from trade_trace.cli import main as cli_main

    def _broken_registry() -> ToolRegistry:
        reg = ToolRegistry()
        reg.register("decision.add", _noop)
        # Now inject a collision and force a re-validate at first use.
        reg.by_name["decision.duplicate"] = ToolRegistration(
            name="decision.duplicate",
            cli_invocation=("decision", "add"),
            handler=_noop,
        )
        reg.validate()  # this raises
        return reg

    monkeypatch.setattr("trade_trace.cli.default_registry", _broken_registry, raising=True)
    rc = cli_main(["journal", "status"])
    out = capsys.readouterr()
    assert rc == 1
    # stdout must be the envelope, not a traceback
    parsed = next(
        (
            __import__("json").loads(line)
            for line in out.out.strip().splitlines()
            if line.startswith("{")
        ),
        None,
    )
    assert parsed is not None
    assert parsed["ok"] is False
    assert parsed["error"]["code"] == "STORAGE_ERROR"
    assert parsed["error"]["details"]["reason"] == "cli_name_collision"
    assert "decision.add" in {
        entry["tool_a"] for entry in parsed["error"]["details"]["colliding"]
    } | {entry["tool_b"] for entry in parsed["error"]["details"]["colliding"]}


def test_runtime_registry_validates_clean():
    """The production registry must construct cleanly at every startup."""

    reg = build_registry()
    # journal.status MUST be present at M0
    assert "journal.status" in reg.by_name
    assert reg.by_cli[("journal", "status")] == "journal.status"
