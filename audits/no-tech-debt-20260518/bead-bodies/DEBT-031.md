Context:
Domain: test-harness-and-fixtures
Candidate: DEBT-031
Raw source: lane:6#candidate-2
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-6.md

Technical-debt claim:
Remove nested full-suite pytest subprocess from default dogfood verification test

Evidence:
test_final_dogfood_verification.py runs sys.executable -m pytest for the whole suite inside pytest; lane targeted run failed because inner collection hit unrelated security import error.

Carrying cost / risk:
One integration test duplicates CI, obscures failures, and multiplies runtime/blast radius.

Target paydown:
Move nested suite run to explicit marker/manual verification or replace with bounded dogfood contract assertions; fix stale comment.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: test-debt, maintenance-hotspot
- priority: P2
- risk: medium
- confidence: high
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/integration/test_final_dogfood_verification.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Remove nested full-suite pytest subprocess from default dogfood verification test
- Paydown boundary followed: Move nested suite run to explicit marker/manual verification or replace with bounded dogfood contract assertions; fix stale comment.
- Validation evidence: python3 -m pytest -q tests/integration/test_final_dogfood_verification.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-031 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-6.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-031.
