Context:
Domain: reports-projections-export
Candidate: DEBT-026
Raw source: lane:5#candidate-6
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-5.md

Technical-debt claim:
Capture one as_of clock instant inside report.watchlist

Evidence:
watchlist computes stale threshold, row ages, and as_of from multiple datetime.now/now_iso reads.

Carrying cost / risk:
Boundary stale tests can be flaky and report internals can be time-inconsistent.

Target paydown:
Capture one UTC instant at entry and pass through age/stale/as_of; add exact-threshold test.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: observability-debt, test-debt
- priority: P3
- risk: low
- confidence: high
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/integration/test_report_pnl_watchlist.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Capture one as_of clock instant inside report.watchlist
- Paydown boundary followed: Capture one UTC instant at entry and pass through age/stale/as_of; add exact-threshold test.
- Validation evidence: python3 -m pytest -q tests/integration/test_report_pnl_watchlist.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-026 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-5.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-026.
