Context:
Domain: build-package-ci-release
Candidate: DEBT-003
Raw source: lane:0#ci-coverage-trigger-gap-002
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-0.md

Technical-debt claim:
Run quality gates before release tags, not only inside PyPI publish workflow

Evidence:
.github/workflows/workflow.yml triggers only on push tags v* while ruff/mypy/pytest live inside that publish workflow.

Carrying cost / risk:
Regressions can merge to main and be discovered only during publish; release job combines validation with packaging/publishing.

Target paydown:
Add PR/main CI or reusable test workflow; keep PyPI publish tag-gated.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: ops-deploy-debt, tooling-drift
- priority: P2
- risk: medium
- confidence: high
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- GitHub Actions workflow inspection
- ruff check src tests
- mypy src
- python3 -m pytest -q
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Run quality gates before release tags, not only inside PyPI publish workflow
- Paydown boundary followed: Add PR/main CI or reusable test workflow; keep PyPI publish tag-gated.
- Validation evidence: GitHub Actions workflow inspection; ruff check src tests; mypy src; python3 -m pytest -q
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-003 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-0.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-003.
