# DEFER Report Owner Recommendation Matrix

Date: 2026-07-09

Scope: trade-trace-cjgz2.4 recommendation artifact for the 9 report-catalog cull rows that were left `DEFER`.

Non-scope: this document does not decide the owner disposition, change report registrations, change schemas, change handlers, or update tests. It records an evidence-backed recommendation for owner review.

Current-worktree caveat: this matrix reflects the working tree inspected on 2026-07-09, including pre-existing uncommitted code/docs/test changes from trade-trace-cjgz2.1 and trade-trace-cjgz2.2. It should be re-read against the final commit before owner sign-off.

## Runtime Catalog Readback

Readback command:

```sh
PYTHONPATH=src python3 -c 'from trade_trace.core import build_registry; rows=("report.audit_readiness","report.autonomy_readiness","report.current_exposure","report.execution_quality","report.exposure_anomalies","report.opportunity","report.paper_exposure","report.phase_gate_readiness","report.reconciliation_mismatches"); reg=build_registry(); public=set(reg.public_names()); experimental=set(reg.public_names(include_experimental=True)); print("public_count", len(public)); print("include_experimental_count", len(experimental)); print("name|registered|public|visibility|is_write"); [print(f"{name}|{name in reg.names()}|{name in public}|{reg.get(name).metadata().get('catalog_visibility')}|{reg.get(name).is_write}") for name in rows]'
```

Observed output:

```text
public_count 77
include_experimental_count 87
name|registered|public|visibility|is_write
report.audit_readiness|True|True|public|False
report.autonomy_readiness|True|True|public|False
report.current_exposure|True|True|public|False
report.execution_quality|True|True|public|False
report.exposure_anomalies|True|True|public|False
report.opportunity|True|True|public|False
report.paper_exposure|True|True|public|False
report.phase_gate_readiness|True|True|public|False
report.reconciliation_mismatches|True|True|public|False
```

Conclusion from runtime readback: all 9 rows are currently registered, default-public, and read-only (`is_write=False`). The recommendation below therefore treats `keep public` as the low-mutation path unless an owner chooses a stricter product posture.

## Summary Matrix

| Report | Current registry/catalog status | Proposed disposition | Owner decision status | Highest safety condition |
| --- | --- | --- | --- | --- |
| `report.audit_readiness` | Registered, public, read-only | Keep public | Approved keep public (owner, 2026-07-10) | Must remain local provenance diagnostics, not a trading/autonomy authorization. |
| `report.autonomy_readiness` | Registered, public, read-only | Keep public | Approved keep public (owner, 2026-07-10) | Must remain evidence-only and pass through owner-thresholded gate status. |
| `report.current_exposure` | Registered, public, read-only | Keep public | Approved keep public (owner, 2026-07-10) | Must keep local-projection and broker-truth caveats prominent. |
| `report.execution_quality` | Registered, public, read-only | Keep public | Approved keep public (owner, 2026-07-10) | Must read only imported/local receipt evidence and avoid live execution assurance. |
| `report.exposure_anomalies` | Registered, public, read-only | Keep public | Approved keep public (owner, 2026-07-10) | Must distinguish projection/data-quality caveats from market risk. |
| `report.opportunity` | Registered, public, read-only | Keep public | Approved keep public (owner, 2026-07-10) | Must stay retrospective process diagnostics, not recommendations/backtesting/live advice. |
| `report.paper_exposure` | Registered, public, read-only | Keep public | Approved keep public (owner, 2026-07-10) | Must remain paper-only, local-evidence-only, and non-executing. |
| `report.phase_gate_readiness` | Registered, public, read-only | Keep public | Approved keep public (owner, 2026-07-10) | Must require owner-supplied thresholds and never self-grant readiness. |
| `report.reconciliation_mismatches` | Registered, public, read-only | Keep public | Approved keep public (owner, 2026-07-10) | Must remain local mismatch evidence, not remediation or external account truth. |

## Row Evidence

### `report.audit_readiness`

Proposed disposition: keep public.

Owner decision: APPROVED — keep public (owner sign-off 2026-07-10, recorded in bead trade-trace-degbz).

Evidence:

- Runtime readback above: registered, public, `is_write=False`.
- Registered through `ReportToolRegistration` with a deterministic, no-network, no-advice description in `src/trade_trace/reports/tool_handlers/registration.py:226-238`.
- The schema advertises only stale-threshold inputs and describes the report as read-only local diagnostics in `src/trade_trace/reports/tool_schemas.py:169-175`.
- Implementation states deterministic local diagnostics only, no network, no recommendations in `src/trade_trace/reports/audit_readiness.py:1-4`, and returns only `summary` plus bounded `issues` in `src/trade_trace/reports/audit_readiness.py:70-112`.
- Architecture docs describe it as deterministic SQL over existing journal tables that never fetches market data, scores source credibility, or gives trading advice in `docs/architecture/reports.md:622-624`.
- Tests cover empty-journal safe output, blocker/warning surfacing with remediation, and registered read-only schema in `tests/integration/test_audit_readiness.py:10-16`, `tests/integration/test_audit_readiness.py:68-88`, and `tests/integration/test_audit_readiness.py:148-154`.

Safety rationale and caveats:

- Public visibility is appropriate because the report is diagnostic and helps an owner or agent find provenance gaps before relying on journal records.
- The `ready` flag is audit-readiness only. It must not be described as permission to trade, permission to use a wallet, or a Phase-3 autonomy grant.
- Keep the remediation wording because prior dogfood found blocking issues without an in-surface path to clear them.

Catalog implications:

- If the owner accepts `keep public`, no registration change is needed. Update only the owner disposition record in the cull/decision artifact.
- If the owner rejects and chooses `internalize`, preserve composition for `report.phase_gate_readiness` and `report.autonomy_readiness` while removing the standalone public listing.
- If the owner chooses `remove`, first redesign the gate reports because `audit_readiness` is an explicit input to both.

Required validation for implementation:

- Runtime readback must still show the intended catalog visibility and `is_write=False`.
- Run `tests/integration/test_audit_readiness.py`, `tests/integration/test_phase_gate_readiness.py`, and `tests/integration/test_autonomy_readiness.py` for keep/internalize/remove decisions that affect this row.
- Run `tests/security/test_no_network_default.py` or its relevant smoke row before any claim that the public surface remains no-network by default.

### `report.autonomy_readiness`

Proposed disposition: keep public.

Owner decision: APPROVED — keep public (owner sign-off 2026-07-10, recorded in bead trade-trace-degbz).

Evidence:

- Runtime readback above: registered, public, `is_write=False`.
- Registered as an evidence bundle that composes the owner-thresholded phase gate, adds longitudinal trend/expectancy evidence, and renders no verdict of its own in `src/trade_trace/reports/tool_handlers/registration.py:269-302`.
- Module docstring states evidence-only, not a verdict; no code path can grant autonomy beyond the underlying gate in `src/trade_trace/reports/autonomy_readiness.py:1-44`.
- Implementation passes thresholds straight through to `report_phase_gate_readiness`, re-projects criteria, and returns `non_executing` plus `local_evidence_only` in `src/trade_trace/reports/autonomy_readiness.py:390-514`.
- Phase-gate docs describe the bundle as evidence-only and note that the owner-decision invariant holds transitively in `docs/architecture/phase-gates.md:147-202`.
- Tests pin public registration, bundle composition, ready/gate-status pass-through, and the invariant that a strong trend cannot self-grant while any threshold is unset in `tests/integration/test_autonomy_readiness.py:122-180`.

Safety rationale and caveats:

- Public visibility is appropriate because it packages the evidence an owner needs to review autonomy readiness without granting autonomy itself.
- The bundle must not be marketed as a standalone go/no-go verdict. Its only readiness verdict is the underlying owner-thresholded gate result.
- Trend and expectancy series are descriptive evidence and can be low-N; caveat codes such as `LOW_SAMPLE_SIZE` and `PARTIAL_COVERAGE` must stay visible.

Catalog implications:

- If the owner accepts `keep public`, no registration change is needed. Keep docs clear that this is an owner-review packet.
- If the owner chooses `internalize`, update docs that currently list it as shipped/public and verify owner workflows can still get the evidence bundle through the intended internal route.
- If the owner chooses `remove`, preserve or replace any public owner-review path that currently depends on the bundle.

Required validation for implementation:

- Runtime catalog readback for visibility and `is_write=False`.
- Run `tests/integration/test_autonomy_readiness.py` and `tests/integration/test_phase_gate_readiness.py`.
- Run `tests/docs/test_markdown_links.py` if docs references to `phase-gates.md` or report lists are edited.

### `report.current_exposure`

Proposed disposition: keep public.

Owner decision: APPROVED — keep public (owner sign-off 2026-07-10, recorded in bead trade-trace-degbz).

Evidence:

- Runtime readback above: registered, public, `is_write=False`.
- Registered as the recommended trader-agent entry point for open trades/current exposure while saying decisions are activity/audit trail, not canonical exposure, and that it does not assert broker truth in `src/trade_trace/reports/tool_handlers/registration.py:502-517`.
- Schema advertises `limit` and `cursor` and describes the composed buckets in `src/trade_trace/reports/tool_schemas.py:424-443`.
- Handler composes canonical `open_positions`, `event_exposure_sets`, `watchlist`, `recent_trade_activity`, and `projection_anomalies`, and propagates truncation/cursor from open positions in `src/trade_trace/reports/tool_handlers/portfolio_exposure.py:765-862`.
- Current-exposure contract tells agents to use this report first for current exposure and states Trade Trace does not execute trades, place orders, query brokers, or prove broker portfolio truth in `docs/architecture/current-exposure-agent-contract.md:66-85`.
- Tests cover positive empty output, composed buckets, record-only caveats, filtered child buckets, pagination/truncation, bounded default page size, and schema discoverability in `tests/integration/test_report_current_exposure.py:107-410`.
- The Phase-2 paper loop test calls it in a local non-executing fixture and checks `position_truth_caveat` in `tests/integration/test_phase2_paper_trading_loop.py:431-437`.

Safety rationale and caveats:

- Public visibility is appropriate because this is the safer front door for exposure questions compared with raw decisions or lower-level P&L.
- The answer is local journal/projection state. It is not broker truth, imported account truth, settlement truth, redemption truth, or external portfolio truth.
- Pagination/truncation is a safety requirement because silent under-reading can make an agent believe exposure is smaller than it is.

Catalog implications:

- If the owner accepts `keep public`, no registration change is needed; maintain it as the documented default current-exposure entry point.
- If internalized or removed, update `report.pnl` next-actions, current-exposure docs, open-trades agent docs, and tests that currently direct agents here.
- Any future public status must retain `limit`/`cursor`, truncation, and lower-level-report links.

Required validation for implementation:

- Runtime catalog readback for visibility and `is_write=False`.
- Run `tests/integration/test_report_current_exposure.py`, `tests/integration/test_open_trades_agent_surface.py`, `tests/contracts/test_tool_schema_runtime_parity.py::test_current_exposure_and_pnl_schema_discoverability_for_open_trades`, and `tests/integration/test_phase2_paper_trading_loop.py::test_phase2_paper_trading_loop_is_repeatable_local_and_non_executing` for behavior-affecting changes.

### `report.execution_quality`

Proposed disposition: keep public.

Owner decision: APPROVED — keep public (owner sign-off 2026-07-10, recorded in bead trade-trace-degbz).

Evidence:

- Runtime readback above: registered, public, `is_write=False`.
- Registered as read-only local execution-quality/slippage diagnostics over imported external receipts, pre-trade intents, and local snapshots, with no fetch, broker access, execution, cancellation, remediation, advice, alpha, or profit claims in `src/trade_trace/reports/tool_handlers/registration.py:171-184`.
- Schema repeats the local-only/no-execution boundary and exposes only filtering/threshold inputs in `src/trade_trace/reports/tool_schemas.py:143-160`.
- Implementation reads `external_execution_receipts`, optional `pretrade_intents`, and snapshots, then returns caveat codes and `non_executing`, `local_evidence_only`, `credential_blind`, and `advice_free` flags in `src/trade_trace/reports/execution_quality.py:104-249`.
- Tests cover missing snapshot, partial fill, rejected receipt, stale snapshot, cancel failure, stale open imported evidence, spread-crossing boundaries, sparse/no-data caveats, and local/non-executing flags in `tests/integration/test_execution_quality_report.py:64-187`.
- Boundary tests pin `report.execution_quality` as a public process report in `tests/security/test_mvp_boundary_audit.py:498-510`.

Safety rationale and caveats:

- Public visibility is appropriate because it helps operators inspect imported receipt quality without opening a live execution or remediation path.
- The report only evaluates local/imported evidence. It must not imply Trade Trace fetched, verified, cancelled, or remediated anything externally.
- Slippage values are computed only where local numeric evidence exists; missing evidence must remain explicit through caveat codes.

Catalog implications:

- If the owner accepts `keep public`, no registration change is needed.
- If internalized, update the Phase-2 public catalog docs and tests that treat it as the unfrozen process report.
- If removed, preserve another local diagnostic path for imported receipt quality before relying on reconciliation or external receipt rows.

Required validation for implementation:

- Runtime catalog readback for visibility and `is_write=False`.
- Run `tests/integration/test_execution_quality_report.py` and `tests/security/test_mvp_boundary_audit.py::test_unfrozen_process_reports_are_public`.
- If descriptions change, run `tests/security/test_mvp_boundary_audit.py::test_registered_tool_descriptions_do_not_emit_uncaveated_advice_claims`.

### `report.exposure_anomalies`

Proposed disposition: keep public.

Owner decision: APPROVED — keep public (owner sign-off 2026-07-10, recorded in bead trade-trace-degbz).

Evidence:

- Runtime readback above: registered, public, `is_write=False`.
- Registered as a read-only current-exposure ambiguity/data-quality caveat report, not market risk or broker truth, in `src/trade_trace/reports/tool_handlers/registration.py:485-501`.
- Schema lists stable projection-anomaly codes and says the report covers local journal/projection data quality, not market risk or broker truth, in `src/trade_trace/reports/tool_schemas.py:399-423`.
- Handler emits `projection_anomalies` for entry decisions without projection lineage, record-only actual rows, duplicate decisions, fragmented same-side exposure, missing/stale marks, and missing/stale projections in `src/trade_trace/reports/tool_handlers/portfolio_exposure.py:358-557`.
- Tests cover positive empty output, duplicate/record-only/missing-event anomalies, missing/stale marks, fragmented same-side exposure, projection missing/stale, and schema text that includes stable codes plus `not market risk` in `tests/integration/test_report_exposure_anomalies.py:107-242`.
- `report.current_exposure` composes this lower-level report and exposes it as `projection_anomalies` in `tests/integration/test_report_current_exposure.py:107-118` and `src/trade_trace/reports/tool_handlers/portfolio_exposure.py:804-859`.

Safety rationale and caveats:

- Public visibility is appropriate because it gives agents a direct, caveated way to explain why exposure answers may be incomplete or ambiguous.
- The report must keep `market_risk` separate from projection/data-quality risk. A clean result does not prove external market risk is low.
- It must remain a diagnostic drilldown, not a remediation or broker-verification path.

Catalog implications:

- If the owner accepts `keep public`, no registration change is needed; keep the report visible as a drilldown linked from `report.current_exposure`.
- If internalized, `report.current_exposure` can still compose it, but public docs and `lower_level_reports` should not advertise the standalone tool.
- If removed, `report.current_exposure` needs another way to surface projection anomalies.

Required validation for implementation:

- Runtime catalog readback for visibility and `is_write=False`.
- Run `tests/integration/test_report_exposure_anomalies.py` and `tests/integration/test_report_current_exposure.py`.
- Run `tests/contracts/test_report_envelope_completeness.py` if report-envelope membership changes.

### `report.opportunity`

Proposed disposition: keep public.

Owner decision: APPROVED — keep public (owner sign-off 2026-07-10, recorded in bead trade-trace-degbz).

Evidence:

- Runtime readback above: registered, public, `is_write=False`.
- Registered as path-dependent opportunity diagnostics over supplied snapshots, with no external price fetching, and defaulted optional arguments in `src/trade_trace/reports/tool_handlers/registration.py:369-397`.
- Implementation replays decisions against supplied post-decision snapshots, labels derived historical process outcomes, emits caveats for sparse/missing snapshots, and bounds records through `max_records` in `src/trade_trace/reports/opportunity.py:1-8` and `src/trade_trace/reports/opportunity.py:168-353`.
- Opportunity docs explicitly state two non-negotiable constraints: no price fetching and process diagnostics, not recommendations, in `docs/architecture/opportunity-analysis.md:9-24`.
- The same docs state it is not a backtester, market simulator, recommendation engine, or real-time tool in `docs/architecture/opportunity-analysis.md:126-138`.
- Tests cover public registration, classification labels, sparse/missing snapshot caveats, duplicate outcome/position de-fanout, and unsupported-filter validation in `tests/integration/test_report_opportunity.py:131-333`.
- Tool-schema parity tests cover defaulted arguments and accepted `minimum_coverage` values in `tests/contracts/test_tool_schema_runtime_parity.py:100-176`.

Safety rationale and caveats:

- Public visibility is acceptable only if copy and examples keep the report retrospective and process-oriented.
- This is the riskiest name in the 9-row set because `opportunity` can be misread as a trading signal. Keep the strongest caveat: no recommendation, no live advice, no backtest, no synthetic prices, no external fetching.
- Labels such as `missed_positive_edge` and `good_skip` describe what happened in supplied historical rows. They must not be phrased as what to trade next.

Catalog implications:

- If the owner accepts `keep public`, no registration change is needed; consider a follow-up docs/copy hardening pass that keeps the non-recommendation boundary visible in model-facing text.
- If the owner chooses `internalize`, update PRD/report docs and any schema examples that advertise the report as shipped public.
- If the owner chooses `remove`, update tests and docs that treat it as a shipped local journal/projection analysis report.

Required validation for implementation:

- Runtime catalog readback for visibility and `is_write=False`.
- Run `tests/integration/test_report_opportunity.py` and the `report.opportunity` sections of `tests/contracts/test_tool_schema_runtime_parity.py`.
- Run `tests/security/test_mvp_boundary_audit.py::test_registered_tool_descriptions_do_not_emit_uncaveated_advice_claims` after any wording changes.

### `report.paper_exposure`

Proposed disposition: keep public.

Owner decision: APPROVED — keep public (owner sign-off 2026-07-10, recorded in bead trade-trace-degbz).

Evidence:

- Runtime readback above: registered, public, `is_write=False`.
- Core comments state the paper-fill ledger cluster, including `report.paper_exposure`, was unfrozen into the public Phase-2 catalog and is paper-only, non-executing, local-evidence-only, credential-blind, and free of venue client/signing/order-placement/cancellation/fund-movement paths in `src/trade_trace/core.py:240-257`.
- Handler aggregates only filled `paper_fill_records` rows into a paper-only exposure/P&L basis and returns `paper_only`, `non_executing`, and `no_live_execution_claims` in `src/trade_trace/tools/paper_fills.py:290-307`.
- Registration description states paper-only exposure/P&L basis with explicit exclusion of imported/live truth or execution claims in the `registry.register(...)` call at `src/trade_trace/tools/paper_fills.py:339`.
- Tests cover paper exposure netting/exclusion behavior and pin public, non-experimental status in `tests/integration/test_paper_fill_records.py:303-335`.
- The Phase-2 paper loop test calls `report.paper_exposure` and asserts `non_executing` plus `no_live_execution_claims` in `tests/integration/test_phase2_paper_trading_loop.py:423-429`.
- Boundary tests list `report.paper_exposure` in `SHIPPED_REPORTS` and document the public Phase-2 catalog rationale in `tests/security/test_mvp_boundary_audit.py:335-345` and `tests/security/test_mvp_boundary_audit.py:512-541`.

Safety rationale and caveats:

- Public visibility is appropriate because the report makes paper exposure explicit instead of letting agents infer exposure from paper-fill rows.
- The report must never imply real fills, live execution, imported account truth, settlement, redemption, or funds at risk.
- It should remain tied to `paper_fill_records` only and should not silently include external/account truth rows.

Catalog implications:

- If the owner accepts `keep public`, no registration change is needed.
- If internalized or removed, update the Phase-2 loop, paper-fill docs, and freeze-state tests that currently pin public catalog membership.
- A remove/internalize decision should also specify whether `paper_fill.record/get/list` remain public without this aggregating report.

Required validation for implementation:

- Runtime catalog readback for visibility and `is_write=False`.
- Run `tests/integration/test_paper_fill_records.py`, `tests/integration/test_phase2_paper_trading_loop.py`, and `tests/security/test_mvp_boundary_audit.py::test_unfrozen_paper_fill_ledger_is_public`.

### `report.phase_gate_readiness`

Proposed disposition: keep public.

Owner decision: APPROVED — keep public (owner sign-off 2026-07-10, recorded in bead trade-trace-degbz).

Evidence:

- Runtime readback above: registered, public, `is_write=False`.
- Registered as measurable Phase-2 to Phase-3 gate criteria computed from the journal and compared to owner-supplied thresholds; unset thresholds can never yield ready in `src/trade_trace/reports/tool_handlers/registration.py:239-268`.
- Schema requires owner-supplied thresholds for criteria and states any unset criterion reports `pass=null` and the gate is never ready in `src/trade_trace/reports/tool_schemas.py:176-203`.
- Module docstring states numeric thresholds are an owner decision, no default pass bar is embedded, and ready can only be true when the owner supplied every threshold and all criteria clear in `src/trade_trace/reports/phase_gate_readiness.py:1-29`.
- Implementation sets `owner_thresholds_unset`, `insufficient_data`, `not_ready`, or `ready` and returns `non_executing` plus `local_evidence_only` in `src/trade_trace/reports/phase_gate_readiness.py:222-388`.
- Phase-gate docs state measurement is shipped but thresholds are unfinalized owner decisions, and the gate can never return ready until owner thresholds are set in `docs/architecture/phase-gates.md:1-8` and `docs/architecture/phase-gates.md:76-107`.
- Tests cover public registration, unset-threshold non-readiness, no self-grant with a strong record, and threshold validation in `tests/integration/test_phase_gate_readiness.py:108-140` and `tests/integration/test_phase_gate_readiness.py:236-263`.

Safety rationale and caveats:

- Public visibility is appropriate because the report gives transparent owner-review evidence and structurally prevents omitted bars from becoming a pass.
- The report is a measurement, not authorization. Passing it is not equivalent to unfreezing Phase 3 or granting a wallet.
- Owner thresholds must not be committed or implied without explicit owner sign-off.

Catalog implications:

- If the owner accepts `keep public`, no registration change is needed; keep threshold placeholders explicitly non-authoritative.
- If internalized, ensure owners still have an accessible way to run the gate and review criteria.
- If removed, `report.autonomy_readiness` must be redesigned because it composes this gate.

Required validation for implementation:

- Runtime catalog readback for visibility and `is_write=False`.
- Run `tests/integration/test_phase_gate_readiness.py` and `tests/integration/test_autonomy_readiness.py`.
- Run `tests/docs/test_markdown_links.py` if phase-gate docs are edited.

### `report.reconciliation_mismatches`

Proposed disposition: keep public.

Owner decision: APPROVED — keep public (owner sign-off 2026-07-10, recorded in bead trade-trace-degbz).

Evidence:

- Runtime readback above: registered, public, `is_write=False`.
- Core comments state the reconciliation cluster, including `report.reconciliation_mismatches`, was unfrozen into the public Phase-2 catalog; it is local-evidence-only, credential-blind, non-executing, and has no fetch/sign/place/cancel/settle/fund-movement/remediation path in `src/trade_trace/core.py:259-276`.
- Handler reads `reconciliation_records`, returns deterministic mismatch-code aggregates plus `local_evidence_only` and `non_executing`, and provides agent hints that Trade Trace does not cancel, halt, remediate, fetch private state, or move funds in `src/trade_trace/tools/reconciliation.py:380-399`.
- Registration description says it reports local reconciliation mismatch records and stable mismatch codes for external operators with no remediation or execution path in the `registry.register(...)` call at `src/trade_trace/tools/reconciliation.py:430`.
- Reconciliation tests pin public, non-experimental status and state the cluster was unfrozen into the public Phase-2 catalog in `tests/integration/test_reconciliation_records.py:210-241`.
- The Phase-2 paper loop test calls the report and asserts `non_executing`, `credential_blind`, and empty mismatch codes for the local fixture in `tests/integration/test_phase2_paper_trading_loop.py:455-459`.
- Boundary tests list it in `SHIPPED_REPORTS` and document the no-remediation/no-fund-movement public-catalog rationale in `tests/security/test_mvp_boundary_audit.py:340-345` and `tests/security/test_mvp_boundary_audit.py:544-574`.

Safety rationale and caveats:

- Public visibility is appropriate because mismatch records are operator evidence and make imported-vs-local discrepancies explicit.
- The report must not imply Trade Trace fetched private account state, proves broker truth, halts trading, remediates mismatches, settles, redeems, or moves funds.
- Manually flagged codes must remain distinct from deterministically derived mismatch codes so reproducibility is not overstated.

Catalog implications:

- If the owner accepts `keep public`, no registration change is needed.
- If internalized or removed, update Phase-2 loop tests, reconciliation docs, and public-catalog pins.
- A remove/internalize decision should specify whether `reconciliation.record/get` remain public without the report.

Required validation for implementation:

- Runtime catalog readback for visibility and `is_write=False`.
- Run `tests/integration/test_reconciliation_records.py`, `tests/integration/test_phase2_paper_trading_loop.py`, and `tests/security/test_mvp_boundary_audit.py::test_unfrozen_reconciliation_cluster_is_public`.

## Cross-Row Recommendation

Recommended owner action: approve `keep public` for all 9 rows, subject to the safety conditions above.

Reason: the current runtime catalog already exposes all 9 rows publicly; all 9 are read-only; docs/tests/source evidence show local-evidence, non-executing, no-advice, owner-thresholded, or caveated behavior. Moving any row to `internalize`, `remove`, or `keep deferred` would be a real product/catalog change and should be handled by a follow-up implementation bead after owner sign-off.

## Owner Decision Record (2026-07-10)

- The owner approved `keep public` for all 9 rows on 2026-07-10; the decision
  is recorded in bead `trade-trace-degbz`.
- The residual blockers listed at preparation time are resolved: this matrix
  was re-verified on 2026-07-10 against the clean committed tree at `e00ac30`
  (runtime readback reproduced identical output — `public_count 77`,
  `include_experimental_count 87`, all 9 rows registered/public/read-only —
  and the targeted catalog/registration tests passed).
- Because the approved disposition ratifies the current runtime state, no
  registration, schema, handler, or test changes were required.
- Three citation errata found during the 2026-07-10 re-verification were
  fixed in place in this document: the `reports.md` line range for the
  audit-readiness architecture quote (601-606 → 622-624), and the
  registration-description cites for `report.paper_exposure`
  (`paper_fills.py:310-316` → `:339`) and `report.reconciliation_mismatches`
  (`reconciliation.py:402-407` → `:430`), which previously pointed inside the
  handler bodies rather than at the `registry.register(...)` calls.
