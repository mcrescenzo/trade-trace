Context:
Domain: security-boundaries
Candidate: DEBT-002
Raw source: direct#validation-current pytest collection
Artifacts: audits/no-tech-debt-20260518/verification/validation-current.txt

Technical-debt claim:
Repair stale SECRET_PATTERNS import in redacted export security test

Evidence:
Full pytest collection fails: tests/security/test_redacted_exports.py imports SECRET_PATTERNS from trade_trace.exporter, but exporter.py no longer exports it.

## Steps to Reproduce
Run `python3 -m pytest -q --maxfail=5`; collection fails in tests/security/test_redacted_exports.py importing `SECRET_PATTERNS` from `trade_trace.exporter`.

Carrying cost / risk:
Default test suite cannot collect, hiding downstream regressions and weakening security-export coverage.

Target paydown:
Update test/import boundary to current security.patterns/exporter API or re-export intentionally; ensure redacted export tests collect.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: bug
- debt_class: test-debt, security-hardening
- priority: P1
- risk: high
- confidence: high
- justification: Track=bug; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/security/test_redacted_exports.py
- python3 -m pytest -q
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Repair stale SECRET_PATTERNS import in redacted export security test
- Paydown boundary followed: Update test/import boundary to current security.patterns/exporter API or re-export intentionally; ensure redacted export tests collect.
- Validation evidence: python3 -m pytest -q tests/security/test_redacted_exports.py; python3 -m pytest -q
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-002 and artifact refs audits/no-tech-debt-20260518/verification/validation-current.txt.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-002.
