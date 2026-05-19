Context:
Domain: security-boundaries
Candidate: DEBT-038
Raw source: lane:7#SEC-04
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-7.md

Technical-debt claim:
Expand no-network default tests beyond journal.init/status/schema

Evidence:
no-network test monkeypatches socket connect/getaddrinfo but exercises only journal.init/status/schema; no registry-wide representative smoke or static import audit.

Carrying cost / risk:
Air-gap promise may regress in other tools without detection.

Target paydown:
Add registry-wide representative no-network smoke and static dependency audit for network libs/subprocess paths.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: security-hardening, test-debt
- priority: P2
- risk: medium
- confidence: high
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/security/test_no_network_default.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Expand no-network default tests beyond journal.init/status/schema
- Paydown boundary followed: Add registry-wide representative no-network smoke and static dependency audit for network libs/subprocess paths.
- Validation evidence: python3 -m pytest -q tests/security/test_no_network_default.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-038 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-7.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-038.
