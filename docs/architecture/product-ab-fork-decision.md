# Product A/B fork: commit to the calibration journal, freeze autonomous-ops

> Status: **decision document for trade-trace-4kec** (decision + rationale).
> The implementation lands in this same epic's children; this doc records
> the fork so future surface work cites it rather than re-litigating scope.

## Decision

Trade Trace ships **one** product: **Product A — a calibration + continuity
journal for an LLM trading agent**. The execution-lifecycle and
reconciliation surface (**Product B — autonomous-ops**) is **frozen behind
the experimental catalog-visibility tier**, not deleted, so a future
"contract surface" story can revive it intact.

This was executed by epic trade-trace-4kec:

- **KEEP 56** default public tools (Product A).
- **FREEZE 40** Product-B tools behind the experimental tier
  (`public_names(include_experimental=True)` / `MCP_INCLUDE_EXPERIMENTAL=1`;
  see `v002-pm-pivot-catalog.md` §4.6 and §1's frozen list).
- **CUT 3** redundant report tools (`report.calibration_trajectory`,
  `report.strategy_performance`, `report.amm_slippage`) — removed from the
  registry entirely.

56 + 40 + 3 = the prior 99-tool catalog.

## Why

A multi-agent feature triage (workflow `wy97te58m`, 2026-05-29) found the
project was over-built ~2×. A dogfood-proven calibration + continuity journal
(~30 core tools) was wrapped in ~40 tools of execution-lifecycle /
reconciliation governance that presuppose a trade **executor the product
explicitly is not** (README's "not a trader" positioning), plus redundant
report surfaces.

Evidence the B surface was speculative, not load-bearing:

- Both v0.0.2 Phase-5 dogfood runs and the AC-01..09 scorecard exercised
  **only** Product-A tools.
- The autonomous-ops and reconciliation clusters had **zero** dogfood and
  self-classify in their own docs as a "contract precursor… not a shipped
  capability claim".
- `approval.report` admits "no execution import table is compared" — the
  reconciliation loop has no ground-truth executor to reconcile against.

Freezing (not deleting) keeps the handlers dispatchable for tests and a
future opt-in, preserves the contract work already done, and removes the
surface from the default catalog an agent sees — so the product's identity
matches its README positioning.

## What the freed surface budget buys

The triage produced a decision-time deficit taxonomy (D1–D5) that the
remaining child beads of trade-trace-4kec reinvest into:

- **D1 — calibration blindness**: read-at-decision-time recalibration
  (`.7`), abstention / no-bet record (`.8`), bet-sizing / process scoring
  decoupled from outcome (`.11`).
- **D2 — cross-session amnesia**: prospective mistake trip-wire (`.10`),
  semantic/analogical recall of structurally similar markets (`.13`).
- **D3 — confabulation**: forecast independence + process scoring (`.9`,
  `.11`).
- **D4 — no ground-truth anchor**: pre-commit forecast independence lock
  (`.9`), resolution-criteria interpretation as a first-class field (`.12`).
- **D5 — systematic-error blindness**: read-at-decision-time recalibration
  (`.7`), the trip-wire (`.10`), resolution-criteria interpretation (`.12`).

## Reviving Product B

If the autonomous-ops surface is revived, it returns through a dedicated
"contract surface" story, and the anchored-calibration flow folds its
anchor write into `forecast.add` rather than re-shipping the standalone
`forecast.anchor_to_snapshot` writer (superseded in intent by `.9`).
