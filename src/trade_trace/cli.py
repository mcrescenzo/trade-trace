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


class UnknownCommandError(Exception):
    """Raised by `_invocation_from_args` when positional tokens do not
    extend any registered CLI invocation. Per trade-trace-kynj the
    dispatcher converts this to a typed `NOT_FOUND` envelope rather
    than a raw `SystemExit` with stderr text — agent callers can then
    parse failures the same way for any tool surface."""

    def __init__(self, tokens: list[str], known: list[tuple[str, ...]]) -> None:
        self.tokens = list(tokens)
        self.known = sorted(" ".join(c) for c in known)
        super().__init__(
            f"unknown command: {' '.join(tokens) or '<no command>'}"
        )


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
        raise UnknownCommandError(tokens, registry.cli_invocations())
    return ".".join(longest), tokens[len(longest):]


def _schema_arg_lines(tool_name: str, registry: ToolRegistry) -> list[str]:
    """Render schema properties as CLI flags for command-specific help."""

    reg = registry.get(tool_name)
    schema = reg.json_schema or {}
    properties = schema.get("properties") or {}
    required = set(schema.get("required") or [])
    lines: list[str] = []
    for name in sorted(properties, key=lambda n: (n not in required, n)):
        # Underscore-prefixed fields are transport/control inputs injected by
        # global CLI options (for example `_confirm` from `--confirm`). They are
        # not user-facing schema flags; rendering them would produce confusing
        # triple-dash spellings such as `---confirm` in command help.
        if name.startswith("_"):
            continue
        prop = properties.get(name) or {}
        flag = "--" + name.replace("_", "-")
        kind = prop.get("type") or "value"
        if isinstance(kind, list):
            kind = "|".join(str(k) for k in kind)
        marker = "required" if name in required else "optional"
        description = prop.get("description") or ""
        enum = prop.get("enum")
        if enum:
            description = (description + " " if description else "") + "one of: " + ", ".join(map(str, enum))
        lines.append(f"  {flag} <{kind}>  {marker}" + (f"; {description}" if description else ""))
    return lines


def _print_command_help(parser: argparse.ArgumentParser, tool_name: str, registry: ToolRegistry) -> None:
    """Print global argparse help plus schema-derived flags for one tool."""

    reg = registry.get(tool_name)
    invocation = " ".join(reg.cli_invocation)
    print(f"usage: tt [global options] {invocation} [tool options]", file=sys.stdout)
    print("", file=sys.stdout)
    print(f"Tool: {tool_name}", file=sys.stdout)
    if reg.description:
        print(reg.description, file=sys.stdout)
        print("", file=sys.stdout)
    metadata = reg.metadata()
    if metadata:
        if metadata.get("usage_summary"):
            print("usage summary:", file=sys.stdout)
            print(f"  {metadata['usage_summary']}", file=sys.stdout)
        if metadata.get("examples"):
            print("examples:", file=sys.stdout)
            for example in metadata["examples"]:
                print(f"  {example}", file=sys.stdout)
        if metadata.get("enum_notes"):
            print("enum notes:", file=sys.stdout)
            for key, value in metadata["enum_notes"].items():
                print(f"  {key}: {value}", file=sys.stdout)
        if metadata.get("common_failures"):
            print("common failures:", file=sys.stdout)
            for failure in metadata["common_failures"]:
                print(f"  - {failure}", file=sys.stdout)
        if metadata.get("next_actions"):
            print("next actions:", file=sys.stdout)
            for action in metadata["next_actions"]:
                print(f"  - {action}", file=sys.stdout)
        print("", file=sys.stdout)
    print("global options:", file=sys.stdout)
    for action in parser._actions:
        if not action.option_strings:
            continue
        opts = ", ".join(action.option_strings)
        print(f"  {opts}  {action.help or ''}", file=sys.stdout)
    print("", file=sys.stdout)
    print("tool options from schema:", file=sys.stdout)
    lines = _schema_arg_lines(tool_name, registry)
    if lines:
        for line in lines:
            print(line, file=sys.stdout)
    else:
        print("  (no schema-advertised arguments)", file=sys.stdout)
    print("", file=sys.stdout)
    print(
        "JSON convention: for object/array values, pass JSON with the schema field flag "
        "(for example --metadata-json '{...}' or --tags '[...]'). Repeating a flag "
        "accumulates values into a list.",
        file=sys.stdout,
    )


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
        add_help=False,
    )
    parser.add_argument("-h", "--help", action="store_true", help="show this help message and exit")
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
            "journal.backup, journal.repair, journal.config_set, "
            "keyring.revoke) — without it the tool returns "
            "meta.preview_only=true (bead trade-trace-2z7)"
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
        return 0 if args.help else 2

    try:
        tool_name, remaining = _invocation_from_args(positional, registry)
    except UnknownCommandError as exc:
        # Emit a typed NOT_FOUND envelope per trade-trace-kynj instead
        # of the legacy SystemExit-with-stderr. CLI/MCP parity contract.
        return _emit_cli_error(
            tool="<unknown>",
            actor_id=args.actor_id,
            request_id=args.request_id,
            code=ErrorCode.NOT_FOUND,
            message=str(exc),
            details={
                "entity_kind": "tool",
                "tokens": exc.tokens,
                "known_invocations": exc.known,
                "next_actions": [
                    "Run `tt --help` for global options.",
                    "Run `tt tool schema --tool <tool.name>` to inspect a tool contract.",
                    "Use space-separated CLI invocations such as `tt decision add` for tool name `decision.add`.",
                ],
            },
        )
    if args.help:
        _print_command_help(parser, tool_name, registry)
        return 0
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
