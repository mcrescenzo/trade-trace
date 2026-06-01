# TraceLab stagger schedule

This file documents the deterministic 14-day accelerated TraceLab schedule defined in `tools/tracelab/schedule.py`. It is an operator/test artifact, not a production daemon or cron runner.

## Contract being exercised

The locked Phase 5 charter validates recoverable SQLite/WAL single-writer behavior, not parallel-write throughput. The schedule therefore keeps normal write bursts staggered while still allowing rare contention to be handled by the documented 5s `busy_timeout` plus the B11 one-retry wrapper.

## Named backup quiescence window

- Name: `b12-nightly-backup-quiescence`
- Cadence: every 24h during the 14-day run
- Window: T+03:20:00 through T+03:30:00 each run day
- Paused roles: `trader-agent`, `seeder`, `resolution-feeder`
- Backup: `backup-b7` starts at T+03:22:00 and runs only inside this window

`backup-b7` invokes `journal.backup` via `tools/tracelab/backup.py`. The writer pause is required because `wal_checkpoint` plus `shutil.copy2` is only a consistent backup operation without concurrent writers.

## Staggered task offsets and cadences

| Task | Role | Offset | Cadence | Duration | Writes? | Notes |
| --- | --- | ---: | ---: | ---: | --- | --- |
| `trader-a` | trader agent | T+00:02 | 30m | 75s | yes | Primary burst at minute `:02/:32`. |
| `trader-b` | trader agent | T+00:17 | 30m | 75s | yes | Offset 15m from `trader-a`, far beyond the 7s busy-timeout + retry envelope. |
| `seeder-b3` | seeder | T+00:10 | one-shot | 4m | yes | Early B3 seed of near-term binary markets to target N>=20. |
| `resolution-feeder-b4` | resolution feeder | T+00:47 | 6h | 2m | yes | Periodic lagging feeder; not aligned to trader bursts. |
| `health-snapshotter-b5` | health snapshotter | T+00:23 | 1h | 30s | no | Read-only DB health snapshot. |
| `backup-b7` | backup | T+03:22 | 24h | 5m | yes | Runs only inside `b12-nightly-backup-quiescence`. |

## Dry simulation

`tools.tracelab.schedule.dry_simulation()` expands the schedule deterministically. Contract tests assert:

- the two trader agents have no simultaneous write-burst starts;
- nearest trader-burst starts are separated by more than the 5s busy timeout and the 7s timeout+retry envelope;
- the required sidecars are present at distinct cadences;
- each backup occurrence is contained within `b12-nightly-backup-quiescence`; and
- paused writer roles have no scheduled occurrences overlapping the backup quiescence window.
