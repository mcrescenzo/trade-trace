Context:
Domain: build-package-ci-release
Candidate: DEBT-001
Raw source: lane:0#build-ci-version-smoke-drift-001 + lane:6#candidate-1
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-0.md

Technical-debt claim:
Fix stale hard-coded package version assertions in smoke/golden tests

Evidence:
pyproject.toml:7 and src/trade_trace/version.py report 0.0.1rc0 while tests/test_smoke.py:9 and tests/golden/test_journal_status_parity.py:70 assert 0.0.1; targeted pytest shows both failures.

## Steps to Reproduce
Run `python3 -m pytest -q tests/test_smoke.py tests/golden/test_journal_status_parity.py --maxfail=3`; both tests assert package version `0.0.1` while pyproject/version.py are `0.0.1rc0`.

Carrying cost / risk:
Release/test gates fail after version bump; version truth duplicated across tests.

Target paydown:
Centralize version expectation from package/project metadata or update contract intentionally; avoid duplicated literal release versions.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: bug
- debt_class: test-debt, tooling-drift
- priority: P1
- risk: high
- confidence: high
- justification: Track=bug; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/test_smoke.py tests/golden/test_journal_status_parity.py
- python3 -m pytest -q
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Fix stale hard-coded package version assertions in smoke/golden tests
- Paydown boundary followed: Centralize version expectation from package/project metadata or update contract intentionally; avoid duplicated literal release versions.
- Validation evidence: python3 -m pytest -q tests/test_smoke.py tests/golden/test_journal_status_parity.py; python3 -m pytest -q
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-001 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-0.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-001.
