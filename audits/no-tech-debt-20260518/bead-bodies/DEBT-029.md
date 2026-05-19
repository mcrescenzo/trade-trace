Context:
Domain: reports-projections-export
Candidate: DEBT-029
Raw source: lane:5#candidate-9
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-5.md

Technical-debt claim:
Clarify low-level report output metric semantics for playbook adherence and P&L coverage

Evidence:
group sample_size counts distinct decisions, summary sample_size counts adherence rows and duplicates total_adherence_rows. DEBT-030 adds report.pnl data_coverage denominator includes closed positions, making mark coverage misleading.

Carrying cost / risk:
Same field name has inconsistent meaning inside one report envelope.

Target paydown:
Change summary.sample_size to distinct decisions or rename field; add one-decision/multiple-rule test. Also fold DEBT-030: rename or compute pnl data_coverage/open_mark_coverage with tests for closed/open positions.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: observability-debt, type-schema-debt
- priority: P3
- risk: low
- confidence: high
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/integration/test_playbook_layer.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Clarify low-level report output metric semantics for playbook adherence and P&L coverage
- Paydown boundary followed: Change summary.sample_size to distinct decisions or rename field; add one-decision/multiple-rule test.
- Validation evidence: python3 -m pytest -q tests/integration/test_playbook_layer.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-029 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-5.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-029.
