# Forecast add/supersede shared write-kernel investigation (trade-trace-m29q)

Date: 2026-05-20
Scope: investigation only; no production behavior changes.
Files audited: `src/trade_trace/tools/ledger.py`, focused on `_forecast_add` and `_forecast_supersede`, plus existing regression tests.

## Current forecast.add behavior

`_forecast_add` currently owns the full create path for a new forecast:

1. Reads required `thesis_id` and `outcomes`; defaults `kind` to `binary`.
2. Validates `outcomes` by kind:
   - `binary`: binary forecast validator.
   - `categorical`: categorical forecast validator.
   - `scalar`: scalar point-estimate validator.
   - unknown kind raises `VALIDATION_ERROR` with `field=kind`.
3. Normalizes `resolution_at`, captures `yes_label`, sets `scoring_support = "supported"`, scans `resolution_rule_text` for secrets, and computes common segment metadata.
4. Opens one database connection and one `UnitOfWork`.
5. Performs idempotency replay lookup before relational inserts using `(event_type="forecast.created", actor_id, idempotency_key)`.
6. On replay:
   - Re-emits `forecast.created` through `emit_event` with a reconstructed `_forecast_payload(forecast_id)` so the event writer performs semantic replay/conflict handling.
   - Reads the original forecast row's `created_at`.
   - Returns `id`, requested `thesis_id`, requested/defaulted `kind`, `scoring_state="pending"`, and original `created_at`.
   - Does not insert new `forecasts`, `forecast_outcomes`, edges, or score rows.
7. On first write:
   - Generates or accepts `forecast_id` from `args["id"]`.
   - Captures one `created_at = now_iso()` used for the forecast row, default `valid_from`, and late auto-score timestamp.
   - Looks up the thesis instrument and current non-superseded head `resolved_final` outcome before inserting the forecast.
   - Computes `late_recorded` via `_late_recorded_calc` when a head resolved outcome exists, then injects `metadata_json.late_recorded=true` into the forecast row when applicable.
   - Inserts one `forecasts` row with `scoring_state='pending'`.
   - Inserts one `forecast_outcomes` row per supplied outcome with generated `fo` ids.
   - Emits `forecast.created` with payload shape:
     - `id`
     - `thesis_id`
     - `kind`
     - `resolution_at`
     - `yes_label`
     - `resolution_rule_text`
     - `outcomes`: list of `{outcome_label, probability, lower_bound, upper_bound}` with labels coerced to string and probabilities to float.
   - If a current head resolved_final outcome existed, scores the new forecast in the same transaction and emits `forecast.scored` in the same transaction.
8. Returns `id`, `thesis_id`, `kind`, `scoring_state="pending"`, `created_at`, and optional `auto_scored`.

Important payload/replay note: add replay uses `_forecast_payload(forecast_id)`, which is derived from current call args plus the replayed id. This is what lets the event writer detect idempotency-key reuse with incompatible payloads.

## Current forecast.supersede behavior

`_forecast_supersede` currently inlines a near-copy of the forecast insert path so the replacement forecast and its supersedes lineage commit atomically:

1. Requires `prior_forecast_id`; defaults `kind` to `binary`; requires and validates `outcomes` using the same kind validators as add.
2. Scans `resolution_rule_text`, normalizes `resolution_at`, captures `yes_label`, sets `scoring_support = "supported"`, captures idempotency key and common segment metadata.
3. Opens one database connection and one `UnitOfWork`.
4. Looks up `prior_forecast_id` first; if missing, raises `NOT_FOUND` before idempotency replay handling.
5. Derives `thesis_id` from the prior forecast row rather than accepting caller input.
6. Performs idempotency replay lookup before relational inserts using `(event_type="forecast.created", actor_id, idempotency_key)`.
7. On replay:
   - Uses the stored original `forecast.created` payload as `payload=replay` and `subject_id=replay["id"]` for event-writer semantic replay/conflict handling.
   - Reads original replacement `created_at` from `forecasts`.
   - Returns `id`, derived `thesis_id`, current requested/defaulted `kind`, `scoring_state="pending"`, original `created_at`, and `supersedes_prior_forecast_id` equal to the current request's `prior_id`.
   - Does not insert another forecast, outcome row, supersedes edge, or event.
8. On first write:
   - Generates or accepts `new_forecast_id` from `args["id"]`.
   - Captures one `created_at = now_iso()` used for replacement forecast, default `valid_from`, supersedes edge, and late auto-score timestamp.
   - Sets forecast metadata with `_maybe_inject_late_flag(args, late_recorded=False)` before the later auto-score path. This differs from add, which precomputes a possible late flag and stores it on the forecast row.
   - Inserts one replacement `forecasts` row with `scoring_state='pending'` and the prior forecast's `thesis_id`.
   - Inserts replacement `forecast_outcomes` rows.
   - Emits `forecast.created` with the same normal first-write payload shape as add.
   - Inserts a `forecast -> forecast` edge of type `supersedes` from replacement to prior.
   - Emits `edge.created` for that edge.
   - Emits `forecast.superseded` with payload `{prior_forecast_id, new_forecast_id}` and subject kind/id `forecast`/`new_forecast_id`.
   - Looks up the thesis instrument and current non-superseded head `resolved_final` outcome; if present, scores the replacement and emits `forecast.scored`, all inside the same `UnitOfWork`.
9. Returns `id`, `thesis_id`, `kind`, `scoring_state="pending"`, `created_at`, `supersedes_prior_forecast_id`, and optional `auto_scored`.

Important payload/replay note: supersede first-write `forecast.created` payload shape matches add, but replay uses the original stored event payload, not a reconstructed payload. This is safer for exact event-writer replay, but the returned `kind` and `supersedes_prior_forecast_id` are still derived from the current request/prior lookup rather than directly from the original payload/edge. Existing tests cover no duplicate rows/events on replay, not all conflict/return-shape edge cases.

## Atomicity/idempotency/event-ordering constraints

Constraints that a shared kernel must preserve exactly:

- All first-write operations for `forecast.add` happen in a single `UnitOfWork`: forecast row, forecast outcomes, `forecast.created`, optional score row, optional `forecast.scored`.
- All first-write operations for `forecast.supersede` happen in a single `UnitOfWork`: replacement forecast row, replacement outcomes, `forecast.created`, supersedes edge row, `edge.created`, `forecast.superseded`, optional score row, optional `forecast.scored`.
- Supersede must not call `_forecast_add` as a separate transaction. Existing comments and tests document the prior bug: replacement forecast could commit without lineage edge if a later edge insert failed.
- Supersede edge/event ordering is currently: `forecast.created` first, then relational `edges` insert, then `edge.created`, then `forecast.superseded`, then optional `forecast.scored`.
- Add event ordering is currently: `forecast.created`, then optional `forecast.scored`.
- Idempotency replay must be checked before relational inserts on both paths.
- Event-writer replay/conflict validation must still be invoked by calling `emit_event` on replay.
- On replay, no extra relational rows and no extra event rows should appear. Existing regression `test_forecast_supersede_replay_returns_original_replacement` asserts forecast/edge/event counts are stable.
- `emit_event(... allow_no_idempotency=True)` compatibility remains part of the tool surface; missing idempotency keys are still tolerated.
- `created_at` must remain a single timestamp for related rows/events within a write path as currently implemented.
- The current primary response `meta.event_id` behavior depends on first emitted event being `forecast.created`; a helper must not move `edge.created`, `forecast.superseded`, or `forecast.scored` before it.
- `check_idempotency_replay` is keyed only by event type/actor/key. A shared helper must avoid accidentally allowing a supersede replay to bypass prior-forecast lineage validation semantics unless intentionally changed in a separate behavior bead.

## Resolved_final auto-score behavior and whether code/comments disagree

Current behavior:

- `forecast.add` auto-scores when a non-superseded head `resolved_final` outcome already exists for the thesis instrument. It also computes/injects `metadata_json.late_recorded=true` on the forecast row before inserting the forecast when appropriate.
- `forecast.supersede` also auto-scores when a non-superseded head `resolved_final` outcome already exists for the prior forecast's thesis instrument. It emits `forecast.scored` after the supersedes events in the same transaction.
- Existing narrow regression `test_forecast_supersede_auto_scores_against_existing_resolved_final` verifies the supersede response includes `auto_scored` and that the score has `late_recorded=true`.
- Contract/integration validation also confirms a `forecast.scored` event path is generally covered.

Comment disagreement:

- The `_forecast_supersede` docstring lines 1585-1591 say auto-scoring is intentionally NOT replicated and can be repaired by `journal.rescan_scoring`.
- The executable code below that docstring, lines 1759-1795, explicitly implements the late auto-score path for supersede and cites trade-trace-ld6l.
- Therefore code and comments disagree. The code is current behavior; the old docstring is stale and dangerous for future refactors.

Potential subtle behavior difference:

- Supersede's auto-score result/score row can carry `late_recorded=true`, but the replacement forecast row metadata is inserted with `late_recorded=False` before scoring and is not updated later. Add precomputes and stores the late flag on the forecast row. Any shared kernel must decide whether this difference is contractual or a bug, but this investigation must not change it.

## Existing/missing tests and exact validation results

Existing relevant tests found:

- `tests/contracts/test_event_enum_coverage.py::test_forecast_superseded_event_emitted` covers `forecast.superseded` emission.
- `tests/integration/test_ledger_event_emission.py` covers event emission broadly, including forecast-related event behavior in the required validation set.
- `tests/integration/test_manual_ledger_flow.py::test_forecast_supersede_writes_edge` covers supersede writing a lineage edge at a basic level.
- `tests/integration/test_manual_ledger_flow.py::test_forecast_supersede_atomic_when_edge_insert_fails` covers the key atomicity regression: edge insert failure rolls back the replacement forecast row.
- `tests/integration/test_manual_ledger_flow.py::test_forecast_supersede_replay_returns_original_replacement` covers supersede idempotency replay: same replacement id, idempotent replay meta, no second forecast, no second supersedes edge, no extra events.
- `tests/integration/test_manual_ledger_flow.py::test_forecast_supersede_auto_scores_against_existing_resolved_final` is the requested already-resolved regression; it exists and verifies `auto_scored` plus score `late_recorded=true`.

Validation run:

```text
$ ./.venv/bin/python -m pytest tests/contracts/test_event_enum_coverage.py::test_forecast_superseded_event_emitted tests/integration/test_ledger_event_emission.py -q
................                                                         [100%]
16 passed in 0.35s
```

Additional credibility check for the requested already-resolved supersede regression:

```text
$ ./.venv/bin/python -m pytest tests/contracts/test_event_enum_coverage.py::test_forecast_superseded_event_emitted tests/integration/test_ledger_event_emission.py tests/integration/test_manual_ledger_flow.py::test_forecast_supersede_auto_scores_against_existing_resolved_final -q
.................                                                        [100%]
17 passed in 0.39s
```

Missing or weak coverage:

- No direct test was found that asserts supersede's full event ordering (`forecast.created` -> `edge.created` -> `forecast.superseded` -> optional `forecast.scored`).
- No direct test was found that asserts supersede replacement forecast row metadata lacks/preserves `late_recorded` when auto-scored after an existing resolved_final outcome, while add stores that flag on the forecast row.
- No direct test was found for idempotency-key conflict behavior on supersede when the same key is reused with different replacement payload/prior.
- No direct test was found that replay return fields for supersede are sourced from the original write rather than current request fields; current implementation returns current `kind` and current `prior_id` after replay validation.

No tests were added for this investigation because the requested already-resolved supersede auto-score regression already exists and passes.

## Decision: defer shared kernel until stale-comment and parity questions are handled

Decision: defer implementation of a shared `_insert_forecast_core`/write kernel in this bead. Do not reject the idea; implement only in a follow-up behavior-preserving refactor bead with explicit guardrails.

Evidence:

- There is real duplicated code between add and supersede for validation, forecast row insertion, forecast_outcome insertion, and `forecast.created` payload construction.
- A helper is plausible if it accepts an existing `UnitOfWork` and performs no transaction management of its own.
- The helper must not include supersede edge/event insertion in a separate transaction or hide event ordering.
- Current comments in `_forecast_supersede` are stale and contradict code around late auto-score behavior. Refactoring against the comments rather than the code would regress behavior.
- Add and supersede differ in at least three behavior-sensitive ways:
  1. Thesis source: add takes `thesis_id`; supersede derives it from the prior forecast.
  2. Replay payload: add reconstructs payload; supersede uses stored payload on replay.
  3. Late metadata: add precomputes and injects forecast-row `metadata_json.late_recorded`; supersede initializes metadata with `late_recorded=False` even though it may then create a late score.
- Atomicity risk is high because a prior implementation was fixed specifically to avoid multi-transaction supersede writes.

Safe shape if implemented later:

- A shared helper should be an in-transaction insert primitive, not a public handler and not a transaction-owning function.
- Candidate API: `_insert_forecast_core(uow, *, args, ctx, thesis_id, forecast_id, created_at, kind, outcomes, yes_label, resolution_at, scoring_support, seg, late_recorded_for_forecast_metadata) -> payload/result_fragment`.
- It should insert only the forecast row and forecast_outcomes and return the exact `forecast.created` payload. The caller should remain responsible for replay checks, event emission ordering, supersedes edge/events, and auto-score placement unless a second carefully designed helper handles scoring.
- Any extraction must have tests pinning no row/event count changes, event order, replay behavior, and late metadata differences before and after.

## Proposed downstream bead if implementing

Title: Refactor forecast.add/supersede to shared in-transaction forecast insert helper without semantic changes

Acceptance criteria:

1. Introduce a private helper that requires an active `UnitOfWork` and does not open/close DB connections or start/commit transactions.
2. Preserve `forecast.add` first-write behavior exactly: row values, forecast_outcomes, `forecast.created` payload, replay semantics, optional late metadata injection, optional `forecast.scored`, response shape.
3. Preserve `forecast.supersede` first-write behavior exactly: prior lookup semantics, row values, forecast_outcomes, `forecast.created` payload, supersedes edge row, `edge.created`, `forecast.superseded`, optional `forecast.scored`, response shape.
4. Preserve event ordering exactly for add and supersede, including `forecast.created` as the first emitted event.
5. Preserve idempotency replay behavior: no extra forecasts, edges, scores, or events on replay; conflict reuse still surfaces through event-writer validation.
6. Add/keep regression coverage for supersede against an already `resolved_final` outcome verifying `auto_scored` and `forecast.scored` event emission.
7. Add event-order regression for supersede, including the optional late `forecast.scored` case.
8. Either update the stale supersede docstring to match code or move detailed behavior comments beside the refactored call sites.

Non-goals:

- Do not change scoring semantics.
- Do not change idempotency-key requirements or replay conflict semantics.
- Do not change supersede lineage model or event order.
- Do not change late-recorded forecast-row metadata behavior unless covered by a separate behavior bead.
- Do not convert supersede back to calling `_forecast_add` or any helper that owns its own transaction.

Validation commands for downstream implementation:

```bash
./.venv/bin/python -m pytest tests/contracts/test_event_enum_coverage.py::test_forecast_superseded_event_emitted tests/integration/test_ledger_event_emission.py -q
./.venv/bin/python -m pytest tests/integration/test_manual_ledger_flow.py::test_forecast_supersede_atomic_when_edge_insert_fails tests/integration/test_manual_ledger_flow.py::test_forecast_supersede_replay_returns_original_replacement tests/integration/test_manual_ledger_flow.py::test_forecast_supersede_auto_scores_against_existing_resolved_final -q
./.venv/bin/python -m pytest tests/integration/test_manual_ledger_flow.py tests/integration/test_report_calibration.py -q
```
