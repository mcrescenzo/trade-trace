Context:
Domain: domain-tools-ledger-memory-playbook
Candidate: DEBT-019
Raw source: lane:4#DTLMP-003
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-4.md

Technical-debt claim:
Add replay-safe idempotency to strategy.update

Evidence:
strategy.update accepts idempotency_key and emits strategy.updated, but unlike strategy.create does not call check_idempotency_replay before update.

## Steps to Reproduce
Call `strategy.update` twice with the same idempotency_key after a successful first update; current code does not call check_idempotency_replay before mutating.

Carrying cost / risk:
Retries can perform second UPDATE/new timestamp/event instead of returning original result.

Target paydown:
Check replay before mutation and return original row; add repeat-key regression.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: bug
- debt_class: state-persistence-debt, type-schema-debt
- priority: P1
- risk: high
- confidence: high
- justification: Track=bug; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/integration/test_strategy_tools.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Add replay-safe idempotency to strategy.update
- Paydown boundary followed: Check replay before mutation and return original row; add repeat-key regression.
- Validation evidence: python3 -m pytest -q tests/integration/test_strategy_tools.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-019 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-4.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-019.
