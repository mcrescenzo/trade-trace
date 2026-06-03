# Friction registry (rolling)

> The dedup memory for the AX dogfood loop. **Read this at the start of every
> run (Phase A)** so the bot does not re-report or re-fix something already
> handled, and **update it at the end of every run (Phase D)** with whatever was
> found this run.
>
> One row per distinct friction item. Keep `id` stable once assigned
> (`AX-NNN`, monotonically increasing). When an item's disposition changes
> (e.g. open → fixed), update its row in place rather than adding a new one.

## Status legend

- `open` — observed, not yet addressed (still reproducible).
- `fixed` — resolved by a direct commit this loop (see `ref` for the SHA).
- `filed` — handed to Beads as a feature / major rework / design question
  (see `ref` for the bead id).
- `intentional` — confirmed deliberate; promoted to
  [`intentional-design.md`](./intentional-design.md). Do not re-report.
- `wontfix` — decided against, with reason in `ref`.

## Surface legend

`tool` (MCP tool behavior) · `schema` (tool schema/description text) ·
`error` (error message / `next_actions` hint) · `doc` (docs drift) ·
`cli` (CLI surface) · `onboarding` (cold-start/first-run) · `report` (report output).

## Registry

| id | first-seen run | surface | description | status | ref |
|----|----------------|---------|-------------|--------|-----|
| _none yet_ | | | | | |

<!--
Example row (delete when the first real item lands):
| AX-001 | 2026-06-04-01 | schema | `forecast.add` schema does not say probability must sum to 1.0 across labels | fixed | a1b2c3d |
-->
