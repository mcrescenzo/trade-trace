# MVP Dogfood and Provenance Protocol

> Status: **shipped**. The MVP loop-usefulness protocol agents follow today; pinned by tests under `tests/integration/test_final_dogfood_verification.py`.

Status: clean planning draft. Date: 2026-05-18.

Companion docs: [PRD.md](../PRD.md), [VISION.md](../VISION.md),
[scoring.md](scoring.md), [persistence.md](persistence.md),
[reports.md](reports.md), [memory-layer.md](memory-layer.md),
[operability.md](operability.md).

## 1. Purpose

[PRD](../PRD.md) §10.2 lists seven "loop-useful" acceptance criteria
(#10–#16) for the MVP. These criteria distinguish "the plumbing runs"
(§10.1) from "the loop actually helps." They are inherently easier to
hand-wave than to verify.

This doc converts §10.2 into a **deterministic protocol** the final
verifier (trade-trace-c1r) and the eval-fixture harness
(trade-trace-8dv) can execute against a synthetic journal with
known answers. It also locks the provenance policies that govern
late-recorded forecasts, imported data, and ambiguous resolution so
calibration metrics are honest.

The doc is **not** a fixture spec — that lives in trade-trace-8dv. It
is the contract the fixture must satisfy.

## 2. Provenance Policy

### 2.1 Decision before outcome (locked)

[VISION.md](../VISION.md) Principle 1 is load-bearing: a forecast
recorded after its outcome cannot be a calibration measurement of the
agent, only a record of imported history. The dogfood protocol
operationalizes the principle as follows.

A forecast row is **pre-outcome** when both:

1. `forecasts.created_at < outcomes.created_at` (the forecast's
   transaction time strictly precedes the outcome's), AND
2. `forecasts.created_at <= forecasts.resolution_at` (the forecast was
   committed before its own resolution time).

Either condition failing flags the row as `late_recorded`. The exact
mechanism:

- The server stamps `forecast_scores.metadata_json.late_recorded = true`
  (boolean) and `forecast_scores.metadata_json.late_recorded_by_seconds`
  (integer; `max(0, forecasts.created_at - min(outcomes.created_at,
  forecasts.resolution_at))` in seconds) on **every** score row whose
  forecast does not satisfy both conditions above.
- Scoring still fires per [`scoring.md`](scoring.md) §6 ("Late-recorded
  forecasts get scored immediately"). The protocol does not change
  scoring; it changes which rows are counted in calibration aggregates
  by default.

### 2.2 Back-dated / imported forecasts and calibration (locked)

**Decision: conditional inclusion**, defaulting to excluded.

- `report.calibration` filters `late_recorded` rows out of every
  aggregate metric (`brier`, `log_score`, `ece`, `sharpness`, baseline,
  reliability bins) **by default**. The filtered count is surfaced as
  `data.summary.late_recorded_excluded` (integer) and a one-line caveat
  in `data.caveats[]`.
- Callers may opt in with `ReportFilter.outcome.include_late_recorded =
  true` (additive field per [`reports.md`](reports.md) §2; non-breaking
  because the default behavior is opt-out). When set, the metric panel
  is computed over the full set; the caveat still records that
  `late_recorded` rows are present.
- The forecasts themselves are not deleted, archived, or hidden from
  list tools. They are queryable, they appear in `report.unscored_
  forecasts` only if literally unscored, and they participate in path
  analysis and P&L aggregates that don't depend on prediction-before-
  resolution semantics.

This treats imported history as **evidence the agent has**, not as
**calibration the agent earned**.

### 2.3 Late-recorded policy at write time (locked)

When `forecast.add` is called and a `resolved_final` outcome already
exists for the linked instrument with `outcomes.resolved_at <=
now()`:

**Decision: option (c) — flag with `metadata_json.late_recorded = true`
and still auto-score.** Rationale:

- (a) auto-score immediately *without flagging* hides the late-record
  fact from reports and silently contaminates calibration.
- (b) reject with `VALIDATION_ERROR` blocks honest imports of historical
  research (the dogfood loop needs to support importing back-tested
  predictions for replay).
- (c) preserves the data, scores it (so downstream reports can find it),
  and surfaces the late-recording so calibration aggregates can filter
  it. This is the only choice that satisfies both "preserve all
  evidence" and "calibration is honest."

The flag is written to **both** `forecasts.metadata_json.late_recorded`
(at create time) and to every `forecast_scores.metadata_json.
late_recorded` row triggered by that forecast (at score time). The
duplication is intentional: query paths into either table can detect
the property without a join.

### 2.4 Evidence / source warning policy (locked)

[VISION.md](../VISION.md) Principle 9 and `memory-layer.md`
emphasize evidence capture; PRD §4.5 makes source attachment a
first-class write. The policy:

- **Schema-optional, warn (not block).** A decision, thesis, or
  forecast write without an attached source is accepted with no
  `VALIDATION_ERROR`. Blocking source-less writes is rejected because
  agents commonly write a thesis first and attach evidence in the next
  call.
- **Coach surfaces the gap.** `report.coach` and `report.mistakes`
  filter for `has_thesis_without_source` and emit a coach signal
  `sample_size_warning` style note for instruments or strategies where
  >50% of decisions over the lookback window lack any attached source.
- **Late-attached sources are second-class for calibration.** When a
  `source.attach_to_thesis` or `source.attach_to_forecast` write
  happens **after** the linked outcome's `resolved_final` row exists,
  the edge row carries `metadata_json.attached_post_outcome = true` so
  process-vs-outcome reviews (`report.mistakes` with
  `target_kind=thesis`) can distinguish "evidence the agent had" from
  "evidence the agent retrospectively justified with."

### 2.5 Free-text idempotency replay policy (locked)

[`persistence.md`](persistence.md) §5.2 already defines per-event-type
semantic equivalence. The dogfood protocol adds one rule on top:

- **Free-text fields tolerated for replay** include `body`, `title`,
  `note`, `excerpt`, `extracted_text`, `summary`, `reason`,
  `description`, `hypothesis`, `resolution_rule_text`. Any change to a
  structural field in the §5.2.1 registry returns
  `IDEMPOTENCY_CONFLICT`; any change limited to a free-text field
  succeeds as a replay (returns `meta.idempotent_replay = true` and
  the **original** event's `data`, not the new free-text version).
- Implication: agents that rephrase their reasoning on retry get an
  honest "you already recorded this" rather than a duplicate. The
  written text remains what was committed first.

### 2.6 Retrieval-strategy vs trading-strategy naming (locked)

`memory-layer.md` §7.5 ("Terminology note") already locks the naming
choice: `memory.recall` result rows use `strategy` to mean
**retrieval strategy** (`bm25`/`temporal`/`semantic`/`graph`);
PRD §2.12 uses `strategy` to mean **trading strategy** (the
`strategies` table). The dogfood protocol affirms:

- The two namespaces never collide in API payloads (input vs result
  position).
- No rename is needed. The terminology note in `memory-layer.md` §7.5
  and the cross-reference here are the canonical disambiguation.

## 3. Ambiguous-resolution scenarios (3 required)

The dogfood fixture (trade-trace-8dv) MUST include all three scenarios
below. Each has a deterministic trigger event, an expected system
behavior, and an expected agent action.

### 3.1 Scenario A — `void`: post-resolution void

| Field | Value |
|---|---|
| Trigger event | `outcome.add(instrument_id=I_A, status="void", resolved_at=T, outcome_label="VOID")` on a binary forecast F_A. |
| What makes it ambiguous | The market was cancelled after observably trading; the predicted YES/NO answer has no realized indicator. |
| Expected system behavior | `forecasts.scoring_state` for F_A remains `pending`. No `forecast_scores` row is written. |
| Expected agent action | Record outcome with `status="void"` and an `outcomes.metadata_json.void_reason` note. Do not score. If a later final answer emerges, write a new outcome with `status="resolved_final"` and a `supersedes` edge from new → void row; the supersession auto-fires scoring per [`scoring.md`](scoring.md) §5 + §5.1. |
| Fixture artifact name | `scenario-void-and-resupersede` |
| Measurable assertion | After the void: `forecast.show(F_A).scoring_state == "pending"` AND no row in `forecast_scores` for F_A. After the supersede: exactly one `forecast_scores` row for F_A with `metadata_json.outcome_id` pointing to the new outcome. |
| Test name | `tests/dogfood/test_scenario_void_supersede.py` |

### 3.2 Scenario B — `disputed`: contradictory sources

| Field | Value |
|---|---|
| Trigger event | `outcome.add(instrument_id=I_B, status="disputed", resolved_at=T, outcome_label="YES")` AND two `source.attach_to_decision` calls landing sources with opposite `stance` (one `supports`, one `contradicts`). |
| What makes it ambiguous | Two attached sources disagree on the realized outcome; the agent cannot verify which is correct yet. |
| Expected system behavior | `forecasts.scoring_state` for F_B remains `pending`. Both source edges land in `edges` and survive without conflict (edges are append-only). |
| Expected agent action | Record disputed outcome with both source evidences attached; write a reflection memory node with `meta_json.scope_kind = "tag"` and `scope_tag = "disputed-source"`; if the dispute is later reconciled, write a new outcome with `status="resolved_final"` and a supersedes edge. |
| Fixture artifact name | `scenario-disputed-contradictory-sources` |
| Measurable assertion | After the writes: `forecast.show(F_B).scoring_state == "pending"`; `edges.list(target_kind="decision", target_id=D_B)` returns exactly two source edges with opposite types; `report.mistakes(filter={tags_any:["disputed-source"]})` surfaces the reflection. |
| Test name | `tests/dogfood/test_scenario_disputed_sources.py` |

### 3.3 Scenario C — `resolved_provisional`: pending appeal window

| Field | Value |
|---|---|
| Trigger event | `outcome.add(instrument_id=I_C, status="resolved_provisional", resolved_at=T_initial, outcome_label="YES", metadata_json={"appeal_window_ends_at": T_final})`. |
| What makes it ambiguous | The market called it YES, but a binding appeal could still flip the result; calibration must not bake in the provisional answer. |
| Expected system behavior | `forecasts.scoring_state` for F_C remains `pending` because [`scoring.md`](scoring.md) §5 explicitly disallows auto-scoring on `resolved_provisional`. |
| Expected agent action | Record provisional outcome with the appeal-window metadata; once the window closes, write a `resolved_final` outcome (with a `supersedes` edge if the answer changed, or as a parallel `resolved_final` row if confirming). Auto-score fires on the `resolved_final` per `scoring.md` §5 + §5.1. |
| Fixture artifact name | `scenario-provisional-then-final` |
| Measurable assertion | Between provisional and final: `forecast.show(F_C).scoring_state == "pending"` AND `report.unscored_forecasts(filter={...})` lists F_C. After the final: F_C is `scored`; if the provisional was superseded, the score's `metadata_json.outcome_id` points to the post-supersession final. |
| Test name | `tests/dogfood/test_scenario_provisional_final.py` |

## 4. Fixture size targets (pinned to trade-trace-8dv)

The dogfood fixture must contain at least:

| Item | Minimum count | Notes |
|---|---|---|
| Decisions | 30 | Exercises [`PRD`](../PRD.md) §3.1 required-field matrix across at least 8 of the 13 `decisions.type` values, including `skip`, `paper_enter`, `paper_exit`, `hold`, `update_thesis`, `resolved`, and `review`. |
| Reflections (memory nodes, `node_type=reflection`) | 10 | At least 2 with `meta_json.scope_kind="period"`, 2 with `meta_json.scope_kind="tag"`, and the rest row-backed via `about` edges. |
| Resolved binary forecasts (`scoring_state=scored`, non-late-recorded) | 5 | Resolved against `outcomes.status="resolved_final"`. |
| Strategies | 2 | One `active`, one previously-`updated` (to exercise the `strategy.updated` event). |
| Playbook version updates | 1 | A `playbook.propose_version` event whose `provenance_reflection_node_id` references a reflection in the fixture. |
| Later adherence rows | 2 | One `decision_playbook_rules.status="followed"` and one `status="overridden"` referencing the new version. The `overridden` row's decision has an outcome captured per [`PRD`](../PRD.md) §10.2 #12. |
| Stale watch | 1 | A `watch` decision older than `config.report.watchlist.stale_days` (default 30) with no follow-up decision. |
| Unscored forecast (live, not late-recorded) | 1 | Past `resolution_at` with no `outcomes` row, surfaceable by `report.unscored_forecasts`. |
| Sources with `redaction_status="none"` | ≥3 | Normal attached evidence. |
| Sources with `redaction_status="redacted"` | ≥1 | Tests body-omission path in `review.bundle`. |
| Sources with `redaction_status="sensitive"` | ≥1 | Tests unconditional-exclusion path. |
| Stale source | ≥1 | `sources.freshness_at` ≥ 30 days before the decision that cites it; tests `source.source_freshness_before_decision` filter. |
| Contradictory source pair | ≥1 | Two sources attached to the same decision/forecast with opposite `stance` (one `supports`, one `contradicts`); supports Scenario B (§3.2). |
| Late-recorded forecast | ≥1 | Exercises §2.2 / §2.3 default-exclusion in `report.calibration`. |
| Ambiguous-resolution scenarios A/B/C | 1 each | Per §3 above. |

The full inventory is the contract trade-trace-8dv implements. Fixture
generation runs under an injected UTC clock so timestamps are
reproducible.

## 5. Loop-usefulness criteria mapped to PRD §10.2

Each criterion below has: (a) the fixture artifact name, (b) the
measurable assertion, (c) the test name. trade-trace-c1r (final
verification) runs these assertions against the fixture; passing all
seven is the §10.2 acceptance gate.

### 5.1 #10 — recurring error/strength pattern

(a) `fixture artifact`: tag `overpaid-on-illiquid` applied to 4
decisions spread across both strategies, plus tag `liquidity-ignored`
co-occurring on 3 of them.
(b) `measurable assertion`: `report.mistakes(filter={})` returns a
group keyed `overpaid-on-illiquid` with `count >= 3`; its
`co_occurrence_top` array contains `liquidity-ignored`; and no
`forecasts.metadata_json.flagged_by_agent_in_advance` flag is set on
the originating theses (the agent did not pre-flag the pattern).
(c) `tests/dogfood/test_loop_useful_recurring_pattern.py`

### 5.2 #11 — recall citation in a later thesis

(a) `fixture artifact`: reflection node `N1` linked to outcome `O_x`
via `about`. A later thesis `T2` on a related instrument is created
after a `memory.recall` call that returned `N1`; `T2` carries a
`supports` edge to `N1`.
(b) `measurable assertion`: there exists an `edges` row with
`source_kind=thesis`, `source_id=T2`, `target_kind=memory_node`,
`target_id=N1`, `edge_type in {derived_from, supports}`. The
`memory_recall_events` row preceding `T2.created_at` whose `query_text`
matches `T2.body` has `N1` in its `node_ids_returned`.
(c) `tests/dogfood/test_loop_useful_recall_cited.py`

### 5.3 #12 — playbook rule changes a later decision

(a) `fixture artifact`: playbook rule `R1` (a `playbook_rule` memory
node attached to `playbook_version` `V1`). One decision `D_followed`
with a `decision_playbook_rules` row referencing `R1` and
`status="followed"`; one decision `D_overridden` with a row
referencing `R1`, `status="overridden"`, plus a captured outcome
(`outcomes` row with `status="resolved_final"` for the override case).
(b) `measurable assertion`: `report.playbook_adherence(filter={
playbook_version_id: V1})` returns counts
`{considered: >=2, followed: >=1, overridden: >=1, not_applicable: 0}`.
The override outcome row exists and is queryable via
`decision.show(D_overridden).outcome_id`.
(c) `tests/dogfood/test_loop_useful_playbook_changes_decision.py`

### 5.4 #13 — ambiguous resolution handled correctly

(a) `fixture artifact`: scenarios A, B, C from §3.
(b) `measurable assertion`: union of the per-scenario assertions in
§3.1/§3.2/§3.3.
(c) `tests/dogfood/test_loop_useful_ambiguous_resolution.py`
(re-runs the three scenario tests as a suite).

### 5.5 #14 — sample-size warning on calibration

(a) `fixture artifact`: exactly 5 resolved binary forecasts in the
"calibration-eligible" subset (after filtering out `late_recorded`).
(b) `measurable assertion`: `report.calibration(filter={})` returns
`data.summary.sample_size == 5` and a non-null
`data.summary.sample_warning` string containing the substring "below"
and `5`. `meta.contract_version == "1.0"` is set.
(c) `tests/dogfood/test_loop_useful_sample_warning.py`

### 5.6 #15 — strategy-scoped recall narrows usefully

(a) `fixture artifact`: strategy `S1` with three reflection nodes
`{N_S1_a, N_S1_b, N_S1_c}` whose `meta_json` scopes back to `S1`
indirectly (via decision/thesis `strategy_id`), NOT via direct edges
to the strategy endpoint. A later thesis `T_S1_next` in strategy `S1`
created **after** a `memory.recall(query, context={kind:"strategy", id:S1})`
returns at least one of `{N_S1_a, N_S1_b, N_S1_c}`; `T_S1_next` carries
a `supports` or `derived_from` edge to the returned node.
(b) `measurable assertion`: the relevant `memory_recall_events` row
exists with `context_kind="strategy"`, `context_id=S1`, and at least
one of the three node IDs in `node_ids_returned`. An `edges` row
connecting `T_S1_next` to that node with `edge_type in
{derived_from, supports}` exists. The originating thesis of `S1`
(`T_S1_first`) does NOT have an edge to that node (demonstrating
strategy-scoped recall surfaced a memory the agent didn't already
cite).
(c) `tests/dogfood/test_loop_useful_strategy_scoped_recall.py`

### 5.7 #16 — sharpness signal distinguishes flat from sharp

(a) `fixture artifact`: a tag-filtered subset of forecasts where one
group has `p_yes` clustered near `0.5` (the "flat" sub-forecaster) and
another has `p_yes` in `{0.1, 0.9}` with calibration accuracy (the
"sharp-and-calibrated" sub-forecaster). Both subsets have ≥20 scored
forecasts so they pass the `sample_warning` threshold individually.
(b) `measurable assertion`:
`report.calibration(filter={decision: {tags_any:["flat"]}})` returns
`summary.sharpness < 0.02` and `summary.ece < 0.05`.
`report.calibration(filter={decision: {tags_any:["sharp"]}})` returns
`summary.sharpness > 0.10` and `summary.ece < 0.05`. The pair makes
"sharpness distinguishes flat-but-calibrated from sharp-and-calibrated"
a measurable property.
(c) `tests/dogfood/test_loop_useful_sharpness_signal.py`

## 6. "Agent did not already know this" (resolves PRD §11 OQ#2)

PRD §11 open question #2 asks how to operationalize "the agent did not
already know this." The dogfood protocol locks the answer:

- A reflection or recalled memory `N` satisfies "the agent did not
  already know this" relative to a later thesis `T` when BOTH:
  1. There is no `derived_from`, `supports`, or `about` edge from `T`'s
     thesis row (or any decision/forecast row written in the same
     transaction as `T`) to `N`'s row written **before** `T.created_at`.
  2. There is a `memory_recall_events` row whose
     `actor_id == T.actor_id`, `created_at <= T.created_at`, and
     `node_ids_returned` includes `N`.

This is the same construction used in §5.6 #15. It surfaces explicitly
in `report.coach` as a top-level note `"recall surfaced N nodes not
cited in advance"` whenever a new thesis is committed after such a
recall.

The mechanism is implementation-detectable without an explicit
"prior-knowledge" boolean on theses. PRD §11 OQ#2 is therefore closed.

## 7. What this protocol does NOT cover

- It does not specify the fixture **generator** — trade-trace-8dv does.
- It does not specify **dogfood scoring rubrics** beyond the §5
  measurable assertions; subjective "is this a good reflection" is out
  of scope by design (the system stores, the agent judges, per VISION
  Principle 10).
- It does not specify how trade-trace-c1r consumes the protocol; that
  bead's verification harness defines the runner.

## 8. Closed decisions summary

| Decision | Locked answer | §ref |
|---|---|---|
| Back-dated forecast in calibration | Conditional, default excluded; `ReportFilter.outcome.include_late_recorded` opts in | §2.2 |
| Late-recorded forecast write | Option (c): flag `late_recorded=true`; still auto-score | §2.3 |
| Missing-source policy | Schema-optional with coach warning; never blocks | §2.4 |
| Late-attached source | Edge carries `metadata_json.attached_post_outcome=true` | §2.4 |
| Free-text idempotency replay | Free-text-only changes return original event as replay | §2.5 |
| Retrieval vs trading "strategy" naming | Disambiguated by position in payload; no rename | §2.6 |
| Three ambiguous-resolution scenarios | A=void→supersede, B=disputed-sources, C=provisional→final | §3 |
| Fixture size targets | Inventory pinned per §4 | §4 |
| #10–#16 measurable assertions | Per §5 | §5 |
| "Agent did not already know this" | Edge-set + recall-event construction | §6 |
