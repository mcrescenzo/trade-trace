> Status: **decision document for trade-trace-lsi5**
>
> Investigation-only record; no production behavior changes.

# review.bundle decomposition investigation (trade-trace-lsi5)

Date: 2026-05-20
Scope: investigation only; no production behavior changes.

## Current pipeline phases

`src/trade_trace/tools/review_bundle.py` currently has helper sections plus one orchestration handler:

1. Input parsing and filter support validation
   - `ReviewBundleInput.model_validate(args)` rejects extra input and bounds record/example limits.
   - `ReportFilter.model_validate(parsed.filter)` validates filter shape.
   - `enforce_supported_filter(..., report="review.bundle")` allows only the supported subset documented by tests: `actors.actor_id`, `instrument.venue_id`, `strategy.strategy_id`, `time_window.decision_at_gte`, `time_window.decision_at_lt`.
   - `applied_filter_view(...)` produces the normalized filter stored in the bundle.

2. Decision selection
   - `_select_decision_ids` applies the supported filter subset.
   - Rows are ordered by `d.created_at ASC, d.id ASC` and capped by `max_records`.

3. Selected row fetching and related record gathering
   - `_decision_rows` fetches selected decisions ordered by `created_at ASC, id ASC`.
   - `_related_record_rows` derives sorted unique `instrument_id`, `thesis_id`, and `forecast_id` sets, then fetches:
     - theses by id ordered by id via `_fetch_by_ids`;
     - forecasts by id ordered by id via `_fetch_by_ids`;
     - outcomes by instrument ordered by `resolved_at ASC, id ASC`;
     - positions by instrument ordered by `id ASC`.
   - The `selected` mapping is emitted in this insertion order: `decisions`, `theses`, `forecasts`, `outcomes`, `positions`.

4. Optional attached record gathering
   - `target_kinds` is assembled in insertion order: `decision`, `thesis`, `forecast`, `outcome`.
   - If `include_sources`, `_gather_attached_sources` walks `edges`, deduplicates source ids with `sorted(...)`, fetches sources ordered by id, and applies source redaction rules.
   - If `include_reflections`, `_gather_reflections` fetches attached reflection memory nodes ordered by `m.created_at ASC, m.id ASC` and deduplicates by first occurrence while preserving that order.
   - If `include_playbook`, `_gather_playbook_versions` fetches distinct versions ordered by `pv.created_at ASC, pv.id ASC`.

5. Report summary embedding
   - The handler calls `report_calibration(conn, raw_filter=filter_view)` and stores only `calibration["summary"]` under `report_summaries["calibration"]`.
   - On any exception from calibration summary generation, the bundle continues and substitutes `{"sample_size": 0, "sample_warning": None}`.

6. Caveats and defense-in-depth redaction sweep
   - Caveats are appended after DB work in deterministic order: calibration `sample_warning`, sensitive-source omission count, redacted-source inclusion count, then secret-shaped replacement count.
   - `_redact_strings_in_place` recursively walks selected records, sources, reflections, and playbook versions in that order, preserving dict key order and list order while replacing secret-shaped substrings via `redact_for_log`.

7. Top-level bundle construction and hash/meta
   - The top-level `data` mapping is built in this presentation order: `filter`, `selected`, `sources`, `reflections`, `playbook_versions`, `report_summaries`, `caveats`, `suggested_prompts`, `contract_version`, then `bundle_hash`.
   - `_suggested_prompts` returns either an empty list (no decisions) or three static prompts in fixed order.
   - `_bundle_hash` hashes `data` excluding `bundle_hash`.
   - The handler writes `bundle_hash` and `contract_version` to `ctx.meta_hints`.

## Deterministic ordering and hash behavior

Observed deterministic ordering inputs:

- SQL result ordering is explicit for selected decisions, decision rows, outcomes, positions, reflections, and playbook versions.
- Source ids and related id sets are sorted before fetch/dedup where the query itself might otherwise expose unordered set behavior.
- Dict construction order is stable for human-visible output, but the hash does not rely on insertion order.
- `_canonical_json` uses `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)`, so object key ordering inside the digest is canonicalized recursively.
- `_bundle_hash` removes only the top-level `bundle_hash` field before hashing.

Existing hash tests before this investigation:

- `tests/integration/test_review_bundle_contract.py::test_hash_stable_across_identical_calls` proves identical DB/input calls produce the same hash.
- `tests/integration/test_review_bundle_contract.py::test_hash_changes_when_db_state_changes` proves new selected data changes the hash.
- `tests/integration/test_review_bundle_contract.py::test_hash_changes_when_max_records_excludes_a_decision` proves selection-bound differences affect the hash.
- `tests/integration/test_review_bundle_contract.py::test_cli_review_bundle_parity_with_mcp` proves CLI and MCP agree on hash for the same input.

New regression added by this investigation:

- `tests/integration/test_review_bundle_contract.py::test_bundle_hash_uses_canonical_key_order_not_insertion_order` pins the current top-level presentation key order and proves `_bundle_hash` returns the emitted hash even when the same payload body is rebuilt in reverse insertion order. This is a narrow hash-stability proof for future decomposition work and does not change production behavior.

## Redaction and caveat behavior

Source redaction rules in `_gather_attached_sources`:

- `redaction_status='sensitive'`: omit the entire source row from `sources`; increment omitted-sensitive count.
- `redaction_status='redacted'`: include the source but set content-bearing fields to `None` when present: `body`, `extracted_text`, `excerpt`, `summary`, `note`; increment redacted count.
- missing/falsey status is treated as `none`; row passes through.

Defense-in-depth secret-pattern redaction:

- After data gathering, `_redact_strings_in_place` recursively processes strings in `selected`, `sources`, `reflections`, and `playbook_versions`.
- Each changed string increments a replacement counter.
- If replacements occurred, a final caveat is appended: `<n> secret-shaped value(s) replaced with REDACTED-* tokens (security.md §8)`.

Existing tests covering this surface:

- `tests/integration/test_review_bundle_contract.py::test_sensitive_source_omitted_with_caveat`
- `tests/integration/test_review_bundle_contract.py::test_redacted_source_strips_content_but_keeps_metadata`
- `tests/integration/test_review_bundle_contract.py::test_none_redaction_source_passes_through`
- `tests/security/test_redacted_exports.py` validates export-vs-review-bundle redaction boundaries.
- `tests/security/test_secret_pattern_writes.py` validates write-time secret scanning and `redact_for_log` behavior used by the bundle sweep.

## Partial report-summary failure behavior

`report_calibration` is treated as best-effort inside `review.bundle`. Any exception is swallowed by the handler and replaced with `{"sample_size": 0, "sample_warning": None}` for `report_summaries["calibration"]`. The bundle still proceeds to caveat construction, redaction, suggested prompts, hash construction, and meta hints.

No production change was made. I did not add a monkeypatched failure test because the Bead specifically asked for hash-stability proof if existing coverage was insufficient; the current partial-failure behavior is directly visible in the handler and should be included in downstream validation if decomposition is implemented.

## Decision

Recommend: implement decomposition in a downstream Bead, but only as behavior-preserving internal refactor guarded by the current contract tests plus explicit hash-stability validation.

Rationale:

- The handler mixes validation, selection, gathering, redaction, caveat construction, report summaries, suggested prompts, and hash/meta assembly.
- Most phases already have helper boundaries, so decomposition can reduce orchestration complexity without changing schema or semantics.
- Hash stability is the main risk: even harmless-looking movement can alter list order, top-level key presentation order, caveat order, or hash body contents. The new key-order/hash regression narrows that risk.

## Recommended downstream task shape

Proposed title: Decompose `review.bundle` orchestration without changing bundle schema/hash

Proposed scope:

- Extract behavior-preserving pure helpers for phases such as parsed filter preparation, selected/target context gathering, optional attachments, report summaries, caveat construction, redaction sweep, and final bundle/hash/meta assembly.
- Keep public output schema, top-level key order, nested selected key order, caveat order, redaction behavior, partial calibration failure behavior, and hash inputs unchanged.
- Do not change SQL ordering, filtering support, include flags, or suggested prompt text/order.

Required validation for that downstream task:

- `./.venv/bin/python -m pytest tests/integration/test_review_bundle_contract.py tests/security/test_redacted_exports.py tests/security/test_secret_pattern_writes.py -q`
- Include an explicit before/after fixture or regression proving `bundle_hash` and top-level key order remain unchanged for representative populated bundle data.
- `git diff --check`

## Validation commands/results for this investigation

- Focused new regression: `./.venv/bin/python -m pytest tests/integration/test_review_bundle_contract.py::test_bundle_hash_uses_canonical_key_order_not_insertion_order -q` — passed.
- Required suite: `./.venv/bin/python -m pytest tests/integration/test_review_bundle_contract.py tests/security/test_redacted_exports.py tests/security/test_secret_pattern_writes.py -q` — passed.
- Whitespace: `git diff --check` — passed.
