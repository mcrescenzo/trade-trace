"""CSV fills import adapter per imports.md §4 (bead trade-trace-5qr).

A thin shim on top of the JSONL import path. The adapter:

1. Reads a CSV file + a JSON mapping file.
2. Applies the mapping per row to produce decision.add args.
3. Writes the canonical JSONL audit artifact under
   `$TRADE_TRACE_HOME/import/csv/<timestamp>/<source>.jsonl`.
4. Delegates the actual writes to `import.commit` against the
   generated JSONL — all schema enforcement lives there, the CSV
   shim never duplicates the dispatch path.

Idempotency: CSV rows lack a natural key, so the adapter derives
one as `sha1("{import_run_id}:{source_row_number}")[:32]`. Re-running
the same CSV with the same `import_run_id` is a clean replay.

No broker auto-inference: the mapping file is required. Trade Trace
never reaches out to a broker; the user authors the mapping.
"""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.storage.paths import resolve_home
from trade_trace.tools._helpers import now_iso, require
from trade_trace.tools.errors import ToolError
from trade_trace.tools.imports import _import_commit

# Per imports.md §4.1 — every row produces these fields after mapping.
_REQUIRED_FIELDS = (
    "executed_at",
    "side",
    "quantity",
    "price",
)
_OPTIONAL_FIELDS = (
    "fees", "slippage", "account_label", "strategy_id", "strategy_slug", "tags",
    "declared_risk_amount", "declared_risk_unit", "expected_edge",
    "expected_edge_after_costs", "cost_basis_estimate", "risk_reward_estimate",
)
_SUPPORTED_MAPPING_TARGETS = set(_REQUIRED_FIELDS) | set(_OPTIONAL_FIELDS) | {
    "instrument_id", "instrument_external_id",
}

# Aliases per imports.md §4.1: buy maps to long-increase, sell to
# long-decrease / short-increase per signed-quantity convention.
_SIDE_ALIASES = {"buy": "long", "sell": "long"}
_VALID_SIDES = {
    "long", "short", "yes", "no", "flat_neutral", "pairs_long_short",
}

# Credential-shaped target fields. Reject mappings that target any of
# these so a CSV column called "api_key" can't be smuggled into
# metadata_json (bead trade-trace-jky / 7j1l aligned policy).
_FORBIDDEN_MAPPING_TARGETS = {
    "api_key", "secret_key", "client_secret", "broker_token",
    "wallet_seed", "wallet_seed_phrase", "seed_phrase", "mnemonic",
    "private_key", "auth_token", "access_token", "refresh_token",
    "bearer_token", "password", "passphrase", "session_token",
    "signing" + "_key", "signing_secret", "trading_password",
}


def _apply_mapping_value(rule: Any, row: dict[str, str]) -> Any:
    """Translate one mapping rule against a CSV row.

    Returns the mapped value or `None` when the source column is
    missing/empty and no default applies. The caller decides
    whether `None` is required-field-missing or optional-skipped.
    """

    if isinstance(rule, str):
        return row.get(rule) or None
    if not isinstance(rule, dict):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"mapping rule must be a string or object; got {type(rule).__name__}",
            details={"rule": rule},
        )
    if "static" in rule:
        return rule["static"]
    column = rule.get("column")
    if not column:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "mapping object rule requires 'column' or 'static'",
            details={"rule": rule},
        )
    raw = row.get(column)
    if raw is None or raw == "":
        if "default" in rule:
            return rule["default"]
        return None
    if "values" in rule:
        values_map = rule["values"]
        if not isinstance(values_map, dict):
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                "mapping 'values' must be an object",
                details={"column": column, "rule": rule},
            )
        if raw not in values_map:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"value {raw!r} from column {column!r} is not in the "
                "mapping's 'values' dictionary",
                details={"column": column, "value": raw,
                         "allowed": sorted(values_map.keys())},
            )
        return values_map[raw]
    if "format" in rule:
        fmt = rule["format"]
        tz_name = rule.get("timezone")
        try:
            naive = datetime.strptime(raw, fmt)
        except ValueError as exc:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"value {raw!r} from column {column!r} does not match "
                f"format {fmt!r}: {exc}",
                details={"column": column, "value": raw, "format": fmt},
            ) from exc
        if tz_name:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(tz_name)
            except Exception as exc:  # pragma: no cover - bad tz
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    f"unknown timezone {tz_name!r}: {exc}",
                    details={"column": column, "timezone": tz_name},
                ) from exc
            aware = naive.replace(tzinfo=tz).astimezone(UTC)
        else:
            aware = naive.replace(tzinfo=UTC)
        return aware.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return raw


def _validate_mapping(mapping: dict[str, Any]) -> None:
    """Validate mapping shape and target fields.

    The CSV adapter is intentionally not a generic ETL surface: only fields
    understood by the downstream `decision.add` path (plus CSV-only metadata
    conveniences documented in imports.md) may be targeted.
    """

    for field in _REQUIRED_FIELDS:
        if field not in mapping:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"CSV mapping is missing required target {field!r}",
                details={"field": field, "required_fields": list(_REQUIRED_FIELDS)},
            )
    if "instrument_id" not in mapping and "instrument_external_id" not in mapping:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "CSV mapping must include instrument_id or instrument_external_id",
            details={"field": "instrument_id"},
        )

    for target in mapping:
        if target not in _SUPPORTED_MAPPING_TARGETS:
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"CSV mapping target {target!r} is not supported",
                details={"field": target, "supported_fields": sorted(_SUPPORTED_MAPPING_TARGETS)},
            )
        target_lower = target.lower()
        for forbidden in _FORBIDDEN_MAPPING_TARGETS:
            if forbidden in target_lower:
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    f"CSV mapping target {target!r} is credential-shaped; "
                    "the no-credentials policy forbids importing into this "
                    "field (PRD §2.8, bead trade-trace-jky)",
                    details={"field": target},
                )


def _derive_idempotency_key(run_id: str, row_no: int) -> str:
    digest = hashlib.sha1(
        f"{run_id}:{row_no}".encode(),
        usedforsecurity=False,
    ).hexdigest()
    return digest[:32]


def _row_to_decision_args(
    row: dict[str, str], mapping: dict[str, Any], *,
    row_no: int, run_id: str, source_file: str,
) -> dict[str, Any]:
    """Translate one CSV row + mapping into `decision.add` args."""

    mapped: dict[str, Any] = {}
    for target, rule in mapping.items():
        mapped[target] = _apply_mapping_value(rule, row)

    # Required-field check.
    for field in _REQUIRED_FIELDS:
        if mapped.get(field) in (None, ""):
            raise ToolError(
                ErrorCode.VALIDATION_ERROR,
                f"CSV row {row_no}: required field {field!r} is missing "
                "after mapping",
                details={"line": row_no, "file": source_file, "field": field},
            )
    if not (mapped.get("instrument_external_id") or mapped.get("instrument_id")):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"CSV row {row_no}: instrument_external_id or instrument_id "
            "is required after mapping",
            details={"line": row_no, "file": source_file,
                     "field": "instrument_external_id"},
        )

    raw_side = str(mapped["side"]).lower()
    side = _SIDE_ALIASES.get(raw_side, raw_side)
    if side not in _VALID_SIDES:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"CSV row {row_no}: side {raw_side!r} is not in the decisions.side "
            "enum (buy/sell aliases are accepted)",
            details={"line": row_no, "file": source_file,
                     "field": "side", "value": raw_side,
                     "allowed": sorted(_VALID_SIDES)},
        )

    instrument_id = mapped.get("instrument_id")
    if not instrument_id and mapped.get("instrument_external_id"):
        # The agent supplied an external id; the JSONL replay path
        # cannot resolve it server-side without a separate lookup.
        # For MVP we surface a clear error so the user provides
        # `instrument_id` (already-resolved) — the upstream tooling can
        # do the resolution in a follow-up bead.
        raise ToolError(
            ErrorCode.UNSUPPORTED_CAPABILITY,
            f"CSV row {row_no}: instrument_external_id resolution is "
            "deferred; the mapping must produce instrument_id directly "
            "(resolve the external id to a Trade Trace instrument id "
            "before mapping). Tracked under the P1 CSV import roadmap.",
            details={"line": row_no, "file": source_file,
                     "field": "instrument_external_id"},
        )

    # Determine decision type from quantity sign + side per signed-qty
    # convention. Positive cumulative qty = long exposure, negative =
    # short. For MVP, every fill is recorded as a `decision.add` add-row;
    # exit/position-event pairing can be layered later without changing the
    # JSONL adapter contract.
    try:
        quantity = float(mapped["quantity"])
        price = float(mapped["price"])
    except (TypeError, ValueError) as exc:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"CSV row {row_no}: quantity and price must be numeric",
            details={"line": row_no, "file": source_file},
        ) from exc

    args: dict[str, Any] = {
        "instrument_id": instrument_id,
        "type": "add",
        "side": side,
        "quantity": quantity,
        "price": price,
        "idempotency_key": _derive_idempotency_key(run_id, row_no),
    }
    if mapped.get("fees") is not None:
        args["fees"] = float(mapped["fees"])
    if mapped.get("slippage") is not None:
        args["slippage"] = float(mapped["slippage"])
    if mapped.get("strategy_id"):
        args["strategy_id"] = mapped["strategy_id"]
    if mapped.get("tags"):
        tags = mapped["tags"]
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        args["tags"] = tags
    for field in (
        "declared_risk_amount", "expected_edge", "expected_edge_after_costs",
        "cost_basis_estimate", "risk_reward_estimate",
    ):
        if mapped.get(field) is not None:
            try:
                args[field] = float(mapped[field])
            except (TypeError, ValueError) as exc:
                raise ToolError(
                    ErrorCode.VALIDATION_ERROR,
                    f"CSV row {row_no}: {field} must be numeric",
                    details={"line": row_no, "file": source_file, "field": field},
                ) from exc
    if mapped.get("declared_risk_unit"):
        args["declared_risk_unit"] = mapped["declared_risk_unit"]
    metadata: dict[str, Any] = {
        "import_run_id": run_id,
        "import_source": "csv_fills",
        "csv_row_number": row_no,
        "csv_source_file": source_file,
    }
    if mapped.get("account_label"):
        metadata["account_label"] = mapped["account_label"]
    if mapped.get("strategy_slug"):
        metadata["strategy_slug"] = mapped["strategy_slug"]
    metadata["executed_at"] = mapped["executed_at"]
    args["metadata_json"] = metadata
    return args


def _write_jsonl_artifact(
    home: Path, source_csv: Path, run_id: str,
    decision_args_list: list[dict[str, Any]],
) -> Path:
    """Write the canonical JSONL artifact under
    `$HOME/import/csv/<timestamp>/<source>.jsonl` per imports.md §4.3."""

    timestamp = run_id.replace(":", "-").replace(".", "-")[:32]
    target_dir = home / "import" / "csv" / timestamp
    target_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = target_dir / f"{source_csv.stem}.jsonl"
    with artifact_path.open("w", encoding="utf-8", newline="\n") as f:
        for args in decision_args_list:
            line = {"tool": "decision.add", "args": args}
            f.write(json.dumps(line, sort_keys=True, default=str) + "\n")
    return artifact_path


def _import_csv_fills(args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """`import.csv_fills` — MVP CSV import adapter per imports.md §4."""

    csv_path = Path(require(args, "csv_path"))
    mapping_path = Path(require(args, "mapping_path"))
    if not csv_path.exists():
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"CSV file not found: {csv_path}",
            details={"field": "csv_path", "path": str(csv_path)},
        )
    if not mapping_path.exists():
        raise ToolError(
            ErrorCode.NOT_FOUND,
            f"mapping file not found: {mapping_path}",
            details={"field": "mapping_path", "path": str(mapping_path)},
        )

    run_id = args.get("import_run_id") or now_iso()
    home = resolve_home(args.get("home"))

    try:
        mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"mapping file is not valid JSON: {exc}",
            details={"field": "mapping_path", "path": str(mapping_path)},
        ) from exc
    if not isinstance(mapping, dict):
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            "mapping file must contain a JSON object",
            details={"field": "mapping_path"},
        )
    _validate_mapping(mapping)

    decision_args_list: list[dict[str, Any]] = []
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row_no, row in enumerate(reader, start=1):
            decision_args_list.append(_row_to_decision_args(
                row, mapping, row_no=row_no, run_id=run_id,
                source_file=str(csv_path),
            ))

    artifact_path = _write_jsonl_artifact(
        home, csv_path, run_id, decision_args_list,
    )

    # Delegate to the JSONL import.commit path so all schema
    # enforcement happens there — the CSV shim stays thin.
    commit_args = {
        "path": str(artifact_path),
        "home": args.get("home"),
        "transaction_mode": args.get("transaction_mode", "single"),
    }
    commit_result = _import_commit(commit_args, ctx)
    return {
        "artifact_path": str(artifact_path),
        "import_run_id": run_id,
        "row_count": len(decision_args_list),
        "commit_result": commit_result,
    }


def register_csv_import(registry: ToolRegistry) -> None:
    from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    registry.register(
        "import.csv_fills",
        _import_csv_fills,
        description=(
            "Import per-fill executions from a CSV file using an "
            "explicit JSON mapping (imports.md §4). The adapter emits "
            "a JSONL audit artifact under "
            "$TRADE_TRACE_HOME/import/csv/<run_id>/<source>.jsonl and "
            "then delegates to import.commit. There is NO auto-inference "
            "of broker-specific schemas — the mapping file is required. "
            "Idempotency keys are derived as "
            "sha1('{run_id}:{row_no}')[:32]; re-running the same CSV "
            "with the same import_run_id is a clean replay."
        ),
        is_write=True,
        **_examples_for("import.csv_fills"),
    )
