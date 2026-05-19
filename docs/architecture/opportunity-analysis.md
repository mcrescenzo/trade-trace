# Path-Dependent Opportunity Analysis (P1 Design)

Status: P1 design draft. Date: 2026-05-18.

Companion docs: [PRD.md](../PRD.md), [reports.md](reports.md),
[risk-units.md](risk-units.md), [scoring.md](scoring.md).

## 1. Purpose

`report.opportunity` analyzes the **path** between a decision and its
outcome — what the agent could have done if it had perfect timing —
using the snapshot series the agent already supplied. This is the
adapter for Tradervue's MFE/MAE/Exit-Efficiency concepts, with two
non-negotiable constraints:

1. **Trade Trace never fetches price data.** The analysis runs on
   externally-supplied snapshots (PRD §2.4). If a decision's instrument
   has no snapshot series after the decision, the metric is `NULL` and
   the row reports `data_coverage = "missing"`.
2. **Process diagnostics, not recommendations.** The labels — `good_skip`,
   `missed_positive_edge`, `right_thesis_wrong_timing`,
   `bad_process_good_outcome`, `good_process_bad_outcome` — describe
   *what happened*, never *what to do*.

This is **P1 design**. MVP captures snapshots and decisions; the
analysis tool lands later. The snapshot schema is already adequate.

## 2. Prerequisites (from MVP)

The MVP `snapshots` table (PRD §3.1) supplies the substrate:

- `instrument_id`, `captured_at`, `price`, `bid`, `ask`, `mid`,
  `spread`, `volume`, `implied_probability`, `liquidity_depth_json`.
- Ordering: rows are queried by `(instrument_id, captured_at ASC)`.
- Source: free-form string; the importer sets `source = "manual"` or
  the importer's name. Trade Trace does not interpret source values;
  reports may filter by them.

Decisions reference snapshots via `decisions.snapshot_id` (the
"as-of" snapshot at decision time). Path analysis walks
`captured_at > decisions.created_at` for the same instrument.

## 3. Path Metrics

For a closed or pending position with snapshot series `S_1, S_2, ...,
S_N` after `decision.created_at`, and a thesis horizon
`H = decision.thesis.time_horizon_at` (default to
`forecast.resolution_at` if thesis lacks one):

| Metric | Definition |
|---|---|
| `max_favorable_move` | max profit-direction price travel between decision and `min(H, last_snapshot)`, expressed as both raw price delta AND fraction of declared R when R is set. |
| `max_adverse_move` | analog for adverse direction. |
| `path_best_exit_value` | best realized P&L the position could have achieved under declared exit constraints (`exit_triggers`, `invalidation_condition`). |
| `path_worst_drawdown` | worst drawdown from peak during the holding window. |
| `edge_peak` | max favorable edge (mid-price minus snapshot bid/ask at the time) — meaningful when liquidity is captured. |
| `invalidation_hit_at` | first `captured_at` where a machine-checkable invalidation condition was met. NULL if invalidation_condition is free-text or never tripped. |
| `exit_efficiency` | `realized_pnl / path_best_exit_value` when both are positive; `NULL` when path_best_exit_value <= 0. |

Side handling:

- `side = long`: favorable = price up; adverse = price down.
- `side = short`: favorable = price down; adverse = price up.
- `side = yes`: favorable = implied_probability or price up.
- `side = no`: favorable = implied_probability or price down.
- `side = flat_neutral`: path metrics are NULL (no directional signal).
- `side = pairs_long_short`: composite handling deferred to P2.

Each metric carries `data_coverage`:

- `complete` — snapshots cover decision_at through min(H, now) with
  no gap >25% of the window.
- `partial` — coverage 50-75%.
- `sparse` — coverage <50%.
- `missing` — no post-decision snapshots.

Reports never compute metrics on `missing` rows. `sparse` rows carry
a caveat. The thresholds are constants in MVP-P1; configurable in P2.

## 4. Classification Labels

Path metrics combine with the realized outcome to produce categorical
labels — useful in `report.mistakes`/`strengths` and in `report.coach`:

| Label | Rule |
|---|---|
| `missed_positive_edge` | decision was `skip`/`watch` AND `max_favorable_move >= missed_positive_threshold` (default = +0.5R or +5% price, whichever is more conservative for the asset class) AND no invalidation hit. |
| `good_skip` | decision was `skip`/`watch` AND `max_adverse_move >= good_skip_threshold` (default = -0.3R or -3% price) OR `invalidation_hit_at` is non-NULL. |
| `right_thesis_wrong_timing` | decision entered a position, `max_adverse_move` violated declared R before resolution, but the final outcome aligned with thesis direction. |
| `bad_process_good_outcome` | outcome was favorable but `decision_playbook_rules.status = "overridden"` exists with `status != "considered"`, OR `invalidation_hit_at` is set and was ignored. |
| `good_process_bad_outcome` | outcome was adverse, but no `overridden` rule and no `invalidation_hit_at`. The agent followed the playbook; the market won. |

Labels are mutually-not-exclusive — a single decision can carry both
`right_thesis_wrong_timing` and `good_process_bad_outcome`. They are
stored on `report.opportunity`'s response, not on the `decisions` row
itself (the labels are derived; the source data on the row is the
ground truth).

## 5. `report.opportunity`

```jsonc
{
  "tool": "report.opportunity",
  "args": {
    "filter": { /* ReportFilter */ },
    "horizon": "thesis_horizon",          // "thesis_horizon" | "forecast_resolution" | {"days": 30}
    "direction_source": "thesis_side",    // "thesis_side" | "decision_side" | "forecast_yes_label"
    "minimum_coverage": "partial",        // "complete" | "partial" | "sparse"; rows below this are excluded
    "max_records": 100,
    "include_labels": true                // when false, returns metrics only
  }
}
```

Response groups by `classification_label` by default; `group_by` can be
overridden to any field allowed by `report.compare`.

Per-group metrics: count, mean R (when available),
`mean_max_favorable_move_r`, `mean_max_adverse_move_r`,
`mean_exit_efficiency`, `invalidation_hit_rate`. Sample-size minimum
20 per group (configurable).

Drill-down per [reports.md](reports.md) §3 is mandatory: every group
links back to its decisions and snapshot ranges.

## 6. What This Is NOT

- **Not a backtester.** Trade Trace replays decisions against snapshots
  the agent already provided. It does not synthesize prices, replay
  historical fills, or extend snapshot series.
- **Not a market simulator.** The "best exit" is computed against the
  prices that actually occurred in the supplied snapshots, not against
  a counterfactual market.
- **Not a recommendation engine.** Labels describe historical process;
  the report never says "you should have exited at X" or "skip this
  setup next time."
- **Not real-time.** All metrics are retrospective. No streaming, no
  live snapshot ingestion, no alerts.

## 7. Snapshot-Series Conventions

For `report.opportunity` to compute reliably:

- Snapshots should be captured at meaningful intervals — at minimum, at
  decision time and at outcome time. Denser sampling (intraday for
  equities, every-N-minutes for prediction markets) improves the
  `data_coverage` rating.
- Snapshots are append-only; duplicate `(instrument_id, captured_at)`
  rows are tolerated but flagged: the latest-written wins for path
  computation, and the report's response includes a
  `duplicate_snapshot_count` caveat.
- Snapshots carry `metadata_json.regime_tag` if the agent wants
  regime-aware analysis; `report.compare(group_by=market_regime_tag)`
  picks it up via the `ReportFilter.market_context.market_regime_tag`
  field.

## 8. Synthetic Fixtures (for tests)

The P1 test suite ships synthetic snapshot-series fixtures covering:

- Favorable move after skip → `missed_positive_edge`.
- Adverse move before final win → `right_thesis_wrong_timing`.
- Exit too early → `exit_efficiency < 0.5`.
- Invalidation hit before resolution → `invalidation_hit_at` populated.
- Missing snapshots → `data_coverage = "missing"`, metric NULL.
- Wide spread makes apparent edge unusable → `edge_peak < spread`,
  surfaces as a caveat in `report.opportunity` response.

## 9. Boundaries vs Risk Units

`risk-units.md` and `opportunity-analysis.md` complement each other:

- Risk-units provides the **denominator** for R-normalized metrics.
- Opportunity analysis provides the **path** the trade actually took.

When R is missing (per [risk-units.md](risk-units.md) §3.5), opportunity
metrics fall back to absolute price units (price delta, raw P&L). The
report response makes the unit explicit:

```jsonc
{"max_favorable_move": {"value": 0.04, "unit": "price"}}
// vs
{"max_favorable_move": {"value": 1.6, "unit": "R", "r_amount": 100.0}}
```

## 10. Open Questions

1. **Best-exit definition under thesis-declared exits.** §3's
   `path_best_exit_value` uses declared `exit_triggers` when present;
   absent them, it uses the literal best snapshot-price. Edge case:
   should an agent's *trailing* stop concept (move stop up as price
   moves) be modeled? P2; needs a structured stop-evolution schema.
2. **Resolution time vs horizon time.** Some forecasts resolve before
   their thesis horizon; some after. §3 uses `min(H, last_snapshot)` —
   meaning resolved forecasts use up to resolution, not beyond.
   Document the edge case in the report response.
3. **Snapshot-source quality scoring.** The `snapshots.source` field is
   free-form. If dogfood shows mixed-quality sources (e.g. one
   high-fidelity feed and one occasional manual entry), a per-source
   confidence weight could enter path metrics. P2.
4. **Liquidity-aware path metrics.** `edge_peak` minus best-available
   bid/ask captures the actually-tradable edge. When `liquidity_depth_json`
   is populated, the report can estimate slippage at the edge peak
   and emit a `realizable_edge` metric. Additive P2 enhancement.
