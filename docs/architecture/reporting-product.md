# Reporting product architecture

> Status: **decision document for trade-trace-gtep**

This document locks the executable architecture for the Console
reporting product overhaul (EPIC [trade-trace-3o4a]). Every defaulted
decision listed below is **resolved** — downstream foundation and UI
beads proceed from these decisions without further product input.

The audit it builds on lives at
`docs/audits/console-reporting-gap-map-20260520T033700Z.md`
(trade-trace-q6wj). Cross-link: the existing Console serve / read-only
threat model is in [`console.md`](./console.md); the report tool
catalog is in [`reports.md`](./reports.md).

## 1. Product boundary (locked, non-negotiable)

These constraints are inherited from PRD §2.4, §7 and VISION
"What this is NOT". They are restated here so dashboard / foundation
beads do not have to relitigate them:

1. **Local-first, package-shipped, read-only.** The product is a
   FastAPI-served React Console on `127.0.0.1` (or a user-supplied
   loopback host). It opens with the user's local journal — there is
   no remote mode, no multi-tenant mode, no auth surface.
2. **No broker, no execution.** Trade Trace never sends an order, a
   webhook, a broker API request, or any outbound credentialed request.
   This includes the reporting product.
3. **No market-data fetching.** The reporting product reads only the
   local journal projections + snapshots already in the database.
   It never queries an external venue, price feed, or news source.
4. **No outbound network from the Console process.** The single
   permitted outbound path (optional local embedding-model weight
   download, PRD §2.4) does NOT run from Console. Reporting must
   inherit the loopback-only socket guard from
   [`console.md`](./console.md) §Threat model. The CSP must remain
   `'self'` only — no CDN, no Google Fonts, no analytics, no remote
   chart bundles.
5. **No trade advice / no financial recommendations.** Per PRD §4.2
   and [`reports.md`](./reports.md), Console dashboards must not
   render synthesized "you should do X" copy. The `report.coach`
   forbidden-phrase gate (`tests/integration/test_report_coach.py`)
   stays in force; any Console rendering of coach output must inherit
   the gate's allowlist or skip the rendering.
6. **No frontend-only financial math.** Backend reports (`report.*`
   tools + `src/trade_trace/reports/*.py`) are the canonical source of
   every aggregate metric. The frontend renders server-provided numbers
   and never computes P&L, R-multiples, win rate, ECE, or any other
   finance/calibration aggregate in JavaScript. This rules out
   client-side filtering that changes a displayed metric — facets
   re-issue the report call, they do not recompute locally.

## 2. Canonical terminology (locked)

Beads, code, and Console copy must use these terms consistently.
Aliases that exist in the journal are listed for translation only.

| Term | Definition | Storage source | NOT to be confused with |
|---|---|---|---|
| **Decision** | An agent action recorded against an instrument (`actual_enter`, `paper_enter`, `add`, `reduce`, `actual_exit`, `paper_exit`, `watch`, `skip`, `hold`, `invalidate_thesis`, `update_thesis`, `resolved`, `review`). Append-only. | `decisions` table | Trades. A `watch`/`skip` is a decision but not a trade. |
| **Trade** | A decision with a non-zero quantity that opens, adds to, reduces, or closes a position (`actual_enter`, `paper_enter`, `add`, `reduce`, `actual_exit`, `paper_exit`). | `decisions` table filtered to trading-decision types | Decisions. `watch` is never a trade. |
| **Position** | The rebuildable projection of a (instrument, kind, side) cumulative exposure over time. | `positions` (projection) + `position_events` (source) | Decisions. A position is built from trades. |
| **Forecast** | A probability distribution attached to a thesis (binary, categorical, scalar). | `forecasts` table | Decisions. A decision may or may not be backed by a forecast. |
| **Outcome** | The realized result for an instrument at a resolution time (`resolved_final`, `resolved_provisional`, `void`, `cancelled`, `ambiguous`, `disputed`). | `outcomes` table | Forecast scores. The outcome is the truth; scores compare forecasts to it. |
| **Strategy** | A named, mutable-but-audited grouping of decisions/forecasts. Orthogonal to playbooks and tags; one strategy per decision (MVP). | `strategies` table + `strategy_id` on `decisions` | Tags. Strategies are first-class with their own slug/status; tags are free-form. |
| **Playbook version** | A specific revision of a procedural ruleset. Append-only. | `playbook_versions` + `decision_playbook_rules` for adherence | Strategies. A playbook is a procedure; a strategy is a thesis family. |
| **Thesis** | A narrative claim about an instrument that motivates one or more decisions/forecasts. | `theses` table | Decision reason. The reason is per-decision; the thesis is shared. |
| **Reflection** | An agent-authored memory node (typically `node_type='reflection'`) tied to a decision/forecast/outcome. | `memory_nodes` + edges | Sources. Reflection is the agent's hindsight; source is the supporting evidence. |
| **Source** | An external citation (article, document, dataset) attached to a thesis/decision/forecast/memory node. | `sources` + `source_*_attachments` | Reflections. |

Dashboard copy SHOULD prefer "Trade" when the row is restricted to
trading-decision types; "Decision" otherwise. Detail pages use the
storage-canonical noun (a position-detail page says "position", not
"trade").

Agent-facing current-exposure reports/tool schemas additionally follow
[`current-exposure-agent-contract.md`](./current-exposure-agent-contract.md):
open exposure is canonical only from `positions` backed by
`position_events`; decisions are activity/audit; `watch` decisions are
never positions; and actual-recorded decisions remain record-only unless
a corresponding position projection/event exists.

## 3. Page information architecture (shipped)

The React Console route catalog is now the source of truth. Primary
navigation contains the top-level routes below; nested `/reports/*`
routes are reachable from the Reports page/direct URLs. Logs and Raw JSON
are **not** primary-nav pages. Their audit role is covered by journal
event detail, raw payload views, `/api/console/logs`, and
`/api/console/raw/{event_id}`.

| Section | Page | Shipped behavior |
|---|---|---|
| **Dashboard** | Overview (`/`) | Local overview rollup over journal counts, P&L, risk, recent activity, and caveats. |
| **Trades / Positions** | All Trades (`/trades`) | Filterable position lifecycle rows by default, backed by `GET /api/console/positions`; `/trades?view=events` is the flat trade-typed decision-event audit escape hatch backed by `GET /api/console/trades`. Position detail is opened from position rows, not a primary-nav item. |
| **Reports** | Report Browser (`/reports`) | Safe report catalog with links into report pages and export packet affordances. |
| | Period / Edge Review (`/review`) | Local review surface over existing aggregates; packet-style backend contracts are deferred to trade-trace-2vq5. |
| | P&L (`/reports/pnl`) | Dashboard for `report.pnl`. |
| | Risk (`/reports/risk`) | Dashboard for `report.risk`. |
| | Performance (`/reports/performance`) | Decision velocity / performance timeline from current backend reports. |
| | Strategy performance (`/reports/strategy`) | Wraps strategy/playbook report data where present. |
| | Decision intelligence (`/reports/decisions`) | Watchlist / decision-intelligence surface using current report contracts. |
| | Process analytics (`/process`) | Local process signals where backend-local data exists; richer process contracts are deferred to trade-trace-4exy. |
| | Compare (`/reports/compare`) | Comparison report surface using `report.compare`. |
| | Calibration (`/calibration`) | Calibration and integrity rendering from backend report payloads. |
| | Evidence (`/evidence`) | Source quality / provenance analytics from backend report payloads. |
| **Reference tables** | Strategies (`/strategies`) | Paginated local strategy table. |
| | Playbooks (`/playbooks`) | Paginated local playbook table. |
| **Audit / inspection** | Journal (`/journal`) | Journal timeline/replay with event detail, related records, and raw payload access. |
| | Decisions (`/decisions`) | Paginated decision inspection. |

### 3.1 Reporting lane vs developer/audit lane (locked)

The IA separates the two reader audiences without making every audit
endpoint a nav destination:

- **Reporting lane**: Dashboard, Trades, Reports (P&L / Risk /
  Performance / Strategy / Decision intelligence / Calibration / Evidence).
  Optimized for the Tradervue-like reading experience.
- **Developer / audit lane**: Journal, event detail/raw payload,
  related-record drilldowns, Decisions, `/trades?view=events` trade
  decision-event rows, position detail, and local JSON endpoints for
  logs/raw. Optimized for inspection and provenance.

Top navigation lists shipped top-level pages from the shared route
catalog. `/integrity`, `/logs`, and `/raw` are not current React routes;
do not document them as primary pages unless the route catalog changes.

## 4. Metric glossary (locked)

Each Console dashboard MUST surface metrics by name from this
glossary; the help/explanation system (trade-trace-4nux) renders
copy keyed off these names. Definitions are pinned to the
implementations under `src/trade_trace/reports/`.

### 4.1 Trade / P&L metrics (`report.pnl`)

- **Realized P&L** — Closed-position cash result: Σ over closed
  position legs of `(exit_price − entry_price) × signed_quantity − fees`.
  Source: `positions.realized_pnl` (rebuilt projection).
- **Unrealized P&L** — Open-position mark-to-market: Σ over open
  positions with a current snapshot of `(mark_price − entry_price) ×
  signed_quantity`. Source: `positions.unrealized_pnl` (set during
  mark events).
- **Mark-to-market (MTM) P&L** — Realized + unrealized.
- **Open mark coverage** — Open positions with a current mark /
  total open positions. Surfaced in summary; <100% triggers a
  missing-mark caveat (see §6).
- **Closed position count / Open position count** — Cardinality
  per group.

### 4.2 Risk metrics (`report.risk`)

- **R-multiple (R)** — Per-decision realized return divided by the
  declared risk amount: `(exit_value − entry_value) / declared_risk_amount`.
  Source: risk-units.md §3.2. Decisions without `declared_risk_amount`
  are excluded from the aggregate and counted in caveats.
- **Mean / median R** — Aggregate over included decisions.
- **Expectancy in R** — `win_rate × avg_win_R + loss_rate × avg_loss_R`.
- **Win rate / Loss rate / Breakeven count** — Cardinality bands of
  the R distribution (`R > 0` / `R < 0` / `R == 0` within a tolerance).
- **Payoff ratio** — `avg_win_R / |avg_loss_R|` when both exist.
- **Best / Worst R** — Extremes of the R distribution.
- **Pending count (n_pending_with_risk)** — Decisions with declared
  risk but no close. Surfaced separately so a high pending count does
  not depress the aggregate silently.
- **R histogram** — Bins for the distribution chart.

### 4.3 Performance metrics (`bbww` read model + `ai45` page)

- **Equity curve** — Cumulative MTM P&L by time bucket (day default).
  Sourced from the canonical trade/position read model (trade-trace-bbww).
- **Drawdown** — Peak-to-trough decline of the equity curve; max
  drawdown and current drawdown surfaced.
- **Performance calendar** — Per-day realized + MTM P&L heatmap.
- **Bucket alignment** — All time buckets are UTC-aligned per
  `report.decision_velocity` precedent.

### 4.4 Calibration metrics (`report.calibration` + `report.calibration_integrity`)

- **Brier score** — `(p − outcome)²` averaged across scored binary
  forecasts. Lower is better.
- **Log score** — `−log(p)` if outcome=1 else `−log(1−p)`. Lower is
  better.
- **Expected Calibration Error (ECE)** — Equal-width 10-bin
  reliability gap, weighted by bin count.
- **Sharpness** — `Var(p)`; how confidently the agent forecasts.
- **Baseline / Skill** — Brier vs the base rate; positive = skilled.
- **Reliability bins** — 10 equal-width bins of forecasted probability
  vs realized rate, for the reliability diagram chart.
- **Integrity diagnostics** (six rates from `report.calibration_integrity`):
  `forecast_coverage`, `unsupported_rate`, `ambiguous_rate`,
  `disputed_rate`, `void_cancelled_rate`, `suspicious_late_rate`.
  Each surfaces as a caveat tile.

### 4.5 Decision intelligence metrics

- **Mistakes** — Tag-aggregated patterns ranked by mean Brier
  (worst first); from `report.mistakes`.
- **Strengths** — Mirror of mistakes (best first); from
  `report.strengths`.
- **Stale watches** — `watch` decisions older than
  `stale_threshold_days` (default 14); from `report.watchlist`
  mode `stale`.
- **Overdue watches** — `watch` decisions with `review_by <= now`;
  from `report.watchlist` (trade-trace-gbtj added the contract).
- **Unscored forecasts** — Forecasts past `resolution_at` with no
  resolved-final outcome; from `report.unscored_forecasts`.

### 4.6 Sample / data-quality caveats (locked)

A metric is **caveated** when any of the following is true; the
caveat system (trade-trace-oafl) MUST surface it as a first-class UI
element, not a footnote:

- `summary.sample_warning` is set (n < min_sample, default 20).
- A group's `groups[].sample_warning` is set.
- An integrity diagnostic above its alert threshold (calibration
  integrity rates default to 0.1).
- Open mark coverage <100%.
- Risk aggregate excludes decisions due to missing
  `declared_risk_amount`.
- Forecast scoring excludes late-recorded entries.
- The opportunity report's `data_coverage` flag is `sparse` or
  `missing`.

## 5. ReportFilter / global query-state contract (locked)

The global filter UI (trade-trace-hayy) MUST round-trip to canonical
`ReportFilter` JSON. Specifically:

1. **Single source of truth**: `ReportFilter`
   (`src/trade_trace/contracts/report_filter.py`) is the schema; the
   Console form MUST NOT add filter axes the server does not validate.
   New axes are added by extending `ReportFilter` first, then surfacing
   the field in the UI.
2. **URL state**: every dashboard URL encodes the active filter via a
   single query parameter `f=<base64url-json>` (base64url of the
   `ReportFilter` JSON; `{}` means no filter, omitted means default
   = no filter). The URL is the canonical share/bookmark surface; no
   server-side saved-filter feature ships in MVP.
3. **Empty payload semantics**: empty arrays / `null` / omitted fields
   mean "no filter on that axis"; the server is the source of truth
   for this per `ReportFilter` validation (`extra="forbid"`).
4. **Round-trip pin**: when the user opens a URL with `f=...`, the
   form renders the filter exactly; when the user changes the form,
   the URL updates to the new filter without dropping any field.
5. **Per-dashboard filter projection**: dashboards may restrict the
   surface they expose (e.g., a Calibration page omits irrelevant
   facets), but the URL state must remain valid `ReportFilter` JSON
   so the same URL works in other dashboards.
6. **No client-side recomputation**: filter changes always re-issue the
   relevant `report.*` call (per §1.6). Loading state must be visible.
7. **Filter facets ARE the available sub-filters**:
   `time_window`, `actors` (`actor_id`/`agent_id`/`model_id`/
   `environment`/`run_id`), `strategy` (`strategy_id` with the
   `__none__` sentinel; `playbook_id`; `playbook_version_id`),
   `instrument` (`venue_id`/`venue_kind`/`instrument_id`/`asset_class`/
   `symbol`), `decision` (`decision_type`/`side`/`tags_*`/`has_*`),
   `market_context` (`spread_bucket`/`liquidity_bucket`/`volume_bucket`/
   `market_regime_tag`), `outcome`
   (`resolution_status`/`scoring_state`/`score_*`/`include_late_recorded`),
   `source` (`source_kind`/`source_stance`/`source_freshness_before_decision`).

## 6. Report evidence / drilldown contract (locked)

Every aggregate metric rendered in the Console MUST link to evidence.
This rules out "trust me" tiles.

1. **Numbers come from `ReportResult`.** Every dashboard widget
   carries the originating `report.*` tool, the filter that produced
   the number, and the request_id. The widget renders an "Evidence"
   affordance that opens:
   - The raw `ReportResult.summary.metrics` and `groups[].metrics`
     as a table.
   - The `groups[].record_ids` lists (decisions, forecasts, outcomes,
     sources) as deep links into the corresponding detail pages.
   - The originating `tool.schema` info (tool name, CLI invocation,
     description), so the user can reproduce the call.
2. **No metric without record_ids.** Per
   [`reports.md`](./reports.md) §3.1 the report tools already supply
   `groups[].record_ids`. The Console MUST refuse to render an
   aggregate that lacks them; this is a schema constraint, not a
   render-time toggle.
3. **Examples are mandatory.** `groups[].examples` (kind + id +
   summary) drives the row-level drilldown context in dashboards. A
   group with `examples=[]` MUST be rendered with an explicit "no
   examples available" affordance instead of being silently empty.
4. **Truncation surfaces.** When `truncated=True`, the widget renders
   a visible "showing first N — call the report tool directly for the
   full set" affordance, including the next-cursor when present.
5. **Sample warnings render as chrome, not labels.** When
   `summary.sample_warning` or `groups[].sample_warning` is set, the
   widget renders a caveat banner consistent with §4.6; the metric
   tile gets a small caveat icon linked to the banner.
6. **Read-only export packets** (trade-trace-sqtq) bundle the
   `ReportResult` JSON + the originating filter + the rendered HTML
   snapshot. They never include credentials, request_ids that could
   leak across users, or any source-side identifiers not already in
   the journal.

## 7. Dependency policy (locked)

### 7.1 Charting

Charts use **Apache ECharts** bundled into the React/Vite build under
`src/trade_trace/console/static/app/assets/`. No CDN or runtime package
download is allowed. Chart series and aggregate values are produced by
backend report tools; the frontend renders those values and does not
perform financial or calibration aggregation in JavaScript.

### 7.2 Frontend stack

FastAPI serves a prebuilt React/Vite SPA. Source lives in
`frontend/console/`; wheels ship the compiled app assets. The stack is
React, TypeScript, Vite, TanStack Router, TanStack Query, TanStack
Table/Virtual, ECharts, Radix primitives, Tailwind, and Lucide icons.

### 7.3 Python dependencies

No new runtime Python dependencies for the reporting product. All
report computations live in the existing reports/contracts modules.
If new deps appear during implementation, the bead introducing them
MUST update PRD §2.4 (one-permitted-outbound-path framing) and
re-run the dependency-safety verification gate (`qclv`).

## 8. Read model + adapter contract (foundation beads — shipped)

The foundation wave is complete; this section now reflects what
shipped. Implementations live under
`src/trade_trace/console/reporting/` (read model, adapter, filter
state) and `src/trade_trace/console/static/` (chart scaffold).

1. **Trade / position read model** (trade-trace-bbww — *shipped*):
   `src/trade_trace/console/reporting/trade_rows.py` +
   `position_rows.py`. Public surface:
   - `list_trades(conn, *, cursor, limit, strategy_id, instrument_id,
     decision_type) -> Page[TradeRow]` — paginated trades index
     filtered to the trading decision types. Composite
     `(created_at, id)` cursor so deterministic fixtures with shared
     `created_at` paginate totally.
   - `trade_detail(conn, decision_id) -> TradeRow | None` — single
     trade by decision_id; returns `None` for unknown ids and for
     non-trading decision types (the `watch`/`skip` lane never
     surfaces here). This is a supported external Python read-model
     helper exported from `trade_trace.console.reporting`; it is
     intentionally not a Console HTTP endpoint or React route today.
   - `position_detail(conn, position_id) -> PositionDetail | None`
     — lifecycle projection row joined to instrument/venue, plus
     the chronological `position_events` lineage and the opening
     decision's strategy/playbook for audit.
   Named missing-data caveats (`missing_risk_budget`,
   `missing_price`, `missing_quantity`, `no_strategy`, `no_thesis`,
   `no_sources`, `open_no_mark`) replace silent zero-fills.
   Test pin: `tests/integration/test_console_reporting_read_model.py`
   (13 tests).
2. **ReportResult-to-Console adapter** (trade-trace-8ine — *shipped*):
   `src/trade_trace/console/reporting/adapter.py`. Public surface:
   - `run_report(tool, args, *, actor_id, home) -> DashboardContext`
     — dispatches via `trade_trace.core.dispatch`, enforces the
     **closed** `SAFE_REPORT_TOOLS` allowlist (15 reports) and the
     `LAZY_WRITE_DENY_SET` (`report.coach`, `signal.scan`), and
     normalizes the envelope into the typed `DashboardContext` /
     `DashboardGroup` / `WidgetEvidence` dataclasses.
   - Preserves every §6 evidence contract field: `summary_metrics`,
     `summary_filter`, `summary_sample_warning`, `summary_caveats`,
     groups (with `metrics` / `filter` / `record_ids` / `examples` /
     `sample_size` / `sample_warning` / `truncated`), `drilldowns`,
     `as_of`, `truncated`, `next_cursor`, `raw_envelope`, plus a
     `WidgetEvidence` aggregate (tool + CLI invocation + request_id
     + aggregated record_ids/examples).
   - Errors out-of-band: `ReportAdapterError` for deny-set / non-
     allowlisted / VALIDATION_ERROR envelopes so Console handlers
     can render typed user-facing copy.
   - The lazy-write deny set is duplicated **verbatim** from
     `console.endpoints.LAZY_WRITE_DENY_SET` so the AST-scan test
     (`tests/contracts/test_console_endpoints.py
     ::test_endpoints_do_not_dispatch_lazy_write_handlers`) catches
     drift in both files.
   Test pin: `tests/integration/test_console_reporting_adapter.py`
   (7 tests).
3. **Pagination + perf baseline** (trade-trace-mmbj — *shipped*):
   reuse cursor pagination from existing endpoints; perf budget =
   first page <1s wall-clock over a 100k-row population, 5×
   headroom required for the dashboard suite.
   `tests/integration/test_console_perf_baseline.py` pins the
   budget for the journal (events) AND the reporting read model
   (`list_trades`); both have first-page + deep-cursor cases.
   No new SQLite indexes were needed — the existing
   `decisions(created_at)` ordering meets budget under the composite
   cursor.
4. **Charting layer**: ECharts is bundled by Vite into the shipped SPA
   assets. There is no runtime chart download, no CDN fallback, and no
   operator-installed chart binary. Test pin:
   `tests/contracts/test_console_charting.py`.
5. **Fixtures** (trade-trace-dnwh — *shipped*): the new
   `mvp-eval-rich` `journal.fixture_seed` target (in
   `src/trade_trace/tools/fixture.py`) overlays `mvp-eval` with
   5 closed positions (winners/losers/breakeven), 4 open positions
   (2 marked via `snapshot.add`, 2 unmarked for the missing-mark
   caveat), declared-risk on some decisions and not others, and a
   `rich-only-N1` low-N strategy. Determinism pinned by
   `tests/integration/test_fixture_seed.py
   ::test_fixture_seed_mvp_eval_rich_is_deterministic`.
6. **Global filter UI backend** (trade-trace-hayy — *shipped*):
   `src/trade_trace/console/reporting/filter_state.py` provides
   `encode_filter(rf) -> base64url`, `decode_filter(s) -> ReportFilter`,
   `summarize_filter(rf) -> list[facet]`, and the
   `FILTER_QUERY_PARAM='f'` constant. Round-trips losslessly (incl.
   the `__none__` strategy sentinel), rejects unknown axes via
   `ReportFilter.model_validate` (`extra="forbid"`), and emits a
   compact `e30` payload for the no-filter case. The form / facet
   rendering / live-URL JS land in dashboard UI beads. Test pin:
   `tests/integration/test_console_reporting_filter_state.py` (14
   tests).

## 9. What this document does NOT decide

Out of scope (deferred to dedicated beads):

- Specific ECharts color palette / branding / theming.
- Per-page wireframes (UI beads own those).
- Visual polish + responsive breakpoints (trade-trace-bxhu).
- Browser/a11y QA (trade-trace-0d3p).
- User-facing copy edits beyond the metric glossary (trade-trace-4nux).
- Server-side saved filter presets (rejected for MVP; revisit when
  there is demand).
- Annotations / comments / journal writes from the dashboards
  (forbidden by §1.1).
- Cross-user / cross-account features.

## 10. Acceptance

This document satisfies trade-trace-gtep when:

- A foundation bead (`8ine`, `bbww`, `dnwh`, `hayy`, `mmbj`, `ycag`)
  can be picked up and implemented without asking Michael for
  product or dependency decisions. Each foundation bead references
  this doc's relevant section.
- The 12 UI dashboard beads (after the `xkdd` readiness gate) can
  consume the metric glossary in §4 and the IA in §3 directly.
- The QC + security beads (`pgem`, `qclv`, `rnje`, `xjld`, `0d3p`)
  have a written contract to verify against (the constraints in §1,
  §6, and §7).
