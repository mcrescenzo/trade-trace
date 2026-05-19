# Mutation Audit Packet

## Planned mutation
- Run id: 20260519T175941Z
- Repo / Beads DB: /home/hermes/code/trade-trace / /home/hermes/code/trade-trace/.beads
- Epic id: TBD, relation-based membership
- Matrix path: docs/audits/bughunt-20260519T175941Z/candidate_matrix.json
- Candidate-to-bead plan:
- CAND-001 create P2 bug: Unknown CLI commands bypass the JSON error-envelope contract
- CAND-002 create P2 bug: CLI parser documents repeated/comma array flags but passes strings or last value
- CAND-003 merge/update existing trade-trace-3i33: Tool/MCP schema contract is false for most registered tools
- CAND-004 create P1 bug: forecast.supersede idempotent retry creates extra replacement forecasts and edges
- CAND-005 create P2 bug: forecast.supersede skips late auto-score when a resolved_final outcome already exists
- CAND-006 create P2 bug: reflection.prompt_for_outcome can attach the wrong forecast/thesis for multi-forecast instruments
- CAND-007 no create (needs-more-evidence): reflection.prompt_for_outcome omits strategy-scoped prior reflections despite documented packet scope
- CAND-008 create P3 bug: report.compare advertises group_by values that are rejected at runtime
- CAND-009 create P1 bug: journal.restore trusts manifest paths and can write outside TRADE_TRACE_HOME
- CAND-010 create P3 bug: Fresh direct import of trade_trace.tools.admin fails with circular ImportError
- CAND-011 create P3 bug: PRD documents journal.init --enable-embeddings, but the flag is a silent no-op
- CAND-012 create P2 bug: journal.status golden parity test reads the developer default Trade Trace home
- CAND-013 create P2 bug: NDJSON exit-code test expects review.bundle to be unsupported after it became implemented
- Labels / relations / dependencies: relation-only links from epic to every accepted bug/new existing merged bug and final gate. No parent-child links, no blocking dependencies.
- Generated script or command source: docs/audits/bughunt-20260519T175941Z/materialize_bughunt.py

## Pre-snapshots
See `verification/pre_mutation_snapshot.txt`.

## Advisor gate
Advisor accepted materialization with adjustments: CAND-003 merged/systemic; CAND-004 inspected against cpz2/re4 and kept distinct; CAND-010 downgraded to P3; CAND-007 deferred.

## Execution log
Materialization executed via `materialize_bughunt.py`; stdout saved in `materialization_output.txt`.

Actual ID map is durable in `candidate_to_bead_map.json`:
- EPIC -> `trade-trace-4c4i`
- FINAL -> `trade-trace-ck50`
- CAND-001 -> `trade-trace-kynj`
- CAND-002 -> `trade-trace-pybt`
- CAND-003 -> `trade-trace-3i33` (existing bead updated/merged)
- CAND-004 -> `trade-trace-ug7p`
- CAND-005 -> `trade-trace-ld6l`
- CAND-006 -> `trade-trace-vzmq`
- CAND-008 -> `trade-trace-cs0r`
- CAND-009 -> `trade-trace-l24k`
- CAND-010 -> `trade-trace-9oxn`
- CAND-011 -> `trade-trace-0tdt`
- CAND-012 -> `trade-trace-68ew`
- CAND-013 -> `trade-trace-boqe`

Post-materialization repair: existing merged bead `trade-trace-3i33` lacked the local bug-template `## Steps to Reproduce` heading, so it was updated with concrete reproduction commands. Other `bd lint` warnings were pre-existing/out-of-scope beads from separate programs.

## Post-snapshots
- Initial post-materialization verification: `verification/final_verification_preclose.txt`
- Final post-close verification: `verification/final_verification_postclose.txt`
- Final report: `final_report.md`

## Rollback / repair notes
Created items can be identified by label `bughunt:exhaustive-refresh-20260519` and provenance candidate ids in their descriptions. Remove relation links with `bd dep unrelate <epic> <id>` if membership is wrong; close/supersede mistaken bug beads only after inspecting duplicate/fix surface.
