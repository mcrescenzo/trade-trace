# Autonomous trader substrate contract

> Status: **contract precursor** for planned non-custodial Trade Trace additions. This is not a shipped capability claim. It defines the buildable local substrate Trade Trace may own for paper trading, execution intents, risk checks, imports, reconciliation, audit, replay, and due-work reports.

This document covers only planned Trade Trace-owned substrate additions. External broker, order-signing, custody, scheduler, scanner, and executor systems are out of scope except as sources of sanitized read-only/imported facts.

Companion docs: [PRD.md](../PRD.md), [AGENT_GUIDE.md](../AGENT_GUIDE.md), [contracts.md](contracts.md), [memory-layer.md](memory-layer.md), [reports.md](reports.md), [current-exposure-agent-contract.md](current-exposure-agent-contract.md), [risk-units.md](risk-units.md), [replay-case-bundles.md](replay-case-bundles.md), and [opportunity-analysis.md](opportunity-analysis.md).

## 1. Product boundary and enforcement contract

Trade Trace is a local AI-only journal, memory, calibration, risk, and audit substrate. For autonomous-trader support it may store proposed actions, deterministic checks, sanitized imported facts, paper fills, reconciliation outputs, and review/replay bundles. It must remain credential-blind and non-executing.

Hard invariants:

- Trade Trace never stores private keys, seed phrases, API secrets, passphrases, signing material, relayer credentials, or execution credentials.
- Trade Trace never signs, places, replaces, cancels, redeems, settles, deposits, withdraws, approves token allowances, moves funds, or operates as custodian.
- Trade Trace never emits directional trading advice such as explicit buy/sell/execute-now recommendations. It may report policy status, recorded evidence, exposure projections, due work, and reconciliation caveats.
- Trade Trace exposes reports and append-only records; any scheduler, market scanner, credentialed adapter, live executor, halt/cancel mechanism, operator UI, or compliance/legal decision stays outside this product.

Mechanical enforcement criteria for future implementation:

- CLI/MCP schemas must reject secret-looking credential fields and must not include executor verbs (`place`, `cancel`, `sign`, `withdraw`, `deposit`, `approve`) as Trade Trace-owned actions.
- Tests must scan tool descriptions, examples, logs, exports, replay bundles, and adapter request/response fixtures for forbidden credential fields and execution claims.
- Imported payloads must be redacted or content-addressed before storage; raw private venue responses may only be referenced by a sanitized local artifact hash/path if explicitly supported.
- Reports must label external account truth as imported evidence with provenance, never as a fact Trade Trace fetched with credentials.
- The code-backed contract registry in `src/trade_trace/contracts/autonomous_substrate.py` is the canonical gate for shared autonomous record families, common provenance fields, redaction field classes, event-type/idempotency expectations, and migration-registry expectations. Downstream feature beads must extend concrete schemas against that registry rather than inventing per-feature field semantics.

Short rule:

> Trade Trace records, checks, reconciles, scores, audits, and queues review work. External systems research, schedule, authenticate, sign, submit, cancel, move funds, and fetch private venue state.

## 2. Shared record semantics

All planned substrate records below share these requirements unless a narrower contract says otherwise.

### 2.1 Append-only rows and derived projections

- Intents, risk checks, approvals/waivers, imported execution events, account snapshots, reconciliation results, audit bundles, replay cases, paper fills, and reviews are append-only records.
- State is derived from lifecycle/event rows. Do not mutate an intent from `pending` to `approved` to `filled`; append the approval, import, reconciliation, and review events that produce that lifecycle view.
- Corrections are append-only. A correction cites the superseded record ID, reason code, actor/importer, and replacement/corrected values. Projections must ignore or caveat superseded facts deterministically.
- Idempotency keys are mandatory for imports and recommended for all writes. Replaying the same import or paper fixture must not double-count exposure, fills, P&L, or violations.

### 2.2 Provenance and as-of fields

Every risk check, market/quote/book snapshot, account import, execution-event import, reconciliation result, audit bundle, and replay case must carry provenance sufficient for deterministic reconstruction:

- `source_id` / `source_ref` and `source_kind`;
- `captured_at` for when the source fact was observed by its originator;
- `effective_at` or `as_of` for the time the fact claims to represent;
- `retrieved_at` / `imported_at` for when Trade Trace received it;
- `schema_version` and adapter/importer version where applicable;
- `confidence` and `staleness` or a deterministic freshness bucket;
- `source_precedence` when multiple projections can answer the same question;
- content hash and optional redacted artifact reference when raw payload retention is allowed.

If fields disagree, reports must show the precedence and caveat instead of silently selecting a truth. Existing current-exposure precedence still applies: append-only `position_events`/`positions` projections outrank decision-only activity, while imported account truth is separately labeled and reconciled rather than treated as Trade Trace-native proof.

### 2.3 Privacy and leakage model

Autonomous-trader records can leak strategy, position, market, and account information even without secrets. Implementations must minimize leakage across CLI output, MCP responses, logs, exports, audit bundles, replay bundles, and adapter calls.

Required controls:

- default summaries should avoid unnecessary full position, account, or strategy detail;
- bundle/export commands must support redaction profiles for account labels, public addresses, strategy IDs, notes, source text, and external order IDs;
- replay cases must separate candidate-visible inputs from evaluator-only labels/outcomes;
- adapter requests must include only the minimal public/read-only identifiers needed for the configured adapter task;
- logs must not dump private raw payloads, prompts containing hidden strategy context, or unredacted bundle contents by default;
- anti-leakage fixtures must verify that evaluator-only outcomes, private account facts, and raw imported payloads are absent from candidate-visible replay inputs.

## 3. Execution lifecycle contract

Trade Trace-owned lifecycle views are derived from append-only rows in this order:

```text
execution intent
  -> pre-trade risk check
  -> approval or waiver
  -> external event imports / paper fill events
  -> account snapshot imports
  -> reconciliation
  -> review, outcome, scoring, and replay bundle
```

The lifecycle is a local audit trail, not an execution workflow engine. A future report may show an intent as "blocked", "waiver-required", "approved", "externally-submitted", "partially-filled", "filled", "rejected", "orphan-external", "mismatched", or "ready-for-review", but those labels are derived from append-only evidence.

### 3.1 Versioned risk policies and pre-trade checks

Risk policy and pre-trade checks must be implemented before or alongside execution intents so every intent can be evaluated against a deterministic policy contract.

A risk policy is immutable once referenced. Changes create a new `policy_version`. Policies are data, not prose, and may include limits for notional, market/event/category/strategy exposure, total exposure, daily/weekly loss, open orders, liquidity, spread, slippage, time-to-resolution, allowed/blocked categories, ambiguity/dispute constraints, required evidence, required forecast/thesis/decision links, approval threshold, and paper-only/close-only modes.

A pre-trade check record must include:

- `check_id`, `intent_id` or proposed-intent hash, `policy_id`, `policy_version`;
- `checked_at`, `as_of`, actor/importer, environment, and account label if applicable;
- input snapshot IDs for local journal projection, market/quote/book data, imported account state, current exposure, open orders, and source/evidence packet;
- per-rule results with deterministic `reason_code`, observed value, limit/threshold, contributing record IDs, and severity;
- aggregate status: `pass`, `warn`, `fail`, or `missing_data`;
- waiver requirement: none, warning-waivable, hard-block/non-waivable, or requires explicit operator approval;
- staleness/confidence caveats for every external or derived input.

`missing_data` is not a soft pass. Reports must distinguish missing account truth, stale market data, stale exposure projections, unavailable liquidity/depth, and absent source/forecast/thesis links with stable reason codes.

#### Deterministic evaluator (shipped — trade-trace-g629)

The "evaluate" half of this contract is implemented as a pure, credential-blind,
non-executing evaluator in `src/trade_trace/tools/risk.py`
(`evaluate_risk_policy`), surfaced as the **read-only** tool `risk.evaluate`. It
takes a proposed `pretrade_intent` (by `proposed_intent_id` or an inline
`proposed_intent`) plus a `risk_policy_version` row and caller-supplied input
`snapshots` (exposure projection, market/quote/book, imported account state),
and RETURNS per-rule results plus an aggregate `pass`/`warn`/`fail`/`missing_data`
status with the matching receipt `outcome`. It writes no rows and never blocks,
signs, places, or routes an order; its verdict drops straight into
`risk.check_record` so a recorded receipt is no longer a hand-crafted,
caller-trusted verdict.

Policy `rules_json` entries are data, not prose. Each rule carries a
`limit_class`, a `severity` (`warning` or `hard_block`), a `threshold`, and an
optional `waiver` class. Covered §3.1 limit classes: `notional`,
`market_exposure`, `category_exposure`, `total_exposure`, `daily_loss`,
`weekly_loss`, `spread`, `slippage`, `time_to_resolution` (a minimum-runway
check), `allowed_categories`, `blocked_categories`, `required_links` (required
forecast/thesis/decision links), `approval_threshold`, `paper_only`, and
`close_only`. Reason codes are stable: `within_limit`, `limit_exceeded`,
`category_blocked`, `category_not_allowed`, `required_link_missing`,
`approval_threshold_exceeded`, `paper_only_violation`, `close_only_violation`,
`missing_input_data`, `stale_input_data`, `unknown_limit_class`,
`malformed_rule`.

The aggregate is a deterministic fold over per-rule severities
(`hard_block` > `missing_data` > `warning` > `info`). `missing_data` is never a
soft pass: a rule the evaluator cannot apply (missing input, malformed rule, or
an `unknown_limit_class` the evaluator refuses to guess at) raises the aggregate
to at least `missing_data`, and a `hard_block` violation still outranks
`missing_data`.

### 3.2 Execution intents

An execution intent is an immutable local pre-trade ticket. It is not an order and carries no authority to execute.

Minimal intent fields:

- linked `market_id`, `instrument_id`, `forecast_id`, `decision_id`, `thesis_id`, strategy/playbook version, and source/evidence IDs where available;
- venue and public venue market/instrument identifiers;
- side, intended size/notional, limit/worst acceptable price, max slippage, and intended order semantics as non-executing metadata;
- intended account label, environment (`paper`, `supervised_live`, etc.), capital/strategy bucket, and executor label if intentionally recorded;
- expected-value inputs supplied by the caller and max-loss assumption;
- required `policy_version` and pre-trade-check reference when the check has been run;
- idempotency key, creator/actor, `created_at`, and provenance fields.

Useful invariant for external executors:

> A live executor may choose to require a matching Trade Trace intent and passing/waived pre-trade check before it acts, but Trade Trace only records and reports that evidence.

### 3.3 Approval and waiver records

Approvals and waivers are append-only lifecycle records linked to an intent and risk-check result.

Required fields:

- approving actor or approval mode (`human`, `supervisor_agent`, `policy_auto_warning`, etc.);
- approved/waived rule IDs and reason codes;
- waiver class: warning waiver, missing-data waiver, or hard-block override attempt;
- explicit boundary for self-waiver: which warning classes can be self-waived and which require independent approval;
- expiry (`expires_at`, max notional/size, account/environment scope, and policy version scope);
- whether the waiver permits paper-only, supervised-live, or no execution;
- violation-report reference when an execution/import later contradicts the approval boundary.

Hard-block rules must not be silently waived. If an override record is allowed for audit completeness, reports must label it as a violation or non-compliant override unless the policy explicitly permits that override class.

## 4. Paper trading contract

Paper trading is a first-class local simulation ledger and the safest bridge from research to any external live process.

Paper events are append-only and should reuse the same intent, risk-check, approval/waiver, reconciliation, audit, and replay contracts where possible. A paper account/environment must be explicit so reports never confuse paper exposure with imported/live account truth.

Conservative fill model requirements:

- each simulated fill cites quote/book/market snapshot IDs used for fillability;
- fillability must account for side, limit price, spread, liquidity/depth coverage, timestamp freshness, and market tradability metadata;
- slippage model, fee assumptions, partial-fill rules, and remaining quantity must be recorded;
- if book depth is missing/stale or insufficient, the event must be `missing_data`, `unfilled`, or partially filled according to deterministic rules rather than optimistically filled;
- paper P&L and exposure reports must carry mark-price source, mark `as_of`, confidence/staleness, and source precedence.

Acceptance fixtures must include full fill, partial fill, no fill due to price, no fill due to missing/stale depth, slippage cap exceeded, and duplicate paper fill import/idempotency.

## 5. Imports, reconciliation, and projections

### 5.1 Execution-event imports

Trade Trace may import sanitized execution facts produced by an external executor or reconciler. Supported imported facts include submission/acceptance/rejection, partial/full fills, expiration, replacement/correction, fees, settlement/redemption facts, and executor/venue failure facts. These are records of what another system says happened.

Import validation requirements:

- validate schema version, required provenance fields, idempotency key, account/environment label, venue identifiers, event type, quantities/prices, and event timestamps;
- reject or quarantine malformed, secret-bearing, impossible, duplicate-conflicting, or policy-inconsistent payloads rather than folding them into projections;
- detect duplicate fills and external order IDs deterministically;
- allow append-only corrections that cite the original import and explain the correction reason;
- represent orphan external orders/fills explicitly when no matching Trade Trace intent exists.

### 5.2 Account snapshots

Trade Trace may import externally fetched account snapshots after credentials and private transport have been handled elsewhere. Snapshot imports may include sanitized balances, available/committed collateral, open orders, positions, fills/trades, unsettled claims, public allowance/approval facts, venue timestamps, account label, and environment.

Account projections and reports must carry source precedence, confidence, and staleness semantics. If local projection and imported account truth disagree, reconciliation reports must identify the mismatch rather than rewriting local history.

### 5.3 Reconciliation reports

Reconciliation compares Trade Trace's local projection against imported execution/account facts as of a specified time. It must report:

- intent with no imported external event;
- external order/fill with no matching intent;
- duplicate fill import;
- rejected order after approved intent;
- partial-fill and remaining-size mismatch;
- local-vs-imported position, price, fee, balance, or exposure mismatch;
- stale imported snapshot;
- ambiguous resolution or insufficient data to choose a projection;
- unreviewed policy violation or waiver-boundary breach.

The mismatch-code set a reconciliation record reports is **deterministically derived** from append-only local + imported rows and must be byte-reproducible for a given `as_of`. Caller-supplied mismatch codes are never unioned into that derived set; they are recorded on a distinct `manually_flagged` operator-annotation channel (surfaced alongside, but separate from, the derived `mismatch_codes`) so the derived set stays reproducible and a caller can never silently mutate or escalate the derivation (including `diff_severity`, which is derived from the derived set alone). Downstream cleanliness gates (`reconciliation_cleanliness`) treat a record as an open critical breach when its derived severity/codes are critical **or** it carries an operator-flagged critical code, so operator-flagged breaches still gate.

The output is evidence for an external operator/executor. Trade Trace does not cancel, halt, or remediate external orders.

## 6. Audit bundles, replay cases, and due work

### 6.1 Audit bundles

Audit bundles must be reproducible from append-only records and must include provenance/as-of metadata for every component: market metadata, source/evidence packet, thesis, forecast, decision, strategy/playbook version, risk policy/check, intent, approval/waiver, paper/imported execution events, account snapshots, reconciliation result, outcome/resolution, score, P&L, reflection, and playbook updates.

Bundles must support redaction profiles and must never include secrets or unredacted private payloads by default.

### 6.2 Replay and evaluation cases

Replay cases convert historical paper/live decisions into deterministic evaluation artifacts. They must follow strict `as_of` semantics: candidate-visible inputs include only information available at the case `as_of`; evaluator-only labels include later outcome, score, P&L, reconciliation result, and reflections.

Replay case records must include case source IDs, `as_of`, task mode, contract/schema version, source precedence, snapshot IDs, redaction profile, candidate-visible artifact hash, evaluator-only artifact hash, and anti-leakage check result.

### 6.3 Due/work-queue reports

Trade Trace may expose due work through existing report patterns such as lifecycle/bootstrap/work-queue reports. Queue items are derived obligations, not scheduler state. Useful derived items include stale account snapshot, intent awaiting risk check, check requiring approval/waiver, intent with no matching import, import awaiting reconciliation, discrepancy requiring operator review, unresolved outcome, overdue reflection, and stale replay/audit bundle.

## 7. Public/read-only Polymarket metadata adapter scope

Credential-free Polymarket metadata support is allowed only as opt-in adapter normalization that improves local journal/report fidelity. It is disabled by default and must not run as a background scheduler or daemon.

Allowed public/read-only metadata may include configured market refresh, public snapshot/order-book data, spread/depth normalization, token IDs, tick-size/tradability metadata, negative-risk metadata, public outcome data, public price history, and intentionally supplied public-address position metadata.

Adapter constraints:

- no secrets, authentication, signing, order placement, cancellation, custody, or private account payloads;
- no private strategy/position payload leakage in adapter requests;
- explicit user/config opt-in per adapter/source;
- provenance and as-of fields on every stored snapshot;
- deterministic staleness/confidence reporting when used by risk checks, paper fills, or audit/replay bundles.

## 8. Implementation order

1. **Shared substrate contracts:** append-only lifecycle/event rows, idempotency, provenance/as-of fields, redaction conventions, and schema gates.
2. **Versioned risk policy and pre-trade checks:** deterministic policy data, rule results, reason codes, stale/missing-data handling, and waiver requirements. The deterministic evaluator (`risk.evaluate` / `evaluate_risk_policy`) is shipped (trade-trace-g629); see §3.1 "Deterministic evaluator".
3. **Execution intents and approval/waiver records:** immutable intent rows plus lifecycle views derived from checks and approvals.
4. **Paper trading ledger:** conservative fill model, paper positions/P&L/exposure, and paper reconciliation fixtures.
5. **Execution-event and account-snapshot imports:** validation, quarantine, corrections, source precedence, confidence, and staleness.
6. **Reconciliation reports:** local projection vs imported truth with stable mismatch/caveat codes.
7. **Audit bundles and replay cases:** strict as-of reconstruction, candidate-visible/evaluator-only split, redaction, and anti-leakage gates.
8. **Due-work reports and opt-in public metadata adapters:** derived obligations and credential-free metadata normalization only where they improve journal/report quality.

## 9. Deterministic acceptance gates

Future work is not complete until fixtures and tests cover at least:

- paper full fill, partial fill, no fill, stale/missing book, slippage cap, and duplicate paper fill idempotency;
- live-intent pre-trade pass, warning, fail, missing-data, waiver-required, warning waiver, expired waiver, and hard-block violation;
- rejected external order, partial fill, duplicate fill, orphan external order/fill, stale account snapshot, and imported correction — the external execution-receipt import cluster (`external_receipt.import/get/list/report`) is shipped and public (trade-trace-g776); each receipt is sanitized, append-only, credential-blind imported evidence (never TT-fetched), and malformed/secret-bearing/credential-shaped/impossible payloads are quarantined at the import boundary. Gates: `tests/integration/test_external_receipts.py` (boundary quarantine, secret/credential rejection, imported-correction labelling) and `tests/integration/test_reconciliation_records.py` §9 gates (`test_recon_gate_rejected_external_order_for_approved_intent`, `test_recon_gate_orphan_external_order_no_intent`, `test_recon_gate_mismatch_orphan_and_duplicate`, `test_recon_gate_partial_fill_remaining_mismatch`, `test_recon_gate_imported_correction_is_consumed_not_orphaned`) pin that `reconciliation._build_derived` consumes these rows into `REJECTED_APPROVED_INTENT` / `ORPHAN_EXTERNAL_ORDER` / `ORPHAN_EXTERNAL_FILL` / `DUPLICATE_FILL` / `PARTIAL_FILL_REMAINING_MISMATCH`;
- reconciliation match, mismatch, ambiguous resolution, stale source precedence, and local projection vs imported account-truth disagreement — the account-snapshot import cluster (`account_snapshot.import/get/list/report`) is shipped and public (trade-trace-qfn8); each snapshot is sanitized, append-only, credential-blind imported evidence (never TT-fetched), labelled `record_kind=sanitized_imported_account_snapshot` with provenance and source-precedence/confidence/staleness semantics, and malformed/secret-bearing/credential-shaped/impossible (negative, available>total) payloads are quarantined at the import boundary. Gates: `tests/integration/test_account_snapshots.py` (boundary quarantine, secret/credential rejection, imported-evidence-with-provenance labelling, freeze-state regression) and `tests/integration/test_reconciliation_records.py` §9 gates (`test_recon_gate_stale_source_precedence`, `test_recon_gate_local_vs_imported_position_disagreement`, `test_recon_gate_local_vs_imported_balance_disagreement`, `test_recon_gate_missing_snapshot_derives_balance_and_position_mismatch`) pin that `reconciliation._latest_snapshot` reads these rows by source-precedence ordering and `_build_derived` consumes them into `STALE_SNAPSHOT` / `POSITION_MISMATCH` / `BALANCE_MISMATCH`;
- audit bundle redaction and replay anti-leakage, including evaluator-only labels hidden from candidate-visible inputs;
- schema/log/export scans proving no credentials, private payloads, execution verbs, or Trade Trace-owned order actions leak into the public surface;
- opt-in Polymarket metadata disabled by default, no scheduler behavior, no secrets, no private payload leakage, and correct provenance/staleness fields when enabled.

## 10. Summary

The planned autonomous-trader substrate is a non-custodial local control ledger. Trade Trace may own paper trading, execution intents, risk-policy checks, approval/waiver records, sanitized imports, reconciliation, audit/replay bundles, due-work reports, and opt-in public metadata normalization. It must not become a bot, broker, signer, custodian, scheduler, advice engine, or private account fetcher.
