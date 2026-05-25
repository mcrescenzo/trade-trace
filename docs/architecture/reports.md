# Reports: Filters, Drill-Down, Compare, Bundles

> Status: **shipped**. `ReportFilter` / `ReportResult` / drill-down / `review.bundle` describe the live report surface.


**Implementation status (v0.0.2 PM pivot):** shipped: report.calibration,
report.calibration_anchored, report.calibration_terminal,
report.calibration_trajectory, report.calibration_integrity,
report.forecast_diagnostics,
report.book, report.risk, report.audit, report.lifecycle,
report.recall, report.work_queue, report.bootstrap, report.coach,
report.strategy_health, report.compare, report.policy_candidates,
report.filter_schema, report.market_lifecycle,
report.resolution_quality, report.amm_slippage, and
report.time_decay_sharpening. Legacy report names such as
report.pnl, report.watchlist, report.open_positions,
report.current_exposure, report.exposure_anomalies,
report.audit_readiness, report.source_quality,
report.playbook_adherence, report.recall_receipts,
report.memory_usefulness, report.strategy_performance,
report.opportunity,
report.unscored_forecasts, and report.decision_velocity are retained
only as hidden/legacy compatibility metadata or consolidated into the
reports above. Deferred (post-v0.0.2): trading-native
calibration-by-liquidity-bucket, skipped-positive-edge review, and
broader replay/evaluation surfaces.

Current-vs-target audit note (trade-trace-0rxr): the live registry still
includes `report.mistakes` and `report.strengths`, but their shipped
implementation is narrower than the earlier product target. They are
legacy-compatible tag aggregate reports over decision tags with scored
forecast Brier ranking, not the broader decision+review tag
count/co-occurrence contract. See §4.3 for the exact shipped behavior and
the deferred target.

Companion docs: [PRD.md](../PRD.md), [VISION.md](../VISION.md),
[scoring.md](scoring.md), [persistence.md](persistence.md),
[contracts.md](contracts.md), [memory-layer.md](memory-layer.md),
[policy-evidence-bundles.md](policy-evidence-bundles.md), and
[replay-case-bundles.md](replay-case-bundles.md).

## 1. Purpose

PRD §4.2 lists deterministic reports but does not specify the shared
filter shape, the drill-down envelope, or the per-report return schemas.
This doc fills that gap.

The driving principle: **every aggregate must carry the filter spec
that produced it and the contributing record IDs.** An agent that runs
`report.calibration` and sees "decisions tagged `liquidity-ignored` are
worst-calibrated" must be able to fetch the exact decisions without
guessing what filter the report applied. That round-trip is the
contract.

## 2. `ReportFilter`

`ReportFilter` is the shared input shape for every read/report tool.
Pydantic-validated; unknown fields rejected; empty arrays mean "no
filter on this field"; `null` means "unset."

```jsonc
{
  "time_window": {
    "created_at_gte": null,         // ISO 8601 UTC
    "created_at_lt": null,
    "decision_at_gte": null,        // decisions.created_at
    "decision_at_lt": null,
    "resolved_at_gte": null,        // outcomes.resolved_at
    "resolved_at_lt": null
  },
  "actors": {
    "actor_id": [],
    "agent_id": [],
    "model_id": [],
    "environment": [],              // paper|actual_recorded|simulation|backtest_import|manual_review
    "run_id": []
  },
  "strategy": {
    "strategy_id": null,            // single id, slug, "__none__", or null
    "playbook_id": [],
    "playbook_version_id": []
  },
  "instrument": {
    "venue_id": [],
    "venue_kind": [],
    "instrument_id": [],
    "asset_class": [],
    "symbol": []
  },
  "decision": {
    "decision_type": [],            // any of the 13 decisions.type values
    "side": [],
    "tags_any": [],                 // OR over tag set
    "tags_all": [],                 // AND over tag set
    "has_thesis": null,             // tri-state: null|true|false
    "has_forecast": null,
    "has_reflection": null,
    "has_playbook_adherence": null
  },
  "market_context": {
    "spread_bucket": [],            // "tight"|"medium"|"wide" (deterministic banding; see §6)
    "liquidity_bucket": [],         // "thin"|"medium"|"deep"
    "volume_bucket": [],            // "low"|"medium"|"high"
    "market_regime_tag": []         // free-form tags from snapshot metadata
  },
  "outcome": {
    "resolution_status": [],        // any of outcomes.status values
    "scoring_state": [],            // any of forecasts.scoring_state values
    "score_gte": null,              // brier_binary lower bound
    "score_lt": null,
    "include_late_recorded": false  // see dogfood-protocol.md §2.2: false (default) excludes late-recorded forecasts from calibration aggregates; true includes them with caveat
  },
  "source": {
    "source_kind": [],
    "source_stance": [],            // supports|contradicts|neutral
    "source_freshness_before_decision": null  // bool: was source.freshness_at <= decision.created_at?
  }
}
```

### 2.1 Rules

- All keys are optional; the canonical empty filter `{}` matches every
  row.
- Strings in array fields are case-sensitive enum or slug values; the
  server lowercases known enums on receipt for tolerance.
- `strategy.strategy_id` honors the §2.12 sentinel: omitted or `null`
  applies no strategy filter; `"__none__"` selects rows whose
  `strategy_id IS NULL`; any other string is treated as a single
  strategy id or slug (slug resolved server-side).
- Time fields are UTC ISO 8601 with millisecond precision per
  [operability.md](operability.md) §2.
- Filters compile to parameter-bound SQL only; no string interpolation
  of caller values into queries. Unknown fields are rejected with
  `VALIDATION_ERROR`.
- `tags_any` and `tags_all` may both be set: a row matches when
  `(decision_tags ∩ tags_all == tags_all) AND (decision_tags ∩ tags_any ≠ ∅)`.
- `report.calibration` applies `actors.actor_id`, `actors.agent_id`,
  `actors.model_id`, `actors.environment`, and `actors.run_id` against
  scored forecasts. `report.compare(base_report="calibration")` may group
  by the same actor/run fields. Reports that do not list these fields in
  `_filter_support.SUPPORTED_FILTER_FIELDS` reject them instead of silently
  broadening the result.

### 2.2 Round-trip and `report.filter_schema`

The filter must round-trip through JSON without semantic loss. The
`report.filter_schema` tool returns the Pydantic-generated JSON Schema
so agents can introspect valid fields, types, and enum values without
reading these docs.

## 3. `ReportResult` and `ReportGroup`

Every report returns an envelope of this shape:

```jsonc
{
  "ok": true,
  "data": {
    "summary": {
      "sample_size": 42,
      "sample_warning": null,           // null or human-readable string
      "filter": { /* echoed ReportFilter */ },
      "metrics": { /* report-specific top-level metrics */ }
    },
    "groups": [
      {
        "key": "liquidity_ignored",
        "label": "Decisions tagged liquidity-ignored",
        "metrics": { /* per-group metrics */ },
        "filter": { /* sub-filter that selects this group */ },
        "record_ids": {
          "decisions": ["d_..."],
          "forecasts": ["f_..."],
          "outcomes": ["o_..."],
          "sources": ["s_..."]
        },
        "examples": [                   // up to max_examples (default 3)
          {
            "kind": "decision",
            "id": "d_...",
            "summary": "skip on NVDA prediction, spread > expected edge"
          }
        ],
        "sample_size": 12,
        "sample_warning": null,
        "truncated": false              // true if record_ids was trimmed
      }
    ],
    "drilldowns": [                     // optional callouts the report wants to highlight
      {
        "label": "Worst Brier in thin-liquidity markets",
        "filter": { /* targeted sub-filter */ },
        "record_ids": { /* a slice of the contributing IDs */ }
      }
    ]
  },
  "meta": {
    "tool": "report.calibration",
    "contract_version": "1.0",
    "request_id": "...",
    "bin_policy": "equal_width_0.1",
    "truncated": false,
    "next_cursor": null
  }
}
```

### 3.0 Shared backend report-contract conventions

These conventions are the reusable contract for every backend report,
including period review and process analytics surfaces. They define the
stable JSON shape that agents can parse before any report-specific metric
schema is considered.

**Versioning and compatibility.** Every report envelope MUST carry
`meta.contract_version`. MVP report contracts use `"1.0"`. Additive,
optional fields are backward-compatible within the same major version;
renaming/removing fields, changing field types, changing metric meanings,
or changing unsupported-data semantics requires a major version bump and a
deprecation window. Report-specific `data.contract_version` MAY be present
when the payload is embedded elsewhere, but `meta.contract_version` is the
transport-level authority.

**Requested vs applied scope.** Reports MUST distinguish caller intent from
the actual computation:

- `data.requested_scope` (or a report-specific equivalent such as
  `data.filter` for legacy reports) echoes the caller's requested
  `ReportFilter`, requested sections, features, groupings, limits, and
  cursors after schema validation.
- `data.applied_scope` / `data.applied_filter` records the exact filter and
  report options used for every aggregate. If the report accepts only a
  subset of the request, the applied scope MUST be narrower-or-equal to the
  requested scope and the unsupported portions MUST be listed explicitly.
- A report MUST NOT return a global report while echoing a scoped filter.
  If a requested filter path cannot be honored, reject it or emit
  machine-readable unsupported metadata; never silently ignore it.

**Filter, section, and feature support.** Each report MUST expose support
metadata either in success `data` or validation-error `error.details`:

- `supported_filter_paths`: canonical dot paths the report can actually
  apply, such as `actors.actor_id` or `time_window.decision_at_gte`.
- `unsupported_filter_paths`: requested non-empty paths that were not
  applied. Current strict reports reject these with `VALIDATION_ERROR`;
  future exploratory reports may return `ok: true` only if every ignored
  path is present here and no aggregate claims to reflect it.
- `supported_sections` / `unsupported_sections`: requested report sections
  that can or cannot be computed.
- `supported_features` / `unsupported_features`: requested analytic
  features, grouping dimensions, attribution modes, model panels, or
  diagnostics that can or cannot be computed.

Unsupported and insufficient-data entries are machine-readable objects, not
free text only. Minimum shape:

```jsonc
{
  "path": "decision.tags_all",          // or section/feature name
  "reason_code": "unsupported_filter_path",
  "message": "report.period_review cannot apply decision.tags_all",
  "requested_value": ["liquidity-ignored"],
  "applied": false
}
```

**Mandatory unsupported-analytics invariant.** If a report cannot
truthfully compute a requested section, feature, metric, grouping, or
filter, it MUST emit machine-readable `unsupported_*` or
`insufficient_data` metadata instead of silently omitting the item,
zero-filling it, fabricating an empty aggregate, or returning an unscoped
global result while echoing the requested scope.

**Caveats, low-N, and coverage.** Reports MUST make reliability limits
parseable:

- `caveat_codes`: stable strings for caveats such as
  `LOW_SAMPLE_SIZE`, `PARTIAL_COVERAGE`, `REDACTED_SOURCE_CONTENT`,
  `LATE_RECORDED_EXCLUDED`, `LOCAL_ROWS_ONLY`, or
  `DIAGNOSTIC_ONLY_NO_CAUSAL_CLAIM`.
- `sample_warning`: human-readable warning mirrored in `meta.sample_warning`
  when a report-level sample threshold is missed.
- `coverage`: per-section/per-metric counts such as
  `{eligible_count, included_count, missing_count, coverage_pct,
  denominator_kind}`. Low-N and missing-coverage conditions MUST be caveats,
  not hidden in prose.
- If metrics are suppressed because N or coverage is too low, emit the
  metric key with `null` plus `insufficient_data` metadata, or place the
  metric under `unsupported_features`; do not use `0` as a placeholder for
  unknown/uncomputed values.

**Contributing IDs.** Every aggregate metric MUST include the contributing
record IDs needed to reproduce it, following the existing
`record_ids.{decisions,forecasts,outcomes,sources,...}` convention. If IDs
cannot be made available, the report MUST emit a machine-readable reason:

```jsonc
{
  "metric": "mean_brier",
  "record_ids_unavailable": {
    "reason_code": "not_materialized_in_read_model",
    "record_kind": "forecast_scores",
    "reproducible_by_filter": true,
    "filter": { /* exact applied sub-filter */ }
  }
}
```

**Stable JSON shape.** Reports SHOULD prefer stable keys with `null`, empty
arrays, or explicit status objects over shape-shifting omission. Arrays MUST
have deterministic ordering. Examples in this document are contract
examples: new reports should preserve the same envelope, support metadata,
caveat, coverage, contributing-ID, truncation, and boundary fields even when
their metrics differ.

**Truncation and cursoring.** Truncation MUST be explicit at the smallest
affected level (`groups[].truncated`, section `truncated`, and/or
`meta.truncated`). `next_cursor` is opaque and stable for the same database
snapshot, request, and ordering. Truncated ID lists MUST still include the
applied sub-filter that can enumerate the full set. Cursors paginate result
presentation only; they MUST NOT change the metric denominator unless the
report explicitly documents page-local metrics.

**Redaction and source handling.** Report source projections follow
`review.bundle` §5.3: `sensitive` sources are omitted with caveat codes and
counts; `redacted` sources keep provenance metadata but strip content fields;
`none` sources may include content after the secret-pattern scan. Metrics
that depend on source text MUST declare redacted/sensitive coverage and emit
`insufficient_data` when redaction prevents truthful computation.

**Local read-only boundaries.** Backend reports are deterministic analyses
over local stored rows. They MUST NOT fetch external market/source/outcome
data, call brokers, inspect wallets, place/cancel orders, execute trades,
schedule alerts, generate trading advice, emit buy/sell/hold signals, claim
alpha/edge, or make profit claims. Reports may describe historical local
records and process diagnostics only.

Example success skeleton for a future scoped report:

```jsonc
{
  "ok": true,
  "data": {
    "requested_scope": {"filter": {"actors": {"agent_id": ["agent-a"]}}, "sections": ["coverage", "mistakes"]},
    "applied_scope": {"filter": {"actors": {"agent_id": ["agent-a"]}}, "sections": ["coverage"]},
    "supported_filter_paths": ["actors.agent_id", "time_window.decision_at_gte"],
    "unsupported_filter_paths": [],
    "supported_sections": ["coverage"],
    "unsupported_sections": [
      {"section": "mistakes", "reason_code": "insufficient_scored_forecasts", "minimum": 20, "actual": 3, "applied": false}
    ],
    "supported_features": ["group_by_agent"],
    "unsupported_features": [],
    "coverage": {"eligible_count": 12, "included_count": 12, "missing_count": 0, "coverage_pct": 100.0, "denominator_kind": "decisions"},
    "caveat_codes": ["LOCAL_ROWS_ONLY", "LOW_SAMPLE_SIZE"],
    "summary": {"sample_size": 12, "sample_warning": "only 3 scored forecasts; mistakes panel requires 20"},
    "groups": [{"key": "agent-a", "metrics": {"decision_count": 12}, "record_ids": {"decisions": ["dec_..."]}, "truncated": false}]
  },
  "meta": {"tool": "report.period_review", "contract_version": "1.0", "truncated": false, "next_cursor": null}
}
```

### 3.1 Drill-down rule

A report MUST populate `groups[].record_ids` for every metric it
exposes. If a metric is a count or aggregate over rows, those exact
rows must be enumerable from the report response. The pattern is:

1. Agent runs `report.X(filter=F)`.
2. Agent identifies a worst group `g`.
3. Agent calls a list tool (e.g. `decision.list(filter=groups[g].filter)`)
   and gets the same record set the report aggregated.

This round-trip is a verified golden test for every report.

### 3.2 Sample-size warnings

When `sample_size` falls below the report's minimum:

- `summary.sample_warning` (and `meta.sample_warning`) is set to a
  short human-readable string (`"only 7 scored forecasts; calibration
  is unreliable below 20"`).
- Numerical metrics still compute but are flagged.

Per-report minimums:

| Report | Minimum (default, configurable) |
|---|---|
| `report.calibration` | 20 scored binary forecasts |
| `report.forecast_diagnostics` | 20 scored binary forecasts |
| `report.mistakes` / `report.strengths` | 10 tagged decisions |
| `report.pnl` | 5 closed positions |
| `report.playbook_adherence` | 10 decisions with adherence rows |
| `report.compare` | each group must hit its own report's minimum independently |
| `report.opportunity` | per [opportunity-analysis.md](opportunity-analysis.md) |
| `report.risk` | per [risk-units.md](risk-units.md) |

Thresholds are read from `config.report.<tool>.min_sample` with the
above defaults.

### 3.3 Truncation and cursoring

When `groups[].record_ids[*]` would exceed `max_record_ids_per_group`
(default 1000, configurable per call), the array is truncated and
`groups[].truncated = true`. The agent uses the corresponding sub-filter
to enumerate the full set via the relevant list tool.

When the **number of groups** exceeds `max_groups` (default 100), the
top-N-by-`sample_size`-then-by-`key` groups are returned, and the meta
envelope sets `truncated: true` plus `next_cursor: "<opaque>"` so the
caller can request the next page. Ordering is stable across pages.

## 4. Per-Report Metric Schemas

### 4.1 `report.calibration`

See [scoring.md](scoring.md) §7 for the full panel: Brier, log score,
ECE, sharpness, baseline (prevalence, Brier-baseline, log-score-baseline,
skill), reliability bins.

Groups: by default, one group; group-by is via `report.compare` (§4.7).
The single-group case still emits `groups[]` for shape uniformity.

**Late-recorded filter (default exclusion).** Per
[`dogfood-protocol.md`](dogfood-protocol.md) §2.2, every score row
whose forecast does not satisfy the "pre-outcome" condition is stamped
with `forecast_scores.metadata_json.late_recorded = true`.
`report.calibration` excludes those rows from every aggregate metric
unless the filter's `outcome.include_late_recorded` is `true`. The
summary always reports `data.summary.late_recorded_excluded` (integer
count) and adds a caveat to `data.caveats[]` when any were excluded.

**Embedded integrity panel (MVP hardening, bead trade-trace-jzn).** Every
`report.calibration` envelope also carries `data.integrity_diagnostics`
— the same shape that `report.calibration_integrity` (§4.8) emits as a
standalone surface. The embed exists so an agent reading the calibration
panel cannot ignore the denominator/hygiene context. See §4.8.

### 4.2 `report.forecast_diagnostics`

Binary-first retrospective report over local forecasts, scored outcomes,
decisions/non-actions, and caller-supplied snapshots. The scored diagnostic
sample includes only binary forecasts with a usable YES probability; non-binary
or otherwise unsupported forecasts are excluded from scored metrics and listed
under `summary.exclusions.counts_by_reason` plus bounded forecast IDs.

The market/reference panel uses only stored `snapshots.implied_probability`
linked through local decisions. It reports the agent probability minus that
stored value as `recorded_market_reference_gap`/`mean_recorded_market_reference_gap`;
this is a caller-supplied retrospective reference comparison, not a trading
signal, advice, alpha, opportunity ranking, or profitability evidence. If no
implied probability is stored, the report emits
`missing_market_reference`; it does not derive a probability from price fields
and does not fetch market data. Spread and liquidity coverage are reported as
coverage counts/caveat codes rather than inferred quality thresholds.

The base-rate/reference panel reuses the local scored binary sample prevalence
and calibration metrics where enough resolved outcomes exist. Low-N and
`baseline_unavailable` caveats are explicit. Decision coverage includes counts
by decision type, including non-actions such as `watch`, `skip`, `hold`, and
`review`, plus drill-down IDs for forecasts, decisions, snapshots, outcomes,
forecast scores, and strategies where applicable.

### 4.3 `report.mistakes` / `report.strengths`

Current shipped behavior: these compatibility reports group by
`decision_tags` only and rank tags by mean binary Brier score from scored
forecasts attached to the tagged decisions. `report.mistakes` orders worst
mean Brier first; `report.strengths` orders best mean Brier first.
Per-group metrics are `decision_count`, `scored_forecast_count`, and
`mean_brier`; drill-down IDs include contributing decisions and forecasts.
Decisions without a scored forecast still contribute to `decision_count`
and decision drill-down IDs but not to `mean_brier`.

Filter support is intentionally empty today: non-default `ReportFilter`
fields are rejected rather than silently ignored.

Deferred target behavior from older product language: broader tag counts,
tag co-occurrence, and conditional outcome rates across both decisions and
reviews (`review_tags`). That broader decision+review tag aggregate is not
shipped by the current implementation and must be tracked as follow-up
implementation work before docs can describe it as live behavior.

### 4.3 `report.pnl`

Per-group P&L roll-up. Per-group metrics: realized P&L, unrealized P&L,
mark-to-market P&L using latest snapshots, count of closed positions,
data_coverage (`positions_with_marks / total_positions`). Groups are
typically by `agent_id`, `model_id`, `strategy_id`, or `instrument_id`
depending on the caller's `group_by`.

### 4.4 `report.watchlist` (stale-watch surface; rolled in the historical `watch.stale` name per trade-trace-ftnu)

Lists `watch` decisions. Per-row metrics: `created_at`, `review_by`,
`age_days`, `overdue`. Per bead trade-trace-gbtj, `watch` decisions
accept first-class UTC ISO `review_by` deadlines (matrix kind `O`); a
row is `overdue=True` when `review_by <= as_of`. The summary echoes
`overdue_count`. `mode='stale'` filters rows by *age* against
`stale_threshold_days` (default 14) and remains independent of
`overdue` — a watch can be one, both, or neither.

### 4.5 `report.unscored_forecasts`

Lists forecasts past `resolution_at` with no `forecast_scores` row.
Per-row: forecast, days past resolution, outcome status if any.

### 4.6 `report.playbook_adherence`

Group by playbook version. Per-group: counts of self-reported
`decision_playbook_rules.status` values (`considered`, `followed`,
`overridden`, `not_applicable`); override-outcome breakdown where
outcomes exist. The report also includes an audit-only `predicate_audit`
section at summary and group level. This section evaluates explicit
`memory_nodes.metadata_json.predicate` metadata (legacy fallback:
`memory_nodes.meta_json.predicate`) through the closed-set
predicate evaluator and reports machine-checkable statuses (`pass`,
`fail`, `not_computable`, `ambiguous`, `not_applicable`), alignment
labels, mismatches, missing/unresolved metadata, record refs, source refs,
and caveats. Predicate audit is deterministic and read-only: it does not
parse rule prose, block execution, place trades, mutate playbooks, or
provide advice.

### 4.7 `report.compare`

Inputs:

- `filter`: a `ReportFilter` defining the baseline candidate set.
- `group_by`: allowlisted per base report. For `base_report='calibration'`:
  `actor_id`, `agent_id`, `model_id`, `run_id`, `strategy_id`,
  `decision_type`, `venue_id`, `asset_class`, `environment`,
  `instrument_id`, `outcome_status`, `status`. For `base_report='pnl'`:
  `instrument_id`, `status`, `venue_id`, `asset_class`.
- `base_report`: the underlying report whose metrics to compute per
  group. Current shipped implementation supports `calibration` and `pnl`.
  Other planned kernels (`mistakes`, `playbook_adherence`) remain deferred.

Output: a `ReportResult` whose `groups[]` is one entry per distinct
value of `group_by`, each with the `base_report`'s metric set. Each
group carries its own sub-filter for drill-down. Sample warnings are
per group; the summary aggregates over all groups.

### 4.7.1 `report.strategy_performance` (shipped wrapper)

Decision for trade-trace-4md: this is implemented as a convenience
wrapper over `report.compare(base_report='pnl', group_by='strategy_id')`,
not as a separate metric stack. Optional `strategy_id` narrows to one
strategy; omission compares all strategies and includes the `__none__`
no-strategy bucket when positions cannot be traced to a strategy-linked
decision.

### 4.8 `report.calibration_integrity` (MVP hardening)

Six anti-goodhart hygiene diagnostics over the journal. The same shape
is embedded inside `report.calibration.data.integrity_diagnostics`; the
standalone tool exists for agents that want the panel without recomputing
calibration metrics. Diagnostics:

1. `forecast_coverage` — `{total_decisions, total_forecasts,
   scored_forecasts, denominator_coverage_pct}`. The denominator-truth
   block: no other metric is interpretable without it.
2. `unsupported_rate` — forecasts with `scoring_support='unsupported'`
   (categorical/scalar in MVP, awaiting the P1 scorer).
3. `ambiguous_rate` — outcomes with `status='ambiguous'`.
4. `disputed_rate` — outcomes with `status='disputed'`.
5. `void_cancelled_rate` — combined for `status in (void, cancelled)`.
6. `suspicious_late_rate` — forecasts whose `created_at` is after a
   matching outcome's `resolved_at` (post-hoc bias indicator).

Each diagnostic returns `{count, total, rate_pct, sample_ids,
truncated}`. The framing is hygiene-not-fraud per scoring.md §9: the
goal is to make the panel honest about its denominator, not to second-
guess intent. Empty journal returns `summary.sample_warning="no_data"`.

Source: bead trade-trace-jzn.

### 4.9 `report.source_quality` (MVP hardening)

Five provenance hygiene diagnostics over the legacy source-attachment graph and
the v0.0.2 inline provenance projections. During the additive PM-source
transition, source-quality readers count direct forecast/decision/memory-node
source edges and `metadata_json.sources` arrays, with legacy thesis-edge
fallback for old journals:

1. `missing_sources_on_actual_enter` — `actual_enter` decisions with no direct
   decision/forecast/inline provenance and no linked-thesis legacy source
   attachments.
2. `stale_sources` — sources whose `freshness_at` predates the linked
   decision's `created_at` by more than `stale_threshold_days` (default
   7). The live diagnostic only considers rows where `sources.freshness_at`
   is set; `sources.retrieved_at` is retrieval/provenance time and is not a
   fallback for evidence freshness.
3. `contradictory_sources` — theses with both `supports` and
   `contradicts` edges from sources of the same `kind`.
4. `duplicated_sources` — source rows with the same `content_hash`
   attached to the same target more than once.
5. `sensitive_sources` — sources with `redaction_status='sensitive'`
   that show up in the attachment graph (the `review.bundle` path
   strips these per §5.3; the diagnostic surfaces them so agents know
   which edges operate against a blank-out).

Each diagnostic returns `{count, sample_ids, samples, truncated}`. The
report is intentionally global (no `ReportFilter` input): provenance
hygiene is a journal-level diagnostic, not a per-strategy slice. No external
fetching, no credibility scoring.

Source: bead trade-trace-l9q.

### 4.10 `report.audit_readiness` (prediction/event-market readiness)

Read-only local audit diagnostics for prediction/event-market journal arcs.
The report is deterministic SQL over existing journal tables: it never
fetches market data, never scores source credibility, and never gives
trading advice.

Inputs:

- `stale_snapshot_threshold_days`: non-negative integer, default `1`.
- `stale_source_threshold_days`: non-negative integer, default `7`.

Output:

```jsonc
{
  "summary": {
    "sample_size": 1,              // actual_enter + paper_enter decisions
    "blocking_count": 2,
    "warning_count": 3,
    "info_count": 1,
    "ready": false,               // true only when sample_size > 0 and no blocking issues
    "sample_warning": null,        // "no_data" when no entered decisions exist
    "stale_snapshot_threshold_days": 1,
    "stale_source_threshold_days": 7
  },
  "issues": [
    {
      "check": "missing_resolution_rule_provenance",
      "severity": "blocking",     // blocking | warning | info
      "count": 1,
      "sample_ids": {"forecasts": ["fc_..."]},
      "samples": [/* bounded examples with contributing IDs */],
      "truncated": false
    }
  ]
}
```

Current checks:

- `blocking`: missing resolution-rule/criteria provenance for
  `prediction_market` / `event_market` forecasts, missing snapshot on
  entered decisions, weak decision provenance, and contradictory thesis
  sources.
- `warning`: stale linked snapshots, missing bid/ask/spread/depth market
  microstructure, and stale attached sources.
- `info`: missing source retrieval metadata and missing agent/model/run
  segmentation metadata.

Source: bead trade-trace-r566.

### 4.11 `report.lifecycle` (derived decision/non-action lifecycle)

Read-only derived cases over local journal rows. This report cites source
refs and reason/caveat codes so a stateless agent can inspect unfinished
local process state before adding another thesis, forecast, decision,
outcome, reflection, or adherence row. It never persists lifecycle state,
fetches outcomes, checks broker/exchange truth, schedules follow-up, or
produces advice.

Inputs:

- `as_of`: UTC read boundary for deterministic due/stale checks.
- `stale_threshold_days`: non-negative integer; default follows the
  watchlist stale threshold.
- `states`: optional list of lifecycle states. CLI uses `--states-json`.
- `filter`: supported `ReportFilter` fields are applied; unsupported
  non-empty fields are rejected.

Examples:

```bash
tt report lifecycle --home <journal-home> --as-of 2026-05-22T00:00:00Z --states-json '["pending_review","stale"]'
```

```json
{"tool":"report.lifecycle","args":{"as_of":"2026-05-22T00:00:00Z","states":["pending_review","stale"],"filter":{"instrument":{"instrument_id":["ins_..."]}}}}
```

Case snippet:

```json
{
  "case_id": "derived:forecast:fc_123:lifecycle",
  "state": "pending_review",
  "source_refs": [{"kind": "forecast", "id": "fc_123"}, {"kind": "instrument", "id": "ins_456"}],
  "due_at": "2026-05-21T00:00:00Z",
  "reason_codes": ["forecast_scoring_state:pending", "resolution_at_due_without_score"],
  "caveat_codes": ["missing_source_ref"]
}
```

Forbidden interpretations: not a durable lifecycle table, scheduler,
daemon, reminder, assignment queue, human dashboard workflow, trading
signal/ranking/advice, profit claim, broker truth, wallet/execution path,
or permission to fetch live market/source/outcome data.

### 4.12 `report.recall_receipts`

Read-only computed receipt over `memory_recall_events`, `memory_nodes`, and typed `edges`. It does not create a durable receipt table. It answers: what memories were returned, which scoped downstream consumer linked back to them, and which attribution caveats apply.

Inputs:

- `recall_id`, `node_id`: optional point filters.
- `consumer_kind`, `consumer_id`: downstream consumer scope. `consumer_id` requires `consumer_kind`; strong attribution requires both.
- `run_id`, `agent_id`, `model_id`, `environment`: actor/run segmentation from the recall event.
- `instrument_id`, `strategy_id`: filters against recall context.
- `as_of`: bounds recall events and edge evidence by `created_at`.
- `limit`: positive integer event limit.

Item conventions mirror [memory-layer.md §9.1](memory-layer.md#91-downstream-recall-use-and-citation-conventions): `status` is `cited_or_used` when a consumer-to-memory `supports`, `derived_from`, `about`, `follows`, or `violates` edge exists, otherwise `ignored_or_unattributed`. `attribution_status` narrows the reason to `cited_or_used`, `contradicted`, `stale`, or `not_attributable`. `source_refs` from `memory_node -> source` never count as downstream use. Unscoped inference carries `CONSUMER_INFERENCE_UNSCOPED`; stale/invalidated nodes, contradiction edges, and supersession edges carry explicit caveat codes.

Forbidden interpretations: not a generic transcript memory store, durable receipt table, task queue, dashboard workflow, trading signal/ranking/advice, profit claim, broker/execution/wallet path, or permission to fetch live/external data.

### 4.13 `report.strategy_health`

Read-only local process-health report across strategy rows. It defaults to
active strategies and emits administrative review context only: it does not
rank strategies by performance, recommend trading more or less, fetch market
data, infer edge/profit, or create durable strategy lifecycle state.

Inputs:

- `status`: `active` by default; accepts `active`, `archived`, or `all`.
- `as_of`: optional UTC read boundary for review-due checks; pass it for
  reproducible output.
- `min_sample`: positive integer for low-N caveats.
- `filter`: supports strategy id/slug, actor/run/model/environment, and
  `created_at_*` windows. Unsupported non-empty fields are rejected rather
  than silently broadened.

Outputs include one group per matching strategy, ordered by due-review then
slug/id. Each group carries `sections` with `{count, record_ids}` for
decisions, review-due decisions, open unresolved forecasts, thesis
source-reference gaps, repeated overrides (only surfaced once at least two
override decisions exist), and policy-candidate support status. Source-quality
checks are intentionally limited to missing thesis source references; broader
source freshness/contradiction diagnostics remain in `report.source_quality`.
Policy candidate support status is sourced from the shipped read-only
`report.policy_candidates` local surface over reflection `memory_nodes` with
`metadata_json.policy_candidate` (legacy fallback: `meta_json.policy_candidate`);
it remains caveated and does not promote or mutate policy/playbook state.

Forbidden interpretations: not a strategy ranking, performance leaderboard,
signal/edge detector, trading advice, policy promotion engine, scheduler,
broker/execution/wallet path, or permission to fetch live/external data.

### 4.14 `report.memory_usefulness`

Read-only diagnostic projection over `report.recall_receipts` plus returned memory-node metadata and downstream typed edge evidence. It is a caveated evidence view only: it does not estimate causal memory value, optimize memory, score agents/models, rank trades, make profit claims, or provide advice.

Inputs mirror `report.recall_receipts` and add `memory_kind` (`observation`, `reflection`, `playbook_rule`) for node-type slicing. Supported slices/groups include strategy and instrument from recall context; agent, model, run, and retrieval strategy from the recall event; memory kind; confidence bucket; age bucket; and citation/use status. Age/decay/confidence fields are emitted when available on `memory_nodes`; outcome impact is reported as not measurable unless explicit local edge evidence supports a narrow caveated control.

The report always includes explicit negative controls:

- `recalled_unused`: returned memories without downstream use/citation edge evidence.
- `used_contradicted`: used memories that also have downstream contradiction evidence.
- `stale_retrieved`: invalidated or stale memories returned by recall.
- `high_confidence_bad_outcome`: edge-based only; flagged from high-confidence memories with explicit contradictory/harmful edge evidence, not from inferred outcomes.
- `missing_expected_memory`: currently `not_measurable` unless a local expected-memory signal exists; no expectation is invented.
- `overfit_harmful`: edge-based only from explicit harmful/violation edge evidence.

Outputs include `summary.metrics`, `groups`, `memory_diagnostics`, `negative_controls`, `source_refs`/receipt refs, and `caveat_codes` such as `DIAGNOSTIC_ONLY_NO_CAUSAL_CLAIM`, `OUTCOME_IMPACT_NOT_INFERRED`, `NO_EXPECTED_MEMORY_SIGNAL`, and edge-specific caveats.

Forbidden interpretations: not a durable usefulness table, generic memory framework, reward/scoring signal, model optimization target, task queue, dashboard workflow, trading signal/ranking/advice, profit claim, broker/execution/wallet path, or external/live fetch path.

### 4.15 `report.work_queue`

`report.work_queue` projects selected lifecycle states into transient
process-obligation items. This is the current replacement for the removed
legacy `agent.next_actions` alias. It is for external agents/orchestrators
to inspect and choose from; Trade Trace does not claim, assign, schedule,
notify, retry, or execute the items.

Inputs:

- `as_of`, `stale_threshold_days`, and `filter` as above.
- `kinds`: optional list of work kinds. CLI uses `--kinds-json`.

Examples:

```bash
tt report work_queue --home <journal-home> --as-of 2026-05-22T00:00:00Z --kinds-json '["resolve_due_forecast","record_reflection"]'
tt report work_queue --home <journal-home> --as-of 2026-05-22T00:00:00Z --kinds-json '["review_due_watch","record_playbook_adherence"]'
```

```json
{"tool":"report.work_queue","args":{"as_of":"2026-05-22T00:00:00Z","kinds":["resolve_due_forecast"],"filter":{"actors":{"run_id":["run-2026-05-22"]}}}}
```

```json
{"tool":"report.work_queue","args":{"as_of":"2026-05-22T00:00:00Z","kinds":["record_reflection","record_playbook_adherence"]}}
```

Item snippet:

```json
{
  "item_id": "derived:work_queue:record_reflection:decision:dec_123",
  "kind": "record_reflection",
  "priority": "due",
  "source_refs": [{"kind": "decision", "id": "dec_123"}, {"kind": "outcome", "id": "out_456"}],
  "allowed_actions": ["inspect_outcome_review_and_source_context", "record_reflection_memory_if_caller_accepts_lesson"],
  "forbidden_actions": ["schedule_job", "assign_owner", "fetch_market_data", "fetch_outcome", "trading_execution"],
  "closure_condition": "Closes when a reflection memory is linked about decision dec_123 or the source is superseded/closed.",
  "caveat": ["derived_read_only", "local_rows_only", "no_external_fetch_or_market_lookup", "no_trading_advice_or_signal"]
}
```

Allowed actions are local process verbs only: inspect cited rows, record a
caller-supplied outcome/source/review/reflection/adherence row when the
caller has evidence, or document that input is missing. Forbidden
interpretations are the same as lifecycle plus no task-manager semantics:
no scheduler/daemon/reminder, no assignment/claiming, no notification, no
dashboard workflow, no advice/signal/ranking/profit language, no broker or
wallet action, and no source/market/outcome fetching.

## 5. `review.bundle`

`review.bundle(filter, *, max_records?, include_sources?,
include_reflections?, include_playbook?, max_examples_per_record?)`
packages a bounded case set as deterministic JSON for an external
reviewer (a separate LLM agent or a human). It is **not** an LLM call;
the system emits the data, not an opinion.

### 5.1 Inputs

- `filter`: `ReportFilter`.
- `max_records`: default 25, hard cap 200. The bundle prefers diverse
  records (no single instrument or tag dominates) when sampling under
  the cap.
- `include_sources`: default `true`. Attached sources are included,
  subject to `redaction_status` (see §5.3).
- `include_reflections`: default `true`. Reflections targeting the
  selected records are included.
- `include_playbook`: default `true`. Playbook versions referenced by
  any selected decision are included.

### 5.2 Output

```jsonc
{
  "ok": true,
  "data": {
    "filter": { /* echoed */ },
    "selected": {
      "decisions": [/* full row objects */],
      "theses": [/* same */],
      "forecasts": [/* same */],
      "outcomes": [/* same */],
      "positions": [/* projection rows */]
    },
    "sources": [/* attached source rows, redaction applied */],
    "reflections": [/* memory_node rows of type reflection */],
    "playbook_versions": [/* relevant playbook_versions and their rules */],
    "report_summaries": {
      "calibration": { /* same shape as report.calibration's data */ },
      "playbook_adherence": { /* ... */ }
    },
    "recall_receipts": {
      "status": "included",              // or "omitted"
      "consumer_scope": "selected_decisions",
      "receipt_refs": [{"receipt_id": "recall_receipt:...", "recall_id": "..."}],
      "blocks": [/* computed receipt summaries scoped to selected decisions */],
      "caveat_codes": ["STALE_OR_INVALIDATED_MEMORY"],
      "omissions": [],                   // e.g. no_recall_receipts, omitted_no_selected_consumers, truncated
      "truncated": false,
      "attribution_conventions": { /* same conventions as report.recall_receipts */ }
    },
    "caveats": [
      "sample_size 18 below recommended 20 for calibration",
      "3 sources omitted (redaction_status = sensitive)"
    ],
    "suggested_prompts": [
      "Which decisions reflect the same root-cause mistake?",
      "Is the agent over-using <tag>?"
    ]
  },
  "meta": {
    "tool": "review.bundle",
    "bundle_hash": "sha256:...",
    "contract_version": "1.0"
  }
}
```

`bundle_hash` is a SHA-256 of the canonical JSON of `data`; same DB
state and same filter produces the same hash, so reviewers can detect
"this is the same case set I already reviewed."

Replay/bootstrap consumers should read the bundle's `recall_receipts` block
instead of persisting duplicate receipt state. The block is computed from
`report.recall_receipts` for the selected decision consumers and carries
receipt IDs, node IDs used/ignored, source refs, and caveat codes (including
stale/invalidated, contradicted, superseded, and `HARMFUL_DOWNSTREAM`/violation edge cases).
If no decisions are selected, no scoped receipts exist, the caller disables the
section, or the bounded receipt cap is reached, `status`, `omissions`, and
`truncated` make that explicit. Fresh-session bootstrap is the composition of
`report.work_queue` with `report.recall_receipts`; no separate durable
bootstrap packet or receipt table is implied.

### 5.3 Redaction rules

- `sources.redaction_status = 'sensitive'`: **unconditionally excluded**.
  Listed in `caveats` as `"N sources omitted (sensitive)"`.
- `sources.redaction_status = 'redacted'`: included with `body`,
  `extracted_text`, `excerpt`, `summary`, `note` fields **omitted**.
  Metadata (kind, uri, retrieved_at, stance) is preserved so the
  reviewer can see provenance without content.
- `sources.redaction_status = 'none'`: included in full.
- Secret-pattern scan (per [operability.md](operability.md) §6.3 and
  §7) runs over outgoing content; matches are redacted to
  `[REDACTED:<pattern>]` and counted in `caveats`.

### 5.4 What `review.bundle` MUST NOT include

- LLM-generated commentary or opinion.
- Trade recommendations.
- Anything not derived from the DB.
- Secrets-shaped content (post-redaction).

### 5.5 MVP commitment

Historical note: this section originally said MVP shipped only the
contract and deferred implementation to P1. That is no longer current.
`review.bundle` is implemented and tested as a deterministic bounded
review packet with supported-filter rejection, source redaction,
recall-receipt composition, stable bundle hashing, and CLI/MCP parity.
The contract in §§5.1-5.4 describes the live surface; future work should
be documented as additive changes rather than as an implementation stub.

## 6. Bucketing Policies

Several filter fields use deterministic buckets to make report filters
stable across calls:

| Bucket | Boundaries (default) | Source field |
|---|---|---|
| `spread_bucket` | `tight: spread / price < 0.005`; `medium: < 0.02`; `wide: >= 0.02` | `snapshots.spread / snapshots.price` |
| `liquidity_bucket` | `thin: volume < 1000`; `medium: < 100000`; `deep: >= 100000` | `snapshots.volume` |
| `volume_bucket` | `low: volume < 1000`; `medium: < 1_000_000`; `high: >= 1_000_000` | `snapshots.volume` |
| `confidence_bucket` | `very_low/low/medium/high/very_high` | `theses.confidence_label` (identity) |

The numerical thresholds are constants in MVP for deterministic test
reproduction; configurable via `config.bucketing.<name>` from M2. The
chosen snapshot per decision is the latest snapshot whose `captured_at`
falls before or at `decision.created_at`.

## 7. CLI Surface

```bash
trade-trace report calibration --filter-json filter.json
trade-trace report compare --base-report calibration --group-by model_id --filter-json filter.json
trade-trace review bundle --filter-json filter.json --max-records 25 --no-include-sources
trade-trace report filter_schema    # prints the JSON schema for ReportFilter
trade-trace report bootstrap --as-of 2026-01-20T00:00:00Z --filter-json '{}' --budgets-json '{"max_chars_total":24000}'
```

CLI and MCP accept identical filter shapes per
[contracts.md](contracts.md) §2 (schema-equal, error-equal,
envelope-equal). NDJSON streaming applies to truncated/cursored reports.
`report.bootstrap` is the CLI/report-surface alias for the bootstrap v0 packet;
it returns `data.kind="agent.bootstrap"`, composes only local read models, and
does not persist packets, fetch external data, schedule follow-up work, prepare
orders, or generate trading recommendations.

## 8. Open Questions

1. **Custom bucketing.** §6 ships fixed thresholds for reproducibility.
   If dogfood shows the defaults are wrong for prediction markets vs.
   equities, expose per-asset-class threshold overrides via config.
2. **Composable group_by.** `report.compare` accepts one `group_by`;
   two-level group-by (e.g. `model_id × strategy_id`) is a P1+
   enhancement. Sub-filters already compose, so the implementation is a
   straightforward extension.
3. **`bundle_hash` canonicalization.** §5.2 promises a stable hash;
   the canonical JSON form (key ordering, whitespace stripping,
   timestamp precision) needs a one-line policy. Recommended: RFC 8785
   JSON Canonicalization Scheme. Pin in implementation.
