"""Migration policy helpers per docs/architecture/operability.md §4.

This module encodes the *policy* checks (not the migration runner itself);
they back the test suite and serve as code-review prompts so a new migration
cannot silently break the contract:

- Forward-only: target_version < current_version is a runtime error.
- Adding a value to an open enum is non-breaking; adding a value to a closed
  enum requires a contract version bump (PRD §3.1 closed-enum list).
- Removing a column requires a major version bump and a one-version
  deprecation window.
- Renaming a column requires add-new + dual-write + remove-old over two
  schema versions.

The CHECK lists are exhaustive per the current docs; adding a new closed
enum requires extending OPEN_ENUMS / CLOSED_ENUMS here AND updating the
relevant architecture doc in the same patch.
"""

from __future__ import annotations

from dataclasses import dataclass

# Closed enums (per operability.md §4.3): adding values requires a major
# contract version bump.
CLOSED_ENUMS: dict[str, frozenset[str]] = {
    "decisions.type": frozenset(
        {
            "watch",
            "skip",
            "paper_enter",
            "paper_exit",
            "actual_enter",
            "actual_exit",
            "add",
            "reduce",
            "hold",
            "invalidate_thesis",
            "update_thesis",
            "resolved",
            "review",
        }
    ),
    "outcomes.status": frozenset(
        {
            "resolved_final",
            "resolved_provisional",
            "ambiguous",
            "disputed",
            "void",
            "cancelled",
        }
    ),
    "memory_nodes.node_type": frozenset({"observation", "reflection", "playbook_rule"}),
    "edges.edge_type_m1": frozenset({"about", "supports", "contradicts", "supersedes"}),
    "edges.edge_type_m3": frozenset(
        {"about", "supports", "contradicts", "supersedes", "derived_from", "violates", "follows"}
    ),
    "forecasts.scoring_state": frozenset({"pending", "scored", "failed", "superseded"}),
    "forecasts.scoring_support": frozenset({"supported", "unsupported"}),
    "forecast_scores.failure_reason": frozenset(
        {"yes_label_ambiguous", "label_mismatch", "outcome_superseded_mid_score", "scalar_value_invalid", "unsupported_kind"}
    ),
    "signals.severity": frozenset({"info", "warn", "critical"}),
    "error_codes": frozenset(
        {
            "VALIDATION_ERROR",
            "NOT_FOUND",
            "IDEMPOTENCY_CONFLICT",
            "UNSUPPORTED_CAPABILITY",
            "STORAGE_ERROR",
            "SCORING_UNSUPPORTED",
            "SCORING_NOT_READY",
            "INVARIANT_VIOLATION",
            "MARKET_NOT_RESOLVED",
            "MARKET_AMBIGUOUS",
        }
    ),
}

# Open enums (per operability.md §4.3): additive extensions are non-breaking.
OPEN_ENUMS: dict[str, frozenset[str]] = {
    "signals.kind": frozenset(
        {
            "calibration_drift",
            "override_outcome_negative",
            "override_outcome_positive",
            "stale_watch",
            "unscored_forecast",
            "sample_size_warning",
            "risk_data_missing",
        }
    ),
    "events.event_type": frozenset(
        {
            # M1 ledger entity creation events (trade-trace-vvt).
            "venue.created",
            "instrument.created",
            "snapshot.added",
            "thesis.created",
            "source.added",
            # M1 ledger lifecycle events.
            "decision.created",
            "outcome.recorded",
            "forecast.created",
            "forecast.scored",
            "forecast.anchored_to_snapshot",
            "forecast.superseded",
            "edge.created",
            "source.attached",
            # M3 memory + playbook + strategy + signal events.
            "playbook.proposed_version",
            "memory_node.retained",
            "memory_node.invalidated",
            "playbook_rule.followed",
            "playbook_rule.overridden",
            "strategy.created",
            "strategy.updated",
            "signal.emitted",
            # Importer bookkeeping.
            "import.row_committed",
        }
    ),
}


class MigrationPolicyError(RuntimeError):
    """Raised when a proposed migration violates the policy."""


@dataclass
class EnumChange:
    enum_key: str  # e.g. "decisions.type"
    added: frozenset[str]
    removed: frozenset[str]

    @property
    def is_additive_only(self) -> bool:
        return not self.removed


def check_enum_extension(
    enum_key: str,
    new_values: set[str] | frozenset[str],
) -> EnumChange:
    """Inspect a proposed change to a known enum and decide its breaking-ness.

    Returns an EnumChange describing the diff. Raises MigrationPolicyError if:
    - The enum is closed AND values were added without an accompanying
      contract version bump (the caller is responsible for setting the bump
      in the contract; this check is a hard reminder).
    - Any value was removed from a closed enum.

    For open enums, additive changes are always OK; removals raise because
    even open enums must not drop values silently.
    """

    new = frozenset(new_values)
    if enum_key in CLOSED_ENUMS:
        baseline = CLOSED_ENUMS[enum_key]
        added = new - baseline
        removed = baseline - new
        if removed:
            raise MigrationPolicyError(
                f"closed enum {enum_key!r}: cannot remove values {sorted(removed)} "
                f"without a major contract version bump and a one-version "
                f"deprecation window per operability.md §4.4"
            )
        if added:
            raise MigrationPolicyError(
                f"closed enum {enum_key!r}: adding values {sorted(added)} is a "
                f"breaking contract change requiring a contract version bump "
                f"per operability.md §4.3 (the constant in storage/policy.py "
                f"must be updated in the same patch as the contract bump)"
            )
        return EnumChange(enum_key=enum_key, added=frozenset(), removed=frozenset())

    if enum_key in OPEN_ENUMS:
        baseline = OPEN_ENUMS[enum_key]
        added = new - baseline
        removed = baseline - new
        if removed:
            raise MigrationPolicyError(
                f"open enum {enum_key!r}: removing values {sorted(removed)} is "
                f"not supported even on open enums; existing rows would lose "
                f"their CHECK constraint match"
            )
        # Additive extensions are allowed without a bump; we just acknowledge
        # the diff for caller introspection.
        return EnumChange(enum_key=enum_key, added=added, removed=frozenset())

    raise MigrationPolicyError(
        f"unknown enum {enum_key!r}; register it in storage/policy.py before "
        f"running a migration that depends on it"
    )


def check_no_reverse_migration(*, current_version: int, target_version: int) -> None:
    """Forward-only invariant per operability.md §4.2. Raises if the caller
    tries to step the schema_version backward."""

    if target_version < current_version:
        raise MigrationPolicyError(
            f"forward-only migrations: target_version={target_version} < "
            f"current_version={current_version}. Backups are the recovery "
            f"path for downgrades (operability.md §4.2 + §5)."
        )


def check_column_change(
    *,
    table: str,
    before: set[str],
    after: set[str],
    major_version_bump: bool = False,
) -> None:
    """Per operability.md §4.4 column lifecycle:

    - Adding a nullable column is non-breaking.
    - Adding a non-nullable column with a default is non-breaking (two-step).
    - Removing or renaming a column is breaking; requires
      `major_version_bump=True` (and the deprecation-window dance described
      in §4.4).

    Raises MigrationPolicyError when the change would silently break the
    contract.
    """

    added = after - before
    removed = before - after

    if removed and not major_version_bump:
        raise MigrationPolicyError(
            f"table {table!r}: removing columns {sorted(removed)} requires a "
            f"major contract version bump AND a one-version deprecation "
            f"window per operability.md §4.4. Pass major_version_bump=True "
            f"to acknowledge the bump."
        )

    # Adding columns is always allowed at the policy layer (the migration
    # script is responsible for NOT NULL handling per §4.4); just return.
    _ = added
