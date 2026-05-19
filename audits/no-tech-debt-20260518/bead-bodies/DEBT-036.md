Context:
Domain: security-boundaries
Candidate: DEBT-036
Raw source: lane:7#SEC-02
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-7.md

Technical-debt claim:
Cover explicit metadata_json credential injection in no-credentials policy

Evidence:
tests pass credential-shaped unknown top-level args, but _store_metadata_json accepts caller-provided JSON/string unchanged; metadata_json={api_key:...} is not tested.

## Steps to Reproduce
Pass credential-shaped values inside explicit `metadata_json`, including nested object or raw JSON string, through write tools covered by no-credentials policy; current `_store_metadata_json` returns/stores caller JSON unchanged.

Carrying cost / risk:
No-credential guarantee can be bypassed via metadata_json and exported in events/JSONL.

Target paydown:
Decide reject/sanitize/document metadata_json credentials; add nested/string metadata_json tests.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: bug
- debt_class: security-hardening, test-debt
- priority: P1
- risk: high
- confidence: high
- justification: Track=bug; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/security/test_no_credentials.py tests/security/test_secret_pattern_writes.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Cover explicit metadata_json credential injection in no-credentials policy
- Paydown boundary followed: Decide reject/sanitize/document metadata_json credentials; add nested/string metadata_json tests.
- Validation evidence: python3 -m pytest -q tests/security/test_no_credentials.py tests/security/test_secret_pattern_writes.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-036 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-7.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-036.
