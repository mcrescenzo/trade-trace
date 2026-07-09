# Release notes

## Unreleased

### Removed public report tools

The 2026-07 report-catalog consolidation removed low-value pre-1.0 public
report tool names after the catalog census found no demonstrated agent-loop
value for them as standalone surfaces. Removed names are no longer registered;
current public tools are discoverable through `tool.schema` and the MCP tool
listing.

Disposition record:
[`audits/catalog-census-2026-07-07/disposition-matrix.md`](../audits/catalog-census-2026-07-07/disposition-matrix.md)

Implementation plan:
[`docs/superpowers/plans/2026-07-07-report-catalog-consolidation.md`](superpowers/plans/2026-07-07-report-catalog-consolidation.md)

Removed public names:

- `report.decision_velocity`
- `report.time_decay_sharpening`
- `report.rule_lineage`
- `report.process_analytics`
- `report.process_quality`
- `report.operational_health`
- `report.calibration_advisory`
- `report.calibration_anchored`
- `report.calibration_terminal`
- `report.compare`
- `report.filter_schema`
- `report.market_lifecycle`
- `report.mistake_tripwire`
- `report.policy_candidates`
- `report.resolution_misreads`
- `report.resolution_quality`
- `report.strengths`

### Internalized report modules

The following former public report names were removed from registration,
schema, and catalog surfaces, but their module logic remains available through
composed public reports:

- `report.lifecycle`
- `report.memory_usefulness`
- `report.calibration_integrity`
- `report.source_quality`
