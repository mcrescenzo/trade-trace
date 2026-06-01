# TraceLab operational run configuration

This document is the human-readable operational run configuration for the TraceLab live run. It records operator decisions and budgets that must be fixed before launch. It references the locked Phase 5 charter instead of restating or extending its concurrency contract.

## Locked charter reference

The live run is governed by [`docs/LIVE_TEST_CHARTER.md`](../LIVE_TEST_CHARTER.md). In particular, the recovery-in-one-retry behavior, `single_writer_lock` handling, and Phase 5 pass/fail criteria are defined only in the locked charter. This run-config does not redefine, broaden, or extend that contract; operators must resolve any apparent conflict by following the locked charter.

The deterministic schedule and backup quiescence plan are documented in [`docs/tracelab/stagger-schedule.md`](stagger-schedule.md). Machine-checkable capture hygiene for JSONL drain suppression, transcript retention, dispatch-trace rotation, and replay caveats remains in [`docs/tracelab/run-config.json`](run-config.json).

## Operator decisions and budgets

### Kill switch

The live-network kill switch is a shared configuration flip: set `network.polymarket.enabled=false` in the shared config row. The expected result is an immediate `ADAPTER_DISABLED` response from adapter paths.

Do **not** use process kills such as `kill -9` as the operational kill switch. Process termination may be used only for ordinary process supervision after evidence is preserved; it is not the TraceLab network-disable mechanism.

### Bankroll and risk-unit labels

Bankroll accounting uses explicit, human-readable labels. Free-text risk sizing must use the hex-free `risk_unit_label` convention already documented for trader agents:

- `risk-unit-small`
- `risk-unit-medium`
- `risk-unit-large`

Do not put `0x...` strings, addresses, transaction hashes, or bare 40-hex tokens in free-text bankroll, risk, thesis, decision, reason, falsification, exit, invalidation, or resolution prose. Structured product identifiers stay in structured product fields only.

### Minimum-N rule and seeding target

Minimum scoreable sample size is **N=20**.

Abort/extend rule: at the planned end of the run, count only scorecard-eligible records after applying the late-recorded policy below. If eligible N is less than 20, the run is not a pass, fail, or silent inconclusive; it must be explicitly marked `MIN_N_NOT_MET` and either:

1. extended under the same charter and this run-config until eligible N reaches at least 20, or
2. aborted with sanitized evidence and follow-up beads filed by the controller.

To reduce the chance of a short-N outcome, the seeder should over-seed **40-50** candidate markets rather than targeting exactly 20.

### Gamma call budget

Current approved TraceLab Gamma API budget is **500 requests per day** across discovery, seeding, health canary, and any other TraceLab Gamma callers. The previous 100-request discovery cap was superseded for dry-run discovery; 500/day is the current approved budget truthfully recorded for the live run. Any future increase beyond 500/day requires a separate owner-approved escalation and must not be inferred from this document.

### HITL sign-off before enabling network

Before setting any real network path to enabled, the owner must complete a human-in-the-loop sign-off checkpoint confirming:

- the disposable `TRADE_TRACE_HOME` is selected and initialized;
- this run-config and the locked charter are the active operator documents;
- the Gamma budget is accepted;
- the kill switch has been rehearsed as a config flip to `network.polymarket.enabled=false`; and
- sanitized evidence capture is ready.

Non-dry seeding in a disposable home may have been separately approved and verified, but final live/production network enablement still requires this HITL gate.

### Disposable home location, permissions, inode sizing, and teardown

Use a disposable home outside any developer's long-lived profile, for example `/tmp/trade-trace-tracelab/$RUN_ID`.

Required setup:

- directory mode `0700`;
- owned by the operator account running TraceLab;
- no checked-in secrets or reused production wallet material;
- filesystem selected with enough free inodes for SQLite/WAL files, rotated dispatch traces, transcripts, backups, and post-run evidence bundles;
- record `df -i` / inode availability and the resolved absolute home path in sanitized launch evidence.

Teardown is not implemented here. Follow the B20 teardown bead/runbook when available; until then, preserve required evidence first and remove the disposable home only after controller approval.

### Late-recorded exclusion policy

Default policy: scorecards must **exclude late-recorded records** unless the scorecard runner is explicitly invoked with `include_late_recorded=true`.

A record is late-recorded when the decision/evidence was recorded after the feeder cadence window that should have captured it for the relevant market/resolution event. This policy is tied to the resolution-feeder cadence in the stagger schedule and is consumed by B6 scorecard work. B6 may implement the mechanics, but it must treat default exclusion as this run-config's decision unless a reviewer deliberately opts into `include_late_recorded=true` and records that choice.

### Watchlist and work queue handoff

Seeded markets and follow-up work must be handed to trader agents through `report.watchlist` and `report.work_queue`. Do not inject market IDs, condition IDs, transaction hashes, addresses, or trading instructions through the agent prompt.

### Confirmation coach and bootstrap lock behavior

Confirmation coach and bootstrap behavior are covered by the locked charter's retry policy when they touch the journal. This document adds no separate retry contract for those paths.
