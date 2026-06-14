# Credential-blind isolation contract (core vs. execution boundary)

> Status: **design — not implemented** (trade-trace-2ki5). This document
> defines the *exact* credential-isolation boundary between the
> credential-blind journal/memory **core** (everything shipped today) and the
> future Phase-3 **execution module** that may hold venue credentials. No
> execution code, credential field, venue call, or order authority ships with
> this doc — the substrate today holds **zero** credentials and routes **zero**
> orders. This is the durable contract the future boundary MUST satisfy, stated
> as testable assertions, not prose. It sits under EPIC trade-trace-u1gv
> (Phase-3 Execution Safety Design) and is consumed as a required input by the
> [execution design-review / sign-off gate](execution-design-review-gate.md#3-required-design-artifact-inputs).

Source bead: trade-trace-2ki5. Parent epic: trade-trace-u1gv.

Companion docs:
[`security.md`](security.md) (the shipped credential-blind threat model and the
mechanical credential ban this contract scopes),
[`security-execution.md`](security-execution.md) (the Phase-3 credential-handling
threat model — the *attacker/asset* view of the same boundary this doc draws),
[`autonomous-trader-substrate.md`](autonomous-trader-substrate.md) (§1 hard
invariants),
[`execution-safety-contracts.md`](execution-safety-contracts.md) (venue
allowlist / caps / exposure / kill switch — *what an order may do* once it
crosses the boundary),
[`execution-design-review-gate.md`](execution-design-review-gate.md) (the human
sign-off that consumes this contract),
[`VISION.md`](../../VISION.md) ("What never changes" → *Credential discipline*).

## 1. The invariant this contract pins

[`VISION.md` "What never changes"](../../VISION.md#what-never-changes) promises:
*"The journal and memory core stays credential-blind forever. Execution, when it
comes, lives behind its own isolated safety boundary with its own design
review."* [`autonomous-trader-substrate.md` §1](autonomous-trader-substrate.md#1-product-boundary-and-enforcement-contract)
states the hard invariant: *"Trade Trace never stores private keys, seed
phrases, API secrets, passphrases, signing material, relayer credentials, or
execution credentials."* Today that ban is **product-wide** and is verified
mechanically by [`security.md` §6](security.md#6-credential-ban) /
`tests/security/test_no_credentials.py`.

Phase 3 introduces a component that legitimately *does* hold venue credentials
(see [`security-execution.md` §2](security-execution.md#2-phase-3-assets)). The
moment that component exists, "credential-blind" can no longer mean "no
credential anywhere in this product" without contradiction — it must mean **the
journal/memory core is credential-blind, and the execution module is the only
holder of credentials.** This document draws that line precisely so the existing
ban is *preserved for the core* rather than silently relaxed.

The boundary is a single asymmetric membrane:

- **Core → boundary:** the core hands the boundary a *proposed intent* (a
  forecast + a desired action) and the deterministic, owner-set policy config.
  Never a credential.
- **Boundary → core:** the boundary hands the core an *append-only audit* of
  what it did (proposed / bounded / submitted / filled / rejected / halted /
  flattened). Never a credential, never signing material, never a raw venue
  payload.

Everything below is defense in depth around that one membrane.

## 2. The owner decision, resolved: re-scope the ban to "core only" in THIS repo

The open question the bead poses is: does the product-wide credential ban
(`test_no_credentials.py` scanning **all** schema/tools) get **re-scoped to
"core only"**, or does the execution module live in a **fully separate
repo/distribution** so the ban can stay product-wide for *this* repo?

**Resolved (author recommendation, flagged for owner sign-off at the
[design-review gate](execution-design-review-gate.md#2-scope-two-sign-offs-not-one)):
the execution module is a SEPARATE distribution, AND the ban in this repo is
restated as "core only" in scope language — both, not either/or.** Concretely:

- **R1 — Separate distribution.** The Phase-3 execution module is a distinct
  package / distribution that this repository does **not** import, vendor, or
  depend on. This repository — the journal/memory core — never gains a code
  path that holds a credential. Consequently `test_no_credentials.py` continues
  to scan the **entire** schema and tool surface *of this repo* and continues to
  pass unchanged, because this repo *is* the core. The execution module carries
  its own, separate credential-handling tests in its own distribution; they are
  out of scope for this repo.
- **R2 — "Core only" stated in scope language, enforced as belt-and-suspenders.**
  Even though R1 means this repo never holds a credential, this contract makes
  the *scope intent* explicit and adds a **complementary** assertion (§6) that
  credentials never reach the core's **export and bundle** surfaces — surfaces
  `test_no_credentials.py` historically under-covers (it scans schema/tool
  shape and `journal.status`, not the JSONL outbox or `review.bundle` /
  `replay.case_bundle` outputs). This guards the *output* edge of the membrane
  even if a future feature bead were to widen the core.

**Why both.** R1 is the strong guarantee (the core simply has no credential code
to leak). R2 is the cheap, durable proof that survives a future refactor: if
some later bead in *this* repo ever added a credential-shaped field, R1's "this
repo is the core" assumption would be the thing that broke, and R2's export/bundle
scan plus the existing schema/tool scan would catch it. The two are layered: R1
removes the credential from the repo; R2 proves the core's outputs stay clean
regardless.

This resolution means **Phase-3 work does not touch this repo's credential-test
surface to *relax* it** — the ban stays maximally strict here. The boundary is
expressed as "the execution module lives elsewhere," not as "this repo now
tolerates a credential column behind a flag."

## 3. What is core (under the ban, forever) vs. what is boundary

### 3.1 Core surface — credential-blind, unchanged

The **core** is everything in this repository: the journal/memory substrate, its
SQLite schema, its JSONL export outbox, its `review.bundle` / `replay.case_bundle`
outputs, and every tool in `default_registry()`. The core is exactly the surface
`tests/security/test_no_credentials.py` audits today. It remains under the full
[`security.md` §6](security.md#6-credential-ban) ban:

- No DB column name matches `wallet|broker|seed|signing|private_key|api_key`
  (existing assertion).
- No tool argument schema includes a credential-shaped field name (existing
  assertion).
- No `tool.description` mentions credential words (existing assertion).
- Every write tool **silently drops** any of the 20 canonical credential keys
  in `PROJECT_CREDENTIAL_KEYS`
  (`src/trade_trace/security/credential_keys.py`) — both as flat args and nested
  in `metadata_json` (existing assertions).

### 3.2 Boundary surface — credential-holding, separate distribution

The **boundary** is the Phase-3 execution module (a separate distribution per
§2/R1). It — and only it — may hold the assets enumerated in
[`security-execution.md` §2](security-execution.md#2-phase-3-assets): venue API
keys, signing material / private keys, session/auth tokens, live order
authority, and the deterministic policy config. None of these is a column, tool
argument, or tool description in this repository.

### 3.3 The dividing line, stated as a rule

> A datum belongs to the **boundary** (and is forbidden in the core) if and only
> if it is a credential, signing material, an auth/session secret, or a **raw
> venue request/response payload**. Everything the core records about execution
> is the *sanitized, append-only audit* of what the boundary did — intents,
> bounded decisions, fills-as-imported-evidence, reconciliation results — never
> the secret that authorized it nor the raw bytes that carried it.

This is consistent with the already-shipped import discipline: external
execution receipts and account snapshots are *"sanitized, append-only,
credential-blind imported evidence (never TT-fetched)"* and *"malformed /
secret-bearing / credential-shaped / impossible payloads are quarantined at the
import boundary"* ([`autonomous-trader-substrate.md` §5](autonomous-trader-substrate.md#5-imports-reconciliation-and-projections)).
The credential-blind core already refuses raw private venue payloads at its
import edge; this contract states that the *same* refusal governs the new
boundary→core direction.

## 4. No credential, signing material, or raw venue payload crosses back into core

This is the load-bearing back-flow rule. The boundary→core direction (§1) is the
*only* place a Phase-3 credential could leak into the credential-blind core, so
it is gated by an explicit allowlist of what may cross:

**Permitted to cross boundary → core** (all already credential-free record
families the core understands today):

- The proposed/bounded **intent** lifecycle events
  ([`autonomous-trader-substrate.md` §3.2](autonomous-trader-substrate.md#32-execution-intents)).
- Sanitized **execution-receipt / fill** evidence and **account snapshots**,
  imported through the existing quarantining import boundary (§3.3).
- **Order-decision audit events** (proposed / bounded / submitted / rejected /
  halted / flattened) — the kind, side, size, venue *identifier*, policy
  `policy_version`, reject reason code, and idempotency key, all of which are
  already credential-free metadata classes.

**Forbidden to cross boundary → core, without exception:**

- Any credential key in `PROJECT_CREDENTIAL_KEYS`, any signing material, any
  private key, any session/auth/bearer token, any passphrase or seed.
- Any **raw venue request or response body** — only a *sanitized*,
  content-addressed reference (hash/path) to such a payload may be recorded, per
  the existing import rule, and even that reference is scrubbed of secrets (§5).
- Any field whose name or value would trip the schema/tool credential ban (§3.1)
  or the write-time secret scan (§5).

A boundary that needs to record *that* a credentialed call happened records the
**sanitized fact** (venue id, timestamp, idempotency key, outcome code), never
the credential or the raw bytes that made the call.

## 5. The write-time secret scan and bundle redaction extend to the boundary

The two existing scrubbing layers already cover every byte that crosses
boundary → core, because that data enters the core through the *same* write and
export/bundle paths every other record uses. This contract states that coverage
explicitly so a future implementer cannot route boundary data around it:

- **Write-time secret scan** ([`security.md` §5 layer 1](security.md#5-secret-pattern-scanning-and-log-redaction)
  / [§6.5 free-text scan policy](security.md#65-free-text-scan-policy-bead-trade-trace-7j1l)).
  Every long-form free-text field a boundary-originated event writes into the
  core (any `reason`, `note`, `*_text`, or `metadata_json` blob) is scanned by
  `reject_if_contains_secrets` before insert. A credential-shaped value (e.g. an
  `sk-…` key, an `0x…`-prefixed signing material, a JWT) accidentally embedded
  in a boundary audit string is **rejected at write time** — it never reaches a
  core row. Any new persisted free-text column a Phase-3 event introduces in the
  core MUST follow the §6.5 rule (scanned, or explicitly listed exempt, with a
  corresponding `test_secret_pattern_writes.py` case).
- **Log redaction** ([`security.md` §5 layer 2](security.md#5-secret-pattern-scanning-and-log-redaction)).
  `redact_for_log()` continues to scrub secret-shaped substrings from every log
  line, including any line a boundary-originated event produces, exactly as
  [`security-execution.md` §4 control 6](security-execution.md#4-controls)
  requires (*"logs never dump credentials, raw venue payloads, or order
  secrets"*).
- **Bundle redaction** ([`security.md` §8](security.md#8-redaction-of-reviewbundle-contract-impl-is-p1)
  / [reports.md §5.3]). `review.bundle` and `replay.case_bundle` already run a
  final secret-pattern scrub over outgoing strings and unconditionally omit
  `redaction_status = 'sensitive'` rows. Because boundary-originated audit
  events are ordinary core rows, they pass through this same redaction; no
  bundle export path may emit a credential or a raw venue payload. The
  security-gate budget keys remain non-caller-overridable
  ([`security.md` §6.5](security.md#65-free-text-scan-policy-bead-trade-trace-7j1l)).
- **Export-time warning** ([`security.md` §5 layer 3](security.md#5-secret-pattern-scanning-and-log-redaction)).
  `drain_outbox` continues to warn on secret-shaped bytes in the JSONL outbox so
  an operator is alerted before sharing.

The point: there is **no new scrubbing machinery** to build for the boundary.
The boundary inherits the core's existing three-layer scan because it writes
through the core's existing write/export/bundle paths — and this contract
forbids any path that bypasses them.

## 6. Testable assertions (the invariant, not prose)

The invariant is stated as assertions a test enforces today, plus assertions a
future Phase-3 implementation in a separate distribution must carry. Each
core-scoped assertion below is already pinned, or is newly pinned by
`tests/security/test_no_credentials.py` (the complementary export/bundle scan
this bead adds).

**Core-scoped (enforced in THIS repo, must stay green):**

- **A1 — No credential-shaped schema column.** No DB column matches
  `wallet|broker|seed|signing|private_key|api_key`.
  *Pinned by* `test_no_credentials.py::test_no_table_column_resembles_credential`.
- **A2 — No credential-shaped tool argument or description.** No registered
  tool's argument schema names a `PROJECT_CREDENTIAL_KEYS` member; no tool
  description mentions credential words.
  *Pinned by* `test_no_tool_description_mentions_credentials` and the boundary
  audit in `test_mvp_boundary_audit.py`.
- **A3 — Write tools silently drop credential args (flat + nested).** Every
  credential key is dropped from flat args and rejected when nested in
  `metadata_json`.
  *Pinned by* the `test_*_silently_drops_credential_args` /
  `test_metadata_json_rejects_*` cases.
- **A4 — No credential reaches the EXPORT surface.** A credential-shaped value
  written through any core write tool never appears in the JSONL export outbox
  (`drain_outbox`).
  *Pinned by* `test_no_credentials.py::test_no_credential_in_export_surface`
  (added by this bead).
- **A5 — No credential reaches the BUNDLE surface.** A credential-shaped value
  written through any core write tool never appears in a `review.bundle` or
  `replay.case_bundle` output.
  *Pinned by* `test_no_credentials.py::test_no_credential_in_bundle_surface`
  (added by this bead).
- **A6 — Read tools never surface a credential pattern.** `journal.status` (and,
  by A4/A5, exports and bundles) never serialize a string matching a credential
  value pattern.
  *Pinned by* `test_journal_status_never_carries_credentials` plus A4/A5.

**Boundary-scoped (the separate distribution's own tests must establish; out of
scope for this repo, listed so the design-review gate can verify them):**

- **B1 — The boundary is the only credential holder.** No credential, signing
  material, or session token is reachable from any core import, table, tool, or
  export. (R1: the core does not import the boundary distribution.)
- **B2 — Boundary → core writes only sanitized audit.** Every event the boundary
  emits into the core is a credential-free, secret-scanned record of §4's
  permitted set; the boundary holds no path that writes a credential or a raw
  venue payload into a core row.
- **B3 — Raw venue payloads stay behind the boundary.** Only a sanitized,
  content-addressed reference may cross; the raw request/response body never
  becomes a core row or a bundle field (§3.3 / §4).
- **B4 — Boundary logs/exports inherit core scrubbing.** Anything the boundary
  writes through the core's write/export/bundle paths passes the §5 three-layer
  scan; the boundary builds no path that bypasses it.

## 7. What this contract does NOT do

- It does not implement execution, hold a credential, call a venue, move funds,
  or create the separate execution distribution. It is a design-only contract.
- It does not authorize Phase 3. Turning execution on requires the separate
  human sign-off in
  [`execution-design-review-gate.md`](execution-design-review-gate.md), which
  consumes this contract (trade-trace-2ki5) as a required input (§3 there) and
  fails closed if it is missing or stale.
- It does not relax any shipped `security.md` invariant. It restates the
  product-wide ban as *core-scoped* and adds export/bundle coverage; it never
  adds a credential column, argument, or description to this repo.
- It does not set the venue allowlist, caps, exposure limits, or kill-switch
  behavior — those live in
  [`execution-safety-contracts.md`](execution-safety-contracts.md) and the
  cap/exposure/kill-switch beads. This contract governs *credential isolation*
  only.

## 8. Open questions (owner decisions)

The recommendations are the author's defaults, flagged for the owner; they are
not decisions.

1. **Separate distribution vs. in-repo module behind a build flag.** §2
   recommends a **fully separate distribution** (R1) so this repo never gains a
   credential code path and `test_no_credentials.py` stays maximally strict.
   Open: is the owner content to ship the execution module as an independent
   package, or does operational coupling argue for an in-repo, separately-tested
   subpackage (which would require re-scoping `test_no_credentials.py` to a core
   path allowlist — a strictly weaker guarantee this contract advises against)?
2. **Sanitized-reference policy for venue payloads.** §4 permits only a
   sanitized, content-addressed reference to a raw venue payload to cross into
   the core. Open: should *any* reference cross, or should the core record only
   the derived sanitized facts (venue id, outcome code, idempotency key) and
   keep even the hash/path entirely behind the boundary?
3. **Scope of the complementary export/bundle scan.** §6 A4/A5 scan the JSONL
   outbox and the two bundle tools with the canonical credential keys and value
   patterns. Open: should the scan additionally cover every report tool's output
   (a broader, slower sweep), or is the export + bundle pair the right
   cost/coverage point given reports derive from the same already-scanned core
   rows?
