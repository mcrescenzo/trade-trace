"""SQLite bootstrap, migrations, and journal init."""

from trade_trace.storage.database import Database, open_database
from trade_trace.storage.migrations import MIGRATIONS, apply_pending_migrations, current_version
from trade_trace.storage.paths import default_home, resolve_home
from trade_trace.storage.policy import (
    CLOSED_ENUMS,
    OPEN_ENUMS,
    EnumChange,
    MigrationPolicyError,
    check_column_change,
    check_enum_extension,
    check_no_reverse_migration,
)

__all__ = [
    "CLOSED_ENUMS",
    "Database",
    "EnumChange",
    "MIGRATIONS",
    "MigrationPolicyError",
    "OPEN_ENUMS",
    "apply_pending_migrations",
    "check_column_change",
    "check_enum_extension",
    "check_no_reverse_migration",
    "current_version",
    "default_home",
    "open_database",
    "resolve_home",
]
