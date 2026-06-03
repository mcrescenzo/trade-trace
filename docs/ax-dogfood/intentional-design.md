# Intentional-design list — DO NOT "fix" these

> Read this at the start of every AX dogfood run (Phase A). The behaviors below
> **look like bugs but are deliberate and documented.** The cold bot in Phase B
> may still *report* friction around them — that is fine and useful — but the
> engineer in Phase C must **never** edit them directly. If one genuinely
> impedes a real bot, file a Beads *question* (`label:ax-dogfood`) describing the
> friction and proposing a discussion, do not change the behavior.
>
> Maintenance: when a run confirms a *new* surprising-but-intentional behavior
> (with a citation), append it here so future runs stop re-litigating it.

| # | Behavior (looks like a bug) | Why it is intentional | Citation |
|---|---|---|---|
| 1 | After `decision.add(paper_enter)` opens a position, `resolution.add(resolved_final)` leaves the position **open** (`resolved_at` stays null). | Position lifecycle is independent of market resolution; closing is a separate agent action (`paper_exit`/`actual_exit`). Pinned FINDING from the tracelab epic. | `tools/ledger/outcome.py:46-150` never writes `position_events`; opens only in `tools/ledger/decision.py:196-208`. Test: `tests/integration/test_manual_ledger_flow.py::test_resolved_final_does_not_close_open_paper_position`. tracelab epic `trade-trace-04is`; `docs/architecture/position-reopen-semantics.md`. |
| 2 | A second concurrent writer gets `STORAGE_ERROR` with `details.reason="single_writer_lock"`. | v0.0.2 is single-writer-only at the SQLite file level; parallel-write fan-out is deferred. The contract is **recovery in one retry** (`retry_after_seconds`), not simultaneous success. | `docs/LIVE_TEST_CHARTER.md` §v0.0.2 concurrency contract; `docs/architecture/operability.md` §3; `docs/architecture/persistence.md` §2. |
| 3 | `outcome.fetch` returns `status=resolved_final` but `outcome_label="unknown"` on genuinely-resolved markets. | Gamma is a convenience adapter, not a source of truth; not all resolved markets expose `winningOutcome` in the payload. The agent supplies ground-truth via `resolution.add`. | `tools/adapter_polymarket.py` outcome path (~`:428-429`); see the resolution-determination spec in the run playbook. |
| 4 | A forecast does **not** auto-score on resolution unless the outcome carries `confidence >= 0.9` **and** a binary label (`yes/no/true/false`) **and** `status=resolved_final`. | Prevents poisoning calibration with uncertain/ambiguous outcomes. A scoreable forecast (thesis on same instrument, `scoring_support='supported'`) must also already exist. | `tools/ledger/_finality.py:33-41` (`is_auto_scoreable_final`); scoreable query `tools/ledger/_scoring.py:113-134`; `docs/architecture/scoring.md` §5. |
| 5 | `market.bind` on a market with >2 outcomes returns `ADAPTER_PROTOCOL_ERROR`. | The v0.0.2 scorer is binary-only (Brier); rejecting multi-outcome markets up front prevents silent data loss. | `tools/adapter_polymarket.py` (binary guard); `docs/architecture/contracts.md` (`ADAPTER_PROTOCOL_ERROR`). |
| 6 | There is no `forecast.set_yes_label`; `yes_label` cannot be edited after `forecast.add`. | Forecasts are append-only. Correct an ambiguous label by writing a new row via `forecast.supersede`, never by mutation. | `docs/architecture/scoring.md` §3.2; append-only invariant `docs/architecture/persistence.md`. |
| 7 | Same idempotency key + a *different* payload returns `IDEMPOTENCY_CONFLICT` (never commits the second version); calling an adapter with network disabled returns `ADAPTER_DISABLED`. | Append-only + idempotency guarantee replay safety and no silent data loss; fail-closed networking prevents accidental calls/credential leaks. Free-text fields (e.g. `decision.reason`) are excluded from conflict detection so prose can be regenerated. | `docs/architecture/persistence.md` §5; `docs/architecture/semantic-key-policy.md` §3; `docs/architecture/contracts.md` error taxonomy. Beads `trade-trace-cpz2`, `trade-trace-t7hi`. |
| 8 | `resolution.add` rejects status values outside the closed enum with `VALIDATION_ERROR`. | The status enum (`resolved_final`, `resolved_provisional`, `ambiguous`, `disputed`, `void`, `cancelled`) is load-bearing for auto-score logic; arbitrary strings risk silent non-scoring. | `docs/architecture/scoring.md` §5. |

## Contract firewall (always a Beads item, never a direct edit)

Even a "small" change to any of these is filed, not fixed:

- **Append-only** writes (forecasts / outcomes / memory nodes / events).
- **Idempotency** enforcement and key derivation.
- The **typed envelope** contract (`docs/architecture/contracts.md`).
- **Single-writer** concurrency model.
