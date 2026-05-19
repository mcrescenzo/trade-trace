Read-only domain-tools-ledger-memory-playbook review complete for /home/hermes/code/trade-trace at HEAD a33e676ec9d22d6ec268686424521a3d2586f9dd.

What I did:
- Verified repo HEAD and observed pre-existing dirty/untracked files before review.
- Enumerated open Beads to avoid duplicates. Existing open items already cover:
  - embeddings opt-in/provider/reindex/model import,
  - MCP stdio/input schemas/docs,
  - exhaustive bughunt gates.
- Reviewed in-scope tool files:
  - src/trade_trace/tools/admin.py
  - src/trade_trace/tools/decision_matrix.py
  - src/trade_trace/tools/fixture.py
  - src/trade_trace/tools/imports.py
  - src/trade_trace/tools/journal.py
  - src/trade_trace/tools/ledger.py
  - src/trade_trace/tools/memory.py
  - src/trade_trace/tools/playbook.py
  - src/trade_trace/tools/reflection.py
  - src/trade_trace/tools/review_bundle.py
  - src/trade_trace/tools/signals.py
  - src/trade_trace/tools/strategy.py
- Cross-checked related tests and docs where they define contract expectations:
  - tests/integration/test_memory_layer.py
  - tests/integration/test_playbook_layer.py
  - tests/integration/test_strategy_tools.py
  - tests/integration/test_signal_scan.py
  - tests/integration/test_review_bundle_contract.py
  - tests/contracts/test_event_enum_coverage.py
  - docs/PRD.md
  - docs/architecture/memory-layer.md
  - docs/architecture/persistence.md
  - README.md

Files created/modified:
- None. This was read-only. I did not edit files, create/update Beads, install dependencies, format, delete, or push.

Issues encountered:
- Repo was already dirty before my review:
  - modified: src/trade_trace/events/log.py
  - modified: src/trade_trace/events/unit_of_work.py
  - modified: src/trade_trace/reports/*
  - modified: src/trade_trace/tools/journal.py
  - untracked: audits/, docs/audits/
- python was not available as `python`; used `python3` where needed.
- No tests were run; review was static/read-only.

Structured candidates:

Candidate DTLMP-001
Title: memory.reflect is not actually atomic despite code/docs claiming reflection node + about edge are written in one transaction
Severity: P1/P2 maintenance/integrity debt
Lens: state-persistence-debt, docs-contract-drift, test-debt
Evidence:
- src/trade_trace/tools/memory.py:230-235 docstring claims memory.reflect writes reflection node and about edge atomically and preserves the no-orphan invariant.
- src/trade_trace/tools/memory.py:254-257 calls _memory_retain(), which opens its own DB connection and UnitOfWork.
- src/trade_trace/tools/memory.py:144-187 shows _memory_retain commits the memory_nodes insert and memory_node.retained event before returning.
- src/trade_trace/tools/memory.py:261-287 then opens a second DB connection and UnitOfWork to insert the about edge.
- Therefore, if edge insert/event emission fails after _memory_retain succeeds, a committed reflection node can be left without the required about edge.
- docs/architecture/memory-layer.md:337-345 says memory.reflect automatically creates the reflection node and target/about edge.
- tests/integration/test_final_dogfood_verification.py:109-129 checks fixture data has no reflection orphans, but does not appear to exercise rollback/failure between node write and edge write.
Concrete carrying cost:
- Maintainers must reason about a “logical transaction” that is actually two physical transactions.
- Any future change to edge validation/event emission can silently violate the reflection orphan invariant.
- Repair/backfill logic would need to detect and reconcile memory_nodes node_type='reflection' with missing about edges.
Suggested remediation:
- Refactor memory.reflect so node insert, memory_node.retained event, about edge insert, and edge.created event all occur in one UnitOfWork/connection.
- Add a regression test that forces edge insertion/event emission failure after the node insert path and asserts no reflection node remains committed.
Duplicate rationale:
- Distinct from existing open embeddings/MCP/schema Beads. This is a current persistence atomicity bug/debt in the shipped memory.reflect path.

Candidate DTLMP-002
Title: memory.reflect implementation only supports target_kind/target_id + about edge, while docs advertise target object plus derived_from/supports/contradicts/supersedes edge sugar
Severity: P2 docs-contract/API drift
Lens: docs-contract-drift, integration-provider-drift, maintenance-hotspot
Evidence:
- Runtime code requires flat args:
  - src/trade_trace/tools/memory.py:237-238 require(args, "target_kind") and require(args, "target_id").
- Runtime code only creates one about edge:
  - src/trade_trace/tools/memory.py:268-283 inserts edge_type='about'.
- README example uses a different contract:
  - README.md:135-137 shows args with "target": {"kind": "decision", "id": "..."} and "insight".
- PRD advertises richer surface:
  - docs/PRD.md:356 says memory.reflect(target, body, *, importance?, derived_from?, supports?, contradicts?, supersedes?, ...).
- memory-layer docs also advertise richer automatic behavior:
  - docs/architecture/memory-layer.md:337-345 says memory.reflect automatically creates about, derived_from, supersedes, supports, and contradicts edges.
Concrete carrying cost:
- Agent/client authors following README/PRD will call memory.reflect with target/insight or edge-list style args and receive validation errors.
- Maintainers have to keep translating between three shapes: docs’ target object, README’s insight field, and code’s target_kind/target_id/body.
- Future MCP inputSchema derivation will likely fossilize the implementation shape and deepen user-visible drift unless docs/code are reconciled.
Suggested remediation:
- Either update docs/examples to the actual target_kind/target_id/body contract, or implement compatibility handling for target={kind,id}, insight alias for body, and optional edge lists.
- Add contract tests that replay README/PRD examples through mcp_call/tool dispatch.
Duplicate rationale:
- Distinct from existing MCP schema Bead. This is not about schema availability; it is a substantive mismatch between documented memory.reflect semantics and current code.

Candidate DTLMP-003
Title: strategy.update accepts idempotency_key but does not perform idempotency replay checks
Severity: P2 write-contract debt
Lens: state-persistence-debt, test-debt, type-schema-debt
Evidence:
- src/trade_trace/tools/strategy.py:302 reads idempotency_key.
- src/trade_trace/tools/strategy.py:305-340 opens UnitOfWork, updates the strategy row, and emits strategy.updated with the key.
- Unlike strategy.create at src/trade_trace/tools/strategy.py:95-113, strategy.update never calls check_idempotency_replay before mutating.
- Tests cover update mutation/event emission generally but search did not reveal a strategy.update idempotency replay test in tests/integration/test_strategy_tools.py.
Concrete carrying cost:
- Retrying a timed-out strategy.update with the same idempotency_key can perform a second UPDATE, produce a new updated_at timestamp, and attempt/emit another event instead of returning the original result.
- This violates the mental model used by other write tools in ledger/playbook/memory, where idempotency_key is replay-aware.
- Maintenance burden grows because strategy.update looks idempotency-aware at the signature/event layer but is not replay-safe at the mutation layer.
Suggested remediation:
- Add check_idempotency_replay for event_type="strategy.updated" before applying updates.
- Return the original persisted row on replay.
- Add a regression test that repeats strategy.update with the same idempotency_key and asserts one event + stable updated_at.
Duplicate rationale:
- Distinct from existing open MCP/schema/embeddings Beads. This is specific write-idempotency debt in strategy.update.

Candidate DTLMP-004
Title: signal.scan dedupe uses LIKE over JSON text instead of structured related-ref matching
Severity: P3 bounded maintenance debt
Lens: state-persistence-debt, maintenance-hotspot, test-debt
Evidence:
- src/trade_trace/tools/signals.py:143-157 implements _already_signaled with:
  - SELECT id FROM signals WHERE kind = ? AND related_refs_json LIKE ?
  - pattern f'%"{ref_key}":"{ref_id}"%'
- signal.scan currently writes compact JSON via json.dumps(... separators=(",", ":")) in _emit_signal at src/trade_trace/tools/signals.py:88-89, so the self-produced path works.
- The signals table is not guaranteed to contain only this exact compact formatting if future emitters/report.coach/import/replay paths write equivalent JSON with spaces or reordered shapes.
Concrete carrying cost:
- Any future signal producer that serializes related_refs_json differently can bypass dedupe and create duplicate signals for the same logical condition.
- The brittle substring match is hard to extend when signals carry multiple refs or nested metadata.
Suggested remediation:
- Use SQLite json_each/json_extract where available, or load and compare JSON in Python for the bounded result set by kind.
- Add tests with semantically equivalent related_refs_json formatting to ensure dedupe works independent of whitespace/key order.
Duplicate rationale:
- Distinct from current open Beads. Not a deferred signal-kind implementation; this is current dedupe robustness debt.

Rejected / not materialized as candidates:
- import.validate/import.commit stubs:
  - src/trade_trace/tools/imports.py explicitly documents M1 contract stub/P1 implementation and returns UNSUPPORTED_CAPABILITY. Deferred surface appears intentional.
- review.bundle stub:
  - src/trade_trace/tools/review_bundle.py is explicitly a P1 contract/M1 stub. No distinct carrying cost found beyond approved deferral.
- model.import/model.warm/memory.reindex and embeddings.provider non-none:
  - Existing open Beads trade-trace-89x, trade-trace-z6s, trade-trace-heo, trade-trace-izh already cover embeddings/model/reindex implementation path. Avoided duplicate.
- MCP inputSchema / tool.schema gaps:
  - Existing open Bead trade-trace-74b covers auto-derived inputSchema; avoided duplicate.
- playbook “considered”/“not_applicable” mapping to playbook_rule.followed:
  - Initially suspicious, but code/docs/tests align:
    - src/trade_trace/tools/playbook.py:446-449
    - src/trade_trace/tools/playbook.py:612-614
    - docs/architecture/persistence.md:190-192
    - tests/integration/test_playbook_layer.py:231-235
  - Not reported as debt.

Coverage accounting:
- In-scope source files reviewed: 12/12.
- Related integration/contract test areas sampled/reviewed: admin, manual ledger/ledger event emission, memory, memory recall budgets/constants/link, playbook, source attach, strategy, signal scan/schema, review_bundle, event enum coverage, final dogfood verification.
- Lenses applied:
  - type-schema-debt: strategy.update idempotency-key contract mismatch; memory.reflect argument shape drift.
  - state-persistence-debt: memory.reflect two-transaction atomicity; strategy.update retry semantics; signal dedupe persistence matching.
  - maintenance-hotspot: memory.py multi-surface reflect/retain/link paths; signal JSON substring dedupe.
  - test-debt: missing rollback/idempotency/docs-example regression tests.
  - integration-provider-drift: docs/MCP-agent memory.reflect shape drift.
  - docs-contract-drift: README/PRD/memory-layer vs implementation on memory.reflect.
- Open Bead duplicate check performed with bd list --status open --json; no new Beads were created.