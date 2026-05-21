# Repo audit materialization mutation audit — repo-audit-20260521T173511Z

- Epic: `trade-trace-4ju9`
- Gate: `trade-trace-6y4h`
- Finding map:
  - `CSS-20260521-001` -> `trade-trace-dlk6`
  - `CFB-20260521-001` -> `trade-trace-rtl6`
  - `THC-20260521-001` -> `trade-trace-bn02`
  - `THC-20260521-002` -> `trade-trace-beqe`
  - `DCR-20260521-001` -> `trade-trace-efkg`
- Coordinator downgraded `THC-20260521-003` to report-only/defer after advisor matrix gate.
- Beads command source: `bd create --body-file`, `bd dep relate`, `bd dep add` via local `bd version 1.0.3`.
- Matrix updated with materialized IDs: `candidate-matrix.json` and `candidate-matrix.yaml`.

## Post-materialization verification

- `bd dep list trade-trace-4ju9`: epic relates to all five finding beads plus closeout gate.
- `bd dep list trade-trace-6y4h`: gate relates to epic and is blocked by all five finding beads.
- `bd dep cycles`: no dependency cycles detected.
- `bd graph trade-trace-4ju9`: 7 issues across 2 layers; 5 blocking relationships into the closeout gate.
- `bd lint`: initial template warnings were repaired by adding `## Success Criteria` to the epic and `## Steps to Reproduce` to the three bug beads; rerun reports no template warnings.
- `bd orphans`: no orphaned issues found.
- Post-create duplicate scan: 23 mechanical pairs. New repo-audit pairs involving `trade-trace-beqe`, `trade-trace-rtl6`, and `trade-trace-dlk6` are false-positive similarity between audit findings with distinct root causes/validation paths; no merge performed.
- Moving-target preflight before mutation: HEAD remained `a1023ea4f2d498e916acbcbe25eecc0570d873bf`, branch `main`, ahead/behind `0/0`; only untracked audit artifacts under `docs/reviews/` were present.
