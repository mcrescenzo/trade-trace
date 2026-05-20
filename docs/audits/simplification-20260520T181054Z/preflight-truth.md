# Repo simplification review preflight truth — 20260520T181054Z

Mode: backlog-materialization with duplicate/reconciliation guard.

## Repo

- Tool cwd: `/home/hermes/code/trade-trace`
- Resolved git root: `/home/hermes/code/trade-trace`
- Branch: `main`
- Initial HEAD: `ffcd97420bf44c846451bd5d39596d39437d6e3e`
- Initial git status: clean (`git status -sb` showed `## main...origin/main`; `git status --short` empty)
- Tracked files: 305

## Beads

- `bd version`: 1.0.3
- `bd where`: `/home/hermes/code/trade-trace/.beads`, database `/home/hermes/code/trade-trace/.beads/embeddeddolt`
- Initial stats: 387 total, 46 open, 0 in_progress, 27 blocked, 341 closed, 19 ready
- `bd dep cycles`: none
- Initial duplicate scan threshold 0.35: 41 mechanical pairs, mostly known active epic/template overlap
- Mutation syntax verified: `bd create --body-file`, `bd dep relate`, `bd children`, `bd dep add`

## Existing overlap discovered

Initial open-list scan found deadcode, bughunt, console overhaul, and agent-ergonomics epics. A later all-status simplification-label scan found the closed prior simplification epic `trade-trace-mea1` (`simplification:20260519-exhaustive`) with all 16 rows + gates closed. This review therefore materialized only genuinely new or residual/reconciliation items, while merging/defering candidates covered by the prior epic or current open epics.

Relevant existing items used for duplicate disposition:

- `trade-trace-mea1`: closed exhaustive repo simplification backlog 2026-05-19
- `trade-trace-qs5v`: closed test home/MCP fixture simplification
- `trade-trace-qnxt`: closed report-row/result helper simplification
- `trade-trace-x0po`: closed report filter support simplification
- `trade-trace-6x3j`, `trade-trace-y5pj`, `trade-trace-58ic`: closed migration split investigation/harness/package split
- `trade-trace-42vr`: closed release gate/package version investigation
- `trade-trace-ensw`: closed docs validation/canonical-source simplification
- Open/active overlaps: `trade-trace-evwe`, `trade-trace-3i77`, `trade-trace-r1mt`, `trade-trace-0apb`, `trade-trace-nkfz`, `trade-trace-nlp0`, `trade-trace-hdlx`, `trade-trace-kz0h`, React Console overhaul `trade-trace-29m9`

## New epic

- Created narrative/root epic: `trade-trace-w3vs` — `EPIC: repo simplification review 2026-05-20`
- Label: `simplification:20260520`
- Membership model: relation-based epic membership plus candidate labels; final verification has blocking dependencies on materialized rows.

## Lanes

Read-only delegated lanes saved under `lane-reports/`:

1. `lane_0`: CLI/MCP/tool registry/contracts
2. `lane_1`: storage/events/import-export/security
3. `lane_2`: ledger tools/projections
4. `lane_3`: reports/memory/playbook/strategy/review bundle
5. `lane_4`: Console backend/frontend
6. `lane_5`: tests/docs/build

## Advisor gate

Advisor reviewed the matrix/overlap risk before materialization. Main directive: do not bulk-materialize all 32 raw candidates; create only genuinely uncovered work and explicit residual/reopen decisions; merge CLI/MCP, JSONL, release, docs, table, pagination, and prior-report/test helper overlap into existing work or a single reconciliation bead.
