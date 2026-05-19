Context:
tests-fixtures-crosscutting — tests/integration/test_ndjson_streaming.py, src/trade_trace/tools/review_bundle.py, src/trade_trace/cli.py

Observed behavior:
Stale test uses successful review.bundle call as unsupported-capability error.

Expected behavior:
Exit-code test uses a current real error path or updates expectations for review.bundle success.

Evidence:
Full pytest and targeted pytest fail: test_exit_code_one_on_other_error asserts rc 1, but review.bundle returns rc 0; review_bundle.py registers functional handler.

Failure mode / impact:
Full suite false-red on stale unsupported-capability assumption.

## Steps to Reproduce
python3 -m pytest -q tests/integration/test_ndjson_streaming.py::test_exit_code_one_on_other_error

Duplicate check:
Compared against existing open and closed bughunt items in preflight_prior_bughunt_readback.txt. Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback. Possible overlap: none.

Suggested fix direction:
Repair the cited contract/runtime path with the smallest behavior-preserving change; add the listed regression proof.

Validation:
python3 -m pytest -q tests/integration/test_ndjson_streaming.py::test_exit_code_one_on_other_error

Acceptance criteria:
- Test exercises current real error path for rc=1
- review.bundle success is not used as unsupported fixture
- Targeted and relevant review bundle tests pass

Provenance:
Discovered by repo-bughunt candidate CAND-013 in domain tests-fixtures-crosscutting.