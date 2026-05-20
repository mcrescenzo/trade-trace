# Console IA and support contract

> Status: product/IA support contract for trade-trace-r3hc. This document is durable implementation guidance for the React Console overhaul. It narrows the broader reporting-product architecture into page naming, data-source, audit-access, and copy rules.

## 1. Purpose and product boundary

The Trade Trace Console is a local, read-only analytics and review surface for a user's journal. It is not a trading terminal, broker integration, market-data client, alerting engine, or recommendation system.

Hard boundaries:

- Local-first: served by `tt console serve`, defaulting to `127.0.0.1:8765`.
- Package-shipped: the React/Vite app is built into package data; users do not need Node.js.
- Read-only: Console endpoints open the journal with a read-only SQLite handle and never mutate journal state.
- Local data only: pages render data already present in the journal projections, read models, reports, and logs. The Console must not fetch external market data, news, broker data, remote assets, telemetry, or analytics.
- Backend-owned aggregates: JavaScript renders server-provided metrics. P&L, risk, calibration, scoring, win rate, ECE, R-multiples, and similar aggregates come from Python read models/report tools.
- No trade advice: Console copy may summarize recorded journal facts and report outputs, but must not recommend trades, rank what the user should do next, or imply financial advice.

This contract intentionally separates primary product/review pages from secondary developer/audit affordances. Logs and Raw JSON are not primary top-level navigation items.

## 2. Glossary

| Term | Console meaning | Canonical data source | Copy rule |
|---|---|---|---|
| Trade | A trading decision with non-zero quantity that opens, adds to, reduces, or closes exposure (`actual_enter`, `paper_enter`, `add`, `reduce`, `actual_exit`, `paper_exit`). | `decisions` filtered by trading decision types; Console read model `list_trades`; report tools such as `report.pnl` and `report.risk`. | Use only when the page/row is restricted to trading-decision types. A watch/skip is never a trade. |
| Position | Rebuildable projection of exposure for an instrument/kind/side over time. | `positions`, `position_events`, `position_detail`, trade/position read model. | Describe lifecycle, exposure, marks, and caveats; do not imply the projection is a broker statement. |
| Decision | Any recorded agent/user action against an instrument/thesis, including trade entries/exits, watches, skips, holds, thesis updates, and reviews. | `decisions` table and `/api/console/decisions`. | Use when non-trading rows are included. Do not call all decisions trades. |
| Strategy | Named grouping/family of decisions or forecasts. Orthogonal to playbooks and tags. | `strategies` table, `strategy_id` fields, `/api/console/strategies`, `report.strategy_performance`. | Say "strategy" for grouping/segment analysis, not a promise of edge. |
| Playbook | Procedural ruleset/version used to evaluate adherence. | `playbooks`, playbook versions/rules, `/api/console/playbooks`, `report.playbook_adherence`. | Use for process/adherence review. Do not call adherence "guaranteed discipline" or outcome causality. |
| Journal Event | Append-only event envelope in the journal log. | `events`, `/api/console/events`, `/api/console/events/{event_id}`, `/api/console/raw/{event_id}`. | Developer/audit noun. Product dashboards should link to event evidence rather than expose event JSON first. |
| Forecast | Probability distribution attached to a thesis/instrument and horizon. | `forecasts`, `/api/console/forecasts`, calibration reports. | Use as a recorded probability, not a prediction guarantee. |
| Outcome | Resolved truth/result used to score forecasts or contextualize decisions. | `outcomes`, `/api/console/outcomes`, report scoring inputs. | Label provisional/ambiguous/disputed/void states explicitly. |
| Source / Evidence | Supporting source records, report evidence blocks, examples, record IDs, raw report envelope, or journal event payloads that let the user inspect where a number came from. | `sources`, source attachments, report adapter `evidence`, `groups[].record_ids`, `groups[].examples`, `raw_envelope`, raw event endpoints. | Every aggregate must expose evidence or a clear "evidence unavailable" state. |
| Calibration | Forecast-quality measurement comparing forecast probabilities to outcomes. | `report.calibration`, `report.calibration_integrity`, forecasts/outcomes. | Say "calibration" and "scoring"; never say the model is "accurate" without the specific measured statistic and caveat. |
| Caveat | Visible limitation, warning, missing-data condition, sample warning, or data-quality note attached to a row, group, or metric. | Report `summary_sample_warning`, `summary_caveats`, group warnings, trade read-model caveats such as missing risk/mark/source. | Caveats are first-class UI chrome, not hidden footnotes. |
| Review Period | The active time/filter window used for reports and tables. | `ReportFilter.time_window`, table cursor/limit parameters, report request args, URL `f=<base64url-json>`. | Copy must state the active period/filter when it materially changes a number. |

## 3. Canonical navigation model

Primary navigation must optimize for journal review and reporting. Secondary access must preserve auditability without presenting raw internals as the product's main experience.

Primary product/review navigation:

1. Overview (`/`)
2. Trades (`/trades`)
3. Reports (`/reports`)
   - P&L (`/reports/pnl`)
   - Risk (`/reports/risk`)
   - Performance (`/reports/performance`)
   - Strategy / Playbook (`/reports/strategy`)
   - Decision Intelligence (`/reports/decisions`)
   - Compare (`/reports/compare`)
4. Calibration (`/calibration`)
5. Evidence (`/evidence`)
6. Strategies (`/strategies`)
7. Playbooks (`/playbooks`)

Secondary developer/audit affordances:

- Journal (`/journal`)
- Decisions table/detail (`/decisions`, future `/decisions/{id}` if implemented)
- Per-record Raw Payload viewer via `/api/console/events/{event_id}` or `/api/console/raw/{event_id}` from record drawers/links
- Logs (`/api/console/logs`, and any `/logs` UI if retained)
- Export packets from `/api/console/reports/{tool}/export?f=...`

Mandatory IA rules:

- Logs and Raw JSON must not appear as primary top-level nav peers with Overview, Trades, Reports, Calibration, Evidence, Strategies, or Playbooks.
- If Logs or a Raw JSON route remains, it must be under a clearly labeled secondary "Developer", "Audit", or "Advanced" disclosure/group.
- Product pages must link to raw/audit evidence from the relevant record or metric instead of requiring users to start from a raw dump.
- Strategies and Playbooks may be primary pages because they are domain objects, but their audit internals remain secondary.

## 4. Page map and support matrix

| Page | User question answered | Local data source / API / report / read model | Supported filters | Unsupported / empty states | Caveats |
|---|---|---|---|---|---|
| Overview (`/`) | "What is the current state of my journal and headline reporting picture?" | `/api/console/status`; `report.pnl`; `report.risk`; later report rollups from backend reports only. | Review Period via `ReportFilter`/URL `f`; report-supported facets only. | Missing DB or unsupported schema shows typed status error; no trades/reports shows empty metric cards with setup guidance; report adapter errors show typed report failure. | Must distinguish DB metadata from performance facts; no client-computed summary math. |
| Trades (`/trades`) | "Which recorded trading decisions make up my trade history?" | `/api/console/trades`; `list_trades` read model; source decisions and positions. | Cursor/limit; strategy_id; instrument_id; decision_type; future valid `ReportFilter` projections. | No trades means no trading-decision rows, not no journal activity; missing instrument symbol should fall back to instrument title then `n/a`; unknown cursor shows pagination error. | Trade caveats such as missing risk, price, quantity, strategy, thesis, sources, or open mark must be visible. |
| Position detail (`/positions/{id}` when routed) | "How did this position open, change, and close?" | `/api/console/positions/{position_id}`; `position_detail` read model; related decisions/position_events. | Position ID path; linked context from Trades/reports. | Unknown position returns not-found; no marks or open position shows explicit state. | Projection is journal-derived, not broker-confirmed; realized/unrealized values depend on recorded prices/marks. |
| Reports catalog (`/reports`) | "Which safe local reports are available and how can I inspect/export them?" | `/api/console/catalog`; `SAFE_REPORT_TOOLS`; `/api/console/reports/{tool}/export`. | ReportFilter `f`; report tool selection. | Empty safe-tool catalog is an implementation error; blocked lazy-write handlers remain blocked. | Catalog must not expose `report.coach` or `signal.scan` as runnable Console actions. |
| P&L (`/reports/pnl`) | "What P&L is recorded for the review period?" | `POST /api/console/reports/report.pnl/run`; trade/position read model; export endpoint. | ReportFilter facets supported by `report.pnl` (time, strategy, instrument, decision facets where server validates). | No closed/open trades shows explicit no P&L data state; missing marks reduce/qualify MTM. | Label realized, unrealized, MTM, and coverage separately; no broker reconciliation claim. |
| Risk (`/reports/risk`) | "What recorded risk/R-multiple distribution exists?" | `report.risk`; decisions with declared risk and outcomes/position context. | ReportFilter facets supported by `report.risk`. | No declared risk shows "risk unavailable" rather than zero; pending rows remain separate. | Excluded missing-risk decisions must be counted/caveated; no risk advice. |
| Performance (`/reports/performance`) | "What does recorded performance over time look like?" | `report.decision_velocity` today; future backend performance read model/reports for equity/drawdown/calendar. | ReportFilter time and supported facets. | If only decision velocity exists, label as activity/performance proxy; no equity/drawdown chart without backend data. | Never compute equity curve/drawdown in JS; UTC bucket alignment where time buckets exist. |
| Strategy / Playbook (`/reports/strategy`) | "How do strategies and playbook adherence compare in the journal?" | `report.strategy_performance`; `report.playbook_adherence`; `/api/console/strategies`; `/api/console/playbooks`. | Strategy/playbook facets; Review Period; server-supported report filters. | No strategies/playbooks shows setup/empty rows; no adherence data says unavailable, not zero adherence. | Do not present strategy ranking as a recommendation or causality proof. |
| Decision Intelligence (`/reports/decisions`) | "Which recorded decision patterns, watches, and unscored forecasts need review?" | `report.mistakes`; `report.strengths`; `report.watchlist`; `report.unscored_forecasts`; `/api/console/decisions`. | Decision, instrument, strategy, time, outcome/scoring filters where supported. | No stale watches or unscored forecasts shows clear all-clear for the selected filter only; no mistakes/strengths at low sample shows caveat. | Use "pattern" and "recorded result" language; no "you should buy/sell/avoid" copy. |
| Compare (`/reports/compare`) | "How do report groups compare under a selected local filter?" | `report.compare`; base safe report outputs. | Valid base_report/group_by/filter args; URL `f` for filter state where applicable. | Invalid base report/grouping shows typed validation; no comparable groups shows empty comparison. | Comparison does not establish causality; surface sample sizes and warnings. |
| Calibration (`/calibration`) | "How well did forecasts match outcomes, and are scoring inputs healthy?" | `report.calibration`; `report.calibration_integrity`; forecasts/outcomes. | Time, strategy, instrument, outcome/scoring, source filters supported by server. | No scored forecasts shows unscored/insufficient data state; ambiguous/disputed/void outcomes separated. | Low N, unsupported outcomes, late forecasts, and integrity rates must be visible. |
| Evidence (`/evidence`) | "What sources/evidence support the journal and reports?" | `report.source_quality`; `sources`; source attachment tables; report evidence blocks. | Source facets, strategy/instrument/time facets where supported. | No sources means no attached sources, not no truth; broken/missing attachment data is caveated. | Evidence quality is provenance coverage, not source correctness guarantee. |
| Strategies (`/strategies`) | "What named strategies exist and what is their status?" | `/api/console/strategies`; columns id/name/slug/status/created_at. | Cursor/limit; future status/search only if backend supports it. | Empty table means no strategy records; do not show event-style columns for strategy rows. | Strategy status is journal metadata, not performance certification. |
| Playbooks (`/playbooks`) | "What playbooks exist and what is their status/description?" | `/api/console/playbooks`; columns id/name/description/status/created_at. | Cursor/limit; future status/search only if backend supports it. | Empty table means no playbook records; do not show event-style columns for playbook rows. | Playbook existence does not mean every decision has adherence data. |
| Journal (`/journal`) | "What append-only events are in the journal?" | `/api/console/events`; event detail `/api/console/events/{event_id}`. | Cursor/limit. | Empty means no events in the selected journal; missing event detail shows not-found. | Secondary developer/audit page; should link to raw payload affordance. |
| Decisions (`/decisions`) | "What decisions, trading and non-trading, are recorded?" | `/api/console/decisions`; decision detail if implemented. | Cursor/limit; decision_type; instrument_id. | Empty under filter means no matching decisions; non-trading decisions are valid. | Must use decision columns (`type`, `instrument_id`, `thesis_id`, `side`, `quantity`, `price`, `created_at`), not event columns. |
| Logs (secondary `/logs` if retained) | "What local Console/server log lines help debug this session?" | `/api/console/logs?level=&tail=`. | `level`; `tail` clamped by backend. | Missing log file/empty logs shows structured empty state. | Redacted, read-only, secondary only; not a product review page. |
| Raw Payload (secondary disclosure, not primary nav) | "What exact event/report payload produced this record or metric?" | `/api/console/raw/{event_id}`; `/api/console/events/{event_id}`; report `raw_envelope`; report export packet. | Event ID; report filter `f`; originating request metadata where available. | Missing payload shows not-found/unsupported for that record; malformed JSON shown as safely escaped text. | Audit-only; preserve provenance fields; never make raw JSON the default product landing path. |

## 5. Raw/audit access policy

Raw and audit access is required for trust, but it must be contextual and secondary.

Required affordances:

- Every report aggregate must offer an Evidence action showing originating tool, filter, request_id when available, record_ids, examples, group metrics, sample warnings, caveats, and raw report envelope/export access.
- Every Journal/Decision/Trade/Position row that can map to an event or record detail should expose a read-only "Raw payload" or "View event" action.
- Logs access, if present in UI, must be structured, redacted, read-only, and hidden under Developer/Audit/Advanced navigation.
- Export packets are read-only reproductions of server report output and active filter state. They must not add new claims or client-derived aggregates.

Forbidden IA patterns:

- A top-level primary nav tab named "Raw JSON".
- A top-level primary nav tab named "Logs".
- Product dashboard cards that render a number without evidence/caveat affordance.
- Raw JSON as the only route for inspecting report evidence.

## 6. Copy standards and forbidden claims

Allowed copy patterns:

- "Recorded P&L for this review period"
- "Decisions matching the current filter"
- "Forecasts with resolved outcomes"
- "Source coverage in this journal"
- "Sample is below the recommended threshold"
- "No matching trades for the selected filter"
- "Evidence unavailable for this aggregate" when the server truly lacks it

Required copy practices:

- Name the active Review Period/filter when a metric depends on it.
- Prefer factual verbs: recorded, observed, grouped, matched, excluded, missing, unresolved, caveated.
- Distinguish zero from unavailable from not-applicable.
- Include sample size and caveats near aggregate comparisons.
- Explain unsupported states as data/product support limits, not as user failure.
- Keep report math wording aligned with backend report definitions.

Forbidden claims:

- Advice or recommendation: "buy", "sell", "hold this", "enter now", "exit now", "increase size", "best trade to take".
- Causality overclaims: "this strategy caused profits", "this source proves the outcome", "this playbook guarantees results".
- Unsupported competitor-style promises: "broker-grade", "real-time market data", "tax-ready", "audit-certified", "execution quality", "alpha signal", "guaranteed edge", "automated trading", "portfolio optimizer".
- Unsupported precision: showing computed financial/calibration aggregates that did not come from backend reports/read models.
- Hiding caveats: presenting low-N, missing mark, missing risk, ambiguous outcome, late forecast, or sparse evidence results as complete.

## 7. Implementation handoff by bead owner ID

| Bead | Contract ownership / handoff |
|---|---|
| trade-trace-r3hc | Owns this IA/support contract: terminology, navigation lanes, support matrix, raw/audit disposition, and copy boundaries. |
| trade-trace-nlp0 | Use §2 and §4 to fix core row mappings and reusable tables: strategies/playbooks/decisions must use their own fields; trades must fall back from instrument symbol to title. |
| trade-trace-z71g | Use §3, §4, and §5 for supported global filters, URL `f=<base64url-json>`, table pagination, cursor handling, and server-backed filter re-requests. |
| trade-trace-gldl | Use Overview/P&L/Performance rows in §4; render only backend-sourced metrics and visible caveats. |
| trade-trace-469s | Use Risk and Position detail rows in §4; surface missing-risk/position caveats and avoid advice. |
| trade-trace-4lwb | Use Strategy / Playbook row in §4; combine strategy performance and playbook adherence without ranking-as-recommendation copy. |
| trade-trace-m170 | Use Calibration/Evidence rows plus §5; expose calibration integrity, source quality, and report evidence/drilldown affordances. |
| trade-trace-5ja7 | Use Decision Intelligence row in §4; compose mistakes, strengths, watchlist, and unscored forecast reports with caveats and non-advice copy. |
| trade-trace-srs9 | Use §5 for detail drawers/pages and raw payload actions from records/metrics. |
| trade-trace-ebhh | Use Journal row in §4 and §5 to make event timeline/replay audit-friendly without promoting raw dumps to primary product IA. |
| trade-trace-4lxl | If logs/raw developer surfaces remain in UI, implement them as structured, redacted, secondary Developer/Audit/Advanced affordances per §3 and §5. |
| trade-trace-zfyh | Apply copy and unsupported/empty-state rules across page chrome and report surfaces. |
| trade-trace-8o80 | Use this contract as QA criteria for nav hierarchy, page support states, evidence affordances, and forbidden claims. |
| trade-trace-o88k | Final product QA gate should verify the primary nav excludes Logs/Raw JSON, secondary audit access remains available, and screenshots do not show forbidden claims. |
| trade-trace-5fld | Implement glossary, metric help, caveat help, and tooltip/disclosure copy from §2 and §6. |

## 8. Verification checklist for implementers

Before marking a Console UI bead complete, verify:

- Primary nav does not include Logs or Raw JSON as top-level product tabs.
- Logs/Raw JSON, if reachable, are behind Developer/Audit/Advanced grouping or contextual row/detail actions.
- Each page names its local data source/report/API and does not invent unsupported metrics.
- Empty states distinguish no data, filtered-out data, unsupported data, missing DB, and backend errors.
- Every aggregate metric exposes evidence or an explicit unavailable-evidence state.
- Caveats/sample warnings are visible near the affected metric/table row.
- Copy contains no advice, causality overclaims, broker/market-data promises, or unsupported competitor-style claims.
- URL/report filter state round-trips through server-supported `ReportFilter` fields only.
