# Paper-Loop Conventions

Versioned decisions the playbook applies every run. Changing anything here
is a methodology change: bump the run-summary `conventions_version` and note
it in the next run summary.

`conventions_version: 11`
(v11, 2026-07-13, run -11 review: exercise-trade selection made
deterministic and ex-ante — see the Exercise trades section. Selecting a
risk-compliant market+side BEFORE any verdict is compliance with the
owner's limits, not evasion; what remains forbidden is reshaping or
re-siding AFTER a fail verdict. Slippage arithmetic: (spread/2)/mid —
the higher-mid side of the same book always carries lower bps.)
(v10, 2026-07-13, run -10 review — two deviations RATIFIED + one fix:
(1) risk-first chain order: `risk.evaluate` → `risk.check_record` run
BEFORE `decision.add(paper_enter)`, because paper_enter opens a position
immediately (pre-fill) and a later risk fail would strand a phantom
position; a risk fail is journaled as `type=skip`, never paper_enter.
(2) `risk.check_record`'s consistency guard needs the SAME `snapshots`
object passed to `risk.evaluate` — reuse it verbatim. (3) exercise-trade
market selection changed from "cheaper side" to "the side priced nearest
0.50" — longshot sides structurally violate the 100 bps slippage cap
((spread/2)/mid); near-even sides with tight spreads pass. Substrate
design question filed for the pre-risk position-opening footgun.)
(v9, 2026-07-13, owner decisions (see CHARTER.md "Owner decisions —
recorded 2026-07-13"): exercise-trade convention added; settle sweep
tiered; standing-abstention carry-forward; fetch-class keys get a
per-attempt component.
v8, 2026-07-13, run -09 review: writes carry `--run-id`; `decision.add`
side is the outcome side (yes/no), never buy/sell — see Keys.
v7, 2026-07-13, trade-trace-6n4jp: fixed a v6 regression — when a
two-sided book anchors `price` to the book mid (AX-027), `price_source` now
names `"book_mid"` (what actually filled the column), not the pre-anchoring
chain field name. It only names the price → lastTradePrice → last → mid
chain field when no two-sided book was present. v6, 2026-07-13,
trade-trace-2j4r1: snapshot.fetch now records
`metadata_json.price_source` (names which field in the
price → lastTradePrice → last → mid chain supplied the value) and an
explicit `metadata_json.last_trade_price` (absent-not-fabricated); the
thin-book anchor rule below prefers `last_trade_price` when present. v5,
2026-07-13, run -04 review: thin-book anchor rule now names the field
that actually exists — the snapshot `price` column, which the adapter fills
via a `price → lastTradePrice → last → mid` chain; snapshot `bid`/`ask`
map from Gamma `bestBid`/`bestAsk`. Explicit last-trade provenance is
tracked as a bead. v4, 2026-07-13: the substrate now maps Gamma's `volume24hr` into
`snapshot.fetch`'s `metadata_json.volume_24h` (stored row:
`metadata_json.polymarket_snapshot.volume_24h`) — trade-trace-ismzy. The
liquidity check below prefers that true 24h figure, falling back to
cumulative `volume` for snapshots captured before this change. v3,
2026-07-13: forecasts must carry `resolution_rule_text` + `resolution_at`
— see playbook phase 4; thin-book price-anchor rule added below. v2,
2026-07-10: after run 2026-07-10-01, the liquidity-check volume field is
named honestly — the substrate exposes Gamma's cumulative `volume`, not
24h volume. Substrate follow-up tracked in beads labeled `paper-loop`.)

## Keys

- `RUN_ID` = `YYYY-MM-DD-NN` (UTC date + 2-digit sequence for the day).
- Every write: `idempotency_key = paper:<RUN_ID>:<purpose>[:<market_id>]`,
  e.g. `paper:2026-07-11-01:forecast:mkt_abc`.
- Evidence-family tools also take
  `semantic_key = paper:<RUN_ID>:<family>:<market_id>` (families: `intent`,
  `fill`, `account-snapshot`, `external-receipt`, `reconciliation`).
- `account_label = paper-loop`. `environment_label = paper`.
- Pass `--run-id <RUN_ID>` on forecast/decision/fill writes — journal
  provenance columns, not just the idempotency-key namespace (run
  2026-07-13-09 omitted it; append-only means no backfill).
- `decision.add` `side` is the OUTCOME side (`yes`/`no`, or
  `long`/`short`) — never `buy`/`sell`. SELL-YES exposure = `side=no`,
  BUY-YES = `side=yes`.
- Fetch-class tools (`snapshot.fetch`, `market.refresh`,
  `snapshot.fetch_series`, `outcome.fetch`) mint keys with a per-attempt
  component: `paper:<RUN_ID>:<purpose>:<market_id>:a<N>`. A same-key
  IDEMPOTENCY_CONFLICT means REUSE the first row — never treat a replay
  as a fresh price (owner decision, trade-trace-pzyvq).

## Settle sweep (v9: tiered)

Fresh-tier refresh every run: markets with `resolution_at` within 7 days,
`resolution_at = null`, or an open position. FULL sweep (every open
market) on runs where NN % 6 == 1 (runs -01, -07, -13, -19 of each UTC
day). Early resolutions outside the fresh tier are caught by the next
full sweep — bounded, self-healing latency; financial risk zero while
positions are flat.

## Standing abstentions (v9)

The run summary carries a "Standing abstentions" table: forecast id,
direction, edge, and the price at last derivation. Each run copies it
forward from the most recent prior summary and re-derives an entry ONLY
when |price_now − price_at_last_derivation| > 0.03, or when the market
enters its final 7 days. Otherwise carry the line forward verbatim with
a "standing" marker. New gate-clearing stale
edges enter the table via one full derivation first.

## Exercise trades (v9, owner-authorized 2026-07-13)

Purpose: continuously exercise the risk→intent→fill→receipt→reconcile→
settle chain with honest, labeled, minimum-size activity. NOT conviction
trading; the 0.05 conviction gate and abstention discipline are
untouched.

- At most ONE exercise trade per UTC day: before opening one, check the
  prior run summary and `pretrade_intent.list` for an
  `intent_type=exercise` intent today; skip if present.
- Size: $10–20 notional. Selection (v11, deterministic + ex-ante):
  compute, for every universe-passing market in this run's fresh
  snapshots and BOTH sides, the ex-ante slippage bps = (spread/2)/mid at
  the touch. Candidate set = pairs whose ex-ante arithmetic passes ALL
  policy limits (slippage ≤ 100 bps, spread ≤ $0.05, runway, notional).
  Pick the candidate with the highest 24h volume; direction = that pair's
  side (i.e. the lower-bps, higher-mid side of its book). If the set is
  EMPTY, attempt the least-failing candidate anyway and let the risk gate
  cancel it — the cancellation is the day's honest evidence. NEVER
  reshape or re-side after a fail verdict; the ex-ante selection is the
  only place side choice happens.
- Full chain, no shortcuts: `decision.add` (type=paper_enter, reason
  starts `exercise_trade:`), `risk.evaluate` → `risk.check_record` (ALL
  policy rules apply — supply full exposure inputs and links; a fail
  verdict CANCELS the exercise trade, journaled honestly),
  `pretrade_intent.record` with `proposed_shape.intent_type="exercise"`,
  `paper_fill.record` with `evidence_json.reason="exercise_trade"`,
  receipts + reconciliation per the standard procedure, settlement exit
  on resolution like any position.
- Exercise activity must never be described as conviction trading in
  summaries or memories; always label it.

## Fill model (v1: conservative touch-price, honest no_fill)

Inputs: a fresh snapshot (bid/ask/mid/volume) for the market, side,
requested quantity, risk policy caps.

1. Tradeable price: **buy → ask**, **sell → bid**. Never mid.
2. Liquidity check: requested notional (quantity × price) must be
   ≤ 5% of the snapshot's reported volume (USD). NOTE (v4): prefer the
   snapshot's `metadata_json.volume_24h` (Gamma's `volume24hr`, mapped in
   by trade-trace-ismzy) as the denominator — it is a true 24h figure.
   Fall back to the cumulative `volume` field only when `volume_24h` is
   null/absent (snapshots captured before this change); a fallback to
   cumulative volume still overstates recent liquidity, so let the
   policy's $0.05 max-spread rule do the real liquidity screening in that
   case (a stale book fails it). Fail → do NOT trade; if an intent was
   already recorded, record the fill attempt anyway and let it come back
   `fill_status=no_fill` — that is valid evidence.
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
  check (i.e. ≥ $4,000 reported volume — prefer 24h volume, falling back
  to cumulative volume per the v4 note above) AND a live book (spread
  within the policy's $0.05 cap).
- Edge: trade only when |forecast p − tradeable price| ≥ 0.05.
- Thin books (v3, field-corrected in v5, provenance added in v6,
  provenance labeling fixed in v7): when a book is near-empty (spread
  beyond the policy's $0.05 cap or trivial resting size), the midpoint is
  meaningless — do not reason from it or report it as "the price". Note a
  thin book still has both `bestBid`/`bestAsk` present, so the stored
  `price` is still the book mid and `metadata_json.price_source` still
  reads `"book_mid"` (trade-trace-6n4jp: `price_source` names what
  actually filled the `price` column, not a chain field, whenever a
  two-sided book exists — thin or not). When `metadata_json.last_trade_price`
  is present (trade-trace-2j4r1), it is the preferred anchor regardless of
  what `price_source` says. Fall back to the snapshot's **`price`
  field** (the adapter's venue-price/last-trade chain, or the book mid when
  a two-sided book is present) when `last_trade_price` is absent, with an
  explicit caveat in the rationale, and quote `bid`/`ask` (Gamma
  `bestBid`/`bestAsk`) alongside. Such markets fail the universe rule for
  trading regardless; this rule governs how their prices are *described*
  in forecasts and summaries.
- Size: notional = min($200, room under market/category/total exposure
  caps); quantity = notional / price.
- Every intent gets `risk.evaluate` → `risk.check_record` FIRST. A fail or
  missing_data verdict is recorded and journaled as an abstention
  (`decision.add` reason notes the abstention) — never resized to pass.
