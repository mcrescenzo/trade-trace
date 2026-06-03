# Friction registry (rolling)

> The dedup memory for the AX dogfood loop. **Read this at the start of every
> run (Phase A)** so the bot does not re-report or re-fix something already
> handled, and **update it at the end of every run (Phase D)** with whatever was
> found this run.
>
> One row per distinct friction item. Keep `id` stable once assigned
> (`AX-NNN`, monotonically increasing). When an item's disposition changes
> (e.g. open → fixed), update its row in place rather than adding a new one.

## Status legend

- `open` — observed, not yet addressed (still reproducible).
- `fixed` — resolved by a direct commit this loop (see `ref` for the SHA).
- `filed` — handed to Beads as a feature / major rework / design question
  (see `ref` for the bead id).
- `intentional` — confirmed deliberate; promoted to
  [`intentional-design.md`](./intentional-design.md). Do not re-report.
- `wontfix` — decided against, with reason in `ref`.

## Surface legend

`tool` (MCP tool behavior) · `schema` (tool schema/description text) ·
`error` (error message / `next_actions` hint) · `doc` (docs drift) ·
`cli` (CLI surface) · `onboarding` (cold-start/first-run) · `report` (report output).

## Registry

| id | first-seen run | surface | description | status | ref |
|----|----------------|---------|-------------|--------|-----|
| AX-001 | 2026-06-03-01 | report | bootstrap caveat codes are cryptic; no inline gloss/glossary | filed | trade-trace-o1wr |
| AX-002 | 2026-06-03-01 | tool | no live market discovery surface; bot must curl Gamma out-of-band | filed | trade-trace-663l |
| AX-003 | 2026-06-03-01 | schema | market.bind `example_minimal` carries ~32 fields, obscures the 4 required | filed (deferred) | trade-trace-mpsu — entangled: example_minimal is the json_schema_derive source, so trimming it shrinks the schema; needs decoupling (repo-wide) |
| AX-004 | 2026-06-03-01 | error | market.bind missing `source` → bare error, no allowed values | fixed | 4e4ea9c |
| AX-005 | 2026-06-03-01 | error | decision.add missing `type` (not `decision_type`) → bare error, no allowed values | fixed | 8e974a5 |
| AX-006 | 2026-06-03-01 | tool | `market_id` vs `instrument_id` naming inconsistency across tools | fixed | ff641a6 (closed trade-trace-nqyv) |
| AX-007 | 2026-06-03-01 | tool | paper_enter needs `thesis_id` but forecast.add returns `forecast_id` | fixed | 68fb687 (closed trade-trace-4x1b) |
| AX-008 | 2026-06-03-02 | report | unrealized PnL for a `no`-side position marks NO entry (0.875) vs YES price (0.12), no side conversion → phantom +$75.50 on a flat position; `decision.add` price convention for `no` undocumented | filed | trade-trace-ctvb (P1) |
| AX-009 | 2026-06-03-02 | tool | snapshot.fetch/fetch_series/market.refresh build the Gamma URL from `external_id`, ignoring `gamma_market_id`; namespaced external_id (per AGENT_GUIDE example) → HTTP 422 | fixed | 1ea628d |
| AX-010 | 2026-06-03-02 | schema | forecast.add `confidence_label` enum not in tool.schema; invalid value leaked raw SQLite CHECK error | fixed | 4bd01ce |
| AX-011 | 2026-06-03-02 | schema | snapshot.fetch/outcome.fetch advertise `idempotency_key` as optional/runtime-defaulted but reject calls that omit it (`auto_derivation_available:false`) | filed | trade-trace-2cmb (P2) |
| AX-012 | 2026-06-03-02 | report | open forecast with `resolution_at:null` never surfaces in report.work_queue as resolve_due (only report.lifecycle shows it) | filed | trade-trace-ptyi (design Q) |
| AX-013 | 2026-06-03-02 | report | skip/watch/hold decisions can't link `forecast_id`, so report.coach flags a forecasted-but-skipped market as unforecasted | filed | trade-trace-t9n5 (design Q) — fix verified live in run 2026-06-03-03: skip links forecast_id, coach no longer false-flags |
| AX-014 | 2026-06-03-03 | doc | AGENT_GUIDE `market.bind` example omitted now-required `state`+`mechanism`; a cold bot copying it gets VALIDATION_ERROR | fixed | c9383ff (+regression test) |
| AX-015 | 2026-06-03-03 | schema | `market.refresh` advertises only `market_id` required but rejects calls without `idempotency_key` (auto_derivation_available:false) — AX-011 class, tool the 2cmb fix missed | filed | trade-trace-4z2t |
| AX-016 | 2026-06-03-03 | tool | `market.refresh` with `idempotency_key` throws a RAW (non-envelope) error: event_type `market.refreshed` unregistered in events_semantic_keys; tool 100% unusable | filed | trade-trace-4z2t (P1) |
| AX-017 | 2026-06-03-03 | tool | no agent-surface way to retrieve a market's resolution_rule/description text (market.search/bind/snapshot.fetch don't expose it); can't responsibly forecast ambiguous markets | filed | trade-trace-n33z (P2) |
| AX-018 | 2026-06-03-03 | report | `report.work_queue` flags resolve_due_forecast on a still-live market (mid 0.505, accepting_orders:true) solely from resolution_at_missing (AX-012 inverse) | filed | trade-trace-fe2f (design Q) — re-confirmed run 2026-06-03-04 (fc_CheQKZ still flagged while mid 0.505) |
| AX-019 | 2026-06-03-04 | tool | `market.search` `query` is a silent no-op: routed to Gamma `/markets?q=` which has no free-text search and ignores unknown params; any query → identical default list. Discoverability broken + misleading. Real endpoint is `/public-search` (event-nested shape) | fixed | 782d4ec (+regression tests; closed trade-trace-yz3q) |
| AX-020 | 2026-06-03-04 | tool/error | `resolve_due_forecast` obligation has no in-surface path to outcome evidence when Polygon RPC is unset: `outcome.fetch` fails closed (CONFIG_REQUIRED), nothing points to `snapshot.fetch` (Gamma) as the no-RPC alternative; feeder dead-ends, forecasts never score | filed | trade-trace-isqo (design Q) |
| AX-021 | 2026-06-03-05 | tool/schema | `market.bind` first-bind Gamma `/markets/{id}` lookup is built from `external_id`, ignoring the caller's `gamma_market_id`; the AGENT_GUIDE's own bind example (`external_id:"polymarket:<id>"` + bare `gamma_market_id`) → ADAPTER_PROTOCOL_ERROR 422. AX-009 class on the path that fix missed. Also: schema/docstring claimed "Manual/local only: no network" but the adapter-enabled path makes a read-only Gamma call (`bound_via:adapter`) | fixed | f2313e1 (+regression test; corrected stale description) |
| AX-022 | 2026-06-03-05 | report/onboarding | cold `report.bootstrap` on an empty journal surfaces only read/continuity `suggested_process_calls` (work_queue/next_actions/recall_receipts/strategy.show); no first-run entry-point hint (`market.search`→bind→forecast), so a bootstrap-first cold bot hits empty queues with no forward action | filed | trade-trace-xqjv (design Q) — re-confirmed run 2026-06-03-06 (cold probe) |
| AX-023 | 2026-06-03-06 | tool/error | `market.bind` adapter path (`bound_via=adapter`) created only the `markets` row, not the compatibility `instruments` row, so `forecast.add`/`decision.add` on the freshly-returned `market_id` failed `NOT_FOUND "instrument_id not found"` until a `snapshot.fetch` lazily materialized it (`_ensure_market_instrument`). Misleading error + contradicts the bind docstring's "prerequisite for forecast.add" promise. Manual path already did this via `_ensure_market_bind_prerequisites`. | fixed | 9b05e73 (+regression test; reverted-test confirms repro) |
| AX-024 | 2026-06-03-06 | tool | `memory.recall` BM25/FTS5 multi-word queries are conjunctive (implicit AND): every token must co-occur in one node or BM25 yields nothing; dotted/underscored tokens split oddly (`NOT_FOUND`→`not_found`). Fused mode masks it (temporal/graph still return results), so natural-language recall silently degrades to recency-only; LIKE fallback only fires on malformed MATCH, never on a valid zero-result query. Verified live (bm25-only: `bitcoin`✓, `snapshot`✓, `forecast.add instrument_id not found market.bind`→0, `instrument snapshot ordering trap`→0). | filed | trade-trace-95ry (P2) |
