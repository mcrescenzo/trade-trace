Context:
Domain: reports-projections-export
Candidate: DEBT-022
Raw source: lane:5#candidate-2
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-5.md

Technical-debt claim:
Define signed quantity convention and fix projection realized P&L sign coverage

Evidence:
projections.py realized_pnl += (price - avg_entry_price) * qty_delta; long open +100 close -100 at profit yields negative P&L under tests’ convention.

## Steps to Reproduce
Seed a long-like position with open quantity_delta=100 at 0.40 and close quantity_delta=-100 at 0.50, then rebuild projections; formula `(0.50 - 0.40) * -100` produces negative realized P&L for a profitable close.

Carrying cost / risk:
Derived positions/report.pnl can persist inverted realized P&L.

Target paydown:
Define signed convention and add rebuild tests for profitable/losing long and short closes.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: bug
- debt_class: state-persistence-debt, test-debt
- priority: P1
- risk: high
- confidence: medium
- justification: Track=bug; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/integration/test_report_pnl_watchlist.py tests/integration/test_projection_rebuild.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Define signed quantity convention and fix projection realized P&L sign coverage
- Paydown boundary followed: Define signed convention and add rebuild tests for profitable/losing long and short closes.
- Validation evidence: python3 -m pytest -q tests/integration/test_report_pnl_watchlist.py tests/integration/test_projection_rebuild.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-022 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-5.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-022.
