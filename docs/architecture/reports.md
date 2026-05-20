# Reports: Filters, Drill-Down, Compare, Bundles

> Status: **shipped**. `ReportFilter` / `ReportResult` / drill-down / `review.bundle` describe the live report surface.

Status: clean planning draft. Date: 2026-05-18.

**Implementation status (M0-M4 MVP):** shipped: report.calibration,
report.calibration_integrity, report.source_quality, report.mistakes,
report.strengths, report.pnl, report.watchlist,
report.unscored_forecasts, report.decision_velocity,
report.playbook_adherence, report.coach, report.filter_schema,
report.compare, report.strategy_performance. Deferred (P1): report.risk,
report.opportunity. review.bundle ships as a contract-only stub
(UNSUPPORTED_CAPABILITY); the §5 spec is the binding contract for the P1
implementation.

Companion docs: [PRD.md](../PRD.md), [VISION.md](../VISION.md),
[scoring.md](scoring.md), [persistence.md](persistence.md),
[contracts.md](contracts.md), [memory-layer.md](memory-layer.md).

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

### 4.2 `report.mistakes` and `report.strengths`

Group by tag. Per-group metrics: tag count, distinct decisions,
co-occurrence with other tags (top-5), tag-vs-outcome conditional rates
where outcomes exist.

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

Group by playbook version. Per-group: counts of `considered`,
`followed`, `overridden`, `not_applicable`; override-outcome breakdown
where outcomes exist.

### 4.7 `report.compare` (P1)

Inputs:

- `filter`: a `ReportFilter` defining the baseline candidate set.
- `group_by`: one of `agent_id`, `model_id`, `strategy_id`,
  `playbook_version_id`, `decision_type`, `venue_id`, `asset_class`,
  `liquidity_bucket`, `confidence_bucket`, `environment`.
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
   matching outcome's `resolved_at` (post-hoc bias signal).

Each diagnostic returns `{count, total, rate_pct, sample_ids,
truncated}`. The framing is hygiene-not-fraud per scoring.md §9: the
goal is to make the panel honest about its denominator, not to second-
guess intent. Empty journal returns `summary.sample_warning="no_data"`.

Source: bead trade-trace-jzn.

### 4.9 `report.source_quality` (MVP hardening)

Five provenance hygiene diagnostics over the source-attachment graph:

1. `missing_sources_on_actual_enter` — decisions with
   `type='actual_enter'` whose linked thesis has zero attached sources.
2. `stale_sources` — sources whose `freshness_at` predates the linked
   decision's `created_at` by more than `stale_threshold_days` (default
   7).
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
hygiene is a journal-level signal, not a per-strategy slice. No external
fetching, no credibility scoring.

Source: bead trade-trace-l9q.

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

MVP ships the **contract** (envelope shape, redaction rules, hashing).
The **implementation** is P1. Until the implementation ships, the
contract serves as the spec for `report.coach`'s richer-packet variant
and for external review-tool authors who want to integrate.

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
```

CLI and MCP accept identical filter shapes per
[contracts.md](contracts.md) §2 (schema-equal, error-equal,
envelope-equal). NDJSON streaming applies to truncated/cursored reports.

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
