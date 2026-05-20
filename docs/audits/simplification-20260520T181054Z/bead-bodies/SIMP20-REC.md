Context:
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
