"""Shared model validation helpers."""

from __future__ import annotations

from datetime import datetime


def check_bitemporal(valid_from: datetime | None, valid_to: datetime | None) -> None:
    """Raise ``ValueError`` if a closed bi-temporal interval is inverted.

    ``valid_to`` is the half-open upper bound of ``[valid_from, valid_to)``; an
    equal pair is permitted (an empty/instantaneous interval) but a ``valid_to``
    strictly before ``valid_from`` is never valid.
    """

    if valid_from is not None and valid_to is not None and valid_to < valid_from:
        raise ValueError(
            f"bi-temporal validity violated: valid_to ({valid_to.isoformat()}) "
            f"precedes valid_from ({valid_from.isoformat()})"
        )
