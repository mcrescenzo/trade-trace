# Position id reopen semantics

> Status: **decision document** for bead `trade-trace-7h2u`. Codifies
> the existing implementation in `src/trade_trace/projections.py` so a
> future contributor (or AI agent) can replay/rebuild projections
> without inventing domain policy.
>
> No behavior changes in this doc — the regression tests at the bottom
> pin the existing math. A misleading inline comment in
> `projections.py:65-67` ("re-opens start a new accumulation") describes
> intent that the code does not implement; this doc supersedes that
> comment.

## Problem

`position_events` carries `(position_id, instrument_id, event_type,
quantity_delta, …)` rows. A position's cumulative `quantity_delta`
returning to zero closes the position; a later `position_events` row
for the same `position_id` re-opens trading exposure on the same logical
instrument. The replay/projection layer must answer:

1. Does a re-open re-use the original `position_id`, or mint a new one?
2. What does the `positions` projection row contain after a re-open —
   the latest interval, the lifetime aggregate, or every interval
   independently?
3. How are realized P&L and R-multiple values carried across intervals?

## Decision

**The same `position_id` carries every interval; the `positions`
projection is a single lifetime aggregate, not a per-interval ledger.**
Specifically:

- **Identity is logical, not per-interval.** A `position_id` represents
  a `(instrument_id, account, strategy)` slot. A close followed by a
  re-open on the same slot is "the same position holding a new amount,"
  not "a brand new position."

- **`opened_at` is the first event's timestamp.** It is the lifetime
  origin of the position, not the latest open interval's timestamp.

- **`closed_at` is the timestamp of the most recent event that drove
  cumulative quantity to zero.** A subsequent `open` event un-pins
  `status` from `closed` back to `open` but does not clear
  `closed_at`; the projection prefers consistency with the latest
  event in the group.

- **`avg_entry_price` is the lifetime volume-weighted average across
  every entry event** (`open` + `add`), not just the latest interval's.
  `weighted_entry_price_qty` and `abs_entry_qty` accumulate across the
  full history; re-opens fold their fill into the lifetime VWAP.

- **`realized_pnl` accumulates across the full lifecycle** using the
  running lifetime VWAP at each exit. A close after a re-open computes
  P&L against the current VWAP, not the per-interval entry price.
  Fees and slippage are subtracted from `realized_pnl` on every exit
  event.

- **R-multiple columns mirror the latest non-NULL value** seen on a
  `position_events` row in the group. Carrying R values through a
  re-open is therefore "last write wins" for the projection; downstream
  analytics that need per-interval R must query `position_events`
  directly.

- **Re-opens are NOT modelled as a separate lifecycle event.** A
  `position_events` row with `event_type='open'` after the cumulative
  quantity returned to zero is interpreted as continuing accumulation
  without requiring a discriminator column.

### Rationale

1. The MVP's analytic surface (`report.pnl`, `report.watchlist`,
   `report.risk`) reads from the `positions` projection. A lifetime
   aggregate is one row per `position_id` regardless of how many open
   intervals it has had, which keeps report queries simple.
2. Position identity is rarely the question agents ask. The questions
   are: "what's my current exposure?" (current `quantity` from
   `position_events`) and "what did this position cost me over time?"
   (lifetime `realized_pnl`). Both are answerable from the lifetime
   aggregate.
3. The full per-interval history is **not lost** — it lives in
   `position_events`. Anything that wants per-interval analytics walks
   the event log directly. This matches the broader trade-trace
   convention: event log is canonical; projections are convenience.

## Examples

### Example 1: open → close → reopen → still open

```text
position_events for pos_42:
  t0  open   +100 @ 0.40  fees 0.5
  t1  close  -100 @ 0.55  fees 0.5
  t2  open   +50  @ 0.60  fees 0.5
```

Projection row at `t2`:

| field             | value                                   |
|-------------------|-----------------------------------------|
| `id`              | `pos_42`                                |
| `status`          | `open`                                  |
| `opened_at`       | `t0` (first event timestamp)            |
| `closed_at`       | `t1` (last close timestamp)             |
| `avg_entry_price` | `(100·0.40 + 50·0.60) / 150 = 0.4666…`  |
| `realized_pnl`    | `(0.55 − 0.40)·100 − 0.5 = 14.5`        |
| `updated_at`      | `t2`                                    |

The lifetime VWAP folds the t2 fill into the running average.
`realized_pnl` reflects the single close that has happened so far.

### Example 2: open → close → reopen → close

```text
position_events for pos_43:
  t0  open   +100 @ 0.40  fees 0.5
  t1  close  -100 @ 0.55  fees 0.5
  t2  open   +50  @ 0.60  fees 0.5
  t3  close  -50  @ 0.45  fees 0.5
```

Projection row at `t3`:

| field             | value                                                       |
|-------------------|-------------------------------------------------------------|
| `id`              | `pos_43`                                                    |
| `status`          | `closed`                                                    |
| `opened_at`       | `t0`                                                        |
| `closed_at`       | `t3`                                                        |
| `avg_entry_price` | `0.4666…`                                                   |
| `realized_pnl`    | `14.5 + (0.45 − 0.4666…)·50 − 0.5 = 14.5 − 1.333… = 13.166…`|
| `updated_at`      | `t3`                                                        |

The second close computes P&L against the lifetime VWAP that the t2
fill folded into. The reported `realized_pnl` is `≈ 13.166…`, not the
sum of two independently-computed per-interval P&Ls.

### Example 3: a same-sign exit after a close (data error)

If `position_events` carries a `close` row whose sign does not reduce
the current exposure (e.g. another `close` after cumulative quantity
already returned to zero, or a `close` with the wrong sign), the
projection raises `INVARIANT_VIOLATION` per
`tests/integration/test_projection_rebuild.py::test_rebuild_rejects_same_sign_exit_quantity_delta`.
The event log is the source of truth; integrity checks surface
malformed sequences.

## Compatibility and migration

- **No schema migration required.** This decision documents existing
  behavior; the `positions` projection and `position_events` table
  already implement it.
- **Replay determinism.** Two runs of `rebuild_projections` against
  the same `position_events` data produce byte-identical `positions`
  rows. This is verified by the existing
  `tests/integration/test_projection_rebuild.py::test_rebuild_idempotent_after_seeded_position`.
- **External imports** must preserve `position_id` on re-opens (the
  importer's responsibility). Importing a re-open as a fresh
  `position_id` would create two projection rows on the same logical
  slot; downstream reports may double-count exposure.

## Validation tests

The decision is pinned by these regression tests
(`tests/integration/test_projection_rebuild.py`):

- `test_rebuild_idempotent_after_seeded_position` — repeat invocations
  produce the same rows.
- `test_reopen_after_close_uses_first_event_for_opened_at` — asserts
  Example 1 / 2's `opened_at` pinned to the first event, not the latest
  open.
- `test_realized_pnl_accumulates_across_intervals_with_lifetime_vwap`
  — asserts Example 2's `13.166…` lifetime realized P&L, which proves
  the re-open fill folds into the running VWAP before the second close
  computes against it.

If the team later decides per-interval identity (or per-interval VWAP)
is required for an audit/compliance feature, open a separate design
bead — it is a schema + report contract change, not a projections-only
one.
