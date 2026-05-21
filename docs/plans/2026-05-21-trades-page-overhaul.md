# Trades Page Overhaul Plan

**Date:** 2026-05-21  
**Status:** revised implementation plan; Beads program materialized under `trade-trace-hbqs`  
**Primary Beads label:** `trades-page-overhaul`  
**Scope:** Console `/trades` route, the existing `/api/console/trades` decision-event endpoint, a new `/api/console/positions` position-list endpoint, and the existing `/api/console/positions/{position_id}` detail endpoint.

---

## 1. Readiness verdict

This overhaul is implementation-ready **as a contract-first Beads program**, not as a one-shot frontend task.

The previous sketch correctly identified the UX problem, but it was not implementation-ready because it blurred three things the codebase keeps separate:

1. **Trade decision rows** — the existing `/api/console/trades` endpoint returns trade-typed decisions (`paper_enter`, `actual_exit`, `add`, `reduce`, etc.).
2. **Position lifecycle rows** — the human-friendly default view should be one row per position/round-trip lifecycle, backed by the `positions` projection plus event lineage.
3. **Position detail** — the current detail read model carries lifecycle metrics and events, but not enough linked strategy/thesis/source/tag/caveat metadata for the proposed card without frontend N+1 calls.

The revised plan locks those boundaries before implementation:

- Keep `/trades` as the **human-facing route**.
- Default `/trades` to **position rows** from a new `/api/console/positions` endpoint.
- Preserve `/trades?view=events` as the **decision-event escape hatch** backed by existing `/api/console/trades`.
- Do **not** redefine `/api/console/trades` or architecture docs to mean positions.
- Put caveat label/copy/severity in backend read models using the existing `CAVEAT_GLOSSARY`; do not add a new `error` severity in this pass.
- Fix filter serialization so arrays are preserved rather than silently truncated.

---

## 2. Current code facts this plan relies on

| Fact | Evidence |
| --- | --- |
| Current Trades page renders flat decision rows. | `frontend/console/src/main.tsx` `TradesPage` uses `endpoint="/api/console/trades"` and columns `decision_id`, `decision_type`, `instrument`, `side`, `quantity`, `price`, `caveats`. |
| Existing `/api/console/trades` is a decision-event list endpoint. | `src/trade_trace/console/serve.py` binds `/api/console/trades` to `list_trades(...)` with `strategy_id`, `instrument_id`, and scalar `decision_type`. |
| There is no positions list endpoint. | `serve.py` exposes `/api/console/positions/{position_id}` only. |
| Current `PositionDetail` is useful but not sufficient for the proposed card. | `src/trade_trace/console/reporting/position_rows.py` includes lifecycle metrics/events and opening IDs, but not strategy slug/name, thesis snippets, full source/tag summaries, or caveat metadata objects. |
| Frontend filter helpers currently lose array values. | `tableFilterParams` in `frontend/console/src/main.tsx` returns `instrument_id?.[0]` and `decision_type?.[0]`; `pageQuery` in `frontend/console/src/api.ts` serializes only scalar values. |
| Caveat severity already exists and is constrained. | `CAVEAT_GLOSSARY` in `metric_glossary.py` uses `info` / `warning`; `tests/contracts/test_metric_glossary.py` asserts that supported set. |
| Position table has no quantity column. | `positions` migration has status/prices/P&L/risk fields; size/net quantity must be derived from `position_events.quantity_delta`. |

---

## 3. Product goal

Make the page answer the human question:

> “What trades have I journaled, what is open or closed, and how did they turn out?”

without losing the audit-grade decision/event trail underneath.

The default scan should read like position lifecycle stories:

```text
2026-05-19 09:32  AAPL   Long 100 @ $182.40   Closed @ $185.10   +$270 (+1.5R)   breakout-pullback   Hygiene 5/6
2026-05-18 14:15  MSFT   Paper short 1 @ 0.55 Open (1 add)        no current mark  —                   Hygiene 4/6
```

The event-level audit view remains available:

```text
/trades?view=events
```

---

## 4. Non-negotiable boundaries

- Read-only Console remains read-only: no journal writes, broker calls, market-data fetches, cloud sync, or public/network actions.
- No frontend-only financial math. P&L, R-multiple, status, size/event rollups, caveats, and missing-data semantics come from backend read models.
- No schema migration in this program unless a later implementation bead proves one is necessary and creates a separate design/migration bead.
- Do not remove raw/audit access; demote it visually.
- Do not redefine architecture terminology: trade-typed **decisions** remain decision/event records; **positions** are rebuildable lifecycle projections.

---

## 5. Backend API contracts

### 5.1 Existing endpoint remains decision-event oriented

`GET /api/console/trades`

Purpose: flat audit list of trade-typed decisions.

Required changes:

- Keep existing row semantics.
- Add `decision_at_from` / `decision_at_to` filters.
- Change `decision_type` from scalar-only to array-capable query parsing.
- Preserve pagination/cursor contract.

Array encoding default:

```text
/api/console/trades?decision_type=paper_enter&decision_type=add
```

Do not silently truncate arrays to the first item.

### 5.2 New position list endpoint

`GET /api/console/positions`

Purpose: default `/trades` scan view — one row per position lifecycle.

Filters:

| Param | Type | Notes |
| --- | --- | --- |
| `cursor` | string? | Same cursor/Page helper pattern as current list endpoints. |
| `limit` | int | Default 50. |
| `status` | repeated string? | Supports position statuses from schema (`open`, `partial`, `closed`, `resolved`, `expired`, `assigned`, `voided`); UI may expose a smaller grouped set. |
| `kind` | repeated string? | `paper`, `actual`, `simulation`. |
| `instrument_id` | repeated string? | Even if v1 UI selects one instrument, API should not force lossy truncation. |
| `strategy_id` | string? / repeated if implementation chooses | Must be explicit in tests; no silent first-value behavior. |
| `opened_from` / `opened_to` | ISO timestamp? | Date range for position opened_at. |
| `outcome` | string? | UI-level categories such as `winning`, `losing`, `flat`, `open`; backend owns the mapping. |

`PositionRow` should include enough to render the scan without extra row-level calls:

```text
position_id
instrument_id
instrument_symbol
instrument_title
venue_id
venue_kind
kind
side
status
opened_at
closed_at
updated_at
net_quantity              # derived from position_events
avg_entry_price
realized_pnl
unrealized_pnl
initial_risk_amount
realized_r_multiple
unrealized_r_multiple
opening_decision_id
opening_strategy_id
opening_strategy_slug
opening_strategy_name
add_count
reduce_count
event_count
caveats                  # machine codes
caveat_entries           # code, label, summary, severity from CAVEAT_GLOSSARY
```

### 5.3 Enriched position detail endpoint

`GET /api/console/positions/{position_id}` already exists. Extend its read model so one response can render the detail card.

Add bounded fields; do not fetch unbounded source bodies:

```text
strategy_slug / strategy_name
opening_thesis_id
opening_thesis_title/snippet
source_summaries[]       # id/kind/title/url-or-label/stance if available
tag_summaries[]
risk_rollup              # declared risk, fees/slippage rollup, R multiples
events[]                 # current PositionEvent lineage
caveat_entries[]         # same glossary-backed objects as list rows
raw/debug payload         # preserved for audit, rendered under <details>
```

Frontend must not reconstruct this card by calling multiple endpoints per row.

---

## 6. Frontend behavior

### 6.1 `/trades` default: positions view

Default columns:

| Column | Behavior |
| --- | --- |
| When | Relative time plus absolute timestamp on hover/title. |
| Instrument | Symbol first; title + venue badge secondary; fixture/demo banner if rows look synthetic. |
| Side | Human chips for `long`, `short`, binary `yes`/`no`, etc. |
| Size / Entry | Backend-derived net size and average entry; show units honestly when unknown. |
| Status / Outcome | Open/partial/closed/resolved/etc.; realized/unrealized P&L and R when supplied. |
| Strategy | Slug/name badge when available; neutral empty state otherwise. |
| Hygiene | Compact meter using caveat entries. |
| IDs | Copyable IDs on hover/detail, not the primary leftmost scan column. |

### 6.2 `/trades?view=events`: decision-event audit view

Keep the existing decision list but humanize it:

- Add `decision_at` column.
- Render decision enums as plain labels (`Enter • Paper`, `Exit • Actual`, `Scale-in`, `Scale-out`).
- Keep decision IDs copyable.
- Keep raw record/event detail accessible.
- State clearly that these rows are journal decisions, not grouped position outcomes.

### 6.3 Filters

Fix query serialization first, then build UI controls.

- Array values must round-trip through URL state, `tableFilterParams`, `pageQuery`, and FastAPI parsing.
- Prefer repeated query params for table endpoints.
- Date range filters use explicit from/to params.
- Use existing `/api/console/instruments` and `/api/console/strategies` as picker sources when practical.
- Segmented UI labels (`All / Real / Paper`, `Entries / Exits / Scale-ins / Scale-outs`) map to backend decision-type arrays for event view and kind/status/outcome filters for positions view.

### 6.4 Detail card

Position-row expansion should show:

1. Timeline strip of `PositionEvent`s.
2. Thesis snippet and link/copyable ID.
3. Source/tag chips.
4. Risk/P&L panel: declared risk, realized/unrealized R, fees, slippage.
5. Caveat explanations from backend `caveat_entries`.
6. Raw JSON/debug detail under a collapsed `<details>` block.

### 6.5 Hygiene and onboarding

- Render `info` caveats as neutral hygiene items.
- Reserve warning chrome for backend `warning` caveats such as missing price/quantity/open mark.
- Top copy should say plain-English facts, not implementation jargon.
- Demo-data banner may use fixture-name heuristic (`FixtureInst-*`, `RichInst-*`) in this pass; it must not imply broker/live data.
- KPI strip is current-page scoped unless backend totals are explicitly supplied.

---

## 7. Implementation sequence

1. Lock contract and docs language.
2. Add `/api/console/positions` and enriched position detail fields.
3. Fix frontend/backend array/date/view-mode filter handling.
4. Implement default position-first table.
5. Preserve/humanize decision-event view.
6. Implement detail card.
7. Add hygiene/onboarding/demo/polish.
8. Run backend/frontend contract tests.
9. Run browser QA for default view, event view, detail expansion, empty/demo states, responsive/contrast sanity.
10. Update docs.
11. Product/architecture review gate.
12. Final verification.

---

## 8. Beads program

Root epic: `trade-trace-hbqs` — `[EPIC] Trades page overhaul: position-first human-readable Console`

This epic is the narrative/root index, not the executable starting task. Task dependencies and gates are authoritative; labels are an index only.

Canonical query:

```bash
bd list --label trades-page-overhaul --status open --flat --limit 0 --sort id
bd graph trade-trace-hbqs
```

### Node map

| Temp role | Bead ID | Title |
| --- | --- | --- |
| Contract lock | `trade-trace-wf4g` | Lock Trades page route, API, filter, and caveat contracts |
| Backend positions list | `trade-trace-498b` | Implement `/api/console/positions` list read model and endpoint |
| Backend detail enrichment | `trade-trace-c5xs` | Enrich position detail read model for trade detail cards |
| Filter/query foundation | `trade-trace-wyxn` | Fix Console table filter state for arrays, date ranges, and view mode |
| Default positions view | `trade-trace-uh0o` | Implement position-first Trades page table |
| Event escape hatch | `trade-trace-na9e` | Preserve and humanize the decision-event escape hatch |
| Detail card | `trade-trace-lpy0` | Implement human-readable position detail card |
| Hygiene/polish | `trade-trace-5r3m` | Add hygiene meter, onboarding strip, demo banner, and visual polish |
| Backend contract QC | `trade-trace-r78x` | Test Trades page backend contracts and filter semantics |
| Frontend QC | `trade-trace-gx8o` | Test Trades page frontend behavior |
| Browser QA | `trade-trace-hju0` | Browser QA the redesigned Trades page |
| Docs QC | `trade-trace-5ugx` | Update docs and architecture truthfulness for Trades page overhaul |
| Review gate | `trade-trace-u6do` | Product/architecture review gate for Trades page overhaul |
| Final gate | `trade-trace-g09k` | Final verification for Trades page overhaul |

Expected first executable leaf:

```bash
bd show trade-trace-wf4g
```

Close rule: close `trade-trace-g09k` first, then close `trade-trace-hbqs` only after material beads are closed, explicitly deferred, or superseded with notes.

---

## 9. Verification already performed for planning/materialization

Planning checks run before materialization:

```bash
python3 ~/.hermes/skills/software-development/beads-program-planning/scripts/beads_plan_lint.py /tmp/trades-page-overhaul.graphspec.json --repo /home/hermes/code/trade-trace
python3 ~/.hermes/skills/software-development/beads-program-planning/scripts/graphspec_cycle_check.py /tmp/trades-page-overhaul.graphspec.json
```

Result: graph lint had 0 blockers; cycle check reported no cycles/unknown dependencies.

Post-materialization checks:

```bash
python3 ~/.hermes/skills/software-development/beads-program-planning/scripts/beads_materialize_verify.py /tmp/trades-page-overhaul.graphspec.json /tmp/trades-page-overhaul.mapping.json
bd dep cycles
bd dep list trade-trace-hbqs
bd dep list trade-trace-g09k
bd ready --label trades-page-overhaul
bd lint
bd orphans
```

Result: materialization verify reported 0 mismatches and 0 description warnings; Beads had no dependency cycles, no lint warnings, and no orphaned issues. `bd ready --label trades-page-overhaul` exposes `trade-trace-wf4g` plus the root epic as ready; the epic is intentionally a non-executable narrative root.
