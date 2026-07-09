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
from dataclasses import dataclass, field, replace
from typing import Any

import jsonschema

from trade_trace.contracts.json_schema_derive import derive_schema


def _compile_validator(schema: dict[str, Any] | None) -> Any | None:
    """Build a draft-specific jsonschema validator instance for ``schema``.

    Built once at registration time so per-dispatch validation skips the
    ``jsonschema.validate`` overhead of re-detecting the draft, re-checking the
    schema, and re-instantiating a validator (see trade-trace-u5l3). Returns
    ``None`` when there is no schema to validate against.
    """

    if schema is None:
        return None
    cls = jsonschema.validators.validator_for(schema)
    return cls(schema)


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
    `report.calibration` -> `("report", "calibration")`
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
    hints onto `Meta` after the handler returns. Standard hint keys land on
    typed fields: `event_id`, `idempotent_replay`, `bin_policy`,
    `sample_warning`, `truncated`, `next_cursor`, `cli_human_hint`,
    `mcp_transport_hints`.

    Per bead trade-trace-30u: any non-standard hint key is also propagated
    to the envelope's `meta` dict via Meta's `extra='allow'` config. This
    gives future tools and providers an extensible metadata channel
    without requiring a Meta schema change. The previous behavior of
    silently dropping unknown keys is gone.
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
    display_minimal: dict[str, Any] | None = None
    json_schema: dict[str, Any] | None = None
    compiled_validator: Any | None = None
    usage_summary: str = ""
    examples: list[str] = field(default_factory=list)
    enum_notes: dict[str, str] = field(default_factory=dict)
    common_failures: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    catalog_visibility: str = "public"
    is_admin: bool = False
    legacy_name: str | None = None
    renamed_to: str | None = None
    removed_in: str | None = None
    redirect: str | None = None

    def metadata(self) -> dict[str, Any]:
        """Self-describing metadata shared by CLI help, tool.schema, and MCP."""

        out: dict[str, Any] = {
            "catalog_visibility": self.catalog_visibility,
        }
        if self.is_admin:
            out["is_admin"] = True
        if self.legacy_name:
            out["legacy_name"] = self.legacy_name
        if self.renamed_to:
            out["renamed_to"] = self.renamed_to
        if self.removed_in:
            out["removed_in"] = self.removed_in
        if self.redirect is not None:
            out["redirect"] = self.redirect
        if self.usage_summary:
            out["usage_summary"] = self.usage_summary
        if self.examples:
            out["examples"] = list(self.examples)
        if self.enum_notes:
            out["enum_notes"] = dict(self.enum_notes)
        if self.common_failures:
            out["common_failures"] = list(self.common_failures)
        if self.next_actions:
            out["next_actions"] = list(self.next_actions)
        return out

    def display_example_minimal(self) -> dict[str, Any] | None:
        """The minimal example surfaced to agents via ``tool.schema``.

        Decoupled from ``example_minimal`` (the schema-derivation source)
        per bead trade-trace-mpsu: a tool may advertise a full
        ``example_minimal`` so the derived ``json_schema`` keeps every
        accepted property, while showing a trimmed ``display_minimal``
        (required + a couple of core fields) so the example does not bury
        the handful of actually-required fields. When no ``display_minimal``
        is registered, the displayed example falls back to
        ``example_minimal``.
        """

        if self.display_minimal is not None:
            return self.display_minimal
        return self.example_minimal


@dataclass
class ToolRegistry:
    """Holds the canonical tool table. Detects CLI collisions at registration
    time. The same registry instance is shared by the CLI and MCP adapters
    so registration is verified exactly once per process startup."""

    by_name: dict[str, ToolRegistration] = field(default_factory=dict)
    by_cli: dict[tuple[str, ...], str] = field(default_factory=dict)
    # Cache of `sorted(self.by_name)`. `names()` is called on every
    # NOT_FOUND error and known-tools build (journal.py:326), but the
    # tool table is frozen after process-startup registration. Rebuilt
    # only by the three methods that mutate `by_name`: register(),
    # alias() (via register()), and mark() (trade-trace-ukwy).
    _sorted_names: list[str] | None = field(default=None, repr=False)

    def register(
        self,
        name: str,
        handler: ToolHandler,
        *,
        description: str = "",
        is_write: bool = False,
        example_minimal: dict[str, Any] | None = None,
        example_rich: dict[str, Any] | None = None,
        display_minimal: dict[str, Any] | None = None,
        json_schema: dict[str, Any] | None = None,
        optional_keys: tuple[str, ...] | list[str] | None = None,
        usage_summary: str = "",
        examples: list[str] | tuple[str, ...] | None = None,
        enum_notes: dict[str, str] | None = None,
        common_failures: list[str] | tuple[str, ...] | None = None,
        next_actions: list[str] | tuple[str, ...] | None = None,
        catalog_visibility: str = "public",
        is_admin: bool = False,
        legacy_name: str | None = None,
        renamed_to: str | None = None,
        removed_in: str | None = None,
        redirect: str | None = None,
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
        effective_json_schema = (
            json_schema if json_schema is not None
            else derive_schema(example_minimal, optional_keys=optional_keys)
            if example_minimal is not None
            else None
        )
        self.by_name[name] = ToolRegistration(
            name=name,
            cli_invocation=invocation,
            handler=handler,
            description=description,
            is_write=is_write,
            example_minimal=example_minimal,
            example_rich=example_rich,
            display_minimal=display_minimal,
            json_schema=effective_json_schema,
            compiled_validator=_compile_validator(effective_json_schema),
            usage_summary=usage_summary,
            examples=list(examples or ()),
            enum_notes=dict(enum_notes or {}),
            common_failures=list(common_failures or ()),
            next_actions=list(next_actions or ()),
            catalog_visibility=catalog_visibility,
            is_admin=is_admin,
            legacy_name=legacy_name,
            renamed_to=renamed_to,
            removed_in=removed_in,
            redirect=redirect,
        )
        self.by_cli[invocation] = name
        self._sorted_names = None

    def get(self, name: str) -> ToolRegistration:
        return self.by_name[name]

    def names(self) -> list[str]:
        if self._sorted_names is None:
            self._sorted_names = sorted(self.by_name)
        return self._sorted_names

    def cli_invocations(self) -> list[tuple[str, ...]]:
        return sorted(self.by_cli)

    def public_names(
        self,
        *,
        include_admin: bool = False,
        include_legacy: bool = False,
        include_experimental: bool = False,
    ) -> list[str]:
        """Return tool names visible in the default v0.0.2 catalog.

        `experimental` is a distinct opt-in tier from `legacy`: it stays hidden
        unless `include_experimental` is set, and `include_legacy` does not
        surface it. Every other non-public visibility rides with `legacy`.
        """

        out: list[str] = []
        for name, reg in self.by_name.items():
            vis = reg.catalog_visibility
            if vis == "experimental":
                if not include_experimental:
                    continue
            elif vis != "public" and not include_legacy:
                continue
            if not include_admin and reg.is_admin:
                continue
            out.append(name)
        return sorted(out)

    def public_registrations(
        self,
        *,
        include_admin: bool = False,
        include_legacy: bool = False,
        include_experimental: bool = False,
    ) -> list[ToolRegistration]:
        return [self.by_name[name] for name in self.public_names(
            include_admin=include_admin,
            include_legacy=include_legacy,
            include_experimental=include_experimental,
        )]

    def mark(
        self,
        name: str,
        *,
        catalog_visibility: str | None = None,
        is_admin: bool | None = None,
        legacy_name: str | None = None,
        renamed_to: str | None = None,
        removed_in: str | None = None,
        redirect: str | None = None,
    ) -> None:
        """Update catalog metadata for an already-registered tool."""

        reg = self.by_name[name]
        self.by_name[name] = replace(
            reg,
            catalog_visibility=(catalog_visibility if catalog_visibility is not None else reg.catalog_visibility),
            is_admin=(is_admin if is_admin is not None else reg.is_admin),
            legacy_name=(legacy_name if legacy_name is not None else reg.legacy_name),
            renamed_to=(renamed_to if renamed_to is not None else reg.renamed_to),
            removed_in=(removed_in if removed_in is not None else reg.removed_in),
            redirect=(redirect if redirect is not None else reg.redirect),
        )
        # mark() never adds/removes a key, so the sorted-name set is
        # unchanged today; invalidate anyway so the cache stays correct if
        # mark() ever rekeys an entry (trade-trace-ukwy).
        self._sorted_names = None

    def alias(
        self,
        new_name: str,
        existing_name: str,
        *,
        legacy_name: str | None = None,
        description: str | None = None,
        catalog_visibility: str = "public",
        is_admin: bool | None = None,
        example_minimal: dict[str, Any] | None = None,
        example_rich: dict[str, Any] | None = None,
        display_minimal: dict[str, Any] | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> None:
        """Register a new public name backed by an existing handler."""

        existing = self.by_name[existing_name]
        self.register(
            new_name,
            existing.handler,
            description=description if description is not None else existing.description,
            is_write=existing.is_write,
            example_minimal=example_minimal if example_minimal is not None else existing.example_minimal,
            example_rich=example_rich if example_rich is not None else existing.example_rich,
            display_minimal=display_minimal if display_minimal is not None else existing.display_minimal,
            json_schema=json_schema if json_schema is not None else existing.json_schema,
            usage_summary=existing.usage_summary,
            examples=existing.examples,
            enum_notes=existing.enum_notes,
            common_failures=existing.common_failures,
            next_actions=existing.next_actions,
            catalog_visibility=catalog_visibility,
            is_admin=existing.is_admin if is_admin is None else is_admin,
            legacy_name=legacy_name,
        )

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
