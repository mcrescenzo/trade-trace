> Status: **decision document for trade-trace-eijx** (investigation +
> recommendation). No code changes in this doc; the bead's mandate is
> design-only.

# Schema-governed registries: inventory + single-source decision

## Problem

Schema-pinned knowledge (event types, enum values, timestamp columns)
lives in five places today:

| Source                                              | Holds                                                                                  | Purpose                                                                                  |
|-----------------------------------------------------|----------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------|
| `src/trade_trace/storage/policy.py` `OPEN_ENUMS`    | open-enum-extension allowlist                                                          | gates migrations that add new values to documented enums.                                |
| `src/trade_trace/events/semantic_keys.py`            | structural-field + free-text-field registry per event type                             | drives idempotency replay equivalence + secret scanning.                                 |
| `src/trade_trace/exporter.py` `_STATIC_EVENT_TOOL_MAP` | event-type → exporter tool-name mapping                                                | turns event rows into JSONL `{tool, args}` lines.                                        |
| `src/trade_trace/storage/migrations/m*.py` `CHECK (… IN …)` | the storage-level CHECK constraint per enum column                                     | hard-rejects bad rows at the DB layer.                                                   |
| `src/trade_trace/timestamps.py` `TIMESTAMP_API_GOVERNED_COLUMNS` | timestamp columns the boundary validator must normalize                          | gates `to_utc_iso8601` on every API-bound write.                                          |

Adding a new event type / enum value / timestamp column requires
touching multiple files. A drift between them is a contract-drift
bug. But auto-deriving these registries from a single source has a
well-known risk: a new column would be **automatically** governed
under the same rules without an explicit owner sign-off, weakening
the "every governed surface is reviewed" property.

## What's actually duplicated

After walking each source, the overlap is narrow:

- **Event-type enum** (the set of `*.created` / `*.added` /
  `*.scored` etc.): appears in `SEMANTIC_KEYS` keys,
  `_STATIC_EVENT_TOOL_MAP` keys, migration 002's events.event_type
  CHECK, and (after trade-trace-apgt) the import taxonomy
  `_CASCADED_EVENT_TOOLS` / `_DIAGNOSTIC_EVENT_TOOLS` sets +
  `tests/contracts/test_jsonl_replay_taxonomy.py`.
- **Decision-type enum** (13 values from `decision_matrix.py` rows):
  appears in `DECISION_MATRIX` keys + migration 003's decisions.type
  CHECK + `OPEN_ENUMS["decision.type"]`.
- **Source-kind enum** (10 values from migration 003): appears in
  the migration CHECK + the hand-crafted source.add JSON schema
  (added in trade-trace-2ya5) + `OPEN_ENUMS["source.kind"]`.
- **Timestamp columns** (`*_at` everywhere): each governed column
  appears in its migration's column declaration + the
  `TIMESTAMP_API_GOVERNED_COLUMNS` allowlist.

## Choices considered

### A. Single-source the event-type registry only

`SEMANTIC_KEYS` is the largest event-type catalog; treat it as the
canonical list and derive everything else.

- `_STATIC_EVENT_TOOL_MAP` becomes a `dict` keyed on
  `SEMANTIC_KEYS.keys()`; a lint test asserts equality.
- The migration CHECK constraint is canonicalized in
  `OPEN_ENUMS["event.event_type"]`; a lint test asserts the migration
  CHECK matches the OPEN_ENUMS list.
- The import taxonomy sets (`_CASCADED_EVENT_TOOLS`,
  `_DIAGNOSTIC_EVENT_TOOLS`) remain explicit — they classify *policy*,
  not membership — but the existing
  `test_jsonl_replay_taxonomy.py` (trade-trace-apgt) pins the union.

**Cost:** two small lint tests; no production code change.
**Carrying risk:** very low. Every existing audit surface keeps its
explicit form; the lint tests only catch drift.
**Recommendation:** **adopt**. Filed as follow-up bead.

### B. Single-source the decision-type and source-kind enums

Move the canonical enum list to `OPEN_ENUMS` (it's already the
contract location) and have `decision_matrix.DECISION_MATRIX` +
`_SOURCE_ADD_SCHEMA` derive their value-spaces from it.

- `decision_matrix.py`: assert at import time that
  `DECISION_MATRIX.keys() == set(OPEN_ENUMS["decision.type"])`.
- `_SOURCE_ADD_SCHEMA["properties"]["kind"]["enum"]` derived from
  `OPEN_ENUMS["source.kind"]` at module load.

**Cost:** small. The schema-derivation runs once per process; no
runtime overhead.
**Carrying risk:** medium. If `OPEN_ENUMS` is wrong, BOTH the matrix
and the schema are wrong. Today they cross-validate (a typo in the
matrix surfaces as a CHECK violation on the very first write).
**Recommendation:** **DEFER**. The cross-validation is a real safety
property — the cost of removing it isn't repaid by the convenience.

### C. Auto-derive `TIMESTAMP_API_GOVERNED_COLUMNS` from migrations

Walk every migration's column declarations, collect `*_at` columns,
build the governed set automatically.

**Cost:** moderate (the migration files are Python with embedded SQL
strings; parsing them reliably requires either an AST walker or
running the migrations against a fresh DB and reading
`sqlite_master`).
**Carrying risk:** HIGH. Auto-blessing every `*_at` column would
silently include columns that are NOT supposed to flow through the
boundary normalizer (e.g., projection-only columns where the value
is computed, not caller-supplied). The current explicit allowlist is
load-bearing.
**Recommendation:** **REJECT**. This is the case the bead description
explicitly calls out — "automatic derivation could silently bless new
timestamp columns."

### D. Move `_CASCADED_EVENT_TOOLS` / `_DIAGNOSTIC_EVENT_TOOLS` into a registry

The import taxonomy and the docs/architecture/jsonl-replay-taxonomy.md
classify every event type into a bucket. A registry could pin this in
one place.

**Cost:** small.
**Carrying risk:** low — the existing
`test_jsonl_replay_taxonomy.py` already enforces the union; making it
a single-sourced dict would replace the assertion with a lookup.
**Recommendation:** **DEFER**. The current per-file sets read more
naturally for their context (importer code wants the buckets; the
doc wants the prose). The lint test already catches drift.

## Recommendation summary

Adopt only **option A** (single-source the event-type registry via
two small lint tests). Defer B and D as "low value relative to risk";
reject C as actively unsafe.

## Follow-up bead

Filed: implement the two lint tests:

1. `_STATIC_EVENT_TOOL_MAP.keys() == SEMANTIC_KEYS.keys()`.
2. The migration 002 `events.event_type` CHECK enum equals
   `OPEN_ENUMS["event.event_type"]`.

Neither test changes production behavior; both fail loudly when a
new event type lands in one place but not the other. Implementation
is a single test file with two parametrized assertions.
