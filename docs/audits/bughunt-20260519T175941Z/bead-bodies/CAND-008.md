Context:
reports-memory-strategy-playbook — src/trade_trace/reports/compare.py, docs/PRD.md, tests/integration/test_report_compare.py

Observed behavior:
Documented/in-code group_by values are rejected by runtime allowlists.

Expected behavior:
Advertised group_by values match runtime behavior or schema/docs are narrowed by base_report.

Evidence:
primary_evidence.txt report_compare_static_snippet: DOCUMENTED_GROUP_BY/PRD list playbook_version_id/liquidity_bucket/confidence_bucket; CALIBRATION_GROUP_SQL/PNL_GROUP_SQL omit them and reject unsupported group_by.

Failure mode / impact:
Agents receive validation errors for documented report.compare inputs.

## Steps to Reproduce
TRADE_TRACE_HOME=$(mktemp -d) pytest -q tests/integration/test_report_compare.py

Duplicate check:
Compared against existing open and closed bughunt items in preflight_prior_bughunt_readback.txt. Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback. Possible overlap: none.

Suggested fix direction:
Repair the cited contract/runtime path with the smallest behavior-preserving change; add the listed regression proof.

Validation:
TRADE_TRACE_HOME=$(mktemp -d) pytest -q tests/integration/test_report_compare.py

Acceptance criteria:
- Advertised group_by values match runtime behavior
- Tests cover every advertised group_by or schema omits unsupported values
- Errors distinguish invalid from unsupported-for-base-report

Provenance:
Discovered by repo-bughunt candidate CAND-008 in domain reports-memory-strategy-playbook.