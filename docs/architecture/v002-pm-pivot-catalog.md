# v0.0.2 PM-pivot tool/report catalog reconciliation

> Status: **shipped** as of 2026-05-25; scope reined in + decision-time features added 2026-05-29 (epic trade-trace-4kec). The default public registry now exposes **70** tools, generated from `build_registry().public_names()`. The scope-reignin half froze **40** Product-B tools behind the experimental tier (`public_names(include_experimental=True)`; see §4.6) and removed **3** redundant report tools (KEEP 56 / FREEZE 40 / CUT 3 of the prior 99); the build half then reinvested the freed budget into **13** decision-time D1–D5 tools (§1.3), taking the default catalog to 69, and `market.search` (read-only live market discovery, bead trade-trace-663l) then took it to 70. Older 89 → 45 planning tables below are retained only as historical disposition context; use the current catalog summary and `tool.schema` for runtime truth.

## Why this exists

`next-steps.md` (the planning roadmap, now archived at
`docs/history/next-steps.md`) declared three different tool-count baselines —
**81**, **84**, and **45** target — across Parts I, II, and XV.
This document originally reconciled those planning numbers against the
then-current 89-tool registry. The pivot has since landed and the scope
was reined in by epic trade-trace-4kec; the runtime registry now reports
**56 public tools** in the default catalog, with 40 Product-B tools frozen
behind the experimental tier.

This doc pins the **authoritative runtime baseline** (Section 1),
keeps the old-tool disposition table as historical implementation
context (Section 2), collapses the unresolved-resolution semantics that
next-steps.md defaulted (Section 3), and records the transport contract
(`legacy_name`, removed-tool hints, and deprecation-clear errors) that
the catalog/transport gate (trade-trace-lznx) enforces (Section 4).

It does **not** rewrite next-steps.md or move existing docs; it
supersedes the disagreement between them by being the single
authoritative source the v0.0.2 implementation beads cite.

---

## 1. Current runtime baseline (2026-05-25)

Generated from `build_registry().public_names()` for the default public catalog: 70 tools. (The scope-reignin freeze/cut landed the surface at 56; epic trade-trace-4kec then reinvested the budget into 13 decision-time D1–D5 tools — see §1.3 — for 69; `market.search` then added the read-only live market discovery surface for 70.)

`abstention.get`, `abstention.list`, `abstention.record`, `decision.add`, `export.drain`, `forecast.add`, `forecast.commit_blind`, `forecast.independence`, `forecast.interpret_resolution`, `forecast.resolution_interpretation`, `forecast.reveal_snapshot`, `import.commit`, `journal.backup`, `journal.config_set`, `journal.fixture_seed`, `journal.init`, `journal.schema`, `journal.status`, `market.bind`, `market.find_similar`, `market.refresh`, `market.search`, `memory.link`, `memory.recall`, `memory.reflect`, `memory.retain`, `outcome.fetch`, `playbook.record_adherence`, `playbook.upsert`, `replay.case_bundle`, `replay.evaluate_output`, `replay_artifact.get`, `replay_artifact.list`, `replay_artifact.record`, `report.audit_readiness`, `report.bootstrap`, `report.calibration`, `report.calibration_advisory`, `report.calibration_integrity`, `report.coach`, `report.compare`, `report.current_exposure`, `report.exposure_anomalies`, `report.filter_schema`, `report.forecast_diagnostics`, `report.lifecycle`, `report.mistake_tripwire`, `report.mistakes`, `report.open_positions`, `report.opportunity`, `report.playbook_adherence`, `report.pnl`, `report.policy_candidates`, `report.process_analytics`, `report.process_quality`, `report.resolution_misreads`, `report.risk`, `report.source_quality`, `report.strategy_health`, `report.strengths`, `report.time_decay_sharpening`, `report.unscored_forecasts`, `report.watchlist`, `report.work_queue`, `resolution.add`, `review.bundle`, `snapshot.add`, `snapshot.fetch`, `strategy.upsert`, `tool.schema`.

### Frozen Product-B surface (experimental tier, epic trade-trace-4kec)

40 tools are registered and dispatchable but hidden from the default catalog
behind the experimental tier (`public_names(include_experimental=True)` /
`MCP_INCLUDE_EXPERIMENTAL=1`; see §4.6). They are the autonomous-ops cluster,
the reconciliation/execution-truth cluster, and the anchored-calibration unit
plus speculative viewers:

`account_snapshot.get`, `account_snapshot.import`, `account_snapshot.list`, `account_snapshot.report`, `approval.get`, `approval.list`, `approval.record`, `approval.report`, `autonomous_incident.record`, `autonomous_incident.report`, `autonomous_run.get`, `autonomous_run.record`, `external_receipt.get`, `external_receipt.import`, `external_receipt.list`, `external_receipt.report`, `forecast.anchor_to_snapshot`, `paper_fill.get`, `paper_fill.list`, `paper_fill.record`, `pretrade_intent.get`, `pretrade_intent.list`, `pretrade_intent.record`, `reconciliation.get`, `reconciliation.record`, `report.calibration_anchored`, `report.calibration_terminal`, `report.decision_velocity`, `report.execution_quality`, `report.market_lifecycle`, `report.memory_usefulness`, `report.operational_health`, `report.paper_exposure`, `report.recall_receipts`, `report.reconciliation_mismatches`, `report.resolution_quality`, `risk.check_record`, `risk.policy_version_add`, `snapshot.fetch_series`.

The 3 removed redundant report tools (`report.calibration_trajectory`,
`report.strategy_performance`, `report.amm_slippage`) are gone from the
registry entirely, not frozen.

Renamed public tools expose `legacy_name` metadata: `resolution.add` has legacy `outcome.add`, `playbook.record_adherence` has legacy `decision.record_adherence`, `playbook.upsert` has legacy `playbook.create`, and `strategy.upsert` has legacy `strategy.create`. `tool.schema` and MCP tool metadata also provide removed-tool/deprecation hints for legacy callers.

### Historical planning baseline (2026-05-23)

The older disposition table below was generated from `default_registry().names()` before the pivot landed and is retained as planning history, not as the current public catalog:

| Family | Count | Tools |
|---|---:|---|
| `agent`            |  2 | `agent.bootstrap`, `agent.next_actions` *(aliases — see §1.1)* |
| `decision`         |  2 | `decision.add`, `decision.record_adherence` |
| `export`           |  1 | `export.drain` |
| `forecast`         |  2 | `forecast.add`, `forecast.supersede` |
| `idea`             |  1 | `idea.capture` |
| `import`           |  3 | `import.commit`, `import.csv_fills`, `import.validate` |
| `instrument`       |  1 | `instrument.add` |
| `journal`          | 12 | `journal.backup`, `journal.bundle.plan`, `journal.bundle.status`, `journal.config_set`, `journal.fixture_seed`, `journal.init`, `journal.rebuild_projections`, `journal.repair`, `journal.rescan_scoring`, `journal.restore`, `journal.schema`, `journal.status` |
| `keyring`          |  1 | `keyring.revoke` |
| `market`           |  2 | `market.scan.dry_run`, `market.scan.promote` |
| `memory`           |  5 | `memory.link`, `memory.recall`, `memory.reflect`, `memory.reindex`, `memory.retain` |
| `model`            |  2 | `model.import`, `model.warm` |
| `outcome`          |  1 | `outcome.add` |
| `playbook`         |  6 | `playbook.adherence`, `playbook.create`, `playbook.list`, `playbook.list_versions`, `playbook.propose_version`, `playbook.show` |
| `reflection`       |  1 | `reflection.prompt_for_outcome` |
| `replay`           |  2 | `replay.case_bundle`, `replay.evaluate_output` |
| `report`           | 28 | *(see §1.2)* |
| `resolve`          |  2 | `resolve.pending`, `resolve.record` *(aliases — see §1.1)* |
| `review`           |  1 | `review.bundle` |
| `signal`           |  1 | `signal.scan` |
| `snapshot`         |  1 | `snapshot.add` |
| `source`           |  5 | `source.add`, `source.attach_to_decision`, `source.attach_to_forecast`, `source.attach_to_memory_node`, `source.attach_to_thesis` |
| `strategy`         |  4 | `strategy.create`, `strategy.list`, `strategy.show`, `strategy.update` |
| `thesis`           |  1 | `thesis.add` |
| `tool`             |  1 | `tool.schema` |
| `venue`            |  1 | `venue.add` |
| **Total**          | **89** | |

### 1.1 Why 89 and not 84

next-steps.md Part II AUDIT 2026-05-22 reports **84** based on a
literal count of `registry.register(...)` call sites. That count was
correct for that moment but missed:

- **2 alias namespaces** that share a handler with the canonical
  surface and were counted as one tool in the audit:
  `agent.bootstrap` (→ `report.bootstrap`), `agent.next_actions`
  (→ `report.work_queue`), `resolve.record` (→ `outcome.add`), and
  `playbook.adherence` (→ `report.playbook_adherence`). The runtime
  enumerates each name separately because each is a distinct CLI
  invocation. Three of those four are KILLed under §2; `resolve.record`
  goes when `outcome.add → resolution.add` lands.
- **`report.policy_candidates`** (commit `e25c0b9`, 2026-05-23): one
  net-new report ships in `report.*`.
- **`replay.evaluate_output`** likewise was registered after the
  audit snapshot.

The "84" number in next-steps.md was therefore stale during planning;
the implementation ultimately landed with the 65-tool public catalog,
since reined in to the 56-tool public catalog in §1 by epic
trade-trace-4kec. Treat the 89 → 45 language below as the historical
reduction target, not the current runtime truth.

### 1.2 Shipped reports (30 public)

Pinned by `SHIPPED_REPORTS` in
`tests/security/test_mvp_boundary_audit.py`. The names below are
authoritative; any addition must update that pin and this doc in the
same commit. Eleven report tools were frozen behind the experimental
tier and three were removed by epic trade-trace-4kec — see §1's frozen
list and the cut note — and four decision-time reports were added (§1.3).

`report.audit_readiness`, `report.bootstrap`, `report.calibration`, `report.calibration_advisory`, `report.calibration_integrity`, `report.coach`, `report.compare`, `report.current_exposure`, `report.exposure_anomalies`, `report.filter_schema`, `report.forecast_diagnostics`, `report.lifecycle`, `report.mistake_tripwire`, `report.mistakes`, `report.open_positions`, `report.opportunity`, `report.playbook_adherence`, `report.pnl`, `report.policy_candidates`, `report.process_analytics`, `report.process_quality`, `report.resolution_misreads`, `report.risk`, `report.source_quality`, `report.strategy_health`, `report.strengths`, `report.time_decay_sharpening`, `report.unscored_forecasts`, `report.watchlist`, `report.work_queue`.

### 1.3 Decision-time D1–D5 tools (13, epic trade-trace-4kec build half)

These reinvest the freed surface budget into the decision-time deficits the
triage identified (see `product-ab-fork-decision.md`):

- **D1 calibration**: `report.calibration_advisory` (read-at-decision-time
  recalibration), `abstention.record`/`abstention.get`/`abstention.list`
  (no-bet record so the denominator is not survivorship-biased),
  `report.process_quality` (bet-size vs declared-edge Kelly-consistency,
  outcome-independent).
- **D2/D5 mistakes & continuity**: `report.mistake_tripwire` (fire recurring
  mistake patterns matching a candidate decision's tags),
  `market.find_similar` (structural/analogical recall over markets, no
  embeddings/remote).
- **D3/D4 independence & ground truth**: `forecast.commit_blind` /
  `forecast.reveal_snapshot` / `forecast.independence` (prove a forecast
  preceded the market snapshot), `forecast.interpret_resolution` /
  `forecast.resolution_interpretation` + `report.resolution_misreads`
  (resolution-criteria reading vs actual source → contract-misread class).

---

## 2. Historical old → new disposition target (89 → 45)

Each row pins the v0.0.2 outcome for one runtime tool. Dispositions
are exactly one of **KEEP**, **RENAME**, **FOLD**, **KILL**, or
**NEW**. The `New surface` column names the tool the agent will
call once v0.0.2 ships.

### 2.1 KEEP (15 — verbatim or sharpened)

| Runtime tool | Disposition | New surface | Notes |
|---|---|---|---|
| `journal.init`              | KEEP | `journal.init` | unchanged |
| `journal.status`            | KEEP+ | `journal.status` | adds `adapter` + `cached_markets_count` sections per next-steps.md Part XVI |
| `journal.schema`            | KEEP | `journal.schema` | unchanged |
| `journal.config_set`        | KEEP+ | `journal.config_set` | adds `network.polymarket.*` keys |
| `journal.fixture_seed`      | KEEP+ | `journal.fixture_seed` | rewritten to Polymarket-shaped fixtures (j8g8) |
| `journal.backup`            | KEEP | `journal.backup` | unchanged; SHA-256 manifest retained |
| `journal.restore`           | KEEP | `journal.restore` | unchanged |
| `memory.retain`             | KEEP | `memory.retain` | unchanged; ONNX embeddings under the hood |
| `memory.reflect`            | KEEP | `memory.reflect` | unchanged |
| `memory.link`               | KEEP | `memory.link` | unchanged |
| `memory.recall`             | KEEP | `memory.recall` | unchanged |
| `tool.schema`               | KEEP | `tool.schema` | unchanged |
| `export.drain`              | KEEP | `export.drain` | unchanged |
| `review.bundle`             | KEEP | `review.bundle` | unchanged |
| `replay.case_bundle`        | KEEP | `replay.case_bundle` | unchanged |
| `replay.evaluate_output`    | KEEP | `replay.evaluate_output` | unchanged (post-audit registration) |

### 2.2 RENAME (2 — `meta.legacy_name` carries the old surface)

| Old | New | Notes |
|---|---|---|
| `outcome.add`                | `resolution.add`               | per next-steps.md §VI; `meta.legacy_name=outcome.add` on the new surface for one minor cycle, then dropped |
| `decision.record_adherence`  | `playbook.record_adherence`    | namespace consistency; same handler, same idempotency_key shape |

The dispatcher emits a typed `NOT_FOUND` envelope on the old name
once the rename lands, with `details.renamed_to=<new>` so the agent
gets a deterministic correction instead of a silent failure.

### 2.3 FOLD (18 — handler stays, surface collapses)

| Old | Folded into | Notes |
|---|---|---|
| `venue.add`                  | `market.bind`                | venue/instrument become market metadata fields |
| `instrument.add`             | `market.bind`                | ↑ |
| `thesis.add`                 | `forecast.add.rationale_body`| `theses` table dropped (qmmd/4lki) |
| `forecast.supersede`         | `forecast.add.supersedes_forecast_id` | edge edge — same write path |
| `source.add`                 | *dropped* — sources move into `metadata_json.sources` array | `sources` table dropped |
| `source.attach_to_thesis`    | ↑ | ditto |
| `source.attach_to_decision`  | ↑ | ditto |
| `source.attach_to_forecast`  | ↑ | ditto |
| `source.attach_to_memory_node` | ↑ | ditto |
| `strategy.create`            | `strategy.upsert`            | list via `report.strategy_health` |
| `strategy.update`            | `strategy.upsert`            | ↑ |
| `strategy.list`              | `report.strategy_health`     | ↑ |
| `strategy.show`              | `report.strategy_health`     | ↑ |
| `playbook.create`            | `playbook.upsert`            | rationalize playbook surface to upsert |
| `playbook.show`              | `playbook.upsert` *(read mode)* | ↑ |
| `playbook.list`              | `playbook.upsert` *(read mode)* | ↑ |
| `playbook.list_versions`     | `playbook.upsert` *(read mode)* | ↑ |
| `import.validate`            | `import.commit._dry_run`     | one tool, two modes |
| `journal.rescan_scoring`     | `journal.rebuild_projections`| one rebuild path |

### 2.4 KILL (15 — surface removed, capability dropped or implicit)

| Killed tool | Reason | Caller redirect |
|---|---|---|
| `agent.bootstrap`              | alias of `report.bootstrap` | `report.bootstrap` |
| `agent.next_actions`           | alias of `report.work_queue` | `report.work_queue` |
| `playbook.adherence`           | alias of `report.playbook_adherence` | `report.playbook_adherence` |
| `resolve.record`               | alias of `outcome.add` (and target is renamed) | `resolution.add` |
| `resolve.pending`              | duplicated by `report.work_queue` | `report.work_queue` |
| `idea.capture`                 | subsumed by `memory.retain` | `memory.retain` |
| `market.scan.dry_run`          | replaced by `market.bind` + adapter | `market.bind` |
| `market.scan.promote`          | ↑ | `market.bind` |
| `journal.bundle.plan`          | replaced by adapter | none — capability dropped |
| `journal.bundle.status`        | ↑ | none |
| `reflection.prompt_for_outcome`| prompt assembly belongs to the agent, not the journal | none |
| `import.csv_fills`             | JSONL-only via `import.commit` | `import.commit` |
| `memory.reindex`               | cosmetic; no embeddings-provider switching under v0.0.2 | none |
| `model.import`                 | replaced by inline ONNX runtime | none |
| `model.warm`                   | ↑ | none |
| `keyring.revoke`               | no embeddings provider keys in v0.0.2 | none |

Killed tools must surface a typed `UNSUPPORTED_CAPABILITY` envelope
(not `NOT_FOUND`) when called, with `details.redirect=<new surface or
null>` and `details.removed_in="0.0.2"`. The dispatcher learns to
emit this from a small redirect table; the CLI surfaces the same
envelope through the existing `_emit_cli_error` path.

### 2.5 Admin-only (3 — kept, gated)

| Tool | Notes |
|---|---|
| `signal.scan`                  | only one signal kind; flagged admin-only in the MCP listing |
| `journal.rebuild_projections`  | admin maintenance |
| `journal.repair`               | admin maintenance |

These remain registered but the catalog/transport surface marks them
`is_admin=True` so an MCP client filtering for the default catalog
omits them. They count against the v0.0.2 total of 45.

### 2.6 NEW (6 adapter primitives + 1 forecast anchor)

| New tool | Purpose | Default network behavior |
|---|---|---|
| `market.search(query?, limit?, closed?)`     | **read-only** live discovery of bindable binary (YES/NO) markets via the Gamma list API; returns `external_id`/`gamma_market_id`, `slug`, `question`, `outcomes`, `close_at`. Closes the discovery gap (bead trade-trace-663l): a bot can find markets to forecast on without a pre-known `external_id`, an already-bound market, or an out-of-band Gamma curl. No DB writes, no advice, no trade execution. | adapter-only; fails closed with `ADAPTER_DISABLED` when disabled |
| `market.bind(external_id, source)`           | fetch/cache market metadata; idempotent; populates `markets.*_at` state columns | adapter-only; disabled by default |
| `market.refresh(market_id)`                  | re-fetch state for a bound market | adapter-only; disabled by default |
| `snapshot.fetch(market_id, at=now)`          | capture live implied probability | adapter-only; falls back to `snapshot.add` (manual) when disabled |
| `snapshot.fetch_series(market_id, from, to)` | capture trajectory series for `report.time_decay_sharpening` and `report.calibration_anchored` baselines | adapter-only; **no background scheduler** (see §3.3); falls back to manual `snapshot.add` loop when disabled |
| `outcome.fetch(market_id)`                   | ingest on-chain resolution | adapter-only; **no background scheduler**; requires `network.polymarket.polygon_rpc_url` for the on-chain confirmation step (fails closed `CONFIG_REQUIRED` when unset, with a `no_rpc_resolution_evidence_route` / `hint` pointing at the Gamma read path — see §3.6); manual `resolution.add` is always available |
| `forecast.anchor_to_snapshot(forecast_id, snapshot_id)` | post-hoc anchor for `report.calibration_anchored`; idempotent; corrections via `supersedes_forecast_id` | local-only |

### 2.7 Report consolidation (28 → 13)

next-steps.md Part II §"Report Consolidation" carries the
authoritative mapping. This doc adopts that mapping verbatim and
adds one row: **`report.policy_candidates`** (shipped 2026-05-23)
is **KEEP**ed unchanged — it is a P2 read-only memory-evidence
surface and does not duplicate any consolidation target.

| New surface | Consolidates / status |
|---|---|
| `report.calibration`              | `calibration` + `calibration_integrity` (nested as sections) |
| `report.calibration_anchored`     | NEW (§3.1) |
| `report.calibration_terminal`     | NEW (§3.2) |
| `report.calibration_trajectory`   | NEW (time-to-resolution calibration trend) |
| `report.forecast_diagnostics`     | unchanged |
| `report.book`                     | `pnl` + `open_positions` + `current_exposure` + `exposure_anomalies` + `watchlist` |
| `report.risk`                     | unchanged |
| `report.audit`                    | `audit_readiness` + `source_quality` + `playbook_adherence` |
| `report.lifecycle`                | unchanged |
| `report.recall`                   | `recall_receipts` + `memory_usefulness` (per-item) |
| `report.work_queue`               | unchanged + `decision_velocity` fold |
| `report.bootstrap`                | composer over the above |
| `report.coach`                    | narrowed (forbidden-phrase gate retained) |
| `report.strategy_health`          | absorbs `strategy_performance` |
| `report.compare`                  | unchanged |
| `report.policy_candidates`        | KEEP (post-audit addition) |
| `report.market_lifecycle`         | NEW (PM-native) |
| `report.resolution_quality`       | NEW (PM-native) |
| `report.amm_slippage`             | NEW (PM-native) |
| `report.time_decay_sharpening`    | NEW (PM-native) |

Killed reports: `mistakes`, `strengths`, `opportunity`,
`unscored_forecasts`, `decision_velocity` (fold), `pnl`,
`watchlist`, `open_positions`, `current_exposure`,
`exposure_anomalies`, `audit_readiness`, `source_quality`,
`playbook_adherence`, `strategy_performance`, `memory_usefulness`,
`calibration_integrity` (fold), `recall_receipts`,
`filter_schema` (introspect via `tool.schema`).

That comes out to **13 KEEP/consolidated + 4 NEW PM-native + 3
NEW calibration-baseline/trajectory = 20** report surfaces — close to but not
equal to the prior "13" copy. The prior count predates
`report.policy_candidates`, `report.calibration_terminal`, and the
explicit split of anchored vs unchanged.

### 2.8 Headline totals

The 45-tool target previously published assumed 13 reports. Once
the post-audit additions are absorbed, the v0.0.2 catalog lands at:

- Journal + backup/restore: **5 KEEP + 3 admin-only = 8**
- Memory: **4 KEEP**
- Market/forecast/resolution write surface: **8** (`market.bind`,
  `market.refresh`, `snapshot.add`, `snapshot.fetch`,
  `snapshot.fetch_series`, `outcome.fetch`, `resolution.add`,
  `forecast.add`)
- Strategy/playbook: **2** (`strategy.upsert`, `playbook.upsert`)
- Adherence: **1** (`playbook.record_adherence`)
- Forecast anchor: **1** (`forecast.anchor_to_snapshot`)
- Decision: **1** (`decision.add`)
- Import/export: **2** (`import.commit`, `export.drain`)
- Review/replay: **3** (`review.bundle`, `replay.case_bundle`,
  `replay.evaluate_output`)
- Reports: **35** (`report.*`, per §2.7)
- Tools: **1** (`tool.schema`)
- Signals: **1** admin-only

**Total: 68 registered surfaces (65 default + 3 admin-only).**

The "45" figure in next-steps.md was a target *before* the
`report.policy_candidates` ship, the explicit
`report.calibration_terminal` split, and the
`forecast.anchor_to_snapshot` separation. The pragmatic target is
**~50**; the previously published "45" is now a *floor*, not a
hard contract.

---

## 3. Unresolved-resolution defaults

next-steps.md flagged five decisions as "defaulted". This section
pins the default so downstream beads can rely on it without
re-deriving.

### 3.1 `report.calibration_anchored` semantics

**Decision:** Anchored calibration is computed over forecasts that
have a `forecast.anchor_to_snapshot` edge. The baseline is the
snapshot's implied probability at anchor time; skill is reported as
agent — market in probability units, **not in P&L units**. The
absence of an anchor produces a `coverage.unanchored_count` row in
the diagnostics panel, not an error.

### 3.2 `report.calibration_terminal` semantics

**Decision:** Terminal calibration uses the market's
`closed_for_trading_at` snapshot (or last snapshot before
`resolved_at` when the cleaner field is missing) as baseline.
Markets without a terminal snapshot produce a
`coverage.no_terminal_snapshot_count` row. Output shape is
*identical* to `report.calibration_anchored` so the agent can switch
baselines without changing its parser. Implemented as a thin variant
of the anchored handler.

### 3.3 No background outcome fetching

**Decision:** v0.0.2 ships **no scheduler, no daemon, no background
worker** of any kind. `outcome.fetch` and `snapshot.fetch_series`
are agent-driven explicit calls. The journal does not auto-fetch
on idle, on dispatch, or on `journal.init`. This preserves the
local-first / no-network-by-default product invariant and keeps the
adapter's failure mode confined to the explicit call site.

If the agent wants periodic refresh, it owns that loop and surfaces
the cadence in its own logs — `tt market refresh ...` over a cron
on the agent's host is fine; auto-refresh inside trade-trace is
not.

### 3.4 Manual `market.bind` metadata shape

**Decision:** A `market.bind` call with no adapter (manual mode)
requires the caller to supply every non-generated, non-null column
on the `markets` table explicitly. The handler does **not** guess
or interpolate `resolution_rule_text`,
`closed_for_trading_at`, etc. Missing required fields raise
`VALIDATION_ERROR` with `details.required_fields=[…]`. This keeps
manual binds honest about provenance and prevents agents from
inventing market semantics by omission.

### 3.4a Polymarket `resolution_source` mechanism mapping

**Decision (bead trade-trace-v5va, design half of AX-067):** the
Polymarket adapter maps a bound market to the venue-agnostic
`resolution_source` taxonomy
(`market_contract` / `oracle_feed` / `manual_review` / `arbitration`,
enforced by the `markets` CHECK in migration `m012`) by **mechanism**,
not by a coarse catch-all default.

**Why this changed.** The faithful Polymarket resolution mechanism is
the **UMA optimistic oracle**: a proposer asserts the outcome by
reading the market's stated resolution prose, anyone may dispute, and
disputes escalate to the UMA DVM token-holder vote. There is no
purely on-chain, deterministic `market_contract` resolution on
Polymarket — UMA always sits in the loop. The previous adapter
default (`out.get("resolution_source") or ("arbitration" if disputed
else "market_contract")`) therefore stamped the **least faithful**
value on every non-disputed market. Because `report.resolution_misreads`
scores an agent's `interpreted_resolution_source` against
`markets.resolution_source`, the report could **never** record
`aligned` for a defensible `oracle_feed` reading of a UMA-over-Binance
crypto strike on the live venue, and hard-classified it
`contract_misread` against a constant default — making the diagnostic
unreliable exactly where it is used.

**The mapping** (`adapter_polymarket._resolution_source`):

- **Venue-supplied enum value wins.** If
  `outcome.resolution_source` is already one of the four enum values
  (the path synthetic fixtures and any future faithful Gamma field
  take), it is honored verbatim.
- **`arbitration`** — the market is disputed (the UMA assertion was
  challenged and escalated to the DVM vote).
- **`manual_review`** — ambiguous / unresolvable-by-rule outcomes
  (state `ambiguous`, `raw.ambiguous`, or `outcome.status ==
  "ambiguous"`).
- **`oracle_feed`** — every other (non-disputed, non-ambiguous)
  Polymarket market. This is the faithful default: the UMA optimistic
  oracle is the resolver.

**Consequence.** An agent that reads an undisputed Polymarket market
as `oracle_feed` now scores `aligned`. The provenance/caveat surfacing
shipped in commit 81345c8 (`actual_source_provenance=bound_via`,
`contract_misread_adapter_bound_count`, the adapter caveat) stays in
place; it now fires only when an agent's reading genuinely disagrees
with the faithfully-mapped mechanism (e.g. reading a disputed
`arbitration` market as `oracle_feed`), where it correctly remains a
lower-confidence misread. `market_contract` is retained in the enum
(other venues / explicit venue values may use it) but is no longer the
Polymarket catch-all.

### 3.5 Legacy 0.0.1rc3 import behavior

**Decision:** `import.commit` against a 0.0.1rc3-shaped JSONL bundle
fails with `UNSUPPORTED_CAPABILITY` (not `STORAGE_ERROR`) carrying
`details.reason="legacy_format"`,
`details.detected_version="0.0.1rc3"`, and
`details.transform_required=true`. A separate transform tool — if
ever shipped — lives outside the v0.0.2 surface and is approved as
its own bead. Users with 0.0.1rc3 bundles re-import from their
upstream source (the producing agent's logs / broker exports), which
they generally still have because there is no 0.0.1 stable cut.

### 3.6 No-RPC resolution-evidence route (`outcome.fetch` vs Gamma read path)

**Decision (bead trade-trace-isqo):** `outcome.fetch` ingests
*on-chain* resolution and therefore requires
`network.polymarket.polygon_rpc_url`; with that key unset it fails
closed with `CONFIG_REQUIRED`
(`details.config_key = "network.polymarket.polygon_rpc_url"`). We do
**not** auto-fall back to the Gamma-reported outcome, because doing so
would silently substitute a venue read for on-chain confirmation and
weaken the finality guarantee of an `outcome`/`resolution` row — a
resolution-contract change that is out of scope for a no-RPC
deployment to make implicitly.

Instead, the no-RPC deployment (Gamma enabled, `polygon_rpc_url`
unset) has a **signposted** alternative: the Gamma read path
(`snapshot.fetch` / `market.refresh`) needs no RPC endpoint and
already surfaces Gamma's resolution-evidence fields
(`winningOutcome` / `outcomePrices`, normalized into
`markets.venue_metadata_json`). A caller reads that evidence and
records the resolution with `resolution.add`, which is always
available regardless of adapter config.

To stop an automated resolution feeder from dead-ending here (which
would leave forecasts perpetually pending and never reach the
calibration `N>=20` floor), two non-contract-changing signposts were
added:

- `outcome.fetch`'s `CONFIG_REQUIRED` error now carries
  `details.no_rpc_resolution_evidence_route = "snapshot.fetch"` and a
  human-readable `details.hint` naming the Gamma read path +
  `resolution.add`.
- The `resolve_due_forecast` work-queue obligation
  (`report.work_queue` / `report.bootstrap`) lists
  `fetch_gamma_resolution_evidence_via_snapshot_fetch_when_no_polygon_rpc`
  in its `allowed_actions`, so the no-RPC route is discoverable from
  the obligation itself, not only from the failed call.

The forbidden-action and read-only boundary of `report.work_queue`
is unchanged: this is a pointer to an existing adapter read tool, not
a new fetch/scheduler/broker capability.

---

## 4. Transport contract for the catalog/transport gate

These pin the boundary that the catalog/transport gate
(`trade-trace-lznx`) verifies before adapter/report work proceeds.

### 4.1 `legacy_name` metadata on renamed public tools

The default public catalog exposes canonical v0.0.2 names. Tool metadata
carries compatibility hints for legacy callers: `resolution.add` has
`legacy_name = "outcome.add"`, `playbook.record_adherence` has
`legacy_name = "decision.record_adherence"`, `playbook.upsert` has
`legacy_name = "playbook.create"`, and `strategy.upsert` has
`legacy_name = "strategy.create"`. These hints are visible through
`tool.schema` and MCP tool specs, not as caller-controlled payload data.

### 4.2 Legacy names remain hidden but dispatchable during the additive slice

Old names such as `outcome.add`, `decision.record_adherence`,
`agent.next_actions`, and `venue.add` remain dispatchable for local
compatibility and import/test paths, but default catalog listings hide
them. Their registry metadata carries `renamed_to`, `redirect`, and/or
`removed_in = "0.0.2"` so agents can move to the canonical surface
without a docs round-trip.

### 4.3 Removed/folded tools are metadata-described, not default-advertised

Removed or folded tools are absent from `public_names()` and from the
default MCP/list-tools surface. When included through explicit legacy
inspection, their metadata distinguishes renamed tools from folded or
removed tools via `renamed_to`, `redirect`, and `removed_in`.

### 4.4 MCP/tool-schema filters for admin and legacy surfaces

The default surface a normal agent sees omits legacy tools and admin-only
tools (`signal.scan`, `journal.rebuild_projections`, `journal.repair`).
Admin and legacy surfaces are opt-in inspection modes; current quickstarts
should point agents at the 60-tool public catalog and `tool.schema` for
runtime truth.

### 4.6 Experimental tier (frozen Product-B surface)

`catalog_visibility="experimental"` is a distinct opt-in tier from `legacy`,
used to freeze the autonomous-ops / reconciliation surface (epic
trade-trace-4kec) without deleting handlers. Experimental tools are:

- **Hidden** from the default catalog — absent from `public_names()`,
  `tool.schema` catalog mode, and the MCP list-tools surface.
- **Still dispatchable** — `dispatch()` resolves by `by_name`, so a frozen
  tool remains callable for tests and explicit opt-in callers.
- **Not surfaced by `include_legacy`** — the two tiers are independent;
  `include_legacy=True` does not reveal experimental tools and vice versa.

Opt-in mechanisms (mirroring the admin/legacy precedent):

- **Flag**: `tool.schema {"include_experimental": true}` and
  `public_registrations(include_experimental=True)`.
- **Env**: set `MCP_INCLUDE_EXPERIMENTAL=1` to surface the tier in the MCP
  list-tools catalog (parallel to `MCP_INCLUDE_ADMIN=1`).

### 4.5 Boundary-audit pin

`tests/security/test_mvp_boundary_audit.py` pins the shipped public tool
set (`test_shipped_public_tool_catalog_is_locked`), verifies legacy tools
are hidden but metadata-explained, and keeps the report set pinned via
`test_shipped_report_tool_set_is_locked`. Subsequent catalog changes must
update those pins and docs together.

---

## 5. Verification

```sh
# 1. Runtime public-catalog count (sanity check on this doc)
PYTHONPATH=src python -c \
  "from trade_trace.core import default_registry; \
   print(len(default_registry().public_names()))"
# Expected: 70

# 1b. Frozen experimental Product-B surface (epic trade-trace-4kec)
PYTHONPATH=src python -c \
  "from trade_trace.core import default_registry as r; \
   print(len(r().public_names(include_experimental=True)) - len(r().public_names()))"
# Expected: 40

# 2. Shipped public catalog, legacy metadata, admin filtering, reports pin, and freezes
PYTHONPATH=src pytest \
  tests/security/test_mvp_boundary_audit.py::test_shipped_public_tool_catalog_is_locked \
  tests/security/test_mvp_boundary_audit.py::test_legacy_catalog_tools_are_hidden_but_metadata_explains_transition \
  tests/security/test_mvp_boundary_audit.py::test_admin_tools_are_not_in_default_catalog \
  tests/security/test_mvp_boundary_audit.py::test_shipped_report_tool_set_is_locked \
  tests/security/test_mvp_boundary_audit.py::test_frozen_autonomous_ops_cluster_is_experimental_but_dispatchable \
  tests/security/test_mvp_boundary_audit.py::test_frozen_reconciliation_cluster_is_experimental_but_dispatchable \
  tests/security/test_mvp_boundary_audit.py::test_frozen_anchored_viewers_cluster_is_experimental_but_dispatchable \
  -q
# Expected: 7 passed
```

---

## 6. Out of scope

- Implementing any catalog change (handled in
  trade-trace-rooi, trade-trace-pcxf, trade-trace-t97r, and the
  schema/adapter implementation clusters).
- Polymarket adapter implementation (trade-trace-mmze,
  trade-trace-2h0g).
- The `markets.*_at` migration (trade-trace-qmmd).
- HITL live-adapter smoke (trade-trace-6i38).
- Public release actions (trade-trace-voum,
  trade-trace-3l6w).
