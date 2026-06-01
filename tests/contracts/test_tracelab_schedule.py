from __future__ import annotations

from typing import cast

from tools.tracelab.schedule import (
    BACKUP_QUIESCENCE,
    BUSY_TIMEOUT_SECONDS,
    QUIESCENCE_WINDOW_NAME,
    RETRY_ENVELOPE_SECONDS,
    RUN_DURATION_SECONDS,
    TRACELAB_SCHEDULE,
    dry_simulation,
    occurrences,
    quiescence_occurrences,
)


def test_schedule_includes_required_roles_and_distinct_cadences():
    by_role = {task.role: task for task in TRACELAB_SCHEDULE}

    assert [task.role for task in TRACELAB_SCHEDULE].count("trader-agent") == 2
    assert by_role["seeder"].cadence_seconds is None
    assert by_role["resolution-feeder"].cadence_seconds == 6 * 60 * 60
    assert by_role["health-snapshotter"].cadence_seconds == 60 * 60
    assert by_role["backup"].cadence_seconds == 24 * 60 * 60

    cadences = {
        by_role["seeder"].cadence_seconds,
        by_role["resolution-feeder"].cadence_seconds,
        by_role["health-snapshotter"].cadence_seconds,
        by_role["backup"].cadence_seconds,
    }
    assert len(cadences) == 4
    assert by_role["health-snapshotter"].read_only is True


def test_dry_simulation_offsets_two_trader_write_bursts():
    sim = dry_simulation()
    starts = cast(dict[str, list[int]], sim["trader_start_samples_seconds"])
    assert starts["trader-a"][0] == 2 * 60
    assert starts["trader-b"][0] == 17 * 60

    trader_occurrences = [occ for occ in occurrences() if occ.task.role == "trader-agent"]
    starts_by_time: dict[int, list[str]] = {}
    for occ in trader_occurrences:
        starts_by_time.setdefault(occ.start_seconds, []).append(occ.name)
    assert all(len(names) == 1 for names in starts_by_time.values())

    for a_occ in [occ for occ in trader_occurrences if occ.name == "trader-a"][:20]:
        nearest_b_delta = min(
            abs(a_occ.start_seconds - b_occ.start_seconds)
            for b_occ in trader_occurrences
            if b_occ.name == "trader-b"
        )
        assert nearest_b_delta > RETRY_ENVELOPE_SECONDS
        assert nearest_b_delta > BUSY_TIMEOUT_SECONDS


def test_backup_runs_inside_named_quiescence_window_and_writers_are_paused():
    assert BACKUP_QUIESCENCE.name == QUIESCENCE_WINDOW_NAME
    assert BACKUP_QUIESCENCE.pauses_roles == ("trader-agent", "seeder", "resolution-feeder")

    expanded = occurrences()
    windows = quiescence_occurrences()
    backup_occurrences = [occ for occ in expanded if occ.name == BACKUP_QUIESCENCE.backup_task]
    assert len(backup_occurrences) == RUN_DURATION_SECONDS // (24 * 60 * 60)

    for backup in backup_occurrences:
        assert any(start <= backup.start_seconds and backup.end_seconds <= end for start, end in windows)

    paused_writer_roles = set(BACKUP_QUIESCENCE.pauses_roles)
    for window_start, window_end in windows:
        overlapping_paused_writers = [
            occ
            for occ in expanded
            if occ.task.writer
            and occ.task.role in paused_writer_roles
            and occ.start_seconds < window_end
            and window_start < occ.end_seconds
        ]
        assert overlapping_paused_writers == []
