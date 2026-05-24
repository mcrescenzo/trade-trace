# Agent continuity dogfood runbook

> Status: **shipped** as of 2026-05-24; local operator runbook for the `agent-continuity-loop` fixture and AC-01..AC-09 scorecard checks. This is a deterministic local replay/regression procedure, not live trading validation.

Companion docs: [Agent continuity dogfood scorecard](agent-continuity-scorecard.md), [Agent continuity entity contracts](agent-continuity-contracts.md), [MVP dogfood protocol](dogfood-protocol.md), [Replay case bundles](replay-case-bundles.md), [Agent guide](../AGENT_GUIDE.md).

## 1. Purpose and scope

Use this runbook when an operator or future agent needs an end-to-end, local-first dogfood pass for agent-continuity behavior: bootstrap recovery, due/stale local work, recall receipt usefulness, process caveats, read-only report behavior, replay label separation, and policy quarantine.

The run is intentionally narrow:

- It exercises checked-in deterministic fixture data for `agent-continuity-loop`.
- It evaluates scorecard criteria AC-01..AC-09 from `agent-continuity-scorecard.md`.
- It uses only a local temp `TT_HOME` SQLite journal and caller-supplied fixture rows.
- It validates process continuity and machine-readable boundaries; it does **not** validate live trading decisions, market accuracy, profit, alpha, or broker behavior.

## 2. Preconditions

From a clean repository checkout with the project Python environment available:

1. Run from the repository root.
2. Use a disposable local journal home: `export TT_HOME="$(mktemp -d)"`.
3. Keep command execution deterministic with the fixed read boundary `as_of=2026-02-15T00:00:00Z`.
4. Seed only the deterministic continuity fixture:
   `PYTHONPATH=src tt journal fixture_seed --home "$TT_HOME" --target agent-continuity-loop --allow-no-idempotency`.
5. Do not configure broker credentials, wallet credentials, network fetchers, daemons, schedulers, or remote services for this run.

## 3. Exact local commands

### Focused regression tests

```bash
PYTHONPATH=src pytest \
  tests/integration/test_agent_continuity_fixture.py \
  tests/docs/test_agent_continuity_scorecard_contract.py \
  -q
```

### Manual CLI smoke

```bash
export TT_HOME="$(mktemp -d)"
export AS_OF="2026-02-15T00:00:00Z"

PYTHONPATH=src tt journal init --home "$TT_HOME"
PYTHONPATH=src tt journal fixture_seed --home "$TT_HOME" --target agent-continuity-loop --allow-no-idempotency

PYTHONPATH=src tt agent bootstrap --home "$TT_HOME" --as-of "$AS_OF" --filter-json '{}'
PYTHONPATH=src tt agent next_actions --home "$TT_HOME" --as-of "$AS_OF" --stale-threshold-days 14
PYTHONPATH=src tt report recall_receipts --home "$TT_HOME" --recall-id rec_agent_continuity_0001
PYTHONPATH=src tt report strategy_health --home "$TT_HOME" --as-of "$AS_OF" --min-sample 20
PYTHONPATH=src tt report forecast_diagnostics --home "$TT_HOME" --min-sample 20
```

`replay.case_bundle` needs a local forecast ID from the seeded journal. Discover it from the local SQLite database, then export a one-case bundle. This command is local-only and mirrors the integration fixture; use `tt tool schema --home "$TT_HOME" --tool replay.case_bundle` if the CLI surface changes.

```bash
FORECAST_ID="$(
  PYTHONPATH=src python - <<'PY'
import sqlite3, os
from pathlib import Path
from trade_trace.storage.paths import db_path
home = os.environ["TT_HOME"]
with sqlite3.connect(db_path(Path(home))) as conn:
    row = conn.execute("SELECT forecast_id FROM forecast_scores ORDER BY id LIMIT 1").fetchone()
    if row is None:
        raise SystemExit("no forecast_scores row in fixture")
    print(row[0])
PY
)"

PYTHONPATH=src tt replay case_bundle --home "$TT_HOME" \
  --as-of 2026-01-02T00:00:00Z \
  --case-selection-json "{\"source_refs\":[{\"kind\":\"forecast\",\"id\":\"${FORECAST_ID}\"}],\"max_cases\":1}" \
  --task-json '{"mode":"blind_decision","include_evaluation_labels":true}'
```

## 4. Expected artifacts and evidence

A passing run produces local JSON envelopes for each command above and enough evidence to mark AC-01..AC-09 pass/fail:

- AC-01/AC-02: `agent.bootstrap` includes obligations and `agent.next_actions` includes at least one stale-review or due-resolution work item with local `source_refs` and forbidden actions.
- AC-03: `report.recall_receipts --recall-id rec_agent_continuity_0001` returns the deterministic receipt, two returned memory node IDs, and at least one `cited_or_used` item.
- AC-04: recall/health/diagnostics outputs surface caveats for contradicted or low-sample evidence and avoid advice/ranking/profit language.
- AC-05: read reports do not change core journal table counts; the focused integration test is the authoritative check.
- AC-06: bootstrap and work-queue outputs expose no-fetch/no-broker/no-execution/no-scheduler boundaries.
- AC-07: bootstrap output includes budgets, truncation state, omitted counts, or count-unavailable caveats so partial output is absence-unsafe.
- AC-08: `replay.case_bundle` keeps future score/outcome labels out of candidate-visible case context while allowing evaluator-only labels when explicitly requested.
- AC-09: the fixture has exactly one quarantined policy-candidate reflection and no extra active playbook version from that candidate.

No private raw transcripts, source bodies, API secrets, broker credentials, wallet material, or remote artifacts are required. If operators retain evidence, keep raw output in ignored local paths and commit only a sanitized summary using IDs, command names, scorecard status, caveat codes, and artifact paths that do not reveal private source content. Follow the evidence policy in `agent-workbench-dogfood-evidence.md`.

## 5. Failure interpretation and operator controls

Treat failures as fixture/contract/test signals, not subjective operator judgment. Do not waive a failure because the output “looks useful.” Update the fixture, scorecard, docs, schemas, or deterministic tests so the expected behavior is machine-checkable.

| Failure signal | Interpretation | Operator control |
|---|---|---|
| Missing obligations in `agent.bootstrap` or no stale/due items in `agent.next_actions` | AC-01/AC-02 cannot prove continuity recovery. | Inspect fixture inventory and lifecycle/work-queue report contracts; update fixture rows or scorecard expectations before claiming pass. |
| Stale ideas not surfaced | Staleness thresholds, local source rows, or work-queue synthesis are misaligned. | Use fixed `AS_OF`; adjust deterministic fixture or report tests, not ad hoc operator memory. |
| Recall receipt mismatch or missing `rec_agent_continuity_0001` | AC-03 provenance is broken or fixture IDs drifted. | Re-seed fresh `TT_HOME`; if still failing, update fixture seed and recall receipt tests together. |
| False confidence, advice, ranking, or profit language appears | AC-04/boundary failure. | Tighten report caveats and forbidden-language tests; do not sanitize after the fact and call it pass. |
| Hidden writes during bootstrap/reports | AC-05 failure; read surfaces are mutating source-of-truth tables. | Stop dogfood claims; isolate the mutating tool and update implementation/tests. Explicit recall telemetry belongs only in the originating recall contract. |
| Network/default-off violation | AC-06 failure; the run is no longer caller-supplied/local-only. | Disable the path, add/repair no-network tests, and document any future opt-in separately. |
| Truncation or partial output without counts/caveats | AC-07 failure; absence cannot be interpreted safely. | Require `truncation`, `omitted_counts`, or count-unavailable caveats before relying on missing obligations/memories. |
| Replay label leakage into candidate context | AC-08 failure and regression risk. | Quarantine replay outputs; update `replay.case_bundle` and leakage tests before using bundles for evaluation. |
| Policy quarantine missing or promoted to active playbook | AC-09 failure; unreviewed lessons may become policy. | Restore quarantine semantics and playbook-version count tests; never treat a reflection as active policy by operator choice alone. |

## 6. Boundary and non-goals

This runbook explicitly excludes:

- Broker, exchange, wallet, custody, order-placement, signing, execution, fill-quality, or position-truth validation.
- Live market data, source content, news, filings, price, broker state, or outcome fetching.
- Financial advice, live returns, alpha, market ranking, trade recommendation, buy/sell/hold/sizing/enter/exit guidance, or backtesting-results criteria.
- Scheduler, daemon, generic task manager, dispatcher, alerting, retries, locks, leases, shared assignment, collaboration UI/dashboard, or remote coordination.
- Any requirement for hosted services, shared databases, remote operators, or deployment coordination.

All artifacts remain CLI/MCP/JSON-first, local-first SQLite, and based on caller-supplied data only.

## 7. Optional escalation gates

Current roadmap decisions from the H3-H5 research/docs chain remain deferred unless repeated deterministic dogfood failures demand escalation:

- **AgentRun table/API:** defer while row-level `actor_id`, `agent_id`, `model_id`, `environment`, `run_id`, request IDs, and idempotency are enough for attribution and replay grouping.
- **Durable work-item state:** defer while derived `agent.bootstrap`, `report.lifecycle`, `report.work_queue`, and `agent.next_actions` expose obligations without assignment, claiming, snooze, locks, or scheduler semantics.
- **Standalone handoff coordination:** defer while bootstrap/work-queue/recall receipts support single-agent continuity; any future handoff must be a bounded packet over existing local surfaces, not a coordination service.

Escalate only with repeated, reproducible failures in the local runbook that cannot be fixed by fixture, scorecard, report, or test updates under the existing boundaries.
