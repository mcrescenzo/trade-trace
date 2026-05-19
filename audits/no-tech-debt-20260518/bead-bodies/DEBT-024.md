Context:
Domain: reports-projections-export
Candidate: DEBT-024
Raw source: lane:5#candidate-4
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-5.md

Technical-debt claim:
Propagate calibration record-id truncation to top-level/meta truncated flag

Evidence:
calibration groups can set truncated=True for capped record_ids but top-level return sets truncated False, so meta.truncated misses truncation.

## Steps to Reproduce
Create more than 1000 scored rows in a calibration group and run report.calibration; group truncated is true but top-level `truncated` remains false, so meta truncation is not propagated.

Carrying cost / risk:
Agents relying on envelope meta miss capped result data.

Target paydown:
Set top-level truncated when any group truncates; add >1000 scored rows contract test.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: bug
- debt_class: observability-debt, type-schema-debt
- priority: P2
- risk: medium
- confidence: high
- justification: Track=bug; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/integration/test_report_calibration.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Propagate calibration record-id truncation to top-level/meta truncated flag
- Paydown boundary followed: Set top-level truncated when any group truncates; add >1000 scored rows contract test.
- Validation evidence: python3 -m pytest -q tests/integration/test_report_calibration.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-024 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-5.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-024.
