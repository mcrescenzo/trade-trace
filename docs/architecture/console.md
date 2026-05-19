---
status: design — not implemented
owners: trade-trace
last_reviewed: 2026-05-19
bead: trade-trace-1kkv.1
---

# Trade Trace Console — Architecture and Read-Only Threat Model

> Status: **design — not implemented**. This document is the
> accepted contract for the Console MVP per trade-trace-1kkv.1.
> Implementation beads under the trade-trace-1kkv epic depend on
> this document; they should be opened only after the decisions
> below are accepted.

## Why this exists

The Trade Trace Console (trade-trace-1kkv) is a read-only local
dashboard for the journal. The MVP is meant to be the lowest-risk
surface that exposes journal state without changing it. Without a
written architecture contract, implementation beads risk diverging
on stack choice, lazy-write inclusion, redaction posture, etc.,
each of which alone is small but together would force a Console
rewrite mid-MVP.

This bead exists to *prevent* that. It names every decision
implementation work needs to assume.

## Decisions

### 1. CLI grammar — `tt console serve`

The launch verb is `tt console serve`. Subject-then-verb matches
every other tool in the registry (see `src/trade_trace/core.py:46`
`build_registry()`); `tt console` with no verb prints help and
exits non-zero. The `tt` and `trade-trace` script entry points
both accept the verb.

### 2. Browser-open default — open

`tt console serve` opens the default browser on the bound URL on
startup. Operators with no GUI environment pass `--no-browser` to
opt out. There is no `--browser` flag; the open-by-default keeps
the happy path one command. The CLI prints the URL to stdout
regardless so an operator can paste it manually.

### 3. Backend stack — FastAPI

The backend is built on FastAPI (which already sits on Starlette).
Rationale:

- Trade Trace already depends on Pydantic v2 (`pyproject.toml`
  `dependencies = ["pydantic>=2.7,<3"]`); FastAPI's request and
  response models reuse the existing contract types directly with
  no glue layer.
- FastAPI has the smallest learning surface among the three
  candidates for an async Python web service in 2026.
- `OpenAPI` documentation falls out of the framework, which is
  useful if a future bead exposes the endpoint surface to an
  alternative consumer (CLI, agent).
- Starlette alone would force re-implementing request validation;
  Flask is sync-only and would force a separate ASGI shim.

`FastAPI` ships under the `[console]` extra (see §5).

### 4. Frontend stack — htmx + vanilla DOM

The Console MVP renders server-side templates and uses htmx for
partial updates. There is no Node.js build pipeline. Rationale:

- Trade Trace targets local-first single-user operators. A
  build-time Node toolchain would (a) double the install surface,
  (b) introduce a JS dependency tree we have to audit, and (c)
  add a step between "install package" and "see dashboard".
- The Console exposes ~10 read-only views (journal browse,
  forecast list, decision list, reports, search) that do not need
  a SPA framework. Server-rendered HTML + htmx fragments is
  enough for filter/refresh/paginate UX.
- htmx is small, vendored, and works without npm. The single
  ~50 KiB JS file lives under
  `src/trade_trace/console/static/htmx.min.js` and is shipped in
  the wheel.

Static assets layout:

```
src/trade_trace/console/
    __init__.py
    app.py                 # FastAPI application factory
    templates/             # Jinja2 templates
    static/
        htmx.min.js
        css/console.css
        favicon.ico
```

The Jinja2 template engine is FastAPI's recommended templating
choice; it's already a transitive dep through Starlette in many
environments and we accept the pin via the `[console]` extra.

### 5. Dependency strategy — `[console]` extra

Console depends on FastAPI + Uvicorn + Jinja2. These are added as
an optional install:

```toml
[project.optional-dependencies]
console = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "jinja2>=3.1",
]
```

Rationale:

- The base wheel stays small for the journal / MCP use case
  (`pip install trade-trace` keeps the dependency tree to
  `pydantic` + `mcp`).
- Matches the precedent set by `embeddings` (sqlite-vec + keyring),
  which is already opt-in.
- `mcp` is base (trade-trace-o8j5) because every install needs
  the MCP server. The Console is an optional UI; operators using
  Claude Code never need it.

The CLI entry point checks for the import at `tt console serve`
launch and prints an actionable error if the extra isn't
installed:

```
Console requires the [console] extra:
    pip install 'trade-trace[console]'
```

### 6. SQLite read-only mechanism — URI mode

Every connection the Console opens uses SQLite's URI read-only
flag:

```python
sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
```

This sets the OS-level read flag; attempted writes raise
`sqlite3.OperationalError: attempt to write a readonly database`
instead of relying on call-site discipline. The Console opens
exactly one read-only connection pool; no code path acquires a
writable connection.

This is enforced by a unit test that asserts
`PRAGMA query_only;` returns `1` on every Console connection and
that the connection pool factory rejects non-URI `connect` calls.

### 7. Lazy-write handler list — enumerate and exclude

The Console exposes the report tools as read endpoints. The
following tools are flagged as **side-effect-risky** and the
Console MUST NOT call them:

| Tool             | Side effect                                                                 | Console disposition |
|------------------|------------------------------------------------------------------------------|---------------------|
| `signal.scan`    | Inserts rows into the `signals` table for every match (see `src/trade_trace/tools/signals.py:80`). | **Excluded.** Despite `is_write=False`, signal.scan persists results — incompatible with the read-only contract. |
| `report.coach`   | Coach aggregator references signal output; future revisions may invoke `signal.scan` transitively. | **Excluded** from the Console for the MVP. Re-evaluate after `signal.scan` is converted to a pure read or split into `signal.preview` + `signal.persist`. |

Every other registered `is_write=False` tool is presumed pure-read
and is callable from the Console. The lazy-write contract is a
**closed set** maintained in this document; any tool that newly
acquires a side effect must be added here in the same change that
introduces the side effect.

For the MVP the Console explicitly exposes:

- `report.pnl`, `report.risk`, `report.calibration`,
  `report.calibration_integrity`, `report.compare`,
  `report.decision_velocity`, `report.mistakes`,
  `report.opportunity`, `report.playbook_adherence`,
  `report.source_quality`, `report.strategy_performance`,
  `report.strengths`, `report.unscored_forecasts`,
  `report.watchlist`, `report.filter_schema`.
- Direct read queries against journal projections (decisions,
  forecasts, snapshots, positions, sources, memory_nodes,
  playbooks, strategies, events).

### 8. Sensitive-data redaction posture

The Console renders journal content in HTML. The render path
applies, in order:

1. **HTML escape**: every dynamic string passes through Jinja2's
   default autoescape. No raw `|safe` filter usage outside of
   pre-vetted whitelisted template fragments.
2. **Terminal escape strip**: ANSI escape sequences (`\x1b[...m`)
   are stripped before render. Operators paste tool output into
   journal entries; the Console must not let escape sequences
   reach the browser.
3. **Length truncation**: any string field rendered in a list or
   table view is truncated to 240 chars with a "…" and a "show
   full" link to a detail page. Detail pages render up to 16 KiB
   per field. Anything larger is replaced with a download link.
4. **Binary refusal**: fields with non-printable bytes or
   long base64 sequences are replaced with a placeholder
   (`<binary, N bytes>`). The Console does not attempt to inline
   images or files in the MVP.
5. **Secret pattern scrub**: every rendered string passes through
   `trade_trace.security.patterns.compiled_patterns()` — the same
   adapter the operational log redactor uses
   (`docs/architecture/logging.md` §Redaction). Matches are
   replaced with `***` before render.
6. **Field allowlist for IDs**: identifiers are rendered in full
   only when the field name is in the allowlist
   `{record_id, decision_id, subject, event_id, instrument_id,
   thesis_id, strategy_id, playbook_id, source_id, signal_id,
   memory_node_id}`. Other id-shaped strings are truncated to
   their last 8 characters with a hover-to-reveal.

### 9. Time-zone display contract — UTC default, browser-local toggle

Default render time zone is UTC, marked as such (`2026-05-19
14:30:00 UTC`). The global filter bar carries a toggle (radio:
`UTC | Local`) that switches every visible timestamp to the
browser's local time zone. The toggle is client-side only; the
server always returns UTC ISO 8601 strings.

The toggle state persists in `localStorage` under the key
`trade-trace-console.tz`. There is **no server-side preference
write** — preference persistence touches the browser, never the
journal DB. This is a strict invariant of the read-only contract.

### 10. Refresh-cadence contract — manual button + opt-in polling

- A **manual refresh button** is present on every page. The
  button is keyboard-bindable to `R`.
- A **staleness indicator** ("Data as of HH:MM:SS UTC") is
  rendered next to the refresh button on every page. The
  indicator is server-rendered with the request timestamp.
- **Optional N-second polling**: a small dropdown on the global
  filter bar offers `Off / 10s / 30s / 60s` (default `Off`).
  Polling reuses the htmx `hx-trigger="every Ns"` mechanism and
  triggers the same partial-refresh path as the manual button.
- Polling state persists in `localStorage` under
  `trade-trace-console.poll`. As with tz, no server-side write.

### 11. Browser-test framework — Playwright

The browser-test-scaffolding bead (trade-trace-1kkv.15) is
recommended to adopt **Playwright** (Python bindings) under a
new `[console-test]` extra. Rationale:

- Playwright bundles browsers, so CI doesn't need a separate
  browser install step.
- The Python bindings reuse our existing pytest infrastructure
  with `pytest-playwright`.
- Selenium and Cypress were considered. Selenium needs an
  external driver per browser; Cypress is JS-only.

The browser-test plan, default browsers (`chromium`), and the
test layout (`tests/console/`) are owned by trade-trace-1kkv.15
— this bead only names the framework.

### 12. Logs page — deferred out of MVP

The Console **Logs page is explicitly out of MVP scope**. It is
filed as the standalone follow-up bead trade-trace-jtec, which
depends on trade-trace-3zvl (operational logging contract) — the
contract that makes the Logs page possible at all. trade-trace-3zvl
landed in this work session; trade-trace-jtec remains open and is
**not** a 1kkv child.

### 13. Pagination contract — cursor-based

Every Console list endpoint paginates with a cursor:

```
GET /<list>?cursor=<base64>&limit=<n>
```

`cursor` is opaque base64url-encoded JSON (`{"after": <value>}`).
The caller never inspects it — they pass back whatever
`next_cursor` the previous response returned. The response is:

```json
{
  "rows": [...],
  "next_cursor": "<base64 string>" | null,
  "limit": <int, clamped to MAX_LIMIT>
}
```

`limit` defaults to 50 and is clamped to `MAX_LIMIT = 500` on the
backend. `next_cursor` is `null` when the page is the last one;
otherwise the caller appends `cursor=<next_cursor>` to the next
request.

Rationale (vs. offset/limit):

- Offset pagination scans every prior row on every page — the
  final page of a 100k-event journal costs as much as the first.
  Cursor pagination is a single index seek (`WHERE id > ?`).
- The cursor is stable across requests as long as the order key
  is monotone. The journal's primary `events.id` (autoincrement
  INTEGER PRIMARY KEY) satisfies that by construction.

Implementation: `trade_trace.console.pagination.paginate_query`.
The function is sqlite3-only and formats one extra row past the
limit to decide whether to emit a cursor. Multi-column order is
intentionally unsupported in MVP; composite cursors land if a
later Console page needs them.

#### Performance baseline

The Console's pagination layer ships with a representative-scale
perf test (`tests/integration/test_console_perf_baseline.py`).
The test:

- Seeds a 100k-row events table via direct SQL (deterministic;
  the existing `fixture.seed` only carries the M0-eval profile).
- Runs the equivalent of "first journal page" — one
  `paginate_query` against `events` with `ORDER BY id DESC` and
  `LIMIT 50`.
- Asserts wall-clock under **1 s** for the perf-fixture path
  with a 5× headroom to keep CI non-flaky.

The test runs opt-in via `TRADE_TRACE_RUN_PERF_TESTS=1`, matching
the convention set by `tests/integration/test_fixture_seed.py`
(trade-trace-29u0). CI flips the env var on a dedicated perf job
so the assertion lands in PR signal without slowing every test
run.

## Read-only threat model

Threats considered in scope for the MVP:

| Threat                                           | Mitigation                                                            |
|--------------------------------------------------|-----------------------------------------------------------------------|
| Console code accidentally opens a writable DB connection. | URI read-only mode + `PRAGMA query_only` assertion in pool factory. |
| Console invokes a side-effect-risky tool.        | Lazy-write handler list in §7 is the closed deny set; tests pin it.   |
| Migration runs from Console process.             | The Console process never imports `trade_trace.storage.migrations`; CI test asserts the module is not in `sys.modules` after `app.create()`. |
| HTTP request rewrites the journal via shell-out. | Console never spawns subprocesses; no `/exec` or `/eval` endpoint.    |
| Cross-site scripting via journal content.        | §8 render pipeline (escape + strip + scrub + allowlist).              |
| Console binds to a non-loopback address.         | Default bind is `127.0.0.1:8765`; non-loopback requires `--allow-non-loopback` with a stderr warning. Tests assert default bind. |
| Browser preference write hits the DB.            | tz + poll cadence persist in `localStorage` only (§9, §10).           |
| Operational log contains secret-shaped data.     | Redaction adapter shared with the exporter (`logging.md` §Redaction). |

Network isolation (shipped per trade-trace-1kkv.13):

- The Console process MUST NOT establish a non-loopback socket
  connection during normal operation. The test suite installs an
  `OutboundConnectionAttempted` guard
  (`tests/security/test_console_security_headers.py`) that fails
  any test where the Console reaches outside `127.0.0.0/8`,
  `::1`, or `localhost`.
- Every HTTP response carries the security header set defined in
  `trade_trace.console.security.SECURITY_HEADERS`: CSP (no
  `unsafe-inline`, no `unsafe-eval`, `'self'` only),
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`,
  `Permissions-Policy: camera=()...`, and `Cache-Control: no-store`.
- Templates referencing external resources fail the
  `external_resources_in_template` smoke test, so a future page
  change can't accidentally rely on a CDN.

Threats deferred to later beads:
- Pagination perf baseline on a 100k-event journal — owned by
  trade-trace-1kkv.14.
- Browser-side test scaffolding and golden screenshots — owned by
  trade-trace-1kkv.15.

## Out of scope for this bead

- Implementing the FastAPI app, templates, or static assets.
- Choosing color palette / visual polish.
- Designing the Logs page (separately deferred per §12).
- Defining the Console's pagination contract or perf baseline
  (deferred to trade-trace-1kkv.14).
- Choosing CSP / network-isolation defaults (deferred to
  trade-trace-1kkv.13).

## Acceptance gate

This document is the contract. Implementation beads under
trade-trace-1kkv MAY NOT introduce decisions that conflict with
§§1–12. If a conflict is necessary, the implementer opens a
follow-up bead to amend this document **first**, the amendment is
accepted, and only then does the implementation proceed.
