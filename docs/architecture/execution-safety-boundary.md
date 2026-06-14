# Isolated execution safety-boundary architecture (the bounded-live execution module)

> Status: **design — not implemented** (trade-trace-nl13). This document
> specifies the *topology* of the Phase-3 bounded-live execution module — where
> the boundary sits, what crosses it in each direction, and how it is the
> **only** path from a recorded intent to a real order. No execution code, no
> credential field, no venue call, and no live order authority ships with this
> doc: the substrate today holds **zero** credentials, signs **zero** orders,
> and touches **zero** venues ([`autonomous-trader-substrate.md`
> §1](autonomous-trader-substrate.md#1-product-boundary-and-enforcement-contract)).
> It is a design-only artifact under EPIC trade-trace-u1gv (Phase-3 Execution
> Safety Design) and is consumed as a required input by the
> [execution design-review / sign-off gate](execution-design-review-gate.md#3-required-design-artifact-inputs).

Source bead: trade-trace-nl13. Parent epic: trade-trace-u1gv.

This is the **load-bearing scope decision** for all other Phase-3 design: it
fixes where the executor lives and what the membrane is, so the sibling
contracts can each draw a narrower line and assume this one. Read this doc
first, then the sibling it points you at.

Companion docs:
[`autonomous-trader-substrate.md`](autonomous-trader-substrate.md) (§1 hard
invariants for the credential-blind core; §3 the intent → check → approval
lifecycle this boundary consumes; §5.1 the execution-event import path this
boundary writes back through),
[`execution-isolation-contract.md`](execution-isolation-contract.md) (the
*credential* membrane — what is forbidden to cross, stated as testable
assertions; trade-trace-2ki5),
[`security-execution.md`](security-execution.md) (the Phase-3 attacker/asset
threat model for the same boundary; trade-trace-qtzp),
[`execution-safety-contracts.md`](execution-safety-contracts.md) (venue
allowlist / capital cap / per-market exposure / kill switch — *what an order
may do* once it crosses this boundary),
[`phase-gates.md`](phase-gates.md) (the measured Phase-2→Phase-3 readiness
report — a measurement, not an authorization),
[`execution-design-review-gate.md`](execution-design-review-gate.md) (the
one-time human sign-off that consumes this architecture; trade-trace-qxbb),
[`VISION.md`](../../VISION.md) ("What never changes" → *Credential discipline*;
"Where this ends up" → the kill switch / bounds the human sets).

## 1. What this document fixes (and what the others assume)

[`VISION.md`](../../VISION.md) promises two things this architecture makes
concrete:

- *"Phase 3 — bounded live execution. Real orders, behind a separate safety
  design ... and the same append-only audit trail underneath everything."*
  (`## How we get there`).
- *"Execution, when it comes, lives behind its own isolated safety boundary
  with its own design review."* (`## What never changes` → *Credential
  discipline*).

[`autonomous-trader-substrate.md` §1](autonomous-trader-substrate.md#1-product-boundary-and-enforcement-contract)
states the core's hard invariants: the substrate *"never signs, places,
replaces, cancels, redeems, settles, deposits, withdraws ... or operates as
custodian"*, and *"any scheduler, market scanner, credentialed adapter, live
executor, halt/cancel mechanism, operator UI, or compliance/legal decision
stays outside this product."* The execution lifecycle the substrate already
models stops at *"externally-submitted"* import evidence
([§3](autonomous-trader-substrate.md#3-execution-lifecycle-contract)) — i.e. it
already assumes a **separate** executor, never an in-process one.

This document fixes **where that separate executor lives, what the membrane
between it and the core is, and the direction data flows across it.** The
sibling contracts each assume this topology and narrow it:

| Sibling contract | Assumes from this doc | Adds |
| --- | --- | --- |
| [`execution-isolation-contract.md`](execution-isolation-contract.md) | The boundary is the only credential holder; the membrane is asymmetric | The *credential* allowlist of what may cross, as testable assertions |
| [`security-execution.md`](security-execution.md) | The boundary holds credentials and order authority | The attacker/asset threat model and controls |
| [`execution-safety-contracts.md`](execution-safety-contracts.md) | The boundary is the sole order path | Venue allowlist, caps, exposure limits, kill switch — *what a crossing order may do* |
| [`execution-design-review-gate.md`](execution-design-review-gate.md) | This architecture is reviewable as one artifact | The human sign-off ceremony gating go-live |

## 2. The load-bearing owner decision, resolved

The bead poses three coupled questions. They have one coherent answer, stated
here as the author's recommendation and **flagged for owner sign-off at the
[design-review gate](execution-design-review-gate.md#2-scope-two-sign-offs-not-one)**
(this doc is a *recommendation*, not the authorization):

### 2.1 Question A — does Trade Trace host the executor at all?

**Resolved: the model stays "core records, external executor acts" — Trade
Trace (this repository) does NOT host the executor.** The journal/memory core
remains exactly what [`autonomous-trader-substrate.md`
§1](autonomous-trader-substrate.md#1-product-boundary-and-enforcement-contract)
says it is: *"Trade Trace records, checks, reconciles, scores, audits, and
queues review work. External systems research, schedule, authenticate, sign,
submit, cancel, move funds, and fetch private venue state."* The execution
module is one of those *"external systems"*. It is the named, contracted
realization of the *"live executor [that] stays outside this product"* — not a
new responsibility folded into the core.

This is the conservative reading of the existing invariant, and it is the one
that keeps every §1 invariant intact for *this* repo without a flag, a
re-scope, or a credential code path (§4). It is also what the substrate already
anticipates: §3.2 records an optional `executor label`, and the §3.2 invariant
already reads *"A live executor may choose to require a matching Trade Trace
intent and passing/waived pre-trade check before it acts, but Trade Trace only
records and reports that evidence."*

### 2.2 Question B — separate PROCESS or separate package?

**Resolved: separate DISTRIBUTION and separate PROCESS — the strongest
isolation, not a same-process package.** Concretely:

- **Separate distribution.** The execution module is a distinct package /
  distribution that this repository does **not** import, vendor, or depend on
  (mirroring [`execution-isolation-contract.md`
  §2/R1](execution-isolation-contract.md#2-the-owner-decision-resolved-re-scope-the-ban-to-core-only-in-this-repo)).
  The core has no build flag, no optional extra, and no conditional import that
  would pull executor code — credential-holding or otherwise — into the
  credential-blind core's address space.
- **Separate process.** At run time the executor is its own OS process with its
  own lifecycle, its own credentials, and its own venue network egress. It
  communicates with the core only by (a) **reading** the core's append-only
  records as an authorization input (§3) and (b) **writing** sanitized
  execution facts back through the core's existing import boundary (§5). It does
  not share the core's SQLite handle, its in-process registry, or its address
  space.

**Why a separate process, not just a separate package.** A same-process package
would put credential-holding and venue-touching code in the *same address
space and the same SQLite writer* as the credential-blind core. A bug, a
dependency, or a future refactor in either half could then read the other's
memory or widen the core's write surface. The separate-process boundary makes
the isolation an **OS-enforced** fact, not a code-review-enforced convention:
the core literally cannot reach the executor's credentials, and the executor
literally cannot mutate a core row except by going through the same quarantining
import path every external fact uses (§5). The strongest available isolation is
the correct default for the one component that holds money authority; the
[design-review gate](execution-design-review-gate.md) is where the owner may
relax it, never a code default.

### 2.3 Question C — what, then, is "the boundary"?

The boundary is **not a function call inside Trade Trace.** It is the
**process/distribution membrane** between the credential-blind core and the
external executor, and it is **asymmetric** (the same single membrane
[`execution-isolation-contract.md`
§1](execution-isolation-contract.md#1-the-invariant-this-contract-pins) pins for
credentials, here described as topology):

```text
   credential-blind CORE                external EXECUTOR (the boundary module)
   (this repository)                    (separate distribution + process)
   ─────────────────────                ──────────────────────────────────────
   append-only records  ──── reads ───▶ consumes intent + pre-trade-check
   (intent, check,                      + approval/waiver as its ONLY
    approval/waiver)                     authorization input  (§3)
                                              │
                                              │ holds credentials, signs,
                                              │ submits to allowlisted venue
                                              ▼  (§4 sole-holder rule)
   import boundary      ◀─── writes ──── sanitized execution-event facts
   (§5.1 quarantining)                   (submitted/filled/rejected/halted)  (§5)
```

- **Core → executor:** the core exposes a *proposed, recorded, checked,
  approved* intent. Never a credential, never an order, never a "go" command the
  core itself issues.
- **Executor → core:** the executor hands back an *append-only, sanitized
  audit* of what it did. Never a credential, never signing material, never a raw
  venue payload (§5; [`execution-isolation-contract.md`
  §4](execution-isolation-contract.md#4-no-credential-signing-material-or-raw-venue-payload-crosses-back-into-core)).

Everything below is the topology that makes those two arrows the *only* two
arrows.

## 3. The recorded intent + check + approval is the executor's ONLY authorization input

The boundary module may act on an order **only** when, and exactly to the extent
that, the core's append-only records authorize it. The authorization is not a
prose instruction or an RPC "place this" command — it is the **derived
lifecycle state** of three already-specified append-only record families:

1. an **execution intent**
   ([`autonomous-trader-substrate.md` §3.2](autonomous-trader-substrate.md#32-execution-intents))
   — the immutable pre-trade ticket carrying venue, public market identifier,
   side, intended size/notional, limit/worst price, max slippage, environment
   (`paper` / `supervised_live`), and the required `policy_version`;
2. a passing or explicitly-waived **pre-trade risk check**
   ([§3.1](autonomous-trader-substrate.md#31-versioned-risk-policies-and-pre-trade-checks))
   against that intent's `policy_version`, with an aggregate status of `pass`
   (or `warn` within a recorded waiver);
3. an **approval or waiver record**
   ([§3.3](autonomous-trader-substrate.md#33-approval-and-waiver-records))
   whose scope (max notional/size, environment, policy version, expiry) covers
   this intent.

**The authorization rule, stated as the boundary's gate:**

> The executor MAY submit an order **iff** there exists a recorded intent whose
> linked pre-trade check is `pass` (or `warn` within an in-scope waiver) **and**
> an in-scope, unexpired, unrevoked approval/waiver covers it — and it submits
> *only* within that recorded scope (venue, side, size, price, environment,
> policy version). Absent any one of those records, **the default is deny**: the
> executor does not act.

Three properties make this safe and consistent with the existing substrate:

- **The core never says "go".** The core records *that an intent is approved*;
  it never issues an imperative. The executor reads the evidence and decides for
  itself, exactly as §3.2's invariant already frames it (*"A live executor may
  choose to require a matching Trade Trace intent and passing/waived pre-trade
  check before it acts, but Trade Trace only records and reports that
  evidence"*). This keeps the core **non-executing** — it emits no buy/sell/
  execute-now directive ([§1](autonomous-trader-substrate.md#1-product-boundary-and-enforcement-contract)).
- **Hard blocks cannot be silently bypassed.** A `hard_block` rule that was not
  explicitly and permissibly waived (§3.3: *"Hard-block rules must not be
  silently waived"*) means no in-scope approval exists, so the boundary's gate
  fails closed. `missing_data` is *not* a soft pass
  ([§3.1](autonomous-trader-substrate.md#31-versioned-risk-policies-and-pre-trade-checks)):
  an intent whose check is `missing_data` is not authorized.
- **Scope binds the order.** The executor may not exceed the approved scope: a
  larger size, a different venue, a different environment, or a stale
  `policy_version` is outside the recorded authorization and is denied. This is
  the same scope discipline §3.3 waivers already carry, here enforced at the
  membrane. The bounds the order must also respect — venue allowlist, capital
  cap, per-market exposure, kill-switch state — are owned by
  [`execution-safety-contracts.md`](execution-safety-contracts.md); this doc
  fixes that *those* checks, like the §3.1 check, gate *before* the boundary
  routes anything.

The executor reads these records the same credential-free way any reader does
(the core's read tools / its append-only export); it needs **no** privileged
core access and **no** core credential to read its authorization. The core does
not gain an "approve-and-fire" tool — approval and execution stay on opposite
sides of the membrane.

## 4. The boundary module is the ONLY component permitted to hold credentials or touch a venue

This is the rule the whole topology exists to guarantee:

> **Sole-holder rule.** The Phase-3 execution boundary module is the **only**
> component in the entire system permitted to (a) hold any venue credential,
> signing material, session/auth token, or order authority, and (b) open a
> network connection to a venue to place / replace / cancel / settle / redeem /
> move funds. No part of the journal/memory core — no table, tool, adapter,
> export, bundle, report, or read path — holds a credential or touches a venue.

Consequences, each of which preserves an existing core invariant rather than
relaxing it:

- **The credential ban stays maximally strict for the core.** Because the
  executor is a separate distribution this repo never imports (§2.2), this
  repository never gains a credential code path, and
  `tests/security/test_no_credentials.py` continues to scan the **entire**
  schema/tool surface of this repo and pass unchanged. The precise credential
  membrane — what is forbidden to cross back, stated as testable assertions — is
  owned by [`execution-isolation-contract.md`
  §3–§6](execution-isolation-contract.md#3-what-is-core-under-the-ban-forever-vs-what-is-boundary);
  this doc fixes only the topology (separate process holds the credentials) that
  that contract assumes.
- **The non-custody / no-sign / no-place invariants hold for the core
  verbatim.** The core still *"never signs, places, replaces, cancels ... or
  operates as custodian"* ([§1](autonomous-trader-substrate.md#1-product-boundary-and-enforcement-contract)).
  Those verbs move to the executor *outside* this product; they are not added to
  the core. The read-only public Polymarket metadata adapter
  ([§7](autonomous-trader-substrate.md#7-publicread-only-polymarket-metadata-adapter-scope))
  is unaffected: it is credential-free, opt-in, non-executing, and is **not**
  the execution boundary — it touches only public read-only endpoints and never
  places an order.
- **The venue network egress lives only in the executor.** The core's
  *"no background network, no telemetry, no phone-home"* posture
  ([`security.md` §7](security.md#7-no-background-network-no-telemetry-no-auto-update);
  VISION *Local-first*) is untouched: the only process permitted a venue
  connection is the separate executor, and only on the explicit, opt-in,
  allowlisted venue path ([`execution-safety-contracts.md`
  §2](execution-safety-contracts.md#2-the-execution-venue-allowlist-is-default-empty-deny-all)).

The attacker's-eye view of this asset concentration — why putting all
credentials and order authority in one isolated process is the *intended* design
and how it is defended — is [`security-execution.md`
§2–§4](security-execution.md#2-phase-3-assets).

## 5. The boundary writes execution events back as imports, so the audit trail stays append-only underneath it

The executor's output re-enters the core through **exactly** the existing
execution-event import path
([`autonomous-trader-substrate.md` §5.1](autonomous-trader-substrate.md#51-execution-event-imports)) —
not a new privileged write channel. This is what keeps
[`VISION.md`](../../VISION.md)'s promise that *"the same append-only audit trail
[lives] underneath everything"* and that *"the audit trail is the precondition
for autonomy, not the paperwork after it."*

- **Execution facts are imported evidence, never core-native truth.** Order
  submission/acceptance/rejection, partial/full fills, expirations,
  replacements/corrections, fees, and settlement facts are *"records of what
  another system says happened"* ([§5.1](autonomous-trader-substrate.md#51-execution-event-imports)) —
  here, what the boundary module says happened. They carry full provenance
  ([§2.2](autonomous-trader-substrate.md#22-provenance-and-as-of-fields)) and an
  idempotency key, and are labeled imported evidence with provenance, never a
  fact Trade Trace fetched with credentials.
- **They pass through the same quarantine every import does.** The import
  boundary *"reject[s] or quarantine[s] malformed, secret-bearing, impossible,
  duplicate-conflicting, or policy-inconsistent payloads rather than folding
  them into projections"* and *"detect[s] duplicate fills and external order IDs
  deterministically"* ([§5.1](autonomous-trader-substrate.md#51-execution-event-imports)).
  A credential or raw venue payload that leaked into a boundary-emitted event is
  rejected at this edge — the executor gets no exemption from the quarantine.
- **The audit trail is append-only and replayable underneath the executor.**
  Every execution action lands as an append-only row; state is *derived* from
  those rows, never mutated in place
  ([§2.1](autonomous-trader-substrate.md#21-append-only-rows-and-derived-projections):
  *"Do not mutate an intent from `pending` to `approved` to `filled`; append the
  approval, import, reconciliation, and review events"*). Corrections append and
  cite the superseded record. The result is reconcilable against imported
  account snapshots ([§5.2](autonomous-trader-substrate.md#52-account-snapshots)),
  deterministically reconciled ([§5.3](autonomous-trader-substrate.md#53-reconciliation-reports)),
  and replayable by a skeptic — the boundary cannot rewrite history, only append
  to it.
- **No bypass channel.** The boundary has **no** path that writes a core row
  except this import path. It does not get a direct SQLite handle, a privileged
  insert tool, or a back door. Because boundary-emitted events are ordinary
  imported rows, they inherit the core's write-time secret scan, log redaction,
  and bundle redaction unchanged ([`execution-isolation-contract.md`
  §5](execution-isolation-contract.md#5-the-write-time-secret-scan-and-bundle-redaction-extend-to-the-boundary)).

## 6. This module carries its own design-review process

Per [`VISION.md`](../../VISION.md) (*"Execution ... lives behind its own
isolated safety boundary **with its own design review**"*), neither this
architecture nor any code realizing it authorizes Phase 3 by itself. Turning
execution on requires the **separate, one-time, human design-review sign-off**
specified in
[`execution-design-review-gate.md`](execution-design-review-gate.md)
(trade-trace-qxbb), which:

- consumes **this** document (trade-trace-nl13, *"Isolated safety-boundary
  architecture"*) as a **required design-artifact input**
  ([gate §3](execution-design-review-gate.md#3-required-design-artifact-inputs)),
  alongside the credential-isolation contract, numeric gate criteria, venue
  allowlist, caps, exposure limits, kill switch, and threat model — and **fails
  closed** if any input is missing, stale, or unreviewed;
- splits into **SO-1** (code-merge: may this boundary's code merge, paper-only)
  and **SO-2** (live-capital: may real capital move), with SO-1 a precondition
  for SO-2 and **default-deny** for both
  ([gate §2](execution-design-review-gate.md#2-scope-two-sign-offs-not-one));
- requires an **independent reviewer** (the boundary's implementer may not be
  the sole reviewer of its design)
  ([gate §4](execution-design-review-gate.md#4-independent-reviewer-requirement));
- for SO-2, requires the [`report.phase_gate_readiness`](phase-gates.md#5-the-report)
  result to be verified `ready` against owner-authorized thresholds — a
  measurement that *"can never return `ready` until the owner sets [the
  numbers]"*.

A material change to this architecture (the membrane, the authorization-input
rule, the sole-holder rule, or the import-write-back rule) triggers a **new**
sign-off ([gate §7](execution-design-review-gate.md#7-default-deny-and-re-review-triggers)).

## 7. What this architecture does NOT do — and what it does NOT relax

**Does NOT do:**

- It does not implement execution, hold a credential, call a venue, sign or
  place an order, or move funds. It is a design-only topology spec.
- It does not authorize Phase 3. That requires the separate human sign-off (§6).
- It does not define the credential allowlist (that is
  [`execution-isolation-contract.md`](execution-isolation-contract.md)), the
  venue allowlist / caps / exposure limits / kill switch (that is
  [`execution-safety-contracts.md`](execution-safety-contracts.md)), the threat
  model (that is [`security-execution.md`](security-execution.md)), or the
  numeric readiness bar (that is [`phase-gates.md`](phase-gates.md)). It fixes
  the topology each of those assumes.

**Does NOT relax any
[`autonomous-trader-substrate.md` §1](autonomous-trader-substrate.md#1-product-boundary-and-enforcement-contract)
invariant for the core.** Explicitly, after this design:

- the core still *never stores* private keys, seed phrases, API secrets,
  passphrases, signing material, relayer credentials, or execution credentials
  — those live only in the separate executor process (§4);
- the core still *never signs, places, replaces, cancels, redeems, settles,
  deposits, withdraws, approves allowances, moves funds, or custodies* — those
  verbs move to the executor *outside* this product, not into the core (§2.1,
  §4);
- the core still *never emits directional buy/sell/execute-now advice* — it
  records that an intent is approved; it never tells the executor to fire (§3);
- the core's *scheduler / scanner / credentialed adapter / live executor /
  halt-cancel mechanism / operator UI* all remain *outside this product* — the
  executor is precisely the *"live executor [that] stays outside this product"*,
  now named and contracted, not absorbed into the core (§2.1).

## 8. Open questions (owner decisions)

The recommendations above are the author's defaults, flagged for the owner at
the [design-review gate](execution-design-review-gate.md); they are not
decisions.

1. **Process isolation strength (§2.2).** Recommended: a separate distribution
   AND a separate OS process. Open: is the owner content with the operational
   cost of a second process (deployment, supervision, IPC/file-read latency), or
   does a separately-distributed-but-same-host arrangement (e.g. the executor
   reading the core's append-only JSONL export and writing back through the
   import CLI) suffice? Note even the lighter arrangement keeps the
   separate-distribution guarantee; only the runtime coupling changes.
2. **How the executor reads its authorization (§3).** Open: should the executor
   read the core's authorization via the read-only MCP/CLI surface, via the
   append-only JSONL export outbox, or both? The export outbox is the most
   decoupled (no live core process needed) but is eventually-consistent; the
   read surface is current but couples runtimes.
3. **Whether the core records an executor "ready/halted" heartbeat (§5).** Open:
   should the executor's liveness/halt state itself be an imported fact the core
   records (so reconciliation and the kill-switch contract can observe it), or
   does that state stay entirely outside the core? The kill-switch contract
   ([`execution-safety-contracts.md` Part D](execution-safety-contracts.md#part-d-kill-switch-halt-flatten))
   assumes the activation and transition are recorded; this asks whether
   *steady-state* liveness is too.
4. **Reference vs. derived-fact for venue payloads (§5).** Inherited from
   [`execution-isolation-contract.md` §8 Q2](execution-isolation-contract.md#8-open-questions-owner-decisions):
   should a sanitized, content-addressed *reference* to a raw venue payload ever
   cross into the core, or should the core record only the derived sanitized
   facts (venue id, outcome code, idempotency key) and keep even the hash/path
   behind the boundary?
