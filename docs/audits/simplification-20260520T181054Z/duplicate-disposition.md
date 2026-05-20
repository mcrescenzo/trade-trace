# Duplicate disposition — simplification 20260520

Final duplicate scan command:

```bash
bd find-duplicates --status open --threshold 0.45 --limit 100 --json
```

Result: 3 mechanical pairs, all pre-existing and outside the newly-created `simplification:20260520` rows.

## Pairs

1. `trade-trace-evwe` ↔ `trade-trace-73zr` (similarity 0.5476)
   - Theme: agent-native ergonomics / tool metadata inventory.
   - Disposition: pre-existing overlap inside agent-ergonomics program. No SIMP20 row created for CLI/MCP schema/example/error candidates; those were explicitly merged into this existing program family.

2. `trade-trace-mtdp` ↔ `trade-trace-iixm` (similarity 0.4655)
   - Theme: final verification vs root epic for agent-native workbench ergonomics.
   - Disposition: expected epic/final-gate mechanical similarity; unrelated to simplification materialization.

3. `trade-trace-9t48` ↔ `trade-trace-evwe` (similarity 0.4643)
   - Theme: decision.add matrix and tool metadata/schema/actionability.
   - Disposition: pre-existing agent-ergonomics overlap. No SIMP20 row duplicates it; SIMP20 CLI/MCP findings were merged/deferred to this existing work.

## SIMP20 duplicate posture

- No newly-created `simplification:20260520` bead appears in the threshold 0.45 duplicate scan.
- Lower-threshold scans are noisy because Beads descriptions share safety/validation templates; semantic dedupe source of truth is `candidate-matrix.md`.
- Residual overlaps with closed 2026-05-19 simplification beads are intentionally routed through `trade-trace-2drt` rather than creating duplicate implementation beads.
