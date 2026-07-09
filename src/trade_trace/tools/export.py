"""Public JSONL outbox export/drain tool surface."""

from __future__ import annotations

from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.exporter import drain_outbox
from trade_trace.storage import open_database, resolve_home
from trade_trace.storage.paths import db_path
from trade_trace.tools.errors import ToolError

_EXPORT_DRAIN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "home": {
            "type": "string",
            "description": "Optional TRADE_TRACE_HOME override. Defaults to env/default home.",
        },
        "cleanup_orphans": {
            "type": "boolean",
            "default": True,
            "description": "Delete orphaned *.jsonl.tmp files older than one hour before draining.",
        },
    },
}


def _config_value(conn: Any, key: str) -> str | None:
    row = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    return None if row is None else str(row[0])


def _pending_counts(conn: Any) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT state, COUNT(*)
        FROM outbox
        WHERE export_kind = 'jsonl'
        GROUP BY state
        """
    ).fetchall()
    counts = {"pending": 0, "failed": 0, "exported": 0}
    counts |= {str(state): int(count) for state, count in rows}
    counts["drainable"] = counts["pending"] + counts["failed"]
    return counts


def _export_drain(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`export.drain` — drain pending JSONL outbox rows to local files."""

    home = resolve_home(args.get("home"))
    path = db_path(home)
    if not path.exists():
        raise ToolError(
            ErrorCode.STORAGE_ERROR,
            "journal not initialized; run `tt journal init` first",
            details={"home": str(home), "db_path": str(path)},
        )

    cleanup_orphans = args.get("cleanup_orphans", True)
    if not isinstance(cleanup_orphans, bool):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "cleanup_orphans must be a boolean",
            details={"field": "cleanup_orphans", "value": cleanup_orphans},
        )

    db = open_database(path, create_parent=False)
    try:
        before_counts = _pending_counts(db.connection)
        jsonl_enabled = _config_value(db.connection, "outbox.jsonl_enabled") == "true"
        result = drain_outbox(db.connection, home, cleanup_orphans=cleanup_orphans)
        after_counts = _pending_counts(db.connection)
    finally:
        db.close()

    exported_files = [str(p) for p in result.exported_files]
    orphans_cleaned = [str(p) for p in result.orphans_cleaned]
    warnings: list[dict[str, Any]] = []
    if not jsonl_enabled:
        warnings.append(
            {
                "kind": "outbox_jsonl_disabled",
                "message": (
                    "outbox.jsonl_enabled is not true; this drain exports only rows "
                    "already present in the JSONL outbox. Enable JSONL outbox before "
                    "writing events to enqueue future exports."
                ),
            }
        )
    if result.secret_warnings:
        warnings.append(
            {
                "kind": "sensitive_content_matches",
                "message": "Sensitive-shaped substrings were detected in exported JSONL files; inspect before sharing externally.",
                "count": len(result.secret_warnings),
            }
        )

    ctx.meta_hints["cli_human_hint"] = (
        f"export.drain wrote {len(result.exported_event_ids)} JSONL file(s) under {home / 'export' / 'jsonl'}"
    )
    return {
        "home": str(home),
        "db_path": str(path),
        "export_root": str(home / "export" / "jsonl"),
        "jsonl_enabled": jsonl_enabled,
        "counts_before": before_counts,
        "counts_after": after_counts,
        "exported_count": len(result.exported_event_ids),
        "exported_event_ids": result.exported_event_ids,
        "exported_files": exported_files,
        "orphans_cleaned_count": len(orphans_cleaned),
        "orphans_cleaned": orphans_cleaned,
        "sensitive_content_warnings": result.secret_warnings,
        "warnings": warnings,
        "relationship": {
            "outbox_jsonl_enabled": "Controls whether future event writes enqueue JSONL outbox rows; export.drain drains existing pending/failed rows.",
            "journal_backup": "journal.backup copies the SQLite DB plus the export/jsonl tree; run export.drain first when you need backups to include the latest JSONL export tree.",
            "network": "No external network calls are made; files are written under TRADE_TRACE_HOME/export/jsonl.",
        },
    }


def register_export_tools(registry: ToolRegistry) -> None:
    """Register public export tools."""

    registry.register(
        "export.drain",
        _export_drain,
        json_schema=_EXPORT_DRAIN_SCHEMA,
        description=(
            "Drain pending/failed JSONL outbox rows to local JSONL files under "
            "$TRADE_TRACE_HOME/export/jsonl, mark rows exported, clean old tmp "
            "orphans, and report exported event IDs, paths, counts, and sensitive-content warnings."
        ),
        usage_summary="tt export drain [--home /path/to/home] [--cleanup_orphans false]",
        examples=[
            "tt journal init && tt export drain",
            "tt tool schema --tool export.drain",
            "tt export drain --home /tmp/trade-trace-home",
        ],
        common_failures=[
            "STORAGE_ERROR when the journal has not been initialized.",
            "Zero exported rows when outbox.jsonl_enabled was disabled when events were written.",
        ],
        next_actions=[
            "Inspect exported_files and exported_event_ids in the success envelope.",
            "Run journal.backup after export.drain if the backup must include the latest JSONL export tree.",
        ],
    )
