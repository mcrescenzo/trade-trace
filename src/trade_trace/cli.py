"""CLI entrypoint for Trade Trace.

The CLI maps `subject.verb` MCP tool names to space-separated invocations
(`tt subject verb`). Tool args are passed via long flags (`--key value`).
Output is JSON on stdout by default; `--human` emits prose hints to stderr
without affecting stdout content. Exit code is 0 when `ok=true`, 1 otherwise.

This adapter is intentionally argparse-based — no third-party CLI dep is
required at M0 so the install path stays light. Typer/Click can land later
without changing the contract surface.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from typing import Any

from trade_trace.contracts.envelope import (
    Meta,
    dump_envelope,
    error_envelope,
)
from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import CLINameCollisionError, ToolRegistry
from trade_trace.core import default_registry, dispatch


class MalformedJsonArgError(Exception):
    """Per bead trade-trace-lum: invalid JSON in a `--*-json` argument
    was previously a SystemExit with raw stderr. The dispatcher now
    catches this and emits a typed VALIDATION_ERROR envelope on
    stdout so the agent caller can parse it like any other error."""

    def __init__(self, flag: str, value: str, decode_error: str) -> None:
        self.flag = flag
        self.value = value
        self.decode_error = decode_error
        super().__init__(
            f"--{flag} value is not valid JSON: {decode_error}"
        )


class StrayPositionalArgsError(Exception):
    """Raised by `_parse_kv_args` when the remaining argv after command
    resolution still contains positional tokens. Per bead
    trade-trace-r5k / DEBT-007 the dispatcher converts this to a typed
    VALIDATION_ERROR envelope rather than silently dropping the tokens
    (which previously made malformed CLI calls look successful)."""

    def __init__(self, stray: list[str]) -> None:
        self.stray = stray
        super().__init__(
            f"unrecognized positional argument(s) after command: {stray!r}; "
            "use `--key value` (or `--flag`) for every option"
        )


def _parse_kv_args(unknown: list[str]) -> dict[str, Any]:
    """Parse `--key value` pairs into a dict per docs/architecture/contracts.md §2.1.

    - `--flag` (no value) → True.
    - `--key-with-dashes` → `key_with_dashes`.
    - `--foo-json '<json>'` parses the JSON and assigns to `foo` (without the
      `_json` suffix; the suffix is the transport hint, not the domain key).
    - Repeated `--key v1 --key v2 …` accumulates into `[v1, v2, …]`
      per trade-trace-pybt; the same coercion (true/false/int/float)
      runs on each value independently.

    Stray positional tokens (anything that isn't consumed as the value
    of a `--key`) raise `StrayPositionalArgsError` so the dispatcher
    can surface a typed envelope (bead trade-trace-r5k).
    """

    def _coerce_scalar(text: str) -> Any:
        if text.lower() in {"true", "false"}:
            return text.lower() == "true"
        try:
            return int(text)
        except ValueError:
            pass
        try:
            return float(text)
        except ValueError:
            return text

    out: dict[str, Any] = {}
    stray: list[str] = []
    i = 0
    while i < len(unknown):
        token = unknown[i]
        if not token.startswith("--"):
            stray.append(token)
            i += 1
            continue
        key = token[2:].replace("-", "_")
        is_json = key.endswith("_json")
        domain_key = key[: -len("_json")] if is_json else key
        # peek
        if i + 1 < len(unknown) and not unknown[i + 1].startswith("--"):
            raw_value = unknown[i + 1]
            if is_json:
                try:
                    value: Any = json.loads(raw_value)
                except json.JSONDecodeError as exc:
                    # Per bead trade-trace-lum: surface a typed envelope
                    # in main() instead of a raw SystemExit so agent
                    # callers can parse the failure like any other.
                    raise MalformedJsonArgError(
                        token[2:], raw_value, str(exc),
                    ) from exc
            else:
                value = _coerce_scalar(raw_value)
            i += 2
        else:
            value = True
            i += 1
        # Accumulate repeated flags into a list (trade-trace-pybt).
        if domain_key in out:
            existing = out[domain_key]
            if isinstance(existing, list):
                existing.append(value)
            else:
                out[domain_key] = [existing, value]
        else:
            out[domain_key] = value
    if stray:
        raise StrayPositionalArgsError(stray)
    return out


def _invocation_from_args(
    tokens: list[str], registry: ToolRegistry
) -> tuple[str, list[str]]:
    """Walk positional tokens until they no longer extend a registered CLI invocation.
    Returns (canonical_tool_name, remaining_argv)."""

    longest: tuple[str, ...] = ()
    for candidate in registry.cli_invocations():
        if tuple(tokens[: len(candidate)]) == candidate and len(candidate) > len(longest):
            longest = candidate
    if not longest:
        raise SystemExit(
            f"unknown command: {' '.join(tokens) or '<no command>'}\n"
            f"available commands: {', '.join(' '.join(c) for c in registry.cli_invocations())}"
        )
    return ".".join(longest), tokens[len(longest):]


def _emit_cli_error(
    *,
    tool: str,
    actor_id: str,
    request_id: str | None,
    code: ErrorCode,
    message: str,
    details: dict[str, Any],
) -> int:
    """Build the typed error envelope a CLI-side validation failure emits,
    print it to stdout in canonical sorted-keys JSON, and return the exit
    code mapped from `code`. Centralizes the previously-duplicated startup,
    JSON-arg, and stray-positional error paths per bead trade-trace-hd2r
    (SIMP-001)."""

    import uuid as _uuid
    meta = Meta(
        tool=tool,
        actor_id=actor_id,
        request_id=request_id or _uuid.uuid4().hex,
    )
    env = error_envelope(meta, code, message, details)
    print(json.dumps(env.model_dump(mode="json", exclude_none=True), sort_keys=True))
    if code == ErrorCode.VALIDATION_ERROR:
        return 2
    if code == ErrorCode.INVARIANT_VIOLATION:
        return 3
    return 1



def main(argv: list[str] | None = None, *, registry: ToolRegistry | None = None) -> int:
    """`tt` entrypoint. Returns the process exit code."""

    parser = argparse.ArgumentParser(
        prog="tt",
        description="Trade Trace CLI — agent-native journal, memory, and calibration substrate.",
        add_help=True,
    )
    parser.add_argument("--human", action="store_true", help="emit a one-line prose hint to stderr")
    parser.add_argument(
        "--actor-id",
        default="cli:default",
        help='actor identity for the call (default "cli:default")',
    )
    parser.add_argument(
        "--request-id",
        default=None,
        help="override the server-generated request_id",
    )
    parser.add_argument(
        "--allow-no-idempotency",
        action="store_true",
        help=(
            "opt into at-least-once semantics for retryable writes; the server "
            "skips idempotency_key validation and sets meta.idempotency_disabled=true"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "validate input and compute the would-be event payload + would-be "
            "IDs without writing anything; sets meta.dry_run=true (bead trade-trace-268)"
        ),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "required by mutating admin tools (journal.restore, "
            "journal.backup, journal.repair, journal.config_set) — without "
            "it the tool returns meta.preview_only=true (bead trade-trace-2z7)"
        ),
    )

    args, positional = parser.parse_known_args(argv)

    # Build (and validate) the registry FIRST, regardless of subcommand —
    # b4a requires that the collision check fires on every `tt --help` and
    # `tt --version` invocation too, not only on actual tool calls. The
    # registry build is fast (no I/O, no network).
    try:
        if registry is None:
            registry = default_registry()
    except CLINameCollisionError as exc:
        return _emit_cli_error(
            tool="<startup>",
            actor_id=args.actor_id,
            request_id=args.request_id,
            code=ErrorCode.STORAGE_ERROR,
            message=str(exc),
            details={
                "reason": "cli_name_collision",
                "conflict_kind": exc.conflict_kind,
                "colliding": exc.suggested_renames,
            },
        )

    if not positional:
        parser.print_help(sys.stderr)
        return 2

    tool_name, remaining = _invocation_from_args(positional, registry)
    try:
        tool_args = _parse_kv_args(remaining)
    except MalformedJsonArgError as exc:
        return _emit_cli_error(
            tool=tool_name,
            actor_id=args.actor_id,
            request_id=args.request_id,
            code=ErrorCode.VALIDATION_ERROR,
            message=str(exc),
            details={
                "field": exc.flag,
                "reason": "invalid_json",
                "decode_error": exc.decode_error,
                "tool": tool_name,
            },
        )
    except StrayPositionalArgsError as exc:
        # Per bead trade-trace-r5k / DEBT-007: surface a typed envelope
        # (exit 2) instead of silently dropping stray positional tokens.
        # CLI parity with MCP requires the JSON-envelope shape.
        return _emit_cli_error(
            tool=tool_name,
            actor_id=args.actor_id,
            request_id=args.request_id,
            code=ErrorCode.VALIDATION_ERROR,
            message=str(exc),
            details={
                "field": "argv",
                "stray_positional_args": exc.stray,
                "tool": tool_name,
            },
        )
    if args.allow_no_idempotency:
        # MCP-side convention is the underscore-prefixed key; the CLI sets
        # the same key so the dispatcher path is identical between transports.
        tool_args["_allow_no_idempotency"] = True
    if args.dry_run:
        tool_args["_dry_run"] = True
    if args.confirm:
        tool_args["confirm"] = True
        tool_args["_confirm"] = True
    if (
        tool_name == "journal.config_set"
        and tool_args.get("key") == "embeddings.provider"
        and tool_args.get("value") == "api:openai"
        and tool_args.get("_confirm")
        and not tool_args.get("api_key")
    ):
        print(
            "Warning: api:openai embeddings may send memory text to OpenAI. "
            "The API key will be stored only in the OS keyring.",
            file=sys.stderr,
        )
        tool_args["api_key"] = getpass.getpass("OpenAI API key: ")

    envelope = dispatch(
        tool_name,
        tool_args,
        actor_id=args.actor_id,
        request_id=args.request_id,
        registry=registry,
    )

    # CLI transport contract: set cli_human_hint on success when --human is
    # requested, and ensure the field is present (null) on report.* envelopes
    # so agents see a stable shape. mcp_transport_hints stays null on CLI.
    if envelope.ok and args.human:
        envelope.meta.cli_human_hint = (
            f"ok: {tool_name} (request_id={envelope.meta.request_id})"
        )

    body = dump_envelope(envelope)

    # NDJSON streaming for list tools per contracts.md §1.2 / trade-trace-5tf.
    # Detection: success envelope whose `data.items` is a list. We emit one
    # envelope per item plus a final summary envelope; on error we fall
    # back to a single envelope line.
    if body.get("ok") and isinstance(body.get("data"), dict) and isinstance(
        body["data"].get("items"), list
    ):
        items = body["data"]["items"]
        for item in items:
            line_envelope = {
                "ok": True,
                "data": item,
                "meta": {
                    **body["meta"],
                    "tool": body["meta"]["tool"],
                },
            }
            print(json.dumps(line_envelope, sort_keys=True))
        # Final summary line: empty data with the aggregate metadata.
        summary = {
            "ok": True,
            "data": {
                "items": [],
                "count": body["data"].get("count", len(items)),
                "truncated": body["data"].get("truncated", False),
            },
            "meta": body["meta"],
        }
        if body["data"].get("next_cursor"):
            summary["meta"]["next_cursor"] = body["data"]["next_cursor"]
        if body["data"].get("truncated"):
            summary["meta"]["truncated"] = True
        print(json.dumps(summary, sort_keys=True))
    else:
        print(json.dumps(body, sort_keys=True))

    if args.human and body.get("ok"):
        hint = (
            f"ok: {tool_name} (request_id={body['meta']['request_id']})"
        )
        print(hint, file=sys.stderr)
    elif args.human:
        err = body.get("error", {})
        print(
            f"error[{err.get('code', '?')}]: {err.get('message', '')}",
            file=sys.stderr,
        )

    # Exit code mapping per trade-trace-5tf:
    # 0 on success; 2 on VALIDATION_ERROR; 3 on INVARIANT_VIOLATION;
    # 1 for every other error class (transport/storage/not_found/etc.).
    if body.get("ok"):
        return 0
    err_code = body.get("error", {}).get("code")
    if err_code == "VALIDATION_ERROR":
        return 2
    if err_code == "INVARIANT_VIOLATION":
        return 3
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
