Context:
Domain: reports-projections-export
Candidate: DEBT-028
Raw source: lane:5#candidate-8
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-5.md

Technical-debt claim:
Sanitize event_type before using it in JSONL export filenames

Evidence:
exporter.jsonl_path uses f"{event_type}-{event_id}.jsonl"; exporter accepts arbitrary event_type if upstream expands.

Carrying cost / risk:
Future event types with slash/path chars can create nested/unintended paths under export root.

Target paydown:
Allow/escape filename-safe event_type characters and test slash-containing event type.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: state-persistence-debt, security-hardening
- priority: P3
- risk: low
- confidence: high
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/integration/test_outbox_export.py tests/security/test_redacted_exports.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Sanitize event_type before using it in JSONL export filenames
- Paydown boundary followed: Allow/escape filename-safe event_type characters and test slash-containing event type.
- Validation evidence: python3 -m pytest -q tests/integration/test_outbox_export.py tests/security/test_redacted_exports.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-028 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-5.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-028.
