"""`import.validate` / `import.commit` JSONL replay importer."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.exporter import strip_transport_keys
from trade_trace.storage.paths import db_path, resolve_home
from trade_trace.tools.errors import ToolError


class ImportJSONLLine(BaseModel):
    """The canonical line shape per imports.md §2.1."""

    model_config = ConfigDict(extra="allow")

    tool: str = Field(description="MCP tool name; same as in-process dispatch")
    args: dict[str, Any] = Field(default_factory=dict)


class ImportValidateOutput(BaseModel):
    """Output of `import.validate` per imports.md §3.1."""

    model_config = ConfigDict(extra="allow")

    validated: int = 0
    would_create: int = 0
    would_replay: int = 0
    cascaded_skipped: int = 0
    """Bucket-B cascaded event lines the importer skipped (trade-trace-j5b8).
    See docs/architecture/jsonl-replay-taxonomy.md for the taxonomy."""

    diagnostic_skipped: int = 0
    """Bucket-D diagnostic event lines the importer skipped
    (trade-trace-apgt). Regenerate on demand via `signal.scan` or
    equivalent."""

    errors: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    id_strategy: str = "server_assigned"


class ImportCommitOutput(BaseModel):
    """Output of `import.commit` per imports.md §3.1."""

    model_config = ConfigDict(extra="allow")

    validated: int = 0
    would_create: int = 0
    would_replay: int = 0
    cascaded_skipped: int = 0
    """Bucket-B cascaded event lines skipped during commit (trade-trace-j5b8)."""

    diagnostic_skipped: int = 0
    """Bucket-D diagnostic event lines skipped during commit (trade-trace-apgt)."""

    committed_count: int = 0
    committed_event_ids: list[int] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    id_strategy: str = "server_assigned"


@dataclass
class ParsedRow:
    file: str
    line: int
    tool: str
    args: dict[str, Any]
    contract_version: str | None = None


_ID_FIELDS = {"id"}
_REF_FIELDS = {
    "venue_id",
    "instrument_id",
    "thesis_id",
    "forecast_id",
    "decision_id",
    "outcome_id",
    "source_id",
    "target_id",
    "supersedes_forecast_id",
}

_CASCADED_EVENT_TOOLS = {
    # Bucket-B cascaded events per docs/architecture/jsonl-replay-taxonomy.md
    # (trade-trace-j5b8). These events are emitted INSIDE another tool's
    # transaction and have no standalone write surface; the importer
    # skips them with a `cascaded_skipped` counter and lets the parent
    # tool re-emit them on replay under the same idempotency_key.
    "edge.created",
    "forecast.scored",
    "playbook_rule.followed",
    "playbook_rule.overridden",
    "import.row_committed",
    # Event-type aliases for already-import-ready writers. The exporter
    # writes the event type into the JSONL `tool` field, but the
    # canonical replay path uses the `*.add` / write-tool form. Skipping
    # the alias avoids "tool is not import-ready" rejections on a
    # round-trip restore.
    "outcome.recorded",
    "venue.created",
    "instrument.created",
    "snapshot.added",
    "thesis.created",
    "source.added",
    "source.attached",
    "decision.created",
    "forecast.created",
    "forecast.superseded",
}


_DIAGNOSTIC_EVENT_TOOLS = {
    # Bucket-D diagnostic events per trade-trace-apgt. Observation rows
    # whose original timestamp does not survive restore: regenerate on
    # demand via `signal.scan` or by re-running the invalidation logic.
    # Importer skips with a separate `diagnostic_skipped` counter (and
    # an operability.md §7 note documents the policy).
    "memory_node.invalidated",
    "signal.emitted",
    # market.refresh re-syncs a bound market row from live Gamma on a cache
    # miss; the event records venue truth at fetch time, not a caller
    # mutation, and market.refresh is not import-ready (it would re-fetch
    # live). On restore, regenerate on demand by re-running market.refresh.
    # Bucket D per jsonl-replay-taxonomy.md (AX-068).
    "market.refreshed",
}

_LEGACY_HARD_BREAK_CONTRACT_VERSIONS = {"0.0.1", "0.0.1rc3", "0.0.1-rc3"}
"""Export contract markers that predate the v0.0.2 PM hard break.

Automatic legacy transforms are intentionally out of scope: reject these
imports with an actionable operator message before any dry-run or commit
replay touches the journal.
"""
"""Event-type names that the importer skips with a `cascaded_skipped`
counter rather than rejecting as "not import-ready". A real journal
export emits `tool=edge.created` lines when the runtime emitted an
`edge.created` event; replaying the parent tool (e.g.,
`thesis.add`) regenerates the edge under the same idempotency_key, so
re-issuing the edge.created line would either fail (no such tool) or
double-write. Skipping with a counter preserves the audit value of
the lines while keeping replay correct.

The set also includes the tool-name aliases (e.g., `venue.created` vs
the import-ready `venue.add`) because the exporter writes the event
type as the JSONL `tool` field, not the tool name. The importer's
canonical replay path uses the `*.add` / write tool form."""


_IMPORT_READY_WRITERS = {
    "venue.add",
    "instrument.add",
    "snapshot.add",
    "thesis.add",
    "forecast.add",
    "forecast.supersede",
    "forecast.anchor_to_snapshot",
    "decision.add",
    "outcome.add",
    "resolve.record",
    "source.add",
    "source.attach_to_thesis",
    "source.attach_to_decision",
    "source.attach_to_forecast",
    "source.attach_to_memory_node",
    "playbook.create",
    "playbook.propose_version",
    "strategy.create",
    "strategy.update",
    "memory.retain",
    "memory.reflect",
    "memory.link",
    "market.bind",
    "autonomous_run.record",
    "autonomous_incident.record",
}


def _resolve_import_tool(tool: str) -> str:
    """Translate a JSONL `tool` field through the event-type → tool
    alias map (trade-trace-ths0). Legacy exports may carry the
    event-type alias (e.g., `memory_node.retained`); the importer
    redirects to the canonical write tool (`memory.retain`)."""

    from trade_trace.exporter import _STATIC_EVENT_TOOL_MAP

    return _STATIC_EVENT_TOOL_MAP.get(tool, tool)
_DB_SUFFIXES = ("", "-wal", "-shm")


def _max_errors(args: dict[str, Any]) -> int:
    try:
        return max(1, int(args.get("max_errors", 100)))
    except (TypeError, ValueError):
        return 100


def _add_error(errors: list[dict[str, Any]], max_errors: int, err: dict[str, Any]) -> bool:
    if len(errors) < max_errors:
        errors.append(err)
        return True
    return False


def _error(row: ParsedRow | None, code: ErrorCode | str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    d = dict(details or {})
    if row is not None:
        d.setdefault("file", row.file)
        d.setdefault("line", row.line)
        d.setdefault("tool", row.tool)
    return {"code": str(code), "message": message, "details": d}


def _input_files(path_text: str) -> list[Path]:
    path = Path(path_text).expanduser()
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(p for p in path.rglob("*.jsonl") if not p.name.endswith(".jsonl.tmp"))
    raise ToolError(ErrorCode.NOT_FOUND, f"import path does not exist: {path}", details={"path": str(path)})


def _parse_rows(args: dict[str, Any], *, max_errors: int) -> tuple[list[ParsedRow], list[dict[str, Any]], bool]:
    path = args.get("path") or args.get("file") or args.get("dir")
    if not path:
        raise ToolError(ErrorCode.VALIDATION_ERROR, "import path is required", details={"field": "path"})
    rows: list[ParsedRow] = []
    errors: list[dict[str, Any]] = []
    truncated = False
    for file in _input_files(str(path)):
        with file.open("r", encoding="utf-8") as fh:
            for lineno, text in enumerate(fh, 1):
                if not text.strip():
                    continue
                try:
                    raw = json.loads(text)
                except json.JSONDecodeError as exc:
                    truncated = not _add_error(errors, max_errors, {"code": str(ErrorCode.VALIDATION_ERROR), "message": "invalid JSONL line", "details": {"file": str(file), "line": lineno, "json_error": str(exc)}}) or truncated
                    continue
                if not isinstance(raw, dict):
                    truncated = not _add_error(errors, max_errors, {"code": str(ErrorCode.VALIDATION_ERROR), "message": "JSONL line must be an object", "details": {"file": str(file), "line": lineno}}) or truncated
                    continue
                contract_version = raw.get("_contract_version")
                raw = strip_transport_keys(raw)
                try:
                    line = ImportJSONLLine.model_validate(raw)
                except ValidationError as exc:
                    truncated = not _add_error(errors, max_errors, {"code": str(ErrorCode.VALIDATION_ERROR), "message": "invalid import line shape", "details": {"file": str(file), "line": lineno, "validation_errors": exc.errors()}}) or truncated
                    continue
                rows.append(ParsedRow(str(file), lineno, line.tool, dict(line.args), contract_version if isinstance(contract_version, str) else None))
    return rows, errors, truncated


def _home(args: dict[str, Any]) -> str | None:
    h = args.get("home")
    return str(h) if h is not None else None


def _effective_home(args: dict[str, Any]) -> Path:
    return resolve_home(_home(args))


def _copy_db_files(src_home: Path, dst_home: Path) -> None:
    dst_home.mkdir(parents=True, exist_ok=True)
    src_db = db_path(src_home)
    dst_db = db_path(dst_home)
    for suffix in _DB_SUFFIXES:
        src = Path(str(src_db) + suffix)
        if src.exists():
            shutil.copy2(src, Path(str(dst_db) + suffix))


def _replace_db_files(src_home: Path, dst_home: Path) -> None:
    dst_home.mkdir(parents=True, exist_ok=True)
    src_db = db_path(src_home)
    dst_db = db_path(dst_home)
    for suffix in _DB_SUFFIXES:
        src = Path(str(src_db) + suffix)
        dst = Path(str(dst_db) + suffix)
        if src.exists():
            os.replace(src, dst)
        elif suffix and dst.exists():
            dst.unlink()


def _copy_home_for_validate(home: Path) -> tempfile.TemporaryDirectory[str]:
    tmp = tempfile.TemporaryDirectory(prefix="trade-trace-import-validate-")
    _copy_db_files(home, Path(tmp.name))
    return tmp


_IMMUTABLE_REPLAY_KEYS: dict[str, frozenset[str]] = {
    # Fields the exporter emits as part of the post-mutation row state
    # but the receiving tool refuses to set. The importer drops them
    # before dispatch so a journal round-trip succeeds without
    # require an exporter wire-format change (trade-trace-qtfs).
    "strategy.update": frozenset({
        "name", "slug", "id", "created_at", "updated_at",
    }),
}


def _strip_immutable_replay_keys(tool: str, args: dict[str, Any]) -> dict[str, Any]:
    forbidden = _IMMUTABLE_REPLAY_KEYS.get(tool)
    if not forbidden:
        return args
    return {k: v for k, v in args.items() if k not in forbidden}


def _dispatch_row(row: ParsedRow, home: str | None, actor_id: str):
    from trade_trace.core import dispatch

    row_args = dict(row.args)
    if home is not None:
        row_args.setdefault("home", home)
    # Translate event-type aliases (trade-trace-ths0). The JSONL `tool`
    # field may be the event_type for legacy exports; dispatch
    # canonicalizes via the same map the exporter uses.
    resolved_tool = _resolve_import_tool(row.tool)
    # The exporter writes full post-mutation projection state into the
    # JSONL payload — drop fields the receiving tool refuses to set
    # so a journal round-trip succeeds (trade-trace-qtfs).
    row_args = _strip_immutable_replay_keys(resolved_tool, row_args)
    # The exporter does not currently preserve the original
    # idempotency_key in the JSONL line, and journal replay is the
    # documented at-least-once import path — opt the dispatch-level
    # idempotency_key enforcement out for rows that don't carry their
    # own key (cpz2 + ths0). Rows that *do* carry a key replay
    # normally so the original semantic-key match still wins.
    if "idempotency_key" not in row_args:
        row_args.setdefault("_allow_no_idempotency", True)
    return dispatch(resolved_tool, row_args, actor_id=actor_id).model_dump(mode="json", exclude_none=True)


def _id_strategy_errors(rows: list[ParsedRow], max_errors: int) -> tuple[str, list[dict[str, Any]]]:
    # Skip cascaded + diagnostic events (trade-trace-j5b8 + -apgt) —
    # they carry their own ids but don't participate in the import's
    # id-strategy enforcement; the parent tool's replay or
    # signal.scan regenerates them.
    rows = [
        r for r in rows
        if r.tool not in _CASCADED_EVENT_TOOLS
        and r.tool not in _DIAGNOSTIC_EVENT_TOOLS
    ]
    has_ids = [r for r in rows if any(k in r.args for k in _ID_FIELDS)]
    no_ids = [r for r in rows if not any(k in r.args for k in _ID_FIELDS)]
    if has_ids and no_ids:
        row = no_ids[0]
        return "mixed", [_error(row, ErrorCode.VALIDATION_ERROR, "cannot mix caller-assigned and server-assigned IDs", {"reason": "mixed_id_strategy"})]
    return ("caller_assigned" if has_ids else "server_assigned"), []


def _forward_reference_errors(rows: list[ParsedRow], max_errors: int) -> list[dict[str, Any]]:
    # Skip cascaded + diagnostic events (trade-trace-j5b8 + -apgt) —
    # they reference ids whose parent rows aren't in the import bundle
    # by design.
    rows = [
        r for r in rows
        if r.tool not in _CASCADED_EVENT_TOOLS
        and r.tool not in _DIAGNOSTIC_EVENT_TOOLS
    ]
    defined: set[str] = set()
    future_ids = {str(r.args["id"]) for r in rows if "id" in r.args}
    errors: list[dict[str, Any]] = []
    for row in rows:
        for field in sorted(_REF_FIELDS):
            value = row.args.get(field)
            if isinstance(value, str) and value in future_ids and value not in defined:
                _add_error(errors, max_errors, _error(row, ErrorCode.VALIDATION_ERROR, "referenced ID is not yet defined", {"field": field, "referenced_id_not_yet_defined": value}))
        if "id" in row.args:
            defined.add(str(row.args["id"]))
    return errors


def _tool_errors(rows: list[ParsedRow], max_errors: int) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    for row in rows:
        if row.contract_version in _LEGACY_HARD_BREAK_CONTRACT_VERSIONS:
            _add_error(
                errors,
                max_errors,
                _error(
                    row,
                    ErrorCode.VALIDATION_ERROR,
                    "legacy 0.0.1rc3 JSONL exports are not importable under the v0.0.2 hard-break schema; re-export from v0.0.2 or run an explicit one-time transform before import",
                    {
                        "contract_version": row.contract_version,
                        "reason": "legacy_schema_hard_break",
                        "action": "Use a v0.0.2 export, or transform the legacy export outside import.commit; automatic legacy transforms are intentionally out of scope.",
                    },
                ),
            )
            continue
        # Translate event-type aliases to their write tool names first
        # (trade-trace-ths0). A legacy journal export with
        # tool="memory_node.retained" is the same row as
        # tool="memory.retain"; treat it as the latter for the
        # import-ready check.
        resolved = _resolve_import_tool(row.tool)
        if resolved in _IMPORT_READY_WRITERS:
            continue
        if row.tool in _CASCADED_EVENT_TOOLS or row.tool in _DIAGNOSTIC_EVENT_TOOLS:
            # Bucket-B cascaded events and bucket-D diagnostics are
            # skipped silently with separate counters; the parent tool's
            # replay (bucket B) or signal.scan / equivalent (bucket D)
            # regenerates them.
            continue
        # Anything we didn't already short-circuit above is not import-ready.
        _add_error(
            errors, max_errors,
            _error(row, ErrorCode.VALIDATION_ERROR, "tool is not import-ready",
                   {"tool": row.tool, "resolved_tool": resolved,
                    "import_ready_writers": sorted(_IMPORT_READY_WRITERS)}),
        )
    return errors


def _validate_rows(rows: list[ParsedRow], args: dict[str, Any], ctx: ToolContext, *, max_errors: int) -> ImportValidateOutput:
    out = ImportValidateOutput()
    for err in _tool_errors(rows, max_errors):
        _add_error(out.errors, max_errors, err)
    strategy, strategy_errors = _id_strategy_errors(rows, max_errors)
    out.id_strategy = strategy
    for err in strategy_errors:
        _add_error(out.errors, max_errors, err)
    for err in _forward_reference_errors(rows, max_errors):
        _add_error(out.errors, max_errors, err)
    if out.errors:
        return out

    with _copy_home_for_validate(_effective_home(args)) as tmp:
        for row in rows:
            if len(out.errors) >= max_errors:
                break
            if row.tool in _DIAGNOSTIC_EVENT_TOOLS:
                # Bucket-D diagnostic skip (trade-trace-apgt). The
                # observation regenerates on demand via signal.scan
                # or equivalent.
                out.diagnostic_skipped += 1
                continue
            if row.tool in _CASCADED_EVENT_TOOLS:
                # Bucket-B cascaded skip (trade-trace-j5b8). The parent
                # tool's replay regenerates these lines under the same
                # idempotency_key.
                out.cascaded_skipped += 1
                continue
            env = _dispatch_row(row, tmp, ctx.actor_id)
            if env.get("ok") is True:
                out.validated += 1
                if env.get("meta", {}).get("idempotent_replay"):
                    out.would_replay += 1
                else:
                    out.would_create += 1
            else:
                e = env.get("error", {})
                _add_error(out.errors, max_errors, _error(row, e.get("code", ErrorCode.VALIDATION_ERROR), e.get("message", "validation failed"), e.get("details", {})))
    return out


def _import_validate(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    max_errors = _max_errors(args)
    rows, parse_errors, truncated = _parse_rows(args, max_errors=max_errors)
    out = _validate_rows(rows, args, ctx, max_errors=max_errors)
    for err in parse_errors:
        if not _add_error(out.errors, max_errors, err):
            truncated = True
    if truncated:
        ctx.meta_hints["truncated"] = True
    return out.model_dump(mode="json")


def _import_commit(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    max_errors = _max_errors(args)
    rows, parse_errors, truncated = _parse_rows(args, max_errors=max_errors)
    transaction_mode = args.get("transaction_mode", "single")
    if transaction_mode not in ("single", "per_row"):
        raise ToolError(ErrorCode.VALIDATION_ERROR, "transaction_mode must be 'single' or 'per_row'", details={"field": "transaction_mode"})

    if transaction_mode == "single":
        validation = _validate_rows(rows, args, ctx, max_errors=max_errors)
    else:
        validation = ImportValidateOutput()
        for err in _tool_errors(rows, max_errors):
            _add_error(validation.errors, max_errors, err)
        strategy, strategy_errors = _id_strategy_errors(rows, max_errors)
        validation.id_strategy = strategy
        for err in strategy_errors:
            _add_error(validation.errors, max_errors, err)
        for err in _forward_reference_errors(rows, max_errors):
            _add_error(validation.errors, max_errors, err)
        replayable_rows = [
            row for row in rows
            if row.tool not in _DIAGNOSTIC_EVENT_TOOLS
            and row.tool not in _CASCADED_EVENT_TOOLS
        ]
        validation.validated = len(replayable_rows) if not validation.errors else 0
        validation.would_create = len(replayable_rows) if not validation.errors else 0
    for err in parse_errors:
        if not _add_error(validation.errors, max_errors, err):
            truncated = True
    if truncated:
        ctx.meta_hints["truncated"] = True
    out = ImportCommitOutput(**validation.model_dump(mode="json"))
    if bool(args.get("dry_run", False)):
        return out.model_dump(mode="json")
    if out.errors:
        return out.model_dump(mode="json")

    halt_on_error = bool(args.get("halt_on_error", True))
    home = _home(args)
    actor_id = ctx.actor_id

    if transaction_mode == "single":
        real_home = _effective_home(args)
        with tempfile.TemporaryDirectory(prefix="trade-trace-import-commit-") as tmp:
            staged_home = Path(tmp)
            _copy_db_files(real_home, staged_home)
            for row in rows:
                if row.tool in _CASCADED_EVENT_TOOLS or row.tool in _DIAGNOSTIC_EVENT_TOOLS:
                    # validation already counted these into
                    # cascaded_skipped / diagnostic_skipped.
                    continue
                env = _dispatch_row(row, str(staged_home), actor_id)
                if env.get("ok") is True:
                    out.committed_count += 1
                    meta = env.get("meta", {})
                    if meta.get("event_id") is not None:
                        out.committed_event_ids.append(meta["event_id"])
                    continue
                e = env.get("error", {})
                _add_error(out.errors, max_errors, _error(row, e.get("code", ErrorCode.VALIDATION_ERROR), e.get("message", "commit failed"), e.get("details", {})))
                out.committed_count = 0
                out.committed_event_ids = []
                return out.model_dump(mode="json")
            _replace_db_files(staged_home, real_home)
        return out.model_dump(mode="json")

    for row in rows:
        if row.tool in _DIAGNOSTIC_EVENT_TOOLS:
            out.diagnostic_skipped += 1
            continue
        if row.tool in _CASCADED_EVENT_TOOLS:
            out.cascaded_skipped += 1
            continue
        env = _dispatch_row(row, home, actor_id)
        if env.get("ok") is True:
            out.committed_count += 1
            meta = env.get("meta", {})
            if meta.get("event_id") is not None:
                out.committed_event_ids.append(meta["event_id"])
            continue
        e = env.get("error", {})
        _add_error(out.errors, max_errors, _error(row, e.get("code", ErrorCode.VALIDATION_ERROR), e.get("message", "commit failed"), e.get("details", {})))
        if halt_on_error:
            break
    return out.model_dump(mode="json")


# AX-056: import.commit was registered with **_examples_for(...) and no
# explicit json_schema, so the advertised MCP schema auto-derived from
# example_minimal exposed transaction_mode as a bare string even though the
# runtime enum-validates it against {single, per_row} with a self-documenting
# error (the AX-051 / AX-054 class). This explicit schema mirrors the runtime;
# the handler is unchanged.
_IMPORT_COMMIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "Path to a JSONL file or directory of JSONL files to replay through core dispatch."},
        "transaction_mode": {"type": "string", "enum": ["single", "per_row"], "description": "single = one transaction for the whole file (all-or-nothing after validation); per_row = commit each row independently. Defaults to 'single'."},
        "max_errors": {"type": "integer", "description": "Stop collecting errors after this many (default 100)."},
        "halt_on_error": {"type": "boolean", "description": "Stop at the first failing row (default true)."},
        "idempotency_key": {"type": "string"},
        "home": {"type": "string"},
    },
    "required": ["path", "transaction_mode", "idempotency_key"],
}


def register_import_stubs(registry: ToolRegistry) -> None:
    from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    registry.register(
        "import.validate",
        _import_validate,
        description="Dry-run validate a JSONL file/directory without writing.",
        **_examples_for("import.validate"),
    )
    registry.register(
        "import.commit",
        _import_commit,
        description="Replay a JSONL file/directory through core dispatch.",
        is_write=True,
        json_schema=_IMPORT_COMMIT_SCHEMA,
        **_examples_for("import.commit"),
    )
