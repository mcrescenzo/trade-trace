Context:
Exhaustive repo simplification review for `/home/hermes/code/trade-trace` at commit `d37136e9684138d9f9540f2a71860f36eba354f5` on branch `main`, clean at preflight.

Scope:
Full repo review after prior closed simplification backlogs. This epic indexes only additive/delta simplification candidates that preserve behavior or require investigation before refactor.

Simplification rule:
Candidates must have concrete code evidence, a complexity cost, bounded refactor/investigation shape, behavior-preservation criteria, validation command or explicit gap, and duplicate/overlap disposition.

Reject list:
Pure style, LOC-only rewrites, broad behavior changes, prior-covered residuals, security/policy changes disguised as simplification, and refactors without validation.

Navigation:
- Matrix: `docs/audits/simplification-20260525T173157Z/candidate-matrix.json`
- Domain map: `docs/audits/simplification-20260525T173157Z/domain-map.md`
- Lane reports: `docs/audits/simplification-20260525T173157Z/lane-packets/`
- Query: `bd list --status open --flat --limit 0 --sort id | grep simplification:20260525`

Graph rule:
This epic indexes work via relation links and labels. Dependencies are only used for the final verification gate depending on downstream candidate beads.
