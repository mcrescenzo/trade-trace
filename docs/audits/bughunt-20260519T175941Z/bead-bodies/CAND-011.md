Context:
docs-packaging-ci-contracts — docs/PRD.md, src/trade_trace/tools/journal.py, src/trade_trace/cli.py

Observed behavior:
Documented opt-in flag is accepted but leaves embeddings disabled.

Expected behavior:
Flag either works as documented or docs remove it and unsupported flags do not imply success.

Evidence:
primary_evidence.txt journal_init_enable_embeddings_noop: command ok=true, journal status embeddings_provider none; tools/journal.py ignores flag.

Failure mode / impact:
Agents/operators believe vector recall is enabled when it is not.

## Steps to Reproduce
tmp=$(mktemp -d); TRADE_TRACE_HOME=$tmp python3 -m trade_trace.cli journal init --enable-embeddings; TRADE_TRACE_HOME=$tmp python3 -m trade_trace.cli journal status

Duplicate check:
Compared against existing open and closed bughunt items in preflight_prior_bughunt_readback.txt. Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback. Possible overlap: none.

Suggested fix direction:
Repair the cited contract/runtime path with the smallest behavior-preserving change; add the listed regression proof.

Validation:
tmp=$(mktemp -d); TRADE_TRACE_HOME=$tmp python3 -m trade_trace.cli journal init --enable-embeddings; TRADE_TRACE_HOME=$tmp python3 -m trade_trace.cli journal status

Acceptance criteria:
- Either implement journal.init --enable-embeddings or remove docs claim
- No docs imply silent successful embedding opt-in unless status changes
- Validation confirms documented setup path truth

Provenance:
Discovered by repo-bughunt candidate CAND-011 in domain docs-packaging-ci-contracts.