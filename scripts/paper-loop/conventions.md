# Paper-Loop Conventions

Versioned decisions the playbook applies every run. Changing anything here
is a methodology change: bump the run-summary `conventions_version` and note
it in the next run summary.

`conventions_version: 3`
(v3, 2026-07-13: forecasts must carry `resolution_rule_text` +
`resolution_at` — see playbook phase 4; thin-book price-anchor rule added
below. v2, 2026-07-10: after run 2026-07-10-01, the liquidity-check volume
field is named honestly — the substrate exposes Gamma's cumulative
`volume`, not 24h volume. Substrate follow-up tracked in beads labeled
`paper-loop`.)

## Keys

- `RUN_ID` = `YYYY-MM-DD-NN` (UTC date + 2-digit sequence for the day).
- Every write: `idempotency_key = paper:<RUN_ID>:<purpose>[:<market_id>]`,
  e.g. `paper:2026-07-11-01:forecast:mkt_abc`.
- Evidence-family tools also take
  `semantic_key = paper:<RUN_ID>:<family>:<market_id>` (families: `intent`,
  `fill`, `account-snapshot`, `external-receipt`, `reconciliation`).
- `account_label = paper-loop`. `environment_label = paper`.

## Fill model (v1: conservative touch-price, honest no_fill)

Inputs: a fresh snapshot (bid/ask/mid/volume) for the market, side,
requested quantity, risk policy caps.

1. Tradeable price: **buy → ask**, **sell → bid**. Never mid.
2. Liquidity check: requested notional (quantity × price) must be
   ≤ 5% of the snapshot's reported volume (USD). NOTE (v2): the substrate
   exposes Gamma's CUMULATIVE market volume — the only volume field
   available — which overstates recent liquidity. Until the substrate
   exposes true 24h volume, treat the volume floor as necessary-but-weak
   and let the policy's $0.05 max-spread rule do the real liquidity
   screening (a stale book fails it). Fail → do NOT trade; if an intent
   was already recorded, record the fill attempt anyway and let it come
   back `fill_status=no_fill` — that is valid evidence.
3. `paper_fill.record` args: `book_levels=[{"price": <touch>, "quantity":
   <requested>}]`, `limit_price=<touch>`, `reference_mid_price=<mid>`,
   `slippage_cap_bps=100`, `snapshot_id` + `snapshot_as_of` from the
   snapshot actually used, `order_as_of=<now>`,
   `max_snapshot_age_seconds=900` (the snapshot must come from THIS run).
4. Never fabricate depth, never widen the level to force a fill. `partial`
   and `no_fill` results are recorded as-is.

## Settlement exits (the one exception)

When a market resolves while we hold a position: `decision.add(paper_exit)`
then `paper_fill.record` with a single book level at the resolution value
(winning side → price 1.0, losing side → 0.0), no liquidity check,
`evidence_json.reason = "settlement_exit"`. Settlement is not a market
order.

## Reconciliation ("external truth" = derived-from-venue-data)

Once per run, after fills and settlements:

1. `account_snapshot.import`: positions from `report.current_exposure`
   (each as decimal strings), balances derived as
   `available = bankroll_usd − Σ open cost basis + Σ realized proceeds − fees`
   (all from `report.paper_exposure`), `source_system =
   "paper-loop-derived"`, `source_run_id = <RUN_ID>`,
   `confidence_label = "high"`, `staleness_status = "fresh"`,
   `venue_label = "polymarket"`, marked-to-market at THIS run's snapshots.
2. `external_receipt.import` for each fill recorded this run:
   `lifecycle_state = "filled"` (or `"rejected"` for no_fill),
   `external_event_type = "fill"`, `pretrade_intent_id` linked,
   `sanitized_facts` mirroring the fill's quantities/price/fees as decimal
   strings.
3. `reconciliation.record` (semantic_key per above) →
   `report.reconciliation_mismatches`. Any non-empty mismatch_codes set is
   investigated in-run and explained in the run summary; a mismatch that
   recurs across 2+ runs becomes a bead.

This is NOT broker truth (the report caveat flags say exactly this); it is
a drift-detector for the local ledger and the source of
`reconciliation_cleanliness` evidence.

## Trading rule

- Universe: binary Polymarket markets, resolving in > 6 hours and
  ≤ 90 days, with enough reported volume that a $200 intent passes the 5%
  check (i.e. ≥ $4,000 reported volume — cumulative, per the v2 note
  above) AND a live book (spread within the policy's $0.05 cap).
- Edge: trade only when |forecast p − tradeable price| ≥ 0.05.
- Thin books (v3): when a book is near-empty (spread beyond the policy's
  $0.05 cap or trivial resting size), the midpoint is meaningless — do
  not reason from it or report it as "the price"; anchor to
  `lastTradePrice` with an explicit caveat in the rationale. Such markets
  fail the universe rule for trading regardless; this rule governs how
  their prices are *described* in forecasts and summaries.
- Size: notional = min($200, room under market/category/total exposure
  caps); quantity = notional / price.
- Every intent gets `risk.evaluate` → `risk.check_record` FIRST. A fail or
  missing_data verdict is recorded and journaled as an abstention
  (`decision.add` reason notes the abstention) — never resized to pass.
