# Position id reopen semantics

> Status: **decision document** for bead `trade-trace-7h2u`. Codifies
> the existing implementation in `src/trade_trace/projections.py` so a
> future contributor (or AI agent) can replay/rebuild projections
> without inventing domain policy.
>
> No behavior changes in this doc — implementation already follows the
> "same `position_id`, latest-interval projection" model; see the
> validation test list at the bottom for the regression coverage that
> pins this decision.

## Problem

`position_events` carries `(position_id, instrument_id, event_type,
quantity_delta, …)` rows. A position's cumulative `quantity_delta`
returning to zero closes the position; a later `position_events` row
for the same `position_id` re-opens trading exposure on the same logical
instrument. The replay/projection layer must answer:

1. Does a re-open re-use the original `position_id`, or mint a new one?
2. What does the `positions` projection row contain after a re-open —
   the latest interval, the union of all intervals, or every interval
   independently?
3. How are realized P&L and R-multiple values carried across intervals?

## Decision

**The same `position_id` carries every interval; the `positions`
projection captures the most recent open interval.** Specifically:

- **Identity is logical, not per-interval.** A `position_id` represents
  a `(instrument_id, account, strategy)` slot. A close followed by a
  re-open on the same slot is "the same position holding a new amount,"
  not "a brand new position."

- **The projection is the current state, not a ledger.** The
  `positions` row tracks the latest open interval's `avg_entry_price`,
  `opened_at`, `quantity`, `unrealized_pnl`, etc. The full lifecycle
  history is preserved in `position_events`; the projection is a
  rebuildable convenience.

- **`realized_pnl` accumulates across the full position lifecycle.**
  Closing fills add their realized contribution into the running sum.
  Re-opens do not reset `realized_pnl`; reports comparing "what did
  this position cost me" against the full history are stable.

- **R-multiple columns mirror the latest non-NULL value** seen on a
  `position_events` row in the group. Carrying R values through a
  re-open is therefore "last write wins" for the projection; downstream
  analytics that need per-interval R must query `position_events`
  directly.

- **Re-opens are NOT modelled as a separate lifecycle event.** A
  `position_events` row with `event_type='open'` after the cumulative
  quantity returned to zero is interpreted as a re-open by the
  projection without requiring a discriminator column.

### Rationale

1. The MVP's analytic surface (`report.pnl`, `report.watchlist`,
   `report.risk`) reads from the `positions` projection. Switching to
   per-interval identity would require every report to UNION-ALL across
   intervals and apply window functions to find the latest, which is
   slower and harder to reason about.
2. Position identity is rarely the question agents ask. The questions
   are: "what's my current exposure?" (latest open interval) and
   "what did this position cost me over time?" (cumulative realized).
   Both are easy to answer with the latest-interval projection plus
   the running realized sum.
3. The full per-interval history is **not lost** — it lives in
   `position_events`. Anything that wants per-interval analytics walks
   the event log directly. This matches the broader trade-trace
   convention: event log is canonical; projections are convenience.

## Examples

### Example 1: open → close → reopen → still open

```text
position_events for pos_42:
  t0  open   +100 @ 0.40  (paper_enter)
  t1  close  -100 @ 0.55  (paper_exit; realized = +15)
  t2  open   +50  @ 0.60  (paper_enter)
```

Projection row at `t2`:

| field             | value     |
|-------------------|-----------|
| `id`              | `pos_42`  |
| `status`          | `open`    |
| `opened_at`       | `t2`      |
| `avg_entry_price` | `0.60`    |
| `realized_pnl`    | `+15.0`   |
| `closed_at`       | `NULL`    |

`opened_at` reflects the latest open interval; `realized_pnl` accumulates
across the full history.

### Example 2: open → close → reopen → close

```text
position_events for pos_43:
  t0  open   +100 @ 0.40
  t1  close  -100 @ 0.55  (realized = +15)
  t2  open   +50  @ 0.60
  t3  close  -50  @ 0.45  (realized = -7.5)
```

Projection row at `t3`:

| field          | value      |
|----------------|------------|
| `id`           | `pos_43`   |
| `status`       | `closed`   |
| `opened_at`    | `t2`       |
| `closed_at`    | `t3`       |
| `realized_pnl` | `+7.5`     |

`opened_at` / `closed_at` reflect the latest interval. `realized_pnl`
is the lifetime sum.

### Example 3: a re-open with no prior close (data error)

If `position_events` carries a second `open` on the same `position_id`
without an intervening close, the projection treats the second open as
an `add` (it bumps `quantity_delta` and refreshes
`avg_entry_price` using the volume-weighted average). The event log
remains the source of truth; the integrity check in
`tests/integration/test_projection_rebuild.py` will surface unusual
sequences.

## Compatibility and migration

- **No schema migration required.** This decision documents existing
  behavior; the `positions` projection and `position_events` table
  already implement it.
- **Replay determinism.** Two runs of `rebuild_projections` against
  the same `position_events` data produce byte-identical `positions`
  rows. This is verified by the existing
  `tests/integration/test_projection_rebuild.py::test_rebuild_is_deterministic`.
- **External imports** must preserve `position_id` on re-opens (the
  importer's responsibility). Importing a re-open as a fresh
  `position_id` would create two projection rows on the same logical
  slot; downstream reports may double-count exposure.

## Validation tests

The decision is pinned by these regression tests
(`tests/integration/test_projection_rebuild.py`):

- `test_rebuild_is_deterministic` — repeat invocations produce the same
  rows in the same order.
- `test_reopen_after_close_uses_latest_interval_for_opened_at` (NEW —
  follow-up bead): asserts the Example 1 / Example 2 shape (`opened_at`
  pinned to the latest `open` event).
- `test_realized_pnl_accumulates_across_intervals` (NEW — follow-up bead):
  asserts Example 2's lifetime `realized_pnl` sum, not just the latest
  interval's.

Follow-up beads:

- File a test-only bead to add the two NEW tests above (they pin the
  decision without changing implementation).
- If the team later decides per-interval identity is required (e.g.
  for an audit/compliance feature), open a separate design bead — it
  is a schema + report contract change, not a projections-only one.
