Context:
Domain: domain-tools-ledger-memory-playbook
Candidate: DEBT-020
Raw source: lane:4#DTLMP-004
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-4.md

Technical-debt claim:
Replace signal.scan JSON LIKE dedupe with structured related-ref matching

Evidence:
signals._already_signaled uses related_refs_json LIKE pattern; current compact dumps work but equivalent JSON formatting can bypass dedupe.

Carrying cost / risk:
Future signal producers/imports can duplicate logical signals; matching is brittle as refs grow.

Target paydown:
Use json_each/json_extract or bounded Python JSON comparison; test whitespace/reordered related_refs_json.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: state-persistence-debt, maintenance-hotspot
- priority: P3
- risk: low
- confidence: high
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/integration/test_signal_scan.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Replace signal.scan JSON LIKE dedupe with structured related-ref matching
- Paydown boundary followed: Use json_each/json_extract or bounded Python JSON comparison; test whitespace/reordered related_refs_json.
- Validation evidence: python3 -m pytest -q tests/integration/test_signal_scan.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-020 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-4.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-020.
