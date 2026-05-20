"""Derive minimal JSON Schema input objects from example payloads.

The derived schemas are intentionally conservative: example keys describe the
accepted property shapes, while only top-level non-transport keys are marked
required. Transport/control affordances such as ``_dry_run`` remain optional.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from trade_trace.contracts.report_filter import ReportFilter

_TRANSPORT_CONTROL_KEYS = frozenset(
    {
        "_dry_run",
        "_confirm",
        "_allow_no_idempotency",
    }
)


def derive_schema(
    example: dict[str, Any],
    *,
    optional_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return a JSON Schema dict inferred from an example tool payload.

    Inference rules are intentionally simple and deterministic:
    - str -> string, bool -> boolean, int -> integer, float -> number
      (bool is checked before int because bool subclasses int in Python)
    - list -> array with items inferred from the first item, or unconstrained
      items for an empty list
    - dict -> object with recursively inferred properties
    - a top-level ``filter`` object uses the canonical ReportFilter schema
    - top-level non-transport keys are required; nested example object keys are
      descriptive properties but are not forced into nested ``required`` lists

    ``optional_keys``: top-level example keys whose runtime handler has a
    default and therefore must not be advertised as required. They remain
    in ``properties`` so agents can still discover the knob (per beads
    trade-trace-4zbk).
    """

    if not isinstance(example, dict):
        raise TypeError("derive_schema expects a dict example payload")

    optional_set = frozenset(optional_keys or ())
    schema = _schema_for_value(example, top_level=True, optional_keys=optional_set)
    schema.setdefault("description", "Auto-derived from example_minimal payload.")
    return schema


def _schema_for_value(
    value: Any,
    *,
    top_level: bool = False,
    optional_keys: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if value is None:
        return {"type": "null"}
    if isinstance(value, list):
        return {
            "type": "array",
            "items": _schema_for_value(value[0]) if value else {},
        }
    if isinstance(value, dict):
        properties: dict[str, Any] = {}
        for key, child in value.items():
            if top_level and key == "filter" and isinstance(child, dict):
                properties[key] = ReportFilter.model_json_schema(mode="validation")
            else:
                properties[key] = _schema_for_value(child)

        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if top_level:
            required = [
                key
                for key in value
                if key not in _TRANSPORT_CONTROL_KEYS and key not in optional_keys
            ]
            if required:
                schema["required"] = required
            optional_controls = sorted(key for key in value if key in _TRANSPORT_CONTROL_KEYS)
            optional_runtime = sorted(key for key in value if key in optional_keys)
            description_parts: list[str] = []
            if optional_controls:
                description_parts.append(
                    "Transport/control keys are optional and not required: "
                    f"{', '.join(optional_controls)}."
                )
            if optional_runtime:
                description_parts.append(
                    "Runtime-defaulted keys are optional: "
                    f"{', '.join(optional_runtime)}."
                )
            if description_parts:
                schema["description"] = (
                    "Auto-derived from example_minimal payload. "
                    + " ".join(description_parts)
                )
        return schema
    return {}


__all__ = ["derive_schema"]
