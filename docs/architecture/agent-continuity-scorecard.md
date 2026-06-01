# Agent continuity dogfood scorecard

> Status: **contract precursor** for trade-trace-c6ja.2. This local scorecard defines measurable implementation-readiness criteria for the `agent-continuity-loop` fixture and related reports; it is not a trading-results, live-market, or advice evaluation.

Companion docs: [Agent continuity dogfood runbook](agent-continuity-dogfood-runbook.md), [Agent continuity entity contracts](agent-continuity-contracts.md), [MVP dogfood protocol](dogfood-protocol.md), [Agent guide](../AGENT_GUIDE.md).

## Purpose

The agent-continuity loop is useful only if a fresh/stateless agent can recover local obligations, stale ideas, memory provenance, and boundary caveats without hidden external assumptions. This scorecard converts that claim into deterministic local checks tied to checked-in fixtures, reports, and tests.

The scorecard is intentionally agent-only and local-first:

- Seed data with `journal.fixture_seed --target=agent-continuity-loop`.
- Evaluate only the local SQLite journal and Trade Trace read reports.
- Treat writes as explicit fixture setup or explicit caller actions; read reports must not create hidden journal facts.
- Exclude any criterion based on trading returns, live-market outcome quality, alpha, market ranking, broker verification, or financial advice.

## Reproducible local setup

From the repository root:

```bash
PYTHONPATH=src pytest tests/integration/test_agent_continuity_fixture.py
```

For a manual local journal run:

```bash
export TT_HOME="$(mktemp -d)"
PYTHONPATH=src tt journal init --home "$TT_HOME"
PYTHONPATH=src tt journal fixture_seed --home "$TT_HOME" --target agent-continuity-loop --allow-no-idempotency
PYTHONPATH=src tt report bootstrap --home "$TT_HOME" --as-of 2026-02-15T00:00:00Z --filter-json '{}'
PYTHONPATH=src tt report work_queue --home "$TT_HOME" --as-of 2026-02-15T00:00:00Z --stale-threshold-days 14
PYTHONPATH=src tt report recall_receipts --home "$TT_HOME" --recall-id rec_agent_continuity_0001
PYTHONPATH=src tt report strategy_health --home "$TT_HOME" --as-of 2026-02-15T00:00:00Z --min-sample 20
PYTHONPATH=src tt report forecast_diagnostics --home "$TT_HOME" --min-sample 20
```

The setup is reproducible when run from a fresh home: the fixture uses a frozen clock and deterministic IDs. Raw/private transcripts are not required; if a dogfood run records additional evidence, sanitize it per [Agent workbench dogfood evidence retention](agent-workbench-dogfood-evidence.md).

## Pass/fail interpretation

A run is **implementation-ready** when every required metric below passes on a fresh `agent-continuity-loop` fixture and the focused tests pass. A failed metric means the continuity loop is not yet ready for dogfood claims, even if individual reports still run.

A metric may be marked **blocked** only when the cited fixture/report surface is intentionally absent or a product decision is still open. In that case, do not substitute a subjective operator judgment; update this scorecard or the fixture contract first.

## Scorecard metrics

| ID | Metric | Required threshold | Fixture/report evidence | Focused checks |
|---|---|---:|---|---|
| AC-01 | Missed obligations recovered | `report.bootstrap` returns at least one obligation and `report.work_queue` returns at least one stale-review or due-resolution item for `as_of=2026-02-15T00:00:00Z`. | `agent-continuity-loop` fixture; `report.bootstrap`; `report.work_queue`; source refs and forbidden actions on work-queue items. | `tests/integration/test_agent_continuity_fixture.py::test_agent_continuity_fixture_exercises_bootstrap_work_queue_recall_and_health`; `tests/integration/test_work_queue_next_actions.py` |
| AC-02 | Stale ideas recovered | Work-queue or bootstrap evidence includes a stale local record or due forecast derived from existing journal rows, with no scheduler claim/assignment semantics. | Stale watch and unscored forecast seeded by `agent-continuity-loop`; `report.lifecycle`; `report.work_queue`. | `tests/integration/test_agent_continuity_fixture.py`; `tests/integration/test_bootstrap_report_surface.py`; `tests/integration/test_work_queue_next_actions.py` |
| AC-03 | Memory usefulness evidenced | The deterministic recall receipt `rec_agent_continuity_0001` returns two node IDs and at least one returned memory is cited or used downstream. | `memory_recall_events`; `edges` from the overlay; `report.recall_receipts`. | `tests/integration/test_agent_continuity_fixture.py`; `tests/integration/test_recall_receipts.py`; `tests/integration/test_memory_usefulness.py` |
| AC-04 | False-confidence/advice incidents surfaced or absent | Outputs under the fixture include local caveats for contradicted or low-sample evidence and contain none of the forbidden advice/ranking phrases locked by tests. | `report.recall_receipts` caveat codes; `report.strategy_health`; `report.forecast_diagnostics`; bootstrap hard constraints. | `tests/integration/test_agent_continuity_fixture.py`; `tests/integration/test_strategy_health_report.py`; `tests/integration/test_forecast_diagnostics_report.py` |
| AC-05 | Hidden writes absent from read reports | Table counts for core journal tables are unchanged before vs. after bootstrap, next-actions, recall-receipts, and health reads. Any allowed recall telemetry must be explicit in the originating tool contract, not hidden inside unrelated reports. | SQLite counts for `decisions`, `forecasts`, `outcomes`, `memory_nodes`, `edges`, `memory_recall_events`, `playbook_versions`, and `decision_playbook_rules`. | `tests/integration/test_agent_continuity_fixture.py::test_agent_continuity_fixture_exercises_bootstrap_work_queue_recall_and_health` |
| AC-06 | No-network/default-off proof | The fixture and reports use caller-supplied local rows only and expose hard constraints/forbidden actions for no fetch, no broker/wallet state, no execution, and no scheduler behavior. | `report.bootstrap.hard_constraints`; `report.work_queue.forbidden_actions`; security no-network tests. | `tests/integration/test_agent_continuity_fixture.py`; `tests/security/test_no_network_default.py` |
| AC-07 | Token/truncation behavior explicit | Bootstrap/read packets expose budgets, truncation state, omitted counts or count-unavailable caveats so absence is not treated as proof when output is partial. | `report.bootstrap` budgets/truncation/omitted counts; bootstrap contract in `agent-continuity-contracts.md`. | `tests/integration/test_bootstrap_report_surface.py`; `tests/integration/test_agent_continuity_fixture.py` |
| AC-08 | Replay/evaluation labels kept separate | Replay case bundles can include evaluator-only labels while candidate context excludes future labels and score IDs. | `replay.case_bundle` on a fixture forecast score. | `tests/integration/test_agent_continuity_fixture.py::test_agent_continuity_fixture_exercises_forecast_replay_and_quarantine`; `tests/integration/test_replay_case_bundle.py` |
| AC-09 | Policy changes quarantined before activation | The overlay adds exactly one quarantined policy-candidate reflection and does not create an extra active playbook version from it. | `memory_nodes.meta_json.policy_candidate.status="quarantined"`; `playbook_versions` count. | `tests/integration/test_agent_continuity_fixture.py::test_agent_continuity_fixture_exercises_forecast_replay_and_quarantine` |

## Boundary rules for evaluators

- Do not add pass criteria based on external prices, broker/exchange truth, wallet state, order placement, fill quality, or market-source freshness fetched during the run.
- Do not add pass criteria that recommend buying, selling, holding, sizing, entering, exiting, or ranking instruments.
- Do not treat realized returns, backtest returns, or live performance as evidence that the continuity loop is useful. The scorecard measures process continuity, provenance, caveats, and reproducible local report behavior only.
- Do not treat missing rows as absent when `truncation.is_partial=true`, counts are unavailable, or sections were not requested.

## TraceLab B16 replay caveat

For TraceLab scorecard evidence (B16), rail-adoption findings for coach,
tripwire, advisory, and other read rails must be cited from the **live B1 dispatch trace**, not from replay output. JSONL replay/import is useful for
supported durable write events, but the replay path drops `signal.emitted` and
`memory_node.invalidated` diagnostic lines and never reconstructs read dispatch
calls; therefore these rail-adoption findings are not replay-reproducible.

## Evidence packet template

For a sanitized dogfood evidence note, record:

```markdown
Scorecard version: agent-continuity-scorecard.md
Fixture command: PYTHONPATH=src tt journal fixture_seed --home <temp-home> --target agent-continuity-loop --allow-no-idempotency
As of: 2026-02-15T00:00:00Z
Reports run: report.bootstrap, report.work_queue, report.recall_receipts, report.strategy_health, report.forecast_diagnostics, replay.case_bundle
Metric results: AC-01 pass/fail, ..., AC-09 pass/fail
Local artifacts retained: checked-in tests/docs only, or ignored raw path plus sanitized summary
Boundary confirmation: no network fetch, no execution/custody, no financial advice, caller-supplied data only
```
