# Duplicate disposition

`bd find-duplicates --status open --threshold 0.45` reported many mechanical pairs among the newly created bughunt beads. These are title/lexical overlaps, not root-cause duplicates, after coordinator comparison by failure mode and fix surface.

Disposition:
- trade-trace-85i vs trade-trace-re4: both mention two-transaction/atomicity risk, but one is memory.reflect reflection-edge atomicity and the other is forecast.supersede forecast-lineage atomicity. Separate fix/test surfaces.
- trade-trace-m8c vs trade-trace-vwa: both are test failures, but missing exporter.SECRET_PATTERNS blocks collection while stale version expectations fail smoke/golden after collection. Separate root causes.
- trade-trace-e62 vs trade-trace-85i: both touch memory.reflect, but one is idempotent retry conflict from default valid_from and the other is static atomicity/orphan-risk from two UnitOfWork scopes. Separate validation paths.
- trade-trace-17p vs trade-trace-1zl: both docs bugs, but one is nonexistent CLI commands and the other is broken relative links. Separate docs surfaces.
- trade-trace-jky vs trade-trace-m8c: both security-adjacent, but one is write-time source secret persistence and the other is missing exporter alias/test collection. Separate fixes.
- Remaining high-similarity pairs are mechanical overlaps from shared bughunt labels/terms such as CLI, contract, missing, test, transaction, and source. They remain intentionally separate beads.

Merged before materialization:
- Whole pytest collection blocker was merged into trade-trace-m8c / CAND-003.
- Playbook raw_filter-specific candidate was merged into trade-trace-ke1 / CAND-006.
- Nonexistent `tt init`/`tt mcp` docs candidate was merged into trade-trace-17p / CAND-012.

Rejected before materialization:
- The delegated claim that memory.reflect idempotent replay creates duplicate about edges was rejected after coordinator probe. The live probe showed one edge and an `IDEMPOTENCY_CONFLICT`; the materialized bug is trade-trace-e62 for the retry conflict, not duplicate edges.
