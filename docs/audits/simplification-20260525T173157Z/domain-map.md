# Trade Trace simplification domain map

Review run: `trade-trace-simplification-20260525T173157Z`
Repo: `/home/hermes/code/trade-trace`
Commit: `d37136e9684138d9f9540f2a71860f36eba354f5`

Domains reviewed:

- `contracts-cli-mcp`: `src/trade_trace/cli.py`, `src/trade_trace/mcp_server.py`, contract/golden tests. Lenses: transport validation drift, schema duplication, parity contracts.
- `storage-events-models`: event writer/exporter, projection rebuild, semantic/event registries, storage migrations. Lenses: row hydration duplication, replay/idempotency, registry overlap, intentional audit/security explicitness.
- `tools-ledger-memory-workflows`: ledger source attachment, memory workflows, playbook handlers/predicates, strategy/forecast residuals. Lenses: transactional write kernels, validation boilerplate, evaluator query duplication, prior-backlog overlap.
- `reports-reporting`: report registration, read-model pagination, exposure handlers, timestamp parsing variants, report contracts. Lenses: registration metadata sprawl, cursor contract duplication, temporal validation duplication, compatibility semantics.
- `adapter-market-security`: Polymarket adapter/client, market bind/refresh, market scan schema, endpoint/security tests. Lenses: serializer/projection drift, retry loop duplication, public schema/action drift, security boundary preservation.
- `tests-docs-release`: test helpers, docs/release command surfaces, docs truth. Lenses: prior closed simplification overlap, intentional local fixtures, no additive candidates.

Complexity lenses used: structure, duplication, abstraction/pass-through, deadness/reachability caveats, contract drift, testability, behavior preservation.

Blind spots/caveats:
- Review is static plus targeted tests; no broad implementation refactors were performed.
- Prior closed simplification work means this run intentionally materializes only additive/delta candidates.
- Security-sensitive and behavior-heavy candidates are bounded with characterization/golden-test acceptance or investigation labels.
