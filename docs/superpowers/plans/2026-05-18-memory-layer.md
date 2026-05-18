# Memory Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. During execution, create a `bd` issue per task before writing code (per project CLAUDE.md), claim it on start, close it on commit.

**Goal:** Implement the trade-trace memory layer end-to-end per `docs/architecture/memory-layer.md` v2 — schema, write/read paths, embeddings, signals, CLI, MCP — on a greenfield Python package, with TDD.

**Architecture:** Single SQLite file (WAL, FTS5, optional `sqlite-vec`). Three node kinds (`observation`, `reflection`, `rule`), seven edge types, separate `signals` table. Multi-strategy retrieval (BM25, temporal, semantic, opt-in graph) fused via RRF with context-budget shaping. Local embedding model (`BAAI/bge-small-en-v1.5`) lazy-downloaded on init; OpenAI provider opt-in with keyring storage. Public surface (`memory.retain`, `memory.recall`, `memory.reflect`, `memory.link`) exposed as MCP tools and CLI subcommands with semantic parity.

**Tech Stack:** Python 3.11+, SQLite stdlib + `sqlite-vec`, `sentence-transformers`, `pydantic` v2, `keyring`, `typer` (CLI), `mcp` SDK, `pytest`.

**Phases:**

- Phase 0: Package skeleton + DB + migrations
- Phase 1: Memory schema + endpoint stubs
- Phase 2: Edge validation + write
- Phase 3: Memory write path (`retain`)
- Phase 4: Retrieval (BM25, temporal, confidence, RRF, budget, graph)
- Phase 5: Embeddings (local provider, OpenAI provider, semantic retriever, reindex)
- Phase 6: Signals + `reflect` sugar
- Phase 7: CLI surface
- Phase 8: MCP surface + parity tests
- Phase 9: End-to-end integration test

**Definition of done:** A subagent on a fresh checkout runs `pip install -e .[dev]`, then `pytest` (all green), then `tt init && tt memory retain --kind observation --body "NVDA gaps fade in semis" && tt memory recall --query "NVDA earnings"` and gets a well-formed JSON envelope with the retained record back. MCP server returns an envelope-equivalent response for the same call.

---

## Phase 0: Package Skeleton + DB + Migrations

### Task 0.1: Package skeleton, deps, pytest

**Files:**
- Create: `pyproject.toml`
- Create: `src/trade_trace/__init__.py`
- Create: `src/trade_trace/version.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `.gitignore` additions for `__pycache__`, `*.egg-info`, `.pytest_cache`, `dist/`, `build/`

- [ ] **Step 1: Write a failing import test**

`tests/test_smoke.py`:
```python
def test_package_importable():
    import trade_trace
    assert trade_trace.__version__ == "0.0.0"
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `pytest tests/test_smoke.py -v`
Expected: `ModuleNotFoundError: No module named 'trade_trace'`

- [ ] **Step 3: Create pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "trade-trace"
version = "0.0.0"
description = "Local journal, memory, and calibration substrate for LLM trading agents."
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.6",
    "sqlite-vec>=0.1.6",
    "sentence-transformers>=2.7",
    "keyring>=24",
    "typer[all]>=0.12",
    "mcp>=0.9",
    "numpy>=1.26",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "ruff>=0.4", "mypy>=1.10"]

[project.scripts]
tt = "trade_trace.cli:app"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra --strict-markers"
asyncio_mode = "auto"
```

- [ ] **Step 4: Create src/trade_trace package**

`src/trade_trace/version.py`:
```python
__version__ = "0.0.0"
```

`src/trade_trace/__init__.py`:
```python
from trade_trace.version import __version__

__all__ = ["__version__"]
```

- [ ] **Step 5: Install + run test**

Run: `pip install -e .[dev] && pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/trade_trace tests/ .gitignore
git commit -m "feat(skeleton): package layout, deps, smoke test"
```

---

### Task 0.2: SQLite connection helper with WAL + foreign keys

**Files:**
- Create: `src/trade_trace/db.py`
- Create: `tests/test_db.py`

- [ ] **Step 1: Write failing test for `connect()`**

`tests/test_db.py`:
```python
import sqlite3
from pathlib import Path

import pytest

from trade_trace.db import connect


def test_connect_creates_file_and_enables_wal(tmp_path: Path):
    db_path = tmp_path / "test.sqlite"
    conn = connect(db_path)
    try:
        assert db_path.exists()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert mode.lower() == "wal"
        assert fk == 1
    finally:
        conn.close()


def test_connect_rejects_relative_path():
    with pytest.raises(ValueError, match="absolute"):
        connect(Path("relative.sqlite"))
```

- [ ] **Step 2: Run test, confirm fail**

Run: `pytest tests/test_db.py -v`
Expected: `ModuleNotFoundError: No module named 'trade_trace.db'`

- [ ] **Step 3: Implement `connect()`**

`src/trade_trace/db.py`:
```python
"""SQLite connection helper. WAL mode, foreign keys on, JSON1 available by stdlib."""
from __future__ import annotations

import sqlite3
from pathlib import Path


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the trade-trace SQLite database with project pragmas applied.

    Caller owns the connection lifecycle.
    """
    if not db_path.is_absolute():
        raise ValueError(f"db_path must be absolute, got: {db_path}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn
```

- [ ] **Step 4: Run test**

Run: `pytest tests/test_db.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/db.py tests/test_db.py
git commit -m "feat(db): SQLite connect helper with WAL + foreign keys"
```

---

### Task 0.3: Migration framework

**Files:**
- Create: `src/trade_trace/migrations/__init__.py`
- Create: `src/trade_trace/migrations/runner.py`
- Create: `tests/test_migrations.py`

- [ ] **Step 1: Failing test for migration runner**

`tests/test_migrations.py`:
```python
from pathlib import Path

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate, current_version


def test_migrate_creates_schema_versions_and_applies(tmp_path: Path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    v = current_version(conn)
    assert v >= 1
    rows = conn.execute("SELECT version FROM schema_versions ORDER BY version").fetchall()
    assert [r["version"] for r in rows] == list(range(1, v + 1))


def test_migrate_is_idempotent(tmp_path: Path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    v1 = current_version(conn)
    migrate(conn)
    v2 = current_version(conn)
    assert v1 == v2
```

- [ ] **Step 2: Run test, confirm fail**

Run: `pytest tests/test_migrations.py -v`
Expected: `ModuleNotFoundError`

- [ ] **Step 3: Implement runner**

`src/trade_trace/migrations/__init__.py`:
```python
```

`src/trade_trace/migrations/runner.py`:
```python
"""Minimal forward-only migration runner.

Each migration is a module under `trade_trace.migrations` named
`m{NNNN}_{slug}` exporting `VERSION: int` and `apply(conn)`. The runner
discovers them by listing the package directory and applies any whose
version isn't recorded in `schema_versions` yet.
"""
from __future__ import annotations

import importlib
import pkgutil
import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: callable


def _discover() -> list[Migration]:
    import trade_trace.migrations as pkg

    out: list[Migration] = []
    for _finder, name, _ispkg in pkgutil.iter_modules(pkg.__path__):
        if not name.startswith("m"):
            continue
        mod = importlib.import_module(f"trade_trace.migrations.{name}")
        if not hasattr(mod, "VERSION") or not hasattr(mod, "apply"):
            continue
        out.append(Migration(version=int(mod.VERSION), name=name, apply=mod.apply))
    out.sort(key=lambda m: m.version)
    return out


def _ensure_versions_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_versions (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )"""
    )


def current_version(conn: sqlite3.Connection) -> int:
    _ensure_versions_table(conn)
    row = conn.execute("SELECT MAX(version) AS v FROM schema_versions").fetchone()
    return int(row["v"] or 0)


def migrate(conn: sqlite3.Connection) -> None:
    _ensure_versions_table(conn)
    applied = {
        r["version"]
        for r in conn.execute("SELECT version FROM schema_versions").fetchall()
    }
    for m in _discover():
        if m.version in applied:
            continue
        conn.execute("BEGIN")
        try:
            m.apply(conn)
            conn.execute(
                "INSERT INTO schema_versions (version, name) VALUES (?, ?)",
                (m.version, m.name),
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
```

- [ ] **Step 4: Add a dummy migration so the test has something to apply**

`src/trade_trace/migrations/m0001_bootstrap.py`:
```python
"""Bootstrap migration — `config` table for runtime settings."""
from __future__ import annotations

import sqlite3

VERSION = 1


def apply(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )"""
    )
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_migrations.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/trade_trace/migrations tests/test_migrations.py
git commit -m "feat(migrations): forward-only runner + config table bootstrap"
```

---

### Task 0.4: Events + outbox tables (project invariant)

**Files:**
- Create: `src/trade_trace/migrations/m0002_events.py`
- Modify: `tests/test_migrations.py:1-30` — add new assertions

- [ ] **Step 1: Extend test to assert events/outbox tables exist**

Append to `tests/test_migrations.py`:
```python
def test_events_and_outbox_tables_present(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    tables = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert {"events", "outbox"}.issubset(tables)


def test_events_unique_idempotency(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    conn.execute(
        "INSERT INTO events (event_type, subject_kind, subject_id, payload_json, actor_id, idempotency_key) "
        "VALUES (?,?,?,?,?,?)",
        ("memory_node.retained", "memory_node", "m1", "{}", "agent:test", "k1"),
    )
    import sqlite3
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO events (event_type, subject_kind, subject_id, payload_json, actor_id, idempotency_key) "
            "VALUES (?,?,?,?,?,?)",
            ("memory_node.retained", "memory_node", "m1", "{}", "agent:test", "k1"),
        )
```

- [ ] **Step 2: Run test, confirm fail**

Run: `pytest tests/test_migrations.py -v`
Expected: events/outbox table not found.

- [ ] **Step 3: Add migration**

`src/trade_trace/migrations/m0002_events.py`:
```python
"""Event log + outbox tables. Project-wide invariant: every committed write emits an event row."""
from __future__ import annotations

import sqlite3

VERSION = 2


def apply(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            subject_kind TEXT NOT NULL,
            subject_id TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            idempotency_key TEXT,
            request_id TEXT,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE UNIQUE INDEX events_idem_uniq
            ON events(event_type, actor_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        CREATE INDEX events_subject ON events(subject_kind, subject_id);

        CREATE TABLE outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL REFERENCES events(id),
            export_kind TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('pending','exported','failed')),
            exported_at TEXT,
            error_text TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX outbox_state ON outbox(state);
        """
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_migrations.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/migrations/m0002_events.py tests/test_migrations.py
git commit -m "feat(migrations): events + outbox tables with idempotency uniqueness"
```

---

## Phase 1: Memory Schema + Endpoint Stubs

### Task 1.1: Endpoint stubs (instruments, venues, decisions, playbook_versions)

These are placeholder tables with only `id`/`created_at` columns. M1 ledger plan replaces them with full schemas. Stubs let edge validation work today.

**Files:**
- Create: `src/trade_trace/migrations/m0003_endpoint_stubs.py`
- Modify: `tests/test_migrations.py` — assert stubs exist

- [ ] **Step 1: Extend test**

Append to `tests/test_migrations.py`:
```python
def test_endpoint_stubs_present(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    for t in ("instruments", "venues", "decisions", "theses", "forecasts",
              "outcomes", "positions", "snapshots", "reviews",
              "playbook_versions", "sources"):
        assert t in tables, f"missing stub: {t}"
```

- [ ] **Step 2: Run test, confirm fail**

Run: `pytest tests/test_migrations.py::test_endpoint_stubs_present -v`
Expected: missing table.

- [ ] **Step 3: Add migration**

`src/trade_trace/migrations/m0003_endpoint_stubs.py`:
```python
"""Endpoint stubs for edge validation.

Each table carries only `id TEXT PRIMARY KEY` and a `created_at` column.
The M1 ledger plan will ALTER these tables to add real columns.
"""
from __future__ import annotations

import sqlite3

VERSION = 3

ENDPOINT_KINDS = (
    "instruments", "venues", "decisions", "theses", "forecasts",
    "outcomes", "positions", "snapshots", "reviews",
    "playbook_versions", "sources",
)


def apply(conn: sqlite3.Connection) -> None:
    for name in ENDPOINT_KINDS:
        conn.execute(
            f"""CREATE TABLE {name} (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            )"""
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_migrations.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/migrations/m0003_endpoint_stubs.py tests/test_migrations.py
git commit -m "feat(migrations): endpoint stubs for edge validation"
```

---

### Task 1.2: Memory schema (memory_nodes, memory_node_stats, FTS5)

**Files:**
- Create: `src/trade_trace/migrations/m0004_memory.py`
- Create: `tests/test_memory_schema.py`

- [ ] **Step 1: Failing test**

`tests/test_memory_schema.py`:
```python
from pathlib import Path

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate


def test_memory_nodes_kind_check(tmp_path: Path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    import sqlite3
    import pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO memory_nodes (id, node_type, body, actor_id) VALUES (?,?,?,?)",
            ("n1", "bogus_kind", "x", "agent:test"),
        )


def test_memory_nodes_fts_populated_on_insert(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    conn.execute(
        "INSERT INTO memory_nodes (id, node_type, title, body, actor_id) "
        "VALUES (?,?,?,?,?)",
        ("n1", "observation", "Liquidity note", "thin polymarket spreads widen", "agent:test"),
    )
    rows = conn.execute(
        "SELECT id FROM memory_nodes_fts WHERE memory_nodes_fts MATCH ?",
        ("polymarket",),
    ).fetchall()
    assert [r["id"] for r in rows] == ["n1"]


def test_memory_node_stats_default_zero(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(memory_node_stats)").fetchall()}
    assert {"memory_node_id", "recall_count", "last_recalled_at", "updated_at"}.issubset(cols)
```

- [ ] **Step 2: Run, confirm fail**

Run: `pytest tests/test_memory_schema.py -v`
Expected: missing tables.

- [ ] **Step 3: Migration**

`src/trade_trace/migrations/m0004_memory.py`:
```python
"""Memory layer schema: memory_nodes, memory_node_stats, FTS5 index."""
from __future__ import annotations

import sqlite3

VERSION = 4


def apply(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE memory_nodes (
            id TEXT PRIMARY KEY,
            node_type TEXT NOT NULL
                CHECK (node_type IN ('observation','reflection','rule')),
            version INTEGER NOT NULL DEFAULT 1,
            parent_node_id TEXT REFERENCES memory_nodes(id),
            title TEXT,
            body TEXT NOT NULL,
            meta_json TEXT NOT NULL DEFAULT '{}',
            confidence_base REAL NOT NULL DEFAULT 1.0
                CHECK (confidence_base BETWEEN 0.0 AND 1.0),
            decay_rate_per_day REAL NOT NULL DEFAULT 0.002
                CHECK (decay_rate_per_day >= 0.0),
            embedding_provider TEXT,
            embedding_model TEXT,
            embedding_dim INTEGER,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            actor_id TEXT NOT NULL
        );
        CREATE INDEX memory_nodes_type_created ON memory_nodes(node_type, created_at);

        CREATE TABLE memory_node_stats (
            memory_node_id TEXT PRIMARY KEY REFERENCES memory_nodes(id),
            recall_count INTEGER NOT NULL DEFAULT 0,
            last_recalled_at TEXT,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );

        CREATE VIRTUAL TABLE memory_nodes_fts USING fts5(
            id UNINDEXED,
            title,
            body,
            content=''
        );

        CREATE TRIGGER memory_nodes_ai_fts AFTER INSERT ON memory_nodes BEGIN
            INSERT INTO memory_nodes_fts(id, title, body)
                VALUES (new.id, coalesce(new.title,''), new.body);
        END;
        """
    )
```

- [ ] **Step 4: Run, confirm pass**

Run: `pytest tests/test_memory_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/migrations/m0004_memory.py tests/test_memory_schema.py
git commit -m "feat(memory): memory_nodes + stats + FTS5 with insert trigger"
```

---

### Task 1.3: Edges + signals schema

**Files:**
- Create: `src/trade_trace/migrations/m0005_edges_signals.py`
- Modify: `tests/test_memory_schema.py` — add edge and signal assertions

- [ ] **Step 1: Extend tests**

Append to `tests/test_memory_schema.py`:
```python
def test_edges_unique_per_combination(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    conn.execute("INSERT INTO memory_nodes (id, node_type, body, actor_id) VALUES (?,?,?,?)",
                 ("a", "observation", "x", "agent:test"))
    conn.execute("INSERT INTO memory_nodes (id, node_type, body, actor_id) VALUES (?,?,?,?)",
                 ("b", "reflection", "y", "agent:test"))
    conn.execute(
        "INSERT INTO edges (id, source_kind, source_id, target_kind, target_id, edge_type, actor_id) "
        "VALUES (?,?,?,?,?,?,?)",
        ("e1", "memory_node", "b", "memory_node", "a", "derived_from", "agent:test"),
    )
    import sqlite3, pytest
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO edges (id, source_kind, source_id, target_kind, target_id, edge_type, actor_id) "
            "VALUES (?,?,?,?,?,?,?)",
            ("e2", "memory_node", "b", "memory_node", "a", "derived_from", "agent:test"),
        )


def test_signals_table_present(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(signals)").fetchall()}
    assert {"id", "kind", "severity", "body", "meta_json", "related_refs_json",
            "created_at", "expires_at"}.issubset(cols)
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Migration**

`src/trade_trace/migrations/m0005_edges_signals.py`:
```python
"""Edges and signals tables."""
from __future__ import annotations

import sqlite3

VERSION = 5

EDGE_TYPES = (
    "about", "derived_from", "supports", "contradicts",
    "supersedes", "violates", "follows",
)

ENDPOINT_KINDS = (
    "memory_node", "decision", "thesis", "position", "forecast",
    "outcome", "snapshot", "review", "playbook_version",
    "source", "instrument", "venue", "signal",
)


def apply(conn: sqlite3.Connection) -> None:
    edge_types_sql = ",".join(f"'{t}'" for t in EDGE_TYPES)
    endpoint_kinds_sql = ",".join(f"'{k}'" for k in ENDPOINT_KINDS)
    conn.executescript(
        f"""
        CREATE TABLE edges (
            id TEXT PRIMARY KEY,
            source_kind TEXT NOT NULL CHECK (source_kind IN ({endpoint_kinds_sql})),
            source_id TEXT NOT NULL,
            target_kind TEXT NOT NULL CHECK (target_kind IN ({endpoint_kinds_sql})),
            target_id TEXT NOT NULL,
            edge_type TEXT NOT NULL CHECK (edge_type IN ({edge_types_sql})),
            weight REAL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            actor_id TEXT NOT NULL,
            UNIQUE (source_kind, source_id, target_kind, target_id, edge_type)
        );
        CREATE INDEX edges_from ON edges(source_kind, source_id);
        CREATE INDEX edges_to ON edges(target_kind, target_id);
        CREATE INDEX edges_type ON edges(edge_type);

        CREATE TABLE signals (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            severity TEXT NOT NULL CHECK (severity IN ('info','warn','critical')),
            body TEXT NOT NULL,
            meta_json TEXT NOT NULL DEFAULT '{{}}',
            related_refs_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            expires_at TEXT
        );
        CREATE INDEX signals_kind_created ON signals(kind, created_at);
        """
    )
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_memory_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/migrations/m0005_edges_signals.py tests/test_memory_schema.py
git commit -m "feat(memory): edges with type checks + signals table"
```

---

## Phase 2: Edge Validation + Write

### Task 2.1: Endpoint kind/id validator

**Files:**
- Create: `src/trade_trace/edges.py`
- Create: `tests/test_edges.py`

- [ ] **Step 1: Failing test**

`tests/test_edges.py`:
```python
from pathlib import Path

import pytest

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate
from trade_trace.edges import (
    EdgeRef, validate_endpoint, EndpointNotFoundError, UnknownEndpointKindError,
)


def _setup(tmp_path: Path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    conn.execute("INSERT INTO memory_nodes (id, node_type, body, actor_id) VALUES (?,?,?,?)",
                 ("n1", "observation", "x", "agent:test"))
    conn.execute("INSERT INTO decisions (id) VALUES (?)", ("d1",))
    return conn


def test_validate_endpoint_ok(tmp_path):
    conn = _setup(tmp_path)
    validate_endpoint(conn, EdgeRef(kind="memory_node", id="n1"))
    validate_endpoint(conn, EdgeRef(kind="decision", id="d1"))


def test_validate_endpoint_missing_id(tmp_path):
    conn = _setup(tmp_path)
    with pytest.raises(EndpointNotFoundError):
        validate_endpoint(conn, EdgeRef(kind="memory_node", id="missing"))


def test_validate_endpoint_unknown_kind(tmp_path):
    conn = _setup(tmp_path)
    with pytest.raises(UnknownEndpointKindError):
        validate_endpoint(conn, EdgeRef(kind="banana", id="n1"))
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement**

`src/trade_trace/edges.py`:
```python
"""Edge endpoint validation + write helpers."""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass

# Mirrors m0005 ENDPOINT_KINDS but lives here for runtime use.
ENDPOINT_KINDS: dict[str, str] = {
    "memory_node": "memory_nodes",
    "decision": "decisions",
    "thesis": "theses",
    "position": "positions",
    "forecast": "forecasts",
    "outcome": "outcomes",
    "snapshot": "snapshots",
    "review": "reviews",
    "playbook_version": "playbook_versions",
    "source": "sources",
    "instrument": "instruments",
    "venue": "venues",
    "signal": "signals",
}

EDGE_TYPES = frozenset({
    "about", "derived_from", "supports", "contradicts",
    "supersedes", "violates", "follows",
})


class UnknownEndpointKindError(ValueError):
    pass


class EndpointNotFoundError(LookupError):
    pass


class UnknownEdgeTypeError(ValueError):
    pass


@dataclass(frozen=True)
class EdgeRef:
    kind: str
    id: str


@dataclass(frozen=True)
class WrittenEdge:
    id: str
    source: EdgeRef
    target: EdgeRef
    edge_type: str


def validate_endpoint(conn: sqlite3.Connection, ref: EdgeRef) -> None:
    table = ENDPOINT_KINDS.get(ref.kind)
    if table is None:
        raise UnknownEndpointKindError(f"unknown endpoint kind: {ref.kind}")
    row = conn.execute(
        f"SELECT 1 FROM {table} WHERE id = ?", (ref.id,)
    ).fetchone()
    if row is None:
        raise EndpointNotFoundError(f"{ref.kind}:{ref.id} not found")


def write_edge(
    conn: sqlite3.Connection,
    source: EdgeRef,
    target: EdgeRef,
    edge_type: str,
    actor_id: str,
    weight: float | None = None,
) -> WrittenEdge:
    if edge_type not in EDGE_TYPES:
        raise UnknownEdgeTypeError(f"unknown edge type: {edge_type}")
    validate_endpoint(conn, source)
    validate_endpoint(conn, target)
    edge_id = f"edge_{uuid.uuid4().hex[:16]}"
    conn.execute(
        "INSERT INTO edges (id, source_kind, source_id, target_kind, target_id, edge_type, weight, actor_id) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (edge_id, source.kind, source.id, target.kind, target.id, edge_type, weight, actor_id),
    )
    return WrittenEdge(id=edge_id, source=source, target=target, edge_type=edge_type)
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_edges.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/edges.py tests/test_edges.py
git commit -m "feat(edges): endpoint validation + write helper"
```

---

### Task 2.2: `write_edge` end-to-end test + duplicate handling

**Files:**
- Modify: `src/trade_trace/edges.py` — add `DuplicateEdgeError`
- Modify: `tests/test_edges.py` — extend

- [ ] **Step 1: Add failing tests**

Append to `tests/test_edges.py`:
```python
from trade_trace.edges import write_edge, DuplicateEdgeError, UnknownEdgeTypeError


def test_write_edge_inserts_row(tmp_path):
    conn = _setup(tmp_path)
    e = write_edge(conn, EdgeRef("memory_node", "n1"), EdgeRef("decision", "d1"),
                   "about", actor_id="agent:test")
    row = conn.execute(
        "SELECT edge_type, source_id, target_id FROM edges WHERE id=?", (e.id,)
    ).fetchone()
    assert row["edge_type"] == "about"
    assert row["source_id"] == "n1"
    assert row["target_id"] == "d1"


def test_write_edge_duplicate_raises(tmp_path):
    conn = _setup(tmp_path)
    write_edge(conn, EdgeRef("memory_node", "n1"), EdgeRef("decision", "d1"),
               "about", actor_id="agent:test")
    with pytest.raises(DuplicateEdgeError):
        write_edge(conn, EdgeRef("memory_node", "n1"), EdgeRef("decision", "d1"),
                   "about", actor_id="agent:test")


def test_write_edge_unknown_type(tmp_path):
    conn = _setup(tmp_path)
    with pytest.raises(UnknownEdgeTypeError):
        write_edge(conn, EdgeRef("memory_node", "n1"), EdgeRef("decision", "d1"),
                   "links", actor_id="agent:test")
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Update `write_edge` to translate IntegrityError → DuplicateEdgeError**

Replace `write_edge` and add the error class in `src/trade_trace/edges.py`:
```python
class DuplicateEdgeError(ValueError):
    pass


def write_edge(
    conn: sqlite3.Connection,
    source: EdgeRef,
    target: EdgeRef,
    edge_type: str,
    actor_id: str,
    weight: float | None = None,
) -> WrittenEdge:
    if edge_type not in EDGE_TYPES:
        raise UnknownEdgeTypeError(f"unknown edge type: {edge_type}")
    validate_endpoint(conn, source)
    validate_endpoint(conn, target)
    edge_id = f"edge_{uuid.uuid4().hex[:16]}"
    try:
        conn.execute(
            "INSERT INTO edges (id, source_kind, source_id, target_kind, target_id, edge_type, weight, actor_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (edge_id, source.kind, source.id, target.kind, target.id, edge_type, weight, actor_id),
        )
    except sqlite3.IntegrityError as e:
        if "UNIQUE" in str(e):
            raise DuplicateEdgeError(
                f"edge already exists: {source.kind}:{source.id} -{edge_type}-> {target.kind}:{target.id}"
            ) from e
        raise
    return WrittenEdge(id=edge_id, source=source, target=target, edge_type=edge_type)
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_edges.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/edges.py tests/test_edges.py
git commit -m "feat(edges): duplicate-edge detection + unknown-type error"
```

---

## Phase 3: Memory Write Path (`retain`)

### Task 3.1: Pydantic input model + `retain` core write

**Files:**
- Create: `src/trade_trace/memory/__init__.py`
- Create: `src/trade_trace/memory/retain.py`
- Create: `src/trade_trace/memory/models.py`
- Create: `tests/test_memory_retain.py`

- [ ] **Step 1: Failing test**

`tests/test_memory_retain.py`:
```python
from pathlib import Path

import pytest

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate
from trade_trace.memory.retain import retain
from trade_trace.memory.models import RetainInput


def _conn(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    return conn


def test_retain_writes_observation(tmp_path):
    conn = _conn(tmp_path)
    out = retain(conn, RetainInput(
        node_type="observation",
        body="thin polymarket spreads widen near resolution",
        actor_id="agent:test",
    ))
    row = conn.execute(
        "SELECT node_type, body, decay_rate_per_day FROM memory_nodes WHERE id=?",
        (out.node_id,),
    ).fetchone()
    assert row["node_type"] == "observation"
    assert row["body"] == "thin polymarket spreads widen near resolution"
    # Default decay for observation is 0.003 per memory-layer.md §3.1
    assert row["decay_rate_per_day"] == pytest.approx(0.003)


def test_retain_unknown_node_type_rejected(tmp_path):
    conn = _conn(tmp_path)
    with pytest.raises(ValueError):
        retain(conn, RetainInput(node_type="bogus", body="x", actor_id="agent:test"))


def test_retain_emits_event(tmp_path):
    conn = _conn(tmp_path)
    out = retain(conn, RetainInput(node_type="reflection", body="y", actor_id="agent:test"))
    ev = conn.execute(
        "SELECT event_type, subject_id FROM events WHERE subject_id=?",
        (out.node_id,),
    ).fetchone()
    assert ev["event_type"] == "memory_node.retained"
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement**

`src/trade_trace/memory/__init__.py`:
```python
```

`src/trade_trace/memory/models.py`:
```python
"""Pydantic schemas for memory inputs/outputs."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

NodeType = Literal["observation", "reflection", "rule"]

DEFAULT_DECAY_BY_KIND: dict[NodeType, float] = {
    "observation": 0.003,
    "reflection": 0.002,
    "rule": 0.0,
}


class EdgeSpec(BaseModel):
    edge_type: Literal["about", "derived_from", "supports", "contradicts",
                       "supersedes", "violates", "follows"]
    target_kind: str
    target_id: str
    weight: float | None = None


class RetainInput(BaseModel):
    node_type: NodeType
    body: str = Field(min_length=1)
    title: str | None = None
    tags: list[str] = Field(default_factory=list)
    meta: dict = Field(default_factory=dict)
    confidence_base: float = Field(default=1.0, ge=0.0, le=1.0)
    decay_rate_per_day: float | None = Field(default=None, ge=0.0)
    edges: list[EdgeSpec] = Field(default_factory=list)
    actor_id: str
    idempotency_key: str | None = None


class RetainOutput(BaseModel):
    node_id: str
    event_id: int
    edge_ids: list[str] = Field(default_factory=list)
```

`src/trade_trace/memory/retain.py`:
```python
"""memory.retain — write a memory node + optional outgoing edges, emit event."""
from __future__ import annotations

import json
import sqlite3
import uuid

from trade_trace.edges import EdgeRef, write_edge
from trade_trace.memory.models import (
    DEFAULT_DECAY_BY_KIND, RetainInput, RetainOutput,
)


def retain(conn: sqlite3.Connection, inp: RetainInput) -> RetainOutput:
    """Write a memory node and any specified outgoing edges atomically."""
    node_id = f"mn_{uuid.uuid4().hex[:16]}"
    decay = inp.decay_rate_per_day
    if decay is None:
        decay = DEFAULT_DECAY_BY_KIND[inp.node_type]

    conn.execute("BEGIN")
    try:
        conn.execute(
            "INSERT INTO memory_nodes (id, node_type, title, body, meta_json, "
            "confidence_base, decay_rate_per_day, actor_id) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (node_id, inp.node_type, inp.title, inp.body,
             json.dumps({**inp.meta, "tags": inp.tags}),
             inp.confidence_base, decay, inp.actor_id),
        )

        written_edges: list[str] = []
        for spec in inp.edges:
            e = write_edge(
                conn,
                EdgeRef("memory_node", node_id),
                EdgeRef(spec.target_kind, spec.target_id),
                spec.edge_type,
                actor_id=inp.actor_id,
                weight=spec.weight,
            )
            written_edges.append(e.id)

        cur = conn.execute(
            "INSERT INTO events (event_type, subject_kind, subject_id, payload_json, "
            "actor_id, idempotency_key) VALUES (?,?,?,?,?,?)",
            ("memory_node.retained", "memory_node", node_id,
             json.dumps({"node_type": inp.node_type, "edge_ids": written_edges}),
             inp.actor_id, inp.idempotency_key),
        )
        event_id = cur.lastrowid

        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    return RetainOutput(node_id=node_id, event_id=event_id, edge_ids=written_edges)
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_memory_retain.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/memory tests/test_memory_retain.py
git commit -m "feat(memory): retain writes node + edges + event atomically"
```

---

### Task 3.2: Idempotency replay

**Files:**
- Modify: `src/trade_trace/memory/retain.py`
- Modify: `tests/test_memory_retain.py`

- [ ] **Step 1: Add idempotency test**

Append to `tests/test_memory_retain.py`:
```python
def test_retain_idempotency_replay(tmp_path):
    conn = _conn(tmp_path)
    a = retain(conn, RetainInput(node_type="observation", body="x",
                                 actor_id="agent:test", idempotency_key="k1"))
    b = retain(conn, RetainInput(node_type="observation", body="x",
                                 actor_id="agent:test", idempotency_key="k1"))
    assert a.node_id == b.node_id
    assert a.event_id == b.event_id
    n = conn.execute("SELECT COUNT(*) AS n FROM memory_nodes").fetchone()["n"]
    assert n == 1
```

- [ ] **Step 2: Run, confirm fail** (will create two rows today)

- [ ] **Step 3: Add idempotency lookup to `retain`**

Insert near the top of the function body:
```python
    if inp.idempotency_key is not None:
        existing = conn.execute(
            "SELECT id, subject_id, payload_json FROM events "
            "WHERE event_type = 'memory_node.retained' AND actor_id = ? "
            "AND idempotency_key = ?",
            (inp.actor_id, inp.idempotency_key),
        ).fetchone()
        if existing is not None:
            payload = json.loads(existing["payload_json"])
            return RetainOutput(
                node_id=existing["subject_id"],
                event_id=int(existing["id"]),
                edge_ids=list(payload.get("edge_ids", [])),
            )
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_memory_retain.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/memory/retain.py tests/test_memory_retain.py
git commit -m "feat(memory): retain idempotency replay via events lookup"
```

---

## Phase 4: Retrieval

### Task 4.1: BM25 retriever

**Files:**
- Create: `src/trade_trace/retrieval/__init__.py`
- Create: `src/trade_trace/retrieval/bm25.py`
- Create: `tests/test_recall_bm25.py`

- [ ] **Step 1: Failing test**

`tests/test_recall_bm25.py`:
```python
from pathlib import Path

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate
from trade_trace.memory.retain import retain
from trade_trace.memory.models import RetainInput
from trade_trace.retrieval.bm25 import bm25_search


def _seed(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    retain(conn, RetainInput(node_type="observation",
                             body="NVDA earnings gap fade pattern in semis",
                             actor_id="agent:test"))
    retain(conn, RetainInput(node_type="observation",
                             body="thin polymarket spreads widen near resolution",
                             actor_id="agent:test"))
    return conn


def test_bm25_returns_matches(tmp_path):
    conn = _seed(tmp_path)
    hits = bm25_search(conn, "polymarket", k=5)
    assert len(hits) == 1
    assert "polymarket" in hits[0].body.lower()
    assert hits[0].rank == 1


def test_bm25_returns_empty_for_no_match(tmp_path):
    conn = _seed(tmp_path)
    assert bm25_search(conn, "bitcoin halving", k=5) == []
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement**

`src/trade_trace/retrieval/__init__.py`:
```python
```

`src/trade_trace/retrieval/bm25.py`:
```python
"""BM25 retrieval over memory_nodes_fts."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Hit:
    node_id: str
    rank: int
    raw_score: float
    title: str | None
    body: str
    node_type: str
    created_at: str
    confidence_base: float
    decay_rate_per_day: float


def bm25_search(conn: sqlite3.Connection, query: str, k: int = 20) -> list[Hit]:
    rows = conn.execute(
        """
        SELECT mn.id, mn.title, mn.body, mn.node_type, mn.created_at,
               mn.confidence_base, mn.decay_rate_per_day,
               bm25(memory_nodes_fts) AS raw_score
        FROM memory_nodes_fts
        JOIN memory_nodes mn ON mn.id = memory_nodes_fts.id
        WHERE memory_nodes_fts MATCH ?
        ORDER BY raw_score
        LIMIT ?
        """,
        (query, k),
    ).fetchall()
    return [
        Hit(
            node_id=r["id"], rank=i + 1, raw_score=float(r["raw_score"]),
            title=r["title"], body=r["body"], node_type=r["node_type"],
            created_at=r["created_at"],
            confidence_base=float(r["confidence_base"]),
            decay_rate_per_day=float(r["decay_rate_per_day"]),
        )
        for i, r in enumerate(rows)
    ]
```

Note: SQLite's `bm25()` returns a score where lower is better; we sort ASC and use the position as rank for RRF later.

- [ ] **Step 4: Run**

Run: `pytest tests/test_recall_bm25.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/retrieval tests/test_recall_bm25.py
git commit -m "feat(retrieval): BM25 search over FTS5 index"
```

---

### Task 4.2: Confidence model

**Files:**
- Create: `src/trade_trace/memory/confidence.py`
- Create: `tests/test_confidence.py`

- [ ] **Step 1: Failing test**

`tests/test_confidence.py`:
```python
import math
from datetime import datetime, timedelta, timezone

from trade_trace.memory.confidence import effective_confidence


def test_no_decay_no_supersession():
    now = datetime.now(timezone.utc)
    c = effective_confidence(
        confidence_base=1.0,
        decay_rate_per_day=0.0,
        created_at=now,
        now=now,
        is_superseded=False,
    )
    assert c == 1.0


def test_decay_after_100_days():
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=100)
    c = effective_confidence(
        confidence_base=1.0,
        decay_rate_per_day=0.003,
        created_at=created,
        now=now,
        is_superseded=False,
    )
    assert c == pytest.approx(math.exp(-0.3), rel=1e-6)


def test_supersession_discount():
    now = datetime.now(timezone.utc)
    c = effective_confidence(
        confidence_base=1.0,
        decay_rate_per_day=0.0,
        created_at=now,
        now=now,
        is_superseded=True,
    )
    assert c == pytest.approx(0.25)


import pytest  # noqa: E402 — used in approx above
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement**

`src/trade_trace/memory/confidence.py`:
```python
"""Effective confidence: decay + supersession.

Edge-density factor (supports/contradicts boost) is deferred to P1 per
docs/architecture/memory-layer.md §6.
"""
from __future__ import annotations

import math
from datetime import datetime

SUPERSESSION_DISCOUNT = 0.25


def effective_confidence(
    *,
    confidence_base: float,
    decay_rate_per_day: float,
    created_at: datetime,
    now: datetime,
    is_superseded: bool,
) -> float:
    age_days = max(0.0, (now - created_at).total_seconds() / 86400.0)
    decayed = confidence_base * math.exp(-decay_rate_per_day * age_days)
    if is_superseded:
        decayed *= SUPERSESSION_DISCOUNT
    return max(0.0, min(1.0, decayed))
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_confidence.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/memory/confidence.py tests/test_confidence.py
git commit -m "feat(memory): effective confidence (decay + supersession)"
```

---

### Task 4.3: Temporal weight retriever

**Files:**
- Create: `src/trade_trace/retrieval/temporal.py`
- Create: `tests/test_recall_temporal.py`

- [ ] **Step 1: Failing test**

`tests/test_recall_temporal.py`:
```python
from datetime import datetime, timedelta, timezone
from pathlib import Path

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate
from trade_trace.retrieval.temporal import temporal_rank


def test_temporal_rank_orders_newer_first(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    now = datetime.now(timezone.utc)
    older = (now - timedelta(days=10)).strftime("%Y-%m-%dT%H:%M:%fZ")
    newer = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%fZ")
    conn.execute(
        "INSERT INTO memory_nodes (id, node_type, body, actor_id, created_at) "
        "VALUES (?,?,?,?,?)",
        ("old", "observation", "x", "agent:test", older),
    )
    conn.execute(
        "INSERT INTO memory_nodes (id, node_type, body, actor_id, created_at) "
        "VALUES (?,?,?,?,?)",
        ("new", "observation", "y", "agent:test", newer),
    )
    hits = temporal_rank(conn, k=10, now=now)
    assert [h.node_id for h in hits] == ["new", "old"]
    assert hits[0].rank == 1
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement**

`src/trade_trace/retrieval/temporal.py`:
```python
"""Temporal retriever — exponential recency weight over all nodes."""
from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone

from trade_trace.retrieval.bm25 import Hit


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def temporal_rank(
    conn: sqlite3.Connection,
    k: int = 20,
    *,
    decay: float = 0.02,
    now: datetime | None = None,
) -> list[Hit]:
    now = now or datetime.now(timezone.utc)
    rows = conn.execute(
        "SELECT id, title, body, node_type, created_at, confidence_base, decay_rate_per_day "
        "FROM memory_nodes ORDER BY created_at DESC LIMIT ?",
        (k * 4,),  # over-fetch; we'll re-rank
    ).fetchall()
    scored: list[tuple[float, sqlite3.Row]] = []
    for r in rows:
        age_days = max(0.0, (now - _parse(r["created_at"])).total_seconds() / 86400.0)
        weight = math.exp(-decay * age_days)
        scored.append((weight, r))
    scored.sort(key=lambda t: -t[0])
    return [
        Hit(
            node_id=r["id"], rank=i + 1, raw_score=w,
            title=r["title"], body=r["body"], node_type=r["node_type"],
            created_at=r["created_at"],
            confidence_base=float(r["confidence_base"]),
            decay_rate_per_day=float(r["decay_rate_per_day"]),
        )
        for i, (w, r) in enumerate(scored[:k])
    ]
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_recall_temporal.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/retrieval/temporal.py tests/test_recall_temporal.py
git commit -m "feat(retrieval): temporal recency-weighted retriever"
```

---

### Task 4.4: RRF combiner + min_confidence filter

**Files:**
- Create: `src/trade_trace/retrieval/rrf.py`
- Create: `tests/test_recall_rrf.py`

- [ ] **Step 1: Failing test**

`tests/test_recall_rrf.py`:
```python
from datetime import datetime, timedelta, timezone

from trade_trace.retrieval.bm25 import Hit
from trade_trace.retrieval.rrf import fuse_rrf, FusionInput


def _hit(node_id: str, rank: int, age_days: int = 0) -> Hit:
    created = (datetime.now(timezone.utc) - timedelta(days=age_days)).strftime(
        "%Y-%m-%dT%H:%M:%fZ"
    )
    return Hit(node_id=node_id, rank=rank, raw_score=0.0,
               title=None, body="x", node_type="observation",
               created_at=created, confidence_base=1.0, decay_rate_per_day=0.0)


def test_rrf_combines_two_strategies():
    bm25 = [_hit("a", 1), _hit("b", 2)]
    temporal = [_hit("b", 1), _hit("c", 2)]
    fused = fuse_rrf({"bm25": FusionInput(hits=bm25, weight=1.0),
                      "temporal": FusionInput(hits=temporal, weight=1.0)},
                     k_rrf=60)
    ids = [f.hit.node_id for f in fused]
    # b appears in both → ranks highest
    assert ids[0] == "b"
    assert set(ids) == {"a", "b", "c"}


def test_rrf_applies_min_confidence_filter():
    old = _hit("a", 1, age_days=10_000)  # essentially zero effective confidence
    fresh = _hit("b", 2, age_days=0)
    # Give the old hit non-zero decay so the filter actually kicks in.
    old = Hit(**{**old.__dict__, "decay_rate_per_day": 0.01})
    fused = fuse_rrf({"bm25": FusionInput(hits=[old, fresh], weight=1.0)},
                     min_confidence=0.5)
    ids = [f.hit.node_id for f in fused]
    assert ids == ["b"]
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement**

`src/trade_trace/retrieval/rrf.py`:
```python
"""Reciprocal Rank Fusion combiner with confidence filtering."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from trade_trace.memory.confidence import effective_confidence
from trade_trace.retrieval.bm25 import Hit


@dataclass(frozen=True)
class FusionInput:
    hits: list[Hit]
    weight: float = 1.0


@dataclass(frozen=True)
class FusedRow:
    hit: Hit
    score: float
    top_strategy: str
    effective_confidence: float


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def fuse_rrf(
    inputs: dict[str, FusionInput],
    *,
    k_rrf: int = 60,
    min_confidence: float = 0.0,
    now: datetime | None = None,
) -> list[FusedRow]:
    now = now or datetime.now(timezone.utc)

    # node_id -> (total_score, top_strategy, hit)
    accum: dict[str, tuple[float, str, Hit]] = {}
    for strat, fi in inputs.items():
        for h in fi.hits:
            contrib = fi.weight / (k_rrf + h.rank)
            prev = accum.get(h.node_id)
            if prev is None or contrib > prev[0]:
                top = strat
                base = prev[0] if prev else 0.0
                accum[h.node_id] = (base + contrib, top, h)
            else:
                accum[h.node_id] = (prev[0] + contrib, prev[1], prev[2])

    rows: list[FusedRow] = []
    for node_id, (score, top, hit) in accum.items():
        eff = effective_confidence(
            confidence_base=hit.confidence_base,
            decay_rate_per_day=hit.decay_rate_per_day,
            created_at=_parse(hit.created_at),
            now=now,
            is_superseded=False,  # supersession lookup added in Task 4.5
        )
        if eff < min_confidence:
            continue
        rows.append(FusedRow(hit=hit, score=score, top_strategy=top,
                             effective_confidence=eff))
    rows.sort(key=lambda r: r.score, reverse=True)
    return rows
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_recall_rrf.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/retrieval/rrf.py tests/test_recall_rrf.py
git commit -m "feat(retrieval): RRF combiner with min_confidence filter"
```

---

### Task 4.5: Supersession-aware confidence in RRF

**Files:**
- Modify: `src/trade_trace/retrieval/rrf.py`
- Create: `tests/test_recall_supersession.py`

- [ ] **Step 1: Failing test**

`tests/test_recall_supersession.py`:
```python
from pathlib import Path

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate
from trade_trace.memory.retain import retain
from trade_trace.memory.models import RetainInput, EdgeSpec
from trade_trace.retrieval.bm25 import bm25_search
from trade_trace.retrieval.rrf import fuse_rrf, FusionInput


def test_superseded_node_demoted(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    old = retain(conn, RetainInput(node_type="reflection", body="liquidity rule v1",
                                   actor_id="agent:test"))
    new = retain(conn, RetainInput(
        node_type="reflection", body="liquidity rule v2 supersedes v1",
        actor_id="agent:test",
        edges=[EdgeSpec(edge_type="supersedes", target_kind="memory_node",
                        target_id=old.node_id)],
    ))
    hits = bm25_search(conn, "liquidity rule")
    fused = fuse_rrf({"bm25": FusionInput(hits=hits, weight=1.0)}, conn=conn)
    ids = [r.hit.node_id for r in fused]
    # both present, but v1 has lower effective confidence than v2
    eff = {r.hit.node_id: r.effective_confidence for r in fused}
    assert eff[old.node_id] < eff[new.node_id]
```

- [ ] **Step 2: Run, confirm fail** (`fuse_rrf` has no `conn` arg today)

- [ ] **Step 3: Add supersession lookup to `fuse_rrf`**

Modify signature and body in `rrf.py`:
```python
def fuse_rrf(
    inputs: dict[str, FusionInput],
    *,
    k_rrf: int = 60,
    min_confidence: float = 0.0,
    now: datetime | None = None,
    conn=None,  # sqlite3.Connection | None
) -> list[FusedRow]:
    now = now or datetime.now(timezone.utc)
    accum: dict[str, tuple[float, str, Hit]] = {}
    for strat, fi in inputs.items():
        for h in fi.hits:
            contrib = fi.weight / (k_rrf + h.rank)
            prev = accum.get(h.node_id)
            if prev is None:
                accum[h.node_id] = (contrib, strat, h)
            else:
                top = prev[1] if prev[0] >= contrib else strat
                accum[h.node_id] = (prev[0] + contrib, top, prev[2])

    superseded_ids: set[str] = set()
    if conn is not None and accum:
        placeholders = ",".join("?" for _ in accum)
        rows = conn.execute(
            f"SELECT target_id FROM edges WHERE edge_type='supersedes' "
            f"AND target_kind='memory_node' AND target_id IN ({placeholders})",
            tuple(accum.keys()),
        ).fetchall()
        superseded_ids = {r["target_id"] for r in rows}

    rows: list[FusedRow] = []
    for node_id, (score, top, hit) in accum.items():
        eff = effective_confidence(
            confidence_base=hit.confidence_base,
            decay_rate_per_day=hit.decay_rate_per_day,
            created_at=_parse(hit.created_at),
            now=now,
            is_superseded=node_id in superseded_ids,
        )
        if eff < min_confidence:
            continue
        rows.append(FusedRow(hit=hit, score=score, top_strategy=top,
                             effective_confidence=eff))
    rows.sort(key=lambda r: r.score, reverse=True)
    return rows
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_recall_supersession.py tests/test_recall_rrf.py -v`
Expected: PASS (existing RRF tests still pass since `conn=None` keeps old behavior)

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/retrieval/rrf.py tests/test_recall_supersession.py
git commit -m "feat(retrieval): RRF applies supersession discount via edges lookup"
```

---

### Task 4.6: Budget shaping (compact/max_chars/include_*)

**Files:**
- Create: `src/trade_trace/retrieval/budget.py`
- Create: `tests/test_recall_budget.py`

- [ ] **Step 1: Failing test**

`tests/test_recall_budget.py`:
```python
import pytest

from trade_trace.retrieval.budget import shape_rows, BudgetParams
from trade_trace.retrieval.bm25 import Hit


def _hit(body: str, node_id: str = "n") -> Hit:
    return Hit(node_id=node_id, rank=1, raw_score=0.0, title=None,
               body=body, node_type="observation",
               created_at="2026-05-18T12:00:00.000Z",
               confidence_base=1.0, decay_rate_per_day=0.0)


def test_compact_replaces_body_with_snippet():
    big = "x" * 1000
    out = shape_rows([_hit(big)], BudgetParams(compact=True), query="xxx")
    row = out["rows"][0]
    assert "body" not in row or row["body"] is None
    assert "snippet" in row.get("meta", {})


def test_max_chars_drops_lowest_scoring():
    rows_in = [_hit("a" * 500, "a"), _hit("b" * 500, "b"), _hit("c" * 500, "c")]
    out = shape_rows(rows_in, BudgetParams(max_chars=1200), query="a")
    # 3 rows of ~500 chars each + envelope > 1200; expect drops
    assert out["meta"]["budget_applied"] is True
    assert len(out["rows"]) < 3


def test_include_body_false():
    out = shape_rows([_hit("x" * 100)], BudgetParams(include_body=False), query="")
    assert "body" not in out["rows"][0]
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement**

`src/trade_trace/retrieval/budget.py`:
```python
"""Response shaping for memory.recall: compact, max_chars, include_*."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BudgetParams:
    max_chars: int | None = None
    compact: bool = False
    include_body: bool = True
    include_provenance: bool = True


SNIPPET_LEN = 240


def _snippet(body: str, query: str) -> str:
    if not query:
        return body[:SNIPPET_LEN]
    lower = body.lower()
    needle = query.lower().split()[0] if query.split() else ""
    idx = lower.find(needle) if needle else -1
    if idx < 0:
        return body[:SNIPPET_LEN]
    start = max(0, idx - SNIPPET_LEN // 2)
    end = min(len(body), start + SNIPPET_LEN)
    return body[start:end]


def _row(hit, params: BudgetParams, query: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "node_id": hit.node_id,
        "node_type": hit.node_type,
        "title": hit.title,
        "created_at": hit.created_at,
        "score": getattr(hit, "score", None),
        "strategy": getattr(hit, "top_strategy", None),
        "effective_confidence": getattr(hit, "effective_confidence", None),
    }
    meta: dict[str, Any] = {}
    underlying = getattr(hit, "hit", hit)  # FusedRow exposes .hit
    body = underlying.body
    if params.compact:
        meta["snippet"] = _snippet(body, query)
    elif params.include_body:
        out["body"] = body
    if not params.include_provenance:
        pass  # provenance not yet wired
    if meta:
        out["meta"] = meta
    return out


def shape_rows(hits: list, params: BudgetParams, *, query: str = "") -> dict[str, Any]:
    rows = [_row(h, params, query) for h in hits]
    payload = {"rows": rows, "meta": {"budget_applied": False}}

    if params.max_chars is not None:
        budget_applied = False
        while len(json.dumps(payload)) > params.max_chars and rows:
            # First, try switching to compact
            if not params.compact and rows[0].get("body") is not None:
                params = BudgetParams(
                    max_chars=params.max_chars,
                    compact=True,
                    include_body=False,
                    include_provenance=params.include_provenance,
                )
                rows = [_row(h, params, query) for h in hits]
                payload["rows"] = rows
                budget_applied = True
                continue
            rows.pop()
            payload["rows"] = rows
            budget_applied = True
        payload["meta"]["budget_applied"] = budget_applied
    return payload
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_recall_budget.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/retrieval/budget.py tests/test_recall_budget.py
git commit -m "feat(retrieval): budget shaping — compact, max_chars, include_*"
```

---

### Task 4.7: `memory.recall` orchestrator (BM25 + temporal + RRF + budget)

**Files:**
- Create: `src/trade_trace/memory/recall.py`
- Create: `tests/test_memory_recall.py`

- [ ] **Step 1: Failing test**

`tests/test_memory_recall.py`:
```python
from pathlib import Path

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate
from trade_trace.memory.retain import retain
from trade_trace.memory.recall import recall
from trade_trace.memory.models import RetainInput, RecallInput


def test_recall_returns_match_with_envelope_fields(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    retain(conn, RetainInput(node_type="observation",
                             body="NVDA earnings gap fade in semis",
                             actor_id="agent:test"))
    out = recall(conn, RecallInput(query="NVDA", k=5,
                                   strategies=["bm25", "temporal"]))
    assert len(out["rows"]) == 1
    r = out["rows"][0]
    assert "node_id" in r and "score" in r and "effective_confidence" in r
    assert r["node_type"] == "observation"


def test_recall_respects_max_chars(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    for i in range(5):
        retain(conn, RetainInput(node_type="observation",
                                 body=f"earnings observation {i} " + "z" * 300,
                                 actor_id="agent:test"))
    out = recall(conn, RecallInput(query="earnings", k=10, max_chars=500,
                                   strategies=["bm25"]))
    assert out["meta"]["budget_applied"] is True
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement**

Add `RecallInput` to `src/trade_trace/memory/models.py`:
```python
class RecallInput(BaseModel):
    query: str | None = None
    context_node_id: str | None = None
    strategies: list[Literal["bm25", "temporal", "semantic", "graph"]] = Field(
        default_factory=lambda: ["bm25", "temporal"]
    )
    k: int = Field(default=20, ge=1, le=200)
    max_chars: int | None = Field(default=None, ge=0)
    compact: bool = False
    include_body: bool = True
    include_provenance: bool = True
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    weights: dict[str, float] = Field(default_factory=dict)
```

`src/trade_trace/memory/recall.py`:
```python
"""memory.recall — orchestrate strategies, fuse via RRF, shape to budget."""
from __future__ import annotations

import sqlite3
from typing import Any

from trade_trace.memory.models import RecallInput
from trade_trace.retrieval.bm25 import bm25_search, Hit
from trade_trace.retrieval.temporal import temporal_rank
from trade_trace.retrieval.rrf import fuse_rrf, FusionInput
from trade_trace.retrieval.budget import shape_rows, BudgetParams


def _run_strategy(conn: sqlite3.Connection, name: str,
                  inp: RecallInput) -> list[Hit]:
    if name == "bm25":
        return bm25_search(conn, inp.query or "", k=inp.k) if inp.query else []
    if name == "temporal":
        return temporal_rank(conn, k=inp.k)
    if name == "semantic":
        from trade_trace.retrieval.semantic import semantic_search  # lazy
        return semantic_search(conn, inp.query or "", k=inp.k) if inp.query else []
    if name == "graph":
        from trade_trace.retrieval.graph import graph_neighbors  # lazy
        if inp.context_node_id is None:
            return []
        return graph_neighbors(conn, inp.context_node_id, k=inp.k)
    raise ValueError(f"unknown strategy: {name}")


def recall(conn: sqlite3.Connection, inp: RecallInput) -> dict[str, Any]:
    inputs: dict[str, FusionInput] = {}
    for s in inp.strategies:
        hits = _run_strategy(conn, s, inp)
        if hits:
            inputs[s] = FusionInput(hits=hits, weight=inp.weights.get(s, 1.0))

    fused = fuse_rrf(inputs, min_confidence=inp.min_confidence, conn=conn)
    fused = fused[: inp.k]

    payload = shape_rows(
        fused,
        BudgetParams(
            max_chars=inp.max_chars,
            compact=inp.compact,
            include_body=inp.include_body,
            include_provenance=inp.include_provenance,
        ),
        query=inp.query or "",
    )
    payload["meta"].setdefault("strategies_run", list(inputs.keys()))
    return payload
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_memory_recall.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/memory/recall.py src/trade_trace/memory/models.py tests/test_memory_recall.py
git commit -m "feat(memory): recall orchestrator with strategy + budget shaping"
```

---

### Task 4.8: Graph (1-hop) retriever

**Files:**
- Create: `src/trade_trace/retrieval/graph.py`
- Create: `tests/test_recall_graph.py`

- [ ] **Step 1: Failing test**

`tests/test_recall_graph.py`:
```python
from pathlib import Path

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate
from trade_trace.memory.retain import retain
from trade_trace.memory.models import RetainInput, EdgeSpec
from trade_trace.retrieval.graph import graph_neighbors


def test_graph_returns_one_hop_neighbors(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    a = retain(conn, RetainInput(node_type="observation", body="seed",
                                 actor_id="agent:test"))
    b = retain(conn, RetainInput(
        node_type="reflection", body="derived insight",
        actor_id="agent:test",
        edges=[EdgeSpec(edge_type="derived_from", target_kind="memory_node",
                        target_id=a.node_id)],
    ))
    c = retain(conn, RetainInput(node_type="observation", body="unrelated",
                                 actor_id="agent:test"))
    hits = graph_neighbors(conn, a.node_id, k=10)
    ids = {h.node_id for h in hits}
    assert b.node_id in ids
    assert c.node_id not in ids
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement**

`src/trade_trace/retrieval/graph.py`:
```python
"""Graph retriever — 1-hop BFS around a context memory_node.

Edge direction is collapsed: any neighbor reachable via an incoming or
outgoing edge whose other endpoint is a memory_node counts as a hit.
"""
from __future__ import annotations

import sqlite3

from trade_trace.retrieval.bm25 import Hit


def graph_neighbors(
    conn: sqlite3.Connection,
    context_node_id: str,
    *,
    k: int = 20,
    edge_types: list[str] | None = None,
) -> list[Hit]:
    type_filter = ""
    params: list = [context_node_id, context_node_id]
    if edge_types:
        type_filter = " AND edge_type IN (" + ",".join("?" for _ in edge_types) + ")"
        params.extend(edge_types)
        params.extend(edge_types)  # second branch in UNION
        params = [context_node_id, *edge_types, context_node_id, *edge_types]

    rows = conn.execute(
        f"""
        WITH neighbors AS (
            SELECT target_id AS neighbor_id FROM edges
            WHERE source_kind='memory_node' AND source_id=?
              AND target_kind='memory_node' {type_filter}
            UNION
            SELECT source_id AS neighbor_id FROM edges
            WHERE target_kind='memory_node' AND target_id=?
              AND source_kind='memory_node' {type_filter}
        )
        SELECT mn.id, mn.title, mn.body, mn.node_type, mn.created_at,
               mn.confidence_base, mn.decay_rate_per_day
        FROM memory_nodes mn
        JOIN neighbors n ON mn.id = n.neighbor_id
        LIMIT ?
        """,
        (*params, k),
    ).fetchall()
    return [
        Hit(node_id=r["id"], rank=i + 1, raw_score=1.0,
            title=r["title"], body=r["body"], node_type=r["node_type"],
            created_at=r["created_at"],
            confidence_base=float(r["confidence_base"]),
            decay_rate_per_day=float(r["decay_rate_per_day"]))
        for i, r in enumerate(rows)
    ]
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_recall_graph.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/retrieval/graph.py tests/test_recall_graph.py
git commit -m "feat(retrieval): 1-hop graph neighbor retriever"
```

---

## Phase 5: Embeddings

### Task 5.1: Provider interface + config

**Files:**
- Create: `src/trade_trace/embeddings/__init__.py`
- Create: `src/trade_trace/embeddings/provider.py`
- Create: `src/trade_trace/embeddings/registry.py`
- Create: `tests/test_embeddings_registry.py`

- [ ] **Step 1: Failing test**

`tests/test_embeddings_registry.py`:
```python
from pathlib import Path

import pytest

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate
from trade_trace.embeddings.registry import (
    set_provider, get_active_provider, ProviderConfig, NoProviderError,
)


def test_get_active_returns_none_by_default(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    with pytest.raises(NoProviderError):
        get_active_provider(conn)


def test_set_and_get_provider(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    set_provider(conn, ProviderConfig(name="local", model="BAAI/bge-small-en-v1.5", dim=384))
    p = get_active_provider(conn)
    assert p.name == "local"
    assert p.dim == 384
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement**

`src/trade_trace/embeddings/__init__.py`:
```python
```

`src/trade_trace/embeddings/provider.py`:
```python
"""Abstract embedding provider interface."""
from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    name: str
    model: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

`src/trade_trace/embeddings/registry.py`:
```python
"""Persisted provider configuration in `config` table."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

CONFIG_KEY = "embeddings.provider"


class NoProviderError(LookupError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    name: str  # "local" | "openai" | "none"
    model: str | None = None
    dim: int | None = None


def set_provider(conn: sqlite3.Connection, cfg: ProviderConfig) -> None:
    payload = json.dumps({"name": cfg.name, "model": cfg.model, "dim": cfg.dim})
    conn.execute(
        "INSERT INTO config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
        "updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
        (CONFIG_KEY, payload),
    )


def get_active_provider(conn: sqlite3.Connection) -> ProviderConfig:
    row = conn.execute("SELECT value FROM config WHERE key=?", (CONFIG_KEY,)).fetchone()
    if row is None:
        raise NoProviderError("no embedding provider configured")
    data = json.loads(row["value"])
    return ProviderConfig(name=data["name"], model=data.get("model"), dim=data.get("dim"))
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_embeddings_registry.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/embeddings tests/test_embeddings_registry.py
git commit -m "feat(embeddings): provider interface + persisted registry"
```

---

### Task 5.2: Local sentence-transformers provider with lazy model load

**Files:**
- Create: `src/trade_trace/embeddings/local.py`
- Create: `tests/test_embeddings_local.py`

- [ ] **Step 1: Failing test**

`tests/test_embeddings_local.py`:
```python
import pytest

from trade_trace.embeddings.local import LocalProvider


pytestmark = pytest.mark.slow  # marks first-run model download as slow


def test_local_provider_embeds_text():
    p = LocalProvider(model="BAAI/bge-small-en-v1.5")
    vecs = p.embed(["polymarket spreads widen", "NVDA earnings gap fade"])
    assert len(vecs) == 2
    assert len(vecs[0]) == p.dim == 384
    assert all(isinstance(x, float) for x in vecs[0])
```

Register the `slow` marker in `pyproject.toml` `[tool.pytest.ini_options]`:
```toml
markers = ["slow: tests that require network or heavy compute"]
```

- [ ] **Step 2: Run, confirm fail**

Run: `pytest -m slow tests/test_embeddings_local.py -v`
Expected: import error initially.

- [ ] **Step 3: Implement**

`src/trade_trace/embeddings/local.py`:
```python
"""Local sentence-transformers embedding provider.

Model weights are downloaded on first use via the sentence-transformers
HF cache. The cache directory is overridable with
`SENTENCE_TRANSFORMERS_HOME` if the caller wants to redirect it under
`$TRADE_TRACE_HOME/models/`.
"""
from __future__ import annotations

from functools import cached_property


class LocalProvider:
    name = "local"

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5") -> None:
        self.model = model

    @cached_property
    def _model(self):
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(self.model)

    @cached_property
    def dim(self) -> int:
        return int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> list[list[float]]:
        arr = self._model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
        return [v.astype(float).tolist() for v in arr]
```

- [ ] **Step 4: Run**

Run: `pytest -m slow tests/test_embeddings_local.py -v`
Expected: PASS (downloads ~130MB on first run; cached after).

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/embeddings/local.py tests/test_embeddings_local.py pyproject.toml
git commit -m "feat(embeddings): local sentence-transformers provider (bge-small)"
```

---

### Task 5.3: OpenAI provider with keyring-backed API key

**Files:**
- Create: `src/trade_trace/embeddings/openai_provider.py`
- Create: `src/trade_trace/embeddings/secrets.py`
- Create: `tests/test_embeddings_openai.py`

- [ ] **Step 1: Failing test (mocked)**

`tests/test_embeddings_openai.py`:
```python
from unittest.mock import patch, MagicMock

from trade_trace.embeddings.openai_provider import OpenAIProvider


def test_openai_embed_calls_api_and_returns_vectors():
    fake_resp = MagicMock()
    fake_resp.data = [MagicMock(embedding=[0.1] * 1536),
                      MagicMock(embedding=[0.2] * 1536)]
    fake_client = MagicMock()
    fake_client.embeddings.create.return_value = fake_resp

    p = OpenAIProvider(model="text-embedding-3-small", api_key="sk-test", client=fake_client)
    vecs = p.embed(["a", "b"])

    assert vecs == [[0.1] * 1536, [0.2] * 1536]
    fake_client.embeddings.create.assert_called_once_with(
        model="text-embedding-3-small", input=["a", "b"]
    )


def test_secrets_round_trip(tmp_path, monkeypatch):
    from trade_trace.embeddings import secrets as s
    calls = {}
    def fake_set(service, user, password):
        calls[(service, user)] = password
    def fake_get(service, user):
        return calls.get((service, user))
    monkeypatch.setattr(s, "_keyring_set", fake_set)
    monkeypatch.setattr(s, "_keyring_get", fake_get)

    s.store_api_key("openai", "sk-abc")
    assert s.read_api_key("openai") == "sk-abc"
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement secrets**

`src/trade_trace/embeddings/secrets.py`:
```python
"""OS keyring wrapper for embedding provider API keys.

Keys are never persisted in SQLite. The DB stores only the provider's
*name*; the key lives in the OS keyring under service
`trade-trace.embeddings.<provider>`.
"""
from __future__ import annotations

import keyring

SERVICE_PREFIX = "trade-trace.embeddings"


def _keyring_set(service: str, user: str, password: str) -> None:
    keyring.set_password(service, user, password)


def _keyring_get(service: str, user: str) -> str | None:
    return keyring.get_password(service, user)


def store_api_key(provider_name: str, api_key: str, *, account: str = "default") -> None:
    _keyring_set(f"{SERVICE_PREFIX}.{provider_name}", account, api_key)


def read_api_key(provider_name: str, *, account: str = "default") -> str | None:
    return _keyring_get(f"{SERVICE_PREFIX}.{provider_name}", account)
```

`src/trade_trace/embeddings/openai_provider.py`:
```python
"""OpenAI embedding provider. Outbound network call — opt-in only."""
from __future__ import annotations


class OpenAIProvider:
    name = "openai"

    DIMS: dict[str, int] = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
    }

    def __init__(self, model: str, api_key: str, *, client=None) -> None:
        self.model = model
        self._api_key = api_key
        self.dim = self.DIMS.get(model, 1536)
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(api_key=self._api_key)
        return self._client

    def embed(self, texts: list[str]) -> list[list[float]]:
        resp = self.client.embeddings.create(model=self.model, input=texts)
        return [list(d.embedding) for d in resp.data]
```

Add `openai` to optional deps in `pyproject.toml`:
```toml
[project.optional-dependencies]
openai = ["openai>=1.30"]
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_embeddings_openai.py -v`
Expected: PASS (uses injected mock client, no API call).

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/embeddings/openai_provider.py src/trade_trace/embeddings/secrets.py tests/test_embeddings_openai.py pyproject.toml
git commit -m "feat(embeddings): openai provider + keyring-backed secrets"
```

---

### Task 5.4: Embedding write hook in `retain` + vec table

**Files:**
- Create: `src/trade_trace/migrations/m0006_vec.py`
- Modify: `src/trade_trace/db.py` — load sqlite-vec
- Modify: `src/trade_trace/memory/retain.py` — embed on write if provider active
- Create: `tests/test_memory_embed_on_retain.py`

- [ ] **Step 1: Failing test**

`tests/test_memory_embed_on_retain.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock, patch

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate
from trade_trace.memory.retain import retain
from trade_trace.memory.models import RetainInput
from trade_trace.embeddings.registry import set_provider, ProviderConfig


def test_retain_writes_embedding_when_provider_active(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    set_provider(conn, ProviderConfig(name="local", model="bge", dim=4))
    fake = MagicMock()
    fake.name = "local"
    fake.model = "bge"
    fake.dim = 4
    fake.embed.return_value = [[0.1, 0.2, 0.3, 0.4]]
    with patch("trade_trace.memory.retain._build_provider", return_value=fake):
        out = retain(conn, RetainInput(node_type="observation",
                                       body="a", actor_id="agent:test"))
    row = conn.execute(
        "SELECT embedding_provider, embedding_model, embedding_dim "
        "FROM memory_nodes WHERE id=?",
        (out.node_id,),
    ).fetchone()
    assert row["embedding_provider"] == "local"
    assert row["embedding_dim"] == 4
    vec_row = conn.execute(
        "SELECT rowid FROM memory_node_embeddings WHERE node_id=?",
        (out.node_id,),
    ).fetchone()
    assert vec_row is not None
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Migration + db loader**

`src/trade_trace/migrations/m0006_vec.py`:
```python
"""Vector embeddings table backed by sqlite-vec.

We store the *active* provider's embeddings in `memory_node_embeddings`.
A switch to a different model/dim triggers reindex (see embeddings/reindex.py).
The vec virtual table is created lazily at first init with the current dim.
"""
from __future__ import annotations

import sqlite3

VERSION = 6


def apply(conn: sqlite3.Connection) -> None:
    # Non-vec backing row: maps node -> active embedding present marker.
    # The actual vec virtual table is created in db.ensure_vec_table(conn, dim)
    # because the dim is provider-dependent.
    conn.execute(
        """CREATE TABLE memory_node_embeddings (
            node_id TEXT PRIMARY KEY REFERENCES memory_nodes(id),
            vec_rowid INTEGER NOT NULL UNIQUE,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            dim INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        )"""
    )
```

Modify `src/trade_trace/db.py` — add vec loader:
```python
import sqlite_vec  # add at top

def connect(db_path):  # existing
    ...
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def ensure_vec_table(conn: sqlite3.Connection, dim: int) -> None:
    """Create the sqlite-vec virtual table for the active dim if missing."""
    existing = conn.execute(
        "SELECT name FROM sqlite_master WHERE name='vec_memory'"
    ).fetchone()
    if existing is None:
        conn.execute(f"CREATE VIRTUAL TABLE vec_memory USING vec0(embedding float[{dim}])")
```

Modify `src/trade_trace/memory/retain.py` — write embedding when provider active. Add at top:
```python
from trade_trace.db import ensure_vec_table
from trade_trace.embeddings.registry import get_active_provider, NoProviderError
```

Insert in `retain()` after the `memory_nodes` insert, before the edge loop:
```python
        try:
            cfg = get_active_provider(conn)
        except NoProviderError:
            cfg = None

        if cfg is not None and cfg.name != "none" and cfg.dim is not None:
            provider = _build_provider(cfg)
            vec = provider.embed([inp.body])[0]
            ensure_vec_table(conn, cfg.dim)
            cur = conn.execute(
                "INSERT INTO vec_memory(embedding) VALUES (?)",
                (_serialize_vector(vec),),
            )
            rowid = cur.lastrowid
            conn.execute(
                "INSERT INTO memory_node_embeddings(node_id, vec_rowid, provider, model, dim) "
                "VALUES (?,?,?,?,?)",
                (node_id, rowid, cfg.name, cfg.model, cfg.dim),
            )
            conn.execute(
                "UPDATE memory_nodes SET embedding_provider=?, embedding_model=?, embedding_dim=? "
                "WHERE id=?",
                (cfg.name, cfg.model, cfg.dim, node_id),
            )
```

Add helpers at the bottom of `retain.py`:
```python
import struct


def _serialize_vector(v: list[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


def _build_provider(cfg):
    from trade_trace.embeddings.registry import ProviderConfig
    assert isinstance(cfg, ProviderConfig)
    if cfg.name == "local":
        from trade_trace.embeddings.local import LocalProvider
        return LocalProvider(model=cfg.model or "BAAI/bge-small-en-v1.5")
    if cfg.name == "openai":
        from trade_trace.embeddings.openai_provider import OpenAIProvider
        from trade_trace.embeddings.secrets import read_api_key
        key = read_api_key("openai")
        if not key:
            raise RuntimeError("no openai api key in keyring")
        return OpenAIProvider(model=cfg.model or "text-embedding-3-small", api_key=key)
    raise ValueError(f"unknown provider: {cfg.name}")
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_memory_embed_on_retain.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/migrations/m0006_vec.py src/trade_trace/db.py src/trade_trace/memory/retain.py tests/test_memory_embed_on_retain.py
git commit -m "feat(embeddings): embed on retain via sqlite-vec virtual table"
```

---

### Task 5.5: Semantic retriever

**Files:**
- Create: `src/trade_trace/retrieval/semantic.py`
- Create: `tests/test_recall_semantic.py`

- [ ] **Step 1: Failing test**

`tests/test_recall_semantic.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock, patch

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate
from trade_trace.memory.retain import retain
from trade_trace.memory.models import RetainInput
from trade_trace.embeddings.registry import set_provider, ProviderConfig
from trade_trace.retrieval.semantic import semantic_search


def test_semantic_returns_nearest(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    set_provider(conn, ProviderConfig(name="local", model="bge", dim=4))
    fake = MagicMock(name="local", model="bge", dim=4)
    fake.embed.side_effect = lambda texts: [[1.0, 0.0, 0.0, 0.0] if "a" in t else [0.0, 1.0, 0.0, 0.0] for t in texts]
    with patch("trade_trace.memory.retain._build_provider", return_value=fake), \
         patch("trade_trace.retrieval.semantic._build_provider", return_value=fake):
        ra = retain(conn, RetainInput(node_type="observation", body="aaa",
                                      actor_id="agent:test"))
        rb = retain(conn, RetainInput(node_type="observation", body="bbb",
                                      actor_id="agent:test"))
        hits = semantic_search(conn, "aaa", k=2)
    assert hits[0].node_id == ra.node_id
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement**

`src/trade_trace/retrieval/semantic.py`:
```python
"""Semantic retriever via sqlite-vec."""
from __future__ import annotations

import sqlite3
import struct

from trade_trace.embeddings.registry import get_active_provider, NoProviderError
from trade_trace.retrieval.bm25 import Hit


def _build_provider(cfg):
    from trade_trace.memory.retain import _build_provider as _b
    return _b(cfg)


def _serialize(v: list[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


def semantic_search(conn: sqlite3.Connection, query: str, k: int = 20) -> list[Hit]:
    try:
        cfg = get_active_provider(conn)
    except NoProviderError:
        return []
    if cfg.name == "none":
        return []
    # If no rows have been embedded yet, vec_memory does not exist.
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE name='vec_memory'"
    ).fetchone() is None:
        return []
    provider = _build_provider(cfg)
    qv = provider.embed([query])[0]
    rows = conn.execute(
        """
        SELECT mn.id, mn.title, mn.body, mn.node_type, mn.created_at,
               mn.confidence_base, mn.decay_rate_per_day,
               v.distance AS dist
        FROM vec_memory v
        JOIN memory_node_embeddings mne ON mne.vec_rowid = v.rowid
        JOIN memory_nodes mn ON mn.id = mne.node_id
        WHERE v.embedding MATCH ? AND k = ?
        ORDER BY v.distance
        """,
        (_serialize(qv), k),
    ).fetchall()
    return [
        Hit(node_id=r["id"], rank=i + 1, raw_score=1.0 / (1.0 + float(r["dist"])),
            title=r["title"], body=r["body"], node_type=r["node_type"],
            created_at=r["created_at"],
            confidence_base=float(r["confidence_base"]),
            decay_rate_per_day=float(r["decay_rate_per_day"]))
        for i, r in enumerate(rows)
    ]
```

> **Implementation note for the engineer**: the sqlite-vec API uses ROWID-based addressing. To make the mapping robust, Task 5.6 (reindex) tightens the schema by adding a `rowid INTEGER NOT NULL UNIQUE` column to `memory_node_embeddings` and using that as the join key. For Task 5.5, validate with the test above and accept the schema tightening in 5.6.

- [ ] **Step 4: Run**

Run: `pytest tests/test_recall_semantic.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/retrieval/semantic.py tests/test_recall_semantic.py
git commit -m "feat(retrieval): semantic search via sqlite-vec"
```

---

### Task 5.6: Reindex command

**Files:**
- Create: `src/trade_trace/embeddings/reindex.py`
- Create: `tests/test_embeddings_reindex.py`

- [ ] **Step 1: Failing test**

`tests/test_embeddings_reindex.py`:
```python
from pathlib import Path
from unittest.mock import MagicMock, patch

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate
from trade_trace.memory.retain import retain
from trade_trace.memory.models import RetainInput
from trade_trace.embeddings.registry import set_provider, ProviderConfig
from trade_trace.embeddings.reindex import plan_reindex, execute_reindex


def test_plan_reindex_counts_stale_records(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    set_provider(conn, ProviderConfig(name="local", model="bge-old", dim=4))
    fake = MagicMock(name="local", model="bge-old", dim=4)
    fake.embed.return_value = [[1.0, 0.0, 0.0, 0.0]]
    with patch("trade_trace.memory.retain._build_provider", return_value=fake):
        retain(conn, RetainInput(node_type="observation", body="x", actor_id="agent:test"))

    # Switch provider to a different dim
    set_provider(conn, ProviderConfig(name="local", model="bge-new", dim=8))
    plan = plan_reindex(conn)
    assert plan.stale_count == 1
    assert plan.fresh_count == 0
    assert plan.estimated_cost_usd == 0.0  # local


def test_execute_reindex_replaces_old_vectors(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    set_provider(conn, ProviderConfig(name="local", model="bge-old", dim=4))
    old_fake = MagicMock(name="local", model="bge-old", dim=4)
    old_fake.embed.return_value = [[1.0, 0.0, 0.0, 0.0]]
    with patch("trade_trace.memory.retain._build_provider", return_value=old_fake):
        out = retain(conn, RetainInput(node_type="observation", body="x", actor_id="agent:test"))

    set_provider(conn, ProviderConfig(name="local", model="bge-new", dim=8))
    new_fake = MagicMock(name="local", model="bge-new", dim=8)
    new_fake.embed.return_value = [[0.1] * 8]
    with patch("trade_trace.embeddings.reindex._build_provider", return_value=new_fake):
        execute_reindex(conn)

    row = conn.execute("SELECT model, dim FROM memory_node_embeddings WHERE node_id=?",
                       (out.node_id,)).fetchone()
    assert row["model"] == "bge-new"
    assert row["dim"] == 8
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement reindex**

`src/trade_trace/embeddings/reindex.py`:
```python
"""Reindex existing memory_nodes when the active embedding provider/model/dim changes."""
from __future__ import annotations

import sqlite3
import struct
from dataclasses import dataclass

from trade_trace.db import ensure_vec_table
from trade_trace.embeddings.registry import get_active_provider, ProviderConfig

USD_PER_1K_TOK_OPENAI_SMALL = 0.00002  # rough; documented at run time


def _build_provider(cfg: ProviderConfig):
    from trade_trace.memory.retain import _build_provider as b
    return b(cfg)


@dataclass(frozen=True)
class ReindexPlan:
    active_provider: str
    active_model: str
    active_dim: int
    stale_count: int
    fresh_count: int
    estimated_cost_usd: float


def plan_reindex(conn: sqlite3.Connection) -> ReindexPlan:
    cfg = get_active_provider(conn)
    rows = conn.execute(
        "SELECT mne.model AS m, mne.dim AS d, COUNT(*) AS n "
        "FROM memory_node_embeddings mne GROUP BY m, d"
    ).fetchall()
    stale = sum(int(r["n"]) for r in rows if r["m"] != cfg.model or r["d"] != cfg.dim)
    fresh = sum(int(r["n"]) for r in rows if r["m"] == cfg.model and r["d"] == cfg.dim)
    cost = 0.0
    if cfg.name == "openai":
        # rough char→token estimate: 1 token ≈ 4 chars
        total_chars = conn.execute(
            "SELECT COALESCE(SUM(LENGTH(body)),0) AS s FROM memory_nodes mn "
            "JOIN memory_node_embeddings mne ON mne.node_id = mn.id "
            "WHERE mne.model != ? OR mne.dim != ?",
            (cfg.model, cfg.dim),
        ).fetchone()["s"]
        cost = (total_chars / 4 / 1000) * USD_PER_1K_TOK_OPENAI_SMALL
    return ReindexPlan(active_provider=cfg.name, active_model=cfg.model or "",
                       active_dim=cfg.dim or 0, stale_count=stale,
                       fresh_count=fresh, estimated_cost_usd=cost)


def _serialize(v: list[float]) -> bytes:
    return struct.pack(f"{len(v)}f", *v)


def execute_reindex(conn: sqlite3.Connection, *, batch_size: int = 64) -> None:
    cfg = get_active_provider(conn)
    if cfg.dim is None:
        raise ValueError("active provider has no dim configured")
    provider = _build_provider(cfg)

    # Drop and rebuild vec table at the new dim.
    conn.execute("DROP TABLE IF EXISTS vec_memory")
    ensure_vec_table(conn, cfg.dim)

    rows = conn.execute(
        "SELECT mn.id, mn.body FROM memory_nodes mn "
        "JOIN memory_node_embeddings mne ON mne.node_id = mn.id"
    ).fetchall()

    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        vecs = provider.embed([r["body"] for r in batch])
        for r, v in zip(batch, vecs, strict=True):
            cur = conn.execute(
                "INSERT INTO vec_memory(embedding) VALUES (?)",
                (_serialize(v),),
            )
            rowid = cur.lastrowid
            conn.execute(
                "UPDATE memory_node_embeddings SET provider=?, model=?, dim=?, vec_rowid=? "
                "WHERE node_id=?",
                (cfg.name, cfg.model, cfg.dim, rowid, r["id"]),
            )
            conn.execute(
                "UPDATE memory_nodes SET embedding_provider=?, embedding_model=?, embedding_dim=? "
                "WHERE id=?",
                (cfg.name, cfg.model, cfg.dim, r["id"]),
            )
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_embeddings_reindex.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/embeddings/reindex.py tests/test_embeddings_reindex.py
git commit -m "feat(embeddings): reindex on provider switch with cost estimate"
```

---

## Phase 6: Signals + Reflect

### Task 6.1: Signal writer

**Files:**
- Create: `src/trade_trace/signals.py`
- Create: `tests/test_signals.py`

- [ ] **Step 1: Failing test**

`tests/test_signals.py`:
```python
from pathlib import Path

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate
from trade_trace.signals import emit_signal


def test_emit_signal_writes_row(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    sig_id = emit_signal(conn, kind="calibration_drift", severity="warn",
                         body="expected 0.85, realized 0.62 in high bucket",
                         meta={"bucket": "high"}, related_refs=[])
    row = conn.execute(
        "SELECT kind, severity, body FROM signals WHERE id=?", (sig_id,)
    ).fetchone()
    assert row["kind"] == "calibration_drift"
    assert row["severity"] == "warn"


def test_emit_signal_rejects_bad_severity(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    import pytest, sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        emit_signal(conn, kind="x", severity="meh", body="b", meta={}, related_refs=[])
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement**

`src/trade_trace/signals.py`:
```python
"""System-emitted signals."""
from __future__ import annotations

import json
import sqlite3
import uuid


def emit_signal(
    conn: sqlite3.Connection,
    *,
    kind: str,
    severity: str,
    body: str,
    meta: dict,
    related_refs: list[dict],
    expires_at: str | None = None,
) -> str:
    sig_id = f"sig_{uuid.uuid4().hex[:16]}"
    conn.execute(
        "INSERT INTO signals(id, kind, severity, body, meta_json, related_refs_json, expires_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (sig_id, kind, severity, body, json.dumps(meta), json.dumps(related_refs), expires_at),
    )
    return sig_id
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_signals.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/signals.py tests/test_signals.py
git commit -m "feat(signals): emit_signal writer"
```

---

### Task 6.2: `memory.reflect` sugar

**Files:**
- Create: `src/trade_trace/memory/reflect.py`
- Modify: `src/trade_trace/memory/models.py` — add `ReflectInput`
- Create: `tests/test_memory_reflect.py`

- [ ] **Step 1: Failing test**

`tests/test_memory_reflect.py`:
```python
from pathlib import Path

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate
from trade_trace.memory.reflect import reflect
from trade_trace.memory.models import ReflectInput, ReflectTarget


def _seed(tmp_path):
    conn = connect(tmp_path / "t.sqlite")
    migrate(conn)
    conn.execute("INSERT INTO decisions(id) VALUES ('d1')")
    return conn


def test_reflect_on_decision_creates_about_edge(tmp_path):
    conn = _seed(tmp_path)
    out = reflect(conn, ReflectInput(
        target=ReflectTarget(kind="decision", id="d1"),
        body="I overweighted spread compression here.",
        actor_id="agent:test",
    ))
    edge = conn.execute(
        "SELECT edge_type, target_id FROM edges WHERE source_id=?",
        (out.node_id,),
    ).fetchone()
    assert edge["edge_type"] == "about"
    assert edge["target_id"] == "d1"


def test_reflect_period_target_lives_in_meta(tmp_path):
    conn = _seed(tmp_path)
    out = reflect(conn, ReflectInput(
        target=ReflectTarget(kind="period", period={"start": "2026-05-01", "end": "2026-05-07"}),
        body="Three skips this week were the right call.",
        actor_id="agent:test",
    ))
    row = conn.execute("SELECT meta_json FROM memory_nodes WHERE id=?",
                       (out.node_id,)).fetchone()
    import json
    meta = json.loads(row["meta_json"])
    assert meta["target_scope"]["kind"] == "period"
    # No edges should be created for a period target.
    n = conn.execute("SELECT COUNT(*) AS n FROM edges WHERE source_id=?",
                     (out.node_id,)).fetchone()["n"]
    assert n == 0
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement model + reflect**

Add to `src/trade_trace/memory/models.py`:
```python
class ReflectTarget(BaseModel):
    kind: Literal[
        "decision", "position", "instrument", "playbook_version", "signal",
        "period", "tag",
    ]
    id: str | None = None
    period: dict | None = None  # {start, end}
    tag: str | None = None


class ReflectInput(BaseModel):
    target: ReflectTarget
    body: str = Field(min_length=1)
    title: str | None = None
    actor_id: str
    derived_from: list[str] = Field(default_factory=list)
    supports: list[str] = Field(default_factory=list)
    contradicts: list[str] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)
    decay_rate_per_day: float | None = Field(default=None, ge=0.0)
    confidence_base: float = Field(default=1.0, ge=0.0, le=1.0)
    idempotency_key: str | None = None


ROW_BACKED_TARGETS = frozenset({
    "decision", "position", "instrument", "playbook_version", "signal",
})
```

`src/trade_trace/memory/reflect.py`:
```python
"""memory.reflect — sugar over retain(node_type=reflection) with edge wiring."""
from __future__ import annotations

import sqlite3

from trade_trace.memory.models import (
    EdgeSpec, ReflectInput, RetainInput, ROW_BACKED_TARGETS,
)
from trade_trace.memory.retain import retain, RetainOutput


def reflect(conn: sqlite3.Connection, inp: ReflectInput) -> RetainOutput:
    edges: list[EdgeSpec] = []
    meta: dict = {}
    t = inp.target

    if t.kind in ROW_BACKED_TARGETS:
        if t.id is None:
            raise ValueError(f"target.id required for kind={t.kind}")
        edges.append(EdgeSpec(edge_type="about", target_kind=t.kind, target_id=t.id))
    else:
        meta["target_scope"] = {"kind": t.kind, "period": t.period, "tag": t.tag}

    for obs_id in inp.derived_from:
        edges.append(EdgeSpec(edge_type="derived_from",
                              target_kind="memory_node", target_id=obs_id))
    for sup_id in inp.supports:
        edges.append(EdgeSpec(edge_type="supports",
                              target_kind="memory_node", target_id=sup_id))
    for con_id in inp.contradicts:
        edges.append(EdgeSpec(edge_type="contradicts",
                              target_kind="memory_node", target_id=con_id))
    for sup_id in inp.supersedes:
        edges.append(EdgeSpec(edge_type="supersedes",
                              target_kind="memory_node", target_id=sup_id))

    return retain(conn, RetainInput(
        node_type="reflection",
        body=inp.body,
        title=inp.title,
        meta=meta,
        decay_rate_per_day=inp.decay_rate_per_day,
        confidence_base=inp.confidence_base,
        actor_id=inp.actor_id,
        idempotency_key=inp.idempotency_key,
        edges=edges,
    ))
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_memory_reflect.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/memory/reflect.py src/trade_trace/memory/models.py tests/test_memory_reflect.py
git commit -m "feat(memory): reflect sugar (auto about + provenance edges)"
```

---

## Phase 7: CLI Surface

### Task 7.1: `tt` entry point + `tt init`

**Files:**
- Create: `src/trade_trace/cli/__init__.py`
- Create: `src/trade_trace/cli/init_cmd.py`
- Create: `tests/test_cli_init.py`

- [ ] **Step 1: Failing test**

`tests/test_cli_init.py`:
```python
import json
import os
import subprocess
import sys
from pathlib import Path


def test_tt_init_creates_db(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRADE_TRACE_HOME", str(tmp_path))
    out = subprocess.run(
        [sys.executable, "-m", "trade_trace.cli", "init"],
        capture_output=True, text=True, check=True,
    )
    env = json.loads(out.stdout)
    assert env["ok"] is True
    assert (tmp_path / "trade-trace.sqlite").exists()
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement CLI app**

`src/trade_trace/cli/__init__.py`:
```python
"""`tt` CLI entry point (Typer)."""
from __future__ import annotations

import typer

from trade_trace.cli.init_cmd import init

app = typer.Typer(no_args_is_help=True, add_completion=False)
app.command()(init)


if __name__ == "__main__":
    app()
```

`src/trade_trace/cli/init_cmd.py`:
```python
"""`tt init` — open or create the trade-trace DB and run migrations."""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate


def _home() -> Path:
    base = os.environ.get("TRADE_TRACE_HOME")
    return Path(base).expanduser().resolve() if base else (Path.home() / ".trade-trace")


def init(human: bool = False) -> None:
    home = _home()
    home.mkdir(parents=True, exist_ok=True)
    db_path = home / "trade-trace.sqlite"
    conn = connect(db_path)
    try:
        migrate(conn)
    finally:
        conn.close()

    envelope = {
        "ok": True,
        "data": {"db_path": str(db_path)},
        "meta": {
            "tool": "journal.init",
            "request_id": uuid.uuid4().hex,
            "actor_id": "cli:user",
        },
    }
    json.dump(envelope, sys.stdout)
    sys.stdout.write("\n")
    if human:
        print(f"initialized at {db_path}", file=sys.stderr)
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_cli_init.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/cli tests/test_cli_init.py
git commit -m "feat(cli): tt init opens DB and runs migrations"
```

---

### Task 7.2: `tt memory retain/recall/reflect/link` commands

**Files:**
- Create: `src/trade_trace/cli/memory_cmds.py`
- Modify: `src/trade_trace/cli/__init__.py`
- Create: `tests/test_cli_memory.py`

- [ ] **Step 1: Failing test**

`tests/test_cli_memory.py`:
```python
import json
import subprocess
import sys
from pathlib import Path


import os


def _run(*args, env_home: Path) -> dict:
    out = subprocess.run(
        [sys.executable, "-m", "trade_trace.cli", *args],
        capture_output=True, text=True, check=True,
        env={**os.environ, "TRADE_TRACE_HOME": str(env_home)},
    )
    return json.loads(out.stdout)


def test_retain_then_recall(tmp_path: Path):
    _run("init", env_home=tmp_path)
    env = _run("memory", "retain", "--kind", "observation",
               "--body", "NVDA earnings gap fade pattern",
               "--actor", "cli:test", env_home=tmp_path)
    assert env["ok"] is True
    node_id = env["data"]["node_id"]

    env = _run("memory", "recall", "--query", "NVDA",
               "--strategies", "bm25", "--no-vectors",
               env_home=tmp_path)
    rows = env["data"]["rows"]
    assert any(r["node_id"] == node_id for r in rows)
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement**

`src/trade_trace/cli/memory_cmds.py`:
```python
"""`tt memory ...` subcommands."""
from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import typer

from trade_trace.cli.init_cmd import _home
from trade_trace.db import connect
from trade_trace.memory.models import (
    EdgeSpec, ReflectInput, ReflectTarget, RetainInput, RecallInput,
)
from trade_trace.memory.recall import recall
from trade_trace.memory.reflect import reflect
from trade_trace.memory.retain import retain
from trade_trace.edges import EdgeRef, write_edge

app = typer.Typer(no_args_is_help=True)


def _emit(tool: str, data) -> None:
    env = {"ok": True, "data": data,
           "meta": {"tool": tool, "request_id": uuid.uuid4().hex,
                    "actor_id": "cli:user"}}
    json.dump(env, sys.stdout, default=str)
    sys.stdout.write("\n")


def _conn():
    return connect(_home() / "trade-trace.sqlite")


@app.command("retain")
def cli_retain(
    kind: str = typer.Option(...),
    body: str = typer.Option(...),
    title: str | None = typer.Option(None),
    actor: str = typer.Option("cli:user", "--actor"),
):
    conn = _conn()
    out = retain(conn, RetainInput(node_type=kind, body=body, title=title, actor_id=actor))
    _emit("memory.retain", out.model_dump())


@app.command("recall")
def cli_recall(
    query: str | None = typer.Option(None),
    context: str | None = typer.Option(None),
    k: int = typer.Option(20),
    strategies: list[str] = typer.Option(["bm25", "temporal"]),
    max_chars: int | None = typer.Option(None),
    compact: bool = typer.Option(False),
    no_vectors: bool = typer.Option(False, "--no-vectors"),
):
    conn = _conn()
    if no_vectors and "semantic" in strategies:
        strategies = [s for s in strategies if s != "semantic"]
    payload = recall(conn, RecallInput(
        query=query, context_node_id=context, k=k, strategies=strategies,
        max_chars=max_chars, compact=compact,
    ))
    _emit("memory.recall", payload)


@app.command("reflect")
def cli_reflect(
    target_kind: str = typer.Option(...),
    target_id: str | None = typer.Option(None),
    body: str = typer.Option(...),
    actor: str = typer.Option("cli:user", "--actor"),
):
    conn = _conn()
    out = reflect(conn, ReflectInput(
        target=ReflectTarget(kind=target_kind, id=target_id),
        body=body, actor_id=actor,
    ))
    _emit("memory.reflect", out.model_dump())


@app.command("link")
def cli_link(
    from_kind: str = typer.Option(..., "--from-kind"),
    from_id: str = typer.Option(..., "--from-id"),
    to_kind: str = typer.Option(..., "--to-kind"),
    to_id: str = typer.Option(..., "--to-id"),
    edge_type: str = typer.Option(...),
    actor: str = typer.Option("cli:user", "--actor"),
):
    conn = _conn()
    e = write_edge(conn,
                   EdgeRef(from_kind, from_id),
                   EdgeRef(to_kind, to_id),
                   edge_type, actor_id=actor)
    _emit("memory.link", {"edge_id": e.id})
```

Modify `src/trade_trace/cli/__init__.py`:
```python
from trade_trace.cli.memory_cmds import app as memory_app

app.add_typer(memory_app, name="memory")
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_cli_memory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/cli/memory_cmds.py src/trade_trace/cli/__init__.py tests/test_cli_memory.py
git commit -m "feat(cli): tt memory retain/recall/reflect/link"
```

---

## Phase 8: MCP Surface

### Task 8.1: MCP server + memory tools

**Files:**
- Create: `src/trade_trace/mcp/__init__.py`
- Create: `src/trade_trace/mcp/server.py`
- Create: `tests/test_mcp_memory.py`

- [ ] **Step 1: Failing test (in-process)**

`tests/test_mcp_memory.py`:
```python
import asyncio
from pathlib import Path

import pytest

from trade_trace.db import connect
from trade_trace.migrations.runner import migrate
from trade_trace.mcp.server import call_tool


@pytest.mark.asyncio
async def test_mcp_memory_retain_and_recall(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRADE_TRACE_HOME", str(tmp_path))
    conn = connect(tmp_path / "trade-trace.sqlite")
    migrate(conn)
    conn.close()

    retained = await call_tool("memory.retain", {
        "node_type": "observation",
        "body": "thin polymarket spreads widen",
        "actor_id": "mcp:test",
    })
    assert retained["ok"] is True

    recalled = await call_tool("memory.recall", {
        "query": "polymarket", "k": 5, "strategies": ["bm25"],
    })
    assert recalled["ok"] is True
    assert any("polymarket" in r["body"].lower() for r in recalled["data"]["rows"])
```

- [ ] **Step 2: Run, confirm fail**

- [ ] **Step 3: Implement (in-process callable, MCP framing comes from `mcp` SDK separately)**

`src/trade_trace/mcp/__init__.py`:
```python
```

`src/trade_trace/mcp/server.py`:
```python
"""MCP tool dispatcher.

The CLI and MCP share the same core functions; this module wraps them
behind a single `call_tool(name, args)` async entry point that returns
the envelope. The MCP transport adapter (using the `mcp` SDK) is a thin
wrapper around `call_tool` and is registered when running `tt mcp`.
"""
from __future__ import annotations

import uuid
from pathlib import Path

from trade_trace.cli.init_cmd import _home
from trade_trace.db import connect
from trade_trace.edges import EdgeRef, write_edge
from trade_trace.memory.models import (
    ReflectInput, ReflectTarget, RecallInput, RetainInput,
)
from trade_trace.memory.recall import recall as recall_fn
from trade_trace.memory.reflect import reflect as reflect_fn
from trade_trace.memory.retain import retain as retain_fn


def _env(tool: str, data) -> dict:
    return {"ok": True, "data": data, "meta": {
        "tool": tool, "request_id": uuid.uuid4().hex, "actor_id": data.get("actor_id", "mcp:user"),
    }}


def _conn():
    return connect(_home() / "trade-trace.sqlite")


async def call_tool(name: str, args: dict) -> dict:
    conn = _conn()
    try:
        if name == "memory.retain":
            out = retain_fn(conn, RetainInput(**args))
            return _env(name, out.model_dump())
        if name == "memory.recall":
            payload = recall_fn(conn, RecallInput(**args))
            return _env(name, payload)
        if name == "memory.reflect":
            target = ReflectTarget(**args.pop("target"))
            out = reflect_fn(conn, ReflectInput(target=target, **args))
            return _env(name, out.model_dump())
        if name == "memory.link":
            e = write_edge(
                conn,
                EdgeRef(args["from_kind"], args["from_id"]),
                EdgeRef(args["to_kind"], args["to_id"]),
                args["edge_type"],
                actor_id=args.get("actor_id", "mcp:user"),
                weight=args.get("weight"),
            )
            return _env(name, {"edge_id": e.id})
        return {"ok": False, "error": {
            "code": "VALIDATION_ERROR",
            "message": f"unknown tool: {name}",
        }, "meta": {"tool": name, "request_id": uuid.uuid4().hex,
                    "actor_id": "mcp:user"}}
    finally:
        conn.close()
```

- [ ] **Step 4: Run**

Run: `pytest tests/test_mcp_memory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/trade_trace/mcp tests/test_mcp_memory.py
git commit -m "feat(mcp): in-process call_tool for memory.* tools"
```

---

### Task 8.2: CLI ↔ MCP parity test

**Files:**
- Create: `tests/test_parity.py`

- [ ] **Step 1: Failing test**

`tests/test_parity.py`:
```python
import asyncio
import json
import subprocess
import sys
from pathlib import Path

from trade_trace.mcp.server import call_tool


def _normalize(env: dict) -> dict:
    e = json.loads(json.dumps(env))  # deep copy
    e.get("meta", {}).pop("request_id", None)
    return e


def test_retain_parity(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRADE_TRACE_HOME", str(tmp_path))
    subprocess.run([sys.executable, "-m", "trade_trace.cli", "init"], check=True)

    cli = subprocess.run(
        [sys.executable, "-m", "trade_trace.cli", "memory", "retain",
         "--kind", "observation", "--body", "parity check",
         "--actor", "test:parity"],
        capture_output=True, text=True, check=True,
    )
    cli_env = json.loads(cli.stdout)

    mcp_env = asyncio.run(call_tool("memory.retain", {
        "node_type": "observation", "body": "parity check",
        "actor_id": "test:parity",
    }))

    # IDs differ between runs; assert shape parity, not content equality.
    a, b = _normalize(cli_env), _normalize(mcp_env)
    assert set(a) == set(b) == {"ok", "data", "meta"}
    assert set(a["data"]) == set(b["data"]) == {"node_id", "event_id", "edge_ids"}
    assert set(a["meta"]) == set(b["meta"])
```

- [ ] **Step 2: Run, confirm pass**

Run: `pytest tests/test_parity.py -v`
Expected: PASS (no new code; tests existing shape).

- [ ] **Step 3: Commit**

```bash
git add tests/test_parity.py
git commit -m "test: cli/mcp envelope-shape parity"
```

---

## Phase 9: End-to-end Integration

### Task 9.1: Full-loop integration test

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write the test**

`tests/test_integration.py`:
```python
"""End-to-end: init → retain observations → reflect on a decision → recall."""
import os
import subprocess
import sys
import json
from pathlib import Path


def _run(*args, home: Path) -> dict:
    out = subprocess.run(
        [sys.executable, "-m", "trade_trace.cli", *args],
        capture_output=True, text=True, check=True,
        env={**os.environ, "TRADE_TRACE_HOME": str(home)},
    )
    return json.loads(out.stdout)


def test_full_memory_loop(tmp_path: Path):
    _run("init", home=tmp_path)

    # Seed a decision stub directly so reflect has a target.
    import sqlite3
    conn = sqlite3.connect(tmp_path / "trade-trace.sqlite")
    conn.execute("INSERT INTO decisions(id) VALUES ('d_demo')")
    conn.commit()
    conn.close()

    obs = _run("memory", "retain", "--kind", "observation",
               "--body", "thin polymarket spreads widen near resolution",
               "--actor", "agent:test", home=tmp_path)
    assert obs["ok"]

    refl = _run("memory", "reflect",
                "--target-kind", "decision", "--target-id", "d_demo",
                "--body", "I overweighted spread compression; ignored liquidity profile.",
                "--actor", "agent:test", home=tmp_path)
    assert refl["ok"]
    refl_id = refl["data"]["node_id"]

    recalled = _run("memory", "recall",
                    "--query", "polymarket spreads",
                    "--strategies", "bm25", "--no-vectors",
                    home=tmp_path)
    assert any(r["body"].lower().startswith("thin polymarket")
               for r in recalled["data"]["rows"])

    # Verify reflection's about-edge points at the decision.
    conn = sqlite3.connect(tmp_path / "trade-trace.sqlite")
    edge = conn.execute(
        "SELECT edge_type, target_id FROM edges WHERE source_id=?",
        (refl_id,),
    ).fetchone()
    conn.close()
    assert edge == ("about", "d_demo")
```

- [ ] **Step 2: Run**

Run: `pytest tests/test_integration.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: end-to-end memory loop via CLI"
```

---

## Final acceptance gates

Run all of these before considering this plan complete:

- [ ] `pytest -q` — all tests green (excluding `-m slow` unless network available)
- [ ] `pytest -q -m slow` — local-embedding tests green on a network-enabled machine
- [ ] `ruff check src tests` — no errors
- [ ] `mypy src/trade_trace` — no errors (relax strictness as needed in pyproject)
- [ ] Spec coverage spot-check: every section of `docs/architecture/memory-layer.md` has a task in this plan (see self-review notes below)
- [ ] PRD §3.2 / §4.1 / §11 alignment edit lands in a follow-up PR (out of scope here)

---

## Self-review notes

Mapping spec sections to plan tasks:

- **§2 Design principles** — enforced by overall structure (one SQLite file = Task 0.2; zero-config first run = Task 7.1; opt-in capabilities = Tasks 5.x).
- **§3.1 observation / §3.2 reflection / §3.3 rule** — `node_type` CHECK constraint in Task 1.2; defaults table in Task 3.1.
- **§4 Signals** — Tasks 1.3 (schema), 6.1 (writer), 8.x (no CLI/MCP surface for emit since system-only; signals consumed by `report.coach` in M2 plan).
- **§5 Edge taxonomy** — Tasks 1.3, 2.1, 2.2.
- **§6 Confidence model** — Tasks 4.2, 4.5 (edge-density factor deferred per spec).
- **§7 Retrieval** — Tasks 4.1 (BM25), 4.3 (temporal), 4.4 (RRF), 4.5 (supersession), 4.6 (budget), 4.7 (orchestrator), 4.8 (graph), 5.5 (semantic).
- **§8 Embeddings** — Tasks 5.1 (registry), 5.2 (local), 5.3 (openai + keyring), 5.4 (embed on write), 5.6 (reindex). Bundled-vs-lazy packaging decision left to Task 0.1 (we ship sentence-transformers as a runtime dep; the bge model weight is lazy-downloaded by sentence-transformers' HF cache).
- **§9 Public API** — `memory.retain` (Task 3.1), `memory.recall` (Task 4.7), `memory.reflect` (Task 6.2), `memory.link` (Tasks 2.2 + 7.2). Each exposed as CLI (Task 7.2) and MCP (Task 8.1) with parity test (Task 8.2).
- **§10 Reflection ergonomics** — Task 6.2.

Spec sections NOT covered here and intentionally deferred:
- §11 Hindsight comparison — informational, no code.
- §12 Open questions — informational, no code.
- P1 items (edge-density confidence, dual-index reindex, multi-modal, token budgets, bundled-weights extra) — separate future plan.

Coverage: complete for MVP scope.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-18-memory-layer.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration. Uses `superpowers:subagent-driven-development`.
2. **Inline Execution** — execute tasks in this session with checkpoints. Uses `superpowers:executing-plans`.
