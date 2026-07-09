# Report Catalog Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a usage census over the tool catalog, then delete the ~17 report tools with no demonstrated agent value, shrinking the default public catalog from 103 tools toward ~82 and cutting the MCP tool-listing context cost.

**Architecture:** Three phases. Phase 1 builds an evidence census (mining dogfood run narratives, since dispatch tracing was never enabled) and turns on dispatch tracing for future empirical data. Phase 2 is a **user sign-off checkpoint** on a disposition matrix. Phase 3 executes deletions in coupled batches — distinguishing *full deletes* (leaf report: registry entry + handler module + tests + docs) from *registration-only deletes* (tool leaves the catalog; module survives because surviving tools compose it) — with quality gates green and doc-count literals updated after every batch.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy, SQLite journal (untouched), bd (beads) for task tracking.

## Global Constraints

- Quality gates for every commit: `ruff check src tests scripts && mypy src && pytest -q` — all green before each commit.
- Task tracking in `bd` (beads), NOT TodoWrite/markdown TODOs (per CLAUDE.md).
- `tests/docs/test_catalog_docs_truthfulness.py` derives expected counts from the live registry and checks hard-coded numerals in docs — **every batch that changes the catalog must update the doc literals in the same commit** (files listed in the Deletion Recipe).
- `tests/security/test_mvp_boundary_audit.py::test_shipped_public_tool_catalog_is_locked` pins the exact public tool-name **set** — every deletion edits `SHIPPED_REPORTS` in the same commit.
- Historical/point-in-time docs are NOT edited: `docs/history/**`, `docs/research/**`, `docs/ax-dogfood/runs/**`, `audits/**`. Only living docs (`README.md`, `docs/AGENT_GUIDE.md`, `docs/PRD.md`, `docs/RELEASE_FINAL_GATE.md`, `docs/architecture/**`) are updated.
- Write surfaces, event log, replay/import, and idempotency contracts are untouched — verified finding: report tools never appear as replay targets (imports.md §3.1 rejects read/report tools; jsonl-replay-taxonomy bucket D never dispatches reports).
- Scope guard: this plan deletes **report-family tools only**. Legacy (39) and experimental (5) tool culls, and the paper-trading unfreeze, are follow-up beads filed in Task 12, not work items here.
- Baseline numbers (verify at execution time, they may have drifted): 153 registered tools, 103 public catalog, 44 `report.*` tools, 5 experimental, "103" literals at `README.md:127`, `docs/AGENT_GUIDE.md:176`, `docs/RELEASE_FINAL_GATE.md:22`, `docs/architecture/v002-pm-pivot-catalog.md:526,566,572,584`.

---

## Background: verified facts this plan relies on

**Registration anatomy** (worked out for `report.decision_velocity`, the typical pattern): one `ReportToolRegistration(...)` tuple entry in `src/trade_trace/reports/tool_handlers/registration.py` (entries live in `_REPORT_TOOL_REGISTRATIONS`, lines 85–823); an MCP-facing wrapper in a `src/trade_trace/reports/tool_handlers/*.py` module; a schema entry in `src/trade_trace/reports/tool_schemas.py`; a filter-leaf entry in `src/trade_trace/reports/_filter_support.py` (`SUPPORTED_FILTER_FIELDS`); the handler module `src/trade_trace/reports/<name>.py`; re-exports in `src/trade_trace/reports/__init__.py`.

**Two report tools live outside `reports/`:** `report.paper_exposure` (`src/trade_trace/tools/paper_fills.py:317`) and `report.reconciliation_mismatches` (`src/trade_trace/tools/reconciliation.py:408`). Both are DEFER (phase-2 adjacent), so this doesn't bite — but any grep-based discovery must cover the whole `src/` tree anyway.

**Composition graph (why registration-only deletes exist):**

| Surviving consumer | Composes (module-level import) |
|---|---|
| `reports/bootstrap.py` | forecast_diagnostics, lifecycle, memory_usefulness, recall_receipts, strategy_health, work_queue |
| `reports/coach.py` | calibration_integrity, source_quality, unscored_forecasts, watchlist, tag_aggregates |
| `reports/work_queue.py`, `reports/lifecycle.py` | lifecycle helpers, `watchlist.DEFAULT_STALE_THRESHOLD_DAYS` |
| `reports/memory_usefulness.py` | recall_receipts |
| `reports/compare.py` | pnl, risk, calibration |
| `reports/autonomy_readiness.py` → `phase_gate_readiness.py` | phase_gate_readiness → audit_readiness |
| `tools/review_bundle.py` (`review.bundle`) | `reports/calibration.py`, `reports/recall_receipts.py` |
| `tools/market_similarity.py` (`market.find_similar`) | `reports/buckets.py` |

**Shared handlers:** `agent.bootstrap` / `agent.next_actions` / `playbook.adherence` (legacy-visible names) reuse the literal handler functions of `report.bootstrap` / `report.work_queue` / `report.playbook_adherence`. All three `report.*` targets are KEEP, so no action — but if the matrix ever flips one, the alias must be handled in the same commit.

**Legacy redirects are metadata-only:** `V002_FOLDED_OR_REMOVED` in `src/trade_trace/core.py` maps old names to new (e.g. `strategy.list` → `report.strategy_health`); `dispatch()` does no forwarding. Any entry pointing at a deleted tool must be updated to removed-guidance in the same commit.

**No dispatch data exists:** tracing is off by default (`TRADE_TRACE_DISPATCH_TRACE` unset everywhere, including `scripts/ax-dogfood/run.sh`); no `trace/dispatch.jsonl` exists under any journal home. The retroactive census source is the 63 run narratives in `docs/ax-dogfood/runs/*.md` plus `docs/ax-dogfood/registry.md`, `docs/architecture/dogfood-protocol.md`, and `docs/architecture/agent-continuity-scorecard.md`.

---

### Task 0: Create the bd epic and beads

**Files:** none (beads DB only).

**Interfaces:**
- Produces: an epic bead id (call it `EPIC`) that every later task's commit message and `bd close` references.

- [ ] **Step 1: Create the epic**

```bash
bd create --title="Report catalog consolidation: census + cull to ~14 public reports" \
  --description="Census tool usage from dogfood artifacts, sign off a disposition matrix, then delete ~17 report tools (full) and demote 4 to internal-only (registration delete). Shrinks public catalog 103 -> ~82. Plan: docs/superpowers/plans/2026-07-07-report-catalog-consolidation.md" \
  --type=epic --priority=1
```

- [ ] **Step 2: Create one bead per plan task (1–12), each depending on the epic; make Task 4 (checkpoint) block Tasks 5–12**

```bash
bd create --title="Census tooling: scripts/catalog_census.py + tests" --type=task --priority=1
bd create --title="Run census, commit artifacts under audits/catalog-census-2026-07-07/" --type=task --priority=1
bd create --title="Enable dispatch tracing in ax-dogfood harness" --type=task --priority=2
bd create --title="Disposition matrix + USER SIGN-OFF checkpoint" --type=task --priority=1
bd create --title="Document tool-removal policy in contracts.md/reports.md" --type=task --priority=1
bd create --title="Delete report.decision_velocity (worked example)" --type=task --priority=1
bd create --title="Delete batch: process/meta cluster (5 reports)" --type=task --priority=1
bd create --title="Delete batch: calibration variants (3 reports)" --type=task --priority=1
bd create --title="Delete batch: retrospective/misc cluster (8 reports)" --type=task --priority=1
bd create --title="Registration-only deletes: 4 composed reports -> internal" --type=task --priority=1
bd create --title="Docs truthfulness sweep + reports.md restructure" --type=task --priority=1
bd create --title="Final gate, MCP-size measurement, follow-up beads, push" --type=task --priority=1
```

Then wire dependencies (`bd dep add <child> <blocker>` — check exact syntax with `bd dep --help`): beads for Tasks 5–12 blocked by the Task-4 bead; all blocked by the epic.

- [ ] **Step 3: Claim the first bead** — `bd update <task1-id> --claim`

---

## Phase 1 — Census

### Task 1: Census tooling

**Files:**
- Create: `scripts/catalog_census.py`
- Test: `tests/integration/test_catalog_census.py`

**Interfaces:**
- Consumes: `trade_trace.core.default_registry()` (existing; `.by_name` dict, `.public_names()`).
- Produces: `tool_mention_counts(texts: Iterable[str], tool_names: Iterable[str]) -> Counter[str]` and `aggregate_dispatch_jsonl(lines: Iterable[str]) -> Counter[str]`, importable as `scripts.catalog_census` (script also runnable via `python scripts/catalog_census.py --output-dir ...`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/integration/test_catalog_census.py
"""Census tooling: tally registered-tool mentions in dogfood artifacts."""
import json

from scripts.catalog_census import aggregate_dispatch_jsonl, tool_mention_counts

NAMES = [
    "report.calibration",
    "report.calibration_integrity",
    "report.mistakes",
    "market.bind",
]


def test_counts_exact_tool_mentions() -> None:
    text = "ran report.calibration then market.bind, then report.calibration again"
    counts = tool_mention_counts([text], NAMES)
    assert counts["report.calibration"] == 2
    assert counts["market.bind"] == 1
    assert counts["report.mistakes"] == 0


def test_longer_name_is_not_double_counted_as_prefix() -> None:
    text = "report.calibration_integrity flagged nothing"
    counts = tool_mention_counts([text], NAMES)
    assert counts["report.calibration_integrity"] == 1
    assert counts["report.calibration"] == 0


def test_mentions_inside_paths_or_snake_prose_do_not_count() -> None:
    text = "see src/report.calibration_helpers.py and xreport.calibration"
    counts = tool_mention_counts([text], NAMES)
    assert counts["report.calibration"] == 0


def test_every_known_name_present_in_result_even_at_zero() -> None:
    counts = tool_mention_counts(["nothing here"], NAMES)
    assert set(counts.keys()) == set(NAMES)


def test_aggregate_dispatch_jsonl_counts_tool_field() -> None:
    lines = [
        json.dumps({"tool": "report.calibration", "ok": True}),
        json.dumps({"tool": "report.calibration", "ok": False}),
        json.dumps({"tool": "market.bind", "ok": True}),
        "not json at all",
    ]
    counts = aggregate_dispatch_jsonl(lines)
    assert counts["report.calibration"] == 2
    assert counts["market.bind"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/integration/test_catalog_census.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.catalog_census'` (if `scripts/` lacks an `__init__.py`, import via path is fine too — match how existing tests import from `scripts/`, or add `scripts/__init__.py` if none exists and conftest allows).

- [ ] **Step 3: Implement `scripts/catalog_census.py`**

```python
"""Catalog usage census: tally registered-tool mentions across dogfood artifacts.

Retroactive evidence source: dispatch tracing was never enabled during the
2026-06 dogfood runs, so the only historical usage signal is tool-name
mentions in the run narratives and protocol docs. Forward evidence source:
dispatch JSONL (see aggregate_dispatch_jsonl) once TRADE_TRACE_DISPATCH_TRACE
is enabled in the harness.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

DEFAULT_SOURCES = (
    "docs/ax-dogfood/runs",
    "docs/ax-dogfood/registry.md",
    "docs/architecture/dogfood-protocol.md",
    "docs/architecture/agent-continuity-scorecard.md",
)


def tool_mention_counts(
    texts: Iterable[str], tool_names: Iterable[str]
) -> Counter[str]:
    """Count exact-token mentions of each registered tool name.

    Boundary rules: a mention must not be preceded or followed by a word
    character, dot, underscore, or path separator, so
    ``report.calibration_integrity`` never also counts as
    ``report.calibration``, and file paths don't count.
    """
    names = list(tool_names)
    patterns = {
        name: re.compile(
            rf"(?<![\w./]){re.escape(name)}(?![\w.])"
        )
        for name in names
    }
    counts: Counter[str] = Counter({name: 0 for name in names})
    for text in texts:
        for name, pattern in patterns.items():
            counts[name] += len(pattern.findall(text))
    return counts


def aggregate_dispatch_jsonl(lines: Iterable[str]) -> Counter[str]:
    """Tally the ``tool`` field of dispatch-trace JSONL lines (forward path)."""
    counts: Counter[str] = Counter()
    for line in lines:
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        tool = record.get("tool") if isinstance(record, dict) else None
        if isinstance(tool, str) and tool:
            counts[tool] += 1
    return counts


def _gather_texts(repo_root: Path, sources: Iterable[str]) -> list[str]:
    texts: list[str] = []
    for source in sources:
        path = repo_root / source
        if path.is_dir():
            for child in sorted(path.glob("*.md")):
                texts.append(child.read_text(encoding="utf-8"))
        elif path.is_file():
            texts.append(path.read_text(encoding="utf-8"))
    return texts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dispatch-jsonl", default=None)
    args = parser.parse_args()

    from trade_trace.core import default_registry

    registry = default_registry()
    all_names = sorted(registry.by_name)
    public = set(registry.public_names())

    repo_root = Path(__file__).resolve().parent.parent
    texts = _gather_texts(repo_root, DEFAULT_SOURCES)
    counts = tool_mention_counts(texts, all_names)

    dispatch_counts: Counter[str] = Counter()
    if args.dispatch_jsonl:
        dispatch_path = Path(args.dispatch_jsonl)
        if dispatch_path.is_file():
            with dispatch_path.open(encoding="utf-8") as handle:
                dispatch_counts = aggregate_dispatch_jsonl(handle)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "tool": name,
            "public": name in public,
            "narrative_mentions": counts[name],
            "dispatch_count": dispatch_counts.get(name, 0),
        }
        for name in all_names
    ]
    (out / "census.json").write_text(
        json.dumps(rows, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "| tool | public | narrative mentions | dispatches |",
        "|---|---|---|---|",
    ]
    for row in sorted(
        rows, key=lambda r: (r["narrative_mentions"], r["dispatch_count"])
    ):
        lines.append(
            f"| {row['tool']} | {row['public']} | "
            f"{row['narrative_mentions']} | {row['dispatch_count']} |"
        )
    (out / "census.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out / 'census.json'} and {out / 'census.md'}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/integration/test_catalog_census.py -v`
Expected: 5 passed. If the `scripts.` import fails, check how existing tests reference `scripts/` (grep `-rn "from scripts" tests/` / `sys.path` fixtures in `tests/conftest.py`) and follow that pattern.

- [ ] **Step 5: Gates and commit**

```bash
ruff check src tests scripts && mypy src && pytest -q
git add scripts/catalog_census.py tests/integration/test_catalog_census.py
git commit -m "feat(census): add catalog usage census tooling (<task1-bead-id>)"
```

---

### Task 2: Run the census and commit artifacts

**Files:**
- Create: `audits/catalog-census-2026-07-07/census.json`, `audits/catalog-census-2026-07-07/census.md`

**Interfaces:**
- Consumes: `scripts/catalog_census.py` from Task 1.
- Produces: the evidence artifact Task 4's matrix cites.

- [ ] **Step 1: Run the census**

Run: `python scripts/catalog_census.py --output-dir audits/catalog-census-2026-07-07`
Expected: `wrote audits/catalog-census-2026-07-07/census.json and .../census.md`

- [ ] **Step 2: Sanity-check the output**

Run: `python - <<'EOF'`
```python
import json
rows = json.load(open("audits/catalog-census-2026-07-07/census.json"))
reports = [r for r in rows if r["tool"].startswith("report.")]
used = [r for r in reports if r["narrative_mentions"] > 0]
print(f"{len(reports)} report tools, {len(used)} with >=1 narrative mention")
for r in sorted(used, key=lambda r: -r["narrative_mentions"])[:15]:
    print(f"  {r['tool']}: {r['narrative_mentions']}")
EOF
```
Expected: `report.bootstrap`, `report.work_queue`, `report.calibration`, `report.unscored_forecasts`, `report.coach` near the top (they're named in the run narratives); ~31 report tools with ≥1 mention (registry.md cites 31 distinct names, many as friction reports rather than value — the matrix, not the raw count, decides). If the numbers are wildly different, investigate before proceeding.

- [ ] **Step 3: Commit**

```bash
git add audits/catalog-census-2026-07-07/
git commit -m "chore(census): catalog usage census artifacts (<task2-bead-id>)"
```

---

### Task 3: Enable dispatch tracing in the dogfood harness

**Files:**
- Modify: `scripts/ax-dogfood/run.sh` (env exports near the top, where other `TRADE_TRACE_*`/`export` lines live)

**Interfaces:**
- Produces: future dogfood runs append per-dispatch JSONL to `${TRADE_TRACE_HOME}/trace/dispatch.jsonl`, consumable by `aggregate_dispatch_jsonl` for the next (empirical) census.

- [ ] **Step 1: Confirm where env is set in the harness**

Run: `grep -n "TRADE_TRACE" scripts/ax-dogfood/run.sh scripts/ax-dogfood/setup.sh scripts/ax-dogfood/mcp.json`
Expected: existing `TRADE_TRACE_HOME` (or equivalent DB-home) configuration; no `DISPATCH_TRACE` hits.

- [ ] **Step 2: Add the export next to the existing env setup in `run.sh`**

```bash
# Per-dispatch usage tracing (catalog census evidence; JSONL only, never the journal DB)
export TRADE_TRACE_DISPATCH_TRACE=1
```

If the MCP server env comes from `mcp.json` rather than the shell, add `"TRADE_TRACE_DISPATCH_TRACE": "1"` to that file's `env` block instead — the dispatch path must see it. If `TRADE_TRACE_HOME` is NOT set in the harness, also export `TRADE_TRACE_DISPATCH_TRACE_PATH="$HOME/.trade-trace-axloop/trace/dispatch.jsonl"` (tracing is silently skipped without a resolvable path).

- [ ] **Step 3: Verify tracing activates**

Run (from repo root):
```bash
TRADE_TRACE_DISPATCH_TRACE=1 TRADE_TRACE_HOME=$(mktemp -d) python - <<'EOF'
import os
from trade_trace import dispatch_trace
print("enabled:", dispatch_trace.is_enabled())
EOF
```
Expected: `enabled: True`. (Exact API: check `src/trade_trace/dispatch_trace.py` — `is_enabled()` exists per investigation.)

- [ ] **Step 4: Gates and commit**

```bash
ruff check src tests scripts && pytest -q
git add scripts/ax-dogfood/
git commit -m "feat(ax-dogfood): enable dispatch tracing for usage census (<task3-bead-id>)"
```

---

## Phase 2 — Disposition matrix and checkpoint

### Task 4: Disposition matrix + USER SIGN-OFF (hard checkpoint)

**Files:**
- Create: `audits/catalog-census-2026-07-07/disposition-matrix.md`

**Interfaces:**
- Consumes: `census.json` (Task 2), the provisional matrix below.
- Produces: the signed-off matrix that defines exactly which reports Tasks 6–10 touch. **No deletion task may start before the user approves this file.**

- [ ] **Step 1: Write `disposition-matrix.md`** — start from the provisional matrix below, then adjust rows where the census contradicts it (a report with heavy narrative usage should not stay DELETE without a stated reason; a KEEP with zero mentions anywhere should be flagged). Every row cites its evidence: census count + whether the dogfood protocol/scorecard names it + composition edges.

**Provisional disposition matrix (all 44 report tools):**

| # | Tool | Disposition | Rationale |
|---|---|---|---|
| 1 | report.bootstrap | KEEP | Continuity tier; scorecard-exercised; `agent.bootstrap` alias shares handler |
| 2 | report.calibration | KEEP | Core scoreboard; dogfood-protocol-exercised; composed by compare, review.bundle |
| 3 | report.coach | KEEP | Dogfood-protocol-exercised; composes 4 hygiene reports |
| 4 | report.forecast_diagnostics | KEEP | Scorecard-exercised; composed by bootstrap |
| 5 | report.mistakes | KEEP | Dogfood-protocol-exercised (pattern-recognition criteria) |
| 6 | report.open_positions | KEEP | Money/position truth |
| 7 | report.pnl | KEEP | Money truth; composed by compare |
| 8 | report.playbook_adherence | KEEP | Dogfood-protocol-exercised; `playbook.adherence` alias calls it |
| 9 | report.recall_receipts | KEEP | Scorecard-exercised; composed by bootstrap, memory_usefulness, review.bundle |
| 10 | report.risk | KEEP | Risk truth; composed by compare |
| 11 | report.strategy_health | KEEP | Scorecard-exercised; legacy `strategy.list/show` redirect target |
| 12 | report.unscored_forecasts | KEEP | Session-obligation surface; dogfood-exercised; composed by coach |
| 13 | report.watchlist | KEEP | Composed by coach; stale-idea continuity; registry-cited |
| 14 | report.work_queue | KEEP | Scorecard-exercised; `agent.next_actions` alias shares handler |
| 15 | report.calibration_integrity | REG-ONLY DELETE | Coach composes it; standalone tool never dogfood-exercised directly |
| 16 | report.lifecycle | REG-ONLY DELETE | Bootstrap/work_queue compose it; standalone tool redundant with work_queue |
| 17 | report.memory_usefulness | REG-ONLY DELETE | Bootstrap composes it; meta-meta as a standalone tool |
| 18 | report.source_quality | REG-ONLY DELETE | Coach composes it; standalone tool never dogfood-exercised directly |
| 19 | report.calibration_advisory | DELETE | Calibration variant; one narrative mention (2026-06-06 run); folds into calibration |
| 20 | report.calibration_anchored | DELETE | Experimental-cluster variant |
| 21 | report.calibration_terminal | DELETE | Variant; no dogfood evidence |
| 22 | report.compare | DELETE | Retrospective trend; composes pnl/risk/calibration (kept modules unaffected); no dogfood evidence |
| 23 | report.decision_velocity | DELETE | Meta-telemetry; no dogfood evidence; worked example (Task 6) |
| 24 | report.filter_schema | DELETE | Meta; `tool.schema` covers discovery |
| 25 | report.market_lifecycle | DELETE | Overlaps lifecycle/work_queue; no dogfood evidence |
| 26 | report.mistake_tripwire | DELETE | Speculative variant of mistakes |
| 27 | report.operational_health | DELETE | Substrate telemetry |
| 28 | report.policy_candidates | DELETE | Speculative governance feeder |
| 29 | report.process_analytics | DELETE | Meta-meta; overlaps process_quality |
| 30 | report.process_quality | DELETE | Meta-meta; overlaps process_analytics |
| 31 | report.resolution_misreads | DELETE | Speculative variant of resolution_quality/mistakes |
| 32 | report.resolution_quality | DELETE | No dogfood evidence; mistakes covers the lesson loop |
| 33 | report.rule_lineage | DELETE | Meta-meta provenance browsing; playbook rows carry provenance already |
| 34 | report.strengths | DELETE | Mirror of mistakes with no evidence of use (shared `tag_aggregates` helper stays — mistakes and coach use it) |
| 35 | report.time_decay_sharpening | DELETE | Meta-telemetry; no dogfood evidence |
| 36 | report.audit_readiness | DEFER | Composed by phase_gate_readiness; governance trio — owner call |
| 37 | report.autonomy_readiness | DEFER | Phase-3 gate evidence; actively maintained (commit 72f1561); owner call |
| 38 | report.current_exposure | DEFER | Phase-2 adjacent (execution surface is the next epic) |
| 39 | report.execution_quality | DEFER | Phase-2 adjacent |
| 40 | report.exposure_anomalies | DEFER | Phase-2 adjacent |
| 41 | report.opportunity | DEFER | Decision-time market analysis; phase-2 adjacent |
| 42 | report.paper_exposure | DEFER | Phase-2 adjacent; lives in `tools/paper_fills.py` |
| 43 | report.phase_gate_readiness | DEFER | Governance trio — owner call |
| 44 | report.reconciliation_mismatches | DEFER | Phase-2 adjacent; lives in `tools/reconciliation.py` |

DEFER rows are decided by the owner at this checkpoint: either fold into KEEP (do nothing) or into DELETE (add to Task 9's batch, or the paper-trading epic decides later). Default if undecided: keep, revisit in the paper-trading epic.

- [ ] **Step 2: Commit the matrix** — `git add audits/catalog-census-2026-07-07/disposition-matrix.md && git commit -m "docs(census): disposition matrix for report cull (<task4-bead-id>)"`

- [ ] **Step 3: STOP — present the matrix to the user and get explicit sign-off.** Record the sign-off (date + any row changes) at the top of `disposition-matrix.md` in a follow-up commit. Do not start Task 5+ without it. Final tallies below assume the provisional matrix (17 DELETE, 4 REG-ONLY): public catalog 103 → 82. Recompute if sign-off changes rows.

---

## Phase 3 — Execution

### The Deletion Recipe (referenced by Tasks 6–9)

For each report `<name>` (module `src/trade_trace/reports/<name>.py`, tool `report.<name>`):

1. **Discover the full footprint** (line numbers rot between batches — always re-grep):
   ```bash
   grep -rn "<name>" src tests README.md docs/AGENT_GUIDE.md docs/PRD.md \
     docs/RELEASE_FINAL_GATE.md docs/architecture/ scripts/
   ```
2. **Registry surface:** remove the `ReportToolRegistration("report.<name>", ...)` entry and its handler import from `src/trade_trace/reports/tool_handlers/registration.py`; remove the `_report_<name>` wrapper (and its import) from the `tool_handlers/*.py` module that holds it; remove the `"report.<name>"` entry from `src/trade_trace/reports/tool_schemas.py`; remove the `"report.<name>"` key from `SUPPORTED_FILTER_FIELDS` in `src/trade_trace/reports/_filter_support.py`.
3. **Module (full deletes only):** `git rm src/trade_trace/reports/<name>.py`; remove its import/`__all__` lines from `src/trade_trace/reports/__init__.py`; remove any stray re-import in `tool_handlers/common.py`. **First verify nothing composes it:** `grep -rn "from trade_trace.reports.<name>\|from trade_trace.reports import.*<name>\|from \.<name>\|from \. import.*<name>" src/` must return only the files you are deleting/editing in this step. Non-empty remainder → it's REG-ONLY, stop and fix the matrix.
4. **Redirect hygiene:** `grep -n "report.<name>" src/trade_trace/core.py` — if a `V002_FOLDED_OR_REMOVED` entry points at it, change the entry to removed-guidance (follow the existing convention in that table for removed tools); update narrative comments mentioning it.
5. **Tests:** delete the dedicated test module/blocks; remove parametrize-table rows (`tests/contracts/test_report_envelope_completeness.py`, `tests/integration/test_report_filter.py`, `tests/security/test_report_sql_filters.py`, `tests/security/test_no_network_default.py`, `tests/integration/test_reproducibility_replay.py`); remove the name from `SHIPPED_REPORTS` (and any other pinned set) in `tests/security/test_mvp_boundary_audit.py`; check `tests/contracts/test_report_tool_registration_catalog.py` ordering pins.
6. **Docs (living docs only):** remove the name from the `docs/architecture/reports.md` intro enumeration and its `## 4.x` metric-schema subsection if one exists (do not renumber siblings); edit shared unfreeze-history prose to drop the name; remove enumeration lines in `docs/architecture/v002-pm-pivot-catalog.md` and mentions in `docs/PRD.md`.
7. **Count literals (once per batch, batch of size N):** decrement the public-count numerals by N in `README.md:~127`, `docs/AGENT_GUIDE.md:~176`, `docs/RELEASE_FINAL_GATE.md:~22`, `docs/architecture/v002-pm-pivot-catalog.md:~526,566,572,584`. `tests/docs/test_catalog_docs_truthfulness.py` verifies them against the live registry — run it explicitly.
8. **Gates:** `ruff check src tests scripts && mypy src && pytest -q` — green.
9. **Commit:** one commit per batch, message `refactor(reports)!: delete <names> (census cull, <bead-id>)`.

### Task 5: Document the tool-removal policy

**Files:**
- Modify: `docs/architecture/contracts.md` (§8 versioning area), `docs/architecture/reports.md` (§3.0 area)

**Interfaces:** none downstream; this legitimizes the hard-deletes that follow (the project's practice to date is alias-and-hide — this is a deliberate, documented departure).

- [ ] **Step 1: Add a "Tool removal (pre-1.0)" subsection to `contracts.md` §8**, following that file's prose style:

> During 0.0.x pre-release, tools with no demonstrated usage may be removed outright rather than aliased: the registry entry, schemas, and docs are deleted in the same change, and the removal is recorded in the release notes with the census evidence that justified it. Removed names return `NOT_FOUND` from dispatch. Post-1.0, removals revert to the rename/alias/deprecation-window contract above. Read-only report tools are never replay targets (imports.md §3.1), so removals never affect JSONL import/replay.

- [ ] **Step 2: Add one cross-reference sentence in `reports.md` §3.0** pointing at the new contracts.md subsection, and note the 2026-07-07 census cull with a pointer to `audits/catalog-census-2026-07-07/`.

- [ ] **Step 3: Gates and commit** — `pytest tests/docs -q` (docs truthfulness must still pass; counts unchanged so far), then `git add docs/architecture/contracts.md docs/architecture/reports.md && git commit -m "docs(contracts): document pre-1.0 tool-removal policy (<task5-bead-id>)"`

### Task 6: Worked example — delete `report.decision_velocity`

**Files (verified footprint as of plan date; re-grep at execution, lines rot):**
- Delete: `src/trade_trace/reports/decision_velocity.py`
- Modify: `src/trade_trace/reports/__init__.py` (lines ~36, ~122), `src/trade_trace/reports/tool_schemas.py` (~392–395), `src/trade_trace/reports/_filter_support.py` (~172–177), `src/trade_trace/reports/tool_handlers/common.py` (~37, dead import), `src/trade_trace/reports/tool_handlers/calibration_diagnostics.py` (~22 import, ~265–290 wrapper), `src/trade_trace/reports/tool_handlers/registration.py` (~30 import, ~431–440 entry), `src/trade_trace/core.py` (~362–373 narrative comment)
- Tests: `tests/integration/test_report_unscored_velocity.py` (docstring + lines ~100–178 — keep the `unscored_forecasts` half!), `tests/security/test_report_sql_filters.py` (~123–134), `tests/integration/test_reproducibility_replay.py` (~161–163), `tests/security/test_no_network_default.py` (~109, ~180), `tests/security/test_mvp_boundary_audit.py` (`SHIPPED_REPORTS` entry; `UNFROZEN_MEMORY_PROCESS_REPORTS` set — remove `"report.decision_velocity"`, keep the other two members and the test), `tests/integration/test_report_filter.py` (~213–214), `tests/contracts/test_report_envelope_completeness.py` (~98)
- Docs: `docs/architecture/reports.md` (intro list lines ~16, 20, 24 — edit shared trio prose, no 4.x section exists for this one), `docs/PRD.md` (~387), `docs/architecture/v002-pm-pivot-catalog.md` (~33, 118, 276, 288) + count literals per Recipe step 7 (103 → 102)

**Interfaces:**
- Consumes: signed-off matrix (Task 4), removal policy (Task 5).
- Produces: the validated recipe; public catalog count 102.

- [ ] **Step 1: Claim the bead** — `bd update <task6-bead-id> --claim`
- [ ] **Step 2: Run Recipe step 1 (discovery grep); confirm the footprint matches the list above** (investigate any extra hits before deleting)
- [ ] **Step 3: Apply Recipe steps 2–4** (registry surface, module delete, core.py comment). Composition check per Recipe step 3 must come back clean — nothing composes decision_velocity (verified at plan time).
- [ ] **Step 4: Apply Recipe step 5 (tests) and step 6 (docs), step 7 (count literals −1)**
- [ ] **Step 5: Gates** — `ruff check src tests scripts && mypy src && pytest -q` → all green; then explicitly `pytest tests/docs/test_catalog_docs_truthfulness.py tests/security/test_mvp_boundary_audit.py -v` → PASS
- [ ] **Step 6: Verify the tool is gone from the catalog**

```bash
python -c "
from trade_trace.core import default_registry
names = default_registry().public_names()
assert 'report.decision_velocity' not in names, 'still present'
print(len(names), 'public tools')  # expect 102
"
```

- [ ] **Step 7: Commit** — `git add -A && git commit -m "refactor(reports)!: delete report.decision_velocity (census cull, <task6-bead-id>)"`, `bd close <task6-bead-id>`

### Task 7: Batch — process/meta cluster (5 full deletes)

`report.time_decay_sharpening`, `report.rule_lineage`, `report.process_analytics`, `report.process_quality`, `report.operational_health`

- [ ] **Step 1: Claim bead; apply the Deletion Recipe to all five** (Recipe steps 1–6 per report; step 7 once: count literals −5 → 97). Watch for: `rule_lineage` has a `4.16` section in reports.md; `memory_usefulness` shares prose with this cluster but is REG-ONLY (Task 10) — edit shared prose to drop only these five names.
- [ ] **Step 2: Composition check per report** (Recipe step 3) — all five are leaves per the plan-time graph; a non-empty grep means the matrix was wrong: stop, update matrix, re-confirm with user.
- [ ] **Step 3: Gates green; catalog count check** (expect 97); **commit**; `bd close`.

### Task 8: Batch — calibration variants (3 full deletes)

`report.calibration_advisory`, `report.calibration_anchored`, `report.calibration_terminal`

- [ ] **Step 1: Claim bead; apply the Recipe** (count literals −3 → 94). Watch for: `core.py`'s `EXPERIMENTAL_ANCHORED_VIEWERS` narrative and any experimental-visibility wiring — if any of the three is registered `experimental` rather than public (check `default_registry().public_names()` membership first), the public count decrements by fewer than 3 and the "5 experimental" literals (README ~127, v002 catalog ~572) change instead. Recompute both counts from the registry and make docs match: `pytest tests/docs -q` is the oracle.
- [ ] **Step 2: reports.md — keep `4.1 calibration` intact; the anchored/terminal pair shares unfreeze prose — remove it.** Composition check: `compare.py` imports `calibration` (kept), not the variants (verified at plan time; re-verify).
- [ ] **Step 3: Gates green; commit; `bd close`.**

### Task 9: Batch — retrospective/misc cluster (8 full deletes)

`report.compare`, `report.filter_schema`, `report.market_lifecycle`, `report.mistake_tripwire`, `report.policy_candidates`, `report.resolution_misreads`, `report.resolution_quality`, `report.strengths`

- [ ] **Step 1: Claim bead; apply the Recipe** (count literals −8 → 86). Special cases:
  - `compare`: composes pnl/risk/calibration — deleting `compare.py` removes the *consumer*, safe; its `4.7` reports.md section goes too.
  - `strengths`: shares `tag_aggregates.load_mistakes_and_strengths` with `mistakes` and `coach` — delete the strengths tool/module surface but NOT `tag_aggregates`; `mistakes`' shared `4.3` docs section is edited (drop strengths), not deleted.
  - `filter_schema`: its handler enumerates `SUPPORTED_FILTER_FIELDS` — deleting it removes the last *external* consumer of that table's completeness, but kept reports still read their own entries; leave the table (minus deleted keys, per Recipe step 2).
  - `market_lifecycle`/`resolution_quality`: share unfreeze prose in reports.md (pair block) — remove the block.
- [ ] **Step 2: Composition check per report; gates green; catalog count check (expect 86); commit; `bd close`.**

### Task 10: Registration-only deletes (4 tools → internal modules)

`report.lifecycle`, `report.memory_usefulness`, `report.calibration_integrity`, `report.source_quality`

**Files:** registration.py entries + wrappers + tool_schemas.py entries + `_filter_support.py` keys + catalog pins in `test_mvp_boundary_audit.py` + docs enumerations/4.x sections + count literals (−4 → 82). **Do NOT delete** `src/trade_trace/reports/{lifecycle,memory_usefulness,calibration_integrity,source_quality}.py` — bootstrap/coach/work_queue compose them.

- [ ] **Step 1: Claim bead; apply Recipe steps 1–2 and 4–7 only (skip step 3 module deletion).** Add one line to each surviving module's docstring: `Internal-only since 2026-07 census cull: composed by report.bootstrap/report.coach; not a registered tool.`
- [ ] **Step 2: Keep (or move) tests that exercise the module logic *through* the composing tool.** Dedicated tool-level tests (envelope/registration/dispatch tests for the four names) are deleted; pure-function tests of the module logic stay if they don't dispatch the removed tool name. `report.bootstrap` and `report.coach` integration tests must still pass unchanged — they are the proof the internals survived.
- [ ] **Step 3: Verify composition still works end-to-end**

```bash
python -c "
from trade_trace.core import default_registry
r = default_registry()
names = r.public_names()
for gone in ('report.lifecycle','report.memory_usefulness','report.calibration_integrity','report.source_quality'):
    assert gone not in names, gone
for kept in ('report.bootstrap','report.coach','report.work_queue'):
    assert kept in names, kept
print(len(names), 'public tools')  # expect 82
"
```
Then run the bootstrap/coach integration tests explicitly: `pytest tests/integration -k "bootstrap or coach or work_queue" -v` → PASS.

- [ ] **Step 4: Gates green; commit; `bd close`.**

### Task 11: Docs truthfulness sweep + reports.md restructure

**Files:**
- Modify: `docs/architecture/reports.md`, `README.md`, `docs/AGENT_GUIDE.md`, `docs/PRD.md`, `docs/architecture/v002-pm-pivot-catalog.md`, `docs/RELEASE_FINAL_GATE.md`

- [ ] **Step 1: Full-text sweep for stragglers**

```bash
for name in decision_velocity time_decay_sharpening rule_lineage process_analytics \
  process_quality operational_health calibration_advisory calibration_anchored \
  calibration_terminal compare filter_schema market_lifecycle mistake_tripwire \
  policy_candidates resolution_misreads resolution_quality strengths; do
  grep -rn "report\.$name" src tests README.md docs/AGENT_GUIDE.md docs/PRD.md \
    docs/RELEASE_FINAL_GATE.md docs/architecture/ scripts/ && echo "STRAGGLER: $name"
done
```
Expected: no output except (a) the removal-policy note and census artifacts, (b) `disposition-matrix.md`. Historical dirs (`docs/history`, `docs/research`, `docs/ax-dogfood`, `audits/`) are exempt and not in the sweep. Fix any straggler.

- [ ] **Step 2: reports.md coherence pass** — read the intro enumeration and §4 top-to-bottom once: the shipped list must equal the 14 KEEP + any DEFER rows kept; the four REG-ONLY modules get one sentence in the bootstrap/coach sections noting they're internal composition, not tools. Verify final counts one more time against `python -c "from trade_trace.core import default_registry; print(len(default_registry().public_names()))"`.
- [ ] **Step 3: Add a release-notes entry** (wherever the repo tracks unreleased changes — check for `CHANGELOG*`/release-notes convention; `docs/RELEASE_CHECKLIST.md` knows) listing all removed tool names + census pointer, per the Task 5 policy.
- [ ] **Step 4: Gates green (`pytest tests/docs -q` especially); commit; `bd close`.**

### Task 12: Final gate, measurement, follow-ups, push

- [ ] **Step 1: Full gates** — `ruff check src tests scripts && mypy src && pytest -q` → all green. Also `bd doctor` if available.
- [ ] **Step 2: Measure the win (before/after MCP listing size)**

```bash
python - <<'EOF'
import json
from trade_trace.core import default_registry
r = default_registry()
listing = [r.by_name[n].metadata() for n in r.public_names()]
print("public tools:", len(listing))
print("serialized listing bytes:", len(json.dumps(listing)))
EOF
```
Record before (run on the pre-cull commit via `git stash` or a worktree) and after in the epic bead's notes. Expected: ~82 public tools; listing bytes down roughly proportionally (~20%).

- [ ] **Step 3: File follow-up beads** (do not implement):
  - "Legacy tool cull: evaluate the 39 legacy-visibility tools for removal under the pre-1.0 removal policy" (P2)
  - "Experimental tool review: approval.* + forecast.anchor_to_snapshot — promote or remove" (P3)
  - "DEFER reports disposition: decide the 9 deferred report tools inside the paper-trading epic" (P2, blocked by the paper-trading epic)
  - "Paper-trading unfreeze epic: plan Phase-2 surface activation + Polymarket adapter hardening" (P1 — the original product intent; plan separately)
  - "Re-run catalog census from dispatch JSONL after 2+ weeks of traced dogfood runs; validate the cull empirically" (P2)
- [ ] **Step 4: Close the epic's completed beads; session-close protocol** (per CLAUDE.md — mandatory for this mutating session):

```bash
git pull --rebase
bd dolt push
git push
git status   # MUST show "up to date with origin"
```

- [ ] **Step 5: Hand off** — summarize in the epic bead: final counts, listing-bytes delta, any matrix rows changed at sign-off, link to census artifacts.

---

## Self-review notes (plan author)

- **Census caveat surfaced honestly:** narrative mentions ≠ dispatches; a mention can be a friction complaint. The matrix (human-judged, evidence-cited), not the raw count, decides — and Task 3 + the follow-up bead make the *next* cull empirical.
- **Counts are provisional:** all "103/102/97/94/86/82" figures assume the provisional matrix and plan-date registry; `test_catalog_docs_truthfulness` + the registry one-liners are the runtime oracle at every step, not this document.
- **Line numbers rot:** only Task 6 pins lines (verified at plan date); every other task discovers via grep by design.
- **Riskiest step:** Task 10 (registration-only). Mitigated by explicit composition graph, module-preservation instruction, and the bootstrap/coach integration tests as the proof gate.
