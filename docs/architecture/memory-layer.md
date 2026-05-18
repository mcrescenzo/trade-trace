# Memory Layer — Architecture Note

**Date:** 2026-05-18
**Status:** Refined draft
**Parent:** [`../../PRD.md`](../../PRD.md) §5 & §4.2

This note details the memory layer's node taxonomy, edge semantics, retrieval strategies, and confidence model. The PRD owns the schema rows; this doc owns the semantic intent.

## 1. Goals

The memory layer turns a passive trade ledger into an active knowledge graph the agent can think with. Three concrete capabilities:

1. **Recall**: when an agent forms a new thesis on instrument X, surface relevant past observations, reflections, and playbook rules.
2. **Reflect**: when an outcome resolves or a `coach` signal fires, store the agent's synthesis as a typed memory node linked to the ledger rows that motivated it.
3. **Evolve**: when reflections accumulate, allow the agent to codify them as versioned playbook rules whose adherence and override outcomes are tracked.

It is **not** a generic agent memory framework. The schema is trading-shaped: every node can link to ledger rows; confidence decays with calibration awareness; recall can scope to instrument / venue / asset class / market type.

## 2. Node taxonomy

There are five `node_type` values. Each has type-specific `meta_json` and default `decay_rate_per_day`.

### 2.1 `observation`

A point-in-time record of something the agent noticed about a market, instrument, or pattern. Episodic.

- **Examples**: "Polymarket markets with < $5K ADV around resolution dates show 40bps wider spreads"; "NVDA gapped up 8% post-earnings and faded 4% within the first hour for the third quarter in a row".
- **Required meta**: at least one scoping field — `instrument_id`, `venue_id`, `asset_class`, or `pattern_kind`.
- **Decay default**: 0.003 per day (half-life ~230 days). Episodic observations age, but slowly.

### 2.2 `semantic_claim`

A generalized claim about the world, derived from one or more observations. Less time-stamped, more "what I believe is true".

- **Examples**: "Thin-liquidity prediction markets near resolution are systematically mispriced by ~5%"; "Earnings gap-fades have ~60% hit rate in semis but not in financials".
- **Required meta**: `scope` (market_type, venue, asset_class, general) and optionally `scope_value`.
- **Decay default**: 0.001 per day (half-life ~700 days). Beliefs fade slower than observations.
- **Edges**: typically `derived_from` one or more observations.

### 2.3 `reflection`

A retrospective synthesis written by the agent after a decision, position, period, or `coach` invocation. Subjective.

- **Examples**: "I overweighted the spread compression thesis here and ignored that the liquidity profile didn't match my prior pattern"; "Three skips this week were all driven by `liquidity-ignored` worry that turned out to be correct — keep doing this".
- **Required meta**: `target_kind`, `target_id`. Optional: `mistake_tags`, `strength_tags`.
- **Decay default**: 0.002 per day (half-life ~350 days). Reflections live in the middle.
- **Edges**: always at least one `about` edge to the target; optionally `derived_from` edges to observations / claims; optionally `supersedes` edges to older reflections.

### 2.4 `playbook_rule`

A codified rule belonging to a specific `playbook_version`. Procedural.

- **Examples**: "Do not enter prediction-market positions when spread > 8% of expected edge"; "Require 2x base liquidity for any entry within 7 days of resolution".
- **Required meta**: `playbook_version_id` and `rule_meta` (`trigger_kind`, `applicable_decision_types`, optional `applicable_asset_classes`).
- **`rule_body`** lives in the node's `body` field as free text — the agent reads this when reasoning. `rule_meta` is the machine-checkable shape used for override detection.
- **Decay default**: 0.0 (rules don't decay; they are superseded by new versions).
- **Edges**: `derived_from` → reflection that motivated the rule; `supersedes` → prior version of this rule.

### 2.5 `coach_signal`

System-emitted notification of a notable event. The system writes these; the agent reads (and may reflect on) them.

- **Examples**: "Calibration drift in `high` bucket: expected 0.85, realized 0.62 (n=14)"; "Rule `no-thin-markets` overridden 3 times in 14 days with negative aggregate outcome".
- **Required meta**: `signal_kind`, `severity` (info / warn / critical), `related_ledger_refs[]`.
- **Decay default**: 0.05 per day (half-life ~14 days). Signals are time-bounded; old signals should fall out of recall quickly unless reflected upon.
- **Edges**: `about` edges to the ledger rows that triggered the signal.

## 3. Edge taxonomy

Edges are typed and asymmetric. They live in the `edges` table connecting any memory node to any other memory node *or* to any ledger row (decision, thesis, forecast, outcome, position, snapshot, review, playbook_version, source).

| Edge type | Direction | Semantics |
|-----------|-----------|-----------|
| `about` | reflection / coach_signal → target | "this memory is about this target" |
| `derived_from` | child → parent | "this memory was synthesized from these inputs" |
| `supports` | A → B | "A provides positive evidence for B" |
| `contradicts` | A → B | "A provides negative evidence for B" |
| `supersedes` | new → old | "new replaces old; old is still readable but discounted at recall" |
| `links` | A → B | weakly related, no semantic claim |
| `violates` | decision → rule | "this decision overrode this rule" |
| `follows` | decision → rule | "this decision was consistent with this rule" |

Edges are append-only. "Removing" an edge means adding a `contradicts` edge or a `supersedes` edge that establishes new state without rewriting history.

## 4. Multi-strategy retrieval

`memory.recall(query | context, strategies, k)` runs each enabled strategy and combines scores via weighted rank fusion.

### 4.1 `SEMANTIC`

Vector similarity using `sqlite-vec`. Query is embedded; nodes ranked by cosine similarity to query embedding. When `context` is a ledger ref (e.g., a decision_id), the context's natural-language summary is built from the linked thesis body, instrument title, and recent observations, then embedded.

### 4.2 `BM25`

SQLite FTS5 keyword search over `title` and `body`. Useful when the query has specific terms (tag names, instrument symbols) that semantic search may smooth out.

### 4.3 `TEMPORAL`

Recency boost — nodes are scored by `exp(-age_days * temporal_decay)`. Combined with other strategies as a weight, not as a standalone retriever.

### 4.4 `GRAPH`

Breadth-first traversal from the context node (when `context` is supplied), following edges up to a configurable depth (default 2). Edge types can be filtered (e.g., only `about`, `derived_from`, `supports`). Useful for "show me everything connected to this position".

### 4.5 Combination

Each retriever returns a ranked list with normalized scores in `[0, 1]`. The combiner uses Reciprocal Rank Fusion by default:

```
score(node) = sum over strategies of (weight_s / (k + rank_s(node)))
```

with `k = 60` (RRF standard) and configurable per-strategy weights. The combined ranking is then filtered by `min_confidence` (after applying the decay/edge-density confidence model — see §5).

## 5. Confidence and decay model

Every memory node carries `confidence_base` (set at write, default 1.0) and `decay_rate_per_day` (default by `node_type`). At recall time, the node's *effective* confidence is computed as:

```
age_days = (now - created_at).days
decayed = confidence_base * exp(-decay_rate_per_day * age_days)
edge_density_factor = log(1 + supporting_edges) - log(1 + contradicting_edges)
effective = clamp(decayed * (1 + 0.1 * edge_density_factor) * supersession_discount, 0, 1)
```

Where:
- `supporting_edges` is the count of incoming `supports` edges.
- `contradicting_edges` is the count of incoming `contradicts` edges.
- `supersession_discount = 0.25` if any `supersedes` edge points to this node from a newer node, else `1.0`.

The constants (`0.1` edge-density coefficient, `0.25` supersession discount) are tunable via config and should be calibrated against dogfood data, not picked from theory.

**Properties this model achieves:**
- Old memories don't disappear, they fade.
- Evidence accumulation (supporting edges) keeps load-bearing memories prominent.
- Contradictions discount without deletion.
- Superseded memories are still recallable for audit but rarely surface in top-k.
- `coach_signal` nodes decay fast (high `decay_rate_per_day`) so old signals don't clutter recall.

## 6. Reflection ergonomics

`memory.reflect(target, insight, ...)` is sugar over `retain(node_type=reflection, ...)` that:

1. Creates the reflection node.
2. Automatically creates an `about` edge to the target.
3. Optionally creates `derived_from` edges to specified observations / claims.
4. Optionally creates `supersedes` edges to older reflection IDs.
5. Optionally creates `supports` / `contradicts` edges to specified other memory nodes.

The `target` can be any of:
- A specific decision (`decision_id`)
- A specific position (`position_id`)
- A specific instrument (`instrument_id`)
- A time period (`period: {start, end}`)
- A specific tag (`tag: "liquidity-ignored"`)
- A specific playbook version (`playbook_version_id`)
- A specific coach signal (`coach_signal_id`)

This lets reflections accumulate naturally at every grain — per-trade, per-period, per-pattern.

## 7. Hindsight comparison

Trade Trace's Retain/Recall/Reflect surface deliberately mirrors Vectorize.io's Hindsight so that:

- Agents familiar with Hindsight can use Trade Trace's memory API with minimal context.
- The Hindsight surface is general; the Trade Trace implementation is specialized.

Where Trade Trace diverges:

| Concern | Hindsight | Trade Trace |
|---------|-----------|-------------|
| Domain | General agent memory | Trading-specific |
| Node types | Facts, experiences, entity summaries, beliefs | observation, semantic_claim, reflection, playbook_rule, coach_signal |
| Edges to ledger | N/A (no domain ledger) | First-class: edges connect memory to decisions / outcomes / positions |
| Outcome awareness | No | Yes — calibration-aware confidence; auto-scored forecasts |
| Provenance for rules | N/A | playbook_version_id + provenance edges |
| Storage | Pluggable | SQLite + sqlite-vec + FTS5 (single file) |
| Decay | Temporal | Temporal + edge-density + supersession |

Trade Trace does not import Hindsight as a dependency. The shape is compatible; the implementation is ours.

## 8. Open questions

1. **Embedding reembed on model change**: lazy or eager? P1 concern.
2. **Recall budget shaping**: should `recall` accept a `max_total_tokens` budget and prune body content to fit? Probably yes in P1.
3. **Edge weight semantics**: edges carry an optional `weight` float. Should this weight feed into the edge-density factor? Default behavior in MVP: ignore weight (treat all edges as weight 1.0). Revisit when dogfood data exists.
4. **Multi-modal memory**: chart snapshots, screenshots, attached PDFs? Out of MVP scope; could be added later as a `source` kind with embedding via a multimodal model.
