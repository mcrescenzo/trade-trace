Context:
Materialized from repo-simplification-review row SIMP-006 (SIMPL-REPORTS-001/002/004) under epic trade-trace-mea1. Domain: reports. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Extract small shared report-row and result helpers where report semantics already match. Complexity class: duplicate-logic.

Evidence:
- reports/calibration.py _load_scored_rows and reports/compare.py _load_grouped_scored_rows duplicate scored-forecast predicates, joins, late-recorded handling, and p_yes/y resolution.
- Many report modules hand-build similar ReportResult summary/group envelope shapes.
- calibration.py and compare.py repeat ReportFilter SQL predicate leaf handling and placeholder utilities.

Why simplification is safe/desirable:
The target removes duplicated mechanics or contract-drift surface while preserving existing behavior. It is bounded to the cited files/surfaces and requires compatibility validation before close.

Target simplification:
Extract only exact common substrate for scored-row loading, small result construction, and predicate helpers. Do not introduce a broad report class hierarchy.

Non-goals:
- Do not change CLI/MCP contracts, storage semantics, report schemas, security posture, or agent-facing workflow policy.
- Do not perform broad rewrites or introduce generic frameworks beyond the bounded helper/decision described here.
- Do not absorb deferred/rejected matrix rows into this work without a new explicit decision.

Behavior preservation:
- Preserve current observable behavior for all cited public/tool/test surfaces.
- For investigation rows, preserve behavior by not refactoring until the findings record defines exact current behavior and validation evidence.

Risks / intentional complexity check:
Some duplication is intentional for compatibility, auditability, release safety, or security boundaries. Keep intentional explicitness where the validation plan cannot prove an equivalent simpler shape.

Validation:
- python -m pytest tests/integration/test_report_calibration.py tests/integration/test_report_compare.py tests/integration/test_report_filter.py tests/contracts/test_report_envelope_completeness.py tests/integration/test_report_sample_warnings.py
- Compare representative report JSON before/after for calibration, compare, and one non-scored report.

Acceptance criteria:

- Simplification is limited to the cited bounded surface.
- Existing behavior and public contracts are preserved.
- Listed validation passes or any gap is explicitly resolved before close.
- No unrelated behavior change or broad rewrite lands under this bead.

Provenance:
Discovered by repo-simplification-review candidate SIMP-006 from source candidate(s) SIMPL-REPORTS-001/002/004. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
