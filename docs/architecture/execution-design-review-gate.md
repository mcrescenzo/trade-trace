# Execution design-review / sign-off gate (Phase-3 go-live)

> Status: **design — not implemented** (trade-trace-qxbb). This document
> specifies a one-time human sign-off *process* that must complete before
> any Phase-3 execution code merges or any live capital moves. No execution
> code, tool, or sign-off automation ships with this doc. The artifacts it
> requires as inputs are the sibling design beads under EPIC trade-trace-u1gv,
> several of which are themselves still design-only.

## 1. Why this document exists

[`VISION.md`](../../VISION.md) makes two promises this gate enforces:

- *"Execution, when it comes, lives behind its own isolated safety boundary
  **with its own design review**."* (`## What never changes` →
  *Credential discipline*.)
- *"set the bounds, review the audits, adjust the limits. **Never pick the
  trades.**"* (`## North star`.)

The repository already has **release** gates —
[`docs/RELEASE_CHECKLIST.md`](../RELEASE_CHECKLIST.md),
[`docs/RELEASE_FINAL_GATE.md`](../RELEASE_FINAL_GATE.md), and the consolidation
findings in
[`release-gate-consolidation.md`](release-gate-consolidation.md) — but those
gate *publishing a package*, not *granting an agent a wallet*. It has a
measurable Phase-2→Phase-3 readiness **report**
([`phase-gates.md`](phase-gates.md), `report.phase_gate_readiness`), but that
report is explicitly *"a measurement, not an authorization."* And it has
per-intent approval/waiver records
([`autonomous-trader-substrate.md` §3.3](autonomous-trader-substrate.md#33-approval-and-waiver-records)),
but those cover an *individual* recorded trade ticket, not the one-time
decision to turn execution on at all.

Nothing in the repo defines the **separate, one-time, human design-review
sign-off** VISION promises specifically for the execution boundary. This
document is that process. It does not execute, does not move funds, and does
not by itself unfreeze Phase 3 — it specifies the human ceremony, its required
inputs, and the auditable record that ceremony produces.

This gate is **distinct** from, and sits *downstream* of, all three existing
gates:

| Gate | What it answers | Authority |
| --- | --- | --- |
| Release gate (`RELEASE_FINAL_GATE.md`) | "Can this package version publish?" | Maintainer, per candidate SHA |
| Phase-gate report (`phase-gates.md`) | "Does the track-record *evidence* clear the owner's bar?" | A read-only measurement; no authority |
| Per-intent approval (`§3.3`) | "Is *this one* recorded trade ticket approved/waived?" | Per-intent, recorded after go-live |
| **This gate** | **"May execution be turned on at all — may code merge / may capital move?"** | **One-time human sign-off; default-deny** |

## 2. Scope: two sign-offs, not one

The gate is structured as **two distinct sign-offs** so that writing the
execution module is never conflated with funding it:

- **SO-1 — Code-merge sign-off.** Gates merging *any* Phase-3 bounded-live
  execution code (the module described by trade-trace-nl13) into the main
  line. Establishes that the boundary's *design* has been independently
  reviewed and the implementation matches it. May be granted with paper /
  zero-capital configuration only.
- **SO-2 — Live-capital sign-off.** Gates the *first* configuration that
  permits real capital to move (non-zero caps, a non-empty venue allowlist,
  `environment` other than `paper`). Requires SO-1 plus current, verified
  track-record evidence.

A failed or absent SO-1 blocks SO-2. Neither sign-off is implied by green
tests, a passing release gate, or a `ready` phase-gate report. **The default
is deny:** in the absence of a recorded, in-date, unrevoked sign-off, execution
stays frozen.

## 3. Required design-artifact inputs

A sign-off may not be granted until **every** artifact below exists, is at
`Status` other than draft-incomplete, and is cited by ID in the sign-off
record. These are the sibling beads under EPIC trade-trace-u1gv; this gate is
the *consumer* that makes them collectively load-bearing:

| Required input | Bead | What it must establish |
| --- | --- | --- |
| Isolated safety-boundary architecture | trade-trace-nl13 | The bounded-live execution module: where the boundary is, what crosses it, how it is the *only* path to an order. |
| Credential-blind isolation contract | trade-trace-2ki5 | The journal/memory core never sees execution credentials; the boundary holds them. |
| Numeric gate-criteria spec | trade-trace-i9p2 / [`phase-gates.md`](phase-gates.md) | The resolved-market track-record + calibration + audit-cleanliness thresholds, set by the owner. |
| Venue allowlist contract | trade-trace-6fkv | Which venues are permitted; deny-by-default; how the list is changed. |
| Capital cap + staged-capital schedule | trade-trace-e3sm | Hard capital ceiling and the staged ramp; nothing auto-raises it. |
| Per-market / per-event exposure-limit contract | trade-trace-i9mp | Exposure ceilings per market and per event. |
| Kill-switch (halt + flatten) semantics | trade-trace-8sbv | How execution is halted and positions flattened on demand. |
| Live-execution threat model | trade-trace-qtzp | The credential-handling + live-execution threat model and its mitigations. |

If any artifact is missing, stale, or unreviewed, the gate **fails closed** —
the reviewer records the missing-input reason and the sign-off is not granted.

## 4. Independent reviewer requirement

The sign-off authority is the **human operator**. The operator is the only
party who may grant SO-1 or SO-2; no agent may grant itself either sign-off,
and no agent may infer a sign-off from green tests or a `ready` gate report
(mirroring the release-gate rule that *"no agent should infer ... approvals
from green tests"*).

The design review feeding the sign-off must be performed by **a reviewer
distinct from the implementer**:

- The reviewer of record for a given artifact MUST NOT be the same actor who
  authored that artifact's implementation. (For SO-1 this means the boundary
  code's author cannot be the sole reviewer of the boundary design.)
- The reviewer may be a second human, or an independent reviewer agent acting
  under the operator — but the operator's grant is still required; an agent
  review is *evidence for*, never a substitute for, the human sign-off.
- The implementer↔reviewer separation is recorded in the sign-off event
  (`implementer_actor`, `reviewer_actor`); a record where they are equal is a
  non-compliant override and reports must label it as such, exactly as §3.3
  treats a silently-waived hard block.

## 5. VISION-invariant evidence checklist

The reviewer must, for **each** invariant in `VISION.md` `## What never
changes`, record concrete evidence that the proposed execution design upholds
it. A single unsatisfied row blocks the sign-off (§7, default-deny).

| VISION invariant (`## What never changes`) | Evidence the reviewer must cite |
| --- | --- |
| **Local-first** — one SQLite DB, no cloud/telemetry/sync/phone-home | The execution boundary adds no background sync, no telemetry, no cloud dependency; any network call is the explicit, opt-in venue path only. |
| **Append-only honesty** — forecasts committed before outcomes; history never rewritten | Every execution action (order placed/filled/rejected/halted) lands as an append-only event; no execution path mutates or deletes prior records. |
| **Process graded separately from P&L** | Execution records feed the process/score reports without conflating realized P&L into the process grade. |
| **Capability never outruns accountability** — nothing ships unless recordable, scoreable, replayable | Every order action is recordable, scoreable, and replayable from the journal *before* the boundary is allowed to route it. |
| **Built for agents** — JSON-first, MCP/CLI, schema-checked, no human dashboard | The boundary's surface is the same JSON-first, schema-checked contract; the human's only surface is audits and bounds, not a trading dashboard. |
| **Credential discipline** — journal/memory core stays credential-blind forever; execution behind its own isolated boundary | The credential-blind isolation contract (trade-trace-2ki5) is demonstrated: the core cannot read execution credentials; the boundary is the only credential holder. |
| **Set the bounds, never pick the trades** (North star / human role) | Caps, allowlist, exposure limits, and kill switch are owner-set inputs the agent cannot raise or bypass; the agent picks trades only *within* them. |

Each row's evidence is a pointer (record ID, doc section, or test) — prose
assertions alone are insufficient, consistent with VISION's *"made measurable —
not prose."*

## 6. Phase-gate evidence must be verified MET

Before SO-2 (live capital), the reviewer must verify that the
`report.phase_gate_readiness` result
([`phase-gates.md` §5](phase-gates.md#5-the-report)) returns `ready` against
the **owner-authorized** thresholds (not the placeholder values), computed from
current-head journal state — not a stale snapshot, mirroring the release-gate
*"do not publish ... from stale dated proof"* rule. Specifically:

- `gate_status == "ready"`, every criterion `pass == true`, and
  `owner_thresholds_complete == true`;
- the thresholds used are the owner-authorized numbers recorded in
  `phase-gates.md` §4, captured by value into the sign-off record;
- the underlying evidence bundle (`report.autonomy_readiness`,
  [`phase-gates.md` §7](phase-gates.md#7-the-readiness-evidence-bundle-reportautonomy_readiness))
  shows the track record is *trending* clean, not a single lucky window.

A non-`ready` gate, an unset threshold, or `insufficient_data` blocks SO-2 with
no override path — the safety invariant that *"an unset threshold can never
yield a `ready` gate"* propagates into this gate as a hard block.

## 7. Default-deny and re-review triggers

- **Failing any single criterion blocks go-live.** There is no aggregate
  "mostly passed" grant. A missing input (§3), an implementer-equals-reviewer
  record (§4), an unsatisfied invariant row (§5), or a non-`ready` gate (§6)
  each independently fails the sign-off closed.
- **The gate is re-run on material change.** A new sign-off is required
  whenever the boundary design, the capital cap or staged schedule, the venue
  allowlist, the exposure limits, or the kill-switch semantics change
  materially. A prior sign-off does not cover a config it never reviewed; the
  recorded sign-off's `scope` (caps, allowlist hash, policy version,
  environment) bounds what it authorizes, exactly as §3.3 waivers carry an
  explicit scope and expiry.
- A sign-off may be **revoked** by the operator at any time; a revoked sign-off
  returns execution to the default-deny frozen state.

## 8. Sign-off recorded as an append-only event

The sign-off itself is not prose in this file — it is an **append-only,
auditable record**, reusing the lifecycle-event discipline the substrate
already enforces (§3.3 approval/waiver records are the nearest precedent). The
record is the authorization of record; this document only specifies its
required shape:

- `sign_off_type` — `SO-1` (code-merge) or `SO-2` (live-capital);
- `decision` — `granted` | `denied` | `revoked` (no silent state; a denial is
  recorded, not merely absent);
- `operator_actor` — the granting human (required);
- `implementer_actor` and `reviewer_actor` — must differ (§4);
- `required_inputs` — the cited artifact bead IDs and their reviewed
  versions/SHAs (§3);
- `invariant_evidence` — one entry per VISION invariant row with its evidence
  pointer (§5);
- `phase_gate_evidence` — the `report.phase_gate_readiness` packet captured by
  value, with the owner-authorized thresholds used (§6; SO-2 only);
- `scope` — caps, venue-allowlist hash, exposure limits, policy version, and
  `environment` this sign-off authorizes (§7);
- `expires_at` — optional expiry after which the sign-off must be re-run;
- idempotency key, `created_at`, and provenance, like every other retryable
  write in the substrate.

The record is **append-only**: a revocation or re-review appends a new event;
it never edits or deletes a prior sign-off, so the full authorization history
is replayable by a skeptic. Whether the canonical record lives in the journal,
in `bd`, or both is an owner decision deferred to the implementing bead — but
wherever it lives, it must be append-only and auditable.

## 9. What this gate does NOT do

- It does not execute, route, halt, or move funds. It is a *process* spec.
- It does not unfreeze Phase 3 by itself; it specifies the human ceremony that
  does, and the record that ceremony leaves.
- It does not invent the numeric bar — those are the owner's, in `phase-gates.md`
  §4.
- It does not replace the per-intent approval/waiver flow (§3.3); that flow
  operates *after* SO-2, on individual trade tickets, within the bounds this
  gate authorized.

## 10. Open questions (owner decisions)

These are flagged for the owner; the recommendations above are the author's
default, not a decision:

1. **Single vs. dual authority.** This spec recommends the human operator as
   sole granting authority, with an optional independent reviewer agent as
   *evidence*. Open: should SO-2 require two human signatures?
2. **Record location.** Recommended: an append-only journal lifecycle event
   *and* a `bd` issue for discoverability. Open: is one canonical surface
   preferred to avoid drift?
3. **One gate vs. two.** This spec splits into SO-1 (merge) and SO-2 (capital).
   Open: should code-merge and go-live collapse into a single sign-off?
