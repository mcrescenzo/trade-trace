# Security: Live-Execution + Credential-Handling Threat Model (Phase 3)

> Status: **design — not implemented** (trade-trace-qtzp). This document is
> the [`security.md`](security.md) §1 *addendum* that the shipped threat
> model explicitly anticipates ("future surfaces ... will need their own
> addendum"). It describes Phase-3 bounded-live execution, which **does not
> ship**: there is no execution code, no credential field, no venue call, and
> no live order authority in the current substrate. Nothing here is a
> capability claim. It is a design-only artifact under EPIC trade-trace-u1gv;
> the controls below are requirements that future
> implementation beads must satisfy, gated by
> [`execution-design-review-gate.md`](execution-design-review-gate.md).

Source bead: trade-trace-qtzp. Parent epic: trade-trace-u1gv (Phase-3
Execution Safety Design). Consumed as a required input by the
[execution design-review / sign-off gate](execution-design-review-gate.md#3-required-design-artifact-inputs).

Companion docs: [security.md](security.md) (the shipped, narrow,
credential-blind threat model this extends),
[autonomous-trader-substrate.md](autonomous-trader-substrate.md),
[phase-gates.md](phase-gates.md), [operability.md](operability.md),
[contracts.md](contracts.md).

## 1. Why this addendum exists (scope handoff from `security.md`)

The shipped threat model in [`security.md` §1](security.md#1-purpose) is
deliberately narrow because the substrate "does not execute trades, hold
custody of funds, or call brokers." [`security.md` §2](security.md#2-assets)
records what is *notably not held*: "broker credentials, exchange API keys,
wallet seed phrases, signing keys." Phase 3 — bounded-live execution behind
an isolated safety boundary — introduces every one of those, plus live order
authority and real capital. That is an entirely new attack surface the
shipped model intentionally excludes.

This addendum does **not** relax the shipped invariants. The journal/memory
**core** stays credential-blind forever ([`VISION.md` "What never
changes"](../../VISION.md#what-never-changes): "The journal and memory core
stays credential-blind forever. Execution, when it comes, lives behind its
own isolated safety boundary with its own design review."). The credential
ban verified mechanically in [`security.md` §6](security.md#6-credential-ban)
continues to apply to the core: no broker/wallet/signing/seed/api-key column,
tool argument, or description may exist in the journal schema. The new assets
below live **only** behind the execution boundary — a process the core cannot
read — never in the journal the rest of this repository is about.

The boundary between the credential-blind core and the credential-holding
execution process is **the** central control. Everything else in this
document is defense in depth around that single line.

## 2. Phase-3 assets

These exist only behind the execution boundary, never in the journal core.

| Asset | Where it lives (boundary-only) | What its compromise grants an attacker |
|---|---|---|
| Venue API keys | Boundary-held secret store (owner decision: OS keyring / external signer / HSM — §8). Never a journal column. | The ability to authenticate as the operator to a trading venue: place, cancel, or query orders within the key's venue-side permissions. |
| Signing material / private keys | Boundary-held or, preferably, an external signer process the boundary calls but never reads (§8). | The ability to sign orders or on-chain transactions — direct authority over capital, not merely API access. |
| Session / auth tokens | Ephemeral, boundary-held; short-lived. | Time-bounded impersonation of an authenticated venue session — a smaller blast radius than a long-lived key, hence preferred where venues support it. |
| Live order authority | The boundary's *only-path-to-an-order* code (the isolation contract, trade-trace-nl13 / trade-trace-2ki5). | The ability to actually route an order — the capability the credentials unlock. Held separately from the credentials so that even a credential holder cannot route an order that violates the deterministic bounds (§4). |
| Real capital | At the venue, under the operator's account. | Direct financial loss, bounded by the staged capital cap and per-market/per-event exposure limits (§4). The blast-radius requirement (§4) exists precisely to bound this asset's worst case. |
| The deterministic policy config | Caps, venue allowlist, exposure limits, kill-switch state — owner-set inputs the agent cannot raise (trade-trace-6fkv / trade-trace-e3sm / trade-trace-i9mp / trade-trace-8sbv). | The ability to *widen the bounds* — raise a cap, add a venue, disable the kill switch — which is more dangerous than any single key, because it changes what every future order may do. Hence §4 requires this config be signed/verified, not merely a writable file. |

Notably still *not* held by the journal core: any of the above. The core
sees an agent's recorded *intent* and the *append-only record* of what the
boundary did with it — never a credential, never the authority to route.

## 3. Attacker model

Extends [`security.md` §3](security.md#3-attacker-model). The local-user,
other-UID, supply-chain, and leakage attackers there still apply; the rows
below are the *new* adversaries that live execution introduces.

| Attacker | Capability | Why the control below bounds it |
|---|---|---|
| Credential exfiltration via compromised dependency at the boundary | A malicious or compromised package loaded *inside the boundary process* reads the venue keys / signing material and ships them to a remote endpoint. | The boundary inherits [`security.md` §7](security.md#7-no-background-network-no-telemetry-no-auto-update) deny-by-default outbound: the only permitted egress is the explicit, allowlisted venue path (§4). An external signer the boundary never reads (§8) removes the key from the exfiltratable surface entirely. |
| Prompt injection steering order placement | Market text, news, or source excerpts the agent reads contain adversarial instructions ("place a large YES at any price"). | **The agent's free-text reasoning can never itself authorize a credential or a venue (§5).** The agent emits a *proposed intent*; the deterministic policy then bounds it against owner-set caps/allowlist/exposure. Injected text can at most influence the agent's *recorded forecast*, which the policy still clamps — it cannot raise a cap, add a venue, or bypass the kill switch. |
| Order replay / duplication | A retried or replayed submission double-places an order, doubling exposure. | Idempotent order submission (§4): every order carries an idempotency key, so a retry of the same intent is a no-op at the boundary, not a second fill — the same append-only-write discipline already required of the core ([contracts.md](contracts.md), "every retryable write requires an `idempotency_key`"). |
| Hijacked boundary process | An attacker who achieves code execution *inside* the boundary acts with the boundary's full authority: its credentials and its order-routing path. | The worst-case blast radius is bounded by the **staged capital cap and per-market/per-event exposure limits (§4)** — a hijacked boundary still cannot exceed the owner-set ceiling, and the kill switch (§4) lets the operator halt and flatten. This is the defense-in-depth reason a single compromised key must not exceed the staged cap. |
| Venue-side spoofing / response tampering | A man-in-the-middle or a malicious venue endpoint returns forged fills, prices, or acknowledgements to mislead the agent or the audit. | Venue calls use authenticated, integrity-checked transport (owner decision §8); fills are reconciled against independent account snapshots ([autonomous-trader-substrate.md §5.3](autonomous-trader-substrate.md#53-reconciliation-reports)); the append-only audit (§4) records what was *sent and received*, so a skeptic can detect a divergence between the boundary's claims and reconciled venue state. |
| Compromised policy config | An attacker edits the caps / allowlist / kill-switch file to widen the bounds the deterministic policy enforces. | The config is signed/verified before the boundary honors it (§4): an unsigned or tampered config fails closed (execution stays frozen), so widening the bounds requires the owner's signing authority, not mere filesystem write access. |

## 4. Controls

Each control maps to a Phase-3 design bead; this document states the
*requirement*, the bead delivers the contract.

1. **Credential isolation to the boundary.** Venue keys, signing material,
   and session tokens live *only* behind the execution boundary, never in the
   journal core. The credential-blind isolation contract (trade-trace-2ki5)
   and the boundary architecture (trade-trace-nl13) make the boundary the
   *only* path to an order and the *only* holder of credentials. The core's
   credential ban ([`security.md` §6](security.md#6-credential-ban)) is
   unchanged and continues to be enforced by `tests/security/`.

2. **Deny-by-default outbound, scoped to the venue path.** The boundary
   inherits the shipped no-background-network posture
   ([`security.md` §7](security.md#7-no-background-network-no-telemetry-no-auto-update)):
   no telemetry, no auto-update, no incidental egress. The *only* permitted
   outbound is the explicit, allowlisted venue endpoint(s) (trade-trace-6fkv),
   over authenticated, integrity-checked transport. Everything else is denied,
   bounding the credential-exfiltration attacker (§3).

3. **Idempotent order submission.** Every order submission carries an
   idempotency key; a retry of an already-submitted intent is a no-op, never a
   second fill. This is the order-routing analogue of the append-only write
   discipline the core already enforces, and it neutralizes the replay /
   duplication attacker (§3).

4. **Signed/verified deterministic config.** The owner-set bounds — capital
   caps and the staged schedule (trade-trace-e3sm), the venue allowlist
   (trade-trace-6fkv), per-market/per-event exposure limits
   (trade-trace-i9mp), and the kill switch (trade-trace-8sbv) — are
   integrity-verified before the boundary honors them. An unsigned, tampered,
   or unset bound **fails closed**: execution stays frozen. No agent action
   and no injected text can widen a bound; only the owner's signing authority
   can. The maximum-blast-radius requirement is explicit: **a single
   compromised credential or a hijacked boundary cannot exceed the staged
   capital cap and exposure limits** — the staged ramp never auto-raises, and
   the kill switch can halt and flatten on the operator's demand.

5. **Append-only, tamper-evident audit.** Every order action — proposed,
   bounded, submitted, filled, rejected, halted, flattened — lands as an
   append-only event in the journal core, exactly like every other lifecycle
   record ([autonomous-trader-substrate.md §3](autonomous-trader-substrate.md#3-execution-lifecycle-contract)).
   No execution path mutates or deletes prior records. A skeptic can **replay
   every order** from the journal and reconcile it against independent account
   snapshots ([autonomous-trader-substrate.md §5.3](autonomous-trader-substrate.md#53-reconciliation-reports)),
   satisfying the VISION promise that capability never outruns accountability:
   nothing the boundary does is unrecordable, unscoreable, or unreplayable.

6. **Leakage minimization at the boundary.** The privacy/leakage controls in
   [autonomous-trader-substrate.md §2.3](autonomous-trader-substrate.md#23-privacy-and-leakage-model)
   extend to the boundary: venue requests carry only the minimal identifiers
   the venue requires; logs never dump credentials, raw venue payloads, or
   order secrets (the [`security.md` §5](security.md#5-secret-pattern-scanning-and-log-redaction)
   log redactor and write-time secret scan continue to apply to anything that
   crosses back into the journal).

## 5. The agent proposes; the boundary holds authority

This is the load-bearing invariant for the prompt-injection attacker, and it
is worth stating on its own because it is the single line that keeps an LLM's
free-text reasoning from becoming an authorization:

- The agent's output is a **proposed intent** (a forecast and a desired
  action), recorded append-only. It is *never* a credential, a venue grant, or
  an order-routing authority.
- The **deterministic policy** — owner-set caps, allowlist, exposure limits,
  kill switch — bounds that intent. The policy is code with signed config
  (§4), not the agent's prose.
- Therefore market/source text that an attacker injects can, at most,
  influence the agent's *recorded forecast*. It cannot raise a cap, add a
  venue, disable the kill switch, or move capital, because none of those
  authorities are reachable from the agent's text — only from owner-signed
  config and the boundary's deterministic gate.

This mirrors the human-role invariant in
[`VISION.md`](../../VISION.md#north-star): "set the bounds, review the audits,
adjust the limits. Never pick the trades." The agent picks trades only
*within* bounds it cannot widen; the human (and the deterministic policy that
encodes the human's bounds) holds the authority.

## 6. Coherence with the credential-blind core invariant

Nothing in this addendum adds a credential to the journal core. The new
assets (§2) are boundary-only; the core continues to see only intents and the
append-only audit of what the boundary did. The mechanical credential ban
([`security.md` §6](security.md#6-credential-ban)) — no credential-shaped
schema column, tool argument, or tool description — remains true *after* Phase
3 ships, because the credentials never enter the core's schema. If a future
implementation bead were to add a credential field to a journal tool, that is
a regression this addendum forbids and `tests/security/` already catches.

## 7. What this addendum does NOT do

- It does not implement execution, hold a credential, call a venue, or move
  funds. It is a design-only threat model.
- It does not authorize Phase 3. Turning execution on requires the separate
  human sign-off in
  [`execution-design-review-gate.md`](execution-design-review-gate.md), which
  consumes this document as a required input and fails closed if it is missing
  or stale.
- It does not set the numeric bounds (caps, exposure limits, thresholds);
  those are owner decisions recorded in the cap/exposure beads and
  [`phase-gates.md`](phase-gates.md).
- It does not relax any shipped `security.md` invariant; it extends the model
  to a surface that does not yet exist.

## 8. Open questions (owner decisions)

The recommendations below are the author's defaults, flagged for the owner;
they are not decisions.

1. **Where venue credentials physically live.** Recommended: an **external
   signer process** the boundary calls but never reads (smallest
   exfiltratable surface), falling back to an OS keyring; an HSM/hardware
   signer where the venue and capital scale justify it. Plain environment
   variables are the weakest option and should be the floor, not the target.
   Open: which of these is mandated for SO-2 (live capital)?
2. **Prompt-injection defense posture.** Recommended: market/source text may
   influence *only* the agent's recorded forecast, which the deterministic
   policy then bounds (§5); it may **never** influence sizing, the allowlist,
   caps, or the kill switch directly. Open: is any narrower exception (e.g.
   text-driven *abstention*) acceptable, or is the agent's text strictly
   advisory to a forecast?
3. **Maximum blast radius.** Recommended hard requirement: a single
   compromised credential or a hijacked boundary process **cannot exceed the
   staged capital cap and the per-market/per-event exposure limits** (§4), and
   the staged schedule never auto-raises. Open: should there additionally be a
   per-session or per-day loss circuit-breaker independent of the position
   caps?
4. **Transport integrity for venue calls.** Recommended: authenticated,
   integrity-checked transport with response reconciliation against
   independent account snapshots (§3, venue-spoofing row). Open: is certificate
   pinning per venue required, or is standard TLS plus reconciliation
   sufficient?
