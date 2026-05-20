# Lane 2 status: completed

What I did:
- Inspected the in-scope ledger/tool/projection files:
  - /home/hermes/code/trade-trace/src/trade_trace/tools/ledger.py
  - /home/hermes/code/trade-trace/src/trade_trace/models/ledger.py
  - /home/hermes/code/trade-trace/src/trade_trace/projections.py
  - /home/hermes/code/trade-trace/src/trade_trace/events/unit_of_work.py
- Inspected relevant tests:
  - tests/integration/test_projection_rebuild.py
  - tests/integration/test_ledger_event_emission.py
  - tests/integration/test_memory_layer.py
  - searched broader tests for forecast.supersede, source.attach, idempotency, projection coverage
- Ran a read-only verification subset:
  - python3 -m pytest tests/integration/test_projection_rebuild.py tests/integration/test_ledger_event_emission.py tests/integration/test_memory_layer.py::test_memory_node_stats_rebuildable_from_events -q
  - Result: 36 passed in 0.77s
- Confirmed current branch/commit:
  - main / ffcd97420bf44c846451bd5d39596d39437d6e3e
- No files were created or modified.

Coverage accounting:
- Covered assigned domain: ledger-tools-projections.
- Covered known hotspots:
  - _forecast_supersede: src/trade_trace/tools/ledger.py:1567-1805
  - _forecast_add: src/trade_trace/tools/ledger.py:568-726
  - _decision_add: src/trade_trace/tools/ledger.py:791-928 via structural scan, not line-by-line deep audit
  - _score_one_forecast: src/trade_trace/tools/ledger.py:1077-1184 via structural scan, not line-by-line deep audit
  - _make_source_attacher/_handler: src/trade_trace/tools/ledger.py:1412-1514
  - projections: src/trade_trace/projections.py:42-393
  - UnitOfWork: src/trade_trace/events/unit_of_work.py:38-113
- Out-of-scope avoided:
  - no edits
  - no Beads writes
  - no storage migration review except where projection behavior/test comments referenced it
  - no push/publish/delete

Intentional complexity check:
- Several large/duplicated regions appear justified by correctness constraints:
  - UnitOfWork atomicity is load-bearing: relational rows, events, outbox, projections, and dry-run rollback all share one transaction.
  - forecast.supersede intentionally duplicates parts of forecast.add to avoid a previously documented two-transaction lineage corruption window; lines 1567-1587 explain this, and lines 1623-1791 keep forecast insert, outcomes, edge insert, supersede event, and late auto-score inside one transaction.
  - source.attach target validation is justified by source/event integrity: lines 1435-1461 refuse phantom target IDs before edge insertion.
  - projection rebuilds intentionally enforce deterministic append-only replay and invariant rejection; tests cover idempotence, signed quantity conventions, rollback on invalid reversal fills, and reopen semantics.
  - metadata/free-text credential rejection in ledger.py is security/privacy-related and should not be simplified away unless replaced by a central equivalent.

Candidate records:

1. candidate_id: ledger-tools-projections-001
   title: Extract shared forecast write kernel for forecast.add and forecast.supersede
   kind: bounded behavior-preserving refactor
   files:
   - src/trade_trace/tools/ledger.py
   evidence:
   - _forecast_add at lines 568-726 and _forecast_supersede at lines 1567-1805 both perform the same forecast validation, forecast_outcomes insertion, forecast.created payload construction, forecast row insert fields, late resolved_final lookup, _score_one_forecast call, and _emit_forecast_scored call.
   - The duplication is not just cosmetic: current comments at lines 1581-1587 say auto-scoring is intentionally not replicated, but implementation at lines 1755-1791 now does replicate the late auto-score path. This stale local architecture comment is a symptom of duplicated behavior drifting over time.
   - forecast.add’s payload helper exists at lines 602-619; forecast.supersede rebuilds equivalent payload inline at lines 1701-1717.
   proposed_simplification:
   - Introduce an internal helper that runs inside an existing UnitOfWork, e.g. _insert_forecast_core(uow, args, ctx, thesis_id, created_at, idempotency_key, allow_auto_score=True), returning forecast_id, payload, created_at, auto_scored.
   - Keep forecast.supersede as the orchestration layer for prior lookup and supersedes edge/event, but delegate the forecast row/outcomes/payload/auto-score mechanics to the same helper used by forecast.add.
   behavior_preservation_constraints:
   - Must not reintroduce the old two-transaction bug described at lines 1571-1579.
   - forecast.supersede must still insert the new forecast, forecast_outcomes, supersedes edge, edge.created event, forecast.superseded event, and optional forecast.scored event in one UnitOfWork.
   - Idempotency replay for forecast.created must remain before any new forecast/edge insert in supersede, as documented at lines 1638-1647.
   - Event payload shape and result envelope shape must remain stable.
   suggested_tests:
   - Existing targeted tests:
     - tests/contracts/test_event_enum_coverage.py::test_forecast_superseded_event_emitted
     - tests/integration/test_ledger_event_emission.py
   - Add or ensure a focused regression for supersede against an already resolved_final outcome, verifying auto_scored and forecast.scored behavior, because code currently does this but the local comment is stale.
   confidence: high
   risk: medium, because idempotency and atomicity are load-bearing

2. candidate_id: ledger-tools-projections-002
   title: Replace repeated open_db/UnitOfWork/idempotency/replay boilerplate in simple ledger add handlers with a small write helper
   kind: bounded behavior-preserving refactor
   files:
   - src/trade_trace/tools/ledger.py
   evidence:
   - venue.add lines 151-197, instrument.add lines 202-293, snapshot.add lines 298-363, thesis.add lines 368-476, source.attach lines 1416-1512 all repeat the same skeleton:
     - extract idempotency_key
     - open db
     - with UnitOfWork
     - check_idempotency_replay
     - if replay, emit same event and return existing row data
     - otherwise insert primary row
     - emit event
     - finally close db
   - The repetition inflates ledger.py and increases odds of subtle replay/return-shape divergence, especially because replay branches often reconstruct payloads from args rather than central row/payload builders.
   proposed_simplification:
   - Add a local helper/context utility, not a redesign, for the common pattern:
     - with_ledger_uow(args, event_type, actor_id, idempotency_key, replay_handler, write_handler)
     - or a narrower _run_idempotent_insert(args, ctx, event_type, replay_fn, insert_fn)
   - Use it first on low-risk simple handlers: venue.add, snapshot.add, source.attach. Avoid decision/outcome/forecast initially because their side effects are more complex.
   behavior_preservation_constraints:
   - Must preserve db.close in all paths.
   - Must preserve check_idempotency_replay before insert.
   - Must preserve event emission on replay as currently implemented.
   - Must not hide ToolError details or SQLite constraint behavior.
   suggested_tests:
   - tests/integration/test_ledger_event_emission.py
   - strict idempotency tests found via tests/conftest.py markers
   - source.attach not-found tests in contracts/agent ergonomics area
   confidence: medium-high
   risk: low-to-medium if limited to simple handlers

3. candidate_id: ledger-tools-projections-003
   title: Fix stale projection documentation/test naming around memory_node_stats instead of preserving “deferred/no-op” story
   kind: documentation/test simplification
   files:
   - src/trade_trace/projections.py
   - tests/integration/test_projection_rebuild.py
   - tests/integration/test_memory_layer.py
   evidence:
   - tests/integration/test_projection_rebuild.py lines 9-11 still says memory_node_stats is deferred until M3 and rebuild is a no-op.
   - tests/integration/test_projection_rebuild.py lines 293-307 names test_memory_node_stats_rebuild_is_noop and asserts zero rows only because the fixture has no memory_recall_events.
   - Actual implementation at src/trade_trace/projections.py lines 335-393 fully rebuilds memory_node_stats from memory_recall_events, including corrupt-row skipping.
   - tests/integration/test_memory_layer.py lines 484-510 already verifies memory_node_stats is rebuildable from events.
   proposed_simplification:
   - Rename the test and comments in test_projection_rebuild.py to reflect “empty source rebuild returns zero rows,” not “deferred/no-op.”
   - Optionally consolidate memory_node_stats rebuild assertions in one place to reduce contradictory test intent.
   behavior_preservation_constraints:
   - No production behavior change required.
   - Keep coverage for projection=all including memory_node_stats.
   suggested_tests:
   - tests/integration/test_projection_rebuild.py
   - tests/integration/test_memory_layer.py::test_memory_node_stats_rebuildable_from_events
   confidence: high
   risk: low

4. candidate_id: ledger-tools-projections-004
   title: Introduce named row access or typed accumulator state for positions projection
   kind: bounded behavior-preserving refactor
   files:
   - src/trade_trace/projections.py
   evidence:
   - rebuild_positions selects 13 columns at lines 91-108.
   - _accumulate_position then relies on numeric tuple indexes throughout:
     - instrument_id = events[0][1] at line 199
     - opened_at = events[0][10] at line 200
     - decision_id = row[12] in _derive_kind_and_side at line 168
     - event id for error details = row[11] at lines 253 and 265
   - This makes future column/order edits risky and obscures behavior in a function already carrying complex signed quantity/reversal invariants.
   proposed_simplification:
   - Use sqlite3.Row access, a small dataclass, NamedTuple, or constants for row indexes.
   - Keep the replay algorithm and SQL ordering unchanged.
   behavior_preservation_constraints:
   - Preserve ORDER BY position_id, created_at, id.
   - Preserve invariant errors for same-sign exits and over-close reversals.
   - Preserve exact output columns and None-vs-0 behavior for realized/unrealized PnL.
   suggested_tests:
   - tests/integration/test_projection_rebuild.py full file
   - report.pnl sample warning tests that consume positions projection
   confidence: medium-high
   risk: low

5. candidate_id: ledger-tools-projections-005
   title: Centralize source.attach target metadata to reduce registration/schema/validation scattering
   kind: bounded behavior-preserving refactor
   files:
   - src/trade_trace/tools/ledger.py
   evidence:
   - _make_source_attacher dynamically validates supported target kinds through _ATTACH_TARGET_TABLES at lines 1439-1448 and f-string SQL at lines 1450-1452.
   - register_ledger_tools separately registers four attach tools at lines 1931-1941.
   - Tests/contracts mention source.attach_to_* schema coverage, meaning the set of attach tools is externally visible.
   proposed_simplification:
   - Use a single constant mapping target_kind -> {tool_name, table, example_key/schema metadata}, then drive both validation and registration from that mapping.
   - This keeps the current four tool names and does not introduce a generic public source.attach endpoint.
   behavior_preservation_constraints:
   - Keep explicit registered tool names.
   - Keep NOT_FOUND details for source and target.
   - Keep edge_type derivation from source stance: supports/contradicts else about.
   confidence: medium
   risk: low

Merge/reject notes:
- I do not recommend simplifying UnitOfWork itself in this lane. The code is short and load-bearing; dry-run rollback and projection updater execution inside the transaction justify its current structure.
- I do not recommend removing security scans or credential metadata recursion from ledger.py. They are intentional privacy/security complexity.
- I do not recommend a behavior-changing redesign of forecast.supersede. Its duplication is ugly, but the all-in-one UnitOfWork architecture is intentional and should be preserved.

Issues encountered:
- python was not available as python; used python3 instead.
- search output for broad idempotency/supersede queries was noisy/truncated, so I narrowed follow-up reads.
- No repository modifications were made.
