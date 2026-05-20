# Advisor review — deadcode hunt 2026-05-20

Advisor gate result: materialize a narrowed set.

Safe materialization:
- DC-20260520-001: P3 cleanup task, unused frontend dependencies.
- DC-20260520-002: P3 investigation/owner-confirmation task, not removal, for EventRecord.to_jsonl_line canonical serialization path.
- DC-20260520-003 + DC-20260520-004: merge into one P2 docs-truth bug: stale CLI examples against live help/schema.
- DC-20260520-005: P4 owner-confirmation/investigation task, not removal, for Console trade_detail wiring/removal decision.
- DC-20260520-006: P4 owner-confirmation/investigation task, not removal, for security.keyring.delete_api_key product path.

Keep matrix-only / reject:
- DC-20260520-007: matrix-only needs-more-evidence; public Database method + docstring makes removal speculative.
- DC-20260520-008: keep; explicit retention comment + test/support role + prior resolved clock cleanup.
- DC-20260520-009: keep/product backlog, not deadcode; exported/tested glossary copy looks intentionally staged.
- DC-20260520-010: keep; encode_filter is contract-test support for decode route, summarize_filter is public/planned helper.
- DC-20260520-011: reject/no bead; duplicate-suppressed prior helper theme.

Classification corrections:
- 001, 002, 005, 006 are cleanup/investigation tasks, not bugs.
- 003/004 are legitimate bugs because stale docs produce concrete operator/agent command failure.
- Owner-confirmation items must be worded as “decide wire/deprecate/remove” and acceptance must allow preservation if intentionally public/future-facing.

Pre-mutation requirements from advisor:
- Recheck live HEAD/status and open-Beads/duplicate scan immediately before mutation.
- Save CLI help/probe outputs for docs bug.
- Create final verification gate blocked only by materialized items.
- Run body-integrity readback after Beads writes.
