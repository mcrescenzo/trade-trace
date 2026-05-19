Context:
tests-fixtures-crosscutting — tests/golden/test_journal_status_parity.py, src/trade_trace/storage/paths.py

Observed behavior:
Test reads ~/.trade-trace/XDG default and fails when initialized.

Expected behavior:
Test uses tmp_path/monkeypatched home and is hermetic.

Evidence:
Full pytest and targeted pytest fail: schema_version 10 != 0; lane-packets/lane-5.md isolated TRADE_TRACE_HOME temp run passes.

Failure mode / impact:
Full suite false-red depends on developer/CI machine state.

## Steps to Reproduce
python3 -m pytest -q tests/golden/test_journal_status_parity.py::test_journal_status_parity

Duplicate check:
Compared against existing open and closed bughunt items in preflight_prior_bughunt_readback.txt. Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback. Possible overlap: none.

Suggested fix direction:
Repair the cited contract/runtime path with the smallest behavior-preserving change; add the listed regression proof.

Validation:
python3 -m pytest -q tests/golden/test_journal_status_parity.py::test_journal_status_parity

Acceptance criteria:
- Test uses isolated temporary home
- Passes with real default home initialized or absent
- Full suite no longer fails on machine state

Provenance:
Discovered by repo-bughunt candidate CAND-012 in domain tests-fixtures-crosscutting.