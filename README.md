# Trade Trace

**A local, open-source, AI-only journal, memory, and calibration substrate
for LLM trading agents.**

Trade Trace records the trading decisions an LLM agent makes and helps
the agent improve through a closed learning loop: journal a decision,
resolve the outcome, score calibration, review deterministic reports,
write reflections, update a versioned playbook, and recall that learning
next time. It runs locally, exposes both an MCP server and a CLI with
JSON-first contracts, and never executes trades.

## Status

Pre-release (`0.0.x`). MVP milestones M0–M4 + the agent-ready epic have
landed: storage, manual write surface, event log + idempotency,
deterministic reports + integrity diagnostics, a typed memory graph
with bi-temporal validity, first-class strategies, versioned playbooks
with adherence/override tracking, stdio MCP + `tool.schema` discovery,
optional opt-in embeddings (local model and OpenAI API), and
SHA-256-verified backup/restore. No stable `0.0.1` cut yet — see
[`docs/RELEASE_CHECKLIST.md`](./docs/RELEASE_CHECKLIST.md) and
[`SECURITY.md`](./SECURITY.md).

## Install

From PyPI:

```bash
pip install trade-trace
export TRADE_TRACE_HOME="$HOME/.trade-trace"
tt journal init
```

Requirements: Python 3.11+ and SQLite with FTS5 (see
[`docs/architecture/persistence.md`](./docs/architecture/persistence.md)
§2.1 for the build-dependency policy). MCP support is bundled by default.
Optional vector recall installs with `trade-trace[embeddings]`
(adds `sqlite-vec` and OS keyring support for local or API embeddings).
The optional read-only **Console** dashboard installs with
`trade-trace[console]` (FastAPI + Uvicorn + Jinja2); see
[`docs/CONSOLE.md`](./docs/CONSOLE.md).

For development:

```bash
pip install -e .
```

## Quickstart

The fastest path for an agent is the MCP stdio server:

```bash
trade-trace-mcp           # spoken on stdin/stdout — no network listen
```

See [`docs/AI_AGENT_MCP_GETTING_STARTED.md`](./docs/AI_AGENT_MCP_GETTING_STARTED.md)
for client configuration (Claude Code, Claude Desktop, Cursor, Windsurf,
Cline), actor identity (`MCP_ACTOR_ID`), required idempotency keys,
dry-run patterns, and a minimal end-to-end journal loop.

The CLI mirrors the MCP tool catalog and uses NDJSON envelopes
(`tt resolve pending` streams one envelope per record):

```bash
tt journal init
tt venue add --name Polymarket --kind prediction_market \
    --idempotency-key venue-1 --actor-id agent:default
tt instrument add --venue-id ven_... --asset-class prediction_market \
    --title "Will X happen by 2026-06-30?" \
    --idempotency-key inst-1 --actor-id agent:default
tt thesis add --instrument-id ins_... --side yes --body "..." \
    --idempotency-key thesis-1 --actor-id agent:default
tt forecast add --thesis-id th_... --kind binary \
    --outcomes-json '[{"outcome_label":"YES","probability":0.48},
                      {"outcome_label":"NO","probability":0.52}]' \
    --resolution-at 2026-06-30T00:00:00Z \
    --idempotency-key fc-1 --actor-id agent:default
tt decision add --instrument-id ins_... --type skip \
    --reason "edge < spread" \
    --idempotency-key dec-1 --actor-id agent:default
```

When the outcome lands, `tt outcome add --status resolved_final ...`
auto-scores every pending binary forecast against the resolved label
using the Brier form per
[`docs/architecture/scoring.md`](./docs/architecture/scoring.md) §3.

Run `tt tool schema --tool <name>` against any registered tool to get
the auto-derived input schema; the registry is the source of truth.

## What this is

- A **decision journal** with instruments, snapshots, theses, forecasts,
  outcomes, and process tags.
- A **trading-native memory layer** modeled on Retain / Recall /
  Reflect, with outcome-linked and calibration-aware recall.
- A **binary MVP calibration grader** that scores supported binary
  forecasts with Brier score when outcomes resolve.
- A **playbook loop** that versions rules, records manual/advisory
  overrides, and keeps provenance from reflections.
- **Strategies** that group decisions, theses, and reviews under a named
  edge thesis so reports, recall, and reflection can be scoped to one
  logical grain.
- An **MCP server** and **CLI** whose schemas and semantics are
  equivalent after transport normalization.

## What this is not

- Not a trade executor. No order signing, wallet handling, broker
  credentials, seed phrases, or trade routing.
- Not a remote service or broker dashboard. The optional
  `trade-trace[console]` extra ships a **local, read-only** review
  dashboard at `http://127.0.0.1:8765` — it does not execute trades,
  call broker APIs, or fetch market data; it reads the journal SQLite
  file via a SQLite URI `mode=ro` handle. See
  [`docs/CONSOLE.md`](./docs/CONSOLE.md).
- Not a generic agent memory framework. The schema is trading-shaped.
- Not a backtesting engine, tax accountant, social platform, or source
  of financial advice.

## Security and privacy

- **Outbound network is unconditionally off by default.** A fresh
  `journal.init` makes zero outbound calls; the boundary is verified by
  `tests/security/test_no_network_default.py`.
- **Credentials are never persisted.** Every write tool silently drops
  credential-shaped args (`api_key`, `wallet_seed`, `private_key`,
  `mnemonic`, `broker_token`, …); verified by
  `tests/security/test_no_credentials.py`.
- **Free-text fields are scanned at write time** for embedded secrets
  (OpenAI / Slack token / Ethereum address / JWT shapes). A match
  returns a `VALIDATION_ERROR` envelope before the row is inserted.
- **Idempotent retries.** Every retryable write requires
  `idempotency_key`; pure replays return the original event with
  `meta.idempotent_replay=true`; conflicting payloads return
  `IDEMPOTENCY_CONFLICT` with a structural diff (no raw bodies leaked).
- **Append-only invariants** are enforced by SQLite `BEFORE UPDATE/DELETE`
  triggers on every M1 source/event table; only the `positions`
  projection and the outbox state column are mutable.
- **Backups** carry a SHA-256 manifest; restore verifies every file's
  digest before copying and rejects path-traversal entries (see
  `tests/security/test_restore_manifest_paths.py`).
- **No telemetry.** Anything that looks like network access is a bug.

See [`SECURITY.md`](./SECURITY.md) for the supported-version policy and
how to report vulnerabilities via GitHub Security Advisories.

## Documentation

- [`docs/AI_AGENT_MCP_GETTING_STARTED.md`](./docs/AI_AGENT_MCP_GETTING_STARTED.md)
  — first-call walkthrough for an agent connecting via MCP.
- [`docs/AGENT_GUIDE.md`](./docs/AGENT_GUIDE.md)
  — longer journal-loop operating guide.
- [`docs/CLAUDE_CODE.md`](./docs/CLAUDE_CODE.md),
  [`docs/CLAUDE_DESKTOP.md`](./docs/CLAUDE_DESKTOP.md),
  [`docs/IDE_MCP_SETUP.md`](./docs/IDE_MCP_SETUP.md)
  — client setup recipes.
- [`docs/CONSOLE.md`](./docs/CONSOLE.md)
  — install/launch/page-map for the optional read-only Console
  dashboard (`trade-trace[console]`).
- [`docs/VISION.md`](./docs/VISION.md) — north star.
- [`docs/PRD.md`](./docs/PRD.md) — working PRD and MVP scope.
- [`docs/architecture/contracts.md`](./docs/architecture/contracts.md)
  — CLI/MCP envelope and error codes.
- [`docs/architecture/persistence.md`](./docs/architecture/persistence.md)
  — events, outbox, idempotency.
- [`docs/architecture/memory-layer.md`](./docs/architecture/memory-layer.md)
  — memory layer spec (node taxonomy, retrieval, bi-temporal validity,
  embeddings posture).
- [`docs/architecture/scoring.md`](./docs/architecture/scoring.md)
  — forecast scoring (Brier, log score, ECE, sharpness, reliability bins,
  lifecycle, `failure_reason` enum).
- [`docs/architecture/reports.md`](./docs/architecture/reports.md)
  — `ReportFilter` / `ReportResult` / drill-down / `review.bundle`.
- [`docs/architecture/operability.md`](./docs/architecture/operability.md)
  — timezone, multi-process, migrations, logging, blob caps, JSONL
  on-disk format.
- [`docs/RELEASE_CHECKLIST.md`](./docs/RELEASE_CHECKLIST.md)
  — version policy and pre-publish gates.

## License

MIT. See [`LICENSE`](./LICENSE).
