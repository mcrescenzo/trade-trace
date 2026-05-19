> Status: **decision document for trade-trace-gkt3**. No code or test
> changes; the bead's mandate is design-only.

# Semantic-key event policy

## Problem

`trade_trace.events.semantic_keys.SEMANTIC_KEYS` declares the
structural/free-text shape of every event type. Without a written
policy, a new write surface can't tell whether to:

- register a semantic key (and what structural vs free-text fields to
  enumerate),
- emit a fresh event type at all,
- skip the registry entirely (rare — only for cascaded edge events).

The lane review for trade-trace-gkt3 classified this as a contract
seam: "implementation tasks will either overfit tests or create
inconsistent policy."

## Policy

### Rule 1: every retryable write tool emits at least one event with a semantic key

Tools registered with `is_write=True` MUST emit at least one event
whose type appears in `SEMANTIC_KEYS`. The replay-equivalence check
(`payloads_equivalent` per persistence.md §5.2.1) relies on the
semantic-key registry to decide which payload fields force a conflict
versus which are tolerated as free-text differences. A write tool
without a semantic key would either:

- pass replay even when the structural payload changed (data
  corruption), or
- raise IDEMPOTENCY_CONFLICT on every free-text rephrasing (agent
  friction).

Both are unacceptable.

**Enforcement:** `tests/contracts/test_event_enum_coverage.py` walks
the default registry and asserts every `is_write` tool's primary
event type appears in `SEMANTIC_KEYS`. The
`test_write_tools_have_schemas.py` regression
(trade-trace-3i33) ensures every write has an `example_minimal`; the
semantic-key test ensures the corresponding event type is also
registered.

### Rule 2: cascade events INSIDE a tool's transaction do not need their own semantic key

Events emitted as a side effect of a parent tool (e.g.,
`edge.created` from `memory.reflect`, `forecast.scored` from
`outcome.add`) inherit the parent's idempotency_key and replay
discipline. Their payload is fully determined by the parent's
structural fields; an independent semantic key would be redundant.

These event types ARE in `SEMANTIC_KEYS` today (for completeness on
the JSONL replay surface), but their `structural_fields` exist to
support the JSONL importer's bucket-B / bucket-D classification
(per docs/architecture/jsonl-replay-taxonomy.md), not for direct
write-tool replay.

### Rule 3: free-text fields are an explicit choice, not a default

`SemanticKeySpec.free_text_fields` declares the columns that
`payloads_equivalent` should ignore when comparing replay vs original.
Adding a column to `free_text_fields` is a deliberate decision: it
means "agents may rephrase this between attempts; the replay still
matches." Adding too many free-text fields hides real divergence;
adding too few causes false-positive conflicts.

**Default:** when in doubt, treat a field as structural. Promotion to
free-text requires a written reason in the bead.

### Rule 4: enum-coverage tests catch silent additions

`tests/contracts/test_event_enum_coverage.py` enforces that every
write-tool event_type appears in `SEMANTIC_KEYS`. The new
`tests/contracts/test_event_type_registry_alignment.py` lints
(trade-trace-yjvs) catch drift between SEMANTIC_KEYS, the exporter
tool map, and the migration enum.

Together these three tests cover the "did we forget to register the
event?" question without requiring an external owner sign-off.

## Validation

A new event type lands in the same PR as:

1. A `SemanticKeySpec` entry naming structural + free-text fields.
2. An emitter call site (in a write tool's `emit_event(...)`).
3. The corresponding write tool's `example_minimal` if it's a
   user-callable surface (per trade-trace-3i33).
4. If the event has a write tool, an entry in
   `exporter._STATIC_EVENT_TOOL_MAP`.

The existing tests
(`test_event_enum_coverage.py`,
`test_event_type_registry_alignment.py`,
`test_write_tools_have_schemas.py`) catch any of the four missing in
isolation; the PR's author still owns naming and free-text field
choices.

## What this doc explicitly does NOT decide

- It does not rename existing event types or rewrite event storage.
- It does not create broad replay or migration work; bucket
  classifications live in `jsonl-replay-taxonomy.md` (trade-trace-dew2)
  and the per-tool semantic specs.
- It does not change idempotency contracts (trade-trace-cpz2 is the
  surface for that).

If a future write surface needs additional invariants beyond the four
above (e.g., per-row append-only triggers, a new edge family), file a
separate design bead — those are extensions to this policy, not
substitutes for it.
