# trade-trace-8bdd — Remove unused internal decision-matrix/test helpers

Status: open
Type: task
Priority: P4
Labels: cleanup-candidate, dead-code, deadcode-hunt, deadcode:refresh-20260519, domain:tests, domain:tools

## Description

Context:
Domains: tools/tests.
Candidate: DC-REFRESH-002, batched from raw `COLUMNS` and `_thesis_for` findings.

Dead-code claim:
Two internal/private helpers appear unused and can be removed or intentionally wired.

Evidence:
- `src/trade_trace/tools/decision_matrix.py:18` defines `COLUMNS`; excluding audits, `git grep COLUMNS` finds no use except the definition. Live validation iterates `DECISION_MATRIX` in `validate_decision_fields`, called from ledger write paths.
- `tests/integration/test_report_risk.py:50` defines `_thesis_for`; excluding audits, reference search finds only the definition. It is not a pytest fixture, autouse fixture, parametrization name, or test function. `_instrument()` now seeds the needed thesis internally.
- `python3 -m pytest --collect-only -q tests` collected 1046 tests in the lane; `test_report_risk.py` is live but `_thesis_for` is not used.

Reference search scope:
Tracked `src` and `tests`, active docs as needed, excluding audit artifacts.

Reference search commands / output summary:
- `git grep -n COLUMNS -- ':!docs/audits/**' ':!audits/**'` -> `decision_matrix.py` definition plus unrelated timestamp constant substring; no use of decision-matrix `COLUMNS`.
- `git grep -n _thesis_for -- ':!docs/audits/**' ':!audits/**'` -> definition only.
- Ruff scoped unused-name checks passed in delegated lane.

Why it may be falsely alive:
`COLUMNS` may be intended for future docs generation; `_thesis_for` may be a near-future test helper. No current repo evidence supports either.

Impact / risk of keeping:
Low but real clutter: stale ordering artifact in a validation module and dead test helper in a live test file.

Recommended action:
Remove both or wire them into real validation/tests.

Safe-removal validation:
- `python3 -m ruff check src/trade_trace/tools/decision_matrix.py src/trade_trace/tools/ledger.py tests/integration/test_report_risk.py`
- `python3 -m pytest tests/integration/test_report_risk.py tests/integration/test_manual_ledger_flow.py tests/integration/test_ledger_event_emission.py -q`

Duplicate check:
Not a duplicate of the closed 2026-05-18 `_all_columns` test-helper candidate; no open duplicate found in pre-mutation scans.

Acceptance criteria:
- `COLUMNS` and `_thesis_for` are removed or used intentionally.
- Exact-symbol reference search after the change shows no stale definitions.
- Relevant ruff and pytest checks pass.

Provenance:
Discovered by repo-deadcode-hunt candidate DC-REFRESH-002 in docs/audits/deadcode-20260519T180524Z/candidate-matrix.json.


## Notes



## Acceptance

COLUMNS and _thesis_for removed or intentionally used; exact-symbol search clean; targeted ruff/pytest pass.
