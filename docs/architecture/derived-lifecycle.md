# Internal derived decision/non-action lifecycle

> Status: **partial — public report shipped, internal substrate documented** for `trade-trace-03b6`; `report.lifecycle` is a public read-only report while the derived lifecycle substrate remains an internal implementation note.

`trade_trace.reports.lifecycle.derive_lifecycle_cases(conn, as_of=..., stale_threshold_days=...)` derives lifecycle cases from existing SQLite rows only. The public `report.lifecycle` surface exposes those cases as a read-only report. It does not create lifecycle tables, durable work items, scheduler state, advice, source fetches, or dashboard payloads.

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

## Public usage

Agents can inspect lifecycle state before adding new trading records:

```bash
tt report lifecycle --home <journal-home> --as-of 2026-05-22T00:00:00Z --states-json '["pending_review","stale","reflection_due","adherence_due"]'
```

```json
{"tool":"report.lifecycle","args":{"as_of":"2026-05-22T00:00:00Z","states":["pending_review","stale"],"filter":{"strategy":{"strategy_id":"str_..."}}}}
```

Representative case shape:

```json
{
  "case_id": "derived:lifecycle:decision:dec_123",
  "state": "reflection_due",
  "status": "reflection_due",
  "reason_codes": ["resolved_evidence_missing_reflection"],
  "source_refs": [{"kind": "decision", "id": "dec_123"}, {"kind": "outcome", "id": "out_456"}],
  "threshold_basis": {"as_of": "2026-05-22T00:00:00Z"},
  "caveat_codes": ["missing_source_ref"]
}
```

`report.work_queue` and `agent.next_actions` are projections over this lifecycle substrate. They may turn `pending_review`, `stale`, `reflection_due`, or `adherence_due` cases into process-obligation items, but they remain derived/read-only and close only when source journal rows change or are superseded. They must not be interpreted as scheduler state, assignments, human dashboard tickets, market signals, advice, broker truth, or permission to fetch outcomes/market data.
