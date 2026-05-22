# Policy Promotion Evidence Bundles

> Status: **contract draft** for G2 reflection quarantine. This document defines the durable evidence contract that future policy-candidate reports and playbook lifecycle work can consume. It does not ship a CLI/MCP command, database table, predicate evaluator, or automatic promotion path.

**Date:** 2026-05-22  
**Parent:** [memory-layer.md](memory-layer.md), [reports.md](reports.md), [replay-case-bundles.md](replay-case-bundles.md)

## 1. Purpose

A policy promotion evidence bundle is a local, agent-facing review packet that explains why one or more quarantined reflections may or may not support a durable playbook/process rule. It is the contract between subjective memory and procedural memory:

- `reflection` nodes may capture retrospective lessons, caveats, and hypotheses.
- `playbook_rule` nodes and playbook versions are durable procedural policy.
- An evidence bundle records the provenance, scope, supporting cases, contradictory cases, caveats, and criteria result before a reflection influences durable policy/playbook behavior.

The bundle is testable because every claim in it must point at existing local identifiers: decisions, non-actions, forecasts, outcomes/scores, sources, recall receipts, replay cases, adherence rows, overrides, reflections, playbook versions, rules, strategies, agents, models, environments, and runs.

## 2. Non-goals and boundaries

Evidence bundles are **not**:

- an automatic global policy promotion mechanism;
- a human approval dashboard;
- an execution blocker or order-routing system;
- a market-data fetcher or source-verification service;
- positive trading advice, trade recommendation text, or a performance ranking;
- a general reinforcement-learning reward loop;
- a substitute for explicit playbook version provenance.

A future report may compute or render these bundles, but the contract here must not be read as claiming that such a report already exists. The current boundary is local-first and agent-only: bundles summarize recorded journal state and make policy-readiness auditable.

## 3. Required identity and provenance fields

Every bundle must carry stable IDs or deterministic keys for the candidate, inputs, and proposed policy target.

| Field | Required | Meaning |
|---|---:|---|
| `bundle_id` | yes | Stable ID or deterministic key for this evidence bundle. |
| `candidate_id` | yes | Stable candidate ID/key. May be computed from reflection IDs + intended policy text until a durable object exists. |
| `status` | yes | One of the allowed bundle statuses in §9. |
| `reflection_ids` | yes | One or more quarantined `reflection` memory-node IDs that motivated the candidate. |
| `candidate_statement` | yes | Process-only description of the possible rule/change. Must not be phrased as trade advice. |
| `target_policy_kind` | yes | `playbook_rule`, `playbook_version`, `process_policy`, or `reject_no_policy_change`. |
| `playbook_id` / `playbook_version_id` | conditional | Required when the candidate targets a playbook or rule. |
| `rule_node_ids` | conditional | Existing rule IDs to supersede, reject, narrow, or compare against. Empty for a brand-new rule candidate. |
| `supersedes_rule_node_ids` | no | Prior rules the candidate would supersede if promoted. |
| `created_at` / `as_of` | yes | Bundle creation time and read boundary used to assemble evidence. |
| `reviewer_actor_id` | no | Agent/process actor that assembled or reviewed the bundle. |

The bundle must keep the source reflections quarantined until promotion criteria pass and an explicit playbook/process write occurs in a separate lifecycle step. Bundle status alone is not durable policy.

## 4. Required scope fields

Promotion can only apply within an explicit scope. Missing scope is a rejection or needs-more-evidence reason.

| Scope axis | Required contract |
|---|---|
| Strategy scope | `strategy_id` or explicit `strategy_scope` of `none` or `global_candidate`. A strategy-linked reflection must not become global by omission. |
| Playbook scope | `playbook_id`, `playbook_version_id`, and target rule IDs where applicable. |
| Decision/non-action scope | Included decision types such as entry, exit, watch, skip, hold, review, thesis update, invalidation, or other local lifecycle records. |
| Instrument/venue/asset scope | Instrument IDs, venue IDs/kinds, asset classes, market/context tags, or explicit `not_scoped`. |
| Time/regime scope | Time window, event/regime tags, and whether outcomes were known at reflection time. |
| Agent/model scope | `actor_id`, `agent_id`, `model_id`, `environment`, and `run_id` filters used to assemble the evidence. |
| Replay scope | Replay case IDs and historical as-of boundary if replay examples are included. |

Cross-strategy, cross-playbook, cross-agent, or global promotion requires stronger evidence than narrow promotion and must set a caveat explaining why the broader scope is justified. No bundle may silently widen scope from the source reflections.

## 5. Evidence sections

A complete bundle has separate sections for support, contradiction, and caveats. Supporting evidence must not be mixed with contradictory evidence or missing-data caveats.

### 5.1 Linked decisions and non-actions

Include the local IDs and summaries of decisions and non-actions that the candidate claims are relevant:

- decisions, watches, skips, holds, reviews, thesis updates, thesis invalidations, and other lifecycle cases;
- whether each case is pre-outcome, post-outcome, late-recorded, provisional, disputed, void, cancelled, or unresolved;
- reason codes/tags and the filter that selected the cases;
- whether the case is support, contradiction, override/failure evidence, or contextual only.

### 5.2 Forecasts, outcomes, and scores

Where applicable, include:

- forecast IDs and the decision/non-action IDs they were attached to;
- resolution rules, resolution timestamps, outcome IDs, and outcome status;
- score IDs/values and calibration/report slices used by the reviewer;
- base-rate/reference caveats and late-recorded/ambiguous/disputed caveats;
- explicit `low_n` caveat when scored or resolved samples are below the relevant report threshold.

Outcome and score evidence must preserve temporal discipline. Post-outcome information may support retrospective review, but it must not be presented as if it was known before the decision.

### 5.3 Source references and source caveats

Include source IDs or source-quality diagnostic references that affected the candidate:

- source refs attached to theses, decisions, forecasts, outcomes, reflections, or rules;
- stance where recorded: `supports`, `contradicts`, or `neutral`;
- freshness, retrieval, redaction/sensitive-source, duplicate-source, missing-source, or contradictory-source caveats;
- explicit note when a source claim is caller-supplied and not externally verified by Trade Trace.

The bundle reports provenance hygiene only. It must not infer source truth or fetch external facts.

### 5.4 Recall receipts

Include recall receipt IDs/events when prior memories or rules were available to the agent:

- recalled reflection/rule/observation IDs;
- whether each memory was cited/used, ignored, stale, contradicted, superseded, or not attributable under the memory-layer receipt convention;
- `consumer_kind` and `consumer_id` when attribution is scoped;
- caveat code when attribution is inferred or unscoped.

Recall evidence matters because a policy candidate based on a lesson that was never recalled, or repeatedly recalled and ignored, should be reviewed differently from one that reliably shaped process behavior.

### 5.5 Playbook adherence, overrides, and failure cases

Include playbook/rule evidence for the same scope:

- adherence row IDs and statuses: `considered`, `followed`, `overridden`, `not_applicable`;
- override reasons and later outcome/score context where available;
- cases where the proposed rule would have applied but was not present, not recalled, or not computable;
- cases where following an existing rule appears to conflict with the candidate;
- failure cases where the candidate would not have helped, would have been too broad, or would have created process friction.

Overrides are evidence, not automatic errors. A bundle must separate "rule was overridden with a recorded reason" from "rule was not considered" and from "future predicate would fail."

### 5.6 Replay examples

If replay/regression substrate is available, include replay case IDs and as-of boundaries:

- historical case ID;
- fields available at the historical decision time;
- whether the candidate would have changed recorded process behavior;
- contradiction/failure cases where the candidate would have produced an undesirable or non-computable process result;
- leakage caveats for any replay that uses post-outcome data.

Replay examples are optional but, when present, they must be local and auditable. They do not rewrite history and do not imply future performance.

## 6. Support vs contradiction evidence

The bundle must explicitly classify evidence items as one of:

| Evidence stance | Meaning |
|---|---|
| `support` | Case/source/receipt/adherence/replay item supports the candidate within the stated scope. |
| `contradiction` | Item weakens, conflicts with, or narrows the candidate. |
| `exception` | Item supports a narrow exception rather than the general candidate. |
| `context` | Item explains scope or provenance but should not count toward support. |
| `missing` | Expected evidence is absent; counts as a caveat or rejection reason. |

Contradictory evidence must be included when known. A bundle that only lists favorable cases is incomplete and cannot be promoted. Contradictions may lead to rejection, supersession of a weaker candidate, or a narrower scope with caveats.

## 7. Sample-size and repeated-pattern rules

Default promotion requires a repeated pattern, not a single case. The bundle must report:

- `support_case_count` and `contradiction_case_count`;
- count of distinct decisions/non-actions, forecasts, outcomes, sources, recall receipts, adherence rows, and replay cases;
- whether cases are independent enough to count as a repeated pattern;
- low-N/sample-size caveats using report thresholds where applicable;
- whether the candidate is scoped narrowly enough for the available evidence.

A single outcome or single reflection may create a candidate, but it must not create a durable general rule by default. Low-N evidence may still be useful for monitoring or a narrow candidate, but the criteria result must reflect the caveat.

## 8. Single-case critical-risk exception

A single case can be eligible only through an explicit critical-risk exception path. The bundle must set `exception_kind = "single_case_critical_risk"` and include all of the following:

1. the concrete failure or near-failure case ID;
2. why the risk is process-critical rather than merely an unfavorable outcome;
3. the narrowest applicable strategy/playbook/decision/instrument/time/agent scope;
4. source, recall, adherence, override, and outcome caveats;
5. contradiction search result, even if the result is `none_found`;
6. a monitoring or supersession trigger for future evidence;
7. a prohibition on global promotion unless separately supported by repeated evidence.

This path is for narrow risk-control process lessons. It does not permit broad policy from one case, and it does not remove the need for explicit playbook provenance.

## 9. Minimal schema-like JSON shape

Future implementations may add fields, but they must preserve these concepts and enum meanings.

```jsonc
{
  "bundle_id": "peb_...",
  "contract_version": "G2.1",
  "candidate_id": "pc_...",
  "status": "candidate",
  "candidate_statement": "Process-only proposed rule/change text",
  "target_policy_kind": "playbook_rule",
  "reflection_ids": ["mem_reflection_..."],
  "playbook_id": "pb_...",
  "playbook_version_id": "pbv_...",
  "rule_node_ids": [],
  "supersedes_rule_node_ids": [],
  "scope": {
    "strategy_ids": ["strat_..."],
    "decision_types": ["skip", "watch", "review"],
    "instrument_ids": [],
    "venue_ids": [],
    "asset_classes": [],
    "time_window": {"created_at_gte": null, "created_at_lt": null},
    "agent": {
      "actor_id": [],
      "agent_id": [],
      "model_id": [],
      "environment": [],
      "run_id": []
    },
    "scope_caveats": []
  },
  "evidence": {
    "support": [
      {"kind": "decision", "id": "d_...", "stance": "support", "caveats": []}
    ],
    "contradictions": [
      {"kind": "outcome", "id": "o_...", "stance": "contradiction", "caveats": ["ambiguous_outcome"]}
    ],
    "forecasts": [],
    "outcomes": [],
    "scores": [],
    "source_refs": [],
    "recall_receipts": [],
    "adherence_rows": [],
    "override_cases": [],
    "failure_cases": [],
    "replay_case_ids": []
  },
  "sample": {
    "support_case_count": 0,
    "contradiction_case_count": 0,
    "distinct_decision_count": 0,
    "distinct_outcome_count": 0,
    "repeated_pattern": false,
    "low_n": true,
    "sample_caveats": ["low_n"]
  },
  "criteria": {
    "provenance": "pass",
    "scope": "pass",
    "repeated_pattern": "fail",
    "outcome_support": "needs_evidence",
    "source_caveats": "caveated",
    "recall_receipts": "needs_evidence",
    "contradiction_review": "caveated",
    "replay_examples": "not_applicable",
    "override_failure_review": "needs_evidence",
    "no_global_auto_promotion": "pass"
  },
  "decision": {
    "criteria_result": "needs_evidence",
    "rationale": "Low-N candidate remains quarantined; no durable rule write authorized.",
    "exception_kind": null,
    "approved_scope": null,
    "supersession_target_ids": [],
    "next_review_trigger": "more_resolved_cases"
  },
  "created_at": "2026-05-22T00:00:00.000Z",
  "as_of": "2026-05-22T00:00:00.000Z"
}
```

Allowed `status` values:

| Status | Meaning |
|---|---|
| `candidate` | Identified but not fully reviewed; not policy. |
| `assembling_evidence` | Bundle is being populated; not policy. |
| `needs_evidence` | Required criteria are missing or low-N/contradictions block promotion. |
| `eligible_for_promotion` | Criteria pass for the stated narrow scope, but no write has happened yet. |
| `promoted` | A separate playbook/process write occurred and cites this bundle. |
| `rejected` | Evidence does not justify policy change. |
| `superseded` | A newer bundle/candidate replaces this review. |
| `monitor_only` | Useful pattern to watch, but not eligible for durable policy. |

Allowed per-criterion result states:

| Criteria state | Meaning |
|---|---|
| `pass` | Criterion satisfied for the stated scope. |
| `fail` | Criterion not satisfied and blocks promotion. |
| `needs_evidence` | Missing evidence prevents a decision. |
| `caveated` | Criterion is partially satisfied but caveats must be retained. |
| `not_applicable` | Criterion does not apply to this candidate/scope. |

Allowed top-level `criteria_result` values:

| Result | Meaning |
|---|---|
| `promote_narrow` | Promote only within the explicit approved scope. Requires a separate playbook/process write. |
| `reject` | Do not promote; retain evidence for audit. |
| `needs_evidence` | Keep candidate quarantined until more evidence resolves gaps. |
| `monitor_only` | Track future cases without changing durable policy. |
| `supersede_existing` | Replace or narrow an existing rule with explicit supersession provenance. |
| `single_case_exception` | Narrow critical-risk exception path from §8. |

## 10. Promotion, rejection, and supersession criteria

### 10.1 Promotion criteria

A candidate is eligible only when all required criteria pass or are explicitly caveated without blocking promotion:

1. reflection and candidate provenance are complete;
2. intended policy/playbook/rule target is explicit;
3. strategy/playbook/agent/model/environment/run scope is explicit;
4. linked decisions/non-actions, forecasts, outcomes/scores, sources, recall receipts, replay examples, and adherence/override evidence are included where applicable;
5. support and contradiction evidence are separated;
6. repeated pattern requirement is satisfied, or §8 critical-risk exception is used;
7. low-N and source caveats are carried into the decision;
8. no unresolved contradiction invalidates the proposed scope;
9. promotion is narrow by default;
10. no automatic global policy promotion occurs.

`eligible_for_promotion` means "ready for a separate explicit lifecycle write," not "already active policy."

### 10.2 Rejection criteria

Reject or keep quarantined when any of the following holds:

- missing reflection/candidate provenance;
- no explicit strategy/playbook/agent/model/environment/run scope;
- single-case evidence without a valid critical-risk exception;
- low-N evidence presented as general policy support;
- known contradictory cases omitted or unresolved;
- source caveats undermine the candidate and cannot be narrowed;
- recall receipts show the relevant lesson/rule was stale, superseded, ignored, or not attributable without explanation;
- replay/failure/override examples show the candidate is too broad;
- candidate text would create advice/execution/fetching behavior or a performance-ranking claim;
- candidate attempts automatic global promotion.

### 10.3 Supersession criteria

Use `supersede_existing` only when the bundle identifies:

- existing rule/playbook IDs to supersede or narrow;
- evidence that the old rule is stale, overbroad, contradicted, repeatedly overridden, not computable, or scoped incorrectly;
- the new narrower scope and retained caveats;
- explicit `supersedes` provenance in the later playbook/process write.

Supersession never deletes old audit history. Old rules remain readable with validity/supersession metadata.

## 11. Future consumers

Likely future consumers include a policy-candidate report, playbook version proposal workflow, bootstrap/read-model surfaces, and replay/regression diagnostics. Those consumers must treat this document as a contract for evidence shape and criteria semantics, not as authorization to implement automatic policy mutation.

