# Memory Layer — Architecture Note

**Date:** 2026-05-18
**Status:** Refined draft v3 (supersedes v2; PRD §3.2/§4.1 alignment now committed)
**Parent:** [`../../PRD.md`](../../PRD.md) §5 & §4.2

This note details the memory layer's node taxonomy, edge semantics, retrieval strategies, embedding policy, and confidence model. The PRD owns the schema rows; this doc owns the semantic intent. As of v3, the PRD schema and this doc are aligned on the 3-node-type taxonomy, the 7-edge-type taxonomy, the separate `memory_node_embeddings` table, the `signals` table, and the `memory_recall_events` event log.

## 1. Goals

The memory layer turns a passive trade ledger into an active knowledge graph the agent can think with. Three capabilities:

1. **Recall**: when an agent forms a new thesis on instrument X, surface relevant past observations, reflections, and playbook rules.
2. **Reflect**: when an outcome resolves or a coach signal fires, store the agent's synthesis as a typed memory node linked to the ledger rows that motivated it.
3. **Evolve**: when reflections accumulate, allow the agent to codify them as versioned playbook rules whose adherence and override outcomes are tracked.

It is **not** a generic agent memory framework. The schema is trading-shaped: every node can link to ledger rows; confidence decays; recall can scope to instrument / venue / asset class / market type.

## 2. Design principles

1. **One SQLite file is the entire product state.** Ledger, memory, edges, FTS index, and (when enabled) vector index live in one DB. `cp trade-trace.sqlite` is a complete backup. Load-bearing for the air-gappable install promise. Backup/restore caveats (open WAL, in-flight outbox drain) covered in [`operability.md`](operability.md) §5.
2. **Zero-config first run, no surprise network.** `pip install trade-trace && tt init && tt mcp` works without flags or API keys. Vectors are **off** by MVP default; `journal.init` makes zero outbound calls. The SEMANTIC strategy is opt-in via explicit config (`tt config set embeddings.provider local` or `tt model import <path>`); this preserves the absolute air-gap promise from VISION §safety on first run.
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

### 3.3 `playbook_rule`

A codified procedural rule belonging to a specific `playbook_version`.

- **Examples**: "Do not enter prediction-market positions when spread > 8% of expected edge"; "Require 2x base liquidity for any entry within 7 days of resolution".
- **Required meta**: `playbook_version_id` and `rule_meta` (`trigger_kind`, `applicable_decision_types`, optional `applicable_asset_classes`).
- **Body** holds the free-text rule the agent reads when reasoning. MVP rules are advisory; automatic violation detection requires explicit predicate fields added later.
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

`memory.recall(query?, context?, strategies?, k?, max_chars?, compact?, include_body?, include_provenance?, min_confidence?, node_types?, mode?, as_of?)` runs each enabled retrieval strategy, fuses scores via Reciprocal Rank Fusion (when `mode = 'fused'`, the default) or returns the per-strategy lists side-by-side (when `mode = 'per_strategy'`), and shapes the result to fit the caller's context budget.

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

**Implementation status (M3, bead trade-trace-ubp split):** the SEMANTIC strategy and its enabling config surfaces (`tt config set embeddings.provider local|openai|none`, `tt model import <path>`, `tt memory reindex --confirm`) are **deferred to bead trade-trace-a4p** (deferred until 2026-06-15). MVP ships BM25 + TEMPORAL + GRAPH only; `memory.recall` runs entirely on local SQLite (FTS5 BM25, in-memory recency, edges-table traversal) with zero network. `journal.status` reports `embeddings_provider = "none"` on every fresh init. The off-by-default contract is verified end-to-end in `tests/security/test_embeddings_off_by_default.py`.

- **`SEMANTIC`** — vector similarity via `sqlite-vec`. **Off by default in MVP** (per PRD §2.4.1). The package ships with `sqlite-vec` and `sentence-transformers` as runtime dependencies, but no model weights are downloaded on `journal.init`. To enable (in a future build that lands bead a4p):
  - `tt config set embeddings.provider local` — authorizes one-time download of `BAAI/bge-small-en-v1.5` (~130MB) into `$TRADE_TRACE_HOME/models/`. Subsequent recall calls use it transparently.
  - `tt model import <path>` — air-gapped install path that uses a pre-staged model without any network call.
  - `tt config set embeddings.provider openai` (or other API provider) — opt-in remote embedding; see §8.3.
  - Once enabled, `memory.recall` includes SEMANTIC in the default `strategies` value.

The "off by default" choice preserves the absolute air-gap promise in VISION §safety on first `journal.init`. MVP recall via BM25 + temporal (+ graph if requested) returns valid results without vectors; SEMANTIC is a ranking-quality improvement, not a correctness gate.

### 7.3 Opt-in strategy: GRAPH

- **`GRAPH`** — 1-hop BFS from the `context` node, following edges optionally filtered by edge type. Deferred from MVP-default because graph relevance only earns its keep once edge populations are dense. Available behind a strategy flag (`strategies: ["graph", ...]`) from day one for callers who want it. Always available regardless of embedding configuration; does not require network.

### 7.4 Combination

Each retriever returns a ranked list with normalized scores. The combiner uses RRF:

```
score(node) = sum over strategies of (weight_s / (k_rrf + rank_s(node)))
final_score(node) = score(node) * importance_boost(node)
```

with `k_rrf = 60` (fixed in MVP for test determinism) and default per-strategy weights of `1.0` each. Weights are configurable via `tt config set recall.weight.<strategy>`.

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

**Implementation status (M3):** §8.1 ships in MVP; §§8.2-8.5 (provider config tool, lazy download, API providers, reindex, disable) are **deferred to bead trade-trace-a4p** (deferred until 2026-06-15, split from bead ubp). MVP wheels do NOT yet bundle `sqlite-vec` / `sentence-transformers` — those install-time dependencies land with a4p. The off-by-default behavior described in §8.1 is the binding contract today: a fresh `journal.init` makes zero outbound network calls and the recall path returns valid results without vectors.

### 8.1 MVP default: vectors off, deps bundled

The base wheel includes `sqlite-vec` and `sentence-transformers` as runtime dependencies — they ship with the install (planned with bead a4p; M3 wheels are vector-dep-free pending that bead). **No model weights are downloaded on `journal.init`.** A fresh install runs fully offline; recall uses BM25 + temporal (+ graph if requested).

This is the load-bearing change from earlier drafts: VISION §safety promises "MVP makes no outbound network calls" and is air-gappable on first run, which a default-on lazy download breaks. Defaulting vectors off keeps that promise; opting in is one config line.

Rationale for shipping deps but not weights: the deps are needed for any vector path (local or API); the weights are large and not everyone needs them. Shipping deps lets the opt-in path activate without `pip install` step two.

### 8.2 Enabling local embeddings

Two paths, both explicit:

- **Online opt-in**: `tt config set embeddings.provider local` authorizes a one-time download of `BAAI/bge-small-en-v1.5` (~130MB, 384-dim, English-only, sufficient for trading content). The next recall call (or `tt model warm`) triggers the download into `$TRADE_TRACE_HOME/models/`. The download target is the model's host only; no telemetry, no metrics, no journal data transmitted. After download, the system runs fully air-gapped.
- **Air-gapped install**: `tt model import <path-to-bge-small>` copies a manually-staged model directory into the cache. The model is identified by its config hash; once present, recall uses it without any network call.

`tt config set embeddings.provider none` (the default state) removes the SEMANTIC strategy. `memory.recall` runs with BM25 + temporal (+ graph if requested) and returns valid results.

### 8.3 API providers

Users can configure a remote embedding provider:

```
tt config set embeddings.provider openai --model text-embedding-3-small
```

The CLI prompts for the API key and stores it in the OS keyring (via the `keyring` library; declared as an optional install extra). The key is **never** stored in the database, **never** stored in plaintext config, and **never** logged. Each call sends `body` (and optionally `title`) to the provider; the response embedding is persisted in `memory_node_embeddings`.

This path sends memory text outside the machine. The CLI emits an explicit warning on `tt config set embeddings.provider <api>` describing what data leaves and where. It is opt-in, requires the API key prompt, and does not become default in any future MVP path.

Two outbound paths exist in trade-trace; both opt-in:
- **Local model weight download** (§8.2): one-time, weights only, no journal data.
- **API embedding provider** (§8.3): per-call, sends memory text outbound.

No other path makes outbound network calls. No telemetry, no usage analytics, no auto-update, no webhook.

### 8.4 Re-embed on provider change

Embedding model identity and dimension are recorded per node in `memory_node_embeddings`. When the provider or model changes:

- New writes use the new provider.
- Old vectors become unusable (dimension mismatch with the new index).
- The user runs `tt memory reindex --confirm` to re-embed existing nodes. The command reports node count and estimated cost (free for local; explicit dollar estimate for API providers) before running.
- Until reindex completes, vector recall covers only nodes embedded under the current provider; BM25 + temporal cover the rest. The combiner handles missing-vector cases gracefully.

Lazy re-embed at recall time is rejected because the vector index needs a fixed dimension; mixing dims is more complex than the eager reindex path.

### 8.5 Disabling vectors

`tt config set embeddings.provider none` removes the SEMANTIC strategy from the default-enabled set. Recall continues to work via BM25 + temporal. The setting is persisted in the config table.

## 9. Public API surface

All operations are exposed as MCP tools and CLI subcommands with semantic parity (see `contracts.md`).

- **`memory.retain(node_type, body, *, title?, tags?, meta_json?, importance?, confidence_base?, decay_rate_per_day?, valid_from?, valid_to?, edges?)`** — write a memory node. `node_type ∈ {observation, reflection, playbook_rule}`. The `edges` parameter lets the caller specify outgoing edges in the same call so reflection-without-edges never happens.
- **`memory.recall(query?, context?, strategies?, k?, max_chars?, compact?, include_body?, include_provenance?, min_confidence?, node_types?, mode?, as_of?)`** — read with multi-strategy retrieval, context-budget shaping, and optional bi-temporal `as_of` filtering.
- **`memory.reflect(target, body, *, importance?, derived_from?, supports?, contradicts?, supersedes?, ...)`** — sugar over `retain(node_type=reflection, ...)` that auto-wires the `about` edge to `target`.
- **`memory.link(from, to, edge_type, *, weight?)`** — explicit edge creation between two existing endpoints. Validates endpoint kind and ID.
- **`reflection.prompt_for_outcome(outcome_id, *, include_forecast?, include_thesis?, include_prior_reflections?)`** — deterministic, no-LLM tool. Returns a structured packet: the resolved outcome, the original thesis and forecast it resolved, prior reflections on the same instrument/strategy, and the calibration delta (forecast probability vs. realized indicator). The caller (a separate LLM) decides what to write back via `memory.reflect`. The system never auto-generates reflections; this tool packages evidence for the reviewer.

The `target` of a reflection can be:

- A specific decision (`decision_id`), position (`position_id`), instrument (`instrument_id`), playbook version (`playbook_version_id`), signal (`signal_id`), outcome (`outcome_id`), forecast (`forecast_id`), or strategy (`strategy_id`) — creates an `about` edge to the target endpoint.
- A time period (`period: {start, end}`) or tag (`tag: "liquidity-ignored"`) — stored in reflection `meta_json` until/unless period/tag entities become first-class endpoints. Strategies, by contrast, *are* first-class (PRD §2.12) and target a strategy directly rather than via `meta_json`.

### 9.1 Period- and tag-scoped reflection lookup

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
