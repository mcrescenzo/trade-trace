# Lane report: core-storage-security

Audit run: `repo-audit-20260521T173511Z`  
Scope fingerprint: `1901b8097953e720`  
Lane: `core-storage-security`  
Mode: read-only source audit; only this lane artifact was written.

## Scope enumeration

Assigned manifest rows were enumerated from `manifest-coverage-ledger.yaml` by filtering `owner_lane == core-storage-security` (36 rows). Focus areas reviewed: storage connection/migration policy, event log/outbox export, import/export serialization helpers, permissions, path resolution, and credential/security helpers.

## Candidate records

### CSS-20260521-001 — `open_database_readonly()` builds an unescaped SQLite URI, so paths containing `?` or `#` open/create the wrong database

- **remediation_track:** bug
- **owner_track:** core-storage-security
- **affected paths/symbols:**
  - `src/trade_trace/storage/database.py:116` `open_database_readonly`
  - `src/trade_trace/storage/database.py:148-149` SQLite URI construction/connect
  - `tests/security/test_readonly_database.py:116-143` existing readonly tests cover missing/unsupported schema but not URI-reserved path characters
- **observed facts with file:line evidence:**
  - `open_database_readonly(path)` accepts any `Path`, checks `path.exists()`, then constructs `uri = f"file:{path}?mode=ro"` and calls `sqlite3.connect(uri, uri=True, ...)` (`src/trade_trace/storage/database.py:135-149`).
  - The function's contract says it uses `sqlite3.connect("file:<path>?mode=ro", uri=True)` so attempted writes are rejected at the SQLite layer (`src/trade_trace/storage/database.py:116-121`), and it should raise typed `ReadOnlyDatabaseError` for missing or unsupported schema (`src/trade_trace/storage/database.py:128-132`).
  - Existing tests assert the readonly handle rejects writes, has `PRAGMA query_only = 1`, reports missing DBs, reports empty DBs as unsupported, and does not run migrations (`tests/security/test_readonly_database.py:96-163` from source-scoped search). I found no test covering database filenames containing URI-reserved characters.
  - Probe command using a temp directory showed the risk: for an existing SQLite file named `db?x.sqlite`, `sqlite3.connect(f"file:{p}?mode=ro", uri=True)` opened `/tmp/.../db` instead and created/listed both `db` and `db?x.sqlite`; `PRAGMA database_list` reported the main DB as the truncated `/tmp/.../db`.
- **inferences:**
  - SQLite URI parsing treats the first `?` as the query delimiter. Because the path is interpolated rather than converted to a properly escaped URI (for example via `path.resolve().as_uri()` plus query, or `urllib.parse.quote`), a legitimate `TRADE_TRACE_HOME` or explicit DB path containing URI-reserved characters can cause the Console/read-only path to inspect or create the wrong sibling file.
  - This is a storage/security bug even though `path.exists()` guards the originally requested path: the subsequent URI no longer necessarily refers to that path. In the observed `?` case, it created/opened a sibling file read-write-ish enough for SQLite to create it before the code set `query_only`, then the schema check would report `unsupported_schema` for the wrong file.
- **assumptions:**
  - User-controlled or environment-derived home paths may contain `?`/`#` on POSIX filesystems; `resolve_home()` does not reject them (`src/trade_trace/storage/paths.py:25-30`).
  - Parent verification should test both `?` and `#`; the probe directly verified `?`.
- **open questions:**
  - Should the project support all valid POSIX filenames, or deliberately reject SQLite URI-reserved characters in `TRADE_TRACE_HOME` / explicit DB paths? Supporting them is less surprising and avoids a path-policy special case.
- **validation command/gap:**
  - Probe run:
    ```bash
    python - <<'PY'
    import sqlite3, tempfile, os
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/'db?x.sqlite'
        c=sqlite3.connect(str(p)); c.execute('create table events(id int)'); c.execute('create table config(key text)'); c.commit(); c.close()
        uri=f'file:{p}?mode=ro'
        conn=sqlite3.connect(uri,uri=True)
        print(sorted(os.listdir(d)))
        print(conn.execute('PRAGMA database_list').fetchall())
    PY
    ```
    Output: `['db', 'db?x.sqlite']` and main DB `/tmp/.../db`.
  - Suggested acceptance validation: add a regression test that seeds a valid DB at a path containing `?` and asserts `open_database_readonly()` opens that exact file (via `PRAGMA database_list`) and rejects writes; also assert it does not create the truncated sibling.
- **prior_match_status:** new
- **duplicate/overlap notes:** No direct existing inventory match. Related but not duplicate: `trade-trace-l24k` (restore path traversal), `trade-trace-d2jv` (safe path helpers), and `trade-trace-71zq` (restore permissions) are closed and concern restore/import containment or file modes, not SQLite URI escaping for read-only DB opens.
- **recommended disposition:** accept
- **proposed Bead if accepted:**
  - **title:** Fix SQLite read-only URI escaping for DB paths containing URI-reserved characters
  - **type:** bug
  - **labels:** `bug`, `security`, `domain:storage-persistence-events-schema`, `core-storage-security`, `repo-audit-20260521T173511Z`
  - **acceptance:**
    1. `open_database_readonly()` constructs a SQLite URI that faithfully addresses the requested `Path` when filenames/directories contain `?`, `#`, spaces, and other URI-reserved characters.
    2. Regression test seeds a valid DB at such a path, verifies `PRAGMA database_list` points at the requested DB, verifies attempted writes still raise readonly errors, and verifies no truncated sibling DB file is created.
    3. Existing readonly tests continue to pass.

## Non-candidate observations

- Permission helpers have been centralized in `src/trade_trace/_permissions.py`; database and exporter call them for DB/WAL/SHM and JSONL files (`src/trade_trace/storage/database.py:20,51-61,71-87,193-204`; `src/trade_trace/exporter.py:28,202-231`). This overlaps closed simplification `trade-trace-fxxm`; no new simplification candidate.
- Append-only events hardening is present through migration `m009_events_append_only.py:34-57`, overlapping closed `trade-trace-dhm`; no regression claim made here.
- Export event-type filenames are sanitized before path construction (`src/trade_trace/exporter.py:39-84`), and JSONL writes use temp+replace with 0600 permissions (`src/trade_trace/exporter.py:184-231`); no new export path traversal candidate found in assigned code.
- Keyring helper refuses known insecure/null/fail/plaintext backends and validates non-empty values before storing (`src/trade_trace/security/keyring.py:23-78,89-106`); no new credential-storage candidate found in this pass.

## Per-assigned-manifest-row treatment

| Path | Treatment |
| --- | --- |
| `src/trade_trace/__init__.py` | opened/contract-checked as package surface; no candidate. |
| `src/trade_trace/_permissions.py` | opened; structurally grouped with storage/export permission enforcement; no candidate beyond closed `trade-trace-fxxm`. |
| `src/trade_trace/clock.py` | source-scoped searched/contract-checked as timestamp/clock helper; no candidate. |
| `src/trade_trace/contracts/__init__.py` | opened/structurally grouped with contracts package; no candidate. |
| `src/trade_trace/contracts/envelope.py` | source-scoped searched/contract-checked for error-envelope interactions; no candidate. |
| `src/trade_trace/contracts/errors.py` | source-scoped searched/contract-checked via keyring `ToolError` usage; no candidate. |
| `src/trade_trace/contracts/grammar.py` | source-scoped searched/contract-checked via event writer actor/idempotency validation; no candidate. |
| `src/trade_trace/core.py` | source-scoped searched/contract-checked as core facade; no candidate. |
| `src/trade_trace/events/__init__.py` | opened/structurally grouped with event exports; no candidate. |
| `src/trade_trace/events/log.py` | opened; event idempotency/outbox write path reviewed; no candidate. |
| `src/trade_trace/events/semantic_keys.py` | source-scoped searched/contract-checked as event idempotency registry; no candidate. |
| `src/trade_trace/events/unit_of_work.py` | opened; transaction/dry-run semantics reviewed; no candidate with enough evidence. |
| `src/trade_trace/exporter.py` | opened; JSONL path, atomic write, secret scan, drain reviewed; no candidate. |
| `src/trade_trace/logging.py` | source-scoped searched/contract-checked for redaction/security overlap; no candidate. |
| `src/trade_trace/models/__init__.py` | opened/structurally grouped with ledger models; no candidate. |
| `src/trade_trace/models/ledger.py` | source-scoped searched/contract-checked as persistence model definitions; no candidate. |
| `src/trade_trace/security/__init__.py` | opened/structurally grouped with security helper exports; no candidate. |
| `src/trade_trace/security/credential_keys.py` | opened; credential key vocabulary reviewed; no candidate. |
| `src/trade_trace/security/keyring.py` | opened; keyring backend validation reviewed; no candidate. |
| `src/trade_trace/security/patterns.py` | source-scoped searched/contract-checked through exporter/logging scanner uses; no candidate. |
| `src/trade_trace/storage/__init__.py` | opened/structurally grouped with migration registry; no candidate. |
| `src/trade_trace/storage/database.py` | opened; candidate CSS-20260521-001 found. |
| `src/trade_trace/storage/edge_audit.py` | source-scoped searched/contract-checked as storage integrity helper; no candidate. |
| `src/trade_trace/storage/migrations/__init__.py` | opened/structurally grouped with migration registry; no candidate. |
| `src/trade_trace/storage/migrations/_runner.py` | opened; migration runner/meta drift policy reviewed; no candidate. |
| `src/trade_trace/storage/migrations/m001_meta.py` | structurally grouped with migration modules; no candidate. |
| `src/trade_trace/storage/migrations/m002_events_outbox.py` | structurally grouped with events/outbox schema; no candidate. |
| `src/trade_trace/storage/migrations/m003_m1_ledger.py` | structurally grouped with ledger schema; no candidate. |
| `src/trade_trace/storage/migrations/m004_p1_stub_columns.py` | structurally grouped with migration modules; no candidate. |
| `src/trade_trace/storage/migrations/m005_signals.py` | structurally grouped with signal schema; no candidate. |
| `src/trade_trace/storage/migrations/m007_strategies.py` | structurally grouped with strategy schema; no candidate. |
| `src/trade_trace/storage/migrations/m009_events_append_only.py` | opened; append-only triggers reviewed; no candidate beyond closed `trade-trace-dhm`. |
| `src/trade_trace/storage/paths.py` | opened; path resolution reviewed; contributes to CSS-20260521-001 assumption that explicit/env homes are not rejecting URI chars. |
| `src/trade_trace/storage/policy.py` | opened; migration policy reviewed; no candidate. |
| `src/trade_trace/timestamps.py` | source-scoped searched/contract-checked via event/export timestamp parsing; no candidate. |
| `src/trade_trace/version.py` | opened/contract-checked as package metadata; no candidate. |

## Commands/searches run

- Enumerated assigned rows:
  - `python - <<'PY' ... yaml.safe_load(... owner_lane == 'core-storage-security') ... PY`
- Direct file reads with line numbers:
  - `src/trade_trace/storage/database.py`
  - `src/trade_trace/events/log.py`
  - `src/trade_trace/exporter.py`
  - `src/trade_trace/security/keyring.py`
  - `src/trade_trace/security/credential_keys.py`
  - `src/trade_trace/events/unit_of_work.py`
  - `src/trade_trace/storage/migrations/m009_events_append_only.py`
  - `src/trade_trace/_permissions.py`
  - `src/trade_trace/storage/paths.py`
  - `src/trade_trace/storage/policy.py`
  - `src/trade_trace/storage/migrations/_runner.py`
  - `existing-audit-family-inventory.json`
- Source/test searches:
  - `open_database_readonly|mode=ro|ReadOnlyDatabaseError|query_only|\?` under `tests/`
  - `open_database_readonly` under `tests/`
  - `readonly.*missing|unsupported_schema|query_only|readonly database` under `tests/`
- Probe command:
  - temp SQLite database named `db?x.sqlite`; connected using current URI interpolation; observed sibling `db` creation/open via `PRAGMA database_list`.

## Coverage caveats

- This lane packet is claim-grounded but not exhaustive dynamic testing; I ran one focused temp-file probe and did not run the full test suite.
- Deadcode/reachability conclusions are source-scoped and exclude generated/cache/build artifacts; no decisive deadcode candidate was raised.
- Import/restore tool surfaces live mainly under `src/trade_trace/tools/` and were assigned to another lane; this lane reviewed storage/export/security helpers and noted overlap with closed restore/import safe-path work where relevant.

## Side-effect declaration

- Wrote exactly one allowed artifact: `/home/hermes/code/trade-trace/docs/reviews/repo-audit-20260521T173511Z/lane-core-storage-security.md`.
- No product/source/test files were modified. No Beads were created or updated. No destructive commands, package-manager operations, pushes, publishes, formatters, or shared-service mutations were run.
