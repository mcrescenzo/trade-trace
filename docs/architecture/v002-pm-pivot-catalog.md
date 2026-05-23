# v0.0.2 PM-pivot tool/report catalog reconciliation

> Status: **decision document for trade-trace-sx4n** (findings + recommendation).
> No code changes in this document — the implementation lands across the
> v0.0.2 program beads (`bd list --all --label v002-pm-pivot --flat --limit 0`).

## Why this exists

`next-steps.md` declares three different tool-count baselines —
**81**, **84**, and **45** target — across Parts I, II, and XV.
`tests/security/test_mvp_boundary_audit.py` pins **28** report tools
but is silent on the rest of the catalog. The runtime registry today
reports **89** tools, **28** of which are reports. Until those
numbers stop contradicting each other, every downstream implementation
bead has to re-do the audit before it can write the FOLD/KILL/RENAME
patches.

This doc pins the **authoritative runtime baseline** (Section 1),
maps every shipped tool to its v0.0.2 disposition (Section 2),
collapses the unresolved-resolution semantics that next-steps.md
defaulted (Section 3), and writes the one-line transport contract
(`meta.legacy_name`, error envelopes for killed tools, etc.) the
catalog/transport gate (trade-trace-lznx) will enforce
(Section 4).

It does **not** rewrite next-steps.md or move existing docs; it
supersedes the disagreement between them by being the single
authoritative source the v0.0.2 implementation beads cite.

---

## 1. Runtime baseline (2026-05-23)

Generated from `default_registry().names()`:

| Family | Count | Tools |
|---|---:|---|
| `agent`            |  2 | `agent.bootstrap`, `agent.next_actions` *(aliases — see §1.1)* |
| `decision`         |  2 | `decision.add`, `decision.record_adherence` |
| `export`           |  1 | `export.drain` |
| `forecast`         |  2 | `forecast.add`, `forecast.supersede` |
| `idea`             |  1 | `idea.capture` |
| `import`           |  3 | `import.commit`, `import.csv_fills`, `import.validate` |
| `instrument`       |  1 | `instrument.add` |
| `journal`          | 12 | `journal.backup`, `journal.bundle.plan`, `journal.bundle.status`, `journal.config_set`, `journal.fixture_seed`, `journal.init`, `journal.rebuild_projections`, `journal.repair`, `journal.rescan_scoring`, `journal.restore`, `journal.schema`, `journal.status` |
| `keyring`          |  1 | `keyring.revoke` |
| `market`           |  2 | `market.scan.dry_run`, `market.scan.promote` |
| `memory`           |  5 | `memory.link`, `memory.recall`, `memory.reflect`, `memory.reindex`, `memory.retain` |
| `model`            |  2 | `model.import`, `model.warm` |
| `outcome`          |  1 | `outcome.add` |
| `playbook`         |  6 | `playbook.adherence`, `playbook.create`, `playbook.list`, `playbook.list_versions`, `playbook.propose_version`, `playbook.show` |
| `reflection`       |  1 | `reflection.prompt_for_outcome` |
| `replay`           |  2 | `replay.case_bundle`, `replay.evaluate_output` |
| `report`           | 28 | *(see §1.2)* |
| `resolve`          |  2 | `resolve.pending`, `resolve.record` *(aliases — see §1.1)* |
| `review`           |  1 | `review.bundle` |
| `signal`           |  1 | `signal.scan` |
| `snapshot`         |  1 | `snapshot.add` |
| `source`           |  5 | `source.add`, `source.attach_to_decision`, `source.attach_to_forecast`, `source.attach_to_memory_node`, `source.attach_to_thesis` |
| `strategy`         |  4 | `strategy.create`, `strategy.list`, `strategy.show`, `strategy.update` |
| `thesis`           |  1 | `thesis.add` |
| `tool`             |  1 | `tool.schema` |
| `venue`            |  1 | `venue.add` |
| **Total**          | **89** | |

### 1.1 Why 89 and not 84

next-steps.md Part II AUDIT 2026-05-22 reports **84** based on a
literal count of `registry.register(...)` call sites. That count was
correct for that moment but missed:

- **2 alias namespaces** that share a handler with the canonical
  surface and were counted as one tool in the audit:
  `agent.bootstrap` (→ `report.bootstrap`), `agent.next_actions`
  (→ `report.work_queue`), `resolve.record` (→ `outcome.add`), and
  `playbook.adherence` (→ `report.playbook_adherence`). The runtime
  enumerates each name separately because each is a distinct CLI
  invocation. Three of those four are KILLed under §2; `resolve.record`
  goes when `outcome.add → resolution.add` lands.
- **`report.policy_candidates`** (commit `e25c0b9`, 2026-05-23): one
  net-new report ships in `report.*`.
- **`replay.evaluate_output`** likewise was registered after the
  audit snapshot.

The "84" number in next-steps.md is therefore stale; this document
authoritatively replaces it with **89**, and the v0.0.2 net-reduction
target accordingly becomes **89 → 45 (-44 tools, ≈49 % reduction)**
rather than the previously published 84 → 45 (-39, ≈46 %).

### 1.2 Shipped reports (28)

Pinned by `SHIPPED_REPORTS` in
`tests/security/test_mvp_boundary_audit.py`. The 28 names below are
authoritative; any addition must update that pin and this doc in the
same commit.

`report.audit_readiness`, `report.bootstrap`, `report.calibration`,
`report.calibration_integrity`, `report.coach`, `report.compare`,
`report.current_exposure`, `report.decision_velocity`,
`report.exposure_anomalies`, `report.filter_schema`,
`report.forecast_diagnostics`, `report.lifecycle`,
`report.memory_usefulness`, `report.mistakes`, `report.open_positions`,
`report.opportunity`, `report.playbook_adherence`, `report.pnl`,
`report.policy_candidates`, `report.recall_receipts`, `report.risk`,
`report.source_quality`, `report.strategy_health`,
`report.strategy_performance`, `report.strengths`,
`report.unscored_forecasts`, `report.watchlist`, `report.work_queue`.

---

## 2. Old → new disposition (89 → 45)

Each row pins the v0.0.2 outcome for one runtime tool. Dispositions
are exactly one of **KEEP**, **RENAME**, **FOLD**, **KILL**, or
**NEW**. The `New surface` column names the tool the agent will
call once v0.0.2 ships.

### 2.1 KEEP (15 — verbatim or sharpened)

| Runtime tool | Disposition | New surface | Notes |
|---|---|---|---|
| `journal.init`              | KEEP | `journal.init` | unchanged |
| `journal.status`            | KEEP+ | `journal.status` | adds `adapter` + `cached_markets_count` sections per next-steps.md Part XVI |
| `journal.schema`            | KEEP | `journal.schema` | unchanged |
| `journal.config_set`        | KEEP+ | `journal.config_set` | adds `network.polymarket.*` keys |
| `journal.fixture_seed`      | KEEP+ | `journal.fixture_seed` | rewritten to Polymarket-shaped fixtures (j8g8) |
| `journal.backup`            | KEEP | `journal.backup` | unchanged; SHA-256 manifest retained |
| `journal.restore`           | KEEP | `journal.restore` | unchanged |
| `memory.retain`             | KEEP | `memory.retain` | unchanged; ONNX embeddings under the hood |
| `memory.reflect`            | KEEP | `memory.reflect` | unchanged |
| `memory.link`               | KEEP | `memory.link` | unchanged |
| `memory.recall`             | KEEP | `memory.recall` | unchanged |
| `tool.schema`               | KEEP | `tool.schema` | unchanged |
| `export.drain`              | KEEP | `export.drain` | unchanged |
| `review.bundle`             | KEEP | `review.bundle` | unchanged |
| `replay.case_bundle`        | KEEP | `replay.case_bundle` | unchanged |
| `replay.evaluate_output`    | KEEP | `replay.evaluate_output` | unchanged (post-audit registration) |

### 2.2 RENAME (2 — `meta.legacy_name` carries the old surface)

| Old | New | Notes |
|---|---|---|
| `outcome.add`                | `resolution.add`               | per next-steps.md §VI; `meta.legacy_name=outcome.add` on the new surface for one minor cycle, then dropped |
| `decision.record_adherence`  | `playbook.record_adherence`    | namespace consistency; same handler, same idempotency_key shape |

The dispatcher emits a typed `NOT_FOUND` envelope on the old name
once the rename lands, with `details.renamed_to=<new>` so the agent
gets a deterministic correction instead of a silent failure.

### 2.3 FOLD (18 — handler stays, surface collapses)

| Old | Folded into | Notes |
|---|---|---|
| `venue.add`                  | `market.bind`                | venue/instrument become market metadata fields |
| `instrument.add`             | `market.bind`                | ↑ |
| `thesis.add`                 | `forecast.add.rationale_body`| `theses` table dropped (qmmd/4lki) |
| `forecast.supersede`         | `forecast.add.supersedes_forecast_id` | edge edge — same write path |
| `source.add`                 | *dropped* — sources move into `metadata_json.sources` array | `sources` table dropped |
| `source.attach_to_thesis`    | ↑ | ditto |
| `source.attach_to_decision`  | ↑ | ditto |
| `source.attach_to_forecast`  | ↑ | ditto |
| `source.attach_to_memory_node` | ↑ | ditto |
| `strategy.create`            | `strategy.upsert`            | list via `report.strategy_health` |
| `strategy.update`            | `strategy.upsert`            | ↑ |
| `strategy.list`              | `report.strategy_health`     | ↑ |
| `strategy.show`              | `report.strategy_health`     | ↑ |
| `playbook.create`            | `playbook.upsert`            | rationalize playbook surface to upsert |
| `playbook.show`              | `playbook.upsert` *(read mode)* | ↑ |
| `playbook.list`              | `playbook.upsert` *(read mode)* | ↑ |
| `playbook.list_versions`     | `playbook.upsert` *(read mode)* | ↑ |
| `import.validate`            | `import.commit._dry_run`     | one tool, two modes |
| `journal.rescan_scoring`     | `journal.rebuild_projections`| one rebuild path |

### 2.4 KILL (15 — surface removed, capability dropped or implicit)

| Killed tool | Reason | Caller redirect |
|---|---|---|
| `agent.bootstrap`              | alias of `report.bootstrap` | `report.bootstrap` |
| `agent.next_actions`           | alias of `report.work_queue` | `report.work_queue` |
| `playbook.adherence`           | alias of `report.playbook_adherence` | `report.playbook_adherence` |
| `resolve.record`               | alias of `outcome.add` (and target is renamed) | `resolution.add` |
| `resolve.pending`              | duplicated by `report.work_queue` | `report.work_queue` |
| `idea.capture`                 | subsumed by `memory.retain` | `memory.retain` |
| `market.scan.dry_run`          | replaced by `market.bind` + adapter | `market.bind` |
| `market.scan.promote`          | ↑ | `market.bind` |
| `journal.bundle.plan`          | replaced by adapter | none — capability dropped |
| `journal.bundle.status`        | ↑ | none |
| `reflection.prompt_for_outcome`| prompt assembly belongs to the agent, not the journal | none |
| `import.csv_fills`             | JSONL-only via `import.commit` | `import.commit` |
| `memory.reindex`               | cosmetic; no embeddings-provider switching under v0.0.2 | none |
| `model.import`                 | replaced by inline ONNX runtime | none |
| `model.warm`                   | ↑ | none |
| `keyring.revoke`               | no embeddings provider keys in v0.0.2 | none |

Killed tools must surface a typed `UNSUPPORTED_CAPABILITY` envelope
(not `NOT_FOUND`) when called, with `details.redirect=<new surface or
null>` and `details.removed_in="0.0.2"`. The dispatcher learns to
emit this from a small redirect table; the CLI surfaces the same
envelope through the existing `_emit_cli_error` path.

### 2.5 Admin-only (3 — kept, gated)

| Tool | Notes |
|---|---|
| `signal.scan`                  | only one signal kind; flagged admin-only in the MCP listing |
| `journal.rebuild_projections`  | admin maintenance |
| `journal.repair`               | admin maintenance |

These remain registered but the catalog/transport surface marks them
`is_admin=True` so an MCP client filtering for the default catalog
omits them. They count against the v0.0.2 total of 45.

### 2.6 NEW (6 adapter primitives + 1 forecast anchor)

| New tool | Purpose | Default network behavior |
|---|---|---|
| `market.bind(external_id, source)`           | fetch/cache market metadata; idempotent; populates `markets.*_at` state columns | adapter-only; disabled by default |
| `market.refresh(market_id)`                  | re-fetch state for a bound market | adapter-only; disabled by default |
| `snapshot.fetch(market_id, at=now)`          | capture live implied probability | adapter-only; falls back to `snapshot.add` (manual) when disabled |
| `snapshot.fetch_series(market_id, from, to)` | capture trajectory series for `report.time_decay_sharpening` and `report.calibration_anchored` baselines | adapter-only; **no background scheduler** (see §3.3); falls back to manual `snapshot.add` loop when disabled |
| `outcome.fetch(market_id)`                   | ingest on-chain resolution | adapter-only; **no background scheduler**; manual `resolution.add` is always available |
| `forecast.anchor_to_snapshot(forecast_id, snapshot_id)` | post-hoc anchor for `report.calibration_anchored`; idempotent; corrections via `supersedes_forecast_id` | local-only |

### 2.7 Report consolidation (28 → 13)

next-steps.md Part II §"Report Consolidation" carries the
authoritative mapping. This doc adopts that mapping verbatim and
adds one row: **`report.policy_candidates`** (shipped 2026-05-23)
is **KEEP**ed unchanged — it is a P2 read-only memory-evidence
surface and does not duplicate any consolidation target.

| New surface | Consolidates / status |
|---|---|
| `report.calibration`              | `calibration` + `calibration_integrity` (nested as sections) |
| `report.calibration_anchored`     | NEW (§3.1) |
| `report.calibration_terminal`     | NEW (§3.2) |
| `report.forecast_diagnostics`     | unchanged |
| `report.book`                     | `pnl` + `open_positions` + `current_exposure` + `exposure_anomalies` + `watchlist` |
| `report.risk`                     | unchanged |
| `report.audit`                    | `audit_readiness` + `source_quality` + `playbook_adherence` |
| `report.lifecycle`                | unchanged |
| `report.recall`                   | `recall_receipts` + `memory_usefulness` (per-item) |
| `report.work_queue`               | unchanged + `decision_velocity` fold |
| `report.bootstrap`                | composer over the above |
| `report.coach`                    | narrowed (forbidden-phrase gate retained) |
| `report.strategy_health`          | absorbs `strategy_performance` |
| `report.compare`                  | unchanged |
| `report.policy_candidates`        | KEEP (post-audit addition) |
| `report.market_lifecycle`         | NEW (PM-native) |
| `report.resolution_quality`       | NEW (PM-native) |
| `report.amm_slippage`             | NEW (PM-native) |
| `report.time_decay_sharpening`    | NEW (PM-native) |

Killed reports: `mistakes`, `strengths`, `opportunity`,
`unscored_forecasts`, `decision_velocity` (fold), `pnl`,
`watchlist`, `open_positions`, `current_exposure`,
`exposure_anomalies`, `audit_readiness`, `source_quality`,
`playbook_adherence`, `strategy_performance`, `memory_usefulness`,
`calibration_integrity` (fold), `recall_receipts`,
`filter_schema` (introspect via `tool.schema`).

That comes out to **13 KEEP/consolidated + 4 NEW PM-native + 2
NEW anchored/terminal = 19** report surfaces — close to but not
equal to the prior "13" copy. The prior count predates
`report.policy_candidates`, `report.calibration_terminal`, and the
explicit split of anchored vs unchanged.

### 2.8 Headline totals

The 45-tool target previously published assumed 13 reports. Once
the post-audit additions are absorbed, the v0.0.2 catalog lands at:

- Journal + backup/restore: **5 KEEP + 3 admin-only = 8**
- Memory: **4 KEEP**
- Market/forecast/resolution write surface: **8** (`market.bind`,
  `market.refresh`, `snapshot.add`, `snapshot.fetch`,
  `snapshot.fetch_series`, `outcome.fetch`, `resolution.add`,
  `forecast.add`)
- Strategy/playbook: **2** (`strategy.upsert`, `playbook.upsert`)
- Adherence: **1** (`playbook.record_adherence`)
- Forecast anchor: **1** (`forecast.anchor_to_snapshot`)
- Decision: **1** (`decision.add`)
- Import/export: **2** (`import.commit`, `export.drain`)
- Review/replay: **3** (`review.bundle`, `replay.case_bundle`,
  `replay.evaluate_output`)
- Reports: **19** (per §2.7)
- Tools: **1** (`tool.schema`)
- Signals: **1** admin-only

**Total: 50 surfaces (47 default + 3 admin-only).**

The "45" figure in next-steps.md was a target *before* the
`report.policy_candidates` ship, the explicit
`report.calibration_terminal` split, and the
`forecast.anchor_to_snapshot` separation. The pragmatic target is
**~50**; the previously published "45" is now a *floor*, not a
hard contract.

---

## 3. Unresolved-resolution defaults

next-steps.md flagged five decisions as "defaulted". This section
pins the default so downstream beads can rely on it without
re-deriving.

### 3.1 `report.calibration_anchored` semantics

**Decision:** Anchored calibration is computed over forecasts that
have a `forecast.anchor_to_snapshot` edge. The baseline is the
snapshot's implied probability at anchor time; skill is reported as
agent — market in probability units, **not in P&L units**. The
absence of an anchor produces a `coverage.unanchored_count` row in
the diagnostics panel, not an error.

### 3.2 `report.calibration_terminal` semantics

**Decision:** Terminal calibration uses the market's
`closed_for_trading_at` snapshot (or last snapshot before
`resolved_at` when the cleaner field is missing) as baseline.
Markets without a terminal snapshot produce a
`coverage.no_terminal_snapshot_count` row. Output shape is
*identical* to `report.calibration_anchored` so the agent can switch
baselines without changing its parser. Implemented as a thin variant
of the anchored handler.

### 3.3 No background outcome fetching

**Decision:** v0.0.2 ships **no scheduler, no daemon, no background
worker** of any kind. `outcome.fetch` and `snapshot.fetch_series`
are agent-driven explicit calls. The journal does not auto-fetch
on idle, on dispatch, or on `journal.init`. This preserves the
local-first / no-network-by-default product invariant and keeps the
adapter's failure mode confined to the explicit call site.

If the agent wants periodic refresh, it owns that loop and surfaces
the cadence in its own logs — `tt market refresh ...` over a cron
on the agent's host is fine; auto-refresh inside trade-trace is
not.

### 3.4 Manual `market.bind` metadata shape

**Decision:** A `market.bind` call with no adapter (manual mode)
requires the caller to supply every non-generated, non-null column
on the `markets` table explicitly. The handler does **not** guess
or interpolate `resolution_rule_text`,
`closed_for_trading_at`, etc. Missing required fields raise
`VALIDATION_ERROR` with `details.required_fields=[…]`. This keeps
manual binds honest about provenance and prevents agents from
inventing market semantics by omission.

### 3.5 Legacy 0.0.1rc3 import behavior

**Decision:** `import.commit` against a 0.0.1rc3-shaped JSONL bundle
fails with `UNSUPPORTED_CAPABILITY` (not `STORAGE_ERROR`) carrying
`details.reason="legacy_format"`,
`details.detected_version="0.0.1rc3"`, and
`details.transform_required=true`. A separate transform tool — if
ever shipped — lives outside the v0.0.2 surface and is approved as
its own bead. Users with 0.0.1rc3 bundles re-import from their
upstream source (the producing agent's logs / broker exports), which
they generally still have because there is no 0.0.1 stable cut.

---

## 4. Transport contract for the catalog/transport gate

These pin the boundary that the catalog/transport gate
(`trade-trace-lznx`) verifies before adapter/report work proceeds.

### 4.1 `meta.legacy_name` on renamed tools

When the agent calls `resolution.add` or
`playbook.record_adherence`, the success envelope carries
`meta.legacy_name = "outcome.add"` /
`meta.legacy_name = "decision.record_adherence"` for one minor cycle
(the v0.0.2 series). Drop the field at v0.0.3.

### 4.2 `NOT_FOUND` on old names after rename

Calling `outcome.add` post-rename surfaces `NOT_FOUND` with
`details.renamed_to = "resolution.add"`. The agent gets a
deterministic correction it can apply without a docs round-trip.

### 4.3 `UNSUPPORTED_CAPABILITY` on killed tools

Killed tools surface `UNSUPPORTED_CAPABILITY` (not `NOT_FOUND`) with
`details.removed_in = "0.0.2"` and `details.redirect = <new surface
or null>`. Distinguishes a renamed tool from a removed one.

### 4.4 `MCP_tool_specs` filter for admin-only

`mcp_tool_specs()` accepts a new `include_admin: bool = False`
keyword. The default surface a normal agent sees omits the three
admin-only tools (`signal.scan`,
`journal.rebuild_projections`, `journal.repair`). The stdio server
honors a `MCP_INCLUDE_ADMIN=1` env opt-in (per `MCP_ACTOR_ID`
precedent).

### 4.5 Boundary-audit pin

The first commit that lands a v0.0.2 tool change updates
`tests/security/test_mvp_boundary_audit.py` so the shipped tool set
matches §2 above, and adds a new `SHIPPED_TOOLS` pin alongside the
existing `SHIPPED_REPORTS` pin. Subsequent beads either flip an
entry in that pin or surface a typed envelope that the catalog/
transport gate rejects.

---

## 5. Verification

```sh
# 1. Runtime baseline count (sanity check on this doc)
PYTHONPATH=src python -c \
  "from trade_trace.core import default_registry; \
   print(len(default_registry().names()))"
# Expected: 89

# 2. Shipped reports pinned set
pytest tests/security/test_mvp_boundary_audit.py::test_shipped_report_tool_set_is_locked -q
# Expected: 1 passed

# 3. Section 2 disposition counts match the runtime baseline
# (15 KEEP + 2 RENAME + 18 FOLD + 15 KILL + 3 admin-only-kept + 28 reports
# - 1 report covered above (policy_candidates) = 89 dispositioned)
```

---

## 6. Out of scope

- Implementing any catalog change (handled in
  trade-trace-rooi, trade-trace-pcxf, trade-trace-t97r, and the
  schema/adapter implementation clusters).
- Polymarket adapter implementation (trade-trace-mmze,
  trade-trace-2h0g).
- The `markets.*_at` migration (trade-trace-qmmd).
- HITL live-adapter smoke (trade-trace-6i38).
- Public release actions (trade-trace-voum,
  trade-trace-3l6w).
