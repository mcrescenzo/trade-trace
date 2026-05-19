# Repo simplification materialization audit

- Epic: trade-trace-mea1
- Repo: /home/hermes/code/trade-trace
- HEAD at materialization: 898d25d68c2ca8f31bbf9ff0694ef2e34ace0b74
- User authorization: Michael said, "dont worry about those other lanes, you may materialize this epic."
- Prior mode: report-only fallback because repo/Beads state moved during review.
- Current action: reopened existing epic and materialized only accepted/accept-merged/accept-tightened/accept-as-investigation rows.
- Deferred/rejected rows were preserved as dispositions and not materialized.
- Artifact root: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z
- ID map: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z/candidate_to_bead_map.json
- Pre-snapshot: /home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z/pre_materialization_snapshot.txt

Graph model:
- Non-blocking `bd dep relate trade-trace-mea1 <child>` for epic membership.
- Candidate rows block QC gates.
- QC gates block final verification.
- Epic remains narrative/root index, not executable proof of completion.

Counts:
- Direct simplification tasks: 11
- Investigation/design-first tasks: 5
- QC gates: 4
- Final gate: 1
