# memory.recall decomposition investigation (trade-trace-y0b2)

Scope: investigation only; no production behavior changes. Primary code audited: `src/trade_trace/tools/memory.py` `_memory_recall` and existing ranking helpers.

## Current behavior phases

### 1. Parse/options
- Requires `query` via `require(args, "query")`.
- Parses `k` as `int(args.get("k", 10))`; validates inclusive `[1, 100]`.
- Budget/provenance knobs:
  - `max_chars`: optional; when present must be an `int >= 1`.
  - `compact`: defaults `False`.
  - `include_body`: defaults `True`.
  - `include_provenance`: defaults `True`.
  - `min_confidence`: optional; when present must be numeric in `[0.0, 1.0]`.
- Scope/ranking knobs:
  - `node_types`: optional non-empty list; entries must be in `NODE_TYPES`; applied before ranking.
  - `mode`: defaults `fused`; allowed values are `fused` and `per_strategy`.
  - `as_of`: normalized by `normalize_timestamp`.
  - `strategies`: defaults to `["bm25", "temporal", "graph"]`; must be a non-empty list drawn from `{bm25, temporal, graph, semantic}`.
  - `context`: defaults `{}`.
- `common_metadata(args)` is read for recall-event segmentation fields.

### 2. Ranking orchestration
- Opens DB, determines embeddings provider with `_embeddings_provider`.
- If provider is not `none`, automatically appends `semantic` to requested strategies unless already requested.
- Loads in-scope nodes with `_load_in_scope_nodes(conn, as_of=as_of)`; absent `as_of` uses current `now_iso()`.
- Applies `node_types` before any strategy runs.
- Runs enabled helpers:
  - `_bm25_rank(conn, query, in_scope_rows)`; FTS5 `MATCH` ordered by `bm25`, fallback to LIKE on malformed MATCH.
  - `_temporal_rank(in_scope_rows, as_of=as_of)`; rank by absolute recency delta, id tie-break.
  - `_graph_rank(conn, context=context, in_scope_rows=in_scope_rows)`; context-aware graph boost, strategy context special-cased; no context degenerates to id order.
  - `_semantic_rank(conn, query, provider, in_scope_rows)` only if requested and provider is not `none`; included in `rankings` only when non-empty.
- Fuses rankings with `_rrf_combine`, preserving per-strategy 1-indexed rank provenance.
- Applies importance boost `1.0 + (importance - 5) * IMPORTANCE_BOOST_SLOPE` and supersession discount `SUPERSESSION_DISCOUNT` for ids returned by `_superseded_node_ids`.
- Sorts final scored candidates by `(-score, node_id)`, then slices `top = scored[:k]`.

### 3. Budget/provenance formatting
- Applies `min_confidence` after top-k slicing, not before ranking or before k. Nodes below threshold, or with null confidence, are dropped.
- Builds emitted items from filtered candidates in score order.
- Body handling order is: fetch body -> optionally compact to max 120 chars (`body[:117] + "..."`) -> test aggregate `max_chars` -> break on first overflow -> increment `chars_used`.
- `max_chars` measures body characters after compaction, regardless of `include_body`; if one candidate would overflow, all remaining candidates are dropped.
- Item base fields: `id`, `node_type`, `title`, `importance`, rounded `score`, and `source_refs` from `_source_refs_for`.
- `body` is omitted when `include_body=False`.
- `strategy_provenance` is omitted when `include_provenance=False`.

### 4. Recall-event/stats writes
- Always logs one `memory_recall_events` row per successful recall, even if no items are returned.
- `strategies_used` stored in the event is `json.dumps(list(rankings.keys()), sort_keys=True)`, i.e. only strategies that produced a ranking key, not necessarily every requested strategy.
- `node_ids_returned` stores emitted item ids after top-k, min_confidence, compaction/max_chars break, and output shaping.
- Event and eager `memory_node_stats` updates occur inside an explicit BEGIN/COMMIT transaction.
- For each returned node id, `memory_node_stats` is inserted or incremented and `last_recalled_at` updated to the recall event timestamp.

### 5. Response/meta_hints construction
- Response fields: `recall_id`, `query`, `strategies_used` sorted from `rankings.keys()`, `k`, `as_of`, `mode`, `items`, `total_in_scope`.
- In `mode='per_strategy'`, adds `per_strategy` dict of raw per-strategy node-id lists, each capped to `k`. These lists are not filtered by `min_confidence` or `max_chars`.
- Meta hints:
  - `generated_at = created_at`
  - `package_version = __version__`
  - `retrieval_strategy_metadata` with sorted `strategies_used`, `k`, `max_chars`, `k_rrf`, `importance_boost_slope`, and `supersession_discount`.

## Behavior-preservation constraints

- Preserve parse/validation messages, error codes, and detail fields for `k`, `max_chars`, `min_confidence`, `node_types`, `mode`, and `strategies` unless explicitly versioned.
- Preserve `min_confidence` placement after final score sort and top-k slicing. Moving it earlier would allow lower-ranked high-confidence nodes into the result set and change current semantics.
- Preserve `max_chars` placement after optional compaction and before item append; preserve first-overflow break semantics rather than skipping oversized items.
- Preserve that `max_chars` is computed from body length even when `include_body=False`.
- Preserve semantic auto-inclusion when embeddings provider is not `none`, and preserve no-network default behavior when provider is `none`.
- Preserve event logging on every successful recall and the event/stats transaction boundary.
- Preserve that event `node_ids_returned` and `memory_node_stats` count only emitted items after min_confidence/max_chars filters.
- Preserve response/meta strategy surfaces as currently defined: response/meta `strategies_used` are sorted `rankings.keys()`, while event serialization uses `list(rankings.keys())`.
- Preserve `per_strategy` raw-list behavior: capped by k only, not budget/confidence filtered.
- Preserve existing ranking constants and helper algorithms (`K_RRF`, `IMPORTANCE_BOOST_SLOPE`, `SUPERSESSION_DISCOUNT`, RRF provenance, tie-breakers).

## Existing and missing characterization tests

Existing coverage observed:
- `tests/integration/test_memory_recall_budgets.py`
  - k limiting and out-of-range validation.
  - aggregate `max_chars <= cap`.
  - `compact` body truncation.
  - `include_body=False` and `include_provenance=False` field omission.
  - `min_confidence` threshold filtering and out-of-range validation.
  - `node_types` filtering and invalid value validation.
  - `mode='per_strategy'` response shape and fused default omission.
- `tests/integration/test_memory_retrieval_constants.py`
  - pinned ranking constants, RRF manual scores, RRF provenance ranks, supersession multiplier.
- `tests/integration/test_memory_layer.py`
  - recall item fields/provenance/source_refs and default strategies.
  - recall event append plus eager `memory_node_stats` updates.
  - stats rebuild equivalence from recall events.
  - as_of filtering.
- `tests/integration/test_projection_rebuild.py`
  - memory_node_stats rebuild no-op/diagnostics and corrupt recall event handling.
- `tests/integration/test_reproducibility_replay.py`
  - deterministic per-strategy and fused recall envelopes under frozen clock.
  - recall meta `retrieval_strategy_metadata` fields.
- Additional semantic/no-network coverage exists in embeddings/security tests, including semantic strategy inclusion when enabled and offline recall when sockets are blocked.

Missing or weak characterization:
- No direct test pins `min_confidence` after top-k slicing. A refactor could move confidence filtering before k and still satisfy current simple threshold tests while changing which nodes are returned.
- No direct test pins `max_chars` first-overflow break rather than skip-and-continue.
- No direct test pins `compact` before `max_chars` ordering.
- No direct test pins `max_chars` still applies when `include_body=False`.
- No direct test pins `per_strategy` lists being unfiltered by `min_confidence`/`max_chars`.
- No direct test pins event `node_ids_returned` and `memory_node_stats` reflecting post-budget emitted items only.
- Existing semantic auto-inclusion/no-network tests are outside the requested validation command; downstream refactor should include them or add focused unit characterization if touching strategy selection.

## Decision

Implement helper split in a downstream bead, after adding focused characterization for the missing ordering interactions above. Rationale: `_memory_recall` currently combines validation, provider/strategy selection, ranking orchestration, post-ranking filters, response shaping, side-effect writes, and meta construction in one large function. Existing ranking helpers are already separated and should be reused as-is. A helper split can reduce risk and improve maintainability if it is pure extraction with unchanged call order and side effects isolated behind a clearly named write helper. Do not change ranking algorithms/constants or provider behavior as part of that split.

## Proposed downstream implementation scope

Suggested bead title: `Refactor memory.recall into behavior-preserving parse/rank/shape/write helpers`

Acceptance criteria:
- Add characterization tests for:
  1. `min_confidence` is applied after top-k selection.
  2. `compact` is applied before `max_chars`.
  3. `max_chars` stops at first overflow and does not skip to later smaller items.
  4. `max_chars` applies even with `include_body=False`.
  5. `per_strategy` lists remain capped raw strategy rankings and are not filtered by confidence/budget.
  6. recall events/stats count only emitted item ids after confidence/budget filters.
- Extract helpers without behavior changes, for example:
  - `_parse_recall_options(args) -> RecallOptions`
  - `_build_recall_rankings(conn, options, in_scope_rows, provider) -> rankings`
  - `_score_ranked_nodes(conn, rankings, in_scope_rows) -> scored`
  - `_shape_recall_items(conn, scored_top, in_scope_rows, options) -> (items, chars_used)`
  - `_write_recall_event_and_stats(conn, ..., items, rankings, options, ctx, seg) -> (recall_id, created_at)`
  - `_build_recall_response(...); _set_recall_meta_hints(...)`
- Keep existing ranking helper functions and constants unchanged.
- Keep DB transaction scope for event/stats writes unchanged.
- No production semantic/no-network default changes.

Exact validation commands:
- `./.venv/bin/python -m pytest tests/integration/test_memory_recall_budgets.py tests/integration/test_memory_retrieval_constants.py tests/integration/test_memory_layer.py tests/integration/test_projection_rebuild.py tests/integration/test_reproducibility_replay.py -q`
- Recommended additional commands for the downstream refactor if strategy selection/provider paths are touched:
  - `./.venv/bin/python -m pytest tests/security/test_embeddings_off_by_default.py tests/security/test_no_network_default.py tests/integration/test_embeddings_sqlite_vec_substrate.py tests/security/test_embeddings_api_keyring.py -q`

