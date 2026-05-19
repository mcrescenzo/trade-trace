Context:
Domain: reports-projections-export
Candidate: DEBT-021
Raw source: lane:5#candidate-1
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-5.md

Technical-debt claim:
Define and enforce supported ReportFilter semantics per report

Evidence:
Many reports validate/echo ReportFilter but apply only tiny subset or none; callers can believe scoped reports were computed over global data.

Carrying cost / risk:
Misleading normalized_filter creates agent/reporting errors and repeated validate-but-ignore pattern.

Target paydown:
Add shared compiler or explicit supported-filter declarations/rejections; tests seed disjoint actors/instruments/strategies/time windows.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.
- Do not alter public CLI/MCP semantics, migrate historical data, loosen security guarantees, or change product policy without an explicit design note and regression tests.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: design
- debt_class: type-schema-debt, test-debt
- priority: P1
- risk: high
- confidence: high
- justification: Track=design; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/integration/test_report_filter.py tests/security/test_report_sql_filters.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Define and enforce supported ReportFilter semantics per report
- Paydown boundary followed: Add shared compiler or explicit supported-filter declarations/rejections; tests seed disjoint actors/instruments/strategies/time windows.
- Validation evidence: python3 -m pytest -q tests/integration/test_report_filter.py tests/security/test_report_sql_filters.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-021 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-5.md.
- Compatibility/backfill/security blast radius is explicitly evaluated before implementation; if uncertain, stop at design/investigation output.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-021.
