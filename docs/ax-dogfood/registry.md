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
| AX-013 | 2026-06-03-02 | report | skip/watch/hold decisions can't link `forecast_id`, so report.coach flags a forecasted-but-skipped market as unforecasted | filed | trade-trace-t9n5 (design Q) |
