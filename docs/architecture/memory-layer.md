# Memory Layer — Architecture Note

> Status: **shipped**. The M3 memory graph (retain/reflect/link/recall + bi-temporal validity + RRF) is live. Semantic embeddings remain opt-in per §8.

**Date:** 2026-05-18
**Status:** Refined draft v3 (supersedes v2; PRD §3.2/§4.1 alignment now committed)
**Parent:** [`../../PRD.md`](../PRD.md) §5 & §4.2

This note details the memory layer's node taxonomy, edge semantics, retrieval strategies, embedding policy, and confidence model. The PRD owns the schema rows; this doc owns the semantic intent. As of v3, the PRD schema and this doc are aligned on the 3-node-type taxonomy, the 7-edge-type taxonomy, the separate `memory_node_embeddings` table, the `signals` table, and the `memory_recall_events` event log.

## 1. Goals

The memory layer turns a passive trade ledger into an active knowledge graph the agent can think with. Three capabilities:

1. **Recall**: when an agent forms a new thesis on instrument X, surface relevant past observations, reflections, and playbook rules.
2. **Reflect**: when an outcome resolves or a coach signal fires, store the agent's synthesis as a typed memory node linked to the ledger rows that motivated it.
3. **Evolve**: when reflections accumulate, allow the agent to codify them as versioned playbook rules whose adherence and override outcomes are tracked.

It is **not** a generic agent memory framework. The schema is trading-shaped: every node can link to ledger rows; confidence decays; recall can scope to instrument / venue / asset class / market type.

## 2. Design principles

1. **One SQLite file is the entire product state.** Ledger, memory, edges, FTS index, and (when enabled) vector index live in one DB. `cp trade-trace.sqlite` is a complete backup. Load-bearing for the air-gappable install promise. Backup/restore caveats (open WAL, in-flight outbox drain) covered in [`operability.md`](operability.md) §5.
2. **Zero-config first run, no surprise network.** `pip install trade-trace && tt journal init && trade-trace-mcp` works without flags or API keys. Vectors are **off** by MVP default; `journal.init` makes zero outbound calls. The SEMANTIC strategy is opt-in via explicit config (`tt journal config_set --key embeddings.provider --value local --idempotency-key <uuid> --confirm` or `tt model import --src <path-to-bge-small> --idempotency-key <uuid> --confirm`); this preserves the absolute air-gap promise from VISION §safety on first run.
3. **Optional capabilities, never required.** Vectors, API embedding providers, graph traversal, edge-density confidence — all opt-in or deferred. The MVP product is fully functional without them.
4. **Trading-specific edges, generic everything else.** Custom typed edges from memory to ledger rows are the moat. Retrieval primitives (BM25, vector, RRF) are standard.
5. **System-emitted signals are not memory.** They live in a separate table because they have a different author (the system) and a different lifecycle (time-bounded notifications, not durable knowledge the agent authored).
6. **Bi-temporal beliefs.** Every belief-shaped node (observation, reflection, rule) records both transaction time (`created_at`, `invalidated_at`) and world time (`valid_from`, `valid_to`) so "what did the agent believe on day X" is unambiguously answerable. Ledger transaction-time semantics are preserved by append-only + supersedes; world-time is added on top. See [`operability.md`](operability.md) §2 for the as-of query pattern.

## 3. Memory node taxonomy

Three `node_type` values cover MVP. The taxonomy maps onto the cognitive-science distinctions used by Mem0 and the generative-agents literature: `observation` ≈ episodic, `reflection` ≈ semantic (lessons synthesized from episodes), `playbook_rule` ≈ procedural (the agent's own how-to playbook).

Each type has a default `decay_rate_per_day`. `decay_rate_per_day` is a writable field so the agent can override per node (e.g., `0.0` for a belief it considers durable, faster decay for a low-confidence guess).

Every node also carries `importance ∈ [1, 10]` set by the writer at create time (default `5`). Importance is a fixed write-time judgement that does not decay; it feeds recall ranking (boosts higher-importance nodes proportionally) and the future two-tier reflection threshold (P1+). It is distinct from `confidence_base` (the writer's belief in the claim) and from retrieval-time `effective_confidence` (decay + supersession; see §6).

Every node carries bi-temporal fields:

- `valid_from` (default = `created_at`) — when the agent claims the belief began holding in the world.
- `valid_to` (nullable, default = `NULL`) — when the agent claims the belief stopped holding. `NULL` means "ongoing until invalidated or superseded."
- `invalidated_at` (transaction time of invalidation) and `invalidated_by` (FK to superseding node) — set when a newer node explicitly invalidates this one (typically via a `supersedes` edge written in the same transaction).

The retrieval and confidence model below combines bi-temporal validity, transaction-time supersession, and decay. An `as_of` query (see [`operability.md`](operability.md) §2) restricts to rows whose `valid_from <= as_of < coalesce(valid_to, +∞)` and whose `invalidated_at` is `NULL` or `> as_of`.

### 3.1 `observation`

A point-in-time record of something the agent noticed about a market, instrument, or pattern. Episodic.

- **Examples**: "Polymarket markets with < $5K ADV around resolution dates show 40bps wider spreads"; "NVDA gapped up 8% post-earnings and faded 4% within the first hour for the third quarter in a row".
- **Required meta**: at least one scoping field — `instrument_id`, `venue_id`, `asset_class`, or `pattern_kind`.
- **Default decay**: `0.003` per day (half-life ~230 days). Episodic, ages slowly.
- **Typical importance**: `4`–`6`. An observation about a single instrument tends to be lower-importance; a pattern observation across many instruments warrants `7`+.
- **Typical `valid_to`**: `NULL`. Observations rarely "stop being true"; they fade via decay. Set `valid_to` explicitly only when the underlying market regime is known to have ended.

### 3.2 `reflection`

A retrospective synthesis written by the agent after a decision, position, period, or coach-signal event. Subjective.

- **Examples**: "I overweighted the spread compression thesis here and ignored that the liquidity profile didn't match my prior pattern"; "Three skips this week were all driven by `liquidity-ignored` worry that turned out to be correct — keep doing this".
- **Required meta**: `target_kind` and `target_id` for row-backed targets, or explicit scope metadata (`period`, `tag`) for non-row targets. Optional: `mistake_tags`, `strength_tags`.
- **Default decay**: `0.002` per day (half-life ~350 days).
- **Typical importance**: `5`–`8`. Reflections that change the agent's behavior next time warrant `8`+; one-off observations stay near the default.
- **Durable beliefs** (e.g., "thin-liquidity prediction markets near resolution are systematically mispriced") can set `decay_rate_per_day` to `0.0005` or lower to express slow-fading belief. There is no separate `semantic_claim` type; a reflection with slow decay plays that role. The agent decides at write time.

#### 3.2.1 Policy-candidate quarantine metadata (G1)

Reflections may optionally carry `metadata_json.policy_candidate` (legacy rows:
`meta_json.policy_candidate`) to make the reflection-to-policy lifecycle
explicit while preserving the separation between subjective memory and durable
playbook policy. This is metadata on `reflection` nodes only; it is not a new
durable table and it never creates, updates, or deletes playbook versions/rules.

Allowed lifecycle statuses are exactly:

- `raw_reflection`
- `candidate_policy`
- `quarantined`
- `needs_more_evidence`
- `rejected`
- `promoted_to_playbook`
- `superseded`

For any status other than `raw_reflection`, metadata must include:

- `candidate_statement`: process-only prose describing the possible policy/playbook implication;
- `scope`: explicit applicability scope. Strategy applicability must be explicit via `strategy_id`, `strategy_ids`, or `strategy_scope` (for example `none` or `global_candidate`) so strategy-linked reflections do not silently become global;
- `evidence`: for `candidate_policy`, `quarantined`, `needs_more_evidence`, and `promoted_to_playbook`, an object that can include reflection IDs, supporting/contradicting case counts, caveats, bundle IDs, recall/source/adherence references, and low-N warnings. Missing evidence is represented as caveats/needs-more-evidence metadata, not by omitting the evidence object.

Additional audit fields are required for terminal/transition states: `rejection_reason` for `rejected`, `superseded_by` for `superseded`, and `playbook_version_id` for `promoted_to_playbook`. `promoted_to_playbook` means a separate explicit playbook/process write has already happened or is being cited; setting this metadata by itself must not mutate the playbook.

Transitions are append-only. To change lifecycle state, write a successor reflection (or another memory node where appropriate) with new metadata and link it with `memory.link` (`supersedes`, `derived_from`, `supports`, or `contradicts`) rather than updating the original `memory_nodes` row.

### 3.3 `playbook_rule`

A codified procedural rule belonging to a specific `playbook_version`.

- **Examples**: "Do not enter prediction-market positions when spread > 8% of expected edge"; "Require 2x base liquidity for any entry within 7 days of resolution".
- **Required meta**: `playbook_version_id` and `rule_meta` (`trigger_kind`, `applicable_decision_types`, optional `applicable_asset_classes`).
- **Body** holds the free-text rule the agent reads when reasoning. MVP rules are advisory; automatic violation detection requires explicit predicate fields added later.
- **Machine-checkable predicate metadata** may be stored under `metadata_json.predicate` (legacy rows: `meta_json.predicate`) for rules that fit the closed-set evaluator in `trade_trace.playbook_predicates`. This is a library substrate only, not a registered report/tool in this bead. Supported families are intentionally narrow (`field_exists`, `field_equals`, `decision_type_in`, `link_exists`, `source_count_at_least`, `timestamp_present`, `forecast_resolution_rule_present`) and evaluate only recorded local fields/links. Missing predicate metadata leaves a rule self-reported-only; rule body/prose is never parsed as executable logic.
- **Default decay**: `0.0`. Rules are superseded by new versions, not faded.
- **Typical importance**: `7`–`10`. Procedural rules are high-leverage by construction; default importance for new rules is `8`.
- **`valid_to`**: typically `NULL` until the rule is superseded by a new playbook version, at which point `invalidated_at` and `invalidated_by` are set.
- **Edges**: `derived_from` → reflection that motivated the rule; `supersedes` → prior rule version.

## 4. Signals (separate from memory)

System-emitted notifications live in a `signals` table, not in `memory_nodes`. Rationale:

- **Different author.** Signals are produced by `report.coach`, lazy stale-watch scans, and write-triggered checks. The agent does not author them.
- **Different lifecycle.** Signals are time-bounded notifications, not durable knowledge. Old signals should fall off the agent's awareness, not occupy graph rank.
- **Different read path.** `report.coach` aggregates recent signals; `memory.recall` does not surface them by default.

### 4.1 `signals` schema (logical)

- `id`, `kind` (`calibration_drift`, `override_outcome_negative`, `stale_watch`, `unscored_forecast`, …)
- `severity` (`info`, `warn`, `critical`)
- `body`, `meta_json`, `related_refs_json` (array of ledger pointers)
- `created_at`, `expires_at` (nullable; informational only)

Append-only. Stale signals are filtered by `created_at` or `expires_at`, never deleted.

### 4.2 Reflection on a signal

When the agent reflects on a signal it considers important, it writes a `reflection` memory node with an `about` edge whose target is the signal row. This promotes the agent's interpretation into durable memory while leaving the raw signal in its short-lived table. Edge endpoint kinds include `signal` for this reason.

## 5. Edge taxonomy

Edges are typed and asymmetric. They live in the `edges` table connecting any memory node or signal to any other memory node, signal, strategy, or validated ledger/source endpoint (decision, thesis, forecast, outcome, position, snapshot, review, playbook_version, source, instrument, venue, signal, strategy). The core validates endpoint kind and ID before insertion. Strategies (PRD §2.12) are first-class endpoints so reflections and observations can target a strategy as a whole.

| Edge type | Direction | Semantics |
|-----------|-----------|-----------|
| `about` | reflection → target | "this reflection is about this target" |
| `derived_from` | child → parent | "this node was synthesized from these inputs" |
| `supports` | A → B | "A provides positive evidence for B" |
| `contradicts` | A → B | "A provides negative evidence for B" |
| `supersedes` | new → old | "new replaces old; old still readable but discounted at recall" |
| `violates` | decision → rule | "this decision overrode this rule" |
| `follows` | decision → rule | "this decision was consistent with this rule" |

**Deferred until concrete need:** `links` (weakly related), `retracts` and `tombstones` (administrative edge admin). Edges are append-only; correction is by `supersedes`. If administrative removal becomes necessary, retract/tombstone edge events will be added later. `contradicts` is semantic evidence and is never used for administrative deletion.

## 6. Confidence and decay model

Every memory node carries `confidence_base` (default `1.0`), `decay_rate_per_day` (default by `node_type`, overridable per node), and `importance` (`[1, 10]`, default `5`). At recall time, effective confidence is:

```
age_days = (now - created_at).days
effective = clamp(
    confidence_base
    * exp(-decay_rate_per_day * age_days)
    * supersession_discount,
    0, 1
)
```

Where `supersession_discount = 0.25` if any `supersedes` edge points at this node from a newer node OR `invalidated_at` is non-null and `<= now`, else `1.0`. The supersession constant is pinned to `0.25` in MVP for test determinism; config override is allowed but the default is fixed.

Importance does NOT enter `effective_confidence`. It is a separate per-row signal applied in the ranker (§7.4) as a small multiplicative boost on the RRF score before final ranking. Keeping the two signals separate preserves the meaning of "confidence" as "how much do I believe this" and "importance" as "how much should this surface."

**Properties:**
- Old memories fade rather than disappear.
- Superseded memories are still recallable for audit but rarely surface in top-k.
- Decay rate is per-node, so the agent can write a durable belief with low decay or a low-confidence guess with high decay.
- Bi-temporal validity is applied **before** ranking: nodes outside the active `[valid_from, valid_to)` window for the recall's `as_of` timestamp (default = `now`) are filtered out of the candidate set; ranking runs only on the survivors.

**Deferred to P1: edge-density factor.** Boosting nodes with many `supports` edges and discounting those with `contradicts` edges is appealing but only earns its keep once edge populations are dense. The shape (e.g., a `(1 + α · (log(1+supports) − log(1+contradicts)))` multiplier) is sketched in P1 backlog. Coefficients must be calibrated against dogfood data, not theory.

Recall telemetry (`recall_count`, `last_recalled_at`) lives in `memory_node_stats`, populated from the `memory_recall_events` event log (PRD §3.2).

## 7. Multi-strategy retrieval

`memory.recall(query, context?, strategies?, k?, max_chars?, compact?, include_body?, include_provenance?, min_confidence?, node_types?, mode?, as_of?)` runs each enabled retrieval strategy, fuses scores via Reciprocal Rank Fusion (when `mode = 'fused'`, the default) or returns the per-strategy lists side-by-side (when `mode = 'per_strategy'`), and shapes the result to fit the caller's context budget. `query` is required by the live schema; optional `context` narrows graph/provenance ranking metadata and is not a substitute for `query`.

The default `strategies` value is `["bm25", "temporal", "semantic"]` when a semantic provider is configured, and `["bm25", "temporal"]` otherwise. Callers can explicitly request `"graph"` to add graph traversal.

`as_of` defaults to `now`. When supplied, recall first filters the candidate set by bi-temporal validity (§3 / [`operability.md`](operability.md) §2): a node is in-scope only when its `valid_from <= as_of < coalesce(valid_to, +∞)` and (`invalidated_at IS NULL` OR `invalidated_at > as_of`). This makes "what did the agent know on day X" a primitive query, not a post-hoc filter. Ranking runs on the in-scope set; out-of-scope nodes are not silently demoted, they are excluded.

`node_types` (optional, subset of `["observation", "reflection", "playbook_rule"]`) further restricts the candidate set. Combined with `as_of`, this lets the agent ask "what playbook rules did I think were active on day X" cleanly.

`mode = 'per_strategy'` returns:

```json
{
  "ok": true,
  "data": {
    "bm25": [...],
    "temporal": [...],
    "semantic": [...],
    "graph": [...],
    "fused": [...]
  }
}
```

So the agent can triangulate (e.g., "BM25 surfaced this node, semantic didn't — likely a rare keyword match"). `fused` is still present so callers don't have to re-combine. Only enabled strategies appear in the result.

### 7.1 Always-on strategies

- **`BM25`** — SQLite FTS5 over `title` and `body`. Free, fast, available without configuration.
- **`TEMPORAL`** — recency weight via `exp(-age_days · temporal_decay)`. Combined as a per-strategy weight, not a standalone retriever.

### 7.2 Opt-in strategy: SEMANTIC

**Implementation status (v0.0.2):** SEMANTIC recall is optional and local-only. The active `embeddings.provider` enum is `none|local`; remote/API embedding providers and keyring-backed embedding credentials are intentionally unsupported. Fresh journals default to BM25 + TEMPORAL + GRAPH-capable local recall only; `memory.recall` runs with zero network by default, and `journal.status` reports `embeddings_provider = "none"` on a fresh init.

- **`SEMANTIC`** — vector similarity using the local ONNX/tokenizers BGE-small path when the operator has both installed the `[embeddings]` extra and imported verified local model assets. There is no automatic model download.
  - `tt journal config_set --key embeddings.provider --value local --idempotency-key <uuid> --confirm` enables use of local assets if present. Missing assets/dependencies degrade semantic recall; journal operations continue.
  - `tt model import --path <path-to-bge-small> --idempotency-key <uuid> --confirm` copies a pre-staged model directory after SHA-256/size verification against Trade Trace-pinned lock data. This is the only model-staging path and performs zero outbound network calls.
  - `tt model warm` attempts a dummy local embed and returns `available=false` if assets/dependencies are absent.
  - Once local embeddings are available, `memory.recall` can include SEMANTIC in the enabled strategies.

The "off by default" choice preserves the absolute air-gap promise in VISION §safety on first `journal.init`. MVP recall via BM25 + temporal (+ graph if requested) returns valid results without vectors; SEMANTIC is a ranking-quality improvement, not a correctness gate.

### 7.3 Opt-in strategy: GRAPH

- **`GRAPH`** — 1-hop BFS from the `context` node, following edges optionally filtered by edge type. Deferred from MVP-default because graph relevance only earns its keep once edge populations are dense. Available behind a strategy flag (`strategies: ["graph", ...]`) from day one for callers who want it. Always available regardless of embedding configuration; does not require network.

### 7.4 Combination

Each retriever returns a ranked list with normalized scores. The combiner uses RRF:

```
score(node) = sum over strategies of (weight_s / (k_rrf + rank_s(node)))
final_score(node) = score(node) * importance_boost(node)
```

with `k_rrf = 60` (fixed in MVP for test determinism) and default per-strategy weights of `1.0` each. Weights are configurable via `tt journal config_set recall.weight.<strategy>`.

`importance_boost(node) = 1.0 + (importance - 5) * 0.05`, mapping `importance = 1` → 0.80x and `importance = 10` → 1.25x. Boost is small by design — recall ranking is primarily driven by retrieval relevance and the §6 confidence model, with importance as a writer-set tiebreaker.

The combined ranking is then filtered by `min_confidence` (after applying the §6 confidence model). Default `min_confidence = 0.0` so the filter is opt-in.

### 7.5 Budget parameters

`memory.recall` accepts:

- **`k`** *(int, default 10)* — desired number of top results before budget shaping.
- **`max_chars`** *(int, default 8000)* — hard ceiling on response payload character count. When the unshaped response would exceed this, the combiner first reduces `k`, then switches to `compact`, then drops lowest-scoring rows. Snippet length under `compact` is exactly 240 chars centered on the highest-scoring matched span (deterministic; ties broken by earliest match position).
- **`compact`** *(bool, default false)* — omit full `body`; return a 240-char snippet in `meta.snippet`. Useful when surfacing many candidates for the caller to pick from.
- **`include_body`** *(bool, default true)* — when false, omit `body` entirely. Useful when the caller only needs IDs, scores, and titles.
- **`include_provenance`** *(bool, default true)* — when false, omit the edge/source summary. When true, each row carries a `meta.provenance` summary with edge counts and the most relevant connected entities.

Every result row always carries `score`, `strategy` (top-contributing), `created_at`, `valid_from`, `valid_to`, `importance`, `effective_confidence`, and `node_type` for ranking transparency. Responses set `meta.budget_applied = true` when any shaping happened.

> **Terminology note.** The `strategy` field on a result row refers to the *retrieval strategy* (`bm25`, `temporal`, `semantic`, `graph`) that contributed the top rank for that row. It is unrelated to the *trading strategy* concept introduced in §7.6 and PRD §2.12. The two namespaces never collide in API payloads because retrieval strategies appear only in result rows under `strategy`, while trading strategies appear in inputs under `context: {kind: "strategy", id}` and in `strategy_id` columns.

### 7.6 Strategy context

When the caller supplies `context: {kind: "strategy", id: <strategy_id>}`, recall narrows to memory associated with that trading strategy (PRD §2.12). Each retrieval strategy interprets the context consistently:

- **`BM25`** — scoring is unchanged; the candidate set is restricted to memory nodes that either (a) have any edge to the strategy endpoint, or (b) carry a row-backed scope in `meta_json` whose backing row (decision, thesis, or review) has `strategy_id` equal to the supplied id.
- **`TEMPORAL`** — same candidate-set restriction as BM25; recency weighting is unchanged.
- **`SEMANTIC`** — same candidate-set restriction; vector similarity is computed normally over the restricted set.
- **`GRAPH`** — 1-hop BFS from the strategy endpoint via `edges`, optionally filtered by `edge_type`. Useful when the agent has been writing reflections that target the strategy directly.

Strategy context composes with `query` (full-text terms still apply within the strategy's subset) and with `min_confidence`/`max_chars` shaping. An empty candidate set (e.g., a fresh strategy with no linked memory yet) returns an empty result with `meta.budget_applied = false`, not an error.

## 8. Embeddings

**Implementation status (v0.0.2):** embeddings are optional, local-only, and fail-soft. The base wheel remains lightweight. Install the `[embeddings]` extra to make the local ONNX/tokenizers runtime available, then import a pre-staged verified model with `tt model import`. Remote/API embedding providers, OS-keyring credential storage, sqlite-vec-backed indexes, and automatic model downloads are not supported in v0.0.2.

### 8.1 Default: vectors off, deps optional

The base install does not require vector dependencies and never downloads model weights. A fresh install runs fully offline; recall uses BM25 + temporal (+ graph if requested). This is load-bearing: the product promise is a local/offline journal that does not send memory or trading data outward by default.

### 8.2 Enabling local embeddings

The supported local path is explicit and air-gapped:

1. Install optional runtime dependencies:
   ```bash
   pip install -e '.[embeddings]'
   ```
2. Pre-stage the pinned `BAAI/bge-small-en-v1.5` assets outside Trade Trace.
3. Import those assets:
   ```bash
   tt model import --path <path-to-bge-small> --idempotency-key <uuid> --confirm
   ```
4. Enable local provider use:
   ```bash
   tt journal config_set --key embeddings.provider --value local --idempotency-key <uuid> --confirm
   ```

`model.import` verifies every imported file against Trade Trace-pinned SHA-256/size lock data and ignores any source-provided manifest as proof. `journal.config_set` does not stage, download, or verify model assets; it only records the provider choice and reports whether local model files are currently present. `model.warm` attempts a local dummy embed and returns a degraded availability response when assets or optional dependencies are missing.

`tt journal config_set --key embeddings.provider --value none --idempotency-key <uuid> --confirm` is the default state and removes SEMANTIC from the active strategy set. Recall continues to work via BM25 + temporal (+ graph if requested).

### 8.3 Unsupported remote/API providers

Remote embedding providers are not part of the v0.0.2 product surface. `embeddings.provider=api:openai` and other remote/provider-key variants fail validation. No keyring backend is imported for embeddings, and no memory text is sent to embedding APIs. `keyring.revoke` remains only as a legacy no-op for older clients.

### 8.4 Re-indexing local embeddings

Embedding model identity and dimension are recorded per node in `memory_node_embeddings`. When `embeddings.provider=local` and verified local assets are available, `tt memory reindex --confirm` embeds existing nodes in one transaction and replaces stale rows for the active provider/model. If assets or optional dependencies are missing, reindex reports degraded availability and leaves existing rows untouched. BM25 + temporal recall remains available either way.

### 8.5 Disabling vectors

`tt journal config_set --key embeddings.provider --value none --idempotency-key <uuid> --confirm` persists the no-vector state. Recall continues to work via BM25 + temporal, and no outbound path is introduced.

## 9. Public API surface

All operations are exposed as MCP tools and CLI subcommands with semantic parity (see `contracts.md`).

- **`memory.retain(node_type, body, *, title?, tags?, metadata_json?, meta_json?, importance?, confidence_base?, decay_rate_per_day?, valid_from?, valid_to?, edges?)`** — write a memory node. `node_type ∈ {observation, reflection, playbook_rule}`. The additive schema transition prefers `metadata_json` and still accepts/writes legacy `meta_json` for compatibility until cleanup. The `edges` parameter lets the caller specify outgoing edges in the same call so reflection-without-edges never happens.
- **`memory.recall(query, context?, strategies?, k?, max_chars?, compact?, include_body?, include_provenance?, min_confidence?, node_types?, mode?, as_of?)`** — read with required `query`, multi-strategy retrieval, context-budget shaping, and optional bi-temporal `as_of` filtering. Optional `context` narrows ranking/provenance; it does not replace `query`.
- **`memory.reflect(target, body, *, importance?, ...)`** — sugar over `retain(node_type=reflection, ...)` that auto-wires the required `about` edge to `target`. The live schema does not accept `derived_from`; add supporting/provenance edges separately with `memory.link` or `memory.retain(edges=...)`.
- **`memory.link(from, to, edge_type, *, weight?)`** — explicit edge creation between two existing endpoints. Validates endpoint kind and ID.
- **`reflection.prompt_for_outcome(outcome_id, *, include_forecast?, include_thesis?, include_prior_reflections?)`** — deterministic, no-LLM tool. Returns a structured packet: the resolved outcome, the original thesis and forecast it resolved, prior reflections on the same instrument/strategy, and the calibration delta (forecast probability vs. realized indicator). The caller (a separate LLM) decides what to write back via `memory.reflect`. The system never auto-generates reflections; this tool packages evidence for the reviewer.

### 9.1 Downstream recall-use and citation conventions

Recall telemetry records what `memory.recall` returned; downstream use is recorded or inferred only from typed edges. The canonical use-link direction is always:

```text
consumer row  --edge_type-->  memory_node
```

where the consumer row is one of `decision`, `thesis`, `forecast`, `outcome`, `review`, or `playbook_version`. Use `memory.link` after the consumer row exists. Do **not** use `memory_node -> consumer` edges to mean downstream use; memory-node outgoing edges remain source/provenance/reference links.

| Consumer kind | When to link recalled memory | Use edge types | Caveat edge types |
|---|---|---|---|
| `decision` | The decision reason cites or materially relies on a recalled lesson/observation/reflection. | `supports`, `derived_from`, `about`, `follows`, `violates` | `contradicts`, `supersedes` |
| `thesis` | A promoted thesis uses a remembered precedent, rule, or reflection as evidence/context. | `supports`, `derived_from`, `about` | `contradicts`, `supersedes` |
| `forecast` | A probability/range forecast uses a remembered calibration lesson or comparable case. | `supports`, `derived_from`, `about` | `contradicts`, `supersedes` |
| `review` / reflection target | A review/reflection explicitly uses recalled memories as evidence for the review conclusion. | `supports`, `derived_from`, `about`, `follows`, `violates` | `contradicts`, `supersedes` |
| `playbook_version` | A playbook/rule change is based on or intentionally departs from a recalled memory. | `supports`, `derived_from`, `about`, `follows`, `violates` | `contradicts`, `supersedes` |

Attribution terms are exact:

- **Cited / used**: a consumer-to-memory edge exists with `supports`, `derived_from`, `about`, `follows`, or `violates`. `violates` still counts as use because the consumer intentionally used the memory as a rule/constraint it broke.
- **Ignored**: the memory was returned in the recall event but the scoped consumer has no downstream edge to it.
- **Not attributable**: the report has no consumer scope, no matching consumer edge, or only memory-node outgoing source/reference edges. The system cannot distinguish "ignored" from "used in free text but not linked".
- **Stale**: the returned memory has `valid_to` at or before the receipt `as_of`, or `invalidated_at`/`invalidated_by` is set. Stale memories may still be cited, but the receipt carries a stale caveat.
- **Contradicted**: a scoped or inferred consumer has a `contradicts` edge to the returned memory. This is not a use edge, but it is downstream evidence and carries a contradiction caveat.
- **Superseded**: a scoped or inferred consumer has a `supersedes` edge to the returned memory. This is not a use edge, but it is downstream evidence and carries a supersession caveat.

Strong attribution requires both `consumer_kind` and `consumer_id` when calling `report.recall_receipts`. If only broad filters are used, the report may infer downstream edges from any supported consumer kind and must mark the receipt with `CONSUMER_INFERENCE_UNSCOPED`.

Source/provenance convention: `memory_node -> source` edges are exposed as `source_refs` in recall receipts, but never prove downstream use. They answer "where did this memory come from?", not "which later decision used it?".

The `target` of a reflection can be:

- A specific decision (`decision_id`), position (`position_id`), instrument (`instrument_id`), playbook version (`playbook_version_id`), signal (`signal_id`), outcome (`outcome_id`), forecast (`forecast_id`), or strategy (`strategy_id`) — creates an `about` edge to the target endpoint.
- A time period (`period: {start, end}`) or tag (`tag: "liquidity-ignored"`) — stored in reflection `meta_json` until/unless period/tag entities become first-class endpoints. Strategies, by contrast, *are* first-class (PRD §2.12) and target a strategy directly rather than via `meta_json`.

### 9.2 Period- and tag-scoped reflection lookup

Since period and tag are not first-class edge endpoints in MVP, the
lookup pattern goes through `meta_json` directly. The canonical
representation in `meta_json` is locked so callers and reports agree on
what to query:

| Scope | `meta_json` shape (written by `memory.reflect`) |
|---|---|
| Period | `meta_json.scope_kind = "period"`, `meta_json.scope_period = {"start": "<ISO 8601 UTC>", "end": "<ISO 8601 UTC>"}`. `start` is inclusive, `end` is exclusive. |
| Tag | `meta_json.scope_kind = "tag"`, `meta_json.scope_tag = "<lower-cased tag>"`. Tag normalization mirrors `decision_tags` (lowercase, leading/trailing whitespace stripped). |

`memory.recall` accepts these scopes via the `context` parameter:

- `context: {kind: "period", id: {"start": "...", "end": "..."}}` —
  restricts the candidate set to reflection nodes where
  `meta_json.scope_kind = "period"` AND the stored period interval
  intersects the supplied interval (`stored.start < query.end AND
  stored.end > query.start`).
- `context: {kind: "tag", id: "liquidity-ignored"}` — restricts the
  candidate set to reflection nodes where `meta_json.scope_kind = "tag"`
  AND `meta_json.scope_tag` equals the lower-cased query tag.

Both lookups compose with `query` (FTS5 over body/title), `as_of`
(bi-temporal validity per §3), `node_types` (which must include
`reflection` for either lookup to return anything), and the other
budget params (`k`, `max_chars`, `compact`). An empty candidate set
returns an empty result with `meta.budget_applied = false`, not an
error.

This pattern reserves first-class period/tag entity promotion for a
later release without changing the recall API: a future
`period`/`tag` endpoint kind on the edges table can be wired up
transparently, with `memory.reflect` writing both the new edge and the
legacy `meta_json` keys for one schema version (the
[`operability.md`](operability.md) §4.4 add-new + dual-write pattern).

## 10. Reflection ergonomics

`memory.reflect(...)` automatically:

1. Creates the reflection node.
2. Creates an `about` edge to the target (for row-backed targets).

The following edge sugar is documented for the contract but **deferred
to P1+** per bead trade-trace-m0h. Passing any of these fields today
returns `UNSUPPORTED_CAPABILITY` so docs-following agents see a clear
deferral message instead of a silent acceptance:

3. Optionally creates `derived_from` edges to specified observations.
4. Optionally creates `supersedes` edges to older reflection IDs.
5. Optionally creates `supports` / `contradicts` edges to other memory nodes.

Until that ships, callers write follow-up edges via `memory.link`,
which is fully implemented. The reflection node + about edge are
still atomic per bead trade-trace-1up.

The MVP write surface accepts two equivalent shapes:

- Flat (canonical): `memory.reflect(target_kind, target_id, body, …)`.
- Sugar (README §quickstart): `memory.reflect(target={"kind", "id"},
  insight, strength_tags?, weakness_tags?, …)`. `strength_tags` and
  `weakness_tags` are folded into the reflection's
  `metadata_json.tags` so structured-tag recall picks them up.

Per bead trade-trace-m0h: the sugar shape and the deferred edge
fields are pinned by tests replaying the README example.

## 11. Hindsight comparison

We evaluated Vectorize.io's Hindsight as a potential dependency. The retrieval architecture (BM25 + vector + graph + temporal, RRF + reranker) is essentially identical to ours, and Hindsight is mature and MIT-licensed.

We chose to build because three product constraints are structurally incompatible with using Hindsight as a dependency:

| Concern | Hindsight | Trade Trace |
|---------|-----------|-------------|
| Storage | Postgres-primary; embedded mode is Postgres-the-process | Single SQLite file — load-bearing for air-gappable install and `cp`-able backup |
| Domain edges | `metadata: {...}` JSON blob for custom fields | Typed edges with endpoint-kind validation linking to decisions / outcomes / playbook versions / signals |
| Confidence | Generic recency + relevance | Calibration-aware: decay + supersession + bi-temporal validity filter at MVP; importance signal in the ranker; edge-density factor at P1. The bi-temporal filter and decay/supersession apply *in* the ranker (filter before scoring; supersession discount inside the score). Edge-density is the deferred piece and is the only Hindsight-parity feature missing from MVP. |
| Bi-temporal model | Transaction time only | Transaction time (`created_at`, `invalidated_at`) plus world time (`valid_from`, `valid_to`) for clean as-of queries |
| Importance signal | No first-class importance | Writer-set `importance ∈ [1,10]` on every node, feeds ranker boost; inspired by Generative Agents |

The Retain/Recall/Reflect public-surface naming mirrors Hindsight so that agents and developers familiar with one can move between systems with minimal context. The implementation is ours.

## 12. Open questions

1. **Edge weight semantics.** Edges carry an optional `weight` float. Should this feed the (P1) edge-density factor in §6? MVP behavior: ignore weight; treat all edges as `1.0`. Revisit when there's dogfood data.
2. **Dual-index during reindex.** §8.4 specifies eager reindex with user confirmation. Open: do we offer a transient "dual-index" mode that keeps old and new embeddings live until the user explicitly drops the old set? Probably P1; MVP is single-active-provider.
3. **Multi-modal memory.** Chart snapshots, screenshots, attached PDFs are out of MVP. Could be added later via a `source` kind with a multimodal embedding model.
4. **Token vs character budgets.** MVP uses `max_chars` (deterministic across tokenizers). If non-English content surfaces a tokenizer-awareness need, add `max_tokens` with explicit tokenizer choice in P1.
5. **Bundled-weights install extra.** `bge-small-en-v1.5` ships as a lazy download. If genuinely air-gapped installs become a common ask, a `pip install trade-trace[vectors-bundled]` extra that includes the weights in the wheel can follow.
6. **Two-tier reflection.** Generative-agents-style threshold-triggered deep reflection from clusters of shallow reflections is appealing but premature. P1+ candidate once importance accumulation across sessions is dogfooded.
7. **Importance boost coefficients.** §7.4 ships a small `1.0 + (importance - 5) * 0.05` boost. The 0.05 slope is a guess; calibrate against dogfood data and revisit.

---

## Appendix: changes from v2 (same date)

- **PRD alignment committed.** §3.2 schema rows, §4.1 API list, and §11 open questions in the PRD now match this doc (3 node types, 7 edge types, separate `memory_node_embeddings` / `signals` / `memory_recall_events` tables).
- **Embeddings flipped to off-by-default in MVP.** Earlier v2 made `bge-small-en-v1.5` default-on via lazy download on first init; that violated the "no outbound calls on `journal.init`" promise in VISION §safety. v3 ships vectors off; opt-in via explicit config or `tt model import`. Deps still ship in the wheel.
- **Node name `rule` → `playbook_rule`.** Resolves the PRD/`memory-layer.md` drift on what to call the procedural-memory node type. Domain term wins.
- **Bi-temporal validity added.** Every memory node now carries `valid_from`, `valid_to`, `invalidated_at`, `invalidated_by`. `memory.recall` accepts `as_of` to query the agent's belief state at a past timestamp.
- **Importance signal added.** Writer-set `importance ∈ [1, 10]`, defaults to `5`. Feeds the recall ranker as a small multiplicative boost.
- **`mode` parameter on `memory.recall`.** Default `fused` preserves prior behavior; `per_strategy` returns side-by-side per-strategy results for triangulation.
- **`reflection.prompt_for_outcome` tool added.** Deterministic packet-builder for outcome-triggered reflection; never calls an LLM.

## Appendix: changes from v1 (same date)

- **Node taxonomy: 5 → 3.** `semantic_claim` collapses into reflection-with-slow-decay (a `decay_rate_per_day` choice, not a type). `coach_signal` moves out of `memory_nodes` into a separate `signals` table because its author and lifecycle differ.
- **Edge taxonomy: 10 → 7.** `links`, `retracts`, `tombstones` deferred until a concrete use case.
- **Confidence model simplified.** Edge-density factor deferred to P1; MVP is decay + supersession only. The factor's coefficients need real dogfood data, not theory.
- **Graph retriever moved from default to opt-in.** Edge populations are sparse at MVP; graph relevance pays off later. Strategy flag exists from day one.
