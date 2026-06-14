# Phase-gate criteria (Phase 2 -> Phase 3)

> Status: **partial — measurement shipped; thresholds are an unfinalized owner decision** (trade-trace-q04o).
> The criteria definitions and the `report.phase_gate_readiness` report (§5)
> are LIVE and tested. The *numeric thresholds* in
> [§4 Owner decision required](#4-owner-decision-required) are NOT finalized —
> they are placeholders pending owner sign-off. Until the owner sets them, the
> gate report can never return `ready`.

## 1. Why this document exists

[`VISION.md`](../../VISION.md) describes a three-phase autonomy arc and says
the gate between phases is **"evidence — track record, calibration, audit
cleanliness — never a roadmap date."** It deliberately gives no numbers.
[`docs/LIVE_TEST_CHARTER.md`](../LIVE_TEST_CHARTER.md) is a different axis (the
v0.0.2 SQLite single-writer concurrency test; its "Phase 5" is release
process, not the autonomy arc) and explicitly "does not authorize"
progression.

Before this document there was no measurable, queryable answer to **"has the
agent earned Phase 3?"** This document turns the prose bar into named
criteria, each computed from the local journal, and pairs it with a report
(`report.phase_gate_readiness`) that evaluates pass/fail against
owner-supplied numbers.

This is a **measurement, not an authorization.** Passing the gate report is a
*necessary* input to an owner's decision to unfreeze Phase 3 — it is not the
decision. A human still sets the bounds and reviews the audit.

## 2. The criteria

Each criterion is a single measurable dimension. The report computes
`measured` from the journal and compares it to an owner-supplied `threshold`
in the stated `direction`. A criterion `pass` is `true`, `false`, or `null`
(indeterminate — see §3).

| Criterion key | Measured from | Direction | Meaning |
| --- | --- | --- | --- |
| `resolved_n` | non-superseded `brier_binary` `forecast_scores` | `measured >= threshold` | Resolved track-record size: how many binary forecasts have actually been graded. Below the owner's floor the record is too thin to judge. |
| `brier` | `report.calibration_anchored` `summary.metrics.brier` | `measured <= threshold` | Mean Brier score over scored binary forecasts that have a market baseline (lower is better). |
| `skill_vs_market` | `report.calibration_anchored` `summary.metrics.skill` | `measured >= threshold` | Brier skill versus the market baseline (`1 - brier / brier_baseline`; `> 0` beats the market). The headline "did it actually beat the market" number. |
| `reconciliation_cleanliness` | `reconciliation_records` (unresolved AND critical) | `measured <= threshold` | Count of reconciliation records that are simultaneously `unresolved` and critical (carry `diff_severity='critical'` or a critical mismatch code: `POLICY_WAIVER_BREACH`, `DUPLICATE_FILL`, `REJECTED_APPROVED_INTENT`). The natural bar is `0`. |
| `audit_readiness` | `report.audit_readiness` `summary.ready` | `measured == threshold` | A populated prediction-market sample with zero blocking provenance issues. Owner-required value is `true`. |
| `paper_fill_coverage` | `pretrade_intents` ∩ `paper_fill_records` | `measured >= threshold` | Fraction of pretrade intents that have a linked paper fill — did the paper layer actually track what would have happened? |

`brier` and `skill_vs_market` are computed over the **anchored** sample
(`anchored_n`), which legitimately excludes forecasts that lack a market
baseline. `resolved_n` counts the **full** resolved track record (including
unanchored forecasts), so `resolved_n >= anchored_n`. Both numbers are
surfaced so an owner can see how much of the track record carries a market
baseline.

## 3. Determinism and the indeterminate state

The report is read-only, deterministic, and local-only (no network, no
advice, no execution). Every number is recomputed from the append-only
journal on each call.

A criterion's `pass` is `null` (**indeterminate**) when either:

- the owner has not supplied a threshold for it, or
- the measured value is unavailable (e.g. `brier`/`skill` with no
  market-baselined sample).

`gate_status` is one of:

- `owner_thresholds_unset` — at least one criterion has no owner threshold.
  **`ready` is `false`.**
- `insufficient_data` — thresholds are complete but `resolved_n == 0` (no
  track record to judge). **`ready` is `false`.**
- `not_ready` — thresholds complete, data present, but at least one criterion
  fails or is indeterminate. **`ready` is `false`.**
- `ready` — every criterion has an owner threshold AND every criterion's
  measured value clears it.

## 4. Owner decision required

**The numeric thresholds are a genuine owner decision. The agent must never
pick the bar that grants itself a wallet** (VISION: *"An agent that cannot
keep an honest record of its own judgment has not earned a wallet"*).

This is enforced structurally, not by convention:

- The report embeds **no default "pass" bar.** Thresholds are supplied per
  call via the `thresholds` argument.
- Any unset threshold yields `pass = null` and `gate_status =
  owner_thresholds_unset`, and **`ready` can never be `true`** while any
  threshold is unset. There is no code path where an omitted bar produces a
  passing gate.

The owner must fill in the numbers below. The values shown are
**placeholders / illustrative starting points for discussion — they are NOT
authorized thresholds and the agent did not choose them as a self-grant.**

| Criterion | Placeholder (owner to confirm/replace) | Rationale to weigh |
| --- | --- | --- |
| `resolved_n` | _TBD_ (e.g. 200) | Enough resolved markets that calibration/skill are not noise. |
| `brier` | _TBD_ (e.g. 0.18) | Below a coin-flip-on-base-rate; tie to observed base rates. |
| `skill_vs_market` | _TBD_ (e.g. ≥ 0.0, ideally > 0) | Must at least match the market baseline; arguably must beat it. |
| `reconciliation_cleanliness` | _TBD_ (e.g. 0 over a rolling window) | Zero open critical mismatches is the natural bar. |
| `audit_readiness` | `true` | Non-negotiable: zero blocking provenance issues. |
| `paper_fill_coverage` | _TBD_ (e.g. 0.9) | Most proposed trades must have a paper fill to learn from. |

Once the owner sets these, record the authorized values here (replacing the
placeholders) and pass them to `report.phase_gate_readiness` (or wire them
into whatever invokes the gate). **Do not commit owner-authorized thresholds
without the owner's explicit sign-off.**

## 5. The report

`report.phase_gate_readiness` (handler in
[`src/trade_trace/reports/phase_gate_readiness.py`](../../src/trade_trace/reports/phase_gate_readiness.py))
computes the criteria above.

```jsonc
// args
{
  "thresholds": {
    "resolved_n": 200,
    "brier": 0.18,
    "skill_vs_market": 0.0,
    "reconciliation_cleanliness": 0,
    "audit_readiness": true,
    "paper_fill_coverage": 0.9
  },
  "min_sample": 30   // optional; floors the anchored panel, does not gate readiness
}
```

The result carries a `summary` (`ready`, `gate_status`,
`owner_thresholds_complete`, pass/fail/indeterminate counts, and the lists of
`failing_criteria` / `indeterminate_criteria`) and a `criteria` array with
each `{measured, threshold, direction, pass, ...}` row.

Pass/fail logic is pinned by
[`tests/integration/test_phase_gate_readiness.py`](../../tests/integration/test_phase_gate_readiness.py),
including the safety invariant that an unset threshold can never yield a
`ready` gate.

## 6. What this gate does NOT do

- It does not execute, halt, remediate, fetch private state, or move funds.
- It does not unfreeze Phase 3 by itself. It is evidence for an owner who
  retains the decision.
- It does not invent the bar. The numbers in §4 are the owner's to set.

## 7. The readiness evidence bundle (`report.autonomy_readiness`)

`report.phase_gate_readiness` (§5) answers the *point-in-time* gate question:
each criterion is computed once and compared to the owner's bar. It does NOT
show whether the track record is *trending* the right way — a single Brier
number cannot distinguish "calibrated for six months" from "got lucky last
week".

`report.autonomy_readiness` (handler in
[`src/trade_trace/reports/autonomy_readiness.py`](../../src/trade_trace/reports/autonomy_readiness.py),
bead trade-trace-r91l) is the longitudinal **evidence bundle** that turns
*"did the agent earn its autonomy?"* into one auditable, replayable call. It
**composes** the gate report (it does not re-implement it) and adds the
time-series evidence the point-in-time gate lacks:

- `gate` — the full `report.phase_gate_readiness` packet, embedded verbatim.
- `criteria` — each gate criterion re-projected into the reports.md §3.0
  tri-state `state` of `pass` / `fail` / `insufficient_data`, with contributing
  `record_ids`. `state` is a pure restatement of the gate's `pass`; the bundle
  adds no new pass logic.
- `calibration_trend` — Brier / skill-vs-market / ECE over fixed-width
  resolution-time windows (newest first), each with its own contributing
  forecast/score/outcome `record_ids` and an `insufficient_data` flag when the
  window's N is below `min_sample` (metrics are still surfaced, never
  zero-filled).
- `expectancy_series` — realized R-multiple expectancy over the same windows,
  using the `report.risk` realized-R definition (closed decisions with a
  declared positive risk budget).
- `audit_hygiene` — the audit-readiness blocking count and open-critical
  reconciliation cleanliness, surfaced as standalone evidence.

### 7.1 Evidence-only, never a verdict

VISION favors *"humans read audits and set bounds."* The bundle therefore
renders **no verdict of its own**. The only `ready` / `gate_status` it reports
is `report.phase_gate_readiness`'s, computed from OWNER-supplied thresholds and
copied through verbatim. The trend and expectancy series are *descriptive*
evidence: they do not vote, and there is **no code path** where a strong trend
turns a not-ready gate into a ready one. The owner-decision safety invariant
of §4 (an unset threshold can never yield a `ready` gate) holds transitively
through the bundle. The agent must never self-grant a wallet.

```jsonc
// args (all optional)
{
  "thresholds": { /* same shape as report.phase_gate_readiness */ },
  "min_sample": 20,    // low-N floor for the trend/expectancy windows; does NOT gate readiness
  "window_days": 30,   // longitudinal-window width
  "max_windows": 12    // trailing-window cap
}
```

Pass-through and evidence-only behavior are pinned by
[`tests/integration/test_autonomy_readiness.py`](../../tests/integration/test_autonomy_readiness.py),
including the invariant that a clean trend cannot make the bundle `ready` while
any owner threshold is unset.
