# tracelab — agentic end-to-end paper-trading test of Trade Trace

Status: design (epic `trade-trace-04is`)
Related: [`LIVE_TEST_CHARTER.md`](./LIVE_TEST_CHARTER.md) (LOCKED — referenced, not extended)

## Purpose

Prove Trade Trace holds up under sustained, real, multi-agent use (**primary
goal — substrate correctness**) and produce a descriptive read of agent
forecasting/process skill (**secondary goal**). Two or more Claude Code trader
agents paper-trade live Polymarket binary markets through Trade Trace for an
accelerated ~1–2 week window, instrumented to capture observability the system
does not emit today.

This document is the verified design. Every load-bearing claim below was
checked against the code; the corrections that changed the design are called
out explicitly. The implementation is tracked as beads under epic
`trade-trace-04is`.

## Decisions (locked with the owner)

| Axis | Decision |
| --- | --- |
| Primary goal | Both, **weighted to substrate correctness** |
| Data mode | **Hybrid** — live `snapshot.fetch` (Gamma) + **manual** resolution ground truth |
| Concurrency | **Multi-agent** (2+ actors), scored as lock **recovery-in-1-retry**, not parallel writes |
| P&L / close | **Resolution-only close on the shipped surface**; the non-close behavior is a logged FINDING, not a fix |
| Discipline | **Not** prompt-hardcoded — agents use native affordances; rail adoption is **measured** |
| Instrumentation | Env-gated dispatch trace + read-only-SQLite health sidecar (MCP tee-proxy **cut**) |
| Duration | Accelerated ~1–2 weeks; seed near-term binaries to cross **N ≥ 20** resolved forecasts |
| Driver | Scheduled Claude Code agents (per the trader profile + `trade_trace` MCP server) |

## Architecture — three layers

### Layer 1 — Trader agents (the system's intended user, under test)

2+ scheduled Claude Code agents, each with a distinct `MCP_ACTOR_ID`
(`agent:trader-a`, `agent:trader-b`), sharing **one** `TRADE_TRACE_HOME`.
`MCP_ACTOR_ID` is read per-call in `mcp_server.py` and is fully decoupled from
home resolution, so two server processes can safely point at the same DB
(proven by `tests/contracts/test_mcp_schema_compat.py`). The launch contract is
materialized by `tools/tracelab/agent_launch.py`: every trader process receives
one shared absolute `TRADE_TRACE_HOME`, a unique `MCP_ACTOR_ID`, a per-actor
`TRADE_TRACE_LOG_DIR`, and an enabled shared dispatch trace path. The helper
rejects duplicate actor ids before launch because the idempotency uniqueness
scope is `(event_type, actor_id, idempotency_key)`: distinct actors may safely
reuse a key, but two misconfigured processes sharing one actor id can collide
with `IDEMPOTENCY_CONFLICT` if their payloads differ. Agents work from the
system's native affordances (`report.bootstrap`, `report.work_queue`,
`report.coach` + the trader profile); they are **not** handed a hardcoded rail
script. Adoption of the discipline rails is measured, not dictated.

### Layer 2 — Sidecar (non-LLM, deterministic)

A set of scripts under `tools/tracelab/`:

- **Seeder** — selects + binds Polymarket markets that are simultaneously
  binary YES/NO, resolving in-window, and liquid. Over-seeds (40–50 candidates)
  because the intersection is scarce; self-throttles Gamma (the adapter has no
  client-side rate limiter); records the seeded conditionId set so
  seeding-induced `ADAPTER_PROTOCOL_ERROR`s can be told apart from genuine ones.
- **Resolution feeder** — applies manual `resolution.add(status=resolved_final,
  confidence≥0.9, outcome_label∈{yes,no,true,false})`, only for markets that
  already have a committed/revealed scoreable forecast. (See the run-fatal
  correction below.)
- **Health snapshotter** — periodic counts via `open_database_readonly`
  (`mode=ro` + `PRAGMA query_only=1`): `events`, `forecast_scores` (the N
  tracker), `positions` (open/closed split), `outbox` backlog, resolved-but-
  unclosed forecasts, free disk **and free inodes**. Also a Gamma schema-drift
  canary. No change to the `journal.status` contract.
- **Metric rollup** — `report.calibration`, `report.calibration_integrity`
  (a **separate** call — see correction), `report.process_quality`,
  `report.resolution_misreads`, `report.pnl`, `report.coach`.
- **Backup** — `journal.backup` **with the confirm flag**, inside a quiescence
  window (see correction).

### Layer 3 — Package instrumentation (authorized, minimal, env-gated)

- **Dispatch trace log** — backfilled into `core.dispatch`, gated on an env var,
  written append-only to a **separate file** (never the journal DB, so it does
  not contend for the single-writer lock or perturb the latency/concurrency
  invariants it measures). Captures every dispatch return path. This is the
  keystone for read-rail adoption and for the zero-row dispatch classes the
  reconciler cannot otherwise see.
- Health counts live entirely in the read-only sidecar — **no** change to any
  shipped tool contract.

The **MCP stdio tee-proxy was cut**: the MCP server generates a fresh
`request_id` per call and ignores the JSON-RPC envelope id, so there is no
shared join key between tee frames and the dispatch trace, and the proxy adds a
redaction-bypass risk for marginal value over the dispatch trace.

## Verified corrections (these changed the design)

1. **RUN-FATAL — scoring needs more than `resolved_final`.**
   `is_auto_scoreable_final` (`tools/ledger/_finality.py:33-41`) also requires
   `confidence ≠ None` **and** `confidence ≥ 0.9` **and** `outcome_label ∈
   {yes,no,true,false}`, **and** a matching scoreable forecast must already
   exist. A resolution missing confidence, or fed for an unforecasted market,
   silently writes **zero** `forecast_scores` rows → N never reaches 20 and
   nothing errors. The feeder has two pre-checks; the golden smoke pins both
   silent-zero paths.
2. **Concurrency = recovery-in-1-retry, not parallel writes**
   (`LIVE_TEST_CHARTER.md:16,61`, LOCKED). The substrate-invariant checker does
   not score simultaneous successful writes or throughput.
3. **`events.request_id` already exists** (`events/log.py:286,298,324`) — write
   →event reconciliation correlates via that column with no trace. The dispatch
   trace is required only for read rails and zero-row classes.
4. **One UnitOfWork = one transaction, not one event.** Cascade tools emit
   multiple `events` rows; reads emit zero; `memory.recall` emits 0 `events`
   rows but 1 `memory_recall_events` row; dry-run emits 0; idempotent replay
   emits 0 new rows. The reconciler buckets by class — a naive 1:1 reconciler
   false-positives "data loss".
5. **`journal.backup` gates on confirm and is not `.backup()`.** Without
   `confirm` it returns `{preview_only:true}` and writes nothing
   (`admin.py:320`); it runs `PRAGMA wal_checkpoint(TRUNCATE)` + `shutil.copy2`
   (`admin.py:338-342`), so it is consistent only with no concurrent writer →
   backups run in a defined quiescence window.
6. **Drop `polygon_rpc_url` entirely.** Resolution is manual, so the only
   metered/credentialed on-chain endpoint is unneeded. Enable Gamma only;
   flipping `network.polymarket.enabled=false` is an instant fail-closed kill
   switch.
7. **The secret scanner hard-blocks 40-hex tokens** in scanned free-text (it
   fails the write with `VALIDATION_ERROR`, not a warning). Agents are
   instructed never to paste raw `0x`/40-hex addresses or tx hashes; the
   risk-unit convention is hex-free; such hits are treated as expected
   recoverable events (Polymarket `conditionId` 0x+64hex is exempt).
8. **Cross-actor idempotency non-collision is trivially true** (the unique index
   is `(event_type, actor_id, idempotency_key) WHERE key IS NOT NULL`). The real
   risk is the opposite — two agents accidentally **sharing** an actor_id →
   `IdempotencyConflictError`. The invariant becomes: assert distinct
   `MCP_ACTOR_ID` per agent, assert zero conflicts, plus positive same-actor
   replay/conflict unit tests.

## Scoring rubric — "is it working?"

**Substrate correctness (primary, pass/fail):** write dispatches reconcile to
`events` via `events.request_id`; zero-row classes reconcile via trace
bucketing; every `single_writer_lock` recovers in 1 retry; zero non-lock
`STORAGE_ERROR`; zero **genuine** `ADAPTER_PROTOCOL_ERROR`; zero
`IdempotencyConflictError`; distinct actor ids; `journal.rebuild_projections`
reproduces positions; a quiesced `journal.backup`/restore round-trips
byte-identical.

**Agent skill (secondary, descriptive):** calibration (Brier/ECE/skill once
N ≥ 20), `process_quality` Kelly alignment, `resolution_misreads`
contract-misread rate, independence-proven rate, abstention discipline, pnl
(with the resolution-only-close caveat).

**System-affordance findings (qualitative payoff):** per-actor read-rail call
counts (observational, not a causal precedence claim — read rails emit nothing
today, so this is trace-only and not replay-reproducible) and a catalogue of
where the shipped surface confused agents.

**Expected-and-documented findings:** neither `paper_exit` nor resolution closes
a position today (pinned by an evidence test); `outcome.fetch` unreliability;
the combinator-stripped `forecast.add` schema; `snapshot.fetch` at=now-only.

## Implementation map (epic `trade-trace-04is`)

- **Phase 0 — instrumentation & substrate proofs:** B1 dispatch trace (.1),
  B21 idempotency replay/conflict tests (.20), B22 resolution-non-close pin (.21)
- **Phase 1 — sidecars:** B3 seeder (.2), B4 resolution feeder (.3),
  B5 health + canary (.4), B6 metric rollup (.5), B7 backup (.6)
- **Phase 2 — agent enablement & run config:** B8 trader profile (.7),
  B9 multi-actor identity (.8), B10 Gamma-only network (.9), B11 lock-retry (.10),
  B12 stagger + quiescence (.11), B18 run-config doc (.17)
- **Phase 3 — analysis & scorecard:** B13 reconciler (.12),
  B14 invariant checker (.13), B15 skill + adoption (.14), B16 scorecard (.15)
- **Phase 4 — run ops, safety, teardown:** B17 golden smoke (.16),
  B19 capture hygiene + disk bounds (.18), B20 teardown (.19)

## Open items for the run-config doc (B18)

Late-recorded exclusion policy; bankroll/risk-unit convention (hex-free);
disposable `TRADE_TRACE_HOME` location/perms/inode sizing + teardown; how the
seeded watchlist reaches agents (via `report.watchlist`/`work_queue`, not prompt
injection); minimum-N abort/extend rule + per-day Gamma call budget; owner HITL
sign-off before enabling the network; confirmation of whether `coach`/`bootstrap`
take the writer lock so the retry policy covers every writing read.

Canonical substrate proof for positive idempotency replay/conflict semantics
lives in package tests, not in the run-artifact checker: see
`tests/integration/test_mcp_idempotency.py` for same-actor/same-key/same-payload
replay producing zero new events and same-actor/same-key/different-payload
surfacing `IDEMPOTENCY_CONFLICT` without a second event row.

Canonical B16/scorecard evidence for the expected resolution-does-not-close
finding lives in `tests/integration/test_manual_ledger_flow.py::test_resolved_final_does_not_close_open_paper_position`: after `decision.add(type=paper_enter)` opens a paper position, `outcome.add(status=resolved_final)` leaves the `positions` row `status='open'` with `resolved_at IS NULL`.
