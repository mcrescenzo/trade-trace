# Risk Units and R-Multiple Analytics (P1 Design)

> Status: **partial — see §3 for the shipped subset**. Migration 004 ships the nullable column stubs; the full P1 R-multiple analytic surface in §4+ is design.

Status: P1 design draft. Date: 2026-05-18.

Companion docs: [PRD.md](../PRD.md), [scoring.md](scoring.md),
[reports.md](reports.md), [opportunity-analysis.md](opportunity-analysis.md).

## 1. Purpose

This doc designs the P1 risk-unit / R-multiple substrate. Risk-unit
fields are **not** in MVP — MVP scores forecasts via Brier and reports
basic P&L. The design is captured here so MVP schemas don't accidentally
preclude P1, and so dogfooders know what's coming.

The borrowed pattern (from Tradervue's "R reporting"): every trade
declares an initial-risk budget; analytics normalize P&L into units of
that risk so size-noise doesn't dominate process signals. For an agent,
the same fields also let calibration analysis distinguish "process
error within budget" from "blew through the stop."

This doc resists scope creep toward broker-account semantics. Risk
fields are declared by the agent on the thesis and decision, never
inferred from execution data fetched externally.

## 2. Concept

For each decision with a position:

- `R` = the initial dollar risk the agent declared at thesis time
  (`declared_risk_amount`).
- `R-multiple` = realized P&L ÷ R.

Example: agent declares R = $100 risk on a trade; trade closes at
+$250 P&L; R-multiple = +2.5R. A second trade with R = $1,000 and P&L
+$250 is +0.25R. Same dollar P&L, very different process signal.

Skips and watches also carry R context (the avoided risk): a `skip`
with declared R = $500 and a hypothetical "if I'd entered" outcome of
-$400 surfaces as a `+0.8R good_skip`.

## 3. Schema Additions

### 3.1 On `theses`

- `risk_unit_label` (text, optional) — human-readable risk unit name
  (e.g. `"1% NAV"`, `"$500"`, `"1pt SPY notional"`). Pure metadata; no
  computation.
- `max_loss_budget` (real, optional) — the declared R amount in the
  thesis's currency, BEFORE the decision is taken. This is the
  "stop-loss in dollars" at the thesis grain.
- `invalidation_condition` (text, optional) — free-text statement of
  the condition that invalidates the thesis. Distinct from
  `falsification_criteria` (which is "what evidence would change my
  mind"): `invalidation_condition` is the **machine-checkable shorthand**
  the agent would use when a snapshot crosses a level (e.g. `"price <
  0.32"` or `"spread > 8%"`). MVP keeps it as free text; P1+
  machine-checkable predicates are a separate ratchet.

`falsification_criteria` remains in MVP and is the broader concept.
`invalidation_condition` is the narrow, tight, computable shadow.

### 3.2 On `decisions`

- `declared_risk_amount` (real, optional) — R declared at decision
  time, in the decision's currency. May differ from
  `thesis.max_loss_budget` if the agent sized the position to a
  fraction of the thesis budget; the decision field is authoritative.
- `declared_risk_unit` (text, optional) — currency or unit label
  consistent with `thesis.risk_unit_label`.
- `expected_edge` (real, optional) — agent's pre-decision estimate of
  the trade's expected P&L in `declared_risk_amount` units (i.e. in
  R). Lets P1 reports compare expected vs realized R.
- `expected_edge_after_costs` (real, optional) — `expected_edge` minus
  declared `fees` and `slippage`. The honest version of expected R.
- `cost_basis_estimate` (real, optional) — pre-decision estimate of
  realized cost basis after fees/slippage.
- `risk_reward_estimate` (real, optional) — declared R:R at decision
  time. Stored for retrospective sanity-checking.

For decision types where these don't apply (`watch`, `review`,
`invalidate_thesis`, `update_thesis`, `hold`, `resolved`) the fields
are optional and forbidden-when-set is NOT enforced (writer can record
hypothetical R on a `skip` to power "good_skip" analysis).

### 3.3 On `position_events`

- `initial_risk_amount` (real, optional) — frozen at the `open` event
  and carried on subsequent `add`/`reduce`/`close` rows for that
  position. Lets the projection compute live R-multiple without
  re-deriving from `decisions`.
- `realized_r_multiple` (real, optional) — computed at `close` event
  time as `(realized_pnl - fees - slippage) / initial_risk_amount`.
  Stored to avoid divide-by-zero handling at report time.
- `unrealized_r_multiple` (real, optional) — recomputed at each `mark`
  event using the latest snapshot.

### 3.4 On `positions` (projection)

- `initial_risk_amount`, `realized_r_multiple`, `unrealized_r_multiple`
  mirror the latest `position_events` values for query convenience.

### 3.5 Validation rules

- `declared_risk_amount >= 0`; `0` is allowed (no-risk trade, e.g. a
  paper trade tracked for calibration only).
- `realized_r_multiple` is computable iff `initial_risk_amount > 0`. If
  `initial_risk_amount = 0` (or missing), `realized_r_multiple` is
  `NULL` and reports filter those rows out with a `caveat` count.
- `expected_edge_after_costs <= expected_edge + 1e-9` (allows for
  floating-point slop); otherwise `VALIDATION_ERROR` with
  `details.field = "expected_edge_after_costs"`.

## 4. Reports

### 4.1 `report.risk`

Aggregate R-normalized performance over scored, closed positions
matching the filter.

Per-group metrics:

- `mean_r` — average `realized_r_multiple`.
- `median_r` — median `realized_r_multiple`.
- `r_distribution` — histogram bins (default `[-Inf, -2, -1, -0.5, 0,
  0.5, 1, 2, +Inf]`).
- `win_rate_r` — fraction of trades with `realized_r_multiple > 0`.
- `payoff_ratio_r` — `mean(r | r > 0) / |mean(r | r < 0)|`.
- `expectancy_r` — `mean(r)` (the field-standard expectancy formula
  collapses to mean R when win-rate × avg-win is summed with loss-rate
  × avg-loss).
- `coverage` — `(positions_with_R / positions_in_filter)`. If below
  `0.5`, the report flags the metrics as low-coverage and adds a caveat.

Sample-size minimum: 10 closed positions with R per group (configurable
per [reports.md](reports.md) §3.2).

### 4.2 `report.r_multiple` (alternative entry point)

Same metrics as `report.risk` but oriented for a single-group drill-down
of the actual R-multiple distribution. Useful when the agent has
spotted a worst group in `report.compare` and wants the distribution.

### 4.3 `report.calibration` interactions

`report.calibration` (per [scoring.md](scoring.md) §7) does **not**
weight by R. Calibration is a probability-vs-outcome metric and stays
clean. A separate `report.calibration_by_r_bucket` (P1+) can answer
"are my big-R bets better-calibrated than my small-R bets?" by binning
on `decisions.declared_risk_amount` and running calibration per bin.

### 4.4 `report.compare` interactions

`group_by = decisions.declared_risk_amount` becomes meaningful once R
is captured; `report.compare(base_report=risk, group_by=strategy_id)`
is the natural "which strategy has best R" view.

## 5. Skips, Watches, and Hypothetical R

For `skip` and `watch` decisions, R is the **avoided** risk. The agent
declares `declared_risk_amount` representing the size they considered.
When an outcome later resolves on the relevant instrument, a
`hypothetical_r_multiple` can be computed as
`(price_at_resolution - price_at_skip) * declared_quantity /
declared_risk_amount`, with sign flipped per `decisions.side`.

This powers two derived signals (both in `report.opportunity` per
[opportunity-analysis.md](opportunity-analysis.md), not in
`report.risk`):

- `good_skip` — skip where hypothetical R is negative below a
  configurable threshold (default `-0.3R`).
- `missed_positive_edge` — skip where hypothetical R is positive above
  a configurable threshold (default `+0.5R`).

The thresholds are configurable; the labels are deterministic given
the thresholds.

## 6. Boundaries and Risks

- **R does not imply broker realism.** A declared R is the agent's
  pre-commitment. Realized R uses recorded fills (per `position_events`
  and `decisions.fees`/`slippage`). The system never reconciles R
  against an external broker; the agent is on the honor system.
- **Missing R is not failure.** Reports gracefully skip rows without R
  and report `coverage` in the response. The system never extrapolates
  R or invents a default.
- **R is opt-in.** A P1 dogfooder who doesn't want R-flavored analytics
  simply leaves the fields unset. MVP behavior is unchanged. The
  schema additions are nullable; migrations are non-breaking
  (per [operability.md](operability.md) §4.3-4.4).
- **R is not a recommendation.** `report.risk` reports *what happened*;
  it never says "increase R" or "this strategy should be sized larger."

## 7. Open Questions

1. **Currency normalization.** When a single agent trades in multiple
   currencies, R values are in different units and cannot be averaged
   naively. P1 ships single-currency reports per filter; multi-currency
   aggregation requires a base-currency selection and conversion-rate
   capture, both deferred. The `decisions.declared_risk_unit` column
   is the hook.
2. **Time-decay of R.** Should an older R-multiple be discounted in
   aggregate reports the way memory nodes decay? Tradervue does not.
   MVP+P1 do not. Revisit if dogfood shows aged R values pollute the
   signal.
3. **Risk for option / multi-leg trades.** A single decision row maps
   1:1 to `declared_risk_amount` for a single-leg trade. Multi-leg
   trades (spreads, condors) currently roll up via the same R; per-leg
   risk accounting is a P2 candidate that depends on multi-leg
   modeling in `decisions`.
