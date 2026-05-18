# Forecast Scoring

Status: clean planning draft. Date: 2026-05-18.

Companion docs: [PRD.md](../../PRD.md), [VISION.md](../../VISION.md),
[memory-layer.md](memory-layer.md), [persistence.md](persistence.md),
[contracts.md](contracts.md).

## 1. Purpose

This doc defines exactly how a forecast becomes a score in Trade Trace. It
nails down the Brier formula form, the binary forecast invariants, the
lifecycle of a forecast row from `pending` to `scored`, the resolution status
enum on outcomes, and the rules for when auto-scoring is allowed to fire.

MVP scope is **binary forecasts only**. Categorical and scalar forecasts may
be stored as record-only data; they are not scored until P1.

## 2. Binary Forecast Invariants

A forecast with `kind = 'binary'` MUST satisfy all of the following on write.
Violating any of them returns `INVARIANT_VIOLATION` (see
[contracts.md](contracts.md)).

- Exactly two rows in `forecast_outcomes` for this forecast.
- Each `forecast_outcomes.probability ∈ [0.0, 1.0]`.
- The two probabilities sum to `1.0` within tolerance `1e-6`.
- The two `outcome_label` values are distinct.
- At least one outcome label, after the outcome resolves, must match the
  resolved `outcomes.outcome_label`. Labels are compared case-insensitively
  with leading/trailing whitespace stripped. If neither label matches, the
  forecast cannot be scored and the call returns `SCORING_NOT_READY` with
  `details.reason = "label_mismatch"`.

## 3. Brier Formula (MVP)

The MVP scorer is `brier_binary`. It uses the **single-probability form**:

```
score = (p_yes - y)^2
```

Where:

- `p_yes` is the forecast probability assigned to the outcome that maps to
  YES (the "positive" outcome, identified by `outcome_label` resolution).
- `y ∈ {0, 1}` is the realized indicator: `1` if the resolved outcome label
  matches the YES label, `0` if it matches the NO label.

The score is in `[0, 1]`; lower is better. Perfect calibration on a single
forecast scores `0`; maximally wrong scores `1`.

### 3.1 Why single-probability form

The two-outcome form `(p_yes - y_yes)^2 + (p_no - y_no)^2` differs from the
single-probability form by a factor of 2 (since `p_no = 1 - p_yes` and
`y_no = 1 - y_yes`). We deliberately do **not** use the two-outcome form in
MVP, for three reasons:

1. One number per forecast is easier to reason about and to surface in
   reports.
2. Most external Brier references (Wikipedia, ForecastBench documentation,
   Tetlock's GJP literature) use the single-probability form for binary
   events.
3. The two-outcome form generalizes more naturally to multi-class scoring,
   which is a P1 concern — when we add categorical scoring, we'll introduce
   a new metric (`brier_multiclass` or similar) rather than overload
   `brier_binary`.

### 3.2 Identifying the YES outcome

When a binary forecast is created, the caller MAY pass `yes_label` to
explicitly identify which of the two outcome labels is YES. `yes_label` is
**immutable** once written — there is no `forecast.set_yes_label` tool, and
no in-place mutation of `forecasts` rows is permitted (the append-only
invariant on `forecasts` is strict; see [PRD](../../PRD.md) §3.1).

If `yes_label` is omitted at create time, the scorer applies the following
heuristic on resolution:

1. If one label exactly matches `"YES"` (case-insensitive), it is YES.
2. Else if one label exactly matches `"TRUE"` (case-insensitive), it is YES.
3. Else if exactly one label matches the resolved `outcomes.outcome_label`,
   that label is YES.
4. Otherwise, the forecast transitions to `scoring_state = 'failed'` with
   `forecast_scores` row carrying `score = NULL` and
   `metadata_json.failure_reason = "yes_label_ambiguous"`. The caller's
   recovery path is `forecast.supersede` ([PRD](../../PRD.md) §4.0): write a
   new forecast row with an explicit `yes_label`, which sets the prior
   forecast's `scoring_state = 'superseded'` via the supersedes-edge
   invalidation path (§4.2).

Heuristic mismatches are silent on creation; they surface only at scoring
time, which is the right moment because the resolved label is needed.

## 4. Status Fields

The `forecasts` table has two distinct status columns. Earlier drafts of the
PRD used a single `scoring_status` that conflated capability with lifecycle;
this is split for clarity.

### 4.1 `scoring_support`

Capability: can this forecast's `kind` be scored by the currently-installed
scorer?

Values:

- `supported`: there is a scorer for this `(kind, scorer_version)`.
- `unsupported`: no scorer registered for this `kind` yet.

`scoring_support` is determined at write time based on `forecast.kind` and
the installed scorer registry. It is recorded on the row so reports can
filter unsupported forecasts without re-querying the scorer.

### 4.2 `scoring_state`

Lifecycle: what has actually happened to this forecast on its journey to a
score? `scoring_state` is an append-only logical view derived from
`forecast_scores` rows plus supersedes-edge events; the column itself is
maintained by the system but expresses the latest committed state.

Values:

- `pending`: created, awaiting resolution or scoring.
- `scored`: a `forecast_scores` row exists; the forecast is graded.
- `failed`: scoring was attempted and produced a structured failure
  (e.g. label mismatch on resolution, ambiguous YES label, outcome row
  superseded mid-scoring). The failure reason is recorded on the
  corresponding `forecast_scores` row with `score = NULL` and
  `metadata_json.failure_reason`.
- `superseded`: the forecast has been replaced by a newer version via
  `forecast.supersede` ([PRD](../../PRD.md) §4.0). A `supersedes` edge
  links the new forecast row to the old; the old forecast is no longer
  scored. The `parent_thesis_id` chain on `theses` does NOT automatically
  supersede dependent forecasts — forecast supersession is explicit so
  that a thesis update without a new probability does not silently
  invalidate the prior calibration record.

### 4.3 Invariants on the two columns

- `scoring_state != 'pending'` requires `scoring_support = 'supported'`.
- An `unsupported` forecast stays in `scoring_state = 'pending'` forever
  unless a future migration upgrades the scorer registry and triggers a
  one-shot rescan. The rescan is a P1 admin command, not part of MVP.
- `scoring_state = 'scored'` requires a `forecast_scores` row with
  `score IS NOT NULL`.
- `scoring_state = 'failed'` requires a `forecast_scores` row with
  `score IS NULL` and a non-empty `metadata_json.failure_reason`.

## 5. Resolution Status

The `outcomes` table records what the market did. Outcomes are append-only;
corrections produce a new row and use a `supersedes` edge (`source_kind =
'outcome'`, `target_kind = 'outcome'`, `edge_type = 'supersedes'`) to mark
the older row inactive. There is no `parent_outcome_id` column on
`outcomes` — the supersedes edge is the single canonical correction
mechanism (resolving an earlier draft ambiguity in [PRD](../../PRD.md)
§3.1 outcomes and [persistence.md](persistence.md) §8). Each row carries
an explicit `status`:

| Value | Meaning | Auto-score allowed |
|---|---|---|
| `resolved_final` | Outcome is finalized and unambiguous. | Yes |
| `resolved_provisional` | Outcome is known but not yet final (e.g. pending appeal window). | No |
| `ambiguous` | Resolution criteria are ambiguous; agent must judge. | No |
| `disputed` | Outcome is contested. | No |
| `void` | Market was voided after the fact (no winner). | No |
| `cancelled` | Market was cancelled before resolution. | No |

**Hard invariant:** the scorer auto-scores a forecast only when the
associated outcome row has `status = 'resolved_final'`. Any other status
leaves the forecast in `scoring_state = 'pending'` until either (a) a new
`outcomes` row with `status = 'resolved_final'` supersedes the earlier one,
or (b) the agent explicitly calls `forecast.score` with a manual override
(which records `metadata_json.manual_override_reason` on the score row).

This invariant exists because bad resolution handling poisons calibration.
A 60% forecast that's auto-scored against a `disputed` outcome that later
flips creates noise that doesn't represent the agent's actual calibration.

## 6. Scoring Lifecycle

A forecast moves through `scoring_state` like this:

```
created
  └─> pending (scoring_support='supported')
       └─> auto-trigger on outcomes.status='resolved_final'
            ├─> scored        (score computed, forecast_scores row written)
            ├─> failed        (label mismatch or other structured failure)
            └─> stays pending (outcome status not 'resolved_final')

created
  └─> pending (scoring_support='unsupported')
       └─> stays pending forever (no auto-score for unsupported kinds)
```

The scoring trigger fires on two events:

1. `outcome.recorded` event with `status = 'resolved_final'`. The scorer
   looks up all `pending` forecasts referencing that instrument and
   resolution time, and scores any whose `scoring_support = 'supported'`.
2. `forecast.created` event when an outcome row already exists with
   `status = 'resolved_final'` and the forecast's resolution time is past.
   (Late-recorded forecasts get scored immediately.)

Both triggers run inside the same transaction as the originating event, so
`forecast_scores` writes and `scoring_state` transitions are atomic with the
event that caused them. See [persistence.md](persistence.md) for transaction
boundaries.

## 7. Calibration Report Depth (MVP)

The MVP `report.calibration` ([PRD](../../PRD.md) §4.2) emits a fixed set
of metrics over scored binary forecasts in the filtered set. Per-forecast
Brier scores from §3 are the substrate; this section defines the aggregate
metrics, the reliability-bin policy, and the report envelope.

A "calibration substrate" that emits only Brier is under-spec'd for the
LLM-forecasting field: every contemporary benchmark (ForecastBench,
Manifold, Brier.fyi) reports a richer panel. The MVP report emits the full
panel because the marginal implementation cost over Brier-only is small and
several DoD criteria ([PRD](../../PRD.md) §10.2 #14, #16) depend on it.

### 7.1 Aggregate metrics

Let `N` be the number of scored binary forecasts in the filtered set,
`p_i` be the YES-side probability of forecast `i`, and `y_i ∈ {0, 1}` be
the realized YES indicator.

- **Mean Brier score**:
  `Brier = (1/N) * sum_i (p_i - y_i)^2`. Lower is better.
  Random forecaster scores `0.25`; "always 50%" scores `0.25`; perfect
  scores `0`.
- **Mean log score (binary)**:
  `LogScore = (1/N) * sum_i [ -y_i * ln(max(p_i, eps)) -
  (1 - y_i) * ln(max(1 - p_i, eps)) ]`, with `eps = 1e-9` to avoid
  `log(0)`. Strictly proper; penalizes confident-and-wrong severely.
  Lower is better.
- **Expected Calibration Error (ECE)** over the bin policy in §9.2:
  `ECE = sum_b (|S_b| / N) * |mean(p_i in b) - mean(y_i in b)|`,
  where `b` ranges over non-empty bins and `S_b` is the set of forecasts
  whose `p_i` falls in bin `b`. Lower is better. Reported with `2`-decimal
  precision and a 1-line interpretation note.
- **Sharpness**:
  `Sharpness = (1/N) * sum_i (p_i - p_bar)^2`, where
  `p_bar = (1/N) * sum_i p_i`. Variance of the probability distribution.
  An "always 50%" forecaster has sharpness `0`; a forecaster who confidently
  picks sides has high sharpness. Sharpness is necessary to interpret
  calibration: a perfectly-calibrated-but-flat (`p_i = sample prevalence`
  for all `i`) forecaster is useless, and only the joint `(ECE, sharpness)`
  surface that.
- **Sample-prevalence baseline**:
  `Baseline = mean(y_i)`, the realized YES rate. The "always say
  `Baseline`" forecaster is the reference. Report:
  - `BrierBaseline = (1/N) * sum_i (Baseline - y_i)^2 = Baseline * (1 - Baseline)`
  - `LogScoreBaseline` computed at `p_i = Baseline` for all `i`
  - `Skill = 1 - (Brier / BrierBaseline)` — positive means agent beats the
    prevalence baseline; negative means worse.
- **Sample size**: `N`, with `sample_warning: true` when `N < 20` and a
  human-readable note. The threshold is configurable
  (`config.report.calibration.min_sample`).

### 7.2 Reliability-diagram bins

Bin policy:

- **Default**: equal-width bins on `[0.0, 1.0]` with width `0.1` (10 bins:
  `[0.0, 0.1)`, `[0.1, 0.2)`, ..., `[0.9, 1.0]`). The final bin is closed
  on the right so `p_i = 1.0` falls into the last bin.
- **Bin shape per bin**:
  - `bin_index`: `0` through `9`.
  - `lower`, `upper`: inclusive lower bound, exclusive upper bound (except
    bin `9`).
  - `bin_midpoint`: `(lower + upper) / 2`.
  - `count`: number of forecasts whose `p_i` falls in the bin.
  - `mean_probability`: `mean(p_i in bin)`.
  - `observed_frequency`: `mean(y_i in bin)`.
  - `gap`: `mean_probability - observed_frequency`.
- **Empty bins**: reported with `count: 0` and `mean_probability` /
  `observed_frequency` set to `null`. Empty bins do not contribute to
  ECE.

Alternative bin policies (equal-mass, custom) are deferred; they can be
added without a contract bump because the bin policy is reported in
`meta.bin_policy`.

### 7.3 Report envelope

`report.calibration` returns:

```json
{
  "ok": true,
  "data": {
    "summary": {
      "sample_size": 42,
      "sample_warning": null,
      "filter": { ... echoed ReportFilter ... },
      "brier_score": 0.183,
      "log_score": 0.487,
      "ece": 0.072,
      "sharpness": 0.094,
      "baseline": {
        "prevalence": 0.43,
        "brier": 0.245,
        "log_score": 0.683,
        "skill": 0.253
      }
    },
    "reliability_bins": [
      {
        "bin_index": 0,
        "lower": 0.0,
        "upper": 0.1,
        "bin_midpoint": 0.05,
        "count": 3,
        "mean_probability": 0.04,
        "observed_frequency": 0.0,
        "gap": 0.04
      },
      ...
    ],
    "record_ids": {
      "forecasts": ["f_...", ...],
      "scored_outcomes": ["o_...", ...]
    },
    "drilldowns": [
      {
        "label": "Worst-calibrated bin",
        "filter": { ... },
        "record_ids": { ... }
      }
    ]
  },
  "meta": {
    "tool": "report.calibration",
    "bin_policy": "equal_width_0.1",
    "contract_version": "1.0",
    ...
  }
}
```

Drill-down per [`reports.md`](reports.md) §3 is mandatory: the agent that
runs the report must be able to pull the exact forecast and outcome IDs
behind any bin or aggregate without re-running with different filters.

### 7.4 Property tests

The MVP test suite enforces:

- A perfectly-calibrated synthetic forecaster (`p_i = y_i ∈ {0, 1}`)
  scores `Brier = 0`, `LogScore ≈ 0`, `ECE = 0`, `Sharpness = 0.25`,
  `Skill = 1`.
- An "always 50%" forecaster on balanced data
  (`p_i = 0.5`, `y_i ∼ Bernoulli(0.5)`) scores `Brier ≈ 0.25`,
  `Sharpness = 0`, `Skill ≈ 0`. Sharpness near zero is the load-bearing
  signal that distinguishes flat-but-calibrated from sharp-and-calibrated.
- A "random" forecaster (`p_i ∼ Uniform(0, 1)`, `y_i = 1`) has
  `Brier ≈ 1/3` in expectation.
- Bin assignment is deterministic on the default policy: `p_i = 0.1`
  goes into `bin_index = 1`; `p_i = 1.0` goes into `bin_index = 9`;
  `p_i = 0.0` goes into `bin_index = 0`.

## 8. Future Scoring Kinds (P1+)

The schema deliberately reserves room for future scorers without migration:

- `forecast_scores.metric` is a string column. Future metrics can be added
  by extending the scorer registry; no schema change required.
- `forecasts.kind` already accepts `categorical` and `scalar` per PRD §3.1.
  Their `scoring_support` is `unsupported` in MVP; once a multi-class or
  CRPS scorer ships, the support flag flips and a rescan picks them up.
- Potential P1 metrics: `brier_multiclass`, `crps`, `interval_score`,
  `quantile_loss`. (Log score is already in MVP per §7.1.) Each new metric
  gets its own short section in this doc when implemented.

## 9. Open Questions

1. **Rescan after scorer upgrade.** When P1 adds a scorer for categorical
   forecasts, do we eagerly rescan all `pending unsupported` forecasts, or
   lazily upgrade them on next read? Likely eager via
   `journal.rescan_scoring`, but cost-bounded.
2. **Score correction on outcome supersession.** When a `resolved_final`
   outcome is later superseded (e.g. user discovers it was wrong), the
   prior `forecast_scores` row is logically stale. MVP behavior: leave
   the prior score row in place (append-only invariant on
   `forecast_scores`), append a new score row triggered by the
   superseding outcome, and rely on the `outcomes`-side supersedes edge
   to make "current score" derivable (latest score whose
   `metadata_json.outcome_id` resolves to a non-superseded outcome). A
   `score_status` column is rejected to avoid mutable state on
   `forecast_scores`.
3. **Multi-step decision scoring.** Some agents make a series of decisions
   on the same forecast (entry, add, hold, exit). Should each get an
   independent calibration score, or only the entry forecast? MVP scores
   only the entry forecast; per-decision calibration is a P1 question.
4. **Alternative bin policies.** §7.2 ships equal-width 0.1 bins. Some
   forecasting literature prefers equal-mass (deciles of the empirical
   probability distribution) bins to avoid empty-bin instability when
   forecasts cluster. P1 candidate, additive — `meta.bin_policy`
   already reports the policy in use, so adding alternatives does not
   break callers.
