Context:
Domain: storage-persistence-events-schema
Candidate: DEBT-011
Raw source: lane:3#candidate-1
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-3.md

Technical-debt claim:
Harden events table with SQLite append-only triggers

Evidence:
migrations.py creates events/outbox but append-only trigger list omits events; test_append_only omits events while events are durable audit log.

Carrying cost / risk:
Primary audit stream can be altered/deleted by direct SQLite write access, weakening replay/export/idempotency forensics.

Target paydown:
Add migration for events BEFORE UPDATE/DELETE triggers while keeping outbox mutable; test both.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.
- Do not alter public CLI/MCP semantics, migrate historical data, loosen security guarantees, or change product policy without an explicit design note and regression tests.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: design
- debt_class: state-persistence-debt, migration-schema-debt
- priority: P1
- risk: high
- confidence: high
- justification: Track=design; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/integration/test_append_only.py tests/integration/test_jsonl_replay_readiness.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Harden events table with SQLite append-only triggers
- Paydown boundary followed: Add migration for events BEFORE UPDATE/DELETE triggers while keeping outbox mutable; test both.
- Validation evidence: python3 -m pytest -q tests/integration/test_append_only.py tests/integration/test_jsonl_replay_readiness.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-011 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-3.md.
- Compatibility/backfill/security blast radius is explicitly evaluated before implementation; if uncertain, stop at design/investigation output.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-011.
