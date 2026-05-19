# trade-trace-ftnu — Reconcile residual watch.stale docs with report.watchlist registry

Status: open
Type: bug
Priority: P3
Labels: bug, dead-code, deadcode-hunt, deadcode:refresh-20260519, docs-truth, domain:docs, domain:reports, stale-contract

## Description

Context:
Domain: docs/report contract truth.
Candidate: DC-REFRESH-004.

Dead-code / stale-contract claim:
Active docs/docstrings still advertise `watch.stale` even though the current tool registry exposes `report.watchlist` and no `watch.stale` tool.

Evidence:
- Live registry readback: `watch.stale` absent; `report.watchlist` present.
- `docs/PRD.md:87` says time-passing signals are generated lazily by `report.coach`, `watch.stale`, `report.unscored_forecasts`, or maintenance scan.
- `docs/PRD.md:368` lists `report.watchlist` and `watch.stale`.
- `docs/architecture/operability.md:57`, `docs/architecture/reports.md:269`, and `src/trade_trace/reports/watchlist.py:3` also mention `watch.stale`.

Reference search scope:
Tracked active docs/source and live registry, excluding audit artifacts for final judgement.

Reference search commands / output summary:
- `PYTHONPATH=src python3` registry enumeration -> `watch.stale False`, `report.watchlist True`.
- `git grep -n watch.stale -- ':!docs/audits/**' ':!audits/**'` -> active docs/source docstring hits.

Why it may be falsely alive:
`watch.stale` might be a planned future alias. If so, docs should label it future/planned or implementation should register/test it.

Impact / risk of keeping:
Agents/users can search for or invoke a nonexistent watch-stale command during operations.

Recommended action:
Reconcile docs/docstrings to the shipped `report.watchlist` surface or intentionally add/test `watch.stale`.

Safe-removal validation:
Registry readback plus grep for active `watch.stale` references after the fix.

Duplicate check:
Overlaps closed docs cleanup beads `trade-trace-ahz` and `trade-trace-17p`, but current residual `watch.stale` evidence remains and no open duplicate exists. The new bead should relate back to those historical beads.

## Steps to Reproduce
1. Run live registry readback and confirm `watch.stale` is absent while `report.watchlist` is present.
2. Grep active docs/source for `watch.stale` excluding audit artifacts.
3. Observe current docs/docstrings still present it as a shipped/current surface.

## Acceptance Criteria
- Active docs/docstrings no longer advertise `watch.stale` as shipped unless the tool is registered and tested.
- If retained as a future/planned alias, docs explicitly mark it future/deferred.
- Validation cites live registry readback and active-doc grep.

Provenance:
Discovered by repo-deadcode-hunt candidate DC-REFRESH-004 in docs/audits/deadcode-20260519T180524Z/candidate-matrix.json.


## Notes



## Acceptance

Active docs/docstrings no longer advertise watch.stale as shipped unless registered/tested; registry readback and grep validation attached.
