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
explicitly identify which of the two outcome labels is YES. If `yes_label`
is omitted, the scorer applies the following heuristic on resolution:

1. If one label exactly matches `"YES"` (case-insensitive), it is YES.
2. Else if one label exactly matches `"TRUE"` (case-insensitive), it is YES.
3. Else if exactly one label matches the resolved `outcomes.outcome_label`,
   that label is YES.
4. Otherwise, scoring returns `SCORING_NOT_READY` with
   `details.reason = "yes_label_ambiguous"`. The caller must record an
   explicit `yes_label` via `forecast.set_yes_label` to score.

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
score?

Values:

- `pending`: created, awaiting resolution or scoring.
- `scored`: a `forecast_scores` row exists; the forecast is graded.
- `failed`: scoring was attempted and produced a structured failure
  (e.g. label mismatch on resolution, ambiguous YES label, outcome row
  superseded mid-scoring). The failure reason is recorded on the
  corresponding `forecast_scores` row with `score = NULL` and
  `metadata_json.failure_reason`.
- `superseded`: the forecast has been replaced by a newer version (via the
  `parent_thesis_id` chain or explicit `forecast.supersede` call). The old
  forecast is no longer scored.

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
corrections produce a new row and use a `supersedes` edge to mark the older
row inactive. Each row carries an explicit `status`:

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

## 7. Future Scoring Kinds (P1+)

The schema deliberately reserves room for future scorers without migration:

- `forecast_scores.metric` is a string column. Future metrics can be added
  by extending the scorer registry; no schema change required.
- `forecasts.kind` already accepts `categorical` and `scalar` per PRD §3.1.
  Their `scoring_support` is `unsupported` in MVP; once a multi-class or
  CRPS scorer ships, the support flag flips and a rescan picks them up.
- Potential P1 metrics: `brier_multiclass`, `log_score`, `crps`,
  `interval_score`. Each one will get its own short section in this doc
  when implemented.

## 8. Open Questions

1. **Rescan after scorer upgrade.** When P1 adds a scorer for categorical
   forecasts, do we eagerly rescan all `pending unsupported` forecasts, or
   lazily upgrade them on next read? Likely eager via
   `journal.rescan_scoring`, but cost-bounded.
2. **Score correction.** If a `resolved_final` outcome is later superseded
   (e.g. user discovers it was wrong), do we delete the old
   `forecast_scores` row or supersede it? Almost certainly supersede; the
   exact mechanism (event-driven retract vs. an additional `score_status`
   column) is TBD.
3. **Multi-step decision scoring.** Some agents make a series of decisions
   on the same forecast (entry, add, hold, exit). Should each get an
   independent calibration score, or only the entry forecast? MVP scores
   only the entry forecast; per-decision calibration is a P1 question.
