Context:
Domain: security-boundaries
Candidate: DEBT-037
Raw source: lane:7#SEC-03
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-7.md

Technical-debt claim:
Clarify and harden export secret-warning and shareable-export boundary

Evidence:
export warnings include event_id/event_type/pattern names only, collapsing counts/locations; raw matches are safely omitted. DEBT-042 adds current raw JSONL export behavior is intentionally full-local but can be confused with shareable/redacted export.

Carrying cost / risk:
Operators get limited guidance to find/remediate affected local data.

Target paydown:
Add relative export path, pattern counts, offsets/JSON pointer paths or redacted snippets; assert raw values absent. Also fold DEBT-042: distinguish full_local_raw export from shareable/redacted export with result fields/docs/tests.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: observability-debt, security-hardening
- priority: P3
- risk: low
- confidence: high
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/security/test_redacted_exports.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Clarify and harden export secret-warning and shareable-export boundary
- Paydown boundary followed: Add relative export path, pattern counts, offsets/JSON pointer paths or redacted snippets; assert raw values absent.
- Validation evidence: python3 -m pytest -q tests/security/test_redacted_exports.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-037 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-7.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-037.
