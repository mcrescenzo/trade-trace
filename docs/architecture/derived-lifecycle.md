# Internal derived decision/non-action lifecycle

> Status: **partial — public report shipped, internal substrate documented** for `trade-trace-03b6`; `report.lifecycle` is a public read-only report while the derived lifecycle substrate remains an internal implementation note.

`trade_trace.reports.lifecycle.derive_lifecycle_cases(conn, as_of=..., stale_threshold_days=...)` derives lifecycle cases from existing SQLite rows only. It does not create lifecycle tables, durable work items, scheduler state, advice, source fetches, or public report payload shapes.

## Scope

The derivation covers decision and material non-action continuity signals needed by later lifecycle/work-queue/report beads:

- decision/non-action states: `open`, `pending_review`, `stale`, `resolved`, `outcome_recorded`, `scored`, `reflection_due`, `reflected`, `adherence_due`, `adherence_recorded`, `closed`, `superseded` where computable from local rows;
- material non-action metadata from `metadata_json.material_non_action` when present;
- source references sufficient for future consumers (`decision`, `instrument`, `thesis`, `forecast`, `snapshot`, `playbook_version`, `strategy`, `source`, `forecast_score` as available);
- caveats such as `missing_source_ref` rather than inferring evidence that is not present.

Ordinary absence of action is not interpreted as a lifecycle case. A case is emitted for existing non-action/review decision rows, material non-action markers, and forecast rows with computable status.

## Determinism

Callers should pass `as_of` for deterministic due/stale computation. Ordering is stable by source timestamp and derived case id; source refs are deduplicated and sorted by kind/id. Threshold basis is echoed in each case.

## Precedence

For decision cases the current internal precedence is:

1. supersession edge;
2. reflection about the decision;
3. playbook adherence recorded/due;
4. linked forecast score;
5. instrument outcome;
6. later `resolved` decision;
7. `review_by` due;
8. stale age threshold for watch/hold/review;
9. terminal close for unmarked `skip`, `resolved`, or `invalidate_thesis`;
10. otherwise open.

Forecast cases use supersession/scoring/outcome/due/open precedence. These are derived interpretations, not persisted lifecycle facts.
