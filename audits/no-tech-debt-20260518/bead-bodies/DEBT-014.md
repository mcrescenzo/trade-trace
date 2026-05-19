Context:
Domain: storage-persistence-events-schema
Candidate: DEBT-014
Raw source: lane:3#candidate-4
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-3.md

Technical-debt claim:
Add storage-level timestamp invariant coverage or explicit delegation policy

Evidence:
timestamps.py enforces UTC helper behavior, but SQLite schema stores *_at TEXT without CHECK/triggers; direct DB paths can persist malformed timestamps.

Carrying cost / risk:
Lexicographic ordering and bi-temporal filters can misbehave if future importer/fixture bypasses helper.

Target paydown:
Choose DB CHECK/triggers or explicit API-only invariant plus schema-audit tests for critical timestamp columns.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.
- Do not alter public CLI/MCP semantics, migrate historical data, loosen security guarantees, or change product policy without an explicit design note and regression tests.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: design
- debt_class: type-schema-debt, migration-schema-debt
- priority: P2
- risk: medium
- confidence: medium
- justification: Track=design; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/test_timestamps.py tests/integration/test_schema.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Add storage-level timestamp invariant coverage or explicit delegation policy
- Paydown boundary followed: Choose DB CHECK/triggers or explicit API-only invariant plus schema-audit tests for critical timestamp columns.
- Validation evidence: python3 -m pytest -q tests/test_timestamps.py tests/integration/test_schema.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-014 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-3.md.
- Compatibility/backfill/security blast radius is explicitly evaluated before implementation; if uncertain, stop at design/investigation output.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-014.
