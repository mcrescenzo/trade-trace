"""Deterministic TraceLab stagger schedule and dry simulation.

This is a schedule definition/helper, not a daemon or cron runner.  It models the
14-day accelerated live-test cadence so tests and operators can verify that the
charter validates recoverable single-writer behavior rather than pathological
parallel-write throughput.
"""
from __future__ import annotations

from dataclasses import dataclass

RUN_DURATION_SECONDS = 14 * 24 * 60 * 60
BUSY_TIMEOUT_SECONDS = 5
B11_RETRY_AFTER_SECONDS = 2
RETRY_ENVELOPE_SECONDS = BUSY_TIMEOUT_SECONDS + B11_RETRY_AFTER_SECONDS
QUIESCENCE_WINDOW_NAME = "b12-nightly-backup-quiescence"


@dataclass(frozen=True)
class ScheduledTask:
    name: str
    role: str
    cadence_seconds: int | None
    offset_seconds: int
    duration_seconds: int
    writer: bool
    paused_during_quiescence: bool = False
    read_only: bool = False
    notes: str = ""


@dataclass(frozen=True)
class Occurrence:
    task: ScheduledTask
    start_seconds: int
    end_seconds: int

    @property
    def name(self) -> str:
        return self.task.name


@dataclass(frozen=True)
class QuiescenceWindow:
    name: str
    cadence_seconds: int
    offset_seconds: int
    duration_seconds: int
    backup_task: str
    pauses_roles: tuple[str, ...]


TRACELAB_SCHEDULE: tuple[ScheduledTask, ...] = (
    ScheduledTask(
        name="trader-a",
        role="trader-agent",
        cadence_seconds=30 * 60,
        offset_seconds=2 * 60,
        duration_seconds=75,
        writer=True,
        paused_during_quiescence=True,
        notes="Primary trader; write bursts start at minute :02/:32.",
    ),
    ScheduledTask(
        name="trader-b",
        role="trader-agent",
        cadence_seconds=30 * 60,
        offset_seconds=17 * 60,
        duration_seconds=75,
        writer=True,
        paused_during_quiescence=True,
        notes="Second trader offset 15 minutes from trader-a, well beyond retry envelope.",
    ),
    ScheduledTask(
        name="seeder-b3",
        role="seeder",
        cadence_seconds=None,
        offset_seconds=10 * 60,
        duration_seconds=4 * 60,
        writer=True,
        paused_during_quiescence=True,
        notes="One-shot early B3 seeding of near-term binaries to cross N>=20.",
    ),
    ScheduledTask(
        name="resolution-feeder-b4",
        role="resolution-feeder",
        cadence_seconds=6 * 60 * 60,
        offset_seconds=47 * 60,
        duration_seconds=2 * 60,
        writer=True,
        paused_during_quiescence=True,
        notes="Periodic lagging manual resolution feed; not on trader burst boundaries.",
    ),
    ScheduledTask(
        name="health-snapshotter-b5",
        role="health-snapshotter",
        cadence_seconds=60 * 60,
        offset_seconds=23 * 60,
        duration_seconds=30,
        writer=False,
        read_only=True,
        notes="Read-only DB health snapshot; may run outside writer quiescence.",
    ),
    ScheduledTask(
        name="backup-b7",
        role="backup",
        cadence_seconds=24 * 60 * 60,
        offset_seconds=3 * 60 * 60 + 22 * 60,
        duration_seconds=5 * 60,
        writer=True,
        notes="Runs journal.backup only inside the named quiescence window.",
    ),
)

BACKUP_QUIESCENCE = QuiescenceWindow(
    name=QUIESCENCE_WINDOW_NAME,
    cadence_seconds=24 * 60 * 60,
    offset_seconds=3 * 60 * 60 + 20 * 60,
    duration_seconds=10 * 60,
    backup_task="backup-b7",
    pauses_roles=("trader-agent", "seeder", "resolution-feeder"),
)


def occurrences(
    *,
    duration_seconds: int = RUN_DURATION_SECONDS,
    tasks: tuple[ScheduledTask, ...] = TRACELAB_SCHEDULE,
) -> list[Occurrence]:
    """Expand the schedule into deterministic occurrences within the run."""
    expanded: list[Occurrence] = []
    for task in tasks:
        if task.offset_seconds >= duration_seconds:
            continue
        starts = [task.offset_seconds]
        if task.cadence_seconds is not None:
            starts = list(range(task.offset_seconds, duration_seconds, task.cadence_seconds))
        expanded.extend(Occurrence(task, start, start + task.duration_seconds) for start in starts)
    return sorted(expanded, key=lambda item: (item.start_seconds, item.name))


def quiescence_occurrences(
    *,
    duration_seconds: int = RUN_DURATION_SECONDS,
    window: QuiescenceWindow = BACKUP_QUIESCENCE,
) -> list[tuple[int, int]]:
    """Return start/end seconds for each named backup quiescence window."""
    return [
        (start, start + window.duration_seconds)
        for start in range(window.offset_seconds, duration_seconds, window.cadence_seconds)
    ]


def dry_simulation() -> dict[str, object]:
    """Return a compact deterministic summary used by docs/tests."""
    expanded = occurrences()
    trader_starts = {
        item.name: [occ.start_seconds for occ in expanded if occ.name == item.name][:4]
        for item in TRACELAB_SCHEDULE
        if item.role == "trader-agent"
    }
    return {
        "run_duration_days": RUN_DURATION_SECONDS // 86_400,
        "busy_timeout_seconds": BUSY_TIMEOUT_SECONDS,
        "retry_envelope_seconds": RETRY_ENVELOPE_SECONDS,
        "quiescence_window": BACKUP_QUIESCENCE.name,
        "trader_start_samples_seconds": trader_starts,
        "occurrence_count": len(expanded),
    }
