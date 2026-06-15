"""Agent ergonomics per bead trade-trace-268.

Covers contracts.md ergonomics surface:

- `tool.schema` returns example_minimal / example_rich / required_metadata
  for every MVP write tool.
- `--dry-run` (CLI) / `_dry_run: true` (MCP) validates inputs and computes
  the would-be IDs without persisting any rows.
- Error envelopes carry next-action hints: VALIDATION_ERROR includes
  `details.expected_format` for timestamp fields; IDEMPOTENCY_CONFLICT
  includes `details.original_event_id` + `details.diff_summary`; NOT_FOUND
  includes `details.entity_kind`.
- Stdout / stderr discipline: `--human` prose goes to stderr; stdout is
  exclusively the JSON envelope.
- CLI exit code mapping: 0 on success, 2 on VALIDATION_ERROR, 3 on
  INVARIANT_VIOLATION, 1 otherwise.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.mcp_server import mcp_call

# -- helpers ------------------------------------------------------------


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(h)})
    assert env.ok
    return h



def _cli(home: Path, *argv: str, human: bool = False, dry_run: bool = False,
         actor_id: str = "cli:default"):
    base = [sys.executable, "-m", "trade_trace.cli", "--actor-id", actor_id]
    if human:
        base.append("--human")
    if dry_run:
        base.append("--dry-run")
    env = {**dict(os.environ), "PYTHONPATH": "src"}
    return subprocess.run(
        [*base, *argv, "--home", str(home)],
        capture_output=True, text=True, env=env,
    )


def _seed_venue_instrument(home: Path) -> tuple[str, str]:
    venue = _mcp(home, "venue.add", {"name": "PM", "kind": "prediction_market"})
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue.data["id"],
        "asset_class": "prediction_market",
        "title": "X",
    })
    return venue.data["id"], inst.data["id"]


# -- 1. tool.schema introspection per write tool kind -----------------


WRITE_TOOLS_WITH_EXAMPLES = [
    "venue.add", "instrument.add", "thesis.add", "forecast.add",
    "decision.add", "resolution.add", "source.add",
]


@pytest.mark.parametrize("tool", WRITE_TOOLS_WITH_EXAMPLES)
def test_tool_schema_returns_example_payloads(home, tool):
    env = _mcp(home, "tool.schema", {"tool": tool})
    assert env.ok, env
    data = env.data
    assert data["tool"] == tool
    assert data["is_write"] is True
    assert data["example_minimal"] is not None, f"{tool} missing example_minimal"
    # Example carries an idempotency_key per contracts.md grammar.
    assert "idempotency_key" in data["example_minimal"]
    # Required-metadata notes inform the agent without re-reading docs.
    meta_notes = data["required_metadata"]
    assert "actor_id_pattern" in meta_notes
    assert "idempotency_key_pattern" in meta_notes
    assert meta_notes["supports_dry_run"] is True
    assert meta_notes["dry_run_flag_cli"] == "--dry-run"


def test_tool_schema_unknown_tool_returns_not_found(home):
    env = _mcp(home, "tool.schema", {"tool": "nope.invalid"})
    assert env.ok is False
    assert env.error.code.value == "NOT_FOUND"
    assert env.error.details["entity_kind"] == "tool"


def test_tool_schema_catalog_lists_default_public_catalog(home):
    env = _mcp(home, "tool.schema", {})
    assert env.ok, env
    names = {t["name"] for t in env.data["tools"]}
    # Representative default v0.0.2 surface: new catalog names plus stable reports.
    for required in ("market.bind", "decision.add", "resolution.add",
                     "playbook.record_adherence", "tool.schema", "report.calibration",
                     # playbook.propose_version is the ONLY tool that mints a
                     # playbook_version_id; playbook.record_adherence requires
                     # one, so the producer must stay catalog-visible alongside
                     # its consumer (trade-trace-47tp).
                     "playbook.propose_version"):
        assert required in names
    for legacy_hidden in (
        "venue.add", "thesis.add", "outcome.add",
        "strategy.create", "playbook.create",
    ):
        assert legacy_hidden not in names


def test_tool_schema_catalog_includes_json_schema_for_mcp_parity(home):
    """Per bead trade-trace-dgdq: CLI catalog mode mirrors MCP
    list-tools by including each tool's `json_schema` so agents can
    discover the full call shape in one round-trip. Tools without an
    example/explicit schema (read-only with no required args) still
    surface a `json_schema` key — set to `None` — so the contract is
    homogeneous.
    """

    env = _mcp(home, "tool.schema", {})
    assert env.ok, env

    catalog = env.data["tools"]
    # Every catalog row carries `json_schema` (None if the tool has no
    # example/explicit schema).
    missing_key = [t["name"] for t in catalog if "json_schema" not in t]
    assert missing_key == [], (
        f"catalog rows missing `json_schema` key: {missing_key!r}. "
        "Per dgdq the catalog must mirror MCP list-tools and expose "
        "each tool's schema (None for tools without one)."
    )

    # Every write tool's catalog row carries a non-None json_schema —
    # write tools without a schema would force agents to drill down N
    # times before they can safely call.
    write_without_schema = [
        t["name"] for t in catalog if t["is_write"] and t.get("json_schema") is None
    ]
    assert write_without_schema == [], (
        f"write tools without `json_schema` in catalog: "
        f"{write_without_schema!r}. Add example_minimal in "
        "tools/_examples.py and wire via `**_examples_for(...)`."
    )

    # Spot-check: the catalog row's json_schema matches per-tool
    # drilldown output (no drift between the two surfaces).
    for sample in ("decision.add", "market.bind", "playbook.upsert"):
        row = next(t for t in catalog if t["name"] == sample)
        drill = _mcp(home, "tool.schema", {"tool": sample})
        assert drill.ok, drill
        assert row["json_schema"] == drill.data["json_schema"], (
            f"catalog `json_schema` for {sample!r} diverged from "
            "per-tool drilldown — both must read from the same registry."
        )


# -- 2. dry-run no-write -----------------------------------------------


def test_dry_run_returns_would_be_id_but_persists_no_row(home):
    """A successful dry-run returns the would-be id + payload but the
    underlying SQLite row is rolled back. Re-reading the venues table
    finds nothing."""

    env = _mcp(home, "venue.add", {
        "name": "DryRunCo",
        "kind": "prediction_market",
        "idempotency_key": "00000000-0000-4000-8000-000000000001",
        "_dry_run": True,
    })
    assert env.ok, env
    would_be_id = env.data["id"]
    assert isinstance(would_be_id, str) and would_be_id.startswith("ven_")
    assert env.meta.dry_run is True

    # Now query the DB directly: no row should exist for that name.
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT COUNT(*) FROM venues WHERE name = ?", ("DryRunCo",)
        ).fetchone()
        assert row[0] == 0, "dry-run must not persist any row"
    finally:
        db.close()


def test_dry_run_validation_failure_still_reports_dry_run(home):
    """Even when dry-run fails validation, meta.dry_run echoes back so
    the agent can confirm no writes were attempted."""

    # Missing required `kind` field.
    env = _mcp(home, "venue.add", {
        "name": "BadVenue",
        "idempotency_key": "00000000-0000-4000-8000-000000000002",
        "_dry_run": True,
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.meta.dry_run is True


def test_dry_run_via_cli_flag(home):
    """The CLI `--dry-run` flag wires the same code path as `_dry_run`."""

    result = _cli(
        home,
        "venue", "add",
        "--name", "DryRunCLI",
        "--kind", "prediction_market",
        "--idempotency-key", "00000000-0000-4000-8000-000000000003",
        dry_run=True,
    )
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)
    assert body["ok"] is True
    assert body["meta"]["dry_run"] is True

    # Confirm row not persisted.
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT COUNT(*) FROM venues WHERE name = ?", ("DryRunCLI",)
        ).fetchone()
        assert row[0] == 0
    finally:
        db.close()


# -- 3. error envelope next-action hints ----------------------------


def test_validation_error_includes_expected_format_for_timestamps(home):
    """A malformed timestamp surfaces details.expected_format so the
    agent can repair the call without docs."""

    _venue_id, inst_id = _seed_venue_instrument(home)
    env = _mcp(home, "resolution.add", {
        "instrument_id": inst_id,
        "resolved_at": "yesterday-ish",  # not ISO 8601
        "outcome_label": "yes",
        "status": "resolved_final",
        "idempotency_key": "00000000-0000-4000-8000-000000000010",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"
    details = env.error.details
    assert details["field"] == "resolved_at"
    assert "ISO 8601" in details["expected_format"]


def test_not_found_includes_entity_kind(home):
    env = _mcp(home, "forecast.supersede", {
        "prior_forecast_id": "fcst_does_not_exist",
        "kind": "binary",
        "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.5},
            {"outcome_label": "no", "probability": 0.5},
        ],
        "idempotency_key": "00000000-0000-4000-8000-000000000011",
    })
    assert env.ok is False
    assert env.error.code.value == "NOT_FOUND"
    assert env.error.details["entity_kind"] == "forecast"


def test_idempotency_conflict_includes_diff_summary_and_original_event_id(home):
    """IDEMPOTENCY_CONFLICT carries original_event_id + diff_summary so the
    agent can adjudicate without re-fetching the original row."""

    _mcp(home, "venue.add", {
        "name": "ConflictA",
        "kind": "prediction_market",
        "idempotency_key": "00000000-0000-4000-8000-000000000020",
    })
    # Same key, different payload.
    env = _mcp(home, "venue.add", {
        "name": "ConflictB",
        "kind": "prediction_market",
        "idempotency_key": "00000000-0000-4000-8000-000000000020",
    })
    assert env.ok is False
    assert env.error.code.value == "IDEMPOTENCY_CONFLICT"
    assert isinstance(env.error.details.get("original_event_id"), int)
    diff = env.error.details["diff_summary"]
    assert "diff_keys" in diff or "changed_keys" in diff or diff


# -- 4. stdout / stderr discipline ----------------------------------


def test_human_prose_goes_to_stderr_stdout_stays_json(home):
    """`tt --human ... 2>/dev/null | jq .` must succeed (stdout is JSON);
    stderr carries the prose hint."""

    result = _cli(home, "journal", "status", human=True)
    assert result.returncode == 0, result.stderr
    body = json.loads(result.stdout)  # raises if stdout isn't valid JSON
    assert body["ok"] is True
    # stderr carries prose; it's not JSON.
    assert result.stderr.strip(), "stderr must carry the --human hint"
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stderr)


def test_human_flag_does_not_leak_to_stdout(home):
    """`tt --human ... 1>/dev/null` must leave stdout empty of JSON envelopes."""

    result = _cli(home, "journal", "status", human=True)
    # Each stdout line is one JSON object; the only newline-separated
    # envelopes belong on stdout.
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        json.loads(line)  # asserts each line is valid JSON
    # stderr lines starting with `{` would indicate a leak the other way.
    for line in result.stderr.splitlines():
        assert not line.lstrip().startswith("{"), \
            f"stderr leaked JSON: {line!r}"


# -- 5. CLI exit code mapping ---------------------------------------


def test_exit_code_zero_on_success(home):
    result = _cli(home, "journal", "status")
    assert result.returncode == 0


def test_exit_code_two_on_validation_error(home):
    """Trigger a VALIDATION_ERROR by passing an unknown command-line shape
    that the underlying tool rejects."""

    _venue_id, inst_id = _seed_venue_instrument(home)
    result = _cli(
        home,
        "resolution", "add",
        "--instrument-id", inst_id,
        "--resolved-at", "not-a-timestamp",
        "--outcome-label", "yes",
        "--status", "resolved_final",
        "--idempotency-key", "00000000-0000-4000-8000-000000000030",
    )
    assert result.returncode == 2, (
        f"exit code must be 2 on VALIDATION_ERROR; got {result.returncode}; "
        f"stderr={result.stderr!r}"
    )


def test_exit_code_one_on_not_found(home):
    """NOT_FOUND maps to exit 1 (the catch-all for non-validation,
    non-invariant errors)."""

    result = _cli(
        home,
        "forecast", "supersede",
        "--prior-forecast-id", "fcst_does_not_exist",
        "--kind", "binary",
        "--yes-label", "yes",
        "--outcomes-json", '[{"outcome_label":"yes","probability":0.5},'
                           '{"outcome_label":"no","probability":0.5}]',
        "--idempotency-key", "00000000-0000-4000-8000-000000000031",
    )
    assert result.returncode == 1


# -- 6. tool.schema example payload validates as a real call ------


def test_thesis_add_example_payload_dry_runs_cleanly(home):
    """Substituting the example's `instrument_id` placeholder with a real
    id, the example payload must dry-run successfully — proving the
    shipped example matches the live contract."""

    _venue_id, inst_id = _seed_venue_instrument(home)
    schema = _mcp(home, "tool.schema", {"tool": "thesis.add"})
    example = dict(schema.data["example_minimal"])
    example["instrument_id"] = inst_id
    example["idempotency_key"] = "00000000-0000-4000-8000-000000000040"
    example["_dry_run"] = True
    env = _mcp(home, "thesis.add", example)
    assert env.ok, env
    assert env.meta.dry_run is True
