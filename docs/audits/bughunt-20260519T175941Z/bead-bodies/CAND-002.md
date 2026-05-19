Context:
cli-mcp-contracts-tools — src/trade_trace/cli.py, docs/architecture/contracts.md, src/trade_trace/tools/memory.py

Observed behavior:
Repeated array flags overwrite and comma arrays remain strings.

Expected behavior:
Documented repeated/comma array syntax works, or docs/schema narrow to JSON-only arrays.

Evidence:
primary_evidence.txt parse_arrays_and_mcp_schemas: repeated node_types -> scalar last value; comma list -> scalar string; docs/contracts.md documents array flags.

Failure mode / impact:
Docs-following agents cannot pass list filters; values may be silently dropped.

## Steps to Reproduce
python3 - <<PY ... _parse_kv_args repeated/comma assertions ... PY

Duplicate check:
Compared against existing open and closed bughunt items in preflight_prior_bughunt_readback.txt. Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback. Possible overlap: none.

Suggested fix direction:
Repair the cited contract/runtime path with the smallest behavior-preserving change; add the listed regression proof.

Validation:
python3 - <<PY ... _parse_kv_args repeated/comma assertions ... PY

Acceptance criteria:
- Documented array encoding works or docs require --*-json only
- Repeated list args do not silently drop earlier values
- Contract tests cover real list-valued tool argument

Provenance:
Discovered by repo-bughunt candidate CAND-002 in domain cli-mcp-contracts-tools.