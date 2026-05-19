Context:
security-config-ops — src/trade_trace/tools/__init__.py, src/trade_trace/tools/errors.py, src/trade_trace/contracts/__init__.py, src/trade_trace/contracts/grammar.py, src/trade_trace/tools/admin.py

Observed behavior:
Fresh `import trade_trace.tools.admin` fails unless import order seeded.

Expected behavior:
Representative public modules import directly in fresh process.

Evidence:
primary_evidence.txt direct_import_admin: ImportError cannot import ToolError from partially initialized trade_trace.tools.errors.

Failure mode / impact:
Package consumers/tests/admin integrations can fail on import-order-dependent cycle.

## Steps to Reproduce
python3 - <<PY
import trade_trace.tools.admin; import trade_trace.tools.errors
PY

Duplicate check:
Compared against existing open and closed bughunt items in preflight_prior_bughunt_readback.txt. Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback. Possible overlap: none.

Suggested fix direction:
Repair the cited contract/runtime path with the smallest behavior-preserving change; add the listed regression proof.

Validation:
python3 - <<PY
import trade_trace.tools.admin; import trade_trace.tools.errors
PY

Acceptance criteria:
- Fresh imports of trade_trace.tools.admin and trade_trace.tools.errors succeed
- Core CLI/MCP startup still succeeds
- Direct-import smoke tests added

Provenance:
Discovered by repo-bughunt candidate CAND-010 in domain security-config-ops.