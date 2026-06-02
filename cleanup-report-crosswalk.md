# Repo-Cleanup → Beads Crosswalk

Materialized 2026-06-02 from the report-only `/repo-cleanup` workflow run
(34 verified candidates). Source report: [`cleanup-report.md`](./cleanup-report.md).

- **Program label:** `cleanup-audit`
- **Root epic:** `trade-trace-laow`
- **Final gate:** `trade-trace-vc5f` (blocked by all 15 children)
- **Membership:** relation-only (`bd dep relate`); prove via `bd dep list trade-trace-laow`,
  `bd graph trade-trace-laow`, or `bd list --status open --flat | grep cleanup-audit` —
  **not** `bd children`.
- **Disposition for all 34 candidates:** create (none deferred/rejected/merged-away).
  No open or closed bead matched these findings (`bd search` clean), so all are net-new.

## Candidate → Bead mapping

| Bead | Title | P | Source candidate(s) |
|------|-------|---|---------------------|
| `trade-trace-exsb` (CL1) | Fix model.import `--src`→`--path` doc drift (schema example + 4 docs) | P1 | doc-drift-32, doc-drift-33, doc-drift-34, doc-drift-35, doc-drift-36 |
| `trade-trace-i6v1` (CL2) | Remove unused tenacity runtime dependency + fix false docstrings | P2 | unused-deps-10 |
| `trade-trace-joqs` (CL3) | Remove 7 unreferenced dead-code helpers/attributes/methods | P2 | dead-code-1, dead-code-2, dead-code-3, dead-code-4, dead-code-5, dead-code-6, dead-code-7 |
| `trade-trace-8m9b` (CL4) | Consolidate byte-identical duplicated report helpers | P2 | duplication-11, duplication-13, duplication-15 |
| `trade-trace-17ih` (CL5) | Consolidate lenient ISO-8601 report-timestamp parsing | P2 | duplication-14 |
| `trade-trace-bijy` (CL6) | Extract shared actor/instrument WHERE-clause filter builder | P2 | duplication-12 |
| `trade-trace-tnpv` (CL7) | Narrow broad `except Exception` clauses to project conventions | P2 | best-practice-28, best-practice-29, best-practice-30, best-practice-31 |
| `trade-trace-j7y0` (CL8) | Delete permanently-skipped 425-line legacy dogfood test module | P2 | stale-markers-18 |
| `trade-trace-vg6g` (CL9) | Apply 5 small simplifications | P3 | simplification-22, simplification-23, simplification-24, simplification-25, simplification-26 |
| `trade-trace-tyqp` (CL10) | Fix stale cli.py exit-code docstring | P3 | best-practice-27 |
| `trade-trace-i861` (CL11) | Remove stray `$(mktemp -d)` directory at repo root | P3 | stale-markers-20 |
| `trade-trace-5ikc` (CL12) | Resolve coach.py calibration_drift placeholder vs M2/M3 status | P3 | stale-markers-21 |
| `trade-trace-ppqp` (CL13) | Archive or prune historical next-steps.md roadmap | P3 | stale-markers-19 |
| `trade-trace-7ut3` (CL14) | Refactor copy-pasted ledger create-handler scaffold | P3 | duplication-16 |
| `trade-trace-7rlv` (CL15) | Add shared write-tool DB-lifecycle context manager | P3 | duplication-17 |

**Coverage: 34/34 candidates mapped** (5+1+7+3+1+1+4+1+5+1+1+1+1+1+1 = 34).

## Merge notes

- **CL1** merges the 5 `model.import` doc-drift items into one bead. The report author kept
  them distinct in the report with cross-references; for an executable backlog they are a single
  coherent edit (rename `src`→`path` across `_examples.py` schema example + README + memory-layer.md
  + security.md + PRD.md). All 5 file:line sites are listed in the bead. `journal.restore --src`
  is explicitly out of scope.
- **CL3** merges 7 independent dead-code deletions. `dead-code-1` (`_sensitive_sources`) requires a
  `git log -L` confirmation and `dead-code-7` (`clock.py`) must not break `tests/test_timestamps.py`'s
  `FixedClock` import — both flagged in the bead body.
- **CL4** consolidates 3 trivial byte-identical helpers; kept **separate** from CL5 (`duplication-14`,
  the lenient parser) per the report author's note that these address distinct helpers.
- **CL7** merges 4 `except Exception` narrowings (incl. the sqlite3 one in polymarket/config.py).
- **CL9** merges 5 trivial simplifications.

## Verification (graph + hygiene)

- `bd dep list trade-trace-vc5f` → gate blocked **by** all 15 children (`via blocks`) ✓
- `bd dep cycles` → none ✓
- `bd orphans` → none ✓
- `bd lint` → clean for all 16 cleanup beads ✓
- `bd ready --exclude-type epic` → all 15 children ready; gate correctly **not** ready ✓
- Open `cleanup-audit` beads: 17 (epic + 15 children + gate) ✓

## Implementation outcomes (2026-06-02)

The full `cleanup-audit` program was implemented and verified. Final gate `trade-trace-vc5f`
and epic `trade-trace-laow` closed. Quality gates on the whole tree: `ruff check src tests`
clean, `mypy src` clean (178 files), `pytest` **2218 passed / 7 skipped** (7 = opt-in perf
baselines, unrelated).

| Bead | Outcome | Notes |
|------|---------|-------|
| CL1 `exsb` | **Fixed** | Was a real schema↔handler mismatch (not mere doc drift): the schema is auto-derived from `example_minimal`, so `src` made the CLI flag `--src` while the handler required `path`. Made `path` canonical end-to-end; inverted the truthfulness guard (now forbids `--src`). |
| CL2 `i6v1` | **Fixed** | Removed unused `tenacity` dep + 2 false docstrings. |
| CL3 `joqs` | **Fixed** | Deleted 6 dead items; `clock.py` kept (tests import it) with corrected comment. |
| CL4 `8m9b` | **Fixed** | `_placeholders`/`_resolve_strategy_filter` → `_filter_support`; strict `_parse_ts` → canonical `timestamps`. |
| CL5 `17ih` | **Fixed** | 4 lenient parsers → exact canonical fns; **added 1 missing canonical** + parity tests. |
| CL6 `bijy` | **Fixed (2 of 3)** | Extracted `apply_actor_instrument_filters` for calibration + forecast_diagnostics; pm_native excluded (different shape, documented). |
| CL7 `tnpv` | **Fixed** | Narrowed 8 broad `except Exception` clauses. |
| CL8 `j7y0` | **Fixed** | Deleted the 425-line skipped dogfood module + corrected `dogfood-protocol.md`. |
| CL9 `vg6g` | **Fixed (4 of 5)** | Applied 4 simplifications; **rejected `simplification-25`** as not behavior-preserving (documented). |
| CL10 `tyqp` | **Fixed** | Corrected the stale cli.py exit-code docstring. |
| CL11 `i861` | **Fixed** | Removed the stray `$(mktemp -d)` dir. |
| CL12 `5ikc` | **Verified-intentional (no change)** | Drift detector is still-planned/partly-shipped (guarded by an `UNSUPPORTED_CAPABILITY` test); placeholder is correct per the finding's "leave as-is if planned" path. |
| CL13 `ppqp` | **Fixed** | Archived `next-steps.md` → `docs/history/` with a superseded banner; updated catalog ref + legacy-grep allowlist/test. |
| CL14 `7ut3` | **Won't-do (evaluated)** | `create_entity` callback abstraction is net-negative over 3 divergent handlers (replay emit/select ordering differs, distinct columns/payloads/returns, thesis supersedes edge) in safety-critical idempotency code; the safely-shared db-lifecycle was harvested by CL15. |
| CL15 `7rlv` | **Fixed (helper + seed)** | Added `db_for_args` context manager; migrated the 3 ledger create-handlers. Remaining ~27 modules' incremental migration tracked as follow-up `trade-trace-0hrq` (acceptance allowed "incrementally"). |

**Dispositions summary:** 11 fully fixed · 1 verified-intentional (CL12) · 1 won't-do with rationale
(CL14) · 2 sub-item carve-outs documented (CL6 pm_native, CL9 simplification-25) · 1 follow-up bead
filed (`trade-trace-0hrq`). Notable correctness catch: CL1 was a genuine broken-CLI bug, not doc drift.
