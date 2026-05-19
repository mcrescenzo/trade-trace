"""Single-transaction unit-of-work helper per persistence.md §6.

A tool call's primary ledger write, any cascaded writes, the `events` row,
the `outbox` row, and any eagerly-maintained projection updates all commit
in one SQLite transaction. The agent sees a single error envelope; no
partial state is committed.

The UnitOfWork context manager handles `BEGIN` / `COMMIT` / `ROLLBACK`,
exposes the event writer, and lets callers register projection updaters
that run inside the same transaction.

When the request-scoped `DRY_RUN_FLAG` is set (per bead trade-trace-268),
the unit of work runs handlers normally, lets projection updaters compute,
and then issues `ROLLBACK` instead of `COMMIT`. Tools see the would-be IDs
in the return value but nothing is persisted. The dispatcher sets the
context var per call so handler code does not need bespoke dry-run paths.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from trade_trace.events.log import EventWriter

ProjectionUpdater = Callable[[sqlite3.Connection], None]


DRY_RUN_FLAG: ContextVar[bool] = ContextVar("trade_trace.dry_run", default=False)
"""Request-scoped dry-run flag. Set by the dispatcher when an agent passes
`_dry_run=True`; UnitOfWork honors it by rolling back instead of committing.
"""


class UnitOfWork:
    """Run a primary write, its cascades, an event row, an outbox row, and
    optional projections atomically.

    Usage:

        with UnitOfWork(conn) as uow:
            uow.execute("INSERT INTO ... VALUES (...)", (...))
            uow.event_writer.write(...)
            uow.register_projection(_update_positions)
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.event_writer = EventWriter(conn)
        self._projections: list[ProjectionUpdater] = []
        self._committed = False

    @property
    def dry_run(self) -> bool:
        """True when this unit of work was opened under a dry-run request.

        Handlers normally don't need to check this — UoW handles rollback —
        but importers and other multi-stage writers can branch on it to
        skip side effects (file emission, subprocess spawn, etc.).
        """

        return DRY_RUN_FLAG.get()

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def register_projection(self, updater: ProjectionUpdater) -> None:
        """Queue a projection updater to run after the primary writes and
        before commit. The updater runs inside the same transaction; any
        exception rolls back everything."""

        self._projections.append(updater)

    def _commit(self) -> None:
        for updater in self._projections:
            updater(self.conn)
        if DRY_RUN_FLAG.get():
            self.conn.execute("ROLLBACK")
            return
        self.conn.execute("COMMIT")
        self._committed = True

    def _rollback(self) -> None:
        self.conn.execute("ROLLBACK")

    def __enter__(self) -> UnitOfWork:
        self.conn.execute("BEGIN")
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if exc_type is not None:
            self._rollback()
            return False  # re-raise
        try:
            self._commit()
        except Exception:
            self._rollback()
            raise
        return False


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[UnitOfWork]:
    """Functional equivalent of `with UnitOfWork(conn) as uow:`."""

    uow = UnitOfWork(conn)
    try:
        with uow as inner:
            yield inner
    finally:
        pass
