# Trade Trace v0.0.2: Prediction-Market Pivot + Remediation Roadmap

> **Status:** Planning / historical roadmap. PM-only pivot approved 2026-05-22. Single comprehensive v0.0.2 release.
> **CLI examples are target spellings for v0.0.2, not the current `default_registry` surface.** Today's CLI uses the `subject.verb` grammar shipped on `main` (e.g., `tt journal.init`, `tt forecast.add`); the hyphenated `subject verb` forms below land with the planned CLI grammar respec in Part X. For current canonical CLI guidance, see `README.md` and `docs/AGENT_GUIDE.md`.
> **Method:** Two investigation rounds + three-agent catalog audit + brainstorming session + follow-up audit pass against codebase (2026-05-22 PM).
> **Predecessor:** This document expands the original v0.0.1rc3 remediation plan with the v0.0.2 PM pivot strategic frame. Existing technical remediation items are preserved and re-prioritized under the new scope.

> **Revision log (2026-05-22 PM audit):** Three parallel Explore-agent audits cross-checked every claim against the codebase. Corrections applied below. Open architectural decisions (forecast_outcomes shape, position_records.side, meta_json rename, source-edge handling) resolved in line with the greenfield/no-users posture. Resolutions tagged inline as `[AUDIT 2026-05-22]`.

---

## Executive Summary

**The pivot:** Trade Trace narrows from "agent-native journal for any trading domain" to **"local-only calibration journal and memory substrate for LLM prediction-market trading agents."** Polymarket is the canonical venue in v1; Kalshi/Manifold are post-v1 adapter targets.

**Headline moves (v0.0.2, single release):**

1. **Scope:** PM-only. Drops equities, options, futures, crypto spot/perp, FX. Overrides VISION non-goal #5.
2. **Network policy:** Opt-in Polymarket adapter (default off). Local-first promise preserved.
3. **Workflow:** Trading-primary, forecasting-supported. `decision.type='watch'` is the pure-forecast path.
4. **Scoring:** Binary-only. Delete `brier_multiclass` and `squared_error_scalar` (~70 LOC + 3 tests).
5. **Versioning:** Hard break 0.0.1rc3 → 0.0.2. No migration shims. Greenfield, no users.
6. **Renaming:** Keep "Trade Trace." Tagline and docs do the repositioning.
7. **Tool catalog:** **89 → ~50 surfaces (~44 % reduction)**. [AUDIT 2026-05-23 / trade-trace-sx4n: runtime baseline is 89, not 84/81 — the audit pre-dated `report.policy_candidates` and `replay.evaluate_output` and counted four alias namespaces as one tool. The 45 target was a floor; the realistic landing zone after `report.calibration_terminal`, `report.policy_candidates`, and `forecast.anchor_to_snapshot` split out is ~50 (47 default + 3 admin-only). See **`docs/architecture/v002-pm-pivot-catalog.md`** for the authoritative old→new disposition of every shipped tool.]
8. **Schema:** New `markets` entity. Drop `theses` table (fold into forecast). Drop `sources` table (fold into `metadata_json`). Collapse `forecast_outcomes` 1:many table into a flat `forecasts.probability` column (binary-only). Prune `decision.type` from 13 → 8 values. Prune `decision.side` from 6 → 3 values (3 dropped: `long`, `short`, `pairs_long_short`). [AUDIT 2026-05-22.]
9. **New capabilities:** `market.bind`, `snapshot.fetch`, `outcome.fetch`, anchored-baseline calibration, four PM-native reports (`market_lifecycle`, `resolution_quality`, `amm_slippage`, `time_decay_sharpening`).
10. **Existing remediation absorbed:** Vector embeddings (ONNX), trajectory/terminal calibration baselines, ECE equal-mass binning, report filter implementation, module split, idempotency auto-derivation, test-order fixes — all in v0.0.2 scope.

**Estimated call burden per agent cycle:** 8 calls today → 5 calls with adapter (7 without adapter). Zero hand-crafted idempotency keys.

**Performance SLOs pinned (Part XVII):** `report.bootstrap` warm < 150 ms p95; `market.bind` (adapter on) < 2 s p95; `forecast.add` / `decision.add` < 30 ms p95. Enforced via opt-in perf-test lane.

**Adapter resilience (Part IV):** Tenacity-based retry (4 attempts, exponential backoff with jitter), no circuit breaker (single-agent volume is 100× below Polymarket rate limits), distinct error codes per failure class (never wrap 429 as generic external error). Snapshots never cached; metadata cached by market-state TTL; resolutions cached forever once final.

**Deferred to post-v0.0.2:** Kalshi adapter, Manifold adapter, CRPS / interval scoring (depends on Kalshi).

---

## Part I — Strategic Direction

### 1. Scope: Prediction-Market-Only

**Override:** VISION.md non-goals bullet on venue-specific product semantics — currently reading "Venue-specific product semantics — fields like Polymarket condition IDs, options Greeks, or futures contract specs live in `metadata_json`, not in the core schema" — is rewritten. The pivot inverts the bullet's premise: the core schema now carries first-class PM concepts (`markets` table, binary-only forecasts, market-state enum), and `metadata_json` continues to carry venue-specific addenda. [AUDIT 2026-05-22: original draft's "non-goal #5" wording was paraphrased; this is the verbatim bullet from `docs/VISION.md` (last bullet under the Non-goals section).]

**New positioning statement:**
> Trade Trace is a local-only calibration journal and memory substrate for LLM prediction-market trading agents. It grades binary forecasts against on-venue resolution, ingests live market prices as an opt-in calibration baseline, and gives the agent a typed memory graph for reflections and playbook rules. It is not a trader, not a market-data fetcher by default, not a dashboard.

**Why it's not arbitrary narrowing:**
- Binary scoring is already MVP-locked in code and docs.
- MVP dogfood tests exclusively use prediction markets.
- `venue.kind` and `asset_class` enum values for equity/option/future are schema slots that are *never used* in tests or examples.
- The deletion surface for non-PM concepts is small (~5% of code by LOC); the enrichment upside is large.

**New non-goal:** "Not a continuous-asset trading journal (equities, options, futures, FX, crypto spot/perp). For those use cases, use a domain-specific journal like Tradervue or Edgewonk."

### 2. Audience

**Primary:** LLM trading agents operating on prediction markets.

**Secondary:** Forecast-research workflows (Manifold-style calibration projects). Served by `decision.type='watch'` without execution metadata.

**Not the audience:** Human discretionary traders journaling by hand; quants needing portfolio-level risk analytics; options/derivatives traders.

### 3. Network Policy: Opt-in Polymarket Adapter

**Principle preserved:** No outbound network by default. Local-first promise intact.

**New affordance:** Users can explicitly enable the Polymarket adapter via config. When enabled:
- `market.bind(external_id="0x...")` fetches market metadata from Gamma API.
- `snapshot.fetch(market_id, at=now)` captures live implied probability.
- `outcome.fetch(market_id)` ingests resolution from on-chain (Polygon).

**Configuration:**
- `network.polymarket.enabled = false` (default)
- User must explicitly enable AND supply `network.polymarket.polygon_rpc_url` to enable resolution ingestion.
- Public Gamma API for metadata (no auth, cached).
- Trade Trace ships *no* default RPC endpoint or API key.

### 4. Scoring: Binary-Only v1

**Delete (revised scope after AUDIT 2026-05-22 — `brier_multiclass` and `squared_error_scalar` are dispatch-string labels in `_compute_score_*`, not standalone functions; the real deletion surface is below):**
- `_validate_categorical_forecast` in `src/trade_trace/tools/ledger.py:545-566` (~22 LOC actual).
- `_validate_scalar_forecast` in `src/trade_trace/tools/ledger.py:568-580` (~13 LOC actual).
- Scoring dispatch branches that assign `metric = "brier_multiclass"` / `"squared_error_scalar"` in `_compute_score_*` (around `ledger.py:1169-1175`); fall back to single-path binary Brier + log-score.
- 3 tests in `tests/integration/test_scoring_p1.py`:
  - `test_categorical_brier_multiclass_scores_on_outcome`
  - `test_scalar_squared_error_scores_on_numeric_outcome_value`
  - `test_invalid_categorical_and_scalar_shapes_rejected`
- Rewrite `docs/architecture/scoring.md` §§ around lines 80, 117, 140, 515 to remove these as named metrics.
- `forecasts.kind` enum reduced to single value `'binary'` (DB CHECK constraint).

**Total deletion:** ~35 LOC validators + ~10 LOC dispatch + doc updates + 3 tests. (Original "~70 LOC" estimate overstated.)

**Defer to post-v0.0.2 (lands with Kalshi adapter):**
- CRPS (Continuous Ranked Probability Score) for scalar distributions
- Pinball loss for quantile forecasts
- Interval score for spread markets

### 5. Renaming: Keep "Trade Trace"

Keep the name. Reposition via tagline, README, VISION rewrites. New tagline: *"Local calibration journal for LLM prediction-market trading agents."*

### 6. Versioning: Hard Break 0.0.1rc3 → 0.0.2

No migration shims. Greenfield permits clean breaks.

---

## Part II — Tool Catalog Consolidation

**Source:** Three-agent audit (2026-05-22). Agents 1 and 2 independently audited each tool; Agent 3 audited report consolidations. Recommendations applied below.

> **[AUDIT 2026-05-22]** Follow-up enumeration of `registry.register(...)` calls in `src/trade_trace/tools/*.py` returned **84 registered tools**, not ~81. The "Net Tool Count" table's "Old" column was an estimate; the per-family rows do not all match a clean enumeration (most affected: Journal claimed 10 / module count 6; Markets/Ledger claimed 11 / module count 8; Memory claimed 5 / module count 4; Import/export claimed 5 / module count 3). The discrepancy is largely categorization — the table groups tools by *concept*, modules group by *file*. Before locking the consolidation scope, reconcile against `tests/security/test_mvp_boundary_audit.py` (the source-of-truth catalog pin) and replace the "Old" column with the boundary-audit-derived counts. The headline target now ~45 (was ~44; +1 from `snapshot.fetch_series` formalization); the reduction percentage is ~46%.

> **[AUDIT 2026-05-23 / trade-trace-sx4n]** The "84" above is itself stale. `default_registry().names()` now returns **89** tools. The audit's literal `registry.register(` grep missed (a) `report.policy_candidates` and `replay.evaluate_output` that shipped after the audit window, and (b) four alias-namespace surfaces (`agent.bootstrap`, `agent.next_actions`, `resolve.record`, `playbook.adherence`) that share a handler with the canonical surface. The authoritative old→new disposition of every shipped tool — KEEP / RENAME / FOLD / KILL / NEW — lives in **`docs/architecture/v002-pm-pivot-catalog.md`**, along with the `meta.legacy_name`, `UNSUPPORTED_CAPABILITY` redirect, admin-only-filter, and boundary-audit-pin contracts the catalog/transport gate will enforce. This document's per-family table below is a useful executive summary but is not the implementation contract; downstream beads cite the catalog doc, not this table.

### KEEP (sharpened)

**Journal (5):**
- `journal.init`, `journal.status` (add adapter state), `journal.schema`, `journal.config_set` (add `network.polymarket.*` keys), `journal.fixture_seed` (Polymarket fixtures).

**Backup/Restore (3, admin-only flag):**
- `journal.backup` (SHA-256 manifest **retained** — agent 2 recommended dropping, rejected: anti-discipline for a journaling product), `journal.restore`, `journal.repair`.

**Memory (4):**
- `memory.retain`, `memory.reflect`, `memory.link`, `memory.recall` (with new ONNX embeddings).

**Other (4):**
- `tool.schema`, `export.drain`, `review.bundle`, `replay.case_bundle`.

### RENAME (PM semantic clarity)

- `outcome.add` → `resolution.add` (rename tool only; underlying `outcomes` table stays — too much migration churn otherwise; `meta.legacy_name` field on the tool surface for transition).
- `decision.record_adherence` → `playbook.record_adherence` (namespace consistency).

### FOLD (consolidated into other tools)

- `venue.add` + `instrument.add` → folded into new `market.bind`.
- `thesis.add` → folded into `forecast.add` as `rationale_body` field. **`theses` table dropped entirely.**
- `forecast.supersede` → folded into `forecast.add` with `supersedes_forecast_id` field.
- `source.add` + `source.attach_to_thesis` + `source.attach_to_decision` + `source.attach_to_forecast` + `source.attach_to_memory_node` → all dropped. **`sources` table dropped entirely.** Sources stored as `metadata_json.sources` array on forecast/decision/memory_node. [AUDIT 2026-05-22: `source.attach_to_memory_node` was missing from the original draft; it's registered via the same factory as the other three at `tools/ledger.py:1470-1472`.]
- `strategy.create` + `strategy.list` + `strategy.show` + `strategy.update` → single `strategy.upsert` (list via `report.strategy_health`).
- `playbook.create` + `playbook.list` + `playbook.show` + `playbook.list_versions` → single `playbook.upsert`.
- `import.validate` → folded into `import.commit` with `_dry_run` mode.
- `journal.rescan_scoring` → folded into `journal.rebuild_projections`.

### KILL

**Aliases and thin wrappers:**
- `agent.bootstrap` (use `report.bootstrap`)
- `agent.next_actions` (use `report.work_queue`)
- `playbook.adherence` (use `report.playbook_adherence`)
- `resolve.record` (alias of `resolution.add`)
- `resolve.pending` (use `report.work_queue`)
- `idea.capture` (use `memory.retain`)

**Out-of-scope under PM-only:**
- `market.scan.dry_run` + `market.scan.promote` (replaced by `market.bind` + adapter)
- `journal.bundle.plan` + `journal.bundle.status` (replaced by adapter)
- `reflection.prompt_for_outcome` (prompt assembly is agent's job)
- `import.csv_fills` (JSONL-only via `import.commit`)
- `memory.reindex` (cosmetic; not needed without embeddings provider switches)
- `model.import`, `model.warm`, `keyring.revoke` (replaced by inline ONNX runtime; no provider switching)

**Admin-only (kept but flagged off the default catalog):**
- `signal.scan` (only emits one signal kind; gated as admin)
- `journal.rebuild_projections`, `journal.repair`

### NEW (PM-native)

**Adapter primitives:**
- `market.bind(external_id, source="polymarket")` — fetch/cache market metadata. Idempotent. Populates `markets.*_at` state-history columns on state change.
- `market.refresh(market_id)` — re-fetch (state changes). Adapter-only. Populates `markets.*_at` state-history columns on state change.
- `snapshot.fetch(market_id, at=now)` — capture live implied probability. Adapter-only; falls back to `snapshot.add` (manual) when disabled.
- `snapshot.fetch_series(market_id, from, to)` — capture a time series of implied probabilities for trajectory baselines. Adapter-only; falls back to manual `snapshot.add` loop when disabled. [AUDIT 2026-05-22: tool was referenced in Part V but missing from this canonical NEW list.]
- `outcome.fetch(market_id)` — ingest on-chain resolution. Adapter-only.

**Forecast anchoring:**
- `forecast.anchor_to_snapshot(forecast_id, snapshot_id)` — post-hoc anchor (idempotent; corrections via supersedes edge).

### Report Consolidation (25 → 13)

**Agent 3 corrected the original 8-report target.** Field-preservation arguments required keeping `risk` and `lifecycle` separate. Four new PM-native reports added.

**Kept / consolidated:**

| Report | Consolidates | Notes |
|---|---|---|
| `report.calibration` | `calibration` + `calibration_integrity` (integrity as sections) | Brier/log-score/ECE/sharpness + 6 hygiene diagnostics |
| `report.calibration_anchored` | NEW | Agent vs market implied probability baseline |
| `report.forecast_diagnostics` | unchanged | Binary signal detection |
| `report.book` | `pnl` + `open_positions` + `current_exposure` + `exposure_anomalies` + `watchlist` | Position book + open-trade visibility. **Risk excluded** (different shape). |
| `report.risk` | unchanged | R-distribution, win/loss histogram, payoff ratios. **Kept separate** from book. |
| `report.audit` | `audit_readiness` + `source_quality` + `playbook_adherence` | Provenance hygiene + adherence aggregates. **Lifecycle excluded** (state machine, different shape). |
| `report.lifecycle` | unchanged | Decision state machine (watch → review → enter, etc.). **Kept separate** from audit. |
| `report.recall` | `recall_receipts` + `memory_usefulness` (diagnostics nested per item) | Memory diagnostics with negative controls |
| `report.work_queue` | unchanged + `decision_velocity` fold | Process obligations + velocity bucketing |
| `report.bootstrap` | composer | Composes the above |
| `report.coach` | narrowed (forbidden-phrase gate retained) | Aggregates audit + forecast signals |
| `report.strategy_health` | `strategy_performance` folded in | Process review |
| `report.compare` | unchanged | Cross-sectional + time-bucketed |

**NEW PM-native reports (the headline value the pivot unlocks):**

| Report | Purpose |
|---|---|
| `report.market_lifecycle` | How long each market stayed in `{open → closed_for_trading → resolving → resolved}`; did the agent re-engage after going stale; distinct from decision lifecycle. |
| `report.resolution_quality` | Ambiguous/voided/disputed/cancelled counts vs decisions touched; did the agent flag uncertainty pre-resolution. |
| `report.amm_slippage` | For AMM markets: agent execution price vs market mid at the time; adverse-fill detection in basis points per position. |
| `report.time_decay_sharpening` | For each market: did agent's forecast probability converge to resolution truth as time passed; slope of agent belief toward truth; late-update detection. |

**Killed reports (functionality preserved in consolidations):**
`mistakes`, `strengths`, `opportunity`, `unscored_forecasts`, `decision_velocity` (folded into `work_queue`), `pnl`, `watchlist`, `open_positions`, `current_exposure`, `exposure_anomalies`, `audit_readiness`, `source_quality`, `playbook_adherence`, `strategy_performance`, `memory_usefulness`, `calibration_integrity`, `recall_receipts`, `filter_schema` (introspect via `tool.schema`).

### Net Tool Count

| Family | Old | New | Δ |
|---|---|---|---|
| Journal | 10 | 5 | -5 |
| Markets/Ledger | 11 | 5 (1 new shape) | -6 |
| Adapter primitives | 0 | 6 | +6 |
| Memory | 5 | 4 | -1 |
| Strategy | 4 | 1 | -3 |
| Playbook | 7 | 3 | -4 |
| Ideas | 1 | 0 | -1 |
| Market scan | 2 | 0 | -2 |
| Reflection | 1 | 0 | -1 |
| Import/export | 5 | 2 | -3 |
| Admin | 8 | 2 | -6 |
| Signals | 1 | 1 (admin) | — |
| Reports | 27 | 13 (incl. 4 PM-native) | -14 |
| Review/replay | 3 | 2 | -1 |
| Tools | 1 | 1 | — |
| **Total** | **~84** | **~45** | **-39 (~46%)** |

[AUDIT 2026-05-22: total updated from ~81 to ~84 to match the registered-tool enumeration. NEW total grew from 44 → 45 with the addition of `snapshot.fetch_series` to the adapter primitives. Per-family "Old" cells above are not yet reconciled against the boundary audit — see the audit callout at the top of Part II.]

---

## Part III — Schema Migration

### Migration numbering [AUDIT 2026-05-22]

Last shipped migration is `m011_agent_continuity_provenance.py`. New migrations in this section are **m012–m015** (original draft used m014–m017, off by two). Renumbered throughout this Part and in Part XII.

### Tables dropped

- **`theses`** — fully folded into `forecasts.rationale_body` plus bi-temporal columns (`invalidated_at`, `invalidated_by`, `updated_at`, `updated_by`). The `decision.type` values `invalidate_thesis` and `update_thesis` now operate on the forecast row directly.
- **`sources`** — fully folded into `metadata_json.sources` array on forecast/decision/memory_node. Schema for the array: `[{kind, title, url, stance, captured_at, hash}]`. Source-quality report queries the JSON arrays via `json_each()`.
- **`source_attachments`** — **does not exist in the codebase today**; remove from any drop-statement list. [AUDIT 2026-05-22: original draft listed this table; grep of all `src/trade_trace/storage/migrations/*.py` confirms it was never created. Source attachments are tracked via **edge rows** in the `edges` table, emitted by the `source.attach_to_*` handler factory at `tools/ledger.py:1487`.]
- **`forecast_outcomes`** — collapsed into a flat `forecasts.probability REAL` column (the YES probability; NO = 1 − YES). [AUDIT 2026-05-22 / decision C1=collapse: matches the plan's mental model ("forecasts.probability") and simplifies the ~6 reports that currently read from `forecast_outcomes`. Greenfield permits this.]
- **`venues`** — folded into `markets.source` enum and `markets.venue_metadata_json`.
- **`instruments`** — replaced by `markets`.

### Source-edge migration handling [AUDIT 2026-05-22 / decision C4]

Existing `source.attach_to_*` edge rows (emitted as `edge_type='about'` or similar by the attach-handler factory; verify exact edge type before writing m015) reference the `sources` table that is being dropped. **Greenfield posture: drop the source-attach edges without back-fill.** No users exist; preserving these edges would require resolving stale source_ids against a back-fill, which is more work than it's worth. The new `metadata_json.sources` arrays start empty on existing rows and are populated by future writes.

### Enum changes

| Enum | Old (count) | New (count) | Dropped |
|---|---|---|---|
| `venue.kind` | 6 | n/a (table gone) | — |
| `asset_class` | 7+ | n/a (column gone) | all non-PM |
| `forecast.kind` | 3 | 1 (`binary`) | `categorical`, `scalar` |
| `decision.side` | **6** | 3 (`yes`, `no`, `flat_neutral`) | `long`, `short`, `pairs_long_short` |
| `decision.type` | 13 | 8 (`watch`, `skip`, `actual_enter`, `actual_exit`, `invalidate_thesis`, `update_thesis`, `resolved`, `review`) | `paper_enter`, `paper_exit`, `add`, `reduce`, `hold` |
| `outcome.status` | 6 | 6 unchanged | — |
| `memory_node.node_type` | 3 | 3 unchanged | — |
| `edge.edge_type` | 7 | 7 unchanged | — |

**Why drop the 5 decision types:** Per Agent 2 audit. Polymarket positions are binary share holdings; no PM workflow needs `add` (increase size), `reduce` (partial exit), `hold` (already implied between actions), `paper_enter`/`paper_exit` (paper trading on prediction markets is the same as forecasting without an enter — `watch` covers it). Killing these simplifies `decision_matrix.py` by ~80 LOC.

**[AUDIT 2026-05-22 / decision C2] `position_records.side` CHECK constraint:** The `position_records` table CHECK constraint already differs from `decisions` and `position_events` — it has 5 values (no `flat_neutral`) at `m003_m1_ledger.py:369-370`. Under the migration, drop `long`/`short`/`pairs_long_short` from all three side columns (decisions, position_events, position_records). **Do not add `flat_neutral` to position_records** — a "flat" position is represented by the absence of an open position record (or by an exit row), not by a `side='flat_neutral'` record. So the post-migration sides are: decisions/position_events = `{yes, no, flat_neutral}` (3 values); position_records = `{yes, no}` (2 values).

### Dropped columns

- `instruments.contract_multiplier` (futures/options legacy).
- `instruments.expiration_or_resolution_at` → `markets.close_at` / `markets.resolution_at`.
- `position_events.event_type` values `'expire'`, `'assigned'`.

### New `markets` table (m012)

```sql
CREATE TABLE markets (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL CHECK (source IN ('polymarket', 'kalshi', 'manifold', 'predictit', 'manual')),
  external_id TEXT NOT NULL,
  title TEXT NOT NULL,
  resolution_rule_text TEXT NOT NULL,
  close_at TEXT,
  resolution_at TEXT,
  -- State-history columns (audit 2026-05-22, gap #1 for report.market_lifecycle):
  opened_at TEXT,                  -- first observed in 'open'
  closed_for_trading_at TEXT,      -- first observed in 'closed_for_trading'
  resolving_at TEXT,               -- first observed in 'resolving'
  resolved_at TEXT,                -- first observed in 'resolved'
  voided_at TEXT,                  -- first observed in 'voided'
  ambiguous_at TEXT,               -- first observed in 'ambiguous'
  mechanism TEXT NOT NULL CHECK (mechanism IN ('clob', 'amm', 'scalar', 'hybrid')),
  state TEXT NOT NULL CHECK (state IN ('open', 'closed_for_trading', 'resolving', 'resolved', 'voided', 'ambiguous')),
  resolution_source TEXT CHECK (resolution_source IN ('market_contract', 'oracle_feed', 'manual_review', 'arbitration')),
  ambiguity_kind TEXT CHECK (ambiguity_kind IN ('market_rules_unclear', 'oracle_dispute', 'event_happened_but_label_ambiguous', 'event_null_and_void')),
  venue_metadata_json TEXT NOT NULL DEFAULT '{}',
  bound_at TEXT NOT NULL,
  bound_via TEXT NOT NULL CHECK (bound_via IN ('adapter', 'manual')),
  actor_id TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE (source, external_id)
);
CREATE INDEX idx_markets_source_external ON markets(source, external_id);
CREATE INDEX idx_markets_state ON markets(state);
CREATE INDEX idx_markets_close_at ON markets(close_at);
```

**[AUDIT 2026-05-22 — PM-native-report derivability check] State-history columns added.** The 4 PM-native reports were traced against the proposed schema. Findings:

- `report.market_lifecycle` ("how long each market stayed in `{open → closed_for_trading → resolving → resolved}`") **requires per-state timestamps**, not just the current `state` value. Each `market.refresh` (and `market.bind`) populates the relevant `*_at` column the **first** time it observes that state (idempotent on state-change-edge, not on every refresh). Lifecycle durations derive from `close_at - opened_at`, `resolving_at - close_at`, etc. Without these columns the report cannot be produced.
- `report.resolution_quality` "did the agent flag uncertainty pre-resolution" leans on the same columns: a forecast/decision is "pre-resolution" if `created_at < markets.resolving_at`.
- `report.amm_slippage` derivability check: `decisions.snapshot_id` is an **existing FK** today (`m003_m1_ledger.py:200`) — no new `decision_snapshot_anchor` table needed. The new `forecast_snapshot_anchor` table (m013) is for forecast-level anchoring; for slippage the existing decision→snapshot FK is sufficient. Slippage formula: `(decisions.price - snapshots.mid) / snapshots.mid * 10000` (basis points), gated by `markets.mechanism = 'amm'`.
- `report.time_decay_sharpening` derivability check: works with the existing `forecasts.created_at` + `forecasts.probability` (post-C1 collapse) + supersedes-edge chain + `outcomes` for truth. No new schema needed.

### New `forecast_snapshot_anchor` table (m013)

```sql
CREATE TABLE forecast_snapshot_anchor (
  id TEXT PRIMARY KEY,
  forecast_id TEXT NOT NULL UNIQUE REFERENCES forecasts(id),
  snapshot_id TEXT NOT NULL REFERENCES snapshots(id),
  market_implied_probability REAL,
  agent_id TEXT,
  model_id TEXT,
  environment TEXT,
  run_id TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  actor_id TEXT NOT NULL
);
CREATE INDEX idx_fsa_forecast ON forecast_snapshot_anchor(forecast_id);
CREATE INDEX idx_fsa_snapshot ON forecast_snapshot_anchor(snapshot_id);
```

### Forecast table changes (m014)

Drop `theses` table; add columns to `forecasts`:
- `rationale_body TEXT` (was `theses.body`)
- `falsification_criteria TEXT` (was `theses.falsification_criteria`)
- `invalidated_at TEXT NULL`, `invalidated_by TEXT NULL` (bi-temporal)
- `updated_rationale_at TEXT NULL`, `updated_rationale_by TEXT NULL`
- `probability REAL CHECK (probability >= 0.0 AND probability <= 1.0)` — the YES probability for binary forecasts (collapses `forecast_outcomes` per decision C1).

Drop FK `forecast.thesis_id`; remove from queries. Drop the `forecast_outcomes` table (back-fill the new `probability` column from existing `forecast_outcomes` rows where `outcome_label='YES'` if any rows must be preserved; greenfield permits a clean drop). [AUDIT 2026-05-22.]

**[AUDIT 2026-05-22 / decision C3] Rename `memory_nodes.meta_json` → `memory_nodes.metadata_json` in this same migration** so all top-level domain tables use the same column name for venue/source metadata. Update all readers/writers of `meta_json` to `metadata_json` (grep `meta_json` across `src/trade_trace/` to find call sites). Greenfield + small rename surface justifies eliminating the naming asymmetry now rather than living with it.

### Source-array migration (m015)

Drop the `sources` table. (No `source_attachments` table to drop — see Tables-dropped section above.) Drop the source-attach edge rows per the C4 decision. Forecasts/decisions/memory_node gain `metadata_json.sources` arrays (memory_nodes via the meta_json→metadata_json rename in m014).

### Renamed columns

- `decision.instrument_id` → `decision.market_id`
- `snapshot.instrument_id` → `snapshot.market_id`
- `outcome.instrument_id` → `outcome.market_id` (table stays `outcomes`; tool renamed `resolution.add`)
- `position_events.instrument_id` → `position_events.market_id`

---

## Part IV — Polymarket Adapter

### Location

```
src/trade_trace/venues/
    __init__.py
    _interface.py          # Abstract pm_venue protocol
    polymarket/
        __init__.py
        client.py          # httpx-based HTTP + Polygon RPC clients
        markets.py         # Gamma API for market metadata
        snapshots.py       # CLOB book + AMM prices → implied probability
        resolutions.py     # On-chain resolution ingestion
        cache.py           # TTL'd local cache
        config.py          # Config keys, validation
        errors.py          # AdapterError, AdapterTimeout, AdapterRateLimited
        tests/
            test_market_fetch.py
            test_snapshot_fetch.py
            test_resolution_fetch.py
            test_offline_fallback.py
```

### HTTP client choice: httpx

- Lazy import inside adapter modules so `network.polymarket.enabled=false` users never load it.
- TLS verification on by default (cannot be disabled via config — security invariant).
- Strict timeout (default 30s); explicit retry-with-backoff (max 3 retries, jittered exponential — see Resilience policy below).
- User-Agent header: `trade-trace/0.0.2 (polymarket-adapter)`.
- Response logging: structured event row with status code + latency only; **never log response body** (privacy + payload size).

### Resilience policy

**Rate-limit context (from Polymarket docs, 2026-05):** Gamma `/markets` endpoint allows 300 req/10s window; CLOB `/book` allows 1500 req/10s. A single-agent journal is two orders of magnitude below these limits. 429 responses are almost always transient (Cloudflare-side noise), not real per-key quota breaches.

**Retry budget** (applies to all outbound HTTP and JSON-RPC):
- Library: `tenacity` (new base dep, pinned `>=8.2` — not gated behind the `[embeddings]` extra). [AUDIT 2026-05-22: confirmed absent from `pyproject.toml` today.]
- Strategy: `wait_random_exponential(multiplier=2, max=30)` + `stop_after_attempt(4)` (1 initial + 3 retries).
- Retry on: `httpx.TransportError`, `httpx.ReadTimeout`, HTTP 408/425/429, HTTP 5xx, JSON-RPC error codes -32005 (rate-limited) and -32603 (internal).
- Honor `Retry-After` header when present: actual wait = `max(Retry-After, computed_backoff)`.
- Do NOT retry on: 4xx other than 408/425/429 (these are permanent — bad condition_id, malformed request).

**No circuit breaker.** Trade Trace runs as a single local agent; per-call retry is sufficient. Cascading-failure protection is not a goal because there is no fan-out and no shared downstream we owe an SLA to. Re-evaluate only if a multi-tenant deployment surface ever lands.

**Cache policy by data type:**
- **Market metadata:** TTLs per state (24h `resolved` / 1h `open` / 5min `resolving` / 0 `ambiguous`|`voided`).
- **Snapshots: never cached.** Every `snapshot.fetch` hits the wire (or errors). Stale prices are actively misleading; the agent is calling `snapshot.fetch` *because* it wants a fresh number.
- **Resolutions:** cached forever once `status='resolved_final'` (on-chain finality is permanent).
- **Stale-while-revalidate: NOT used.** If the wire call fails and the cache is fresh, serve cache silently. If cache is stale AND the wire fails, return `ADAPTER_TIMEOUT` / `EXTERNAL_API_ERROR` — never serve known-stale data without telling the agent.

**`_force_refresh` flag:** exposed only on `market.refresh`. `snapshot.fetch` is always live (no flag needed). `outcome.fetch` is always live for non-final states; final states are cache-only (finality is permanent, no refresh path).

**Error envelope contracts (agent-visible):**

| Upstream condition | Envelope code | `details` shape | Documented agent recovery |
|---|---|---|---|
| 429 after retries | `ADAPTER_RATE_LIMITED` | `{retry_after_seconds, endpoint, attempts}` | Wait `retry_after_seconds`; or manual `snapshot.add` / `resolution.add` |
| Timeout after retries | `ADAPTER_TIMEOUT` | `{timeout_seconds, endpoint, attempts}` | Retry later; or manual fallback |
| 5xx after retries | `EXTERNAL_API_ERROR` | `{status_code, endpoint, attempts}` | Retry later (likely transient) |
| Response schema mismatch | `ADAPTER_PROTOCOL_ERROR` | `{endpoint, validation_error}` | NOT retryable; file a bead — upstream contract drift |
| Adapter off, network needed | `ADAPTER_DISABLED` | `{config_key: "network.polymarket.enabled"}` | Enable adapter or use manual primitive |
| Polygon RPC URL unset | `CONFIG_REQUIRED` | `{config_key: "network.polymarket.polygon_rpc_url"}` | Set config; or use manual `resolution.add` |

**Codes stay distinct.** The agent never sees a generic `EXTERNAL_API_ERROR` for a 429 — code-level distinction is load-bearing for the recovery branch (the agent chooses between "wait + retry" vs "fall back to manual"). The adapter never auto-falls-back to manual — that decision belongs to the agent.

**Secret scrubbing on error details:** `details.endpoint` is host + path only (e.g., `gamma-api.polymarket.com/markets`). Query strings, request bodies, and response bodies are NEVER included (enforced by `test_adapter_url_scrubbing.py`).

**Polygon RPC ops note:** Public `polygon-rpc.com` is documented as fragile (rate-limits aggressively, no SLA). README recommends user-supplied dedicated RPC (Alchemy ~25-50 rps free tier, Infura/QuickNode ~1.15 rps daily-capped). Trade Trace ships no default RPC.

### Capabilities

1. **`market.bind(external_id, source="polymarket")`**
   - Adapter enabled: HTTP GET to Gamma API; returns metadata; upserts `markets` row with `bound_via='adapter'`.
   - Adapter disabled: requires caller-supplied inline metadata; `bound_via='manual'`.
   - Cache TTL: 24h for `resolved`, 1h for `open`, 5min for `resolving`, 0 for `ambiguous`/`voided` (always re-fetch).
2. **`snapshot.fetch(market_id, at?)`**
   - Adapter enabled: queries CLOB / AMM endpoint; computes implied probability; writes snapshot row.
   - `at` parameter: only `at=now` in v0.0.2. Historical snapshot fetching deferred.
3. **`outcome.fetch(market_id)`**
   - Adapter enabled with `polygon_rpc_url`: queries Polygon contract for resolution.
   - Records on-chain transaction hash in `metadata_json`.
   - Idempotent: safe replay.

### Configuration keys

```
network.polymarket.enabled = false                              # default
network.polymarket.gamma_base_url = https://gamma-api.polymarket.com
network.polymarket.polygon_rpc_url = <user-supplied>
network.polymarket.cache_ttl_open_seconds = 3600
network.polymarket.cache_ttl_resolved_seconds = 86400
network.polymarket.cache_ttl_resolving_seconds = 300
network.polymarket.timeout_seconds = 30
network.polymarket.retry_max = 3
network.polymarket.user_agent = trade-trace/0.0.2
```

### Actor ID for adapter operations

When the adapter writes events (snapshot row, market metadata refresh, outcome ingestion), the `actor_id` is `system:polymarket-adapter`. Audit queries can distinguish agent-authored writes from adapter-authored ones.

### Tests

- `test_no_network_default.py`: with adapter disabled, all adapter primitives reject calls that would touch the network.
- `test_adapter_polymarket_offline.py`: mock httpx; verify retry/backoff and cache behavior.
- `test_adapter_polymarket_no_rpc.py`: `outcome.fetch` returns explicit `CONFIG_REQUIRED` when `polygon_rpc_url` is unset.
- `test_adapter_secret_scrubbing.py`: error messages and event-log entries never include URL parameters or response bodies.
- Integration: golden Polymarket API responses in `tests/integration/fixtures/polymarket/`.

---

## Part V — Anchored-Baseline Calibration

### Implementation

**Schema:** `forecast_snapshot_anchor` (Part III).

**`forecast.add` enhancement:**
- Add optional `snapshot_id` arg.
- Add optional `_anchor_to_latest_snapshot=true` flag (requires adapter enabled OR a recent manual snapshot exists for the market).
- Server inserts `forecast_snapshot_anchor` row with `market_implied_probability` copied from the snapshot.

**New tool: `forecast.anchor_to_snapshot`** — post-hoc anchoring with idempotency; corrections via supersedes edge.

**Refactor `_compute_metrics()`** to accept optional `baseline_probabilities`; when provided, baseline metrics use market implied probabilities instead of outcome prevalence.

**New report `report.calibration_anchored`:**
- `baseline` = mean market implied probability across anchored forecasts.
- `brier_baseline` = mean Brier of the market itself against outcomes.
- `skill` = `1 - (brier_agent / brier_market)`. Positive = agent beat the market.
- `unanchored_forecast_count` caveat field.

### Trajectory + Terminal baselines (also v0.0.2)

Originally proposed for v0.0.3; pulled into single-release scope.

- **Trajectory:** time series of market implied probability over the life of the position; report shows convergence/divergence. New tool: `snapshot.fetch_series(market_id, from, to)` (adapter-only, manual fallback). New report: implicit in `report.time_decay_sharpening`.
- **Terminal:** market closing price vs resolution. New report: `report.calibration_terminal` (similar shape to `calibration_anchored` but baseline = `market_prob_at_close`).

---

## Part VI — Predecessor Remediation, Re-Prioritized for v0.0.2

The original next-steps.md identified seven shortcomings. Under single-release scope, all are absorbed into v0.0.2 except items that depend on future venue adapters.

### Absorbed into v0.0.2

#### P0.1 — Real Vector Embeddings (ONNX BGE-small)

**Was:** Predecessor #1 P0 (highest-value investment). The current embeddings path is a deterministic hash stub.

**Plan:** Predecessor Option A (ONNX local). Add `onnxruntime>=1.17` and `tokenizers>=0.19` to `[embeddings]` extra. Pre-export ONNX model (~25MB quantized INT8 BGE-small) + tokenizer.json with SHA-256 lock. Implement `_load_local_onnx_session`, `_tokenize_and_encode`, `_query_embedding_local`. Replace `_model_warm_stub` with eager session loading.

**Decision: drop `sqlite-vec` from dependencies.** Currently loaded but never used; the Python brute-force cosine loop is fast enough for v0.0.2 scale. Re-evaluate if recall latency becomes a problem.

**Cross-platform support (evidence-backed):**
- **onnxruntime 1.26.0** ships wheels for Py 3.11/3.12/3.13 on: macOS arm64 (Apple Silicon), Linux x86_64 + aarch64 (manylinux), Windows AMD64/ARM64. **Gap: no macOS x86_64 (Intel Mac) wheel.**
- **tokenizers 0.23.1** wheel coverage is universal across the above plus musllinux. Sdist requires Rust toolchain — install fails on truly exotic arches.
- BM25 + temporal decay remains the **unconditional default** (base install, not in `[embeddings]` extra). An `[embeddings]` install failure is recoverable: agent gets degraded recall, not a broken journal.
- README install section adds a note for Intel Mac users: "install onnxruntime 1.19 (last x86_64 macOS release) manually, or use BM25 recall."
- **CI matrix expansion:** current CI is ubuntu-latest only. Add a weekly (non-blocking) job that installs `[embeddings]` and runs a smoke import on macOS-arm64 + Windows-latest. This is the only way to catch wheel-availability regressions before users do.

**Effort:** ~250–350 LOC + 2–3 integration tests + ~30 lines of CI YAML.

#### P0.2 — Module Split (`ledger.py`, `reports.py`)

**Was:** Predecessor P2.

**Why P0 now:** PM rewrite touches both monoliths heavily. Splitting first means each PM-related change is small and testable.

**Plan:** Predecessor Phase A + B. Plus PM-specific renames: `ledger/instrument.py` → `markets/bind.py`; `ledger/venue.py` killed; `ledger/thesis.py` deleted (folded into `forecast.py`); `ledger/source.py` deleted (folded into `metadata_json`).

**Effort:** ~4,800 lines moved + ~150 new lines for the markets refactor. [AUDIT 2026-05-22: `ledger.py` is 2,303 LOC and `reports.py` is 2,475 LOC — combined ~4,778 LOC. Original "~2,400" estimate appeared to count one monolith only; both are split under P0.2.]

#### P0.3 — Idempotency Key Auto-Derivation

**New.** Server accepts `idempotency_key` as optional on writes. When omitted, server computes `hash(tool_name + canonical_json(structural_fields))` using the existing `semantic_keys.py` registry. Agent can override by explicitly passing a key. Logs canonical hash in event row.

**Effort:** ~50 LOC + ~80 LOC of tests.

#### P0.4 — Test-Order Sensitivity Fixes

**Was:** Predecessor P2.

**Plan:** Reset `_AUTO_KEY_COUNTER[0] = 0` before each test; reset deterministic counters in fixture clocks; close subprocess handles in MCP test helper; fix ineffective monkeypatches.

**Effort:** ~30 LOC.

#### P1.1 — Report Filter Implementation

**Was:** Predecessor P1. Most reports reject all non-empty filters.

**Plan:** Predecessor doc Phases 1–5. Shared `_sql_filter_builders.py` helper. Implementations for `watchlist` → `book`, `unscored_forecasts` → `work_queue`, `mistakes` → `coach`, etc. Updated for consolidated report set.

**Effort:** ~250 LOC + ~12 tests.

#### P1.2 — ECE Equal-Mass Binning

**Was:** Predecessor P1.

**Plan:** Add `bin_policy` param to `_ece_and_bins`. Add `_ece_equal_mass()`. Boundary tests at 0.0/0.099/0.1/0.5/0.999/1.0. All-forecasts-in-one-bin scenario.

**Effort:** ~60 LOC + ~150 LOC tests.

#### P1.3 — N+1 Snapshot Mark Resolution

**Was:** Predecessor P3.

**Plan:** Rewrite `_latest_snapshot_mark_by_instrument` (now `_latest_snapshot_mark_by_market`) as a single CTE query with `ROW_NUMBER() OVER (PARTITION BY market_id ORDER BY captured_at DESC)`.

**Effort:** ~20 LOC.

#### P1.4 — Coach Report Test Coverage

**Was:** Predecessor P1. Coach has 16 tests with no seeded tag/source/integrity data.

**Plan:** Predecessor doc test plan. ~12–15 new integration tests seeding tags, sources, reflections, and playbook adherence. Verify all 5 `_process_quality_gaps` categories. Synthetic forbidden-phrase injection test.

**Effort:** ~350–500 LOC tests.

### Deferred to post-v0.0.2

- **Kalshi adapter:** Second-priority PM venue. Schema preparation already done (`markets.source` enum slot reserved). Adapter interface (`_interface.py`) designed for polymorphism from day one.
- **Manifold adapter:** Third-priority. Play-money use case for forecast-research workflows.
- **CRPS / interval scoring:** Depends on Kalshi (where spread markets are common).

### Dropped — no longer applicable under PM scope

- **Categorical / scalar forecast scoring:** Delete (~70 LOC + 3 tests).
- **Current-exposure cluster (7 beads):** Subsumed by `report.book`. Close all 7 as superseded.
- **Market scan tools and beads:** Replaced by adapter.
- **Multi-asset-class generic handling:** Code paths collapse to PM-only.
- **Thesis as separate entity:** Folded into forecast.
- **Source as separate entity:** Folded into `metadata_json`.
- **`opportunity` report test suite work:** Report is killed; folded into book + coach.

### Predecessor items not addressed here

- `ast-serialize` lockfile bloat (cosmetic, defer)
- Source-attacher table-name interpolation (no longer exists after source-entity drop)
- Public-history rewrite / OSS launch blockers (separate human-decision track)

---

## Part VII — Call-Burden Math

### Today (v0.0.1rc3, no adapter)

8 calls per cycle, 7 idempotency keys, ~25 required fields. (See predecessor doc Part VII.)

### v0.0.2 with adapter enabled

1. `report.bootstrap` (read)
2. `market.bind(external_id="0x...")` (write) — replaces venue.add + instrument.add; metadata auto-fetched; idempotent on `external_id`
3. `forecast.add(market_id, probability, rationale_body, _anchor_to_latest_snapshot=true)` (write) — replaces thesis.add + forecast.add + snapshot anchor; idempotency auto-derived
4. `decision.add(market_id, forecast_id, type='actual_enter', side='yes', quantity=100, price=0.42)` (write) — idempotency auto-derived
5. (`outcome.fetch` runs in adapter background OR `resolution.add` if manual)
6. `memory.reflect(target_kind='decision', target_id=..., body=...)` (write)

**5 calls. 0 hand-crafted idempotency keys. ~10 required fields.**

### v0.0.2 without adapter

Same shape but `market.bind` requires inline metadata, `snapshot.add` and `resolution.add` are manual. **7 calls.** Still 0 idempotency keys.

---

## Part VIII — Security & Privacy Review (NEW)

The opt-in network policy introduces outbound HTTP / RPC traffic. Required additions to SECURITY.md and the threat model:

### Network surface

- httpx is the only outbound HTTP client. Other clients (requests, aiohttp, urllib3) are prohibited in adapter code.
- TLS verification is on by default; **no config option exists to disable it.** Server certificate validation failures are hard errors.
- Outbound endpoints are constrained to allowlisted hosts per source: Polymarket Gamma API hostname + user-supplied Polygon RPC hostname. Other hostnames rejected.
- No redirects followed beyond 1 hop.
- Default timeout 30s; max 60s configurable.
- Max retries 3 with jittered exponential backoff.

### Data exfiltration posture

- Outbound payloads contain only the `external_id` (Polymarket condition_id) and `market_id` (UUID we generated). Nothing from the agent's journal — no forecast text, no reflection content, no decision rationale.
- Polymarket query parameters and the public RPC method/params are the entire request surface; document explicitly in SECURITY.md.

### Secret scrubbing

- Polygon RPC URL may include an API key in the path or query (common for Alchemy, Infura). Error messages and event-log entries scrub the URL before logging: only hostname + path-without-key.
- HTTP response bodies are never logged. Only status code + latency + URL-hash.

### Configuration validation

- `network.polymarket.gamma_base_url` validated against an HTTPS-only allowlist regex on `journal.config_set`.
- `network.polymarket.polygon_rpc_url` validated as HTTPS or HTTP-localhost only; warns on plain HTTP non-localhost.

### Local-first invariant tests

- `test_no_network_default.py` extended: with adapter disabled, no module imports httpx (lazy-import enforcement).
- `test_adapter_offline_baseline.py`: full agent loop runs with adapter disabled and no network access.
- `test_adapter_url_scrubbing.py`: synthetic API-key-in-URL is never present in event log, error envelopes, or backup manifests.

### Backup / restore under adapter

- Adapter-bound markets are part of the SHA-256 manifest. Restore preserves `bound_via='adapter'` flags. No special handling.
- Cached adapter responses are NOT included in backups (re-fetchable; not authoritative).

---

## Part IX — New Error Codes (NEW)

Additions to the `ErrorCode` enum in `src/trade_trace/contracts/errors.py`:

| Code | When emitted |
|---|---|
| `ADAPTER_DISABLED` | Tool requires the Polymarket adapter, but `network.polymarket.enabled=false`. |
| `ADAPTER_TIMEOUT` | Outbound request exceeded `timeout_seconds`. |
| `ADAPTER_RATE_LIMITED` | Venue returned 429 or equivalent rate-limit signal; retry budget exhausted. |
| `ADAPTER_PROTOCOL_ERROR` | Response shape did not match expected schema; data treated as unsafe. |
| `EXTERNAL_API_ERROR` | Venue returned a 5xx after retries; transient and retryable. |
| `RESOLUTION_NOT_AVAILABLE` | `outcome.fetch` called but market is not in `resolved` state. |
| `CONFIG_REQUIRED` | Tool needs a config key that is unset (e.g., `polygon_rpc_url` for `outcome.fetch`). |
| `MARKET_NOT_BOUND` | Tool references `market_id` that doesn't exist in the `markets` table. |
| `MARKET_STATE_CONFLICT` | Operation invalid for current market state (e.g., `forecast.add` on a `resolved` market). |

Each gets a stable error message format documented in `docs/architecture/contracts.md`.

---

## Part X — CLI Grammar Respec (NEW)

Tool renames and additions require CLI grammar updates. The `subject.verb` → `subject verb` mechanical mapping in `cli.py` still applies, but the verb list shrinks.

### New CLI surface

```
tt market bind <external-id> --source polymarket [--inline-metadata-json '...']
tt market refresh <market-id>
tt snapshot fetch <market-id> [--at now]
tt snapshot add <market-id> --implied-probability 0.42 [...]
tt forecast add --market-id <id> --probability 0.42 --rationale "..." [--anchor-to-latest-snapshot]
tt forecast anchor-to-snapshot --forecast-id <id> --snapshot-id <id>
tt decision add --market-id <id> --type actual-enter --side yes --quantity 100 --price 0.42
tt resolution add --market-id <id> --outcome-label yes --status resolved-final
tt resolution fetch --market-id <id>
tt strategy upsert --slug my-strategy --name "..." [--status active|archived]
tt playbook upsert --slug ... --name "..."
tt playbook propose-version --playbook-id <id> --provenance-reflection-node-id <id>
tt playbook record-adherence --decision-id <id> --playbook-version-id <id> --rule-node-id <id> --status followed
tt report calibration [--filter '...']
tt report calibration-anchored [--filter '...']
tt report book [--filter '...']
tt report risk [--filter '...']
tt report audit [--filter '...']
tt report lifecycle [--filter '...']
tt report recall [--filter '...']
tt report work-queue [--filter '...']
tt report bootstrap [--budget '...']
tt report coach [--filter '...']
tt report strategy-health
tt report compare --base calibration --group-by strategy_id
tt report market-lifecycle [--filter '...']
tt report resolution-quality [--filter '...']
tt report amm-slippage [--filter '...']
tt report time-decay-sharpening [--filter '...']
tt journal init|status|schema|config-set|fixture-seed|backup|restore|repair|rebuild-projections
tt memory retain|reflect|link|recall
tt tool schema [--tool <name>]
tt export drain
tt import commit <jsonl-file> [--dry-run]
tt review bundle --decision-id <id>
tt replay case-bundle --as-of <iso-time>
```

### Dropped CLI commands

`tt venue ...`, `tt instrument ...`, `tt thesis ...`, `tt source ...`, `tt market scan ...`, `tt resolve pending|record`, `tt agent bootstrap|next-actions`, `tt idea capture`, `tt reflection prompt-for-outcome`, `tt model import|warm`, `tt keyring revoke`, all the killed `tt report ...` commands.

### `--human` flag

Continues to work on all read commands. Emits prose hints to stderr while JSON stays on stdout.

---

## Part XI — Documentation Rewrite Scope (NEW)

| File | Action |
|---|---|
| `README.md` | Rewrite tagline, "What it includes," "What it is not," install instructions, MCP setup, CLI quickstart. New section on Polymarket adapter opt-in. |
| `docs/VISION.md` | Rewrite §non-goals (drop #5, add new non-goal), audience, what-it-is-not. New principle: "Opt-in venue clients preserve local-first by default." |
| `docs/PRD.md` | Rewrite §2.4 (network policy now opt-in), §2.5 (binary-only), §3 (asset classes → PM-only), §4 (tool catalog), §2.12 (strategy/playbook scope under PM). |
| `docs/AGENT_GUIDE.md` | Full rewrite. New §2.1 Trading loop (current loop, rewritten). **New §2.2 "Forecast-Only Loop"** for Manifold-style calibration researchers (market.bind → forecast.add → snapshot.fetch → resolution → memory.reflect; no decisions or positions). Examples use Polymarket condition IDs. |
| `docs/AI_AGENT_MCP_GETTING_STARTED.md` | Update tool list. Update example tool calls. New section on adapter configuration. |
| `docs/architecture/contracts.md` | Add new error codes (Part IX). Document idempotency auto-derivation algorithm. Document adapter framing in event log. |
| `docs/architecture/persistence.md` | Document new `markets` and `forecast_snapshot_anchor` tables. Document dropped `theses`, `sources`. Document the `metadata_json.sources` array shape. |
| `docs/architecture/memory-layer.md` | Document ONNX embeddings path (replaces stub). Document sqlite-vec deprecation. |
| `docs/architecture/reports.md` | Rewrite for 13-report catalog. Document the 4 new PM-native reports. |
| `docs/architecture/scoring.md` | Document binary-only constraint. Document anchored-baseline metrics. Mark CRPS/interval scoring as post-v0.0.2. |
| `docs/architecture/operability.md` | Document adapter ops: timeouts, retry budgets, cache TTLs, RPC requirements. |
| `docs/architecture/reporting-product.md` | Already a tombstone; update reference list to point at the new report catalog. |
| `docs/CLAUDE_CODE.md`, `docs/CLAUDE_DESKTOP.md`, `docs/IDE_MCP_SETUP.md` | Update tool examples. New adapter-config section. |
| `docs/RELEASE_CHECKLIST.md` | Update gate sequence (Part XIII below). |
| `SECURITY.md` | Add §Adapter network surface, §Outbound data flows, §Polygon RPC ops. |

**Effort:** ~2 days of doc work. Block v0.0.2 tag on documentation parity.

---

## Part XII — Beads Housekeeping (NEW)

> **[VERIFIED 2026-05-23 / trade-trace-z59f]** Every bead referenced
> in §"First commit of v0.0.2 work" and §"Existing beads to leave
> open" below was already closed/disposed at the time z59f ran.
> Validation: `bd list --id <the 15 IDs> --all --flat` returned 15
> rows, all status ✓ closed. The empty `frontend/` directory was
> removed locally; git tracked nothing under it (`git status` clean
> after `rmdir`), so the "git rm -rf frontend/" item below is also
> a no-op. This Part XII checklist is therefore historical and
> requires no further executor action; the v0.0.2 program runs
> through the trade-trace-2n68 epic + its 35 related beads instead
> of an umbrella tag.

### First commit of v0.0.2 work

1. **`git rm -rf frontend/`** — directory is empty (only `.` and `..`), zero refs from src/. Pure cleanup from prior Console removal. *(Done 2026-05-23 via `rmdir`; produced no commit because empty dirs are not tracked by git.)*
2. **Close as superseded** under the current-exposure cluster: `trade-trace-39pg`, `trade-trace-dr4m`, `trade-trace-suj6`, `trade-trace-ahmp`, `trade-trace-od93`, `trade-trace-umzf`, `trade-trace-ax4e`. *(Already closed.)*
3. **Close as superseded**: `trade-trace-77z` (market_scan edge/opportunity). *(Already closed.)*
4. **Close as superseded**: `trade-trace-2g2` (signal.scan future kinds) — only `unscored_forecast` remains relevant. *(Already closed.)*
5. **Close as scope-changed**: `trade-trace-cs0r` (advanced report filtering) — re-scope to the consolidated report set. *(Already closed.)*

### New v0.0.2 epic

Create umbrella `trade-trace-v0.0.2-pm-pivot` with child beads:
*(Materialized as trade-trace-2n68 with 35 related-to children, label `v002-pm-pivot`. See `audits/beads-programs/v002-pm-pivot/`. The umbrella itself was an epic, not a tag.)*

**P0 (foundation, must land first):**
- Module split (`ledger.py`, `reports.py`)
- Idempotency auto-derivation
- Test-order sensitivity fixes
- Schema migrations m012–m015 (markets, forecast_snapshot_anchor, drop theses + add forecasts.probability + rename meta_json, drop sources + drop source-edges) [AUDIT 2026-05-22: renumbered from m014–m017.]
- Beads housekeeping (this section)

**P1 (PM features):**
- Polymarket adapter
- `market.bind` / `market.refresh` / `snapshot.fetch` / `outcome.fetch` / `forecast.anchor_to_snapshot`
- Anchored-baseline calibration report
- Trajectory + Terminal calibration reports
- Four PM-native reports (`market_lifecycle`, `resolution_quality`, `amm_slippage`, `time_decay_sharpening`)
- Report consolidation (25 → 13)
- Tool catalog consolidation (81 → 44)
- ONNX vector embeddings
- Report filter implementation
- ECE equal-mass binning
- N+1 snapshot query fix
- Coach test coverage

**P2 (polish):**
- New error codes
- Security review additions
- CLI grammar respec
- Documentation rewrite

### Existing beads to leave open

- `trade-trace-3zvl` (operational logging contract) — relevant under adapter; adapter operations should emit structured logs per this contract. *(Already closed 2026-05-22.)*
- `trade-trace-jtec` (Console Logs page) — already deferred; keep deferred (Console UI is gone). *(Already closed 2026-05-22.)*
- `trade-trace-5rrw` (public-history rewrite), `trade-trace-jr9b` (audit-artifact scrubbing), `trade-trace-gcpp` (PyPI trusted publisher) — human-decision blockers, separate track. *(All three already closed 2026-05-22.)*

[VERIFIED 2026-05-23 / trade-trace-z59f] None of these 5 "leave open" beads is actually open. The adapter-logging and public-release tracks live under fresh bead IDs inside the v002-pm-pivot epic (`trade-trace-2h0g` for adapter security/operational logging, `trade-trace-voum`/`trade-trace-3l6w` for release-readiness).

---

## Part XIII — Release Checklist Updates (NEW)

`docs/RELEASE_CHECKLIST.md` gate sequence for v0.0.2:

```
# Pre-publish gates for v0.0.2
1. pip install -e ".[dev,embeddings]"   # embeddings now first-class
2. ruff check src tests
3. mypy src
4. pytest -q                            # ~1,500 tests expected
5. tt journal init                      # smoke test the rebuilt schema
6. tt market bind <test-condition-id> --inline-metadata-json '{...}'   # smoke without adapter
7. # With adapter (manual gate, not in CI):
   #   network.polymarket.enabled=true
   #   network.polymarket.polygon_rpc_url=<test-RPC>
   tt market bind <real-condition-id> --source polymarket
8. # Documentation truthfulness gates
9. pytest tests/docs -q
10. # Security gates
11. pytest tests/security -q
12. # Adapter offline-default gate (P0)
13. pytest tests/security/test_no_network_default.py -q
14. # Adapter secret-scrubbing gate
15. pytest tests/security/test_adapter_url_scrubbing.py -q
16. python -m build
17. # PyPI trusted-publisher (blocked on trade-trace-gcpp human decision)
```

### New CI rules

- All adapter tests run in a CI lane with network disabled (httpx mocked); a second lane runs nightly against a test Polymarket condition with the adapter live (best-effort, can flake without blocking).
- `pytest tests/security/test_mvp_boundary_audit.py` continues to pin the shipped tool set; updated to the new 44-tool catalog.
- **New weekly smoke job** (non-blocking): `pip install -e ".[embeddings]"` + `python -c "import onnxruntime; import tokenizers"` on macOS-arm64 and Windows-latest runners. Catches wheel-availability regressions for users on those platforms before they hit upstream.

---

## Part XIV — Test Fixture Set (NEW)

### Adapter response fixtures

`tests/integration/fixtures/polymarket/` should contain:

| Fixture | Purpose |
|---|---|
| `market_binary_open.json` | Active binary market with normal CLOB book |
| `market_binary_open_amm.json` | Active binary market on AMM with curve data |
| `market_binary_resolved_yes.json` | Resolved YES (on-chain transaction stub) |
| `market_binary_resolved_no.json` | Resolved NO |
| `market_binary_ambiguous.json` | Resolved with `outcome.status='ambiguous'`, ambiguity_kind set |
| `market_binary_voided.json` | Resolved with `outcome.status='void'` |
| `market_binary_disputed.json` | Resolved with dispute on the resolution_source |
| `market_categorical_rejected.json` | Multi-outcome market — adapter must reject with `ADAPTER_PROTOCOL_ERROR` |
| `market_scalar_rejected.json` | Scalar market — adapter rejects |
| `snapshot_thick_book.json` | CLOB book with deep liquidity |
| `snapshot_thin_book.json` | CLOB book with sparse liquidity (slippage scenario) |
| `snapshot_amm_curve.json` | AMM curve at three reference prices |
| `polygon_resolution_tx.json` | Stubbed Polygon RPC response for `outcome.fetch` |

### `journal.fixture_seed` PM shape (rewrite)

Current `src/trade_trace/tools/fixture.py` produces ~30 decisions across **12** decision types (docstring claims 13 "except `hold`" but only 12 are actually seeded — `hold` is excluded but the count still totals 12). Under PM-only (8 decision types, no theses/sources tables), the fixture needs a rewrite. **Recommendation: minimal realistic seed, not heavy.** [AUDIT 2026-05-22.]

**Target `mvp-eval-pm` (replaces `mvp-eval`):**
- **8 markets** (one per representative decision lifecycle)
- **8 forecasts** (binary; at least 4 anchored to snapshots for `report.calibration_anchored` coverage)
- **8 decisions** (one per remaining type: `watch`, `skip`, `actual_enter`, `actual_exit`, `invalidate_thesis`, `update_thesis`, `resolved`, `review`)
- **5 outcomes** (3 resolved YES/NO, 1 ambiguous, 1 voided)
- **2 reflections** (one decision post-mortem, one strategy-level)
- **1 strategy**, **1 playbook** + 1 version + 1 rule
- Agent-vs-market scenarios: at least 2 forecasts above the market, 2 below (for `report.calibration_anchored` skill values).

**New variant `forecast-only-pm`:** for Manifold-style calibration researchers.
- **5 markets**, **5 forecasts**, **5 watch-only decisions**, **3 outcomes**, **2 reflections**.
- No `actual_enter`/`actual_exit` decisions. No positions.
- Exercises `report.calibration`, `report.calibration_anchored`, `report.recall` without any P&L surface.

**Effort:** ~120 LOC fixture rewrite + ~40 LOC for the new variant.

---

## Part XV — Open Items / Risks

### Pre-release license
Confirmed: no 0.0.1 stable cut; hard break to 0.0.2 acceptable.

### Polymarket API stability
Gamma API is public but not formally versioned. Adapter parses defensively (skip unknown fields, validate required, surface explicit errors when shape changes). Cache last-good metadata.

### Polygon RPC ops
Users supply their own RPC URL. Trade Trace ships no defaults. Documented in SECURITY.md.

### Idempotency collisions under auto-derivation
Caller can always override with explicit key. Conflicts logged with canonical hash; surface via existing `IDEMPOTENCY_CONFLICT` path.

### Concurrent `market.bind` race
Single-writer SQLite + `UNIQUE (source, external_id)` index + idempotent upsert should be safe. Tested in `test_adapter_concurrent_bind.py`.

### `outcome` → `resolution` rename consistency
Tool renamed (`outcome.add` → `resolution.add`). Table stays `outcomes` (rename is expensive and the tool surface is what agents see). `meta.legacy_name` carries old tool name for transition.

### What if Polymarket changes API
Document API target version in adapter docstrings. Surface schema changes via `ADAPTER_PROTOCOL_ERROR` rather than silent miscoding. Adapter version is independent of Trade Trace version.

### Frontend directory cleanup
`/frontend/` exists at repo root despite Console removal. Audit and delete in P0 housekeeping if no live references remain.

### JSONL legacy import handling
0.0.1rc3 JSONL exports won't replay cleanly under 0.0.2. Document explicitly: legacy imports require a one-time transform (out of scope for v0.0.2). Users in this position should re-import from the upstream source (which they likely already have).

### What we lose
Optionality for future equity/option/future support. Re-adding would require schema migrations.

### What we gain
- A coherent product story: "the calibration journal for LLM prediction-market trading agents."
- The agent-vs-market calibration metric (impossible on general trading journals).
- Four PM-native reports (market_lifecycle, resolution_quality, amm_slippage, time_decay_sharpening).
- ~46% smaller tool catalog with all real use cases covered.
- A clear roadmap: Polymarket v1 → Kalshi v1.1 → Manifold v1.2 → CRPS scoring.

### Items the 2026-05-22 audit could not verify (carry into pre-implementation pass)

- **Beads existence and state:** Part XII references specific bead IDs (`trade-trace-39pg`, `trade-trace-suj6`, `trade-trace-ahmp`, `trade-trace-od93`, `trade-trace-umzf`, `trade-trace-ax4e`, `trade-trace-dr4m`, `trade-trace-77z`, `trade-trace-2g2`, `trade-trace-cs0r`, `trade-trace-3zvl`, `trade-trace-jtec`, `trade-trace-5rrw`, `trade-trace-jr9b`, `trade-trace-gcpp`). The audit did not run `bd show` on any of these. Verify each is open and matches the described state before closing/superseding.
- **Doc rewrite scope (Part XI):** Structure of `docs/PRD.md`, `docs/VISION.md`, `docs/AGENT_GUIDE.md`, etc. confirmed; content not read in full. The "~2 days of doc work" estimate is unvalidated.
- **Polymarket API contract:** Cache TTLs (24h/1h/5min) and rate limits (300 req/10s Gamma, 1500 req/10s CLOB) cited from "Polymarket docs, 2026-05" — not re-fetched during the audit. Re-verify against current docs before locking the resilience policy in Part IV.
- **`forecast_outcomes` downstream readers:** Decision C1 (collapse to flat `forecasts.probability`) requires updating every report and tool that reads `forecast_outcomes`. Estimated ~6 reports based on grep; full call-site enumeration deferred to implementation kickoff.
- **Coach tests' seeded-data claim (P1.4):** The 16 coach tests confirmed; the assertion that they have "no seeded tag/source/integrity data" was not verified by reading test bodies.

---

## Part XVI — MCP Server Adapter Surface Changes (NEW)

The MCP server (`src/trade_trace/mcp_server.py`, 245 LOC) is intentionally transport-neutral and exposes tools via `mcp_tool_specs()`. Under v0.0.2 it picks up changes from Parts II + IX + XV automatically, but three surfaces need explicit work and dedicated tests.

### 1. `errors.py` extension

Add the 9 new codes from Part IX to the closed `ErrorCode` enum: `ADAPTER_DISABLED`, `ADAPTER_TIMEOUT`, `ADAPTER_RATE_LIMITED`, `ADAPTER_PROTOCOL_ERROR`, `EXTERNAL_API_ERROR`, `RESOLUTION_NOT_AVAILABLE`, `CONFIG_REQUIRED`, `MARKET_NOT_BOUND`, `MARKET_STATE_CONFLICT`.

The enum is referenced by both the CLI and MCP dispatchers; adding to the enum surfaces them on both transports identically.

**Effort:** ~10 LOC + entries in `docs/architecture/contracts.md`.

### 2. `journal.status` payload extension

Currently `journal.status` returns `outbound_network_active: false` (a functional value — there genuinely is no outbound network active today). Under v0.0.2 **keep** that field (it is the load-bearing local-first signal) and **extend** the payload with `adapter_state`: [AUDIT 2026-05-22.]

```python
{
  "adapter_state": {
    "polymarket": {
      "enabled": false,         # mirrors network.polymarket.enabled
      "configured_endpoints": {  # which config keys are set (not their values)
        "gamma_base_url": true,
        "polygon_rpc_url": false
      },
      "cached_markets_count": 0,
      "last_successful_fetch_at": null
    }
  },
  "outbound_network_active": false  # true iff any adapter is enabled
}
```

Agents call `journal.status` at session start to know whether adapter primitives are available before depending on them.

**Effort:** ~25 LOC in `tools/journal.py` `_journal_status` + schema update + 2 tests.

### 3. MCP test suite additions

`tests/integration/test_mcp_stdio_server.py` currently tests transport parity, list_tools, and basic dispatch. Add:

- `test_mcp_adapter_error_codes.py`: induce each of the 9 new error conditions; verify envelope shape on MCP transport matches CLI.
- `test_mcp_adapter_status.py`: verify `journal.status` adapter_state payload on MCP transport.
- `test_mcp_tool_catalog_pinned.py`: assert exact set of ~45 tools is exposed (parallel to existing `test_mvp_boundary_audit.py` but specifically for the MCP transport listing).

**Effort:** ~150 LOC tests across the three files.

### 4. MCP capabilities negotiation

MCP supports server-advertised capabilities (the `experimental` field in initialize response). The Polymarket adapter is a Trade-Trace-side capability, not an MCP-protocol one — no MCP capability flag needed. Agents introspect adapter state via `journal.status`, not the MCP handshake. **No change required.**

### 5. `meta.legacy_name` for renamed tools

For `outcome.add` → `resolution.add`, MCP tool specs include `meta.legacy_name` field so agents written against 0.0.1rc3 patterns get a deprecation-clear error rather than a silent NOT_FOUND. The CLI mirrors this via the dispatch error message.

**Total Part XVI effort:** ~185 LOC + 150 LOC tests.

---

## Part XVII — Performance Budgets (NEW)

Pin SLOs in v0.0.2 to make the "agent-startup substrate" pitch concrete and enforceable. Pin them as opt-in tests in the existing `TRADE_TRACE_RUN_PERF_TESTS=1` lane (precedent: `tests/integration/test_reporting_pagination_perf_baseline.py`).

### SLO table

| Tool | Cold (first call) | Warm (steady state) | Justification |
|---|---|---|---|
| `report.bootstrap` | **< 500 ms p95** | **< 150 ms p95** | ~30 indexed SQLite reads against local tables, no joins beyond instrument/strategy lookups. Reference: existing 100k-row paginate budget is 1.0s with 5× CI headroom (real ~0.05s). Bootstrap is ~30× a single page, so 150ms warm is realistic; cold accounts for WAL handshake + first-query plan cache. |
| `market.bind` (adapter on) | n/a | **< 2.0 s p95, < 5.0 s p99** | Dominated by Gamma API hop (typical 200-800ms) + 1 SQLite append. Budget covers cold TLS + DNS plus retry headroom. |
| `market.bind` (adapter off) | n/a | **< 50 ms p95** | Pure local upsert; no network. |
| `snapshot.fetch` (adapter on) | n/a | **< 1.5 s p95** | CLOB endpoint is typically faster than Gamma; budget tighter. |
| `outcome.fetch` (adapter on, Polygon RPC) | n/a | **< 3.0 s p95** | RPC providers vary widely (Alchemy ~200ms; public polygon-rpc.com ~800ms+). Wider budget. |
| `forecast.add`, `decision.add`, `memory.reflect` | n/a | **< 30 ms p95** | Single SQLite append + idempotency check; should be invisible to agent perception. |
| Single `report.*` call (warm) | n/a | **< 100 ms p95** | Most reports query 1-3 tables with indexed predicates. |

### Flake guard

Budget assertions use **3× the SLO** to avoid CI flakiness from neighbor noise. Actual measurements should be 5-10× under the SLO on dev hardware; the 3× margin catches real regressions, not single-run noise.

### Test infrastructure

- New `tests/integration/test_bootstrap_perf_baseline.py` mirrors the pagination perf test pattern (opt-in via `TRADE_TRACE_RUN_PERF_TESTS=1`).
- New `tests/integration/test_adapter_perf_baseline.py` covers `market.bind` + `snapshot.fetch` against fixture-mocked HTTPX (no real network), with the budget reflecting the local DB write portion only. Real-network budgets are documentation; we don't gate CI on network conditions.
- Update `docs/architecture/operability.md` §3.x with the SLO table and the `TRADE_TRACE_RUN_PERF_TESTS=1` enforcement note.

**Effort:** ~150 LOC tests + ~30 LOC docs.

---

## Appendix A — Tool Catalog Diff (Summary)

See Part II. Net: 81 → 44 tools.

## Appendix B — Predecessor Document

The original v0.0.1rc3 remediation plan is preserved in git history (commit prior to this rewrite). All major findings absorbed above.

---

**Next action:** Review this plan. Iterate. Once approved, the writing-plans skill produces the implementation plan (ordered work items with acceptance criteria), and Part XII (beads housekeeping) is the first concrete step.
