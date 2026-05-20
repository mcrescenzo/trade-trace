# Mutation audit — deadcode hunt 2026-05-20

## Planned materialization
- Epic: to be created.
- Candidate beads: DC-20260520-001, -002, -005, -006.
- Final verification gate: to be created after candidate IDs are known.
- Merged existing docs candidate: DC-20260520-003 plus DC-20260520-004 appended to existing open docs-QC bead `trade-trace-r1mt`; no new duplicate docs bead.

## Pre-mutation live snapshot

```text
HEAD/STATUS
73aee82
## main...origin/main

OPEN
● trade-trace-3i77 [● P1] [task] [agent-native agent-workbench-ergonomics beta-feedback product-ergonomics trade-trace] - Complete report, memory, and playbook schema/actionability contracts (blocked by: trade-trace-ozpg, blocks: trade-trace-i1dy, trade-trace-mtdp, trade-trace-qorh, trade-trace-r1mt, trade-trace-zgea)
○ trade-trace-73zr [● P1] [task] [agent-native agent-workbench-ergonomics beta-feedback product-ergonomics trade-trace] - Inventory agent-facing contract drift and beta dogfood evidence (blocks: trade-trace-mtdp, trade-trace-ozpg)
● trade-trace-9t48 [● P1] [task] [agent-native agent-workbench-ergonomics beta-feedback product-ergonomics trade-trace] - Expose decision.add matrix and actionable recovery guidance (blocked by: trade-trace-ozpg, blocks: trade-trace-mtdp, trade-trace-qorh, trade-trace-r1mt, trade-trace-zgea)
● trade-trace-evwe [● P1] [task] [agent-native agent-workbench-ergonomics beta-feedback product-ergonomics trade-trace] - Unify self-describing tool metadata, CLI help, schemas, and errors (blocked by: trade-trace-ozpg, blocks: trade-trace-j0f8, trade-trace-mtdp, trade-trace-qorh, trade-trace-r1mt, trade-trace-zgea)
● trade-trace-i1dy [● P2] [feature] [agent-native agent-workbench-ergonomics beta beta-feedback dogfood feature-request investigate product-opportunity review trade-trace] - Improve low-sample learning-loop report actionability (blocked by: trade-trace-3i77, blocks: trade-trace-mtdp, trade-trace-qorh, trade-trace-r1mt)
○ trade-trace-iixm [● P1] [epic] [agent-native agent-workbench-ergonomics beta-feedback epic product-ergonomics trade-trace] - Agent-native workbench ergonomics hardening from beta feedback
● trade-trace-j0f8 [● P2] [feature] [agent-native agent-workbench-ergonomics beta beta-feedback dogfood feature-request investigate product-opportunity review trade-trace] - Add lightweight capture-now enrich-later flow for market ideas (blocked by: trade-trace-evwe, trade-trace-ozpg, blocks: trade-trace-mtdp, trade-trace-qorh, trade-trace-r1mt)
● trade-trace-mtdp [● P1] [task] [agent-native agent-workbench-ergonomics beta-feedback product-ergonomics trade-trace] - Final verification for agent-native workbench ergonomics hardening (blocked by: trade-trace-3i77, trade-trace-73zr, trade-trace-9t48, trade-trace-evwe, trade-trace-i1dy, trade-trace-j0f8, trade-trace-ozpg, trade-trace-qorh, trade-trace-r1mt, trade-trace-zgea)
● trade-trace-ozpg [● P1] [decision] [agent-native agent-workbench-ergonomics beta-feedback product-ergonomics trade-trace] - Decide v1 agent-workbench ergonomics defaults (blocked by: trade-trace-73zr, blocks: trade-trace-3i77, trade-trace-9t48, trade-trace-evwe, trade-trace-j0f8, trade-trace-mtdp)
● trade-trace-qorh [● P1] [task] [agent-native agent-workbench-ergonomics beta-feedback product-ergonomics trade-trace] - Add agent smoothness dogfood evals for help/schema-guided loops (blocked by: trade-trace-3i77, trade-trace-9t48, trade-trace-evwe, trade-trace-i1dy, trade-trace-j0f8, trade-trace-zgea, blocks: trade-trace-mtdp, trade-trace-r1mt)
● trade-trace-r1mt [● P1] [task] [agent-native agent-workbench-ergonomics beta-feedback product-ergonomics trade-trace] - Review and update docs/generated examples for agent-facing contracts (blocked by: trade-trace-3i77, trade-trace-9t48, trade-trace-evwe, trade-trace-i1dy, trade-trace-j0f8, trade-trace-qorh, trade-trace-zgea, blocks: trade-trace-mtdp)
● trade-trace-zgea [● P2] [feature] [agent-native agent-workbench-ergonomics beta beta-feedback dogfood feature-request investigate product-opportunity review trade-trace] - Add guided journal bundle and next-action affordances (blocked by: trade-trace-3i77, trade-trace-9t48, trade-trace-evwe, blocks: trade-trace-mtdp, trade-trace-qorh, trade-trace-r1mt)


DUPES
{
  "count": 13,
  "method": "mechanical",
  "pairs": [
    {
      "issue_a_id": "trade-trace-evwe",
      "issue_a_title": "Unify self-describing tool metadata, CLI help, schemas, and errors",
      "issue_b_id": "trade-trace-73zr",
      "issue_b_title": "Inventory agent-facing contract drift and beta dogfood evidence",
      "method": "mechanical",
      "similarity": 0.5476360918909897
    },
    {
      "issue_a_id": "trade-trace-mtdp",
      "issue_a_title": "Final verification for agent-native workbench ergonomics hardening",
      "issue_b_id": "trade-trace-iixm",
      "issue_b_title": "Agent-native workbench ergonomics hardening from beta feedback",
      "method": "mechanical",
      "similarity": 0.46545640148269724
    },
    {
      "issue_a_id": "trade-trace-9t48",
      "issue_a_title": "Expose decision.add matrix and actionable recovery guidance",
      "issue_b_id": "trade-trace-evwe",
      "issue_b_title": "Unify self-describing tool metadata, CLI help, schemas, and errors",
      "method": "mechanical",
      "similarity": 0.46426029390988344
    },
    {
      "issue_a_id": "trade-trace-3i77",
      "issue_a_title": "Complete report, memory, and playbook schema/actionability contracts",
      "issue_b_id": "trade-trace-evwe",
      "issue_b_title": "Unify self-describing tool metadata, CLI help, schemas, and errors",
      "method": "mechanical",
      "similarity": 0.41072813157236776
    },
    {
      "issue_a_id": "trade-trace-i1dy",
      "issue_a_title": "Improve low-sample learning-loop report actionability",
      "issue_b_id": "trade-trace-zgea",
      "issue_b_title": "Add guided journal bundle and next-action affordances",
      "method": "mechanical",
      "similarity": 0.40128093932957654
    },
    {
      "issue_a_id": "trade-trace-9t48",
      "issue_a_title": "Expose decision.add matrix and actionable recovery guidance",
      "issue_b_id": "trade-trace-73zr",
      "issue_b_title": "Inventory agent-facing contract drift and beta dogfood evidence",
      "method": "mechanical",
      "similarity": 0.3932781174973835
    },
    {
      "issue_a_id": "trade-trace-3i77",
      "issue_a_title": "Complete report, memory, and playbook schema/actionability contracts",
      "issue_b_id": "trade-trace-73zr",
      "issue_b_title": "Inventory agent-facing contract drift and beta dogfood evidence",
      "method": "mechanical",
      "similarity": 0.3916628600746178
    },
    {
      "issue_a_id": "trade-trace-ozpg",
      "issue_a_title": "Decide v1 agent-workbench ergonomics defaults",
      "issue_b_id": "trade-trace-iixm",
      "issue_b_title": "Agent-native workbench ergonomics hardening from beta feedback",
      "method": "mechanical",
      "similarity": 0.3899340129736095
    },
    {
      "issue_a_id": "trade-trace-j0f8",
      "issue_a_title": "Add lightweight capture-now enrich-later flow for market ideas",
      "issue_b_id": "trade-trace-zgea",
      "issue_b_title": "Add guided journal bundle and next-action affordances",
      "method": "mechanical",
      "similarity": 0.3877391005407303
    },
    {
      "issue_a_id": "trade-trace-mtdp",
      "issue_a_title": "Final verification for agent-native workbench ergonomics hardening",
      "issue_b_id": "trade-trace-qorh",
      "issue_b_title": "Add agent smoothness dogfood evals for help/schema-guided loops",
      "method": "mechanical",
      "similarity": 0.3749943648987272
    },
    {
      "issue_a_id": "trade-trace-qorh",
      "issue_a_title": "Add agent smoothness dogfood evals for help/schema-guided loops",
      "issue_b_id": "trade-trace-evwe",
      "issue_b_title": "Unify self-describing tool metadata, CLI help, schemas, and errors",
      "method": "mechanical",
      "similarity": 0.36551047866776665
    },
    {
      "issue_a_id": "trade-trace-r1mt",
      "issue_a_title": "Review and update docs/generated examples for agent-facing contracts",
      "issue_b_id": "trade-trace-iixm",
      "issue_b_title": "Agent-native workbench ergonomics hardening from beta feedback",
      "method": "mechanical",
      "similarity": 0.3532608514799518
    },
    {
      "issue_a_id": "trade-trace-qorh",
      "issue_a_title": "Add agent smoothness dogfood evals for help/schema-guided loops",
      "issue_b_id": "trade-trace-3i77",
      "issue_b_title": "Complete report, memory, and playbook schema/actionability contracts",
      "method": "mechanical",
      "similarity": 0.3520769172750359
    }
  ],
  "schema_version": 1,
  "threshold": 0.35
}

CYCLES

✓ No dependency cycles detected
```

## Applied ID map
{
  "epic": "trade-trace-frd0",
  "final_gate": "trade-trace-4hr9",
  "candidates": {
    "DC-20260520-001": "trade-trace-hdlx",
    "DC-20260520-002": "trade-trace-0apb",
    "DC-20260520-005": "trade-trace-kq8y",
    "DC-20260520-006": "trade-trace-bh7q"
  },
  "merged_existing": {
    "DC-20260520-003": "trade-trace-r1mt",
    "DC-20260520-004": "trade-trace-r1mt"
  }
}

## Command log
Saved at `mutation-command-log.json`.
