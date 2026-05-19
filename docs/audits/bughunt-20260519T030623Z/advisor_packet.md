# Advisor evidence packet

Repo: /home/hermes/code/trade-trace
Epic: trade-trace-2d3
Mode: exhaustive repo bughunt, backlog-materialization.

Artifacts:
- manifest.json / coverage_ledger.json / domain_map.md in this directory
- lane-packets/*.md
- primary_evidence.txt
- candidate_matrix.json

Proposed accepted candidates: CAND-001..CAND-014. Merges/rejections recorded in candidate_matrix.json.

Duplicate handling: SECRET_PATTERNS collection blocker merged across storage/docs/tests lanes into CAND-003; playbook raw_filter merged into systemic ReportFilter CAND-006; memory.reflect duplicate-edge claim rejected and reframed as CAND-008 based on coordinator probe.

Primary evidence highlights:
- pytest collect-only: 827 collected then ImportError for exporter.SECRET_PATTERNS.
- targeted smoke/golden: two stale version failures.
- CLI malformed JSON: rc=1, stdout empty, raw stderr.
- config_set without confirm wrote config row.
- source.add note with secret-shaped string persisted and event payload contained secret.
- memory.reflect retry returned IDEMPOTENCY_CONFLICT diff_keys=[valid_from].
- static snippets for report filter, memory.reflect transactions, forecast.supersede two-phase, reflection prompt earliest forecast are in primary_evidence.txt.

Known caveats:
- Some candidates are static/data-integrity risks without failure-injection tests (forecast.supersede, memory.reflect atomicity, reflection prompt).
- The repo has adjacent untracked audits/no-tech-debt-20260518 and new docs/audits bughunt artifacts.
- Full pytest run is blocked by collection error, so later failures may remain hidden.
