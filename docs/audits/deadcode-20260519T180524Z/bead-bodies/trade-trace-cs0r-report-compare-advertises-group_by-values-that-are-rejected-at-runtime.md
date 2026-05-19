# trade-trace-cs0r — report.compare advertises group_by values that are rejected at runtime

Status: open
Type: bug
Priority: P3
Labels: api-contract, bug, bughunt, bughunt:exhaustive-refresh-20260519, dead-code, deadcode-hunt, deadcode:refresh-20260519, domain:reports, domain:reports-memory, needs-owner-confirmation, public-api, stale-contract

## Description

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

Deadcode refresh merge section (DC-REFRESH-003):
Reference search scope: tracked src/tests/docs/README/pyproject, excluding docs/audits/** and audits/** for final judgement.
Reference search commands: `git grep -n DOCUMENTED_GROUP_BY -- ':!docs/audits/**' ':!audits/**'`; source readback of `src/trade_trace/reports/compare.py` runtime group_by allowlists.
Public/dynamic caveat: `DOCUMENTED_GROUP_BY` is exported via `__all__`, so this refresh does not classify it as safe dead-code removal without owner/downstream confirmation.
Why it may be falsely alive: downstream callers may import the exported constant, or it may be intended planned metadata rather than current runtime support.
Duplicate rationale: DC-REFRESH-003 originally created duplicate `trade-trace-yv9z`; final duplicate scan showed this existing bughunt bead is canonical, so `trade-trace-yv9z` was closed and this bead carries the refresh labels/notes.
Safe-removal / repair validation: `python3 -m pytest tests/integration/test_report_compare.py tests/security/test_report_sql_filters.py tests/golden/test_cli_mcp_parity.py -q` plus ruff/source readback for compare/report tooling.
Provenance: repo-deadcode-hunt candidate DC-REFRESH-003 in `docs/audits/deadcode-20260519T180524Z/candidate-matrix.json`.


## Notes

Deadcode refresh DC-REFRESH-003 merged here on 2026-05-19. The refresh found the same exported DOCUMENTED_GROUP_BY/runtime group_by mismatch; canonical remediation remains this existing bughunt bead. See docs/audits/deadcode-20260519T180524Z/candidate-matrix.json.

## Acceptance

Advertised group_by values match runtime behavior; Tests cover every advertised group_by or schema omits unsupported values; Errors distinguish invalid from unsupported-for-base-report
