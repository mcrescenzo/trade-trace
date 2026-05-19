Context:
Domain: security-boundaries
Candidate: DEBT-041
Raw source: lane:7#SEC-07
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-7.md

Technical-debt claim:
Guard or scope runtime secret regex registration against ReDoS

Evidence:
security.patterns.register accepts arbitrary regex and scan_text/finditer over user text; no timeout/performance guard.

Carrying cost / risk:
Untrusted/pathological regex can make writes/redaction/export CPU-expensive if extension point is exposed.

Target paydown:
Decide trusted/test-only scope or add max source length/safe regex engine/scan caps; add static rejection or timeout tests.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.
- Do not alter public CLI/MCP semantics, migrate historical data, loosen security guarantees, or change product policy without an explicit design note and regression tests.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: investigation
- debt_class: security-hardening
- priority: P3
- risk: low
- confidence: medium
- justification: Track=investigation; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- Unit tests for rejected pathological/custom regex policy
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Guard or scope runtime secret regex registration against ReDoS
- Paydown boundary followed: Decide trusted/test-only scope or add max source length/safe regex engine/scan caps; add static rejection or timeout tests.
- Validation evidence: Unit tests for rejected pathological/custom regex policy
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-041 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-7.md.
- Compatibility/backfill/security blast radius is explicitly evaluated before implementation; if uncertain, stop at design/investigation output.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-041.
