"""Migration policy enforcement per docs/architecture/operability.md §4
(trade-trace-6h2 acceptance criteria)."""

from __future__ import annotations

import pytest

from trade_trace.storage import (
    CLOSED_ENUMS,
    OPEN_ENUMS,
    MIGRATIONS,
    MigrationPolicyError,
    apply_pending_migrations,
    check_column_change,
    check_enum_extension,
    check_no_reverse_migration,
    current_version,
    open_database,
)
from trade_trace.storage.paths import db_path


# -- 1. Forward migration data preservation -------------------------------


def test_forward_migration_preserves_data(tmp_path):
    """A migration that adds a table or column must NOT touch unrelated rows.
    We seed the `meta` table with a sentinel row, then apply a fake migration
    that creates a new `__sample` table, and assert the sentinel survives.
    """

    db = open_database(db_path(tmp_path / "home"))
    try:
        # Bring DB to schema_version=1 first.
        apply_pending_migrations(db.connection)
        db.connection.execute(
            "INSERT INTO meta(key, value) VALUES ('sentinel', 'before-fake-migration')"
        )
        before_count = db.connection.execute("SELECT COUNT(*) FROM meta").fetchone()[0]

        # Append a one-off migration that adds a new table.
        def _fake_migration(conn):
            conn.execute("CREATE TABLE __sample (x INTEGER)")
            conn.execute("INSERT INTO __sample(x) VALUES (1), (2), (3)")

        # Splice it into MIGRATIONS for the duration of this test.
        MIGRATIONS.append(_fake_migration)
        try:
            apply_pending_migrations(db.connection)
            after_count = db.connection.execute("SELECT COUNT(*) FROM meta").fetchone()[0]
            assert after_count == before_count, "row count preserved across migration"
            sentinel = db.connection.execute(
                "SELECT value FROM meta WHERE key = 'sentinel'"
            ).fetchone()
            assert sentinel[0] == "before-fake-migration"
            # The new table also has the rows the migration inserted.
            assert db.connection.execute("SELECT COUNT(*) FROM __sample").fetchone()[0] == 3
        finally:
            MIGRATIONS.pop()
    finally:
        db.close()


# -- 2. Reverse migration rejected ----------------------------------------


def test_reverse_migration_rejected_via_check():
    """`check_no_reverse_migration` raises when target < current."""

    with pytest.raises(MigrationPolicyError) as exc:
        check_no_reverse_migration(current_version=5, target_version=3)
    assert "forward-only" in str(exc.value)


def test_reverse_migration_rejected_via_runner(tmp_path):
    """The migration runner refuses target_version below current_version."""

    db = open_database(db_path(tmp_path / "home"))
    try:
        apply_pending_migrations(db.connection)  # bumps to len(MIGRATIONS)
        with pytest.raises(MigrationPolicyError):
            apply_pending_migrations(db.connection, target_version=0)
    finally:
        db.close()


# -- 3. schema_version table updates --------------------------------------


def test_schema_version_table_updates(tmp_path):
    """After each apply, meta.schema_version reflects the new head."""

    db = open_database(db_path(tmp_path / "home"))
    try:
        assert current_version(db.connection) == 0
        apply_pending_migrations(db.connection)
        assert current_version(db.connection) == len(MIGRATIONS)
        # Idempotent re-apply leaves the version unchanged.
        apply_pending_migrations(db.connection)
        assert current_version(db.connection) == len(MIGRATIONS)
    finally:
        db.close()


# -- 4. Enum-extension policy ---------------------------------------------


def test_closed_enum_extension_rejected():
    """Adding a value to a closed enum without a contract bump is rejected."""

    baseline = CLOSED_ENUMS["decisions.type"]
    with pytest.raises(MigrationPolicyError) as exc:
        check_enum_extension("decisions.type", baseline | {"brand_new_type"})
    assert "breaking contract change" in str(exc.value)


def test_closed_enum_removal_rejected():
    """Removing a value from a closed enum is hard-rejected."""

    baseline = CLOSED_ENUMS["outcomes.status"]
    smaller = baseline - {"void"}
    with pytest.raises(MigrationPolicyError):
        check_enum_extension("outcomes.status", smaller)


def test_open_enum_extension_allowed():
    """Adding a value to an open enum is non-breaking (returns the diff)."""

    baseline = OPEN_ENUMS["signals.kind"]
    change = check_enum_extension("signals.kind", baseline | {"new_signal_kind"})
    assert change.is_additive_only is True
    assert change.added == {"new_signal_kind"}
    assert change.removed == frozenset()


def test_unknown_enum_rejected():
    """An enum not registered in policy.py is rejected; registration is the
    deliberate gate for adding new enums."""

    with pytest.raises(MigrationPolicyError):
        check_enum_extension("totally.unknown_enum", {"a", "b"})


def test_failure_reason_enum_locked_to_three_values():
    """Per scoring.md §4.4 the failure_reason enum is closed at three values.
    A future migration that adds a fourth without a contract bump must be
    caught."""

    baseline = CLOSED_ENUMS["forecast_scores.failure_reason"]
    assert baseline == {
        "yes_label_ambiguous",
        "label_mismatch",
        "outcome_superseded_mid_score",
    }
    with pytest.raises(MigrationPolicyError):
        check_enum_extension(
            "forecast_scores.failure_reason",
            baseline | {"some_new_reason"},
        )


# -- 5. Column-removal blocked without major version bump -----------------


def test_column_removal_blocked_without_major_bump():
    """check_column_change refuses removal unless the caller passes the bump
    acknowledgment."""

    with pytest.raises(MigrationPolicyError) as exc:
        check_column_change(
            table="decisions",
            before={"id", "type", "reason", "deprecated_legacy_field"},
            after={"id", "type", "reason"},  # removes deprecated_legacy_field
        )
    assert "major contract version bump" in str(exc.value)


def test_column_removal_allowed_with_major_bump():
    """With major_version_bump=True the policy permits the removal — the
    operator is asserting the §4.4 deprecation window was honored."""

    check_column_change(
        table="decisions",
        before={"id", "type", "reason", "deprecated_legacy_field"},
        after={"id", "type", "reason"},
        major_version_bump=True,
    )  # must NOT raise


def test_column_addition_always_allowed():
    """Adding a column is non-breaking; never raises."""

    check_column_change(
        table="decisions",
        before={"id", "type"},
        after={"id", "type", "new_segmentation_field"},
    )
