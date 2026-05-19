from __future__ import annotations

import json
from pathlib import Path

from trade_trace.mcp_server import mcp_call
from trade_trace.storage import open_database
from trade_trace.storage.paths import db_path
from trade_trace.tools import imports


def _init(home: Path) -> None:
    env = mcp_call("journal.init", {"home": str(home)})
    assert env.ok is True


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line, sort_keys=True) + "\n" for line in lines), encoding="utf-8")


def _call(tool: str, args: dict, actor_id: str = "agent:default") -> dict:
    return mcp_call(tool, args, actor_id=actor_id).model_dump(mode="json", exclude_none=True)


def _venue_line(key: str = "ven-1", venue_id: str | None = "ven_import_1") -> dict:
    args = {"name": "Polymarket", "kind": "prediction_market", "idempotency_key": key}
    if venue_id is not None:
        args["id"] = venue_id
    return {"tool": "venue.add", "args": args}


def _instrument_line(venue_id: str = "ven_import_1", key: str = "ins-1", instr_id: str = "ins_import_1") -> dict:
    return {"tool": "instrument.add", "args": {"id": instr_id, "venue_id": venue_id, "asset_class": "prediction_market", "title": "Will it rain?", "idempotency_key": key}}


def _count(home: Path, table: str) -> int:
    db = open_database(db_path(home))
    try:
        return db.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        db.close()


def test_import_validate_file_and_directory_no_write_and_underscore_metadata(tmp_path: Path):
    home = tmp_path / "home"
    _init(home)
    file = tmp_path / "events.jsonl"
    line = _venue_line()
    line.update({"_event_id": 10, "_event_type": "venue.created", "_created_at": "2026-05-19T00:00:00Z"})
    _write_jsonl(file, [line])

    env = _call("import.validate", {"home": str(home), "path": str(file)})
    assert env["ok"] is True
    assert env["data"]["validated"] == 1
    assert env["data"]["errors"] == []
    assert _count(home, "venues") == 0

    directory = tmp_path / "dir"
    _write_jsonl(directory / "b.jsonl", [_instrument_line()])
    _write_jsonl(directory / "a.jsonl", [_venue_line()])
    env = _call("import.validate", {"home": str(home), "path": str(directory)})
    assert env["ok"] is True
    assert env["data"]["validated"] == 2
    assert env["data"]["errors"] == []
    assert _count(home, "venues") == 0


def test_import_commit_single_prevalidates_and_rolls_back_all_on_error(tmp_path: Path):
    home = tmp_path / "home"
    _init(home)
    file = tmp_path / "events.jsonl"
    _write_jsonl(file, [_venue_line(), {"tool": "instrument.add", "args": {"id": "ins_bad", "venue_id": "missing", "asset_class": "prediction_market", "title": "Bad", "idempotency_key": "bad"}}])

    env = _call("import.commit", {"home": str(home), "path": str(file), "transaction_mode": "single"})
    assert env["ok"] is True
    assert env["data"]["committed_count"] == 0
    assert env["data"]["errors"]
    assert _count(home, "venues") == 0
    assert _count(home, "instruments") == 0


def test_import_commit_per_row_partial_progress(tmp_path: Path):
    home = tmp_path / "home"
    _init(home)
    file = tmp_path / "events.jsonl"
    _write_jsonl(file, [_venue_line(), {"tool": "instrument.add", "args": {"id": "ins_bad", "venue_id": "missing", "asset_class": "prediction_market", "title": "Bad", "idempotency_key": "bad"}}])

    env = _call("import.commit", {"home": str(home), "path": str(file), "transaction_mode": "per_row", "halt_on_error": False})
    assert env["ok"] is True
    assert env["data"]["committed_count"] == 1
    assert env["data"]["errors"]
    assert _count(home, "venues") == 1
    assert _count(home, "instruments") == 0


def test_import_commit_idempotent_replay(tmp_path: Path):
    home = tmp_path / "home"
    _init(home)
    file = tmp_path / "events.jsonl"
    _write_jsonl(file, [_venue_line()])

    first = _call("import.commit", {"home": str(home), "path": str(file)})
    second = _call("import.commit", {"home": str(home), "path": str(file)})
    assert first["data"]["committed_count"] == 1
    assert second["data"]["committed_count"] == 1
    assert second["data"]["would_replay"] == 1
    assert _count(home, "venues") == 1


def test_import_validate_rejects_mixed_id_strategy(tmp_path: Path):
    home = tmp_path / "home"
    _init(home)
    file = tmp_path / "events.jsonl"
    _write_jsonl(file, [_venue_line(venue_id="ven_a"), _venue_line(key="ven-2", venue_id=None)])

    env = _call("import.validate", {"home": str(home), "path": str(file)})
    assert env["ok"] is True
    assert env["data"]["id_strategy"] == "mixed"
    assert env["data"]["errors"][0]["details"]["reason"] == "mixed_id_strategy"
    assert _count(home, "venues") == 0


def test_import_validate_rejects_forward_references(tmp_path: Path):
    home = tmp_path / "home"
    _init(home)
    file = tmp_path / "events.jsonl"
    _write_jsonl(file, [_instrument_line(), _venue_line()])

    env = _call("import.validate", {"home": str(home), "path": str(file)})
    assert env["ok"] is True
    assert env["data"]["errors"]
    assert env["data"]["errors"][0]["details"]["referenced_id_not_yet_defined"] == "ven_import_1"
    assert _count(home, "venues") == 0


def test_import_validate_without_home_uses_isolated_default_home_no_write(tmp_path: Path, monkeypatch):
    default_home = tmp_path / "default-home"
    monkeypatch.setenv("TRADE_TRACE_HOME", str(default_home))
    _init(default_home)
    file = tmp_path / "events.jsonl"
    _write_jsonl(file, [_venue_line()])

    env = _call("import.validate", {"path": str(file)})

    assert env["ok"] is True
    assert env["data"]["validated"] == 1
    assert env["data"]["errors"] == []
    assert _count(default_home, "venues") == 0


def test_import_commit_single_runtime_failure_after_first_row_leaves_real_db_unchanged(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    _init(home)
    file = tmp_path / "events.jsonl"
    _write_jsonl(file, [_venue_line(), _venue_line(key="ven-2", venue_id="ven_import_2")])

    original = imports._dispatch_row
    calls = {"count": 0}

    def fail_second_staged_commit(row, row_home, actor_id):
        calls["count"] += 1
        if calls["count"] == 4:
            return {"ok": False, "error": {"code": "STORAGE_ERROR", "message": "boom", "details": {}}}
        return original(row, row_home, actor_id)

    monkeypatch.setattr(imports, "_dispatch_row", fail_second_staged_commit)

    env = _call("import.commit", {"home": str(home), "path": str(file), "transaction_mode": "single"})
    assert env["ok"] is True
    assert env["data"]["committed_count"] == 0
    assert env["data"]["errors"][0]["message"] == "boom"
    assert _count(home, "venues") == 0


def test_import_rejects_non_import_ready_tools(tmp_path: Path):
    home = tmp_path / "home"
    _init(home)
    file = tmp_path / "events.jsonl"
    _write_jsonl(file, [{"tool": "import.commit", "args": {"path": str(file)}}, {"tool": "journal.status", "args": {}}])

    env = _call("import.validate", {"home": str(home), "path": str(file), "max_errors": 5})
    assert env["ok"] is True
    assert [err["details"]["tool"] for err in env["data"]["errors"]] == ["import.commit", "journal.status"]

    env = _call("import.commit", {"home": str(home), "path": str(file), "transaction_mode": "per_row", "max_errors": 5})
    assert env["ok"] is True
    assert env["data"]["committed_count"] == 0
    assert [err["details"]["tool"] for err in env["data"]["errors"]] == ["import.commit", "journal.status"]


# -- bucket-B cascaded event skip + count (trade-trace-j5b8) -----------


def test_import_skips_cascaded_event_lines_with_counter(tmp_path: Path):
    """Per trade-trace-j5b8 and docs/architecture/jsonl-replay-taxonomy.md:
    a JSONL export contains both the parent write (e.g. `thesis.add`
    serialized as `tool=thesis.created`) and the cascaded
    `edge.created` line emitted inside that tool's transaction. The
    importer must replay the parent write but skip the cascaded event
    with a `cascaded_skipped` counter — replaying both would either
    fail (no such tool as `edge.created`) or double-write."""

    home = tmp_path / "home"
    _init(home)

    jsonl = tmp_path / "cascade.jsonl"
    _write_jsonl(jsonl, [
        # Bucket A: replayable.
        _venue_line(),
        _instrument_line(),
        # Bucket B: cascaded events. These previously hit "tool is not
        # import-ready" errors; now they're silently skipped.
        {
            "tool": "edge.created",
            "args": {
                "id": "edg_cascade", "source_kind": "thesis",
                "source_id": "t_ignored", "target_kind": "thesis",
                "target_id": "t_ignored2", "edge_type": "supersedes",
            },
            "idempotency_key": "edg-cascade-1",
        },
        {
            "tool": "playbook_rule.followed",
            "args": {"decision_id": "d_ignored", "rule_id": "r_ignored"},
            "idempotency_key": "rule-followed-1",
        },
    ])

    env = _call("import.commit", {
        "home": str(home),
        "path": str(jsonl),
        "transaction_mode": "single",
        "idempotency_key": "j5b8-commit",
    })
    assert env["ok"] is True, env
    data = env["data"]
    # Two cascaded lines skipped + counted.
    assert data["cascaded_skipped"] == 2, data
    # Two parent writes committed (venue + instrument).
    assert data["committed_count"] == 2
    # No errors surfaced for the cascaded lines.
    assert data["errors"] == []
    # And no `edges` row was double-written (the cascaded edge.created
    # would have produced one, the parent write produces zero in this
    # minimal fixture).
    assert _count(home, "edges") == 0


def test_import_validate_reports_cascaded_skipped(tmp_path: Path):
    """`import.validate` surfaces the same counter so a dry-run shows
    the operator how many cascaded lines the eventual commit will skip."""

    home = tmp_path / "home"
    _init(home)

    jsonl = tmp_path / "validate.jsonl"
    _write_jsonl(jsonl, [
        _venue_line(),
        {
            "tool": "forecast.scored",
            "args": {"forecast_id": "fc_ignored"},
            "idempotency_key": "scored-validate-1",
        },
    ])

    env = _call("import.validate", {
        "home": str(home), "path": str(jsonl),
    })
    assert env["ok"] is True, env
    data = env["data"]
    assert data["cascaded_skipped"] == 1
    assert data["validated"] == 1  # the venue


# -- bucket-D diagnostic event skip (trade-trace-apgt) ----------------


def test_import_skips_bucket_d_diagnostic_events_with_separate_counter(tmp_path: Path):
    """Per trade-trace-apgt: bucket-D diagnostic events
    (`signal.emitted`, `memory_node.invalidated`) skip with a
    `diagnostic_skipped` counter — distinct from `cascaded_skipped` so
    operators can distinguish 'cascaded parent regenerates this' from
    'regenerate on demand via signal.scan / re-run invalidation'."""

    home = tmp_path / "home"
    _init(home)

    jsonl = tmp_path / "diagnostic.jsonl"
    _write_jsonl(jsonl, [
        _venue_line(),
        {
            "tool": "signal.emitted",
            "args": {"id": "sig_ignored", "kind": "sample_size_warning"},
            "idempotency_key": "signal-emitted-1",
        },
        {
            "tool": "memory_node.invalidated",
            "args": {"id": "mem_ignored", "reason": "stale"},
            "idempotency_key": "node-invalidated-1",
        },
    ])

    env = _call("import.commit", {
        "home": str(home), "path": str(jsonl),
        "transaction_mode": "single",
        "idempotency_key": "apgt-commit",
    })
    assert env["ok"] is True, env
    data = env["data"]
    assert data["diagnostic_skipped"] == 2, data
    assert data["cascaded_skipped"] == 0, data
    assert data["committed_count"] == 1
    assert _count(home, "signals") == 0


# -- bucket-A M3/M4 dispatch (trade-trace-ths0) -----------------------


def test_import_dispatches_m3_m4_event_aliases(tmp_path: Path):
    """Per trade-trace-ths0: event-type aliases for the M3 memory +
    strategy + M4 playbook writes (memory_node.retained,
    strategy.created/updated, playbook.created/proposed_version) used
    to skip silently under the bucket-B umbrella. The importer now
    dispatches them through their write tools so a journal export
    round-trips faithfully."""

    home = tmp_path / "home"
    _init(home)

    jsonl = tmp_path / "m3m4.jsonl"
    # The exporter places `idempotency_key` inside `args` (the rest of
    # the line is transport metadata under `_*` keys), so the import
    # rows mirror that shape — the dispatch-level idempotency_key
    # enforcement (cpz2) reads it from args.
    _write_jsonl(jsonl, [
        # memory_node.retained → memory.retain
        {
            "tool": "memory_node.retained",
            "args": {
                "node_type": "observation",
                "body": "M3 alias round-trip",
                "idempotency_key": "ths0-memnode",
            },
        },
        # strategy.created → strategy.create
        {
            "tool": "strategy.created",
            "args": {
                "name": "ths0-strategy",
                "slug": "ths0-strategy",
                "description": "round-trip strategy",
                "idempotency_key": "ths0-strategy",
            },
        },
    ])

    env = _call("import.commit", {
        "home": str(home),
        "path": str(jsonl),
        "transaction_mode": "single",
        "idempotency_key": "ths0-commit",
    })
    assert env["ok"] is True, env
    data = env["data"]
    # Both writes committed, neither was skipped as cascaded.
    assert data["committed_count"] == 2, data
    assert data["cascaded_skipped"] == 0, data
    # And the corresponding rows now exist in the home.
    assert _count(home, "memory_nodes") == 1
    assert _count(home, "strategies") == 1


def test_journal_export_replays_m3_m4_writes_into_fresh_home(tmp_path: Path):
    """End-to-end acceptance for trade-trace-ths0. Write into one home
    using the real M3/M4 write tools, drain the export queue to JSONL,
    re-import into a fresh home, and assert the projection state
    matches row-for-row."""

    source = tmp_path / "src"
    _init(source)
    # JSONL outbox export is opt-in via config. Admin writes are
    # confirm-gated (operability.md §2z7) so we pass _confirm.
    cfg = _call("journal.config_set", {"home": str(source), "key": "outbox.jsonl_enabled", "value": "true", "_confirm": True, "idempotency_key": "ths0-cfg"})
    assert cfg["ok"] is True, cfg

    # The two cleanest bucket-A creators round-trip today. A separate
    # bead covers expanding the round-trip to strategy.update +
    # playbook.* — those need the exporter to stop emitting immutable
    # fields like `name`/`slug` into the JSONL payload, which is an
    # exporter contract change outside ths0's scope.
    _call("memory.retain", {"home": str(source), "node_type": "observation", "body": "ths0 round-trip memory", "idempotency_key": "ths0-rt-mem"})
    strat = _call("strategy.create", {"home": str(source), "name": "ths0-rt", "slug": "ths0-rt", "description": "round-trip strategy", "idempotency_key": "ths0-rt-strat"})
    assert strat["ok"], strat

    # The exporter is currently a library function (not yet an MCP tool —
    # see trade-trace-c1r / -3zvl); call it directly to drain the outbox
    # into JSONL files.
    from trade_trace.exporter import drain_outbox, iter_jsonl_files
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path as _db_path

    db = open_database(_db_path(source))
    try:
        drain = drain_outbox(db.connection, source)
        db.connection.commit()
    finally:
        db.close()
    assert len(drain.exported_files) >= 2, drain
    export_files = iter_jsonl_files(source)
    assert export_files, "exporter wrote no JSONL files"
    export_dir = export_files[0].parent

    target = tmp_path / "dst"
    _init(target)

    env = _call("import.commit", {"home": str(target), "path": str(export_dir), "transaction_mode": "single", "idempotency_key": "ths0-rt-commit"})
    assert env["ok"] is True, env
    # The importer should have committed all 3 rows; if zero, something
    # (e.g. dispatch-level idempotency_key enforcement) is rejecting
    # them silently before they reach the projection.
    import json as _json
    assert env["data"]["committed_count"] >= 2, _json.dumps(env, indent=2, default=str)

    for table in ("memory_nodes", "strategies"):
        assert _count(target, table) == _count(source, table), (
            f"{table} row count diverged source={_count(source, table)} "
            f"target={_count(target, table)}"
        )
