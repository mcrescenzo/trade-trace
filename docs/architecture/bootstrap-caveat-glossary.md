# Bootstrap caveat-code glossary

> Status: **shipped** companion reference for the `report.bootstrap` /
> `agent.bootstrap` read model. It documents the caveat codes the
> bootstrap packet can emit and the one-line gloss surfaced inline under
> `caveats.caveat_glossary` (per trade-trace-o1wr).

The bootstrap packet keeps caveat codes terse inside its various
`*_caveats` arrays and per-item `caveat_codes` fields. To let a
stateless bot tell which caveats matter, every composed packet also
carries:

- `caveats.caveat_glossary` — an object mapping every caveat code that
  appears anywhere in the packet to the one-line gloss below.
- `caveats.caveat_glossary_doc` — a pointer back to this file for the
  canonical, complete list.

The inline glossary is generated from `CAVEAT_GLOSSARY` in
[`src/trade_trace/reports/bootstrap.py`](../../src/trade_trace/reports/bootstrap.py).
The table here is kept in sync with that constant by
`tests/docs/test_bootstrap_caveat_glossary.py`, which fails if a code is
documented in one place but not the other.

A code that appears in a packet but has no registered gloss falls back to
a stable placeholder (`No gloss registered for this code; see the
caveat-glossary doc.`); that placeholder is a bug signal, not a normal
state.

## Codes

### Hard boundary caveats (always present)

| Code | Meaning |
| --- | --- |
| `no_market_data_fetch` | This packet did not fetch live market/price data; treat any market context as caller-supplied and possibly stale. |
| `no_broker_verification` | No broker/exchange was queried; positions and fills reflect the local journal only, not verified account state. |
| `no_trade_execution` | Nothing here was executed; suggestions are inspection prompts, never orders. |
| `no_financial_advice` | Summaries are not buy/sell recommendations or profit claims. |
| `caller_supplied_data_only` | All evidence comes from data the caller previously recorded locally; no external truth was added. |
| `local_read_only_synthesis` | The packet is a read-only synthesis over local rows; it wrote nothing and ran no recall telemetry. |
| `no_scheduler_or_alert_creation` | No jobs, reminders, or alerts were created; obligations are derived signals, not scheduled tasks. |

### Scope caveats (caller left a dimension unscoped)

| Code | Meaning |
| --- | --- |
| `missing_agent_id` | No agent_id was supplied, so the read spans all agents; results may mix unrelated agents. |
| `missing_run_id` | No run_id was supplied, so the read spans all runs; results may mix unrelated sessions. |
| `missing_strategy_ids` | No strategy_id was supplied, so the read spans all strategies; results may mix unrelated strategies. |

### Evidence caveats

| Code | Meaning |
| --- | --- |
| `no_fetch_performed` | No external fetch backed this item; it rests entirely on previously recorded local evidence. |
| `not_trade_advice` | This item is a process artifact, not trading advice or a signal. |
| `not_executed` | This suggested call was not run; the caller must choose whether to invoke it. |
| `requires_caller_supplied_data` | Acting on this suggestion requires the caller to provide external evidence first. |
| `requires_caller_supplied_evidence` | Acting on this suggestion requires the caller to provide external evidence first. |
| `count_unavailable` | An exact available/omitted count could not be computed for this section; absence is not proof of emptiness. |

### Data-quality caveats (from sub-reports)

| Code | Meaning |
| --- | --- |
| `derived_read_only` | Work-queue obligations are derived read-only signals, not a task manager. |
| `local_rows_only` | Only local journal rows were considered; nothing external was consulted. |
| `no_scheduler_daemon_or_reminder` | The work queue is not a scheduler/daemon and created no reminders. |
| `no_assignment_or_broker_action` | No owner assignment or broker action was taken on these obligations. |
| `no_external_fetch_or_market_lookup` | No external fetch or market lookup backed these obligations. |
| `no_trading_advice_or_signal` | Obligations are process prompts, not trading advice or signals. |
| `low_n_decisions` | Too few decisions to make strategy metrics reliable; treat as directional only. |
| `low_n` | Sample size is below the diagnostic minimum; metrics are caveated and may be noise. |
| `caller_supplied_market_reference_only` | Market references come only from caller-supplied snapshots stored locally; no market data was fetched or derived. |
| `no_external_fetch` | No external fetch backed these diagnostics; they rest on local rows only. |
| `not_advice_or_profitability_evidence` | These diagnostics are not trading advice and are not evidence of profitability. |
| `thesis_source_coverage_only_missing_refs` | Source-coverage check only flags theses missing source refs; it does not assess source content. |
| `source_quality_checks_limited_to_thesis_source_refs` | Source-quality checks look only at thesis source refs, not full provenance. |
| `policy_candidates_unsupported_local_surface` | Policy-candidate promotion is not a supported local surface; candidates are read-only. |
| `late_recorded_excluded` | Late-recorded outcomes were excluded from scoring to avoid look-ahead bias. |
| `baseline_unavailable` | No baseline was available, so calibration is reported without a comparison anchor. |
| `missing_source_reference` | Some items lack a source reference, weakening their provenance. |
| `missing_source_ref` | This case has no linked source record; its provenance is incomplete. |
| `missing_market_reference` | A forecast-decision link lacks a market reference, so market context is incomplete. |
| `missing_spread` | Spread context is missing for some references; liquidity quality is unknown. |
| `wide_spread` | A referenced market had a wide spread; fills/marks may be unreliable. |
| `missing_liquidity_context` | Liquidity context is missing for some references. |

### Memory / recall caveats

| Code | Meaning |
| --- | --- |
| `memory_body_omitted` | Memory node bodies were omitted to save budget; only summaries/IDs are shown. |
| `STALE_OR_INVALIDATED_MEMORY` | A recalled memory node is stale or has been invalidated; do not rely on it as current. |
| `STALE_AS_OF_RECEIPT` | The recall receipt itself is stale relative to as_of; the recall may not reflect current memory. |
| `CONTRADICTED_DOWNSTREAM` | A later record contradicts this memory; weigh it against the contradiction. |
| `SUPERSEDED_DOWNSTREAM` | This memory has been superseded by a newer node; prefer the successor. |
| `HARMFUL_DOWNSTREAM` | Downstream evidence suggests acting on this memory was harmful. |
| `NO_DOWNSTREAM_USE_EVIDENCE` | There is no evidence this recalled memory was used downstream. |
| `CONSUMER_INFERENCE_UNSCOPED` | Consumer attribution could not be scoped precisely; usefulness is uncertain. |
| `RETURNED_NODE_MISSING` | A recall returned a node ID that no longer resolves to a stored node. |
| `REJECTED_RECEIPT` | This recall receipt was rejected and should not be treated as valid attribution. |
| `DIAGNOSTIC_ONLY_NO_CAUSAL_CLAIM` | Memory-usefulness metrics are diagnostic associations only; they make no causal claim. |
| `OUTCOME_IMPACT_NOT_INFERRED` | The impact of memory on outcomes was not inferred; correlation is not impact. |
| `NO_EXPECTED_MEMORY_SIGNAL` | No expected-memory signal could be measured for this control; it is not measurable here, not a finding. |
| `BAD_OUTCOME_NOT_CANONICALLY_INFERRED` | High-confidence-bad-outcome control is edge-based only; the bad outcome was not canonically inferred. |
| `HARMFUL_OVERFIT_EDGE_BASED_ONLY` | Harmful-overfit control is edge-based only; treat as a heuristic flag, not a proven failure. |

### Section / structural caveats

| Code | Meaning |
| --- | --- |
| `section_not_requested` | This section was not requested by the caller, so it is empty by choice, not by absence of data. |
| `playbook_detail_not_composed` | Playbook detail is not composed into this packet; drill in via dedicated tools. |
| `section_unavailable` | This section could not be composed (e.g. invalid sub-report inputs); not an assertion of emptiness. |

### Truncation caveats

| Code | Meaning |
| --- | --- |
| `max_items` | The section hit its max-items budget; some rows were omitted (see omitted_counts). |
| `max_chars` | The section hit its max-chars budget and was emptied; raise the budget to see it. |
| `max_total_chars` | The whole packet hit its total-chars budget; some sections were pruned (see omitted_counts). |
