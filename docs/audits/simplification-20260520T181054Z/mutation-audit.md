# Mutation audit — simplification 20260520T181054Z

## Intent

Create a reduced, advisor-gated repo-simplification backlog for Trade Trace after six read-only discovery lanes. Avoid duplicating the closed `simplification:20260519-exhaustive` backlog and current open deadcode/bughunt/console/agent-ergonomics epics.

## Inputs

- Repo: `/home/hermes/code/trade-trace`
- Baseline HEAD: `ffcd97420bf44c846451bd5d39596d39437d6e3e`
- New epic: `trade-trace-w3vs`
- Raw candidates: 32
- Advisor gate: approved reduced materialization, warned not to bulk-create all 32 or duplicate prior closed work.
- Lane reports: `lane-reports/trade_trace_simplification_lane_0.md` through `lane_5.md`
- Central matrix: `candidate-matrix.md`

## Materialized Beads

Direct tasks:

- `trade-trace-fxxm` — SIMP20-004 centralize POSIX permission helpers
- `trade-trace-d2jv` — SIMP20-005 extract safe path helpers
- `trade-trace-lu6g` — SIMP20-011 named row access for positions projection
- `trade-trace-4v31` — SIMP20-012 single-source source.attach target metadata
- `trade-trace-9gp0` — SIMP20-019 memory-local meta_json parsing helper
- `trade-trace-7v2i` — SIMP20-021 strategy response construction helper
- `trade-trace-10x6` — SIMP20-022/023 Console route catalog + static asset provenance
- `trade-trace-gis0` — SIMP20-029 split journal.fixture_seed internals

Investigation/design-first tasks:

- `trade-trace-m29q` — SIMP20-009 forecast add/supersede write-kernel safety
- `trade-trace-y0b2` — SIMP20-017 memory.recall decomposition characterization
- `trade-trace-lsi5` — SIMP20-020 review.bundle decomposition/hash characterization
- `trade-trace-2drt` — residual report/test-helper reconciliation against 20260519 backlog

Gate:

- `trade-trace-z5bd` — final verification gate, blocked by all 12 materialized work items

## Graph mutations

- Related `trade-trace-w3vs` to each materialized work item and final gate.
- Added blocking dependencies from each materialized work item to final gate `trade-trace-z5bd`.
- Appended materialization note to `trade-trace-w3vs`.

## Duplicate / overlap disposition

Not materialized as new standalone work:

- CLI/MCP examples, registry projection, and CLI exit-code mapping -> merge into existing open agent-ergonomics/schema/error work (`trade-trace-evwe`, `trade-trace-3i77`, `trade-trace-r1mt`).
- JSONL envelope duplication -> merge into open deadcode/serialization owner `trade-trace-0apb`.
- Migration metadata registry -> covered by closed `trade-trace-6x3j`, `trade-trace-y5pj`, and `trade-trace-58ic`; no new bead.
- Report adapter/envelope/filter residuals and residual test helper aliases -> one reconciliation bead `trade-trace-2drt`, not duplicate implementation beads.
- Console DataTable/dependency simplification -> merge into open `trade-trace-nlp0` / `trade-trace-hdlx`.
- Console pagination helper -> covered by closed `trade-trace-1kkv.14` and open Console overhaul; no standalone bead.
- Release workflow dynamic-version issue -> merge into open `trade-trace-nkfz` and prior release-gate work `trade-trace-42vr`.
- Docs markdown helper/status fallout -> merge/defer to `trade-trace-kz0h` / closed `trade-trace-ensw`.
- UnitOfWork.transaction wrapper -> rejected below threshold.
- ECharts chart primitive -> rejected/deferred as intentional architecture unless product policy changes.
- pycache artifact noise -> rejected; `git ls-files` count for tests/docs pycache artifacts is 0.

## Commands / verification

Materialization command:

- `python3 docs/audits/simplification-20260520T181054Z/materialize_simplification_beads_20260520.py`

Post-mutation checks captured in `final-verification-transcript.txt` and `readback-samples.txt`:

- `bd lint` -> no template warnings for 60 checked issues
- `bd orphans` -> one pre-existing orphan `trade-trace-frd0` (exhaustive deadcode epic), unrelated to this simplification materialization
- `bd children trade-trace-w3vs --json` -> `[]`, expected because relation-based membership is used
- `bd dep list trade-trace-w3vs` -> all 12 work items + final gate visible via relates-to
- `bd graph trade-trace-w3vs` -> final gate blocked by all 12 materialized work items; epic visible as root relation
- `bd dep list trade-trace-z5bd` -> all 12 materialized work items block final verification
- `bd dep cycles` -> no cycles
- duplicate scan threshold 0.45 -> 3 mechanical pairs, all pre-existing outside new SIMP20 rows
- `bd list --label simplification:20260520 --status open --flat --limit 0 --sort id` -> epic + 12 rows + final gate visible
- Representative `bd show` readbacks confirmed body/labels/dependencies for `trade-trace-fxxm`, `trade-trace-d2jv`, `trade-trace-m29q`, `trade-trace-2drt`, `trade-trace-z5bd`, and `trade-trace-w3vs`.

## Persistence notes

The audit directory is under `docs/audits/`, which is ignored by `.gitignore`. It must be force-added (`git add -f docs/audits/simplification-20260520T181054Z`) if this artifact is to be committed/pushed.

Beads state is in the project-local `.beads` DB. This repo does not track `.beads/issues.jsonl`.
