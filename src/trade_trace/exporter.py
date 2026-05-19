"""JSONL outbox exporter per docs/architecture/operability.md §9.

Atomic write semantics:
- Each event is written to its own `<YYYY>/<MM>/<DD>/<event_type>-<event_id>.jsonl.tmp`
  first, then renamed to `.jsonl` on success.
- Readers (importer) ignore `.jsonl.tmp` files entirely.
- Orphaned `.jsonl.tmp` files older than 1 hour are cleaned up on the next
  `export.drain` invocation.

Path convention:
  `$TRADE_TRACE_HOME/export/jsonl/<YYYY>/<MM>/<DD>/<event_type>-<event_id>.jsonl`

Underscore-prefixed keys are reserved transport metadata; the importer
drops them on read.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

RESERVED_TRANSPORT_KEYS = frozenset(
    {"_event_id", "_event_type", "_actor_id", "_created_at", "_contract_version"}
)

TMP_SUFFIX = ".jsonl.tmp"
FINAL_SUFFIX = ".jsonl"


_EVENT_TYPE_SAFE_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
)


def _safe_event_type_for_filename(event_type: str) -> str:
    """Sanitize `event_type` for use in a JSONL filename per bead
    trade-trace-qc7 / DEBT-028.

    Today's `event_type` enum is filename-safe by construction
    (`decision.created`, `memory_node.retained`, etc. — only ASCII
    alphanumerics, `.`, `_`, `-`). But the enum is open: a future
    event type could legitimately contain a `/` (nested namespace),
    backslash, NUL, or path-traversal segment, and a naive
    f-string would let it escape the YYYY/MM/DD bucket directory
    or land at an unintended path under the export root.

    The sanitization is conservative: any character outside the
    documented safe set is replaced with `_`. The resulting string
    is collision-safe across realistic event-type drift because
    the event id is also embedded in the filename and is unique.
    """

    return "".join(c if c in _EVENT_TYPE_SAFE_CHARS else "_"
                   for c in event_type) or "_"


def jsonl_path(home: Path, event_type: str, event_id: int, created_at: str) -> Path:
    """Compute the canonical JSONL output path for an event.

    `created_at` must be the canonical UTC ISO 8601 string the events table
    uses; the year/month/day buckets are derived from it. `event_type` is
    passed through `_safe_event_type_for_filename` to keep a hostile or
    misnamed event type from escaping the date-bucket directory.
    """

    ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    base = home / "export" / "jsonl" / f"{ts.year:04d}" / f"{ts.month:02d}" / f"{ts.day:02d}"
    base.mkdir(parents=True, exist_ok=True)
    safe_event_type = _safe_event_type_for_filename(event_type)
    return base / f"{safe_event_type}-{event_id}{FINAL_SUFFIX}"


# -- event_type → tool resolution (imports.md §2.1 superset shape) ---------

def resolve_tool_for_event(event_type: str, payload: dict[str, Any]) -> str:
    """Return the canonical MCP tool name an importer would dispatch to.

    For events with no user-callable tool (system-emitted events like
    `forecast.scored` or `signal.emitted`), returns the event_type itself
    so the line remains self-describing. Importer chooses to dispatch or
    treat as a system-event audit record based on `_event_type`.

    `source.attached` requires the payload to disambiguate the target tool
    (`source.attach_to_thesis` vs `_decision` vs `_forecast`).
    """

    if event_type == "source.attached":
        target = payload.get("target_kind")
        if target in ("thesis", "decision", "forecast", "memory_node"):
            return f"source.attach_to_{target}"
        return event_type
    return _STATIC_EVENT_TOOL_MAP.get(event_type, event_type)


_STATIC_EVENT_TOOL_MAP: dict[str, str] = {
    # M1 ledger writes — every event below is emitted by exactly one user-
    # callable tool. Keep in lockstep with semantic_keys.SEMANTIC_KEYS.
    "venue.created": "venue.add",
    "instrument.created": "instrument.add",
    "snapshot.added": "snapshot.add",
    "thesis.created": "thesis.add",
    "source.added": "source.add",
    "decision.created": "decision.add",
    "outcome.recorded": "outcome.add",
    "forecast.created": "forecast.add",
    "forecast.superseded": "forecast.supersede",
    # `forecast.scored` and `signal.emitted` are system-emitted; the
    # importer treats them as audit-only records and does not redispatch.
    # `import.row_committed` is internal bookkeeping for the importer.
    # `edge.created` has no single tool surface (created as a side effect
    # of thesis.add and forecast.supersede); the importer audits it.
    # Other M3+ event types (playbook.*, memory_node.*, strategy.*) get
    # filled in as their tools land. Until then, the default returns
    # `event_type` so the JSONL line remains valid.
}


def write_event_atomic(
    home: Path,
    *,
    event_id: int,
    event_type: str,
    actor_id: str,
    created_at: str,
    payload: dict[str, Any],
    tool: str | None = None,
    contract_version: str = "1.0",
) -> Path:
    """Atomically write an event JSONL file.

    Produces one line with the imports.md §2.1 superset shape:

        {"tool": "<resolved>", "args": <payload-minus-underscored>,
         "_event_id": ..., "_event_type": ..., "_actor_id": ...,
         "_created_at": ..., "_contract_version": "1.0"}

    `args` excludes underscore-prefixed keys (those are transport-only).
    The importer reads `tool` + `args` directly and ignores transport keys.
    """

    import stat as _stat

    final = jsonl_path(home, event_type, event_id, created_at)
    tmp = final.parent / (final.name + ".tmp")
    args = {k: v for k, v in payload.items() if not k.startswith("_")}
    resolved_tool = tool or resolve_tool_for_event(event_type, args)
    line: dict[str, Any] = {
        "tool": resolved_tool,
        "args": args,
        "_event_id": event_id,
        "_event_type": event_type,
        "_actor_id": actor_id,
        "_created_at": created_at,
        "_contract_version": contract_version,
    }
    # Open with O_CREAT|O_WRONLY|O_TRUNC and explicit mode=0600 so the
    # tmp file is restrictive from the start (bead trade-trace-ljl9 /
    # DEBT-040). On POSIX the umask is masked against the mode bits;
    # umask 0 + mode 0o600 still produces 0o600. We tighten the parent
    # directory after creation too so directory listings don't leak
    # event names.
    flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    fd = os.open(str(tmp), flags, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(line, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        # If anything raised between open and fdopen taking ownership
        # the fd may still be open; under normal flow fdopen owns it
        # and the close happens at end of `with`.
        raise
    os.replace(tmp, final)  # atomic on POSIX
    # Re-pin 0600 on the final path after the rename — `os.replace`
    # preserves the source bits on POSIX, but the explicit chmod
    # tightens the contract on platforms that emulate replace by copy
    # (some filesystems) and re-asserts the bit if a future change
    # widens the tmp creation default.
    try:
        final.chmod(_stat.S_IRUSR | _stat.S_IWUSR)
    except (OSError, NotImplementedError):  # pragma: no cover — Windows
        pass
    # Tighten the date-bucketed parent dirs (export/jsonl/YYYY/MM/DD)
    # so `ls` cannot leak event filenames.
    try:
        for parent in (final.parent, final.parent.parent,
                       final.parent.parent.parent):
            parent.chmod(_stat.S_IRWXU)
    except (OSError, NotImplementedError):  # pragma: no cover — Windows
        pass
    return final


def strip_transport_keys(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop underscore-prefixed transport metadata before re-dispatching a
    JSONL line through the core (importer's read path)."""

    return {k: v for k, v in payload.items() if not k.startswith("_")}


def iter_jsonl_files(home: Path) -> list[Path]:
    """Walk `$TRADE_TRACE_HOME/export/jsonl/` returning every committed
    `.jsonl` file (skipping `.jsonl.tmp`). Deterministic sort by path."""

    base = home / "export" / "jsonl"
    if not base.exists():
        return []
    files = [p for p in base.rglob(f"*{FINAL_SUFFIX}") if not p.name.endswith(TMP_SUFFIX)]
    return sorted(files)


def cleanup_orphan_tmp_files(home: Path, *, older_than_seconds: float = 3600) -> list[Path]:
    """Delete `.jsonl.tmp` files older than `older_than_seconds` (default 1h).

    Returns the list of removed paths. Run on every `export.drain`
    invocation to keep crashed-mid-write debris from accumulating.
    """

    base = home / "export" / "jsonl"
    if not base.exists():
        return []
    cutoff = time.time() - older_than_seconds
    removed: list[Path] = []
    for path in base.rglob(f"*{TMP_SUFFIX}"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed.append(path)
        except FileNotFoundError:
            continue
    return removed


# -- secret scanning (operability.md §6.3 / §7) -----------------------------

# Patterns live in `trade_trace.security.patterns` per bead trade-trace-sy1
# so the write-time guard, the export-time warning, and the log redactor
# all share one registry. SECRET_PATTERNS is kept as a backwards-compatible
# alias for callers that imported from `trade_trace.exporter`.
from trade_trace.security import scan_text as _scan_text  # noqa: E402
from trade_trace.security.patterns import _compiled as SECRET_PATTERNS  # noqa: E402, F401


def scan_for_secrets(text: str) -> list[dict[str, str]]:
    """Return a list of `{pattern, match}` for every secret-shaped substring
    in `text`. Used by `drain_outbox` to emit a per-event warning; never
    blocks the export (operability.md §7 calls this a "did you mean to ship
    these out?" check, not a gate).
    """

    return [{"pattern": m.pattern_kind, "match": m.match} for m in _scan_text(text)]


# -- outbox drain -----------------------------------------------------------

@dataclass
class DrainResult:
    """Summary returned by `drain_outbox`.

    Attributes mirror what an eventual `export.drain` MCP tool would surface
    in its success envelope. The exporter is invoked explicitly per
    operability.md §9.1 — there is no background daemon.
    """

    exported_event_ids: list[int] = field(default_factory=list)
    exported_files: list[Path] = field(default_factory=list)
    secret_warnings: list[dict[str, Any]] = field(default_factory=list)
    orphans_cleaned: list[Path] = field(default_factory=list)


def _read_outbox_pending(conn: sqlite3.Connection) -> list[tuple[int, int]]:
    """Return `(outbox_id, event_id)` rows in the deterministic order the
    drain walks them. Ordering rules:

    - `state IN ('pending', 'failed')` so a retry after a crash resumes
      where the previous run left off (persistence.md §4.1).
    - Ordered by `event_id ASC` so parent rows are emitted before children.
      The event_id ordering matches creation order because `events.id` is
      an autoincrement integer assigned inside the per-event transaction
      that creates the row's parents (operability.md §9 + persistence.md
      §6 unit-of-work boundary).
    - Restricted to `export_kind = 'jsonl'`; future kinds use distinct
      drain functions.
    """

    cur = conn.execute(
        """
        SELECT id, event_id
        FROM outbox
        WHERE export_kind = 'jsonl' AND state IN ('pending', 'failed')
        ORDER BY event_id ASC, id ASC
        """
    )
    return [(row[0], row[1]) for row in cur.fetchall()]


def _load_event(conn: sqlite3.Connection, event_id: int) -> tuple[str, str, str, str] | None:
    """Return `(event_type, actor_id, created_at, payload_json)` for the
    event id, or None if missing (which would indicate FK corruption)."""

    cur = conn.execute(
        "SELECT event_type, actor_id, created_at, payload_json FROM events WHERE id = ?",
        (event_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return (row[0], row[1], row[2], row[3])


def drain_outbox(
    conn: sqlite3.Connection,
    home: Path,
    *,
    cleanup_orphans: bool = True,
) -> DrainResult:
    """Drain every pending/failed outbox row into JSONL files on disk.

    Idempotent: re-running on an already-drained outbox produces zero new
    work because `state = 'exported'` rows are excluded. If a row is
    re-marked pending (e.g. by a restore from backup), its file is rewritten
    byte-for-byte (path includes `event_id`; line content is deterministic
    via canonical JSON).

    The exporter never raises on secret-shaped substrings — it appends to
    `secret_warnings` and proceeds. Operators see the warning in the result
    envelope; they decide whether to redact and resubmit (operability.md §7).
    """

    result = DrainResult()
    if cleanup_orphans:
        result.orphans_cleaned = cleanup_orphan_tmp_files(home)

    pending = _read_outbox_pending(conn)
    for outbox_id, event_id in pending:
        event = _load_event(conn, event_id)
        if event is None:
            # FK should prevent this, but surface a defensive error_text
            # rather than crash the whole drain.
            conn.execute(
                "UPDATE outbox SET state = 'failed', error_text = ?, "
                "attempt_count = attempt_count + 1 WHERE id = ?",
                ("event_row_missing", outbox_id),
            )
            continue

        event_type, actor_id, created_at, payload_json = event
        try:
            payload = json.loads(payload_json)
        except (json.JSONDecodeError, TypeError) as exc:
            # Corrupt payload would abort the whole drain otherwise; per
            # bead trade-trace-eo4 the row is marked failed and the loop
            # continues so a single bad event can't wedge the exporter.
            conn.execute(
                "UPDATE outbox SET state = 'failed', error_text = ?, "
                "attempt_count = attempt_count + 1 WHERE id = ?",
                (f"payload_json_decode_error: {exc}", outbox_id),
            )
            continue
        if not isinstance(payload, dict):
            conn.execute(
                "UPDATE outbox SET state = 'failed', error_text = ?, "
                "attempt_count = attempt_count + 1 WHERE id = ?",
                (
                    f"payload_json_not_object: got {type(payload).__name__}",
                    outbox_id,
                ),
            )
            continue
        try:
            path = write_event_atomic(
                home,
                event_id=event_id,
                event_type=event_type,
                actor_id=actor_id,
                created_at=created_at,
                payload=payload,
            )
        except OSError as exc:
            conn.execute(
                "UPDATE outbox SET state = 'failed', error_text = ?, "
                "attempt_count = attempt_count + 1 WHERE id = ?",
                (str(exc), outbox_id),
            )
            continue

        line_text = path.read_text(encoding="utf-8")
        secrets_found = scan_for_secrets(line_text)
        if secrets_found:
            result.secret_warnings.append(
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "patterns": sorted({m["pattern"] for m in secrets_found}),
                }
            )

        conn.execute(
            "UPDATE outbox SET state = 'exported', exported_at = ?, "
            "attempt_count = attempt_count + 1, error_text = NULL "
            "WHERE id = ?",
            (created_at, outbox_id),
        )

        result.exported_event_ids.append(event_id)
        result.exported_files.append(path)

    return result


def sha256_of_file(path: Path) -> str:
    """Convenience for tests asserting drain idempotency (acceptance criteria
    explicitly call for SHA-256 comparison)."""

    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
