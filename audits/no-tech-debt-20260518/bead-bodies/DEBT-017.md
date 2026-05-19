Context:
Domain: domain-tools-ledger-memory-playbook
Candidate: DEBT-017
Raw source: lane:4#DTLMP-001
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-4.md

Technical-debt claim:
Make memory.reflect node + about-edge write truly atomic

Evidence:
memory.reflect docstring/docs claim one atomic operation, but implementation calls _memory_retain in one UnitOfWork then inserts about edge in a second UnitOfWork.

## Steps to Reproduce
Create a memory.reflect call where node retention succeeds and about-edge insertion/event emission fails; current implementation uses two UnitOfWork transactions so the reflection node can commit without the about edge.

Carrying cost / risk:
Failure between transactions can leave orphan reflection nodes despite no-orphan invariant.

Target paydown:
Refactor reflect to insert node/event/edge/event in one transaction; add forced-failure rollback test.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: bug
- debt_class: state-persistence-debt, test-debt
- priority: P1
- risk: high
- confidence: high
- justification: Track=bug; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/integration/test_memory_layer.py tests/integration/test_memory_link.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Make memory.reflect node + about-edge write truly atomic
- Paydown boundary followed: Refactor reflect to insert node/event/edge/event in one transaction; add forced-failure rollback test.
- Validation evidence: python3 -m pytest -q tests/integration/test_memory_layer.py tests/integration/test_memory_link.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-017 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-4.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-017.
