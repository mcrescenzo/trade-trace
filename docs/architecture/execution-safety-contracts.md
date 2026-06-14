# Execution-safety contracts (live order placement)

> Status: **design — not implemented** (trade-trace-6fkv, trade-trace-e3sm).
> This document specifies the contracts a future Phase-3 execution module
> MUST satisfy before it may place a live order: the **execution-venue
> allowlist** (§§2–9) governing *where* orders may go, and the **capital cap
> + staged-capital schedule** (§§10–16) governing *how much* capital may ever
> be at risk. No execution code, tool, table, allowlist, or cap enforcement
> ships with this doc — the substrate today places no orders, holds no
> credentials, and moves no funds. The contracts are a precondition for that
> code, not a description of it. They sit under EPIC trade-trace-u1gv
> (Phase-3 Execution Safety Design) alongside the
> [execution design-review / sign-off gate](execution-design-review-gate.md)
> and the [phase-gate readiness criteria](phase-gates.md).

## Part A — Execution-venue allowlist

## 1. Why this document exists

[`VISION.md`](../../VISION.md) describes Phase 3 as *"bounded live execution"*
behind *"hard caps, staged capital, **allowlisted venues**, kill switches"*
(`## How we get there` → *Phase 3*), and pins the scope as **"prediction
markets, natively, forever"** (`## North star`). It also lists *"venue
allowlists"* among the bounds *a human set* in the north-star picture.

Nothing in the repo today defines **which venues the execution module may
place real orders on, or how a venue earns that trust.** The only venue
surface that exists is the credential-free, read-only, opt-in Polymarket
**metadata** adapter
([`autonomous-trader-substrate.md` §7](autonomous-trader-substrate.md#7-publicread-only-polymarket-metadata-adapter-scope)),
which explicitly performs *"no order placement, cancellation, custody."*
That adapter already follows a precedent worth mirroring:
[`PRD.md` §2.4.1](../PRD.md) requires *"endpoint allowlisting, TLS
verification, scrubbed error/log output"* and *"no background fetch daemon,
scheduler, **default RPC URL**, or committed credential."*

This document lifts that read-only precedent into the much higher-stakes
**execution** setting: the allowlist that gates *real orders*. It does not
execute, does not move funds, and does not by itself authorize any venue —
turning execution on at all is the separate one-time human sign-off in the
[execution design-review gate](execution-design-review-gate.md). This
contract governs what the execution module is *permitted* to do once that
gate has been passed.

## 2. The execution-venue allowlist is default-empty (deny-all)

The execution module MUST hold an **explicit allowlist** of venues it may
place live orders on. The allowlist is a positive list: a venue is permitted
**if and only if** it appears on the list.

- **Default state is empty.** A freshly configured system has an empty
  execution-venue allowlist, and an empty allowlist means **deny-all** — no
  venue is executable. There is no implicit, built-in, or "well-known"
  venue. The deny-all default is the safe state the system boots into and
  the state it returns to whenever the allowlist is cleared.
- **Deny is the default decision, not an error path.** An order targeting a
  venue absent from the allowlist is **hard-rejected before any network or
  credential use** (§5). The rejection is the normal, expected outcome of an
  unconfigured system, not an exceptional condition.
- **No code default may add a venue.** The allowlist MUST NOT be seeded by a
  constant, environment fallback, packaged config, or migration. Mirroring
  `PRD.md`'s *"no default RPC URL, no committed credential"* rule for the
  read-only adapter: a venue's executability MUST originate from a deliberate
  operator action recorded as a config event (§4), never from shipped code.
  A reviewer reading a clean checkout must be able to conclude that the
  system, as shipped, can place orders on **zero** venues.

## 3. Separate from the read-only metadata-adapter allowlist

The execution-venue allowlist is a **distinct surface** from the read-only
metadata adapter's endpoint allowlist
([`autonomous-trader-substrate.md` §7](autonomous-trader-substrate.md#7-publicread-only-polymarket-metadata-adapter-scope)).
They are not shared, not derived from one another, and not unioned.

- **Trust for public data is not trust for orders.** A venue or endpoint
  trusted to serve public market *metadata* is **not** thereby trusted to
  receive *orders*. Adding a venue to the metadata allowlist grants no
  execution capability, and vice versa.
- **Two lists, two decisions.** Each list is populated by its own operator
  action and its own config event. There is no code path where editing one
  list mutates the other, and no inheritance from the read-only list into
  the execution list.
- **Higher bar for execution.** The execution-venue allowlist carries the
  per-venue endpoint/TLS pinning of §5 *and* the order-placement trust
  decision; the metadata allowlist carries only the read-only endpoint/TLS
  pinning of `PRD.md` §2.4.1. The execution list is the strictly stronger
  grant and is never satisfied by the weaker one.

## 4. How a venue is added: append-only config event, never a code default

A venue becomes executable only through a deliberate **operator
configuration action** that is **recorded as an append-only config event** in
the journal. This mirrors the existing operator-config pattern (e.g. the
`journal.config_set` event used for `embeddings.provider`, described in
[`security.md`](security.md)) and the `PRD.md` §2.4.1 rule that the outbound
surface is *"configured explicitly … no default RPC URL, no committed
credential."*

- **Operator action required.** The agent MUST NOT be able to add a venue to
  its own execution allowlist. Allowlist membership is a bound *a human
  sets* (VISION: *"set the bounds … never pick the trades"*). The agent may
  read the current allowlist; it may not mutate it.
- **Recorded as an append-only config event.** Each add/remove is an
  append-only event carrying, at minimum: the venue identifier, the
  configured endpoint/TLS pin (§5), the operator/principal who made the
  change, an idempotency key, and a timestamp. The current allowlist is the
  **deterministic projection** of these events — the live set is derived by
  replaying the config-event stream, never stored as mutable state that
  could drift from its audit trail.
- **Removal is also an append-only event, not a deletion.** Revoking a venue
  appends a remove event; it never rewrites or deletes the original add.
  After a remove event the venue is again deny-all (§2) until a new add
  event re-grants it. The full grant/revoke history stays replayable.
- **No silent re-grant.** Re-adding a previously removed venue requires a
  fresh operator config event; nothing in code, cache, or prior state
  re-activates a removed venue automatically.

## 5. Per-venue endpoint and TLS pinning

Every executable venue on the allowlist carries an **explicit endpoint and
TLS pin**, recorded in the same config event that adds it. The execution
module places orders only against the pinned endpoint, over verified TLS.

- **Pinned endpoint pattern.** The config event records the exact
  order-placement endpoint(s) for the venue — host and, where applicable,
  the API base path. An order may only be sent to a pinned endpoint for an
  allowlisted venue; a request to any other host, even for an allowlisted
  venue, is rejected (§6). This is the execution analogue of `PRD.md`
  §2.4.1's *"endpoint allowlisting"*.
- **TLS verification is mandatory and non-bypassable.** Order traffic MUST
  use TLS with full certificate-chain verification; there is no
  `verify=false`, no plaintext, and no downgrade path. Where a venue
  supports certificate or public-key pinning, the pin is recorded in the
  config event and enforced per request. A TLS verification failure is a
  hard reject (§6), never a warning the module proceeds past.
- **Pin changes are append-only too.** Changing a venue's pinned
  endpoint/TLS material is a new config event (§4); the prior pin stays in
  the replayable history. An order is always evaluated against the
  currently-projected pin.
- **Scrubbed transport diagnostics.** Consistent with `PRD.md` §2.4.1
  (*"scrubbed error/log output, and no request/response body logging"*),
  endpoint/TLS rejection records and any transport diagnostics MUST NOT
  embed credentials, signed payloads, or raw request/response bodies.

## 6. Non-allowlisted orders are hard-rejected and recorded

Any order whose target venue is **not on the execution allowlist**, or whose
target endpoint is not the venue's pinned endpoint, or whose transport fails
TLS verification, is **hard-rejected**:

- **Reject before any side effect.** The rejection happens before any
  network call, any credential read, and any order transmission. A
  non-allowlisted venue never sees a connection attempt.
- **Recorded as an append-only event.** Every rejection is written to the
  append-only audit trail with the attempted venue, the reject reason
  (not-allowlisted / endpoint-mismatch / TLS-failure), the originating
  intent reference, and a timestamp — scrubbed of secrets per §5. A skeptic
  replaying the journal can see every order the system declined to place and
  why. The decision is not silently dropped.
- **No override at order time.** There is no per-order flag, force, or
  bypass that lets the agent or the execution module place an order on a
  non-allowlisted venue. The only way to make a venue executable is the
  operator config event of §4.

## 7. Prediction markets only — non-prediction-market venues are out of scope

The execution-venue allowlist exists exclusively to gate **prediction-market**
order placement. Per VISION's *"prediction markets, natively, forever … depth
over breadth is not a phase; it is the identity,"* a non-prediction-market
venue (an equity broker, a crypto spot/derivatives exchange for directional
trading, an FX venue) is **out of scope** for this allowlist and MUST NOT be
added to it. The allowlist is not a generic broker-connection registry; it is
the prediction-market execution surface and nothing else.

## 8. Open questions (owner decisions)

These are **owner decisions** the agent must not make for itself; the values
below are recommendations to weigh, flagged for sign-off in the
[execution design-review gate](execution-design-review-gate.md#2-scope-two-sign-offs-not-one)
and in the per-intent approval surface
([`autonomous-trader-substrate.md` §3.3](autonomous-trader-substrate.md#33-approval-and-waiver-records)).

| Decision | Recommendation to weigh |
| --- | --- |
| Which venue(s) does Phase 3 launch execution on? | **Polymarket only** at first — it is the one venue the substrate already integrates (read-only) and the only one with a shipped resolution-finality model. Add others only after each clears its own design review. |
| Is the execution allowlist independent of the metadata-adapter allowlist? | **Yes — independent (§3).** A venue trusted for public data is not automatically trusted for orders; conflating them widens the order-placement surface by accident. |
| Per-venue trust/pinning requirements before a first live order? | At minimum: pinned order endpoint + enforced TLS verification (§5), an operator-recorded config event (§4), and the venue named in the live-capital sign-off (SO-2) of the design-review gate. Stronger venues add certificate/public-key pinning. |

## 9. What this contract does NOT do

- It does not place, cancel, halt, or remediate any order, and ships no
  execution code, tool, table, or allowlist enforcement.
- It does not authorize execution on any venue. Turning execution on at all
  is the one-time human sign-off in the
  [execution design-review gate](execution-design-review-gate.md); this
  contract only constrains what is permitted once that gate passes.
- It does not hold or describe credentials. Credential handling lives behind
  the isolated safety boundary and its own threat-model addendum; this
  contract governs only the venue/endpoint/TLS allowlist that gates whether
  an order may be sent at all.
- It does not pick the trades. Venue membership is a bound a human sets; the
  agent may read the allowlist but may never add to it.

## Part B — Capital cap and staged-capital schedule

## 10. Why this contract exists (and how it differs from the §3.1 pre-trade check)

[`VISION.md`](../../VISION.md) lists *"capital caps"* among the bounds *a
human set* in the north-star picture (`## Where this ends up`: *"all within
bounds a human set: capital caps, per-market exposure limits, venue
allowlists, a kill switch"*) and names *"hard caps, staged capital"* as the
first two safety bounds of Phase 3 (`## How we get there` → *Phase 3*). This
part of the contract specifies the **hard, boundary-enforced** version of
those words.

There is already a capital-shaped surface in the substrate, and this contract
is deliberately **distinct** from it:

- [`autonomous-trader-substrate.md` §3.1](autonomous-trader-substrate.md#31-versioned-risk-policies-and-pre-trade-checks)
  defines a **deterministic pre-trade check** that may evaluate limit classes
  such as `notional`, `total_exposure`, and `daily_loss`/`weekly_loss` and
  return a `pass`/`warn`/`fail`/`missing_data` verdict. That evaluator
  *"writes no rows and never blocks, signs, places, or routes an order"* — it
  is an **advisory check record**, and a `warn` (or even a waived `fail`) does
  not by itself stop anything. The substrate explicitly **never executes**
  (`§1`).
- This capital cap is a **hard global ceiling enforced at the execution
  boundary itself**. It is the last gate before an order is transmitted, it
  is **not waivable at order time**, and its decision on breach is
  **default-deny** — the order is hard-rejected the same way a non-allowlisted
  venue is (§6), before any network or credential use.

The two are layered, not redundant. A §3.1 pre-trade check `pass` is a
*necessary input* an executor may require; the boundary cap is the
*independent backstop* that holds even if a pre-trade check was wrong, stale,
waived, skipped, or never run. **A passing pre-trade check never authorizes
exceeding the cap, and the cap never relies on a pre-trade check having run.**

## 11. The hard global capital ceiling is default-deny on breach

The execution module MUST hold a **hard global capital ceiling**: a maximum
total capital that may be committed to live positions and resting orders at
once. The ceiling is the single hard number the boundary enforces; the
§3.1 advisory checks may apply finer per-market / per-category limits *below*
it, but nothing the agent or a pre-trade check does may raise an order past
the hard ceiling.

- **Default-deny on breach.** If placing (or replacing/increasing) an order
  would push committed live capital — existing live exposure plus resting
  orders plus the new order's worst-case capital-at-risk — above the active
  hard ceiling, the order is **hard-rejected before any side effect** (no
  network call, no credential read, no transmission), exactly as in §6. Deny
  is the default decision on breach, not an exceptional error path.
- **The boundary computes capital-at-risk conservatively.** The committed
  figure the cap is evaluated against uses the worst-case capital the new
  order could consume (e.g. full notional at the limit price for a buy),
  never an optimistic mid or expected-fill estimate. When the inputs needed
  to compute committed capital are missing or stale, the boundary treats the
  state as **`missing_data` and denies** — it never optimistically assumes
  headroom (mirroring §3.1's *"`missing_data` is not a soft pass"*).
- **No order-time override.** There is no per-order flag, force, waiver, or
  bypass that lets the agent or the execution module exceed the hard ceiling.
  Unlike a §3.1 warning, the hard ceiling is **non-waivable at order time**.
  The only way capital headroom increases is a new, approved limit-config
  event (§14, §15).
- **Default state is the lowest configured tier, never unbounded.** A freshly
  configured system has the **staged-capital schedule's first (smallest)
  tier** as its active ceiling, or `0` (deny-all execution) if no tier has
  been authorized. An absent, unparseable, or unauthorized cap configuration
  resolves to `0`, never to "unlimited". A reviewer reading a clean checkout
  must be able to conclude the system, as shipped, may commit **zero** live
  capital.

## 12. The staged-capital ramp schedule

The live capital ceiling is not a single fixed number — it **ramps** through
ordered tiers as gate-evidence accrues. The schedule defines, for each tier,
(a) the hard ceiling that tier authorizes and (b) the **evidence milestone**
that unlocks it. A tier becomes *eligible* only when its milestone is met; the
active ceiling is the highest tier that is both **eligible AND authorized by
an approval record** (§15).

- **Tiers are ordered and monotonically non-decreasing in ceiling.** Tier 0
  is the smallest (the boot default of §11); each later tier authorizes a
  larger ceiling. Eligibility for a higher tier never *lowers* the ceiling; it
  only makes a larger ceiling *available for approval*.
- **Milestones are tied to the phase-gate evidence, not to dates.** Each
  tier's unlock milestone is expressed in terms of the
  [phase-gate readiness criteria](phase-gates.md#2-the-criteria) — primarily
  the **resolved-market count** (`resolved_n`) and the **calibration**
  signals (`brier`, `skill_vs_market`) the gate already computes from the
  journal, plus reconciliation/audit cleanliness. This deliberately reuses the
  existing measurable gate rather than inventing a parallel bar: *"the gate
  between phases is evidence — track record, calibration, audit cleanliness —
  never a roadmap date."* A tier's milestone is **met** only when its named
  gate criteria measure at or beyond the milestone's thresholds; an
  indeterminate (`null`) gate criterion leaves the milestone **unmet** (it
  does not unlock the tier).
- **A milestone makes a tier eligible; it does not auto-raise the ceiling.**
  Meeting a milestone is *necessary but not sufficient*. Crossing up into a
  larger tier still requires the explicit approval record of §15 — the agent
  may demonstrate it earned a tier, but it may **never** raise its own
  ceiling. (Lowering, by contrast, is immediate — §15.)
- **Losing eligibility lowers the ceiling immediately.** If accrued evidence
  later regresses below a tier's milestone (e.g. resolved-N is recomputed,
  calibration degrades, a reconciliation critical opens), the active ceiling
  drops to the highest still-eligible authorized tier **immediately**, with no
  approval required — consistent with the lowering rule of §15.

The **specific tier sizes and the exact milestone thresholds are an owner
decision** (§16); like the phase-gate thresholds, the agent must never pick
the bar that grants itself more capital.

## 13. Every cap value is an immutable policy_version

Each cap value — the hard global ceiling and every tier's `(ceiling,
milestone)` pair — is recorded as an **immutable `policy_version`**, reusing
the rule from
[`autonomous-trader-substrate.md` §3.1](autonomous-trader-substrate.md#31-versioned-risk-policies-and-pre-trade-checks):
*"A risk policy is immutable once referenced. Changes create a new
`policy_version`."*

- **Immutable once referenced.** A cap `policy_version` is never edited in
  place. Once any limit-config event, order decision, or approval record
  references a cap version, that version's values are frozen. Changing a
  ceiling or a tier means **minting a new `policy_version`**, not mutating the
  old one.
- **Caps are data, not prose.** Like §3.1 policies, a cap configuration is a
  structured, versioned record (ceiling amounts, denomination, tier table with
  milestone criteria/thresholds), not free text — so every order rejection can
  cite the exact `policy_version` and tier it was evaluated against.
- **Every enforcement decision is attributable to a version.** A boundary
  reject (or allow) records which cap `policy_version` and which active tier
  were in force, so a skeptic replaying the journal can reconstruct exactly
  what ceiling applied at any moment.

## 14. Enforced at the boundary AND recorded as an append-only limit-config event

The cap is both **enforced** at the execution boundary and **configured**
through the same append-only, projection-derived mechanism the venue allowlist
uses (§4).

- **Configuration is an append-only `limit-config` event.** Setting,
  lowering, or (after approval, §15) raising a cap appends a **limit-config
  event** to the journal carrying, at minimum: the new cap `policy_version`,
  the ceiling amount(s) and denomination, the tier table (or the changed
  tier), the operator/principal, an idempotency key, a timestamp, and — for a
  raise — the approval-record reference (§15). The **active cap is the
  deterministic projection** of these events (joined with current gate
  evidence for tier eligibility, §12), never mutable state that could drift
  from its audit trail. This mirrors the §4 config-event pattern and the
  `journal.config_set` precedent in [`security.md`](security.md).
- **Enforced at the boundary itself.** The ceiling is checked **at the last
  gate before transmission**, in the same hard-reject path as the venue
  allowlist (§6) — not merely in an upstream advisory pre-trade check. An
  order that clears every §3.1 check but would breach the cap is still
  hard-rejected at the boundary.
- **Every boundary decision is an append-only event.** Each cap evaluation —
  allow or deny — is recorded append-only with the attempted order's
  committed-capital figure, the active ceiling, the cap `policy_version` and
  tier, the reject reason on denial (`cap_exceeded` / `cap_missing_data` /
  `cap_unauthorized`), the originating intent reference, and a timestamp —
  scrubbed of secrets per §5. A skeptic replaying the journal can see every
  order the cap declined and the exact ceiling that declined it; the decision
  is never silently dropped.

## 15. Lowering takes effect immediately; raising requires an approval record

The cap is **asymmetric by design**: tightening protection is instant and
unilateral; loosening it is gated.

- **Lowering takes effect immediately, no approval needed.** An operator (or a
  safety mechanism such as a loss-limit halt, §16) may lower the active
  ceiling — or drop to a lower tier — through a limit-config event that takes
  effect **as soon as it is recorded**, with **no approval record required**.
  Reducing capital-at-risk is always allowed to be fast. Loss of tier
  eligibility (§12) likewise lowers the ceiling immediately. From the instant
  a lower cap is recorded, any in-flight order that would breach the new lower
  ceiling is hard-rejected (§11).
- **Raising requires an approval record.** Increasing the active ceiling —
  whether by minting a higher cap `policy_version` or by stepping up into a
  higher (eligible) staged tier — requires an **append-only approval record**,
  reusing the approval contract of
  [`autonomous-trader-substrate.md` §3.3](autonomous-trader-substrate.md#33-approval-and-waiver-records):
  approving actor/mode, the cap `policy_version` and target tier being
  authorized, the gate-evidence snapshot that shows the tier's milestone met
  (§12), an idempotency key, and a timestamp. A raise limit-config event (§14)
  is invalid — and the projection MUST reject it, keeping the lower ceiling —
  unless it cites a matching approval record.
- **The agent may never raise its own cap.** Consistent with VISION's *"set
  the bounds … never pick the trades"* and the phase-gate self-grant
  invariant, the approving actor for a raise is a **human (or independent
  supervisor) decision**, never the trading agent. The agent may *read* the
  active cap, *surface* that it has earned a higher tier, and *propose* a
  raise; it may never author the approval that grants itself more capital.

## 16. Open questions (owner decisions)

These are **owner decisions** the agent must not make for itself; the values
below are recommendations to weigh, flagged for sign-off in the
[execution design-review gate](execution-design-review-gate.md#2-scope-two-sign-offs-not-one)
(the live-capital sign-off, SO-2) and the per-intent approval surface
([`autonomous-trader-substrate.md` §3.3](autonomous-trader-substrate.md#33-approval-and-waiver-records)).
This bead is labeled `needs-design`: the four decisions below require explicit
owner sign-off before any cap value is committed as authorized.

| Decision | Recommendation to weigh |
| --- | --- |
| **Initial hard ceiling** — the first live dollar amount Tier 0 authorizes. | A deliberately small first-live amount (small enough that a total loss is an acceptable tuition cost), sized so the very first live orders test the boundary, not the bankroll. The agent must NOT pick this. |
| **Ramp schedule / tiers + unlock milestones** — tier sizes and which gate-evidence milestone unlocks each. | Tie each tier's unlock to [phase-gate](phase-gates.md#2-the-criteria) `resolved_n` + calibration (`brier`, `skill_vs_market`) thresholds (e.g. modest step-ups gated on growing resolved-N with calibration holding), so capital follows demonstrated track record, not time. Keep step-ups multiplicative-but-bounded so one good window cannot unlock a large jump. |
| **Per-venue vs global denomination** — is the ceiling one global number or one per allowlisted venue? | A **single global ceiling** first (simplest to reason about and the tightest backstop); add per-venue sub-caps later only if multiple venues are allowlisted (§3) and an owner wants to bound exposure to any one venue independently. Whichever is chosen is a versioned cap value (§13). |
| **Daily/weekly loss-limit cooldown / auto-halt behavior** — what happens when a realized loss limit is hit. | On hitting an owner-set daily/weekly realized-loss limit, **auto-halt new opening orders and lower the active ceiling immediately** (§15 lowering is instant and needs no approval), entering a cooldown that only an explicit operator action (or the kill switch) clears. Resuming or re-raising after a halt is a §15 raise and requires an approval record. The exact loss thresholds and cooldown duration are the owner's. |

## 17. What this contract does NOT do

- It does not place, cancel, halt, or remediate any order, and ships no
  execution code, tool, table, cap, or enforcement.
- It does not set the cap. The initial ceiling, the ramp tiers/milestones, the
  denomination, and the loss-limit behavior are the owner's decisions (§16);
  the agent may read the active cap but may never author the approval that
  raises it (§15).
- It does not move or hold funds, and it does not read account balances of its
  own accord. The committed-capital figure it enforces against is computed
  from the journal's own append-only exposure/order projection plus
  caller-supplied snapshots, the same inputs §3.1 uses.
- It is not a substitute for the §3.1 pre-trade check, the venue allowlist
  (Part A), the kill switch, or the design-review sign-off gate. It is one
  layer — the hard capital backstop at the boundary — among the Phase-3 safety
  bounds, all of which must hold before a live order is placed.

## Part C — Per-market and per-event exposure limits

> Status: **design** (trade-trace-i9mp).
> This part specifies the per-market and per-event(negRisk-grid-aware)
> exposure-limit contract a future Phase-3 execution module MUST satisfy. It
> ships no code, table, or enforcement; it is a precondition for that code.

## 18. Why this contract exists (and how it differs from the global cap and the §3.1 check)

[`VISION.md`](../../VISION.md) lists *"per-market exposure limits"* among the
bounds *a human set* in the north-star picture (`## Where this ends up`: *"all
within bounds a human set: capital caps, per-market exposure limits, venue
allowlists, a kill switch"*). Part B (§§10–17) specifies the **single global**
capital ceiling; this part specifies the **per-market** and **per-event**
ceilings that bound *concentration* below that global number. The two are
layered, not redundant: a portfolio can sit comfortably under the global cap
while being dangerously concentrated in one market or one resolution event, and
this contract is the boundary backstop against that concentration.

There are already two concentration-shaped surfaces in the substrate, and this
contract is deliberately **distinct** from both:

- [`autonomous-trader-substrate.md` §3.1](autonomous-trader-substrate.md#31-versioned-risk-policies-and-pre-trade-checks)
  defines a **deterministic pre-trade check** whose covered limit classes
  already include `market_exposure` and `category_exposure` (the shipped
  evaluator's `limit_class` set). That evaluator returns a
  `pass`/`warn`/`fail`/`missing_data` verdict, *"writes no rows and never
  blocks, signs, places, or routes an order"* — it is an **advisory check
  record**, and a `warn` (or even a waived `fail`) does not by itself stop
  anything.
- The `report.portfolio_exposure` projection already derives **per-event
  exposure sets** from the open-`positions` projection: it groups positions by
  Polymarket `event_id`/`event_slug`, computes a per-event
  `conservative_event_risk_amount`, and caveats negative-risk and
  mutually-exclusive grids with stable codes
  (`NEGATIVE_RISK_EQUIVALENCE_UNCONVERTED`,
  `MUTUALLY_EXCLUSIVE_EVENT_CONCENTRATION_UNCONVERTED`). That projection is a
  **read-only diagnostic**; it computes grouped exposure but enforces nothing.

This per-market/per-event cap is the **hard, boundary-enforced** counterpart:
the last gate before an order is transmitted, **not waivable at order time**,
and **default-deny on breach** — an order that would push per-market or
per-event exposure above its active cap is hard-rejected the same way a
non-allowlisted venue (§6) or a global-cap breach (§11) is, before any network
or credential use. **A passing §3.1 `market_exposure`/`category_exposure` check
never authorizes exceeding the cap, and the cap never relies on a pre-trade
check having run.**

## 19. Current per-market and per-event exposure is computed from the append-only positions projection

The figure the cap is evaluated against is **computed deterministically from
the journal's own append-only exposure projection**, reusing the
current-exposure precedence — it is never read from a broker, a balance call,
or caller assertion of its own accord.

- **Reuse the current-exposure precedence.** Per
  [`autonomous-trader-substrate.md` §2.2](autonomous-trader-substrate.md#22-provenance-and-as-of-fields)
  and the
  [current-exposure agent contract §1](current-exposure-agent-contract.md#1-boundary-and-precedence):
  open `positions` rows backed by `position_events` are the canonical exposure
  source and **outrank** decision-only activity; `watch` decisions are never
  exposure; `actual_*`/`add`/`reduce` decisions are record-only unless a linked
  projection exists; imported account truth is separately labelled and
  reconciled, never treated as Trade Trace-native proof. The boundary computes
  current per-market and per-event exposure from exactly these canonical rows.
- **Per-market exposure** is the committed exposure of the open `positions`
  rows for a single market (`instrument_id`), computed conservatively (§21):
  worst-case capital-at-risk of the existing live position plus resting orders
  on that market, plus the new order's worst-case capital-at-risk.
- **Per-event exposure** is the aggregate over the **event group** the market
  belongs to — the same grouping `report.portfolio_exposure` derives from
  `event_grouping`/`polymarket_identity` metadata (`event_id`, falling back to
  `event_slug`, falling back to an `ungrouped:<instrument_id>` singleton when no
  event metadata exists). A negative-risk / categorical grid is one event group;
  every market that resolves from the same underlying event aggregates into one
  per-event figure (§20).
- **The cap reads the projection, never mutable state.** As with the global cap
  (§14) and the venue allowlist (§4), the exposure the boundary enforces against
  is the **deterministic projection** of append-only rows, so a skeptic
  replaying the journal can reconstruct exactly what per-market and per-event
  exposure was in force at the moment of any decision.

## 20. Correlated YES legs aggregate so a single-event cap cannot be collectively breached

A negative-risk / categorical Polymarket grid (one event, N mutually-exclusive
candidate markets) is the failure mode this part exists to close: N separate
YES legs, each comfortably under a per-*market* cap, can collectively pile a
large directional bet onto a single resolution event. **The per-event cap MUST
aggregate correlated legs so the event-group total — not the per-market total —
is what the cap is checked against.**

- **Aggregate before checking the event cap.** Every open position and every
  pending order whose market maps to the same event group (§19) contributes to
  one per-event exposure figure. A new order is rejected if it would push the
  **event-group aggregate** above the per-event cap, even if it leaves every
  individual per-market figure within the per-market cap. A single-event cap
  that summed only one leg at a time would be trivially defeated by splitting
  one bet across the grid's legs.
- **Aggregation is conservative; equivalence is not assumed.** The boundary does
  **not** convert or net correlated legs into a smaller "true" exposure (no
  redemption, settlement, or negative-risk equivalence transform) — consistent
  with `report.portfolio_exposure`'s `NEGATIVE_RISK_EQUIVALENCE_UNCONVERTED`
  caveat. Unconverted, the conservative aggregate is the *gross* event-group
  capital-at-risk; the cap is enforced against that conservative figure, never
  against an optimistic netted one. (Whether a future, owner-approved version
  may credit mutually-exclusive netting is an open question, §22.)
- **Missing event metadata does not dissolve the group into safe singletons.**
  If the metadata needed to assign a market to its event group is missing or
  stale, the boundary treats the per-event exposure as **`missing_data` and
  denies** (§21) rather than silently treating the market as an unbounded
  `ungrouped:` singleton — otherwise dropping the grouping metadata would be a
  way to evade the event cap.

## 21. Default-deny, and missing_data is not a soft pass

The per-market and per-event caps share the global cap's safety posture: deny
is the default decision on breach, and the absence of the data needed to prove
the order is *within* a cap is itself a denial.

- **Default-deny on breach.** If placing (or replacing/increasing) an order
  would push per-market or per-event exposure above its active cap, the order is
  **hard-rejected before any side effect** (no network call, no credential read,
  no transmission), exactly as in §6 and §11.
- **Worst-case capital-at-risk.** Each figure uses the worst-case capital the
  position/order could consume (e.g. full notional at the limit price for a
  buy), never an optimistic mid or expected-fill estimate — the same
  conservative computation the global cap uses (§11).
- **`missing_data` is not a soft pass.** Mirroring
  [`autonomous-trader-substrate.md` §3.1](autonomous-trader-substrate.md#31-versioned-risk-policies-and-pre-trade-checks)
  (*"`missing_data` is not a soft pass"*) and the global cap's
  `cap_missing_data` rule (§14): if the inputs needed to compute per-market or
  per-event exposure are missing or stale — an unreadable/stale `positions`
  projection (`PROJECTION_MISSING`/`PROJECTION_STALE` from the current-exposure
  contract), absent event-group metadata (§20), or a missing mark needed to
  value the position — the boundary treats the state as `missing_data` and
  **denies**. It never optimistically assumes headroom.
- **No order-time override.** As with §11, there is no per-order flag, force,
  waiver, or bypass that lets the agent or the execution module exceed a
  per-market or per-event cap. Unlike a §3.1 warning, these caps are
  **non-waivable at order time**; the only way concentration headroom increases
  is a new, approved limit-config event (raising follows the §15 asymmetry —
  lowering is immediate, raising requires an approval record).
- **Default state is the lowest configured tier, never unbounded.** Mirroring
  §11: an absent, unparseable, or unauthorized per-market/per-event cap
  configuration resolves to `0` (deny-all concentration), never to "unlimited".
  A reviewer reading a clean checkout must be able to conclude the system, as
  shipped, may commit **zero** per-market and **zero** per-event exposure.

## 22. Every breach is recorded as an append-only blocked / violation record

Like the venue allowlist (§6) and the global cap (§14), every per-market /
per-event cap evaluation is **recorded append-only**, and every breach attempt
leaves a durable, replayable blocked/violation record per
[`autonomous-trader-substrate.md` §3.3](autonomous-trader-substrate.md#33-approval-and-waiver-records).

- **Each evaluation is an append-only event.** Allow or deny, the boundary
  records the attempted order's per-market and per-event committed figures, the
  active per-market and per-event caps, the cap `policy_version` (caps are
  immutable versioned data, §13), the event group it aggregated, the contributing
  position/order record IDs, the reject reason on denial
  (`market_exposure_exceeded` / `event_exposure_exceeded` /
  `exposure_missing_data`), the originating intent reference, and a timestamp —
  scrubbed of secrets per §5.
- **Breach attempts are blocked/violation records, not silent drops.** A skeptic
  replaying the journal can see every order the per-market/per-event cap declined
  and the exact concentration figure that declined it. Hard-block exposure rules
  must not be silently waived (§3.3): if an override record is ever allowed for
  audit completeness, reports MUST label it as a violation or non-compliant
  override.
- **Caps are immutable versioned policy.** Each per-market and per-event cap
  value is an immutable `policy_version` (§13); changing a cap mints a new
  version, and every reject cites the exact version and tier it was evaluated
  against.

## 23. Open questions (owner decisions)

These are **owner decisions** the agent must not make for itself; the values
below are recommendations to weigh, flagged for sign-off in the
[execution design-review gate](execution-design-review-gate.md#2-scope-two-sign-offs-not-one)
(the live-capital sign-off, SO-2) and the per-intent approval surface
([`autonomous-trader-substrate.md` §3.3](autonomous-trader-substrate.md#33-approval-and-waiver-records)).
This bead is labeled `needs-design`: the decisions below require explicit owner
sign-off before any per-market or per-event cap value is committed as
authorized. The agent may *read* the active caps and *surface* that it has
earned more headroom; it may never author the approval that loosens them
(§15, §22).

| Decision | Recommendation to weigh |
| --- | --- |
| **Per-market exposure ceiling** — the hard cap on committed capital-at-risk in any single market. | A small fraction of the active global ceiling (§11), small enough that no single market can dominate the bankroll. The agent must NOT pick this. |
| **Per-event-group ceiling** — the hard cap on aggregate committed exposure across one event group (a negRisk/categorical grid). | A ceiling **at least as large as the per-market cap but well below the global cap**, sized so a full grid's correlated YES legs (§20) cannot collectively become a bankroll-sized single-event bet. |
| **Denomination** — is each cap a notional dollar amount, a share/contract count, or a fraction of staged capital? | A **fraction of the active staged-capital ceiling** (§12) is recommended so concentration limits ramp with the global cap rather than needing re-approval at every tier — but this is an owner decision and is recorded as a versioned cap value (§13) whichever denomination is chosen. Share-count and fixed-notional are the alternatives to weigh. |
| **Correlated-market treatment beyond one event** — do markets that resolve from the *same underlying real-world event* but sit in *different* Polymarket event groups aggregate together? | **Conservative default: aggregate only by the explicit Polymarket event group (§19); do not infer cross-event correlation.** Treating distinct event groups as one would require an owner-defined correlation map; until one exists, cross-event correlation is surfaced as a caveat, not silently netted or silently summed. |
| **Mutually-exclusive netting credit** — may a future version credit mutually-exclusive grid legs (no equivalence conversion is assumed by default, §20)? | **Default: no netting credit — enforce against the conservative gross aggregate.** Any future netting credit is a separate, owner-approved versioned cap policy, never a silent default. |

## 24. What this contract does NOT do

- It does not place, cancel, halt, or remediate any order, and ships no
  execution code, tool, table, cap, or enforcement.
- It does not set the caps. The per-market ceiling, the per-event-group ceiling,
  the denomination, and the correlated-market treatment are the owner's
  decisions (§23); the agent may read the active caps but may never author the
  approval that loosens them (§15, §22).
- It does not move or hold funds, and it does not read account balances of its
  own accord. The per-market/per-event figures it enforces against are computed
  from the journal's own append-only `positions`/`position_events` projection
  plus caller-supplied marks, the same inputs §3.1 and the current-exposure
  contract use.
- It does not convert, redeem, settle, or net correlated legs into a smaller
  exposure of its own accord; it enforces against the conservative gross
  aggregate and caveats negative-risk / mutually-exclusive grids (§20).
- It is not a substitute for the global capital cap (Part B), the §3.1 pre-trade
  check, the venue allowlist (Part A), the kill switch (Part D), or the
  design-review sign-off gate. It is one layer — the concentration backstop at
  the boundary — among the Phase-3 safety bounds, all of which must hold before
  a live order is placed.

## Part D — Kill switch (halt + flatten)

> Status: **design** (trade-trace-8sbv).
> This part specifies the kill-switch contract a future Phase-3 execution
> module MUST satisfy. It ships no code, tool, table, signal handler, or
> enforcement; it is a precondition for that code. The substrate today places
> no orders and **cannot halt, cancel, or flatten** anything
> ([`autonomous-trader-substrate.md` §1](autonomous-trader-substrate.md#1-product-boundary-and-enforcement-contract),
> §5.3 records *that* a halt happened but cannot *cause* one) — this contract
> describes authority that only the Phase-3 boundary will hold.

## 25. Why this contract exists (and what it is not)

[`VISION.md`](../../VISION.md) names *"a kill switch"* among the bounds *a
human set* in the north-star picture (`## Where this ends up`: *"all within
bounds a human set: capital caps, per-market exposure limits, venue
allowlists, a kill switch"*) and lists *"kill switches … append-only audit
trail underneath everything"* as a Phase-3 safety bound (`## How we get
there` → *Phase 3*). The venue allowlist (Part A), the global cap (Part B),
and the exposure limits (Part C) each bound *what an individual order may do*.
The kill switch is the orthogonal, **portfolio-wide emergency stop**: a single
operator- or supervisor-triggerable control that freezes new execution and —
on the stronger setting — actively unwinds open exposure, regardless of what
any per-order check would have allowed.

This is a deliberate escalation of authority the current substrate forbids
itself:

- [`autonomous-trader-substrate.md` §5.3](autonomous-trader-substrate.md#53-reconciliation-reports)
  can *record* an external halt as an imported execution fact, but the
  substrate *"does not cancel, halt, or remediate external orders"* and keeps
  any halt/cancel mechanism outside the product
  ([§1](autonomous-trader-substrate.md#1-product-boundary-and-enforcement-contract)). The execution
  module introduced in Phase 3 is the first component that CAN act, so it is
  the first component that needs — and the only component that may hold — a
  kill switch.
- The kill switch is **not** the per-trade pre-trade check
  ([§3.1](autonomous-trader-substrate.md#31-versioned-risk-policies-and-pre-trade-checks)),
  which evaluates one proposed intent and *"writes no rows and never blocks,
  signs, places, or routes an order."* The kill switch is a coarse, global,
  boundary-enforced state, not an advisory per-intent verdict. A passing
  pre-trade check never overrides an engaged kill switch; once the switch is
  engaged, every order is denied irrespective of its individual verdict.

## 26. What the kill switch does: two settings, HALT and HALT+FLATTEN

The kill switch puts the boundary into a **close-only / frozen state** — the
`close_only` mode already named as a policy mode in
[`autonomous-trader-substrate.md` §3.1 L91](autonomous-trader-substrate.md#31-versioned-risk-policies-and-pre-trade-checks)
(*"paper-only/close-only modes"*). It has two configured settings; **which
setting an activation uses is part of the activation record (§28)**.

- **HALT (the floor — always at least this).** Every kill-switch activation,
  at minimum, **halts opening risk**: no new opening orders, no increases, no
  replacements that raise exposure are transmitted. The boundary enters the
  `close_only` state — only orders that *reduce* exposure on an existing
  position (and, per the setting below, cancellations of resting orders) are
  permitted; everything that opens or grows risk is hard-rejected exactly as a
  cap breach is (§11), before any network or credential use.
- **CANCEL-RESTING (part of every activation).** On activation the boundary
  also **cancels the agent's own resting orders** at the allowlisted venue
  where it can — a resting open order is latent opening risk. Cancellation is
  best-effort against the venue but its *intent* is recorded immediately (§28);
  a venue that cannot confirm a cancel leaves a recorded `cancel_unconfirmed`
  that reconciliation (§5.3) must surface, never a silent assumption the order
  is gone.
- **HALT+FLATTEN (the stronger setting).** When the active setting is
  HALT+FLATTEN, the boundary additionally emits **closing orders to flatten
  open positions** down toward zero exposure, using conservative,
  exposure-reducing orders only. Flattening never opens a new directional
  position, never crosses from long to short past zero, and is itself bounded
  by the venue allowlist (Part A) and the append-only audit discipline (§28) —
  it is a constrained unwind, not an unconstrained trading mandate.

**Owner decision, resolved (default).** The default setting is **HALT (+
cancel-resting), with HALT+FLATTEN available as an explicit, operator-selected
escalation**, not the automatic default. Rationale: an automatic flatten can
*realize* losses and pay spread/slippage at the worst possible moment (a venue
outage, a data glitch, a reconciliation false-positive), so reflexive
liquidation can be more dangerous than freezing. Freezing opening risk and
cancelling resting orders stops the bleeding deterministically and without
market impact; converting that freeze into an active unwind is a judgment the
operator (or an explicitly authorized supervisor policy) makes per activation.
A purely automatic trigger (§27) therefore engages **HALT (+ cancel-resting)**
unless the owner has pre-authorized auto-flatten for that specific trigger in
signed config (§4 / [security-execution.md §4](security-execution.md#4-controls)).
This is the single owner sign-off the bead's first open question demands; the
alternatives are weighed in §31.

## 27. Who and what can trigger it (and the auto-trigger set)

The kill switch is triggerable by **deliberate human/supervisor action** and
by a fixed set of **automatic safety conditions**. Triggering it is always
*safe-direction* (it tightens, never loosens), so — like lowering a cap (§15)
— it requires **no approval record**; it takes effect the instant it is
recorded.

- **Human operator (always).** The operator can engage the kill switch at any
  time, at either setting, with no precondition and no approval gate. This is
  the primary control and the one the VISION promise rests on.
- **Supervisor agent (engage only).** An independent supervisor agent may
  *engage* the kill switch (HALT, or HALT+FLATTEN if the owner pre-authorized
  it for the supervisor in signed config). A supervisor may **never disarm**
  it — re-arming is operator-only (§30). The trading agent itself may *request*
  or *surface the need for* a halt but, consistent with the self-grant
  invariant, the engage/disarm authority is not its own.
- **Automatic triggers (resolved set).** The boundary **auto-engages HALT (+
  cancel-resting)** — fail-safe, no human in the loop — on any of the
  following, each of which is a condition under which continuing to open risk
  is unsafe:
  - **Cap / exposure breach that should have been impossible** — a global
    (§11) or per-market/per-event (§21) cap is found already breached (e.g. a
    reconciliation reveals exposure above the ceiling), indicating the
    per-order gate was bypassed or the projection was wrong.
  - **Audit-integrity failure** — the append-only audit trail cannot be
    written, is unreadable, or fails its tamper-evidence check. If the boundary
    cannot *record* what it is doing, it must not *do* it (the audit trail is
    *"underneath everything"*; capability never outruns accountability).
  - **Reconciliation mismatch (critical)** — a reconciliation
    ([§5.3](autonomous-trader-substrate.md#53-reconciliation-reports)) surfaces
    a critical mismatch (e.g. an external fill with no matching intent, a
    local-vs-imported position/balance mismatch, a rejected order after an
    approved intent), meaning local state and venue truth have diverged and the
    boundary can no longer trust its own exposure figure.
  - **Calibration drift below the gate floor** — the [phase-gate readiness
    criteria](phase-gates.md#2-the-criteria) calibration signals (`brier`,
    `skill_vs_market`) regress below the floor that authorized the active
    staged-capital tier (§12). This is the same evidence that lowers the cap
    immediately on lost eligibility (§12); here it additionally trips HALT so a
    demonstrably mis-calibrated agent stops opening new risk, not merely caps
    it.
  - **Config-integrity failure** — the signed deterministic config (caps,
    allowlist, exposure limits, kill-switch state) fails its integrity check
    ([security-execution.md §4](security-execution.md#4-controls)). An
    unsigned/tampered/unverifiable bound **fails closed**, which for the kill
    switch means engaged.

  The **exact thresholds** (which reconciliation codes count as critical, the
  precise calibration floor, debounce/hysteresis to avoid flapping) are owner
  decisions (§31); the *set* of auto-trigger conditions above is the resolved
  contract.

## 28. Latency, idempotency, and recording every activation + transition

- **Latency expectation: HALT is immediate, the floor is fast.** Engaging HALT
  (stop opening risk) takes effect **synchronously, before the next order is
  transmitted** — it is a local state flip on the order path, not a network
  round-trip, so there is no window in which an opening order slips past an
  engaged switch. Cancel-resting and flatten are necessarily *best-effort
  against the venue* and bounded by venue latency; their **intent is recorded
  immediately**, and their venue-confirmation lands as a later append-only
  event (§5.1 import lifecycle), with anything unconfirmed left as a
  reconciliation item (§5.3), never assumed complete.
- **Idempotency.** Activation and disarm are **idempotent**: engaging an
  already-engaged switch is a no-op that records no duplicate state transition
  (it may record a redundant *trigger* observation for audit, but the state
  stays engaged exactly once). Every cancel/flatten order the switch emits
  carries an idempotency key (per
  [security-execution.md §4 control 3](security-execution.md#4-controls)) so a
  retried cancel or flatten is never a second order. Re-running the same
  trigger never double-flattens.
- **Every activation and state transition is an append-only event.** Each
  engage, each disarm (§30), and each emitted cancel/flatten order is written
  to the append-only audit trail — the same lifecycle discipline as every other
  order action
  ([autonomous-trader-substrate.md §3](autonomous-trader-substrate.md#3-execution-lifecycle-contract);
  [security-execution.md §4 control 5](security-execution.md#4-controls)). The
  activation record carries, at minimum: the trigger source
  (`human` / `supervisor` / one of the §27 auto-trigger codes), the setting
  applied (HALT / HALT+FLATTEN), the active cap/policy `policy_version` and
  signed-config reference in force, an idempotency key, a timestamp, and — for
  an auto-trigger — the contributing record IDs (the breaching cap evaluation,
  the failing reconciliation/audit/calibration record) that fired it, scrubbed
  of secrets per §5. The **current kill-switch state is the deterministic
  projection** of these append-only events, never mutable state that could
  drift from its audit trail (mirroring §4 / §14). A skeptic replaying the
  journal can reconstruct exactly when the switch was engaged, by what, at
  which setting, and what it cancelled or flattened.

## 29. Default-deny: if the switch cannot be confirmed functional, do not trade

The kill switch is a **precondition for trading at all**, enforced
fail-closed:

- **Unconfirmable kill switch ⇒ no execution.** If, at the moment an order
  would be transmitted, the boundary cannot positively confirm that the kill
  switch is present, wired into the order path, and its state is readable from
  the append-only projection, the boundary treats execution as **frozen and
  denies the order** — the same `missing_data`-denies posture as the caps (§11,
  §21). A boundary that cannot prove it can stop itself does not start.
- **Engaged state is sticky and fails closed.** While engaged, every opening
  order is hard-rejected; an indeterminate or unreadable kill-switch state is
  treated as *engaged*, never as *clear*. The switch never fails *open* (into
  permitting trading); ambiguity always resolves to the frozen state.
- **Config-integrity ties in.** Because the kill-switch state is part of the
  signed deterministic config
  ([security-execution.md §4 control 4](security-execution.md#4-controls)), an
  unsigned, tampered, or unverifiable config means the kill-switch state cannot
  be trusted, which per the rule above means execution stays frozen. Widening —
  including *disarming* the switch — requires the owner's signing authority,
  not mere filesystem write access.

## 30. Re-arming requires explicit operator action recorded as an approval record

Disarming the kill switch — returning the boundary from the frozen/close-only
state to normal opening-risk execution — is the **only loosening direction**,
and it is gated exactly like raising a cap (§15):

- **Operator-only, never the agent, never the supervisor.** Re-arming is a
  **human-operator decision**. The trading agent may *surface* that the
  triggering condition has cleared and *propose* re-arming; it may never author
  the action that re-arms itself. A supervisor agent may engage but **never
  disarm** (§27) — concentrating the loosening authority in the operator is the
  whole point of an emergency stop. This resolves the bead's third open
  question: **re-arm authority is human-operator-only.**
- **Recorded as an append-only approval record.** Re-arming requires an
  **append-only approval record**, reusing the approval contract of
  [`autonomous-trader-substrate.md` §3.3](autonomous-trader-substrate.md#33-approval-and-waiver-records):
  the approving actor/mode (`human`), the kill-switch event being cleared, an
  attestation that the triggering condition has been resolved, the
  cap/`policy_version` and signed-config reference re-entered into force, an
  idempotency key, and a timestamp. A disarm event lacking a matching approval
  record is invalid and the projection MUST reject it, **keeping the switch
  engaged**.
- **An auto-trigger cannot self-clear.** A kill switch engaged by an automatic
  condition (§27) does **not** silently re-arm when the condition appears to
  pass; clearing it still requires the operator approval record above, so a
  transient flap or a partially-recovered reconciliation can never quietly
  hand authority back to the agent. (The owner may, in signed config, define
  narrowly-scoped exceptions — e.g. a brief auto-debounce on a flapping
  data-staleness trigger — but any such exception is an explicit, recorded,
  owner-set policy, never an implicit default; §31.)

## 31. Open questions (owner decisions)

These are **owner decisions** the agent must not make for itself; the values
below are recommendations to weigh, flagged for sign-off in the
[execution design-review gate](execution-design-review-gate.md#2-scope-two-sign-offs-not-one)
(both sign-offs reference the kill switch) and the per-intent approval surface
([`autonomous-trader-substrate.md` §3.3](autonomous-trader-substrate.md#33-approval-and-waiver-records)).
This bead is labeled `needs-design`: the decisions below require explicit owner
sign-off before any kill-switch behavior is committed as authorized. The agent
may *read* the kill-switch state and *surface* that a trigger has cleared; it
may never author the action that disarms it (§30).

| Decision | Recommendation to weigh |
| --- | --- |
| **HALT-only vs HALT+FLATTEN as the default** (bead open question 1). | **HALT (+ cancel-resting) by default; HALT+FLATTEN as an explicit, operator-selected escalation** (§26). A reflexive auto-flatten realizes losses and pays spread/slippage at the worst moment (outage, data glitch, false-positive); freezing opening risk and cancelling resting orders stops the bleeding deterministically and without market impact. Auto-triggers (§27) engage HALT unless the owner pre-authorized auto-flatten for that specific trigger in signed config. |
| **The auto-trigger set** (bead open question 2). | Resolved set in §27: cap/exposure breach found already-breached, audit-integrity failure, critical reconciliation mismatch, calibration drift below the active tier's gate floor, and config-integrity failure. The owner sets the **thresholds** (which reconciliation codes are critical, the exact calibration floor, debounce/hysteresis) but the *set* is the contract. |
| **Re-arm authority** (bead open question 3). | **Human-operator-only, recorded as an approval record** (§30). A supervisor may engage but never disarm; an auto-trigger never self-clears. Optional, narrowly-scoped, owner-signed auto-debounce exceptions for flapping data-staleness triggers are the only loosening that may be policy-driven, and even those are explicit recorded config, never implicit. |
| **Cancel/flatten execution semantics** — order type, price aggressiveness, and partial-fill handling when flattening. | Conservative, exposure-reducing orders only (no crossing past zero, no new directional position); flatten is bounded by the venue allowlist (Part A) and recorded append-only (§28). The exact order type / limit aggressiveness / time-in-force for a flatten is the owner's, weighed against venue liquidity. |
| **Latency / heartbeat SLOs** — the maximum tolerated time for HALT to take effect and for a venue cancel/flatten confirmation before it is escalated. | HALT is synchronous on the local order path (effectively immediate, §28); set an explicit upper bound on venue cancel/flatten confirmation after which the unconfirmed action is escalated as a reconciliation critical (§5.3). The numeric SLOs are the owner's. |

## 32. What this contract does NOT do

- It does not place, cancel, halt, or flatten any order, and ships no execution
  code, tool, table, signal handler, state machine, or enforcement. The
  substrate today cannot halt or flatten anything
  ([`autonomous-trader-substrate.md` §1](autonomous-trader-substrate.md#1-product-boundary-and-enforcement-contract),
  §5.3).
- It does not authorize execution on any venue, and it does not by itself turn
  the kill switch on or off. Turning execution on at all is the one-time human
  sign-off in the
  [execution design-review gate](execution-design-review-gate.md); engaging or
  disarming the switch at runtime is the operator/supervisor/auto-trigger
  authority of §§27 and 30.
- It does not pick the trades, and it does not let the agent disarm itself. The
  kill switch is a bound a human sets; the agent may read its state and propose
  re-arming, but the engage/disarm authority is never the agent's (§§27, 30).
- It does not move or hold funds, hold credentials, or read account balances of
  its own accord. Credentials live behind the isolated boundary and its own
  [threat-model addendum](security-execution.md); the flatten/cancel exposure
  figures it acts on are computed from the journal's own append-only
  exposure/order projection (§19), the same inputs §3.1 and the caps use.
- It is not a substitute for the venue allowlist (Part A), the global capital
  cap (Part B), the per-market/per-event exposure limits (Part C), the §3.1
  pre-trade check, or the design-review sign-off gate. It is the orthogonal
  portfolio-wide emergency stop — one layer among the Phase-3 safety bounds,
  all of which must hold before a live order is placed.
