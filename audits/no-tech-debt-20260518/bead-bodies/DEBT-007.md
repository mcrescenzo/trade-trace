Context:
Domain: cli-mcp-contracts-tooling
Candidate: DEBT-007
Raw source: lane:2#candidate-1
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-2.md

Technical-debt claim:
Reject stray positional CLI tokens after valid command resolution

Evidence:
cli.py resolves longest command and _parse_kv_args skips non--- tokens; lane reproduction showed tt journal status unexpected-token returns ok=true rc=0.

Carrying cost / risk:
Malformed agent CLI calls can appear successful; CLI/MCP contract parity is weaker than expected.

Target paydown:
Reject leftover positional args with typed VALIDATION_ERROR JSON envelope while preserving --key parsing.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: tooling-drift, docs-contract-drift
- priority: P2
- risk: medium
- confidence: high
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- Targeted CLI contract test for unexpected positional token returns exit 2 JSON error
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Reject stray positional CLI tokens after valid command resolution
- Paydown boundary followed: Reject leftover positional args with typed VALIDATION_ERROR JSON envelope while preserving --key parsing.
- Validation evidence: Targeted CLI contract test for unexpected positional token returns exit 2 JSON error
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-007 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-2.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-007.
