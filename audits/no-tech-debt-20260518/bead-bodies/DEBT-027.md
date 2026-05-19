Context:
Domain: reports-projections-export
Candidate: DEBT-027
Raw source: lane:5#candidate-7
Artifacts: audits/no-tech-debt-20260518/lane-reports/lane-5.md

Technical-debt claim:
Handle malformed event payload JSON per outbox row during export drain

Evidence:
drain_outbox json.loads(payload_json) occurs outside OSError handling; malformed payload can abort drain without row failure/error_text.

Carrying cost / risk:
One corrupt event payload can wedge export with repeated crash and no per-row state transition.

Target paydown:
Catch JSONDecodeError/non-dict per row; mark failed/increment attempt_count/error_text and continue.

Non-goals / boundaries:
- No broad rewrite; no unrelated behavior/product changes; preserve documented local/offline security boundaries unless this row explicitly revises docs.

Behavior/product boundary:
Pay down the named maintenance debt only; product feature expansion is out of scope unless routed as design/investigation.

Routing / classification:
- remediation_track: maintenance
- debt_class: state-persistence-debt, observability-debt
- priority: P2
- risk: medium
- confidence: high
- justification: Track=maintenance; disposition=accept; belongs here when accepted because it has evidence, carrying cost, bounded paydown, and validation path. Sibling workflow routing is recorded where track is bug/deadcode/simplification.

Risks / intentional-debt check:
No existing open bead fully covers this exact root cause based on current open-list and lane duplicate checks.

Validation:
- python3 -m pytest -q tests/integration/test_outbox_export.py tests/integration/test_jsonl_contract.py
Validation gap: not_applicable

Duplicate check:
Compared against existing open agent-ready/embeddings/bughunt/deadcode backlog and duplicate scan as of pre-mutation artifacts. Not a duplicate because: Accepted for Beads materialization.

Acceptance criteria:
- Debt claim is addressed specifically: Handle malformed event payload JSON per outbox row during export drain
- Paydown boundary followed: Catch JSONDecodeError/non-dict per row; mark failed/increment attempt_count/error_text and continue.
- Validation evidence: python3 -m pytest -q tests/integration/test_outbox_export.py tests/integration/test_jsonl_contract.py
- No unrelated cleanup/refactor/product expansion; public API/security/migration behavior stays within documented boundary or is covered by an explicit design decision.
- Bead/update cites repo-no-tech-debt candidate DEBT-027 and artifact refs audits/no-tech-debt-20260518/lane-reports/lane-5.md.

Provenance:
Discovered by repo-no-tech-debt run no-tech-debt-20260518; central matrix row DEBT-027.
