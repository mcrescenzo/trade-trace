# Candidate disposition matrix

Advisor gate applied: CAND-004 kept separate after existing bead inspection; CAND-010 downgraded P2→P3; CAND-007 remains needs-more-evidence; DOC-CI-CONTRACT-001 merged into CAND-003.

- CAND-001 [accept] P2 Unknown CLI commands bypass the JSON error-envelope contract (source: lane-packets/lane-0.md)
  - Reason: Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback.
- CAND-002 [accept] P2 CLI parser documents repeated/comma array flags but passes strings or last value (source: lane-packets/lane-0.md)
  - Reason: Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback.
- CAND-003 [accept] P2 Tool/MCP schema contract is false for most registered tools (source: lane-packets/lane-0.md + lane-packets/lane-4.md)
  - Reason: Accepted as one systemic registry/schema contract bug; raw DOC-CI-CONTRACT-001 is merged here rather than materialized separately.
- CAND-004 [accept] P1 forecast.supersede idempotent retry creates extra replacement forecasts and edges (source: lane-packets/lane-1.md)
  - Reason: Accepted after inspecting trade-trace-cpz2 and trade-trace-re4: existing cpz2 covers missing idempotency-key enforcement; closed re4 covers two-transaction supersede atomicity. This candidate has a distinct failure mode with idempotency_key present: replay writes extra replacement forecast/edges after EventWriter replay.
- CAND-005 [accept] P2 forecast.supersede skips late auto-score when a resolved_final outcome already exists (source: lane-packets/lane-1.md)
  - Reason: Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback.
- CAND-006 [accept] P2 reflection.prompt_for_outcome can attach the wrong forecast/thesis for multi-forecast instruments (source: lane-packets/lane-2.md)
  - Reason: Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback.
- CAND-007 [needs-more-evidence] P3 reflection.prompt_for_outcome omits strategy-scoped prior reflections despite documented packet scope (source: lane-packets/lane-2.md)
  - Reason: Static mismatch is plausible but depends on canonical outcome→strategy resolution; defer until CAND-006 linkage semantics are fixed or dynamically reproduced.
- CAND-008 [accept] P3 report.compare advertises group_by values that are rejected at runtime (source: lane-packets/lane-2.md)
  - Reason: Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback.
- CAND-009 [accept] P1 journal.restore trusts manifest paths and can write outside TRADE_TRACE_HOME (source: lane-packets/lane-3.md)
  - Reason: Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback.
- CAND-010 [accept] P3 Fresh direct import of trade_trace.tools.admin fails with circular ImportError (source: lane-packets/lane-3.md)
  - Reason: Accepted but downgraded per advisor: direct admin module import is an import-order/package-runtime defect, not proven to block CLI/MCP registration. Concrete but lower severity.
- CAND-011 [accept] P3 PRD documents journal.init --enable-embeddings, but the flag is a silent no-op (source: lane-packets/lane-4.md)
  - Reason: Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback.
- CAND-012 [accept] P2 journal.status golden parity test reads the developer default Trade Trace home (source: lane-packets/lane-5.md)
  - Reason: Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback.
- CAND-013 [accept] P2 NDJSON exit-code test expects review.bundle to be unsupported after it became implemented (source: lane-packets/lane-5.md)
  - Reason: Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback.
