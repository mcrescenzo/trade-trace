# Advisor Critique of Research Program Conclusions

**Date:** 2026-05-22  
**Review bead:** `trade-trace-sytd`  
**Advisor mode:** independent critical review via `advisor_deliberate(mode=review)`  
**Status:** Research review only — no implementation approval

## 1. Advisor Verdict

Advisor consensus status: **partial**.

The advisor found the program conclusions **closeable as research-only direction-setting**, but not safe to treat as implementation-ready architecture or final product decision without additional caveats in the final decision packet.

The key advisor warning:

> The final decision must approve only concept priority, non-goals, and research synthesis. It must not imply implementation readiness, external-source truth, schema approval, or product completeness.

## 2. Blockers Identified

These are not blockers to closing this advisor-review bead. They are blockers to closing the final decision packet (`trade-trace-gwv4`) unless resolved there.

| Blocker | Advisor concern | Required resolution before `trade-trace-gwv4` closes |
|---|---|---|
| Confidence/scope ambiguity | “Must-have/foundational” can overstate evidence quality given partial external verification and doc/source drift. | Final decision packet must include confidence labels and state that adoption is product-direction research, not implementation approval. |
| Replay/regression ambiguity | “Core but later-stage” is muddy. Core to what? MVP or evaluation architecture? | Final decision packet must define replay as core to evaluation architecture but not initial MVP/API/storage unless promoted by explicit triggers. |
| Dependency/falsifier graph gap | Dependencies, prerequisites, falsifiers, and blocked-until conditions must be explicit. | Final decision packet must include dependency/falsifier graph or table. |
| Artifact traceability gap | Each accepted/deferred/rejected concept needs rationale, caveat, counterevidence, and creep boundary. | Final decision packet must include a concept decision table with rationale, caveat, counterevidence, and negative-scope boundary. |
| Drift reconciliation gap | Known repo doc/source drift must not be hidden. | Final decision packet must include a drift appendix for strategy.list/status, strategy.show summary-count drift, and scoring docs/source vs PRD binary-only drift. |
| “Not approved” gap | Reader must know what this research does not authorize. | Final decision packet must include explicit “not approved by this decision” section. |

## 3. Non-Blocking Caveats

These should be preserved as caveats, not necessarily blockers:

- External source verification remains partial. Use external evidence as directional/pattern support only unless source trails are refreshed and quoted directly.
- AgentRun/session identity can remain metadata-only for now, but final decision should state what replay/handoff evidence would falsify that.
- Negative-scope guardrails are required across accepted concepts: no dashboard, generic memory, generic scheduler, rule engine, backtester, market-data fetcher, broker/execution system, or advice engine.
- Multi-agent handoff should remain deferred and packet-shaped unless dogfood proves derived packets plus idempotency cannot prevent duplicate/conflicting writes.

## 4. Recommended Final Decision Packet Structure

The advisor recommended that `trade-trace-gwv4` include:

1. **Decision scope statement**
   - Product-direction research only.
   - No implementation, schema, API, migration, UI, runtime, or public claims approved.

2. **Concept decision table**
   - accept / defer / reject;
   - confidence;
   - rationale;
   - caveats;
   - counterevidence/falsifier;
   - creep boundary.

3. **Dependency/falsifier table**
   - what each concept depends on;
   - what would block implementation planning;
   - what would force redesign.

4. **Negative-scope matrix**
   - dashboard;
   - generic memory;
   - scheduler/task manager;
   - general rule engine;
   - backtesting/simulation;
   - market data fetch;
   - broker execution;
   - advice/signal generation.

5. **Drift appendix**
   - `strategy.list`: implementation uses `both`; PRD says `all`.
   - `strategy.show`: implementation returns row-only; PRD describes future summary counts.
   - Forecast scoring: source/docs suggest broader categorical/scalar support while PRD MVP text emphasizes binary-only; binary remains safe core for claims.

6. **Research close criteria**
   - all artifacts linked;
   - blockers addressed or explicitly carried forward;
   - no implementation changes;
   - remaining evidence weaknesses named.

## 5. Resolution Plan

Resolution status for this bead:

- Advisor critique captured: **done**.
- Blockers to final decision identified: **done**.
- No blockers require modifying code or existing research artifacts before closing this review bead.
- Final decision packet (`trade-trace-gwv4`) must resolve or explicitly carry forward the blocker list above before it closes.

## 6. Side Effects

Files written:

- `docs/research/agentic-trade-trace/reviews/advisor-critique.md`

Memory retained: none.  
External side effects: advisor deliberation only; no public/external mutation.  
Implementation changes: none; no code, schema, tests, README/PRD/VISION, config, or runtime files were edited.
