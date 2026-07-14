"""Migration 036_decisions_risk_check_receipt_id.

Adds an optional `risk_check_receipt_id` column to `decisions` per bead
trade-trace-yyegu's owner-affirmed design proposal: decision-time position
opening is AFFIRMED (not moved to fill-time); `decision.add` on
`paper_enter`/`actual_enter` now accepts an optional link to the immutable
`risk_check_receipts` row (written by `risk.check_record`) that backed the
entry, nudging the risk-first chain (risk.evaluate -> risk.check_record ->
decision.add(risk_check_receipt_id) -> pretrade_intent.record -> fill) at
the substrate level without breaking any existing flow. When absent on an
enter-type decision, `decision.add`'s response carries a non-blocking
advisory caveat instead (app-level; no schema enforcement of presence).

Column-only change, same pattern as migration 004/019: nullable, no
default, `REFERENCES risk_check_receipts(id)` for documentation (SQLite
does not enforce FK constraints unless `PRAGMA foreign_keys=ON`, and this
repo validates the reference at the tool layer via `validate_fk_refs`,
mirroring `pretrade_intent.py`'s `_REF_TABLES` pattern, so callers get a
typed VALIDATION_ERROR envelope rather than a raw constraint failure).
"""

from __future__ import annotations

import sqlite3


def _migration_036_decisions_risk_check_receipt_id(conn: sqlite3.Connection) -> None:
    """Add `decisions.risk_check_receipt_id` plus a covering index."""

    conn.execute(
        "ALTER TABLE decisions ADD COLUMN risk_check_receipt_id "
        "TEXT REFERENCES risk_check_receipts(id)"
    )
    conn.execute(
        "CREATE INDEX idx_decisions_risk_check_receipt "
        "ON decisions(risk_check_receipt_id)"
    )


__all__ = ["_migration_036_decisions_risk_check_receipt_id"]
