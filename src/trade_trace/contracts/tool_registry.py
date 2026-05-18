"""Tool registry + CLI invocation mapping per contracts.md §2.1.

The registry stores `subject.verb` MCP-style tool names. CLI invocations are
derived by replacing each `.` with a single space. Collisions are detected at
registration time (every process start) and surface as a fatal STORAGE_ERROR
with `details.reason = "cli_name_collision"`. The CI gate
(tests/contracts/test_cli_name_uniqueness.py) is the primary line of defense;
the runtime check is defense in depth.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class CLINameCollisionError(RuntimeError):
    """Raised when two tool names map to the same CLI invocation.

    Carries structured detail per b4a acceptance criteria: each colliding pair
    is `{tool_a, tool_b, conflict_kind, suggested_rename}`. `conflict_kind` is
    one of `"duplicate_invocation"` (two MCP names whose `subject.verb` split
    yields the same CLI tokens) or `"duplicate_name"` (the same name registered
    twice). `suggested_rename` is a deterministic disambiguation hint the
    operator can copy verbatim.
    """

    def __init__(
        self,
        colliding: list[tuple[str, str]],
        *,
        conflict_kind: str = "duplicate_invocation",
    ) -> None:
        self.colliding = colliding
        self.conflict_kind = conflict_kind
        self.suggested_renames: list[dict[str, str]] = []
        for a, b in colliding:
            # Suggest renaming the second tool by appending `_alt` to its verb;
            # operators can override but they get a clean default.
            rename = f"{b.rsplit('.', 1)[0]}.{b.rsplit('.', 1)[1]}_alt" if "." in b else f"{b}_alt"
            self.suggested_renames.append(
                {
                    "tool_a": a,
                    "tool_b": b,
                    "conflict_kind": conflict_kind,
                    "suggested_rename": rename,
                }
            )
        names = ", ".join(f"{a!r} vs {b!r}" for a, b in colliding)
        super().__init__(
            f"CLI invocation collision detected ({conflict_kind}): {names}. "
            "Two MCP tool names must not map to the same `tt` invocation."
        )


def cli_invocation_for(tool_name: str) -> tuple[str, ...]:
    """Map an MCP tool name (`subject.verb`) to the tuple of CLI tokens after `tt`.

    `decision.add` -> `("decision", "add")`
    `report.filter_schema` -> `("report", "filter_schema")`
    """

    if not tool_name:
        raise ValueError("tool_name must be a non-empty string")
    return tuple(tool_name.split("."))


ToolHandler = Callable[[dict[str, Any], "ToolContext"], dict[str, Any]]


@dataclass
class ToolContext:
    """The per-call context handed to a tool handler. Both transports build
    the same context shape; the handler does not know whether it was invoked
    via CLI or MCP.

    `meta_hints` is a write-back surface for handlers that need to populate
    envelope `meta.*` fields (per contracts.md §3.2). The dispatcher merges
    hints onto `Meta` after the handler returns. Standard hint keys:
    `event_id`, `idempotent_replay`, `bin_policy`, `sample_warning`,
    `truncated`, `next_cursor`, `cli_human_hint`, `mcp_transport_hints`.
    """

    tool: str
    actor_id: str
    request_id: str
    raw_args: dict[str, Any]
    meta_hints: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolRegistration:
    name: str
    cli_invocation: tuple[str, ...]
    handler: ToolHandler
    description: str = ""
    is_write: bool = False
    example_minimal: dict[str, Any] | None = None
    example_rich: dict[str, Any] | None = None
    json_schema: dict[str, Any] | None = None


@dataclass
class ToolRegistry:
    """Holds the canonical tool table. Detects CLI collisions at registration
    time. The same registry instance is shared by the CLI and MCP adapters
    so registration is verified exactly once per process startup."""

    by_name: dict[str, ToolRegistration] = field(default_factory=dict)
    by_cli: dict[tuple[str, ...], str] = field(default_factory=dict)

    def register(
        self,
        name: str,
        handler: ToolHandler,
        *,
        description: str = "",
        is_write: bool = False,
        example_minimal: dict[str, Any] | None = None,
        example_rich: dict[str, Any] | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> None:
        if name in self.by_name:
            raise CLINameCollisionError(
                [(name, name)],
                conflict_kind="duplicate_name",
            )
        invocation = cli_invocation_for(name)
        prior = self.by_cli.get(invocation)
        if prior is not None and prior != name:
            raise CLINameCollisionError([(prior, name)])
        self.by_name[name] = ToolRegistration(
            name=name,
            cli_invocation=invocation,
            handler=handler,
            description=description,
            is_write=is_write,
            example_minimal=example_minimal,
            example_rich=example_rich,
            json_schema=json_schema,
        )
        self.by_cli[invocation] = name

    def get(self, name: str) -> ToolRegistration:
        return self.by_name[name]

    def names(self) -> list[str]:
        return sorted(self.by_name)

    def cli_invocations(self) -> list[tuple[str, ...]]:
        return sorted(self.by_cli)

    def validate(self) -> None:
        """Re-validates the entire registry. Called at process startup as
        defense in depth; the CI gate is the primary line."""

        seen: dict[tuple[str, ...], str] = {}
        collisions: list[tuple[str, str]] = []
        for reg in self.by_name.values():
            prior = seen.get(reg.cli_invocation)
            if prior is not None and prior != reg.name:
                collisions.append((prior, reg.name))
            else:
                seen[reg.cli_invocation] = reg.name
        if collisions:
            raise CLINameCollisionError(collisions)
