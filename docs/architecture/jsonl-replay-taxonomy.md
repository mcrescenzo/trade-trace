# JSONL replay taxonomy for landed write surfaces

> Status: **decision document for trade-trace-dew2** (design). No code
> changes in this document; the implementation tasks are filed as
> follow-up beads.

## Problem

Trade Trace appends every retryable write to `events.payload_json` and
optionally to `outbox/*.jsonl`. The JSONL form is the canonical
on-disk audit + replay surface (`docs/architecture/imports.md` §2).
Today the importer recognizes the M0/M1 ledger event types; M3 memory,
M3 strategy, and M4 playbook events landed afterward but the importer's
replay policy for them is implicit. New contributors writing import
glue can't tell, file by file, which JSONL lines should replay through
`dispatch()`, which should reject, and which should pass through as
diagnostics.

This document defines the policy explicitly so the importer can grow
without ad-hoc per-event branches and so disaster-recovery confidence
isn't an unknown.

## Event surface (today)

The `events` table currently emits these `event_type` values
(per `src/trade_trace/events/semantic_keys.py`):

- M0/M1 ledger: `venue.created`, `market.bound`, `instrument.created`,
  `snapshot.added`, `thesis.created`, `source.added`, `source.attached`,
  `decision.created`, `outcome.recorded`, `forecast.created`,
  `forecast.scored`, `forecast.superseded`, `forecast.anchored_to_snapshot`,
  `edge.created`, `import.row_committed`.
- M3 memory: `memory_node.retained`, `memory_node.invalidated`.
- M3 strategy: `strategy.created`, `strategy.updated`.
- M4 playbook: `playbook.created`, `playbook.proposed_version`,
  `playbook_rule.followed`, `playbook_rule.overridden`.
- H05 risk audit: `risk_policy_version.created`,
  `risk_check_receipt.recorded`.
- Pre-trade intent: `pretrade_intent.recorded`.
- Abstention / no-bet: `abstention.recorded` (local "considered and passed"
  record so the calibration denominator is not survivorship-biased; a journal
  fact, not trade activity).
- Forecast independence lock: `forecast.blind_committed` and
  `forecast.independence_revealed` (immutable proof that a forecast was
  committed blind to the market price before the snapshot was revealed).
- Resolution interpretation: `forecast.resolution_interpreted` (the agent's
  reading of how a market will resolve, recorded at forecast time and later
  checked against the actual resolution source).
- Approval/waiver ledger: `approval_waiver.recorded` (local audit evidence
  only; not a live permission, order, signing, custody, or execution gate).
- External execution receipt: `external_execution_receipt.imported` (sanitized
  caller-supplied evidence only; not a fetch, signing, order, custody, or
  remediation surface).
- Account snapshot: `account_snapshot.imported` (sanitized caller-supplied
  account-state evidence only; not a fetch, private-auth, broker truth, custody,
  or remediation surface).
- Replay/evaluation artifact: `replay_evaluation_artifact.recorded` (externally
  supplied dataset/result evidence for strategy review only; not a simulator,
  backtest engine, optimizer, data fetch, advice, or recommendation surface).
- Paper fill: `paper_fill.recorded` (local paper-only conservative fill evidence;
  not imported/live account truth and not an order, execution, or custody surface).
- Reconciliation: `reconciliation.recorded` (local derived comparison of Trade
  Trace projection with imported external facts; evidence only for external
  operators, not remediation or execution).
- Signal: `signal.emitted` (lazy-emitted by `signal.scan` /
  `report.coach`).
- Market re-sync: `market.refreshed` (emitted by `market.refresh` when it
  re-syncs a bound market row from live Gamma on a cache miss; diagnostic
  venue-truth re-read, not a caller mutation).

## Taxonomy

Every event family lands in one of four buckets:

### A. Replayable through `dispatch()`

The JSONL line carries an envelope `{tool, args, _event_type, …}` that
re-issues against the same tool surface. The importer strips
underscore-prefixed transport keys and calls
`dispatch(tool, domain_args)`. Idempotency replays return the original
row.

**Members:** M0/M1 ledger + M3 memory write families:

- `venue.created` → `venue.add` (legacy replay surface; default v0.0.2
  catalog folds new market setup into `market.bind`)
- `market.bound` → `market.bind`
- `instrument.created` → `instrument.add` (legacy replay surface; default
  v0.0.2 catalog folds new instrument setup into `market.bind`)
- `snapshot.added` → `snapshot.add`
- `thesis.created` → `thesis.add`
- `source.added` → `source.add`
- `source.attached` → `source.attach_to_{thesis,decision,forecast,memory_node}`
- `decision.created` → `decision.add`
- `forecast.created` → `forecast.add`
- `forecast.superseded` → `forecast.supersede`
- `forecast.anchored_to_snapshot` → `forecast.anchor_to_snapshot`
- `outcome.recorded` → `resolution.add` (`outcome.add` remains a hidden legacy dispatch alias)
- `risk_policy_version.created` → `risk.policy_version_add`
- `risk_check_receipt.recorded` → `risk.check_record`
- `pretrade_intent.recorded` → `pretrade_intent.record` (local,
  non-executing proposed intent audit packet only).
- `abstention.recorded` → `abstention.record` (local append-only
  considered-and-passed record; idempotency is keyed by the caller-supplied or
  auto-derived key over the instrument/thesis/as_of/considered_probability, and
  replay performs no network or execution action).
- `forecast.blind_committed` → `forecast.commit_blind` and
  `forecast.independence_revealed` → `forecast.reveal_snapshot` (local
  append-only blind-commit/reveal ordering proof; idempotency is keyed over the
  forecast/snapshot, and replay performs no network or execution action).
- `forecast.resolution_interpreted` → `forecast.interpret_resolution` (local
  append-only record of the agent's resolution-criteria reading; idempotency is
  keyed over the forecast/instrument/source/as_of, and replay performs no
  network or execution action).
- `approval_waiver.recorded` → `approval.record` (local append-only approval,
  waiver, hard-block attempt, and scoped autonomy evidence only; no execution
  or live permissioning behavior is replayed).
- `external_execution_receipt.imported` → `external_receipt.import` (local
  append-only sanitized receipt evidence only; semantic idempotency is keyed by
  the caller-supplied semantic key and material hash, and replay performs no
  network or execution action).
- `account_snapshot.imported` → `account_snapshot.import` (local append-only
  sanitized account snapshot evidence only; semantic idempotency is keyed by the
  caller-supplied semantic key and material hash, and replay performs no network,
  account sync, custody, or execution action).
- `replay_evaluation_artifact.recorded` → `replay_artifact.record` (local
  append-only externally supplied replay/evaluation artifact evidence only;
  semantic idempotency is keyed by the caller-supplied semantic key and material
  hash, and replay performs no data fetch, simulation/backtest execution,
  strategy optimization, advice, recommendation, account sync, or execution
  action).
- `paper_fill.recorded` → `paper_fill.record` (local append-only paper-only
  conservative fill evidence; semantic idempotency is keyed by the caller-supplied
  semantic key and material hash, and replay performs no network, account sync,
  live order, cancellation, custody, settlement, or execution action).
- `reconciliation.recorded` → `reconciliation.record` (local append-only
  reconciliation result over imported/account/paper/projection evidence; replay
  performs no private fetch, order action, cancellation, settlement, fund
  movement, or remediation).
- `memory_node.retained` → `memory.retain` / `memory.reflect`
  (the import path is `memory.retain` for both; `memory.reflect`
  also writes the about-edge but the canonical replay surface for
  the node row is `retain`).

**Acceptance for an implementation bead:** the JSONL `{tool, args}`
envelope is sufficient input; calling `dispatch()` with the same
`idempotency_key` produces `meta.idempotent_replay=true` and no new
rows. (This already works for M0/M1; the M3 memory entry needs a
parity sweep — see follow-up below.)

### B. Replayable but as a cascade of another tool

The event is emitted **inside** another tool's transaction and has no
standalone write surface. Replay happens by replaying the parent.

**Members:**

- `edge.created`: cascaded from `thesis.add` (supersedes edge),
  `forecast.supersede` (supersedes edge), `memory.reflect` (about
  edge), `memory.link` (explicit edge), `source.attach_to_*` (provenance
  edge), `playbook.adherence` (followed/overridden flags),
  `strategy.upsert` (no edges; strategy.created is its own line).
- `forecast.scored`: cascaded from `resolution.add` /
  `journal.rescan_scoring`. Has no direct write tool.
- `playbook_rule.followed` / `playbook_rule.overridden`: cascaded from
  `decision.record_adherence` (or directly from a `decision.add` that
  references a playbook version).
- `import.row_committed`: cascaded from the importer itself when it
  commits a non-event journal row.

**Replay policy:** importer **skips** these on direct replay (`continue`
with a counter), because replaying the parent will regenerate them
under the same idempotency_key. Counting the skip in the import
result makes it observable.

### C. Replayable as an edge-shape write

Events emitted as edges that DO have a direct write surface:

- `playbook.proposed_version` → `playbook.propose_version`
- `playbook.created` → `playbook.upsert`
- `strategy.created` → `strategy.upsert`
- `strategy.updated` → `strategy.update`

Move these to **bucket A** in the implementation: the JSONL `{tool,
args}` envelope replays directly through dispatch. Today's importer
recognizes the parent (decision/thesis) writes but not these; the
follow-up implementation bead must add them to the import dispatch
table.

### D. Diagnostic — not replayed, not failed

Events that record observation rather than mutation. Replaying them
through dispatch would create a fresh observation row, which is wrong
for restore — restores want the *original* observation timestamp.

**Members:**

- `memory_node.invalidated`: an observation about an existing node's
  validity window. Has no direct write surface today; importer skips
  with a logged note.
- `signal.emitted`: lazy-emitted by `signal.scan` / `report.coach`;
  the importer re-runs scan on the imported journal if signals are
  desired. Skip with a logged note.
- `market.refreshed`: emitted by `market.refresh` when it re-syncs a
  bound market row from live Gamma on a cache miss. Records venue truth
  at fetch time, not a caller mutation; `market.refresh` is not
  import-ready (replay would re-fetch live), so the importer skips it
  and a restored journal regenerates it on demand by re-running
  `market.refresh`. (The initial `market.bound` write IS bucket A.)
- `autonomous_run.recorded` / `autonomous_incident.recorded`: historical
  audit events from the cut autonomous run/incident cluster. The write tools
  were removed, so restore does not dispatch these events; existing JSONL keeps
  the original audit facts for archival inspection.

**Replay policy:** importer recognizes these in the manifest, increments
a `diagnostic_skipped` counter, does not call `dispatch()`. A future
bead can revisit this if "preserve original signal/invalidation
timestamp" becomes a requirement (e.g. for audit replays); the policy
today is "regenerate on demand."

### E. Rejected — never legal on import

A JSONL line that doesn't match any of A/B/C/D fails the import with
`VALIDATION_ERROR` + `details.event_type` + `details.unknown_in_taxonomy =
true`. New event families that haven't been triaged into one of the
above buckets surface loudly instead of silently rejecting.

## Compatibility notes

- The current importer recognizes the bucket-A M0/M1 surface already.
  Adding M3 memory / M3 strategy / M4 playbook entries is additive and
  cannot reject lines that previously imported.
- The bucket-B "skip cascaded events" policy is what the importer
  effectively does today (it ignores `edge.created` etc. because
  there's no tool for them). The follow-up beads name the policy
  explicitly + count the skips.
- The bucket-D diagnostic skip means a journal restored via JSONL
  replay will NOT preserve the original `signal.emitted` rows.
  Operators rely on the on-disk JSONL for full fidelity; the new
  policy is "restore reproduces journal state, not transient
  diagnostics." Document this in operability.md as part of the
  implementation bead.

## Follow-up beads

Three implementation beads break this taxonomy into bounded work:

1. **Extend the importer's dispatch table** for bucket-A M3 memory,
   M3 strategy, and M4 playbook tool surfaces. Tests: round-trip a
   journal that contains every bucket-A event family.
2. **Skip + count bucket-B cascaded events** during import. Tests:
   an import that contains both a `decision.created` and the cascaded
   `playbook_rule.followed` writes ONE decision row and zero
   double-counted adherence rows; the import result reports
   `cascaded_skipped: 1`.
3. **Skip + log bucket-D diagnostic events** with an operability.md
   note. Tests: importing a journal with `signal.emitted` rows yields
   `diagnostic_skipped: N` and the events do NOT replay through
   `signal.scan`.

A separate enforcement test under `tests/contracts/` walks
`semantic_keys.py`'s registry and asserts every event type is named in
this document under exactly one bucket — that catches "we added an
event type but forgot to triage its import policy" at PR time.
