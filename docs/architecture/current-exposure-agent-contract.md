# Current exposure agent contract

> Status: contract seam for trade-trace-39pg. This document defines the agent-facing semantics future CLI/MCP reports must preserve; it does not introduce a shipped tool by itself.

## 1. Boundary and precedence

Trade Trace records and projects journal state. It does **not** execute trades, query brokers, fetch market data, or prove an external broker portfolio is true. Any current-exposure answer is a local journal/projection answer with explicit caveats.

For agent-facing current-exposure tools, the precedence is:

1. **Canonical exposure source:** `position_events` are the append-only source of truth for position history and `positions` is the rebuildable projection used for current exposure rows.
2. **Decision trail:** `decisions` are activity/audit/journal records. They explain why an agent watched, skipped, entered, added, reduced, or exited, but they are not themselves canonical current exposure unless linked position events/projections exist.
3. **Watch ideas:** `watch` decisions are never positions, never trades, and never current exposure. They may appear in a watchlist/activity bucket only.
4. **Actual-recorded decisions:** `actual_enter`, `actual_exit`, `add`, and `reduce` record activity the agent says happened elsewhere. They are **record-only** unless a corresponding `position_events` lineage and `positions` projection exists. They never execute externally and never imply broker truth.

If these sources disagree, current-exposure tools must prefer open `positions` rows backed by `position_events`, then surface decisions-only evidence as caveats/activity rather than silently counting it as exposure.

## 2. Stable bucket names

Future report/tool outputs that summarize current exposure should use these stable machine-readable bucket names. Buckets may be empty, but names should not be replaced with presentation labels.

| Bucket | Meaning | Exposure? |
|---|---|---|
| `open_positions` | Open/partial `positions` projection rows backed by `position_events`. Includes paper, actual, or simulation kinds when the projection exists. | Yes |
| `closed_positions` | Closed/resolved/expired/assigned/voided projection rows included for recent context or audit. | No current exposure |
| `watchlist` | `watch` decisions, including stale/overdue watch ideas. | No |
| `recent_trade_activity` | Recent trade-typed decisions and position events shown as audit/activity context. | Not by itself |
| `record_only_actual` | Actual-recorded/add/reduce/exit decisions that do not have a corresponding open projection/event lineage. | No, unless paired with `open_positions` |
| `projection_anomalies` | Missing, stale, duplicate, or contradictory source/projection states that prevent a clean exposure answer. | Caveat only |

Human-facing titles may say “Open positions” or “Recent activity,” but JSON keys, caveat references, examples, and schema descriptions should use the names above.

## 3. Stable caveat and anomaly codes

Current-exposure outputs should expose caveats as stable codes plus human hints. The same code set is suitable for MCP `tool.schema` descriptions, CLI help, and Console copy.

| Code | Trigger | Expected agent wording / hint |
|---|---|---|
| `NO_OPEN_POSITIONS` | No open/partial rows exist in the `positions` projection. | “Canonical open positions: zero.” |
| `OPEN_PAPER_POSITION` | An open projection row has `kind = 'paper'`. | “Paper position recorded in Trade Trace; not external execution.” |
| `OPEN_ACTUAL_RECORDED_POSITION` | An open projection row has `kind = 'actual'`. | “Actual-recorded position exists in the local projection; verify against broker if external truth matters.” |
| `WATCH_ONLY_IDEA` | A matching/current instrument only has `watch` decisions. | “Watch idea only; not counted as exposure.” |
| `DUPLICATE_DECISIONS` | Multiple similar decisions exist without enough position-event lineage to disambiguate exposure. | “Duplicate journal decisions found; exposure is based only on position projection.” |
| `PROJECTION_MISSING` | Position events or entry-like decisions suggest a projection should exist, but no `positions` row can be read. | “Projection missing; rebuild/check projections before relying on exposure.” |
| `PROJECTION_STALE` | `positions.updated_at` predates relevant `position_events` or known rebuild markers. | “Projection may be stale; rebuild/check projections before relying on exposure.” |
| `MISSING_MARK` | An open position has no current mark/valuation needed for unrealized value. | “Open exposure exists, but current mark/P&L is unavailable.” |
| `STALE_MARK` | The latest mark/snapshot is older than the report’s freshness threshold. | “Open exposure exists, but mark is stale as of the requested time.” |
| `RECORD_ONLY_ACTUAL` | `actual_enter`, `actual_exit`, `add`, or `reduce` exists without corresponding position events/projection. | “Recent actual-recorded journal entries exist but are not open exposure.” |
| `ENTRY_DECISION_WITHOUT_POSITION_EVENT` | `paper_enter` or entry-like decision exists without the expected linked `position_events.open`. | “Entry decision lacks a linked position event; not counted as canonical exposure.” |

Tools may add more specific codes later, but must not reuse these names for different meanings.

## 4. Required scenario semantics

- **No-position case:** return `open_positions = []`; include `NO_OPEN_POSITIONS` when the answer is specifically “what is current exposure?” If recent decisions exist, place them in `recent_trade_activity` or `record_only_actual`, not in `open_positions`.
- **Open paper positions:** include projection rows in `open_positions` with `OPEN_PAPER_POSITION`; wording must identify them as local paper exposure.
- **Open actual-recorded positions:** include actual-kind projection rows in `open_positions` with `OPEN_ACTUAL_RECORDED_POSITION`; wording must preserve the local-recorded/broker-verification caveat.
- **Watch-only ideas:** include watches in `watchlist` with `WATCH_ONLY_IDEA`; never promote them to exposure, even if side/reason text sounds directional.
- **Duplicate decisions:** keep duplicate decisions in `recent_trade_activity` and surface `DUPLICATE_DECISIONS`; do not sum them into exposure unless position events/projection rows encode that exposure.
- **Projection missing/stale:** put the issue in `projection_anomalies` with `PROJECTION_MISSING` or `PROJECTION_STALE`; avoid confident exposure totals until the projection is rebuilt or reconciled.
- **Missing/stale marks:** keep the open position in `open_positions`, but mark value/P&L fields as unavailable or caveated with `MISSING_MARK` / `STALE_MARK` rather than filling zero.
- **Record-only actual activity:** place unprojected `actual_*`/`add`/`reduce` decisions in `record_only_actual` and explain that they are journal records only.

## 5. CLI/MCP discovery and examples

Agent entry points:

- Use `tt report current_exposure` (MCP tool `report.current_exposure`) first for “open trades,” “current exposure,” or “what am I in now?” It returns `open_positions`, `watchlist`, `recent_trade_activity`, and `projection_anomalies` together.
- Use `tt report open_positions` (MCP tool `report.open_positions`) when the answer needs row-level canonical open-position detail.
- Use `tt report pnl` (MCP tool `report.pnl`) for realized/unrealized/MTM P&L. If `summary.metrics.open_position_count > 0`, follow up with `tt report current_exposure` or `tt report open_positions` before answering exposure questions.
- Use `tt tool schema --tool report.current_exposure` or `tt tool schema --tool report.pnl` to inspect agent-facing descriptions, examples, and next actions.

CLI/MCP descriptions may reuse this compact wording:

> Current exposure is derived from the `positions` projection backed by `position_events`. Decisions are journal/activity records; `watch` decisions are never positions. Actual-recorded decisions are record-only unless a linked position projection/event exists. Output buckets use stable keys (`open_positions`, `closed_positions`, `watchlist`, `recent_trade_activity`, `record_only_actual`, `projection_anomalies`) and caveat codes such as `NO_OPEN_POSITIONS`, `RECORD_ONLY_ACTUAL`, and `PROJECTION_STALE`.

Example human hints and correct wording:

- **No open trades:** “Canonical open positions: zero; recent journal entries may exist but are not open exposure.”
- **Open paper trade:** “Open paper position recorded in Trade Trace; paper exposure is local journal/projection state, not external execution.”
- **Open actual-recorded trade:** “Actual-recorded open position exists in the local projection; verify against broker if external portfolio truth matters.”
- **Watch-only idea:** “Watch-only idea found in `watchlist`; not counted as exposure.”
- “Projection anomaly found; rebuild/check projections before relying on exposure.”

Trade Trace records trades and projections in the local journal. It does not execute trades, place orders, query brokers, or prove the user’s broker portfolio is true; agent answers must avoid implying portfolio truth when rows are paper, simulated, or record-only.
