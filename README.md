# Trade Trace

**A local, open-source, AI-only journal, memory, and calibration substrate for LLM trading agents.**

Trade Trace records trading decisions an LLM agent makes and helps the agent improve through a closed learning loop: journal a decision, resolve the outcome, score calibration, review deterministic reports, write reflections, update a versioned playbook, and recall that learning next time. It runs locally, exposes both an MCP server and a CLI with JSON-first contracts, and never executes trades.

## What this is

- A **decision journal** with instruments, snapshots, theses, forecasts, outcomes, and process tags.
- A **trading-native memory layer** modeled on Retain / Recall / Reflect, with outcome-linked and calibration-aware recall.
- A **binary MVP calibration grader** that scores supported binary forecasts with Brier score when outcomes resolve.
- A **playbook loop** that versions rules, records manual/advisory overrides, and keeps provenance from reflections.
- **Strategies** that group decisions, theses, and reviews under a named edge thesis (e.g., `earnings-momentum`) so reports, recall, and reflection can be scoped to one logical grain without depending on free-form tags.
- An **MCP server** and **CLI** whose schemas and semantics are equivalent after transport normalization.

## What this is not

- Not a trade executor. No order signing, wallet handling, broker credentials, seed phrases, or trade routing.
- Not a human dashboard. There is no product web UI; P2 may add optional static/read-only inspection exports.
- Not a generic agent memory framework. The schema is trading-shaped.
- Not a backtesting engine, tax accountant, social platform, or source of financial advice.

For the full vision, see [`VISION.md`](./VISION.md). For the working PRD, see [`PRD.md`](./PRD.md).

## Status

**M0 / M1 / M2 / M3 / M4 shipped.** All four milestones cleared their
implementation, test-QC, docs-QC, and gate beads. Package skeleton +
storage + full manual write surface, event log + outbox + idempotency,
deterministic reports + integrity / source-quality diagnostics +
sample-size warnings, memory graph (retain/reflect/link/recall) with
bi-temporal validity + RRF over BM25 + temporal + graph, first-class
strategies, playbook versioning + normalized adherence + override-outcome
tracking, deterministic reflection-prompt packet, secret-pattern write
guard + file-permission + no-telemetry audit, journal backup/restore
with SHA-256 manifest, deterministic-replay clock injection + fixture
seed. The P1+ work that remains (embeddings opt-in, review.bundle / import
implementations, web/sync features) is explicitly scoped out of MVP and
tracked under beads `trade-trace-a4p` and the P1 design docs.

What works today:

- `pip install -e .` then `tt journal init` creates `$TRADE_TRACE_HOME/trade-trace.sqlite` with WAL, 5s busy_timeout, 0600 permissions, and the current schema head.
- The full manual ledger write surface: `venue.add`, `instrument.add`, `snapshot.add`, `thesis.add`, `forecast.add` (binary invariants enforced as `INVARIANT_VIOLATION`), `forecast.supersede`, `decision.add` (13-type required-field matrix enforced), `outcome.add` / `resolve.record` alias, `resolve.pending`, `source.add`, `source.attach_to_{thesis,decision,forecast}`. `source.attach_to_memory_node` returns `UNSUPPORTED_CAPABILITY` until M3.
- Decision → outcome → auto-scoring loop: an `outcome.add` with `status="resolved_final"` automatically scores every pending binary forecast against the resolved label using the single-probability Brier form per [`docs/architecture/scoring.md`](./docs/architecture/scoring.md) §3.
- Idempotent retries: every retryable write requires `idempotency_key` (per PRD §2); pure replays return the original event row with `meta.idempotent_replay=true`; semantically-different payloads return `IDEMPOTENCY_CONFLICT` with a structural diff (no raw bodies leaked).
- Append-only invariants enforced at the SQLite layer via BEFORE UPDATE/DELETE triggers on every M1 source/event table; the projection (`positions`) and the outbox state column are the only exceptions.
- `import.validate` and `import.commit` registered as contract stubs (P1 implementation pending); their schemas + the `import_ready_writers` list are introspectable today.
- `review.bundle` registered as a contract stub (P1 implementation pending); the input/output Pydantic schemas including `bundle_hash` are introspectable today.
- CLI emits NDJSON for list tools (`tt resolve pending`) with one envelope per record plus a summary line per [`docs/architecture/contracts.md`](./docs/architecture/contracts.md) §1.2; exit code mapping: `VALIDATION_ERROR`→2, `INVARIANT_VIOLATION`→3, other errors→1.
- A registration-time + startup CLI-name-collision check ensures two MCP tool names can never map to the same `tt` invocation; the runtime check emits a `STORAGE_ERROR` envelope rather than a Python traceback.
- UTC timestamps validated at the boundary: naive timestamps rejected, non-UTC offsets converted, sub-millisecond digits truncated.
- Outbound network is unconditionally off by default: `tests/security/test_no_network_default.py` monkeypatches `socket.connect`/`getaddrinfo` to refuse any outbound attempt and exercises the full ledger flow without a single call escaping.
- Credential-shaped args (api_key, wallet_seed, private_key, mnemonic, broker_token, etc.) are silently ignored by every write tool and never persist in any column or `metadata_json` blob; verified by `tests/security/test_no_credentials.py`.

Design artifacts:

- [`VISION.md`](./VISION.md) — north star
- [`PRD.md`](./PRD.md) — working PRD and MVP scope
- [`docs/architecture/memory-layer.md`](./docs/architecture/memory-layer.md) — memory layer spec (node taxonomy, retrieval, bi-temporal validity, embeddings posture)
- [`docs/architecture/scoring.md`](./docs/architecture/scoring.md) — forecast scoring (Brier, log score, ECE, sharpness, reliability bins, lifecycle, `failure_reason` enum)
- [`docs/architecture/persistence.md`](./docs/architecture/persistence.md) — events, outbox, idempotency (incl. §5.2.1 per-event-type structural-field registry)
- [`docs/architecture/contracts.md`](./docs/architecture/contracts.md) — CLI/MCP envelope and error codes
- [`docs/architecture/operability.md`](./docs/architecture/operability.md) — timezone, multi-process, migrations, logging, blob caps, JSONL on-disk format
- [`docs/architecture/reports.md`](./docs/architecture/reports.md) — `ReportFilter` / `ReportResult` / drill-down / `review.bundle`
- [`docs/architecture/imports.md`](./docs/architecture/imports.md) — JSONL/CSV local-import contract
- [`docs/architecture/risk-units.md`](./docs/architecture/risk-units.md) — P1 risk-unit / R-multiple analytics design
- [`docs/architecture/opportunity-analysis.md`](./docs/architecture/opportunity-analysis.md) — P1 path-dependent process diagnostics
- [`docs/architecture/dogfood-protocol.md`](./docs/architecture/dogfood-protocol.md) — MVP loop-usefulness protocol and provenance policies

## Install

Today (development):

```bash
pip install -e .
tt journal init
```

The published package (`pip install trade-trace`) ships once the MVP M1–M4
write surface lands. Requirements today: Python 3.11+, SQLite with FTS5.
The base wheel will ship `sqlite-vec` and `sentence-transformers` as runtime
dependencies once M3 lands.

**Vectors are off by default in MVP**: a fresh `journal.init` makes zero
outbound network calls (verified by `tests/security/test_no_network_default.py`).
MVP recall runs with FTS5 + graph + temporal retrieval. Opt in to semantic
recall via `tt config set embeddings.provider local` (one-time model-weight
download, ~130 MB; lands in M3) or `tt model import <path>` for air-gapped
installs. See [`docs/architecture/memory-layer.md`](./docs/architecture/memory-layer.md)
§8.

Trade Trace never fetches trading data, broker data, market prices, order books, or outcomes. The agent calling it supplies all market data through the structured ingestion APIs. The single opt-in outbound path (embedding model download) carries no trading data; the optional API-embeddings path is separately opt-in and warned about at configure time. See [`PRD.md`](./PRD.md) §2.4.1.

## MVP vertical slice

The MVP proves a complete learning-loop slice with narrow breadth:

1. `journal.init`
2. manual `instrument.add` / `snapshot.add` / `thesis.add` / binary `forecast.add` / `decision.add` — with optional `strategy_id` linkage to a named strategy
3. optional `strategy.create` to group decisions/theses/reviews under a named edge thesis (M3; nullable FK column is reserved in M1)
4. `outcome.add`
5. binary Brier scoring
6. deterministic reports and `report.coach` — all accept an optional `strategy_id` filter
7. agent-written `memory.reflect`, including reflections targeted at a strategy
8. `playbook.propose_version` with advisory/manual override tracking
9. `memory.recall` during the next thesis, optionally scoped to a strategy

Deferred or optional after the manual loop: JSONL/CSV import implementations (the write schemas are import-ready in MVP), `sqlite-vec` semantic recall, multi-class/scalar scoring, trading-native edge/market reports (forecast-vs-market, calibration-by-liquidity-bucket), `report.compare`, `report.strategy_performance`, `report.risk` (see [`docs/architecture/risk-units.md`](./docs/architecture/risk-units.md)), `report.opportunity` (see [`docs/architecture/opportunity-analysis.md`](./docs/architecture/opportunity-analysis.md)), `review.bundle` implementation, exact ForecastBench compatibility, sync, HTTP/SSE, websockets, and a web viewer.

## Quickstart for an agent (MCP, planned)

```jsonc
{"tool": "journal.init"}

{"tool": "instrument.add", "args": {
  "venue": "manual",
  "asset_class": "prediction_market",
  "title": "Will X happen by 2026-06-30?",
  "currency_or_collateral": "USDC",
  "actor_id": "agent:default"
}}

{"tool": "strategy.create", "args": {"name": "Thin-liquidity prediction markets", "slug": "thin-liquidity-prediction-markets", "hypothesis": "Markets with < $5K ADV near resolution are systematically mispriced; favor skips when spread > expected edge.", "actor_id": "agent:default"}}

{"tool": "snapshot.add", "args": {"instrument_id": "...", "price": 0.37, "bid": 0.36, "ask": 0.39, "actor_id": "agent:default"}}
{"tool": "thesis.add", "args": {"instrument_id": "...", "side": "yes", "body": "...", "falsification_criteria": "...", "strategy_id": "...", "actor_id": "agent:default"}}
{"tool": "forecast.add", "args": {"thesis_id": "...", "kind": "binary", "outcomes": [{"label": "YES", "probability": 0.48}, {"label": "NO", "probability": 0.52}], "actor_id": "agent:default"}}
{"tool": "decision.add", "args": {"instrument_id": "...", "thesis_id": "...", "type": "skip", "reason": "Estimated edge < spread + resolution risk", "strategy_id": "...", "tags": ["liquidity-ignored", "good-skip"], "actor_id": "agent:default"}}

{"tool": "outcome.add", "args": {"instrument_id": "...", "outcome_label": "NO", "outcome_value": 0.0, "status": "resolved_final", "resolved_at": "2026-06-30T00:00:00Z", "actor_id": "agent:default"}}

{"tool": "report.coach", "args": {"horizon_days": 30, "strategy_id": "..."}}

{"tool": "memory.reflect", "args": {
  "target": {"kind": "decision", "id": "..."},
  "insight": "Skip was correct here; spread compression never materialized.",
  "strength_tags": ["good-skip", "good-liquidity-discipline"],
  "actor_id": "agent:default"
}}

{"tool": "memory.recall", "args": {"context": {"kind": "strategy", "id": "..."}, "node_types": ["observation", "reflection", "playbook_rule"], "k": 10}}
```

## CLI dogfood surface

The CLI mirrors the MCP tool catalog. Stdout is JSON only by default;
`--human` may add prose to stderr without changing stdout semantics.

Working today (M0 + M1):

```bash
# Foundation
tt journal init                      # idempotent SQLite bootstrap
tt journal status                    # version + capability report
tt journal schema --tool Decision    # Pydantic JSON schema for a model

# Manual ledger write path (M1)
tt venue add --name "Polymarket" --kind prediction_market --actor-id agent:default
tt instrument add --venue-id ven_... --asset-class prediction_market \
    --title "Will X happen by 2026-06-30?" --currency-or-collateral USDC \
    --actor-id agent:default
tt snapshot add --instrument-id ins_... --captured-at 2026-05-18T14:00:00Z \
    --price 0.37 --bid 0.36 --ask 0.39 --actor-id agent:default
tt thesis add --instrument-id ins_... --side yes --body "..." --actor-id agent:default
tt forecast add --thesis-id th_... --kind binary \
    --outcomes-json '[{"outcome_label":"YES","probability":0.48},{"outcome_label":"NO","probability":0.52}]' \
    --resolution-at 2026-06-30T00:00:00Z --actor-id agent:default
tt decision add --instrument-id ins_... --type skip \
    --reason "Estimated edge < spread + resolution risk" --actor-id agent:default
tt outcome add --instrument-id ins_... --resolved-at 2026-06-30T00:00:00Z \
    --outcome-label NO --status resolved_final --actor-id agent:default
# (auto-scoring fires; forecast_scores row appears)

# Source / evidence (M1)
tt source add --kind research_doc --title "Liquidity profile" --stance supports \
    --actor-id agent:default
tt source attach_to_thesis --source-id src_... --target-id th_... --actor-id agent:default

# Resolution helpers (M1)
tt resolve pending                   # NDJSON stream of forecasts awaiting resolution
tt resolve record ...                # alias for `tt outcome add`
```

Shipped (M2–M4):

```bash
tt report calibration                # M2: Brier/log/ECE/sharpness panel + integrity diagnostics
tt report calibration_integrity      # M2: 6 anti-goodhart hygiene diagnostics
tt report source_quality             # M2: 5 provenance hygiene diagnostics
tt report mistakes / strengths       # M2: tag-aggregated patterns
tt report pnl / watchlist            # M2: position roll-up + stale-watch list
tt report unscored_forecasts         # M2: time-passed unscored detection
tt report decision_velocity          # M2: daily/weekly decision bucketing
tt report playbook_adherence         # M4: per-version followed/overridden counts
tt report coach                      # M2-M4: synthesized signal packet (no LLM)
tt memory retain / reflect / link    # M3: typed memory graph with bi-temporal validity
tt memory recall --query "..."       # M3: BM25+temporal+graph recall (RRF combined)
tt strategy create / list / show / update  # M3: first-class strategies
tt playbook create / propose_version / adherence  # M4: versioned playbooks
tt decision record_adherence         # M4: normalized adherence rows
tt reflection prompt_for_outcome     # M3: deterministic prompt packet
tt journal backup / restore          # MVP-hardening: SHA-256-verified roundtrip
tt journal config_set                # MVP-hardening: persisted config keys
tt journal fixture_seed --target=mvp-eval  # Deterministic eval-harness dataset
```

Still planned (P1+):

```bash
tt review bundle ...                 # P1 (contract is M1-locked; impl in P1)
tt import validate / import commit   # P1 (contract is M1-locked; impl in P1)
tt config set embeddings.provider local  # P1: sqlite-vec + bge-small (bead trade-trace-a4p)
tt model import / model warm         # P1: air-gap embedding model staging (bead a4p)
tt memory reindex --confirm          # P1: re-embed on provider change (bead a4p)
```

## License

MIT. See [`LICENSE`](./LICENSE).
