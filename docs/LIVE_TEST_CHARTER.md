# Phase 5 live-test charter

This charter is the load-bearing scope document for the Phase 5 live test of Trade Trace v0.0.2. It defines what the live test is allowed to prove, which contracts it is validating, and when the pre-live-testing program may be considered ready for closure.

Phase 5 has not run until fresh evidence is captured against a local test journal. This document is not release evidence and does not itself authorize a tag, secrets, network use, or publication.

## Purpose

Phase 5 validates that two or more agent sessions can use the same local Trade Trace journal without silent write loss, malformed adapter/report envelopes, or cross-session memory isolation failures.

The live test is intentionally narrow:

- It validates the shipped v0.0.2 SQLite/WAL single-writer contract.
- It validates retry behavior when concurrent sessions contend for the write lock.
- It validates that evidence from multiple sessions can be recalled and reported from one local journal.
- It does **not** validate a parallel-write architecture.
- Its load-bearing pass/fail bar is the local journal/concurrency/recall contract, not live-network coverage, raw RPC URLs, private keys, or broker/exchange credentials.

Any optional live-network exercise remains governed outside this charter by the Phase 4 provisioning/Gate-7 evidence path, sanitization requirements, and explicit owner/HITL approval. Such evidence may supplement the program only after those gates are satisfied; it does not change the six Phase 5 exit criteria below.

## Source-of-truth references

The live test must be interpreted against these source-of-truth documents:

- [`docs/architecture/operability.md` §3, Multi-Process Concurrency](architecture/operability.md#3-multi-process-concurrency)
- [`docs/architecture/persistence.md` §2, SQLite as Source of Truth](architecture/persistence.md#2-sqlite-as-source-of-truth)
- [`docs/architecture/reports.md` §6A, Target contract: `report.process_analytics`](architecture/reports.md#6a-target-contract-reportprocess_analytics)

Program context: Phase 2 reporting work piggybacks on the existing **trade-trace-mxip** reporting program. This charter only links that reporting context to Phase 5 evidence expectations; it does not implement or broaden reporting.

## v0.0.2 concurrency contract

For v0.0.2, SQLite at `$TRADE_TRACE_HOME/trade-trace.sqlite` is the single source of truth. The database runs in WAL mode. WAL permits concurrent readers, but writers are serialized at the SQLite database-file level.

The MVP single-writer assumption is:

- One writer process at a time per database file, not per table.
- A second writer waits behind SQLite's `busy_timeout`, whose documented default is **5 seconds**.
- If the write lock is not acquired within that timeout, the failing write returns `STORAGE_ERROR` with:
  - `details.reason = "single_writer_lock"`
  - `details.held_by_pid` when discoverable
  - `details.retry_after_seconds = 2` as the initial recommended wait
- A blocked write is retried once inside the in-process dispatch harness before the envelope is surfaced to an MCP/CLI caller. The retry reuses the same `request_id`; dispatch trace rows record `attempt` and, for retries, `retry_of=<request_id>` so reviewers can pair lock-error -> success under one lineage.
- `single_writer_lock` is a transient, recoverable failure envelope, not data loss.
- Reads are never blocked by writers and never fail with `single_writer_lock`.
- Multi-writer coordination, write fan-out, connection-pool retry/backoff, or migration to a different engine are deferred P1+ work.

The MVP commitment is honest and recoverable single-writer behavior: a second writer never silently loses a write.

## What "multi-agent" means for Phase 5

For this live test, "multi-agent" means multiple logical agent sessions share the same local Trade Trace journal and may attempt overlapping tool calls. Those sessions still serialize at the SQLite layer.

The expected contention behavior is:

1. One writer obtains the SQLite write lock.
2. A secondary writer that cannot acquire the lock within the documented timeout cleanly receives `STORAGE_ERROR` with `details.reason = "single_writer_lock"`.
3. The secondary writer follows `details.retry_after_seconds` and recovers within one documented retry.
4. Both sessions' durable writes are visible after recovery.

This is **not** a parallel-write demonstration. Treating simultaneous successful writes as the criterion would contradict the v0.0.2 architecture. Success is clean lock reporting plus one-retry recovery, not proof that two writers committed at the same instant.

`memory.recall` participates in this contract at the SQLite layer because `memory.recall` appends `memory_recall_events`. A recall call can therefore act as a short writer and can receive the same `single_writer_lock` envelope when another process holds the write lock. The live test must not classify that as a read-path failure if it recovers under the documented retry rule.

Side-effect inspection for report tools: `report.coach` opens the journal read-only (`file:...?mode=ro`) through its handler stack and does not take the write lock. `report.bootstrap` / `agent.bootstrap` currently uses `open_db_for_args`, which can open a normal journal connection while composing the packet; it is therefore covered by the same dispatch-level retry wrapper if SQLite reports `single_writer_lock`.

## Phase 5 quantitative exit criteria

The Phase 5 exit criteria are exactly:

1. Every single_writer_lock emission recovers within ONE documented retry.
2. Zero non-single_writer_lock STORAGE_ERROR.
3. Zero ADAPTER_PROTOCOL_ERROR.
4. Idempotency keys uncollided across concurrent sessions.
5. recall.search returns cross-session results.
6. Final tt journal status reports a clean state.

If any criterion fails, Phase 5 has not passed.

## Evidence and sanitization rules

Evidence must be enough for a reviewer to determine whether each exit criterion passed without exposing secrets or overstating runtime behavior.

Record at minimum:

- The Trade Trace commit/SHA under test.
- The isolated `$TRADE_TRACE_HOME` path pattern used for the test, without local secrets.
- The agent/session identifiers used to distinguish concurrent sessions.
- The exact write and recall/report commands or MCP tool calls exercised.
- Each `single_writer_lock` envelope observed, including `details.reason`, `details.retry_after_seconds`, and whether `details.held_by_pid` was discoverable.
- The retry attempt showing recovery within one documented retry.
- Evidence that idempotency keys were unique across concurrent sessions.
- Evidence that `recall.search` returned results written by another session.
- Final `tt journal status` output showing a clean state.

Do not record raw RPC URLs, bearer tokens, private keys, wallet seeds, exchange credentials, broker credentials, or local credential file contents. Optional adapter testing remains opt-in and must use sanitized evidence only.

## Failure handling and stop rule

Stop the live test and file follow-up beads if any of these occur:

- A `single_writer_lock` emission does not recover within one documented retry.
- Any `STORAGE_ERROR` has a `details.reason` other than `single_writer_lock`.
- Any `ADAPTER_PROTOCOL_ERROR` appears.
- Idempotency keys collide across concurrent sessions.
- `recall.search` cannot return cross-session results after the writes commit.
- Final `tt journal status` does not report a clean state.

Do not close the pre-live-testing program after a failed criterion. Capture the sanitized evidence, file follow-up beads for the failure, and leave release/live-test closure to the controller review process.
