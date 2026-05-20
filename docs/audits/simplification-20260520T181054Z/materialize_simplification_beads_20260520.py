#!/usr/bin/env python3
"""Materialize repo-simplification-review 20260520 Beads."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

REPO = Path('/home/hermes/code/trade-trace')
ART = REPO / 'docs/audits/simplification-20260520T181054Z'
BODY_DIR = ART / 'bead-bodies'
BODY_DIR.mkdir(parents=True, exist_ok=True)
BD = 'bd'
EPIC = 'trade-trace-w3vs'

COMMON_LABELS = ['repo-simplification', 'simplification', 'simplification:20260520', 'behavior-preserving']

items = [
    {
        'key': 'SIMP20-004',
        'title': 'Centralize POSIX permission helpers across storage, exporter, and admin',
        'priority': 'P2',
        'labels': ['candidate:simp20-004', 'domain:storage-events-security', 'complexity:duplicate-logic', 'risk:medium'],
        'body': '''Context:
Domain: storage-events-security. Candidate SIMP20-004.

Current complexity:
File and directory permission tightening is implemented in multiple places with slightly different local names and comments.

Evidence:
- src/trade_trace/storage/database.py:51-75 defines _set_user_only_permissions and _set_user_only_dir_permissions.
- src/trade_trace/storage/database.py:78-89 defines _chmod_wal_shm_siblings.
- src/trade_trace/tools/admin.py:49-70 defines _tighten_file and _tighten_dir.
- src/trade_trace/exporter.py:156-208 performs inline chmod behavior for exported files and parent directories.

Why simplification is safe/desirable:
These paths enforce the same local privacy/security boundary: files should be user-only and directories should be user-only where the platform supports chmod. Divergence here creates maintenance and test drag at a security-sensitive boundary.

Target simplification:
Extract a small internal helper module for chmod_user_only_file, chmod_user_only_dir, and any needed parent-dir helper. Replace local copies while preserving best-effort POSIX behavior and error suppression semantics.

Non-goals:
- Do not weaken permissions.
- Do not change backup/export/database filenames or locations.
- Do not change Windows/non-POSIX behavior beyond preserving existing no-op/best-effort semantics.

Behavior preservation:
- Preserve 0600 file and 0700 directory intent.
- Preserve current suppression of OSError/PermissionError/NotImplementedError where applicable.
- Preserve WAL/SHM sibling chmod behavior.

Validation:
- uv run pytest tests/security/test_file_permissions.py tests/integration/test_outbox_export.py tests/integration/test_admin_tools.py -q
- uv run pytest tests/security -q

Acceptance criteria:
- One internal permission helper module owns file/dir chmod semantics.
- storage/database.py, tools/admin.py, and exporter.py use the shared helper where behavior matches.
- Existing permission/security/export/admin tests pass.
- No unrelated security or storage behavior changes.

Provenance:
Discovered by repo-simplification-review candidate SIMP20-004 in lane storage-events-security.
''',
    },
    {
        'key': 'SIMP20-005',
        'title': 'Extract generic safe path helpers for restore and import containment',
        'priority': 'P2',
        'labels': ['candidate:simp20-005', 'domain:storage-events-security', 'complexity:tangled-ownership', 'security', 'risk:medium'],
        'body': '''Context:
Domain: storage-events-security. Candidate SIMP20-005.

Current complexity:
journal.restore reuses model-import-specific path validation helpers and then wraps/remaps model-oriented errors into restore-specific validation details.

Evidence:
- src/trade_trace/tools/admin.py:129-145 defines _safe_model_relpath and _resolve_under.
- src/trade_trace/tools/admin.py:447-500 journal.restore reuses _safe_model_relpath and manually repeats source-root and home-root containment checks.
- src/trade_trace/tools/admin.py:459-473 catches ToolError from _safe_model_relpath and remaps details for restore.

Why simplification is safe/desirable:
The behavior is good but the ownership is wrong: a model-specific helper now represents a generic manifest/copy-tree path security contract. Generic helpers would reduce cognitive load and reduce future path-validation drift.

Target simplification:
Extract generic safe_relative_path and resolve_under_root helpers. Let model import and journal.restore call the same generic helper while keeping domain-specific error messages/details at call boundaries.

Non-goals:
- Do not relax traversal, absolute path, Windows-drive, symlink, or root-containment checks.
- Do not change ErrorCode.VALIDATION_ERROR behavior for restore manifest path failures.
- Do not redesign restore/import formats.

Behavior preservation:
- Reject empty/non-string, absolute, Windows-drive, and parent-traversal paths.
- Reject resolved source paths outside backup src and destinations outside TRADE_TRACE_HOME.
- Preserve current restore/model error fields or explicitly characterize any difference before implementation.

Validation:
- uv run pytest tests/security/test_restore_manifest_paths.py tests/integration/test_admin_tools.py tests/integration/test_operability_drill.py -q
- Add/confirm direct characterization tests for current restore path error details before refactoring.

Acceptance criteria:
- Generic safe path helpers exist and replace model-specific helper reuse where behavior matches.
- Restore and model import preserve current rejection behavior and error codes/details.
- Listed tests pass.
- No unrelated restore/import behavior changes.

Provenance:
Discovered by repo-simplification-review candidate SIMP20-005 in lane storage-events-security.
''',
    },
    {
        'key': 'SIMP20-011',
        'title': 'Use named row access for positions projection replay',
        'priority': 'P2',
        'labels': ['candidate:simp20-011', 'domain:ledger-tools-projections', 'complexity:state-branching', 'risk:low'],
        'body': '''Context:
Domain: ledger-tools-projections. Candidate SIMP20-011. Includes folded cleanup from SIMP20-013 for stale memory_node_stats projection test wording if touched nearby.

Current complexity:
positions projection replay selects a wide tuple and then relies on numeric indexes across invariant-heavy replay code.

Evidence:
- src/trade_trace/projections.py:91-108 selects 13 columns.
- src/trade_trace/projections.py:168 uses row[12] for decision_id.
- src/trade_trace/projections.py:199-200 uses events[0][1] and events[0][10].
- src/trade_trace/projections.py:253 and 265 use row[11] for event IDs in error details.
- lane evidence also found tests/integration/test_projection_rebuild.py still describes memory_node_stats rebuild as deferred/no-op even though src/trade_trace/projections.py:335-393 implements it.

Why simplification is safe/desirable:
Numeric tuple indexes obscure replay invariants and make future SELECT-column changes risky. Named row access or a small typed event record preserves behavior while making the invariant code auditable.

Target simplification:
Use sqlite3.Row, a NamedTuple/dataclass, or constants for projection row fields. Keep SQL ordering and replay algorithm unchanged. Update stale projection test naming/comments only if part of the same touched surface.

Non-goals:
- Do not change position replay semantics.
- Do not change output columns or PnL calculations.
- Do not alter memory_node_stats behavior except stale wording/tests.

Behavior preservation:
- Preserve ORDER BY position_id, created_at, id.
- Preserve invariant errors for same-sign exits and over-close reversals.
- Preserve realized/unrealized PnL None-vs-0 behavior.

Validation:
- python3 -m pytest tests/integration/test_projection_rebuild.py -q
- python3 -m pytest tests/integration/test_memory_layer.py::test_memory_node_stats_rebuildable_from_events -q
- Run representative P&L/watchlist report tests consuming positions projection.

Acceptance criteria:
- Projection replay no longer depends on unexplained numeric indexes for the wide event tuple.
- Behavior and output shape are unchanged.
- Stale memory_node_stats no-op wording is removed if encountered in the same change.
- Listed tests pass.

Provenance:
Discovered by repo-simplification-review candidates SIMP20-011 and folded SIMP20-013 in lane ledger-tools-projections.
''',
    },
    {
        'key': 'SIMP20-012',
        'title': 'Single-source source.attach target metadata and registration',
        'priority': 'P3',
        'labels': ['candidate:simp20-012', 'domain:ledger-tools-projections', 'complexity:duplicate-logic', 'risk:low'],
        'body': '''Context:
Domain: ledger-tools-projections. Candidate SIMP20-012.

Current complexity:
source.attach target kind metadata is split between validation mappings and explicit tool registration.

Evidence:
- src/trade_trace/tools/ledger.py:1439-1448 validates supported target kinds through _ATTACH_TARGET_TABLES.
- src/trade_trace/tools/ledger.py:1450-1452 uses target-kind-derived table lookup for validation SQL.
- src/trade_trace/tools/ledger.py:1931-1941 separately registers four attach tools.
- tests/contracts cover source.attach_to_* schema visibility, so the set of attach tools is externally visible.

Why simplification is safe/desirable:
The same target-kind set must remain aligned across validation, schema/examples, and registration. A single internal mapping would reduce drift while preserving explicit public tool names.

Target simplification:
Create one internal mapping target_kind -> table/tool/schema/example metadata. Drive both validation and registration from it without adding a generic public source.attach endpoint.

Non-goals:
- Do not change public tool names.
- Do not change source stance edge_type derivation.
- Do not change NOT_FOUND detail behavior for missing source or target.

Behavior preservation:
- Keep all current source.attach_to_* tools registered.
- Keep exact target validation behavior and response shape.

Validation:
- python3 -m pytest tests/contracts/test_tool_schema_runtime_parity.py tests/contracts/test_agent_ergonomics.py tests/integration/test_source_quality.py tests/integration/test_source_attach_to_memory_node.py -q

Acceptance criteria:
- One internal mapping owns source.attach target kind/table/tool metadata.
- Registered attach tools and schemas remain unchanged.
- Source/target validation and edge_type behavior remain unchanged.
- Listed tests pass.

Provenance:
Discovered by repo-simplification-review candidate SIMP20-012 in lane ledger-tools-projections.
''',
    },
    {
        'key': 'SIMP20-019',
        'title': 'Normalize memory-local meta_json parsing in retain and reflect',
        'priority': 'P3',
        'labels': ['candidate:simp20-019', 'domain:reports-memory-playbook', 'complexity:duplicate-logic', 'risk:low'],
        'body': '''Context:
Domain: reports-memory-playbook. Candidate SIMP20-019.

Current complexity:
memory.retain and memory.reflect duplicate meta_json string parsing and object-shape validation.

Evidence:
- src/trade_trace/tools/memory.py:168-186 _memory_retain_in_uow parses string meta_json, validates object shape, and canonicalizes JSON.
- src/trade_trace/tools/memory.py:366-383 _normalize_reflect_input repeats string meta_json parsing/object validation for tag folding.
- Adjacent strategy/playbook metadata serialization differs; cross-tool standardization may be behavior-changing and is out of scope for this bead.

Why simplification is safe/desirable:
The memory-local contract is duplicated inside one module. A helper reduces drift without broadening behavior across tools with different metadata semantics.

Target simplification:
Add a memory-local helper for meta_json object parsing/validation. Apply only to memory.retain and memory.reflect unless a separate behavior-change decision is made.

Non-goals:
- Do not change strategy/playbook metadata_json behavior.
- Do not change memory error codes/messages/details without characterization.
- Do not change secret scanning or tag folding semantics.

Behavior preservation:
- Preserve None -> empty/object behavior, JSON string parsing, object-only validation, field names, and invalid_json details for memory.retain/reflect.

Validation:
- python3 -m pytest tests/integration/test_memory_layer.py tests/integration/test_memory_link.py tests/integration/test_memory_recall_budgets.py tests/security/test_secret_pattern_writes.py -q
- Add direct tests for memory.retain and memory.reflect meta_json string/object/scalar behavior if absent.

Acceptance criteria:
- memory.py has one helper for meta_json object parsing/validation used by retain and reflect.
- Current accepted/rejected meta_json inputs behave the same.
- Listed tests pass.
- No cross-tool metadata behavior changes.

Provenance:
Discovered by repo-simplification-review candidate SIMP20-019 in lane reports-memory-playbook.
''',
    },
    {
        'key': 'SIMP20-021',
        'title': 'Centralize strategy create/update response construction',
        'priority': 'P3',
        'labels': ['candidate:simp20-021', 'domain:reports-memory-playbook', 'complexity:pass-through-layer', 'risk:low'],
        'body': '''Context:
Domain: reports-memory-playbook. Candidate SIMP20-021.

Current complexity:
strategy create/update/replay paths manually build the same response shape even though _strategy_row_to_dict exists.

Evidence:
- src/trade_trace/tools/strategy.py:164-169 defines _strategy_row_to_dict.
- src/trade_trace/tools/strategy.py:157-161 create manually returns the same shape.
- src/trade_trace/tools/strategy.py:329-338 candidate_result manually builds the same shape.
- src/trade_trace/tools/strategy.py:355-363 replay return manually builds the same shape.
- src/trade_trace/tools/strategy.py:388-393 final update return manually builds the same shape.

Why simplification is safe/desirable:
This is small contract-drift prevention: response keys should stay identical across create, update, and idempotent replay.

Target simplification:
Reuse one response builder for all strategy response shapes, possibly by extending _strategy_row_to_dict to accept dict/row or by adding _strategy_response.

Non-goals:
- Do not change strategy SQL, idempotency, event emission, or timestamps.
- Do not change response keys.

Behavior preservation:
- Preserve exact keys: id, name, slug, description, hypothesis, status, created_at, updated_at.
- Preserve updated_at behavior on create and update.
- Preserve idempotent replay returns.

Validation:
- python3 -m pytest tests/integration/test_strategy_tools.py tests/integration/test_reproducibility_replay.py tests/contracts/test_tool_schema_runtime_parity.py -q

Acceptance criteria:
- Strategy create/update/replay response construction uses one helper where behavior matches.
- Response shape and idempotent replay behavior are unchanged.
- Listed tests pass.

Provenance:
Discovered by repo-simplification-review candidate SIMP20-021 in lane reports-memory-playbook.
''',
    },
    {
        'key': 'SIMP20-022-023',
        'title': 'Single-source Console route catalog and static asset provenance guard',
        'priority': 'P2',
        'labels': ['candidate:simp20-022', 'candidate:simp20-023', 'domain:console-backend-frontend', 'complexity:contract-drift', 'complexity:duplicate-logic', 'risk:medium'],
        'body': '''Context:
Domain: console-backend-frontend. Candidates SIMP20-022 and SIMP20-023.

Current complexity:
The Console route/page catalog and packaged static asset source-of-truth are duplicated across backend, frontend, docs, and package data.

Evidence:
- src/trade_trace/console/serve.py:209-220 hard-codes backend app route catalog.
- frontend/console/src/main.tsx:75-89 hard-codes frontend navigation.
- frontend/console/src/main.tsx:380-427 hard-codes frontend route tree.
- docs/CONSOLE.md lists page/API expectations separately.
- src/trade_trace/console/static/app/index.html and assets/console.js are committed separately from frontend source.
- tests/contracts/test_console_shell.py asserts static asset presence but not freshness/provenance.

Why simplification is safe/desirable:
Route catalog drift can break local navigation or fallback behavior, and static-source drift can ship an older Console while source tests pass. Both are source-of-truth simplifications for the same optional local Console surface.

Target simplification:
Introduce a typed frontend route/report definition source that derives nav and route creation. Add a lightweight static asset provenance or release-gate check so packaged static assets are known to correspond to the current frontend build/source contract.

Non-goals:
- Do not add new Console pages or product features.
- Do not change read-only/no-network/no-advice safety posture.
- Do not remove dependencies unless separately covered by deadcode/product-overhaul work.

Behavior preservation:
- Visible routes and report tool mappings remain the same.
- Packaged app serving behavior remains the same.
- Static asset guard should detect drift without changing runtime behavior.

Validation:
- python3 -m pytest tests/contracts/test_console_shell.py tests/contracts/test_console_http_routes.py tests/contracts/test_console_endpoints.py -q
- cd frontend/console && npm test && npm run build
- Verify packaged static asset provenance or rebuild-dirty check is documented and reproducible.

Acceptance criteria:
- Frontend Console nav and route tree are derived from one typed source where practical.
- Backend route fallback/catalog remains aligned with visible app routes or is explicitly reduced to backend-only metadata.
- Static packaged asset freshness/provenance is checked by test, build, or release gate.
- Listed tests/builds pass.
- No Console feature expansion or safety posture change.

Provenance:
Discovered by repo-simplification-review candidates SIMP20-022 and SIMP20-023 in lane console-backend-frontend.
''',
    },
    {
        'key': 'SIMP20-029',
        'title': 'Split journal.fixture_seed into composable deterministic builder profiles',
        'priority': 'P2',
        'labels': ['candidate:simp20-029', 'domain:tests-docs-build', 'complexity:test-drag', 'risk:medium'],
        'body': '''Context:
Domain: tests-docs-build. Candidate SIMP20-029.

Current complexity:
The deterministic fixture seed substrate is monolithic and supports dogfood, diagnostics, console reporting, and browser tests in one large module.

Evidence:
- src/trade_trace/tools/fixture.py is 687 lines.
- It mixes deterministic clock/id generation, generic dispatch wrapper, mvp-eval base seed, mvp-eval-rich overlay, diagnostic source/outcome fixtures, and reporting/console position fixtures.
- tests/integration/test_fixture_seed.py is 282 lines.
- Fixture seed is consumed by tests/console_browser/conftest.py, console reporting adapter/read-model tests, and console HTTP route tests.
- Targeted lane validation: python3 -m pytest tests/integration/test_fixture_seed.py -q => 9 passed, 1 skipped.

Why simplification is safe/desirable:
A single broad seed makes narrow tests depend on unrelated fixture details. Splitting internals into deterministic builder profiles reduces coupling while preserving the public tool contract.

Target simplification:
Keep public journal.fixture_seed behavior stable, but split internals into deterministic IDs/clock helpers, base journal primitives, diagnostic overlays, reporting/position overlay, and a profile registry mapping target -> ordered builders.

Non-goals:
- Do not reduce public mvp-eval or mvp-eval-rich coverage without a product decision.
- Do not change deterministic IDs/counts/hashes unless explicitly approved and tested.
- Do not change Console product behavior.

Behavior preservation:
- Existing fixture targets produce the same rows or explicitly documented equivalent deterministic output.
- Tests using mvp-eval-rich continue to pass.

Validation:
- python3 -m pytest tests/integration/test_fixture_seed.py -q
- python3 -m pytest tests/integration/test_console_reporting_adapter.py tests/integration/test_console_reporting_read_model.py tests/contracts/test_console_http_routes.py -q
- Verify deterministic hashes/counts remain identical for mvp-eval and mvp-eval-rich, or document approved intentional deltas.

Acceptance criteria:
- fixture.py internals are split into composable deterministic builders/profiles.
- Public journal.fixture_seed targets and outputs are preserved or intentionally characterized.
- Narrow tests can use smaller helpers/profiles where safe.
- Listed tests pass.

Provenance:
Discovered by repo-simplification-review candidate SIMP20-029 in lane tests-docs-build.
''',
    },
    {
        'key': 'SIMP20-009',
        'title': 'Investigate shared forecast add/supersede write kernel without breaking atomicity',
        'priority': 'P2',
        'labels': ['candidate:simp20-009', 'domain:ledger-tools-projections', 'complexity:duplicate-logic', 'investigation', 'needs-more-evidence', 'risk:high'],
        'body': '''Context:
Domain: ledger-tools-projections. Candidate SIMP20-009. Investigation/design-first.

Current complexity:
forecast.add and forecast.supersede duplicate forecast row/outcome/payload/auto-score mechanics, but supersede is intentionally all-in-one to avoid a known two-transaction lineage corruption window.

Evidence:
- src/trade_trace/tools/ledger.py:568-726 _forecast_add.
- src/trade_trace/tools/ledger.py:1567-1805 _forecast_supersede.
- src/trade_trace/tools/ledger.py:1581-1587 comments say auto-scoring is intentionally not replicated, but current implementation at 1755-1791 does replicate late auto-score path.
- src/trade_trace/tools/ledger.py:602-619 builds forecast.add payload while 1701-1717 rebuilds equivalent payload inline.

Why investigation-first:
This touches idempotency, event ordering, scoring side effects, and UnitOfWork atomicity. A direct refactor without characterization could reintroduce the old two-transaction bug.

Target investigation:
Characterize exact current behavior for forecast.add and forecast.supersede, especially idempotency replay, supersedes edge/event ordering, resolved_final auto-score behavior, payload shape, and single-transaction guarantees. Decide whether a shared internal write kernel is safe and create downstream implementation beads only after characterization.

Non-goals:
- Do not implement the refactor in this investigation.
- Do not change forecast semantics, event ordering, or scoring.

Validation / findings required:
- tests/contracts/test_event_enum_coverage.py::test_forecast_superseded_event_emitted
- tests/integration/test_ledger_event_emission.py
- Add/confirm a regression for supersede against an already resolved_final outcome verifying auto_scored and forecast.scored behavior.
- Findings must document whether `_insert_forecast_core` or equivalent helper is safe, with exact behavior-preservation criteria.

Acceptance criteria:
- Findings record current forecast.add/supersede behavior and risks.
- Decision says implement shared kernel, defer, or reject, with evidence.
- Any downstream implementation bead includes exact validation commands and ordering/idempotency constraints.
- No production code behavior changes under this investigation.

Provenance:
Discovered by repo-simplification-review candidate SIMP20-009 in lane ledger-tools-projections.
''',
    },
    {
        'key': 'SIMP20-017',
        'title': 'Investigate memory.recall decomposition with ranking and budget characterization',
        'priority': 'P2',
        'labels': ['candidate:simp20-017', 'domain:reports-memory-playbook', 'complexity:god-object', 'investigation', 'needs-more-evidence', 'risk:medium'],
        'body': '''Context:
Domain: reports-memory-playbook. Candidate SIMP20-017. Investigation/design-first.

Current complexity:
_memory_recall is a 237-line orchestration function mixing input parsing, ranking, formatting/budgeting, recall-event writes, stats updates, and meta_hints construction.

Evidence:
- src/trade_trace/tools/memory.py:623-859 _memory_recall.
- Input validation/options: 630-707.
- Ranking orchestration: 712-751.
- Budget/body/provenance formatting: 755-787.
- Recall event + stats writes: 789-823.
- Response/meta_hints construction: 827-859.
- Ranking helpers already exist at 865-1116.

Why investigation-first:
Recall ranking, min_confidence, max_chars budgeting, semantic auto-inclusion, event logging, and memory_node_stats writes are behavior-sensitive. Helper extraction should start with characterization.

Target investigation:
Document exact current ordering/filter/budget/event/meta behavior and decide a safe helper split. Create a downstream implementation bead only after tests prove ranking and budget behavior.

Non-goals:
- Do not change ranking algorithms, constants, semantic provider behavior, or no-network defaults.
- Do not implement decomposition in this investigation.

Validation / findings required:
- python3 -m pytest tests/integration/test_memory_recall_budgets.py tests/integration/test_memory_retrieval_constants.py tests/integration/test_memory_layer.py tests/integration/test_projection_rebuild.py tests/integration/test_reproducibility_replay.py -q
- Add/confirm ordering tests for min_confidence and max_chars interactions before implementation.

Acceptance criteria:
- Findings record exact current parse/rank/format/log/meta phases and behavior-preservation constraints.
- Decision says implement helper split, defer, or reject.
- Any downstream task includes explicit ranking/budget/logging validation.
- No production behavior changes under this investigation.

Provenance:
Discovered by repo-simplification-review candidate SIMP20-017 in lane reports-memory-playbook.
''',
    },
    {
        'key': 'SIMP20-020',
        'title': 'Investigate review.bundle decomposition with hash-stability proof',
        'priority': 'P3',
        'labels': ['candidate:simp20-020', 'domain:reports-memory-playbook', 'complexity:god-object', 'investigation', 'needs-more-evidence', 'risk:medium'],
        'body': '''Context:
Domain: reports-memory-playbook. Candidate SIMP20-020. Investigation/design-first.

Current complexity:
review.bundle mixes filter validation, row fetching, related-record gathering, report summaries, redaction/caveats, and canonical hash/meta construction in one handler.

Evidence:
- src/trade_trace/tools/review_bundle.py:136-158 manually fetches decision rows.
- src/trade_trace/tools/review_bundle.py:161-188 provides _fetch_by_ids.
- src/trade_trace/tools/review_bundle.py:191-249 orchestrates related rows manually.
- src/trade_trace/tools/review_bundle.py:430-548 _review_bundle_handler orchestrates many phases.

Why investigation-first:
review.bundle has deterministic ordering, redaction, caveat, and bundle_hash contracts. Decomposition is desirable only if hash stability and key ordering are characterized.

Target investigation:
Characterize bundle_hash stability, deterministic row ordering, redaction/caveat behavior, and partial report-summary failure behavior. Decide whether to split handler phases and create downstream implementation work only after characterization.

Non-goals:
- Do not change bundle schema, hash inputs, redaction, or partial-failure behavior.
- Do not implement decomposition in this investigation.

Validation / findings required:
- python3 -m pytest tests/integration/test_review_bundle_contract.py tests/security/test_redacted_exports.py tests/security/test_secret_pattern_writes.py -q
- Add/confirm a hash-stability regression before any implementation refactor.

Acceptance criteria:
- Findings record current bundle ordering/hash/redaction/caveat behavior.
- Decision says implement decomposition, defer, or reject.
- Any downstream task includes hash-stability validation.
- No production behavior changes under this investigation.

Provenance:
Discovered by repo-simplification-review candidate SIMP20-020 in lane reports-memory-playbook.
''',
    },
    {
        'key': 'SIMP20-REC',
        'title': 'Reconcile residual report and test-helper simplification findings against 2026-05-19 backlog',
        'priority': 'P2',
        'labels': ['candidate:simp20-014', 'candidate:simp20-015', 'candidate:simp20-016', 'candidate:simp20-027', 'candidate:simp20-028', 'domain:reports-memory-playbook', 'domain:tests-docs-build', 'investigation', 'needs-more-evidence', 'complexity:test-drag', 'risk:medium'],
        'body': '''Context:
Cross-domain reconciliation. Candidates SIMP20-014, SIMP20-015, SIMP20-016, SIMP20-027, and SIMP20-028. Created because the 2026-05-20 review found residual simplification signals that overlap the closed 2026-05-19 simplification backlog.

Current complexity / evidence:
- Closed `trade-trace-qnxt` says report-row/result helper extraction completed, but lane_3 still found report adapter boilerplate and report envelope repetition in tools/reports.py and report modules.
- Closed `trade-trace-x0po` says report filter support declarations were simplified, but lane_3 still found review.bundle filter error conversion drift from report tools.
- Closed `trade-trace-qs5v` says shared initialized_home fixture landed and 20 files migrated, but current AST still finds 37 `home`, 20 `_mcp`, 11 `_envelope`, and 8 `_db` helpers in tests.

Why reconciliation-first:
These may be legitimate residual next-step simplifications, intentionally retained explicit contract examples, or incomplete acceptance from prior closed beads. Creating many duplicate beads would pollute the graph without deciding whether to reopen, supersede, or accept the residual state.

Target investigation:
Compare current code against closed beads `qs5v`, `qnxt`, and `x0po`. Decide for each residual cluster whether:
1. existing closed work is complete and residual duplication is intentional;
2. reopen/update an existing bead is appropriate;
3. create one or more new narrow follow-ups with exact removal lists and validation; or
4. reject/defer.

Non-goals:
- Do not implement report/test helper refactors in this bead.
- Do not reopen closed beads without explicit decision notes and evidence.
- Do not remove contract-example duplication blindly.

Validation / findings required:
- For tests: classify exact duplicate helper bodies vs intentional local examples; preserve per-test isolation.
- For reports: compare residual adapter/envelope/filter patterns against qnxt/x0po acceptance and implementation scope.
- Commands likely needed:
  - python3 -m pytest tests/contracts tests/integration tests/golden -q for test-helper follow-ups.
  - python3 -m pytest tests/contracts/test_report_envelope_completeness.py tests/integration/test_report_filter.py tests/security/test_report_sql_filters.py tests/integration/test_review_bundle_contract.py -q for report follow-ups.

Acceptance criteria:
- Findings classify residual report/test-helper findings with evidence and duplicate/reopen decisions.
- Any downstream bead has an exact file/helper cluster list and validation commands.
- No production/test refactor is performed under this reconciliation bead.
- Closed 2026-05-19 beads are not contradicted silently; any incompleteness is documented.

Provenance:
Discovered by repo-simplification-review candidates SIMP20-014, SIMP20-015, SIMP20-016, SIMP20-027, and SIMP20-028; reconciles against closed epic trade-trace-mea1 and tasks qs5v/qnxt/x0po.
''',
    },
]

final_item = {
    'key': 'SIMP20-FINAL',
    'title': 'Final verification: repo simplification backlog 2026-05-20',
    'priority': 'P2',
    'labels': ['simplification-final', 'verification', 'gate', 'domain:verification', 'risk:medium'],
    'body': '''Context:
Final verification gate for repo-simplification-review 20260520 under epic trade-trace-w3vs.

Current complexity:
This gate ensures the materialized backlog remains behavior-preserving, non-duplicative with the closed 20260519 simplification backlog, and graph-readable.

Required verification:
- Confirm all materialized SIMP20 task/investigation beads are closed, deferred with explicit reasons, or superseded.
- Confirm investigation-first beads closed with findings before any implementation refactor work was created.
- Confirm residual reconciliation bead resolved duplicate/reopen decisions for qs5v/qnxt/x0po overlap.
- Run graph/readback hygiene:
  - bd lint
  - bd orphans
  - bd dep cycles
  - bd dep list trade-trace-w3vs
  - bd graph trade-trace-w3vs
  - bd find-duplicates --status open --threshold 0.45 --limit 100 --json
- Confirm representative `bd show` readbacks preserve evidence, validation, acceptance criteria, and provenance.
- Confirm git status and any repo-local audit artifacts are committed/pushed if the active session scope requires it.

Acceptance criteria:
- No open material simplification row is left without a disposition.
- Duplicate/reconciliation decisions are recorded.
- Final graph/readback/lint/orphan checks are recorded.
- Epic trade-trace-w3vs is ready to close only after this gate passes.

Provenance:
Created by repo-simplification-review 20260520 materialization.
''',
}


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=REPO, text=True, capture_output=True, check=True)

id_map = {}
command_log = []

for item in items + [final_item]:
    labels = ','.join(COMMON_LABELS + item['labels'])
    body_path = BODY_DIR / f"{item['key']}.md"
    body_path.write_text(item['body'])
    acceptance = 'See body acceptance criteria.'
    cmd = [BD, 'create', item['title'], '--type', 'task', '--priority', item['priority'], '--labels', labels, '--body-file', str(body_path), '--acceptance', acceptance, '--json']
    cp = run(cmd)
    obj = json.loads(cp.stdout)
    issue_id = obj['id']
    id_map[item['key']] = issue_id
    command_log.append({'cmd': cmd, 'id': issue_id})
    run([BD, 'dep', 'relate', EPIC, issue_id])

final_id = id_map[final_item['key']]
for item in items:
    # final verification depends on all materialized work items
    run([BD, 'dep', 'add', final_id, id_map[item['key']]])

note = """20260520 materialization note: advisor-gated reduced backlog created from 32 raw simplification candidates. New materialized rows: {rows}. Final verification gate: {final}. Many CLI/MCP, JSONL, release/docs, console dependency/pagination, and prior report/test-helper findings were merged/deferred/reconciled instead of duplicated because closed epic trade-trace-mea1 and current open epics already cover them. Artifact root: docs/audits/simplification-20260520T181054Z.""".format(
    rows=', '.join(id_map[k] for k in [i['key'] for i in items]),
    final=final_id,
)
run([BD, 'update', EPIC, '--append-notes', note])

(ART / 'materialized-id-map.json').write_text(json.dumps(id_map, indent=2, sort_keys=True) + '\n')
(ART / 'mutation-command-log.json').write_text(json.dumps(command_log, indent=2, sort_keys=True) + '\n')
print(json.dumps(id_map, indent=2, sort_keys=True))
