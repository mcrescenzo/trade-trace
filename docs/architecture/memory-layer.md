# Memory Layer — Architecture Note

**Date:** 2026-05-18
**Status:** Refined draft v2 (supersedes v1 from 2026-05-18)
**Parent:** [`../../PRD.md`](../../PRD.md) §5 & §4.2

This note details the memory layer's node taxonomy, edge semantics, retrieval strategies, embedding policy, and confidence model. The PRD owns the schema rows; this doc owns the semantic intent.

## 1. Goals

The memory layer turns a passive trade ledger into an active knowledge graph the agent can think with. Three capabilities:

1. **Recall**: when an agent forms a new thesis on instrument X, surface relevant past observations, reflections, and playbook rules.
2. **Reflect**: when an outcome resolves or a coach signal fires, store the agent's synthesis as a typed memory node linked to the ledger rows that motivated it.
3. **Evolve**: when reflections accumulate, allow the agent to codify them as versioned playbook rules whose adherence and override outcomes are tracked.

It is **not** a generic agent memory framework. The schema is trading-shaped: every node can link to ledger rows; confidence decays; recall can scope to instrument / venue / asset class / market type.

## 2. Design principles

1. **One SQLite file is the entire product state.** Ledger, memory, edges, FTS index, and (when enabled) vector index live in one DB. `cp trade-trace.sqlite` is a complete backup. Load-bearing for the air-gappable install promise.
2. **Zero-config first run.** `pip install trade-trace && tt init && tt mcp` works without flags or API keys. Vectors are on by default via a small local embedding model fetched on init.
3. **Optional capabilities, never required.** API embedding providers, graph traversal, edge-density confidence — all opt-in or deferred. The MVP product is fully functional without them.
4. **Trading-specific edges, generic everything else.** Custom typed edges from memory to ledger rows are the moat. Retrieval primitives (BM25, vector, RRF) are standard.
5. **System-emitted signals are not memory.** They live in a separate table because they have a different author (the system) and a different lifecycle (time-bounded notifications, not durable knowledge the agent authored).

## 3. Memory node taxonomy

Three `node_type` values cover MVP. Each has a default `decay_rate_per_day`, but `decay_rate_per_day` is a writable field so the agent can override per node (e.g., `0.0` for a belief it considers durable, faster decay for a low-confidence guess).

### 3.1 `observation`

A point-in-time record of something the agent noticed about a market, instrument, or pattern. Episodic.

- **Examples**: "Polymarket markets with < $5K ADV around resolution dates show 40bps wider spreads"; "NVDA gapped up 8% post-earnings and faded 4% within the first hour for the third quarter in a row".
- **Required meta**: at least one scoping field — `instrument_id`, `venue_id`, `asset_class`, or `pattern_kind`.
- **Default decay**: `0.003` per day (half-life ~230 days). Episodic, ages slowly.

### 3.2 `reflection`

A retrospective synthesis written by the agent after a decision, position, period, or coach-signal event. Subjective.

- **Examples**: "I overweighted the spread compression thesis here and ignored that the liquidity profile didn't match my prior pattern"; "Three skips this week were all driven by `liquidity-ignored` worry that turned out to be correct — keep doing this".
- **Required meta**: `target_kind` and `target_id` for row-backed targets, or explicit scope metadata (`period`, `tag`) for non-row targets. Optional: `mistake_tags`, `strength_tags`.
- **Default decay**: `0.002` per day (half-life ~350 days).
- **Durable beliefs** (e.g., "thin-liquidity prediction markets near resolution are systematically mispriced") can set `decay_rate_per_day` to `0.0005` or lower to express slow-fading belief. There is no separate `semantic_claim` type; a reflection with slow decay plays that role. The agent decides at write time.

### 3.3 `rule`

A codified procedural rule belonging to a specific `playbook_version`.

- **Examples**: "Do not enter prediction-market positions when spread > 8% of expected edge"; "Require 2x base liquidity for any entry within 7 days of resolution".
- **Required meta**: `playbook_version_id` and `rule_meta` (`trigger_kind`, `applicable_decision_types`, optional `applicable_asset_classes`).
- **Body** holds the free-text rule the agent reads when reasoning. MVP rules are advisory; automatic violation detection requires explicit predicate fields added later.
- **Default decay**: `0.0`. Rules are superseded by new versions, not faded.
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

Edges are typed and asymmetric. They live in the `edges` table connecting any memory node or signal to any other memory node, signal, or validated ledger/source endpoint (decision, thesis, forecast, outcome, position, snapshot, review, playbook_version, source, instrument, venue, signal). The core validates endpoint kind and ID before insertion.

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

Every memory node carries `confidence_base` (default `1.0`) and `decay_rate_per_day` (default by `node_type`, overridable per node). At recall time, effective confidence is:

```
age_days = (now - created_at).days
effective = clamp(confidence_base * exp(-decay_rate_per_day * age_days) * supersession_discount, 0, 1)
```

Where `supersession_discount = 0.25` if any `supersedes` edge points at this node from a newer node, else `1.0`. The supersession constant is tunable via config.

**Properties:**
- Old memories fade rather than disappear.
- Superseded memories are still recallable for audit but rarely surface in top-k.
- Decay rate is per-node, so the agent can write a durable belief with low decay or a low-confidence guess with high decay.

**Deferred to P1: edge-density factor.** Boosting nodes with many `supports` edges and discounting those with `contradicts` edges is appealing but only earns its keep once edge populations are dense. The shape (e.g., a `(1 + α · (log(1+supports) − log(1+contradicts)))` multiplier) is sketched in P1 backlog. Coefficients must be calibrated against dogfood data, not theory.

Recall telemetry (`recall_count`, `last_recalled_at`) lives in `memory_node_stats`, not on the node row.

## 7. Multi-strategy retrieval

`memory.recall(query?, context?, strategies?, k?, max_chars?, compact?, include_body?, include_provenance?, min_confidence?)` runs each enabled strategy, fuses scores via Reciprocal Rank Fusion, and shapes the result to fit the caller's context budget.

The default `strategies` value is `["bm25", "temporal", "semantic"]` when a semantic provider is configured, and `["bm25", "temporal"]` otherwise. Callers can explicitly request `"graph"` to add graph traversal.

### 7.1 Always-on strategies

- **`BM25`** — SQLite FTS5 over `title` and `body`. Free, fast, available without configuration.
- **`TEMPORAL`** — recency weight via `exp(-age_days · temporal_decay)`. Combined as a per-strategy weight, not a standalone retriever.

### 7.2 Default-on strategy

- **`SEMANTIC`** — vector similarity via `sqlite-vec`. Enabled by default because the package ships with vector dependencies and a local embedding model is fetched on first `tt init` (see §8). The agent and CLI do not have to know whether vectors are configured — recall just uses them when present.

### 7.3 Opt-in strategy

- **`GRAPH`** — 1-hop BFS from the `context` node, following edges optionally filtered by edge type. Deferred from MVP-default because graph relevance only earns its keep once edge populations are dense. Available behind a strategy flag (`strategies: ["graph", ...]`) from day one for callers who want it.

### 7.4 Combination

Each retriever returns a ranked list with normalized scores. The combiner uses RRF:

```
score(node) = sum over strategies of (weight_s / (k_rrf + rank_s(node)))
```

with `k_rrf = 60` and configurable per-strategy weights. The combined ranking is then filtered by `min_confidence` (after applying the §6 confidence model).

### 7.5 Budget parameters

`memory.recall` accepts:

- **`max_chars`** *(int, optional)* — hard ceiling on response payload character count. When set, the combiner first reduces `k`, then switches to `compact`, then drops lowest-scoring rows. Recommended default for typical LLM windows: ~8000.
- **`compact`** *(bool, default false)* — omit full `body`; return a `snippet` (~240 chars centered on the highest-scoring matched span) in `meta.snippet`. Useful when surfacing many candidates for the caller to pick from.
- **`include_body`** *(bool, default true)* — when false, omit `body` entirely. Useful when the caller only needs IDs, scores, and titles.
- **`include_provenance`** *(bool, default true)* — when false, omit the edge/source summary. When true, each row carries a `meta.provenance` summary with edge counts and the most relevant connected entities.

Every result row always carries `score`, `strategy` (top-contributing), `created_at`, `effective_confidence`, and `node_type` for ranking transparency. Responses set `meta.budget_applied = true` when any shaping happened.

## 8. Embeddings

### 8.1 Default: bundled deps, lazy-downloaded local model

The base wheel includes `sqlite-vec` and `sentence-transformers` as runtime dependencies — they ship with the install. On the first `tt init` (or first vector write), the system downloads a small local embedding model — current pick: `BAAI/bge-small-en-v1.5` (~130MB, 384-dim, English-only, sufficient for trading content). The model cache lives under `$TRADE_TRACE_HOME/models/`. After first download, the system runs fully air-gapped.

Rationale for shipping deps but not weights: the deps are needed for any vector path (local or API); the weights are large and not everyone needs them. Lazy weight download keeps the wheel small while keeping the path single-command.

### 8.2 Air-gapped install

For environments without network at install time:

- **Pre-stage the model**: `tt model import <path-to-bge-small>` copies a manually-downloaded model into the cache. The model is identified by its config hash; once present, `tt init` skips the download step.
- **Skip vectors entirely**: `tt config set embeddings.provider none` disables vectors. `memory.recall` runs with BM25 + temporal (+ graph if requested). Returns valid results.

### 8.3 API providers

Users can configure a remote embedding provider:

```
tt config set embeddings.provider openai --model text-embedding-3-small
```

The CLI prompts for the API key and stores it in the OS keyring (via `keyring` library). The key is **never** stored in the database, **never** stored in plaintext config, and **never** logged. Each call sends `body` (and optionally `title`) to the provider; the response embedding is persisted.

This is the only path in trade-trace that makes outbound network calls. It is opt-in and explicit. The default install remains fully local.

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

- **`memory.retain(node_type, body, *, title?, tags?, meta?, confidence_base?, decay_rate_per_day?, edges?)`** — write a memory node. The `edges` parameter lets the caller specify outgoing edges in the same call so reflection-without-edges never happens.
- **`memory.recall(query?, context?, strategies?, k?, max_chars?, compact?, include_body?, include_provenance?, min_confidence?)`** — read with multi-strategy retrieval and context-budget shaping.
- **`memory.reflect(target, body, *, derived_from?, supports?, contradicts?, supersedes?, ...)`** — sugar over `retain(node_type=reflection, ...)` that auto-wires the `about` edge to `target`.
- **`memory.link(from, to, edge_type, *, weight?)`** — explicit edge creation between two existing endpoints. Validates endpoint kind and ID.

The `target` of a reflection can be:

- A specific decision (`decision_id`), position (`position_id`), instrument (`instrument_id`), playbook version (`playbook_version_id`), or signal (`signal_id`) — creates an `about` edge.
- A time period (`period: {start, end}`) or tag (`tag: "liquidity-ignored"`) — stored in reflection `meta_json` until/unless period/tag entities become first-class endpoints.

## 10. Reflection ergonomics

`memory.reflect(...)` automatically:

1. Creates the reflection node.
2. Creates an `about` edge to the target (for row-backed targets).
3. Optionally creates `derived_from` edges to specified observations.
4. Optionally creates `supersedes` edges to older reflection IDs.
5. Optionally creates `supports` / `contradicts` edges to other memory nodes.

This lets reflections accumulate naturally at every grain — per-trade, per-period, per-pattern — without the agent having to issue multiple write calls.

## 11. Hindsight comparison

We evaluated Vectorize.io's Hindsight as a potential dependency. The retrieval architecture (BM25 + vector + graph + temporal, RRF + reranker) is essentially identical to ours, and Hindsight is mature and MIT-licensed.

We chose to build because three product constraints are structurally incompatible with using Hindsight as a dependency:

| Concern | Hindsight | Trade Trace |
|---------|-----------|-------------|
| Storage | Postgres-primary; embedded mode is Postgres-the-process | Single SQLite file — load-bearing for air-gappable install and `cp`-able backup |
| Domain edges | `metadata: {...}` JSON blob for custom fields | Typed edges with endpoint-kind validation linking to decisions / outcomes / playbook versions / signals |
| Confidence | Generic recency + relevance | Calibration-aware (decay + supersession at MVP; edge-density at P1) — runs inside the ranker, not as a post-filter |

The Retain/Recall/Reflect public-surface naming mirrors Hindsight so that agents and developers familiar with one can move between systems with minimal context. The implementation is ours.

## 12. Open questions

1. **Edge weight semantics.** Edges carry an optional `weight` float. Should this feed the (P1) edge-density factor in §6? MVP behavior: ignore weight; treat all edges as `1.0`. Revisit when there's dogfood data.
2. **Dual-index during reindex.** §8.4 specifies eager reindex with user confirmation. Open: do we offer a transient "dual-index" mode that keeps old and new embeddings live until the user explicitly drops the old set? Probably P1; MVP is single-active-provider.
3. **Multi-modal memory.** Chart snapshots, screenshots, attached PDFs are out of MVP. Could be added later via a `source` kind with a multimodal embedding model.
4. **Token vs character budgets.** MVP uses `max_chars` (deterministic across tokenizers). If non-English content surfaces a tokenizer-awareness need, add `max_tokens` with explicit tokenizer choice in P1.
5. **Bundled-weights install extra.** `bge-small-en-v1.5` ships as a lazy download. If genuinely air-gapped installs become a common ask, a `pip install trade-trace[vectors-bundled]` extra that includes the weights in the wheel can follow.

---

## Appendix: changes from v1 (same date)

- **Node taxonomy: 5 → 3.** `semantic_claim` collapses into reflection-with-slow-decay (a `decay_rate_per_day` choice, not a type). `coach_signal` moves out of `memory_nodes` into a separate `signals` table because its author and lifecycle differ.
- **Edge taxonomy: 10 → 7.** `links`, `retracts`, `tombstones` deferred until a concrete use case.
- **Confidence model simplified.** Edge-density factor deferred to P1; MVP is decay + supersession only. The factor's coefficients need real dogfood data, not theory.
- **Embeddings made default-on.** Local model (`bge-small-en-v1.5`) downloaded on first init. API provider configurable. Re-embed on provider change is explicit and eager. Air-gapped install paths documented.
- **Graph retriever moved from default to opt-in.** Edge populations are sparse at MVP; graph relevance pays off later. Strategy flag exists from day one.

The PRD (§3.2 schema rows, §4.1 API list, §11 open questions) and `persistence.md` (memory tables) will need a follow-up alignment pass — those edits are out of scope for this doc.
