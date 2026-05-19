Context:
Domain: docs-contract-truth
Candidate: DEBT-006
Raw source: lane:1#docs-contract-truth-003
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-1.md

Technical-debt claim:
Reconcile README/PRD vector dependency claims with pyproject and deferred embeddings posture

Evidence:
README/PRD say base wheel ships sqlite-vec/sentence-transformers after M3, while pyproject base deps only include pydantic and registry descriptions mark embeddings/model import/reindex as deferred/unsupported.

Carrying cost / risk:
Users/operators may expect unavailable vector deps or misunderstand default-off embeddings/air-gap posture.

Target paydown:
Align docs and packaging dependency declarations; link to existing embeddings beads where implementation remains deferred.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: docs-contract-drift, integration-provider-drift, config-drift
- priority: P2
- risk: medium
- confidence: medium
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- Inspect pyproject dependencies and registry tool descriptions; readback README/PRD
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Reconcile README/PRD vector dependency claims with pyproject and deferred embeddings posture
- Paydown boundary followed: Align docs and packaging dependency declarations; link to existing embeddings beads where implementation remains deferred.
- Validation evidence: Inspect pyproject dependencies and registry tool descriptions; readback README/PRD
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-006 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-1.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-006.
