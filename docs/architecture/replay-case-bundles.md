# Replay Case Bundle Contract

> Status: **shipped** — v0 local export. `replay.case_bundle` is available as a read-only deterministic MCP/CLI tool surface for decision/forecast case bundles. This document remains the contract for the current v0 exporter and future replay/regression work. It does not implement replay evaluation, run models, fetch data, execute trades, or backtest.

## Purpose

`replay.case_bundle` packages recorded Trade Trace artifacts into deterministic point-in-time cases so an external candidate agent can be evaluated later by a separate evaluator surface such as `replay.evaluate_output`. The bundle answers: “what local recorded context was available at this `as_of` boundary?” It must not answer whether a counterfactual trade was executable, profitable, or advisable.

The contract follows the replay/regression research substrate, bootstrap packet budget/provenance conventions, recall receipt semantics, derived lifecycle/work-queue boundaries, and report filter rules.

## Hard boundaries

Every implementation and consumer must preserve these constraints:

- local-first, agent-only, JSON-first, caller-supplied data only;
- no live or historical market/source/outcome fetching;
- no broker, wallet, custody, execution, order preparation, fill simulation, slippage model, price-path reconstruction, or backtest engine;
- no model runner or agent hosting: candidate outputs are produced externally and submitted later;
- no trading recommendation, market ranking, process-to-profit proof, or claim that a candidate output would have been tradable;
- read-only bundle generation with no hidden writes; if a future implementation persists replay receipts, that side effect must be explicit and opt-in.

## Request contract

Future CLI/MCP schemas must use one canonical input shape:

```jsonc
{
  "kind": "replay.case_bundle",
  "contract_version": "replay.case_bundle.v0",
  "as_of": "2026-05-22T00:00:00Z",
  "case_selection": {
    "case_ids": ["derived:decision:dec_123:replay"],
    "source_refs": [
      {"kind": "decision", "id": "dec_123"},
      {"kind": "forecast", "id": "fc_456"},
      {"kind": "recall_event", "id": "rec_789"}
    ],
    "filter": {
      "time_window": {"created_at_gte": null, "created_at_lt": "2026-05-22T00:00:00Z"},
      "actors": {"agent_id": ["cron-agent-a"], "model_id": [], "environment": ["paper"], "run_id": []},
      "strategy": {"strategy_id": "strat_123", "playbook_version_id": []},
      "instrument": {"instrument_id": ["ins_123"], "symbol": ["BTC-USD"]},
      "decision": {"decision_type": ["watch", "skip", "paper_enter"], "has_forecast": true},
      "outcome": {"resolution_status": ["resolved_final"], "scoring_state": ["scored"], "include_late_recorded": false}
    },
    "eligible_statuses": ["runnable", "needs_caveat"],
    "max_cases": 25
  },
  "task": {
    "mode": "blind_decision",
    "candidate_output_contract_version": "replay.candidate_output.v0",
    "rubric_version": "replay.rubric.v0",
    "show_original_artifact": false,
    "include_evaluation_labels": false
  },
  "budgets": {
    "max_chars_total": 24000,
    "default_max_items_per_section": 10,
    "default_max_chars_per_section": 4000,
    "include_source_bodies": false,
    "include_memory_bodies": false,
    "include_sensitive_sources": false,
    "redaction_policy": "metadata_and_snippets_only"
  }
}
```

Request rules:

- `kind` is always `replay.case_bundle`; aliases must not fork semantics.
- `contract_version` pins schema behavior. A breaking change requires a new version.
- `as_of` is required for replay. It must be UTC ISO 8601 with explicit `Z` or offset normalized to UTC in the response.
- `case_selection.case_ids` selects stable derived replay case IDs directly. `source_refs` selects cases by original artifacts. `filter` mirrors safe `ReportFilter` dimensions: strategy, instrument, decision/non-action type, forecast status, actor/model/run/environment, time windows, outcome/scoring status, source/adherence coverage, and playbook version. Unsupported non-empty filters must be rejected, not ignored.
- Outcome/scoring filters may be used only for evaluator case selection; matching labels must still be withheld from candidate context unless `task.include_evaluation_labels=true` on an internal/evaluator surface.
- Budgets and redaction flags are hard upper bounds. Implementations may enforce lower safety caps but must echo effective limits and omitted counts.

## Response envelope

A successful response returns the normal success envelope. `data` uses stable top-level fields in this order:

```jsonc
{
  "kind": "replay.case_bundle",
  "contract_version": "replay.case_bundle.v0",
  "bundle_id": "sha256:jcs(data_without_bundle_id)",
  "metadata": {},
  "request": {},
  "as_of_boundary": {},
  "case_index": [],
  "cases": [],
  "candidate_task": {},
  "evaluation_labels": {"status": "withheld"},
  "excluded_artifacts": [],
  "leakage_protections": {},
  "budgets": {},
  "truncation": {},
  "caveats": [],
  "hard_constraints": {}
}
```

`bundle_id` is a deterministic content identifier, preferably SHA-256 over RFC 8785-canonical JSON with `bundle_id` omitted. For fixed database state, request, `as_of`, budgets, and redaction policy, the bundle must be byte-stable after canonicalization. `case_bundle_id` may be used as an alias only if it equals `bundle_id` or is documented as a local persisted row ID.

## Strict `as_of` semantics

`as_of_boundary` must make inclusion rules auditable:

```jsonc
{
  "as_of": "2026-05-22T00:00:00Z",
  "timezone": "UTC",
  "ordering": ["created_at", "source_kind", "id"],
  "inclusion_rule": "recorded_created_at <= as_of and valid_from <= as_of < valid_to_or_infinity and invalidated_at is null_or_after_as_of",
  "no_wall_clock_dependence": true,
  "late_recording_policy": "records created after as_of are excluded even if they describe earlier world-time facts",
  "tie_break_policy": "source_kind_then_id",
  "caveat_codes": []
}
```

Rules:

- All candidate-context sections are bounded by transaction time (`created_at <= as_of`) and, where present, world validity (`valid_from <= as_of < coalesce(valid_to, +infinity)`).
- Invalidated/superseded memory, rules, strategy notes, or source summaries may appear only if they were not invalidated before `as_of`, or if included as caveated audit context because a pre-`as_of` recall exposed them.
- Recall events are included only when the recall event `created_at <= as_of`; receipt/use evidence is included only when the downstream consumer edge or receipt evidence also existed by `as_of`.
- Forecasts, outcomes, scores, reviews, source updates, playbook changes, and reflections recorded after `as_of` are future labels or future context even if their world-time claims reference earlier periods.
- Implementations must not call `now()` after resolving `as_of` except for response transport metadata such as `generated_at`. Selection, ordering, due/stale checks, and truncation must depend on `as_of`, not wall clock.

## Case shape

Each item in `cases[]` is a source-ref-rich bundle:

```jsonc
{
  "case_id": "derived:decision:dec_123:replay:v0",
  "case_key": {
    "source_kind": "decision",
    "source_id": "dec_123",
    "as_of": "2026-05-22T00:00:00Z",
    "task_mode": "blind_decision"
  },
  "case_type": "decision",
  "eligibility_status": "runnable",
  "original_artifact": {"status": "withheld", "source_refs": [{"kind": "decision", "id": "dec_123"}]},
  "point_in_time_context": {
    "instrument": {},
    "snapshots": [],
    "theses": [],
    "forecasts": [],
    "sources": [],
    "strategy_state": {},
    "playbook_state": {},
    "memory_context": {},
    "recall_receipts": [],
    "lifecycle_context": [],
    "work_queue_context": [],
    "prior_reports": []
  },
  "candidate_instructions": {},
  "source_refs": [],
  "evidence_refs": [],
  "caveat_codes": [],
  "omitted_counts": {},
  "truncation": {}
}
```

Case IDs are deterministic from `(source_kind, source_id, as_of, task_mode, contract_version)` unless future work adds persisted replay-case rows. The same original artifact may produce different case IDs for `blind_decision`, `forecast_only`, `review_original`, or other task modes.

### Included recorded artifacts

When present and created/valid by `as_of`, sections may include:

- original decision, non-action, review, thesis, forecast, or recall event identity;
- instrument and venue metadata as stored locally;
- snapshots captured at or before `as_of`, including only caller-supplied price/reference/spread/liquidity fields;
- thesis versions, falsification notes, risk notes, and source attachments valid then;
- pending and already-known forecasts, resolution rules, and prior outcomes/scores known before `as_of`;
- sources, attachment edges, stance, freshness, redaction status, source IDs, and budgeted snippets; no URL/path fetching;
- strategy IDs, status, hypothesis snippets, review caveats, and archived/active state known at `as_of`;
- active playbook version and rule nodes valid at `as_of`, plus adherence evidence recorded before `as_of`;
- memory nodes valid at `as_of` with `valid_from`, `valid_to`, `invalidated_at`, confidence, importance, source refs, and supersession caveats;
- recall events/receipts before `as_of`, including query, context, retrieval strategies, returned node IDs, budget metadata, and bounded use/citation evidence before `as_of`;
- lifecycle and work-queue derived context computed as of `as_of` from local rows;
- bootstrap-style context only when the task mode is a run-start replay rather than a single-case replay.

Every substantive item must carry `source_refs`; items derived from caller-supplied evidence should also carry `evidence_refs`. Bodies are optional and budgeted; IDs, timestamps, validity windows, summaries/snippets, redaction status, and caveats are preferred.

### Original artifact visibility

- `blind_decision` and `forecast_only`: hide the original decision/forecast content that would reveal the answer; expose only source refs and allowed pre-decision context.
- `review_original`: show the original artifact because critique/review behavior is the task.
- `policy_shadow_check`: show historical facts available at `as_of` and the candidate policy/rule under test, but label that policy as shadow/evaluator-supplied if it was not active then.
- `bootstrap_replay`: show startup context sections, not a single original decision as the target.
- `recall_regression`: show the original recall query/context and frozen memory candidate set; hide later use/outcome labels from the candidate unless the mode explicitly asks for receipt review.

## Hidden and evaluation label separation

Future labels must be withheld from `cases[].point_in_time_context`. The top-level `evaluation_labels` section defaults to:

```json
{"status": "withheld", "reason": "candidate_context_must_not_contain_future_labels"}
```

Labels may be returned only when `task.include_evaluation_labels=true` on an explicit evaluator/internal surface, or by a separate evaluator-only response. When included, labels must be structurally separated from candidate context:

```jsonc
{
  "status": "included_for_evaluator_only",
  "labels": [
    {
      "case_id": "derived:decision:dec_123:replay:v0",
      "outcomes": [],
      "forecast_scores": [],
      "post_as_of_reflections": [],
      "post_as_of_source_updates": [],
      "post_as_of_playbook_changes": [],
      "original_artifact_for_blind_tasks": {},
      "source_refs": [],
      "caveat_codes": ["evaluator_only_not_candidate_context"]
    }
  ]
}
```

Withheld labels include later outcomes, forecast scores, calibration bins, later reviews/reflections, later source updates or contradictory evidence, later playbook/rule changes, later strategy edits, and the original final artifact when blind generation is being tested.

## Memory validity semantics

`memory_context.memory_nodes[]` must expose validity and receipt fields:

```jsonc
{
  "node_id": "mem_123",
  "node_type": "reflection",
  "summary": "budgeted snippet",
  "valid_from": "2026-04-01T00:00:00Z",
  "valid_to": null,
  "invalidated_at": null,
  "invalidated_by": null,
  "created_at": "2026-04-02T00:00:00Z",
  "importance": 7,
  "confidence_base": 0.8,
  "included_because": "valid_at_as_of_and_recalled_before_as_of",
  "recall_refs": [{"kind": "recall_event", "id": "rec_789"}],
  "source_refs": [{"kind": "memory_node", "id": "mem_123"}],
  "caveat_codes": []
}
```

Nodes outside the `as_of` validity window are excluded from candidate context unless needed to explain a pre-`as_of` stale recall receipt; those inclusions must carry `stale_or_invalidated_memory_exposed_before_as_of`. Downstream use evidence must be bounded by `as_of` and use the recall receipt conventions: cited/used edges from a consumer to a memory node count; memory-to-source provenance edges do not count as downstream use.

## Strategy and playbook state semantics

`strategy_state` and `playbook_state` must avoid current-policy leakage:

- include status/hypothesis/metadata that existed by `as_of`;
- include active and relevant archived strategies only as known at `as_of`;
- if strategy rows are mutable and reconstructed from audit events rather than versioned rows, set `strategy_state.caveat_codes += ["mutable_strategy_reconstruction"]` and expose reconstruction source refs;
- include the playbook version active at `as_of`, rule memory nodes valid then, and adherence rows recorded then;
- later playbook rules, promoted reflections, strategy edits, or current policy must be excluded from candidate context;
- `policy_shadow_check` may include a newer rule/policy only in a separate `candidate_task.shadow_policy` block labeled `not_active_at_as_of`, never as historical context.

## Candidate task/output contract

`candidate_task` defines what an external candidate agent may submit to `replay.evaluate_output`:

```jsonc
{
  "mode": "blind_decision",
  "allowed_modes": ["blind_decision", "forecast_only", "review_original", "policy_shadow_check", "bootstrap_replay", "recall_regression"],
  "candidate_metadata_required": ["agent_id", "model_id", "prompt_id_or_hash", "environment", "candidate_run_id", "tool_policy_id", "recall_policy_id", "playbook_version_id"],
  "accepted_output_sections": ["decision", "forecast", "citations", "memory_use", "playbook_adherence", "process_next_actions", "caveats", "insufficient_context"],
  "output_contract_version": "replay.candidate_output.v0",
  "rubric_version": "replay.rubric.v0",
  "forbidden_output_claims": ["trade_recommendation", "profitability_claim", "simulated_fill", "market_path_reconstruction"]
}
```

Accepted candidate outputs are machine-readable and task-specific: forecast probability and resolution-rule restatement, allowed decision/non-action classification, required source/memory citations, recall returned/cited/ignored declarations, playbook adherence self-report, predicate audit state where available, process next actions such as “record caller-supplied outcome” or “review source gap,” and explicit insufficient-context/caveat declarations. They are not orders, advice, rankings, or model-run transcripts.

## Explicit excluded artifacts

`excluded_artifacts[]` must list omitted future or forbidden material by reason without leaking content:

- post-`as_of` outcomes, scores, calibration bins, reports, reflections, source updates, playbook versions/rules, strategy edits, memories, recall events, lifecycle/work-queue states, and candidate/evaluator outputs;
- original artifact answer for blind tasks;
- redacted/sensitive source or memory bodies;
- external URLs/pages/files not already stored locally;
- broker/exchange/wallet/execution state;
- fetched market data, reconstructed price paths, simulated fills, P&L/profit proof, or live market rankings.

## Leakage protections

`leakage_protections` must include machine-checkable flags:

```jsonc
{
  "candidate_context_excludes_future_labels": true,
  "evaluation_labels_separated": true,
  "as_of_required": true,
  "utc_only": true,
  "created_at_cutoff_enforced": true,
  "validity_window_enforced": true,
  "late_recording_caveated": true,
  "current_policy_excluded": true,
  "no_fetch_performed": true,
  "no_model_run_performed": true,
  "no_hidden_writes": true
}
```

Any violation should fail bundle generation or mark the case `eligibility_status="quarantined"` with a blocker caveat. Evaluators should treat candidate outputs that cite excluded labels, later rule text, current strategy state, or unstored facts as leakage failures before scoring process quality.

## Current v0 implementation notes

The shipped v0 exporter supports decision and forecast cases from existing local
journal rows via `case_selection.case_ids`, `source_refs`, and a conservative
subset of safe filters (`time_window`, actors, strategy_id, instrument_id,
instrument symbol, decision_type, and has_forecast). Deterministic `case_ids`
round-trip only for IDs produced by this v0 format for the same `as_of` and task
mode. Forecast selection applies supported time/actor/strategy/instrument filters
through the linked thesis/instrument rows and requires both forecast and thesis
validity windows to cover `as_of`. Decision context omits linked theses or
forecasts whose `valid_from`/`valid_to`/`invalidated_at` windows do not cover
`as_of`, with explicit excluded-artifact entries. `recall_event` source refs are
accepted only when the local `memory_recall_events` row exists and was created at
or before `as_of`; otherwise explicit selection fails validation rather than
emitting a fake runnable case. Verified recall refs still produce only minimal
source-ref cases with a caveat until broader recall replay reconstruction lands.
Unsupported non-empty filters are validation errors rather than silently
broadened queries. Forecast `scoring_state` is a mutable current field and is not
exposed as candidate context; v0 emits
`scoring_state_as_of_caveat="not_reconstructed_v0"` instead.
Evaluation labels are withheld by default and, when explicitly requested, remain
structurally separate in top-level `evaluation_labels`.

## Implementation test plan for future F2/F3/F4 work

Future implementation tests should include fixtures that prove:

1. A post-`as_of` outcome/score/reflection/source update/playbook change never appears in candidate context and appears only in evaluator labels when explicitly requested.
2. A late-recorded record with world-time before `as_of` but `created_at > as_of` is excluded and caveated.
3. Memory nodes respect `valid_from`, `valid_to`, `invalidated_at`, and recall/use evidence bounded by `as_of`.
4. Mutable strategy reconstruction emits caveats and never leaks current status/hypothesis without an `as_of` source.
5. `policy_shadow_check` labels newer policy as shadow, not historical.
6. Bundle generation performs no network calls and no hidden writes.
7. Fixed DB/filter/`as_of`/budgets/redaction produces deterministic canonical bundle equality and stable `bundle_id`.
8. Redaction and budget truncation omit bodies while preserving IDs, counts, source refs, and caveats.
9. Every substantive context item has source-ref coverage; missing refs fail or produce blocker caveats.
10. Candidate outputs containing future labels, unstored facts, simulated fills, or advice/ranking claims fail leakage/boundary checks before normal evaluation.

## Non-goals

`replay.case_bundle` is not a backtester, market simulator, execution simulator, trading advisor, model host, scheduler, generic benchmark, data fetcher, or proof that a different agent would have produced better realized returns. It is a deterministic process/evaluation diagnostics contract over recorded local artifacts.
