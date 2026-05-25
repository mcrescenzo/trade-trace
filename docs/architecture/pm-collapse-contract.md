# PM-only schema collapse contract

> Status: **decision document for trade-trace-pg7q** — implementation contract for `trade-trace-4lki` and its split blockers.
> This file is intentionally a contract artifact, not a migration. It exists because a previous one-shot mechanical rewrite made the narrow grep/tests pass while making the broad test suite fail massively.
>
> **Execution update (schema gate trade-trace-q0c9):** the original hard-break target below remains the long-term PM-only direction, but the landed m014/m015/4lki implementation is deliberately additive. Runtime now writes/reads PM-native `markets`, `forecast_snapshot_anchor`, `forecasts.probability`/`market_id`, `memory_nodes.metadata_json`, and inline `metadata_json.sources` while preserving legacy tables/tools as guarded compatibility fallbacks. Residual legacy references are reviewed in `tests/allowlists/mhy1_legacy_grep_allowlist.json`; downstream catalog/CLI/import-export/docs beads own further hard-break surface cleanup.

## Product boundary

Trade Trace v0.0.2 remains a local-first calibration journal and memory substrate for stateless prediction-market agents.

This collapse must not add or widen:

- broker, wallet, order-routing, or trade-execution behavior;
- human dashboard/frontend behavior;
- background scheduler/fetch-daemon behavior;
- default outbound network behavior;
- credential persistence or financial-advice surfaces.

Polymarket and other venue names may appear as market metadata values, but live adapter/network behavior remains opt-in and belongs to later adapter beads, not to the schema collapse itself.

## Current state evidence

The canonical old ledger schema still comes from `src/trade_trace/storage/migrations/m003_m1_ledger.py`:

- `venues` and `instruments` create the old venue/instrument identity chain; `instruments.venue_id` is the old market-source join key.
- `snapshots`, `decisions`, `outcomes`, `position_events`, and `positions` still point at `instrument_id`.
- `theses` is the standalone rationale table. `forecasts.thesis_id` is currently required.
- `forecast_outcomes` stores one row per probability outcome.
- `sources` is standalone; source attachments are edge rows emitted by the source attach tool factory, not a `source_attachments` table.
- `memory_nodes.meta_json` is the major remaining top-level metadata naming outlier; ledger tables already mostly use `metadata_json`.

The PM anchor schema already exists from the previous slice:

- `m012_markets.py` creates `markets` with `source`, `external_id`, lifecycle/state columns, `venue_metadata_json`, `metadata_json`, and `UNIQUE(source, external_id)`.
- `m013_forecast_snapshot_anchor.py` creates one anchor row per forecast with copied `market_implied_probability`.

The runtime is still old-shaped in many surfaces, especially `tools/ledger/forecast.py`, `tools/ledger/thesis.py`, `tools/ledger/source.py`, reports, exporter/importer, direct-SQL fixtures, and docs. That is why 4lki must proceed as ordered slices rather than grep-driven global substitution.

## Canonical replacements

| Old surface | Canonical v0.0.2 replacement | Notes |
|---|---|---|
| `venues` table | Fold into `markets.source` plus `markets.venue_metadata_json` | `markets.source` is the venue/source enum. |
| `venue_id` | No canonical column | Old references should become market binding metadata or disappear. |
| `instruments` table | `markets` table | `markets.id` is the canonical local market ID. |
| `instrument_id` | `market_id` on market-scoped rows | Applies to decisions, snapshots, outcomes, and position events. |
| `instrument.add` | `market.bind` | Manual binding must remain local/offline-capable. |
| `theses` table | Fold into `forecasts` rationale fields | Rationale is part of the forecast row. |
| `thesis_id` | No canonical public argument | Use `forecast_id` for revisions and `market_id` for market scope. |
| `thesis.add` | `forecast.add(..., rationale_body=...)` | Hard-break old tool; see compatibility policy. |
| `forecasts.thesis_id` | `forecasts.market_id` | Forecasts bind directly to markets. |
| `forecast_outcomes` table | `forecasts.probability` | Binary YES probability; NO probability is `1 - probability`. |
| categorical/scalar forecast kinds | Out of v0.0.2 runtime scope | Reject or explicitly mark unsupported; do not preserve hidden scoring paths. |
| `sources` table | `metadata_json.sources` arrays | Stored on forecasts, decisions, and memory nodes. |
| `source.attach_to_*` tools | Fold into write-time `metadata_json.sources` | Old attach edge rows are dropped during m015. |
| `source_attachments` table | None | This table never existed; do not create or drop it. |
| `memory_nodes.meta_json` | `memory_nodes.metadata_json` | Rename in m014 and update all readers/writers deliberately. |

### Source array shape

Every canonical embedded source array uses this shape:

```json
[
  {
    "kind": "url|pdf|image|tweet|news_article|research_doc|transcript|chart_image|note|other",
    "title": "human-readable source title",
    "url": "optional URL or local reference",
    "stance": "supports|contradicts|about",
    "captured_at": "UTC timestamp if known",
    "hash": "optional content hash"
  }
]
```

The default array is absent or empty. Readers must tolerate missing arrays and malformed legacy metadata by returning caveats rather than inventing provenance.

## Compatibility policy

v0.0.2 is a greenfield hard break. Do not maintain hidden compatibility shims that keep the old schema alive.

Old public surfaces should fail explicitly once removed:

- renamed tools use a typed redirect (`renamed_to`) where the new surface is unambiguous;
- killed/folded tools return `UNSUPPORTED_CAPABILITY` with a redirect when useful;
- old field names such as `thesis_id`, `instrument_id`, `venue_id`, and `meta_json` should not be silently accepted at runtime unless a bounded compatibility alias is added in the same slice with tests and an expiration note.

This is deliberately stricter than a mechanical alias layer. The failed one-shot rewrite proved that green tests from broad substitution are not enough: fixture helpers, reports, semantic event keys, exporter/importer replay, and docs must move together.

## Migration sequence

### m014: forecast, rationale, enum, and memory metadata collapse

Purpose: make forecast rows the canonical binary PM prediction/rationale record while preserving local journal semantics.

Required schema changes:

- Rebuild or migrate `forecasts` so it no longer requires `thesis_id`.
- Add:
  - `market_id TEXT REFERENCES markets(id)`;
  - `rationale_body TEXT`;
  - `falsification_criteria TEXT`;
  - `invalidated_at TEXT`;
  - `invalidated_by TEXT`;
  - `updated_rationale_at TEXT`;
  - `updated_rationale_by TEXT`;
  - `probability REAL CHECK (probability >= 0.0 AND probability <= 1.0)`.
- Constrain `forecasts.kind` to `binary` only.
- Drop or stop creating `forecast_outcomes`; backfill `forecasts.probability` from the YES row only when deterministic. Greenfield/manual-review rows may be rejected rather than silently guessed.
- Drop or stop creating `theses`; backfill `forecasts.rationale_body` and `falsification_criteria` from the linked thesis when deterministic.
- Rename `memory_nodes.meta_json` to `memory_nodes.metadata_json`; update all production readers/writers and tests that truly address memory node metadata.
- Prune enums in the same schema slice only where required by the schema contract:
  - `forecast.kind = {'binary'}`;
  - `decisions.side` and `position_events.side = {'yes','no','flat_neutral'}`;
  - `positions.side = {'yes','no'}`;
  - `decisions.type = {'watch','skip','actual_enter','actual_exit','invalidate_thesis','update_thesis','resolved','review'}`.

Do not remove the `sources` table or old source-edge rows in m014; that belongs to m015.

### m015: inline sources and source-edge collapse

Purpose: remove standalone source rows and source attachment edges after forecasts/decisions/memory nodes have canonical metadata containers.

Required schema changes:

- Ensure `forecasts.metadata_json`, `decisions.metadata_json`, and `memory_nodes.metadata_json` support `sources` arrays.
- Drop or stop creating `sources`.
- Delete old `edges` rows where `source_kind='source'` or `target_kind='source'`, plus the old source attach rows produced by source attach tools. Do not backfill stale source IDs.
- Do not create or drop `source_attachments`; it never existed.
- Update source-quality readers to query `metadata_json.sources` with `json_each()` or equivalent local SQLite JSON traversal.

### Market-id rename slice

The implementation can land this inside m014/m015 or as a follow-up dependent slice, but it must be treated as a schema/runtime migration, not a text substitution:

- `decisions.instrument_id` -> `decisions.market_id`;
- `snapshots.instrument_id` -> `snapshots.market_id`;
- `outcomes.instrument_id` -> `outcomes.market_id`;
- `position_events.instrument_id` -> `position_events.market_id`;
- `positions.instrument_id` -> `positions.market_id` if positions remain in the local journal/reporting surface.

Indexes, timestamp-governance tests, semantic keys, report filters, exporter/importer replay, and direct-SQL test builders must all move with the column rename.

## Runtime implementation order

1. **Schema and model seam first.** Add migrations and update low-level helpers/builders so new databases are coherent before removing runtime tools.
2. **Core write tools next.** Implement `market.bind` and update `forecast.add`, `snapshot.add`, `decision.add`, and `resolution.add`/`outcome.add` around `market_id` and `forecasts.probability`.
3. **Source collapse third.** Replace `source.add` and `source.attach_to_*` behavior with embedded source arrays on the owning writes. Update `report.source_quality` only after m015 is real.
4. **Exporter/importer/replay fourth.** Update event names, semantic keys, and replay dispatch so old events fail explicitly or map through documented hard-break errors.
5. **Reports and read models fifth.** Update report joins from venue/instrument/thesis/source tables to market/forecast/source arrays. Quarantine or explicitly keep position/P&L surfaces local-read-only; do not add execution behavior.
6. **Docs/tests last.** Migrate docs and test fixtures after runtime semantics are proven. Do not make grep cleanliness the first success signal.

## Hot spots to update deliberately

- `tests/_direct_sql_builders.py` is the direct-SQL fixture seam; use it to reduce broad test churn.
- `tests/integration/test_manual_ledger_flow.py`, `test_edges.py`, `test_schema.py`, `test_scoring_p1.py`, `test_report_calibration.py`, `test_source_quality.py`, and `test_audit_readiness.py` should become staged gates, not afterthoughts.
- `src/trade_trace/reports/source_quality.py`, `audit_readiness.py`, `strategy_health.py`, `integrity.py`, `calibration.py`, and `forecast_diagnostics.py` encode real semantics over the old tables.
- `src/trade_trace/reporting/trade_rows.py` and `position_rows.py` are high-risk execution-adjacent read models. Keep them local-read-only or reduce them; do not extend them toward broker/execution surfaces.
- `src/trade_trace/exporter.py`, `src/trade_trace/tools/imports.py`, `src/trade_trace/events/semantic_keys.py`, and JSONL replay tests pin event and idempotency contracts.
- `docs/architecture/v002-pm-pivot-catalog.md` is the tool/report catalog source of truth. `docs/PRD.md` and `docs/architecture/persistence.md` still contain substantial old-schema surface and must not be used alone as current truth.

## Validation gates

Run validation in stages and stop on the first red gate that indicates current-scope regression.

### Stage 0: collection/import sanity

```bash
PYTHONPATH=src .venv/bin/pytest --collect-only -q
```

### Stage 1: schema and migration contract

```bash
PYTHONPATH=src .venv/bin/pytest \
  tests/integration/test_migrations.py \
  tests/integration/test_migrations_schema_hash.py \
  tests/integration/test_schema.py \
  -q
```

### Stage 2: core write tools and schema parity

```bash
PYTHONPATH=src .venv/bin/pytest \
  tests/integration/test_manual_ledger_flow.py \
  tests/contracts/test_tool_schema_runtime_parity.py \
  tests/contracts/test_write_tools_have_schemas.py \
  tests/contracts/test_agent_ergonomics.py \
  -q
```

### Stage 3: forecast/scoring/calibration

```bash
PYTHONPATH=src .venv/bin/pytest \
  tests/integration/test_scoring_p1.py \
  tests/integration/test_scoring_lifecycle.py \
  tests/integration/test_report_calibration.py \
  tests/integration/test_forecast_diagnostics_report.py \
  tests/integration/test_outcome_label_null_resilience.py \
  -q
```

### Stage 4: source/provenance collapse

```bash
PYTHONPATH=src .venv/bin/pytest \
  tests/integration/test_source_quality.py \
  tests/integration/test_audit_readiness.py \
  tests/integration/test_edges.py \
  tests/integration/test_source_attach_to_memory_node.py \
  tests/integration/test_review_bundle_contract.py \
  -q
```

### Stage 5: reports/read models

```bash
PYTHONPATH=src .venv/bin/pytest \
  tests/integration/test_report_compare.py \
  tests/integration/test_report_pnl_watchlist.py \
  tests/integration/test_report_open_positions.py \
  tests/integration/test_report_current_exposure.py \
  tests/integration/test_report_exposure_anomalies.py \
  tests/integration/test_report_unscored_velocity.py \
  tests/integration/test_work_queue_next_actions.py \
  tests/integration/test_strategy_health_report.py \
  -q
```

### Stage 6: security/local-only boundary

```bash
PYTHONPATH=src .venv/bin/pytest \
  tests/security/test_mvp_boundary_audit.py \
  tests/security/test_no_network_default.py \
  tests/security/test_no_credentials.py \
  tests/security/test_secret_pattern_writes.py \
  tests/security/test_report_sql_filters.py \
  -q
```

### Stage 7: final 4lki closure gates

```bash
git grep -n "forecast_outcomes\|thesis_id\|source.attach\|meta_json\|instrument_id\|venue_id" src tests docs || true
PYTHONPATH=src .venv/bin/pytest tests/integration/test_migrations.py tests/integration/test_scoring_p1.py tests/integration/test_edges.py -q
PYTHONPATH=src .venv/bin/pytest -q
```

The final grep should be clean unless the final regression bead creates a reviewed allowlist explaining intentional historical references. A clean grep without broad pytest is not sufficient evidence.

## Closure rule for `trade-trace-4lki`

`trade-trace-4lki` is closeable only after:

1. this contract is closed;
2. m014, m015, call-site migration, and final regression blockers are closed with evidence;
3. no hidden source of old schema behavior remains in runtime tools, reports, exporter/importer, semantic keys, or direct-SQL fixture builders;
4. broad pytest passes, or every remaining broad-suite failure is attributed and represented by Beads before closure.
