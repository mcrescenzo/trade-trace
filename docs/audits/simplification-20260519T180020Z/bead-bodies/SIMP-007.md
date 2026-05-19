Context:
Materialized from repo-simplification-review row SIMP-007 (SIMPL-REPORTS-003) under epic trade-trace-mea1. Domain: reports. This row was user-authorized for materialization after the original report-only fallback.

Current complexity:
Co-locate or auto-register report filter support declarations to reduce drift. Complexity class: contract-drift.

Evidence:
- src/trade_trace/reports/_filter_support.py centralizes SUPPORTED_FILTER_FIELDS while individual reports separately pass repeated report-name strings to enforce_supported_filter() and applied_filter_view().
- tools/reports.py and report modules must stay aligned when a report adds/removes supported filters.

Why simplification is safe/desirable:
The target removes duplicated mechanics or contract-drift surface while preserving existing behavior. It is bounded to the cited files/surfaces and requires compatibility validation before close.

Target simplification:
Move report filter support declarations closer to implementations or add an explicit registration path that keeps supported filters and report names in one place.

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
- python -m pytest tests/integration/test_report_filter.py tests/contracts/test_json_schema_derivation.py tests/contracts/test_report_envelope_completeness.py
- Verify unsupported filter errors and applied_filter views remain byte/field compatible for representative reports.

Acceptance criteria:

- Simplification is limited to the cited bounded surface.
- Existing behavior and public contracts are preserved.
- Listed validation passes or any gap is explicitly resolved before close.
- No unrelated behavior change or broad rewrite lands under this bead.

Provenance:
Discovered by repo-simplification-review candidate SIMP-007 from source candidate(s) SIMPL-REPORTS-003. Original artifacts: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z.
