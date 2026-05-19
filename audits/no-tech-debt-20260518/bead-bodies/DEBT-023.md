Context:
Domain: reports-projections-export
Candidate: DEBT-023
Raw source: lane:5#candidate-3
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-5.md

Technical-debt claim:
Preserve true source_quality diagnostic counts before sample truncation

Evidence:
source_quality._bundle computes truncated then slices items and returns count=len(items), so >100 matches report count=100.

## Steps to Reproduce
Create more than MAX_SAMPLE_IDS source-quality diagnostic rows and run source_quality; current `_bundle` slices to MAX_SAMPLE_IDS before returning `count`, so count is capped instead of true total.

Carrying cost / risk:
Observability undercounts large hygiene problems; future rate/summary math unreliable.

Target paydown:
Return total_count separately from capped sample_ids; add >MAX_SAMPLE_IDS test.

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
- python3 -m pytest -q tests/integration/test_source_quality.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Preserve true source_quality diagnostic counts before sample truncation
- Paydown boundary followed: Return total_count separately from capped sample_ids; add >MAX_SAMPLE_IDS test.
- Validation evidence: python3 -m pytest -q tests/integration/test_source_quality.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-023 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-5.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-023.
