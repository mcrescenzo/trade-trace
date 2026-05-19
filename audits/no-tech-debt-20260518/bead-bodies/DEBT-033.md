Context:
Domain: test-harness-and-fixtures
Candidate: DEBT-033
Raw source: lane:6#candidate-4
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-6.md

Technical-debt claim:
Make scoring “property” tests exercise production behavior or rename them

Evidence:
tests/property/test_scoring_properties.py tests inline brier_binary reference with fixed random samples, not production scoring/autoscore/report code; no Hypothesis dependency.

Carrying cost / risk:
Gives impression of property coverage while production scoring regressions could pass.

Target paydown:
Either rename as reference/example tests or route properties through production scoring/report outputs; add Hypothesis only if intentionally adopted.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: test-debt
- priority: P3
- risk: low
- confidence: high
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/property tests/integration/test_scoring_lifecycle.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Make scoring “property” tests exercise production behavior or rename them
- Paydown boundary followed: Either rename as reference/example tests or route properties through production scoring/report outputs; add Hypothesis only if intentionally adopted.
- Validation evidence: python3 -m pytest -q tests/property tests/integration/test_scoring_lifecycle.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-033 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-6.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-033.
