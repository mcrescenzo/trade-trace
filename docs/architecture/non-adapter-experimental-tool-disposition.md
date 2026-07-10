# Non-Adapter Experimental Tool Disposition

> Status: **decision document for trade-trace-4ipeh**. Recorded 2026-07-09
> from the live runtime registry. Scope is limited to the non-adapter
> experimental tools listed below.

## Decision

Keep the five non-adapter experimental tools registered, schema-described, and
dispatchable only through explicit experimental opt-in:

`approval.get`, `approval.list`, `approval.record`, `approval.report`, and
`forecast.anchor_to_snapshot`.

They remain hidden from the default public catalog, default MCP specs, default
`tool.schema`, and the legacy opt-in view. This record does **not** approve
promotion to the default catalog and does **not** approve removal.

Owner-only decision: any future promotion or deletion of one of these tools
requires an owner decision plus a dedicated implementation follow-up bead that
updates runtime registration, docs, tests, and release notes together. Because
this record recommends `keep-experimental` for every in-scope tool, no
implementation follow-up bead is required by this pass.

## Runtime Evidence

Runtime readback was generated from `build_registry()`, `mcp_tool_specs()`, and
`tool.schema` with a temporary initialized journal on 2026-07-09.

Observed registry behavior for all five in-scope tools:

- `registered == true` in `build_registry()`.
- `metadata.catalog_visibility == "experimental"`.
- Absent from `public_names()`.
- Absent from `public_names(include_legacy=True)`.
- Present in `public_names(include_experimental=True)`.
- Absent from default `mcp_tool_specs()`.
- Present in `mcp_tool_specs(include_experimental=True)`.
- Absent from default `tool.schema`.
- Present in `tool.schema` when called with `include_experimental=true`.

The same readback reported the default public catalog at 77 non-admin entries
and the explicit experimental view at 87 entries. The count is supporting
context only; the decision is keyed to the five named tools.

<!-- non-adapter-experimental-disposition:start -->
| Tool | Decision | Runtime evidence | Safety rationale | Owner-only promotion/removal gate |
|---|---|---|---|---|
| `approval.get` | keep-experimental | Read-only; registered; `catalog_visibility="experimental"`; hidden from default and legacy catalog/schema views; visible only with experimental opt-in. | Reads one local approval/waiver/autonomy audit record and returns local evidence only. It is not a live approval gate and has no execution, signing, settlement, fund-movement, or remediation path. | Owner must decide before promotion or deletion; create an implementation bead before changing catalog visibility or removing the handler. |
| `approval.list` | keep-experimental | Read-only; registered; `catalog_visibility="experimental"`; hidden from default and legacy catalog/schema views; visible only with experimental opt-in. | Lists local audit records, including hard-block override attempts, with `record_kind` / `non_executing` response metadata. It does not grant permissions or operate on any external account. | Owner must decide before promotion or deletion; create an implementation bead before changing catalog visibility or removing the handler. |
| `approval.record` | keep-experimental | Write tool; registered; `catalog_visibility="experimental"`; hidden from default and legacy catalog/schema views; visible only with experimental opt-in. | Appends local approval/waiver/autonomy-permission audit evidence. The handler validates referenced local rows, hashes canonical material, rejects credential-shaped metadata and secret-bearing text, and records hard-block override attempts as visible violations rather than live permissions. | Owner must decide before promotion or deletion; create an implementation bead before changing catalog visibility or removing the handler. |
| `approval.report` | keep-experimental | Read-only; registered; `catalog_visibility="experimental"`; hidden from default and legacy catalog/schema views; visible only with experimental opt-in. | Summarizes proposed pre-trade packets against local approval/waiver records and caller-supplied external receipt labels. Its own caveats state that external imports may be unavailable and no execution import table is compared for remediation. | Owner must decide before promotion or deletion; create an implementation bead before changing catalog visibility or removing the handler. |
| `forecast.anchor_to_snapshot` | keep-experimental | Write tool; registered; `catalog_visibility="experimental"`; hidden from default and legacy catalog/schema views; visible only with experimental opt-in. | Retained as a frozen backfill path. It links a forecast to a snapshot after the fact and is superseded for decision-time proof by `forecast.commit_blind` plus `forecast.reveal_snapshot`; default exposure would reintroduce the after-the-fact anchor anti-pattern. | Owner must decide before promotion or deletion; create an implementation bead before changing catalog visibility or removing the handler. |
<!-- non-adapter-experimental-disposition:end -->

## Out Of Scope

The live adapter-backed Polymarket tools are also experimental and opt-in after
`trade-trace-cjgz2.2`, but they are not decided by this record:

`market.refresh`, `market.search`, `outcome.fetch`, `snapshot.fetch`, and
`snapshot.fetch_series`.

Those tools have separate adapter-scope evidence and tests. This decision only
covers the five non-adapter Product-B/frozen tools above.

## Follow-Up Policy

No new follow-up bead is needed for the current `keep-experimental` disposition.
If an owner later chooses to promote or remove any row, the follow-up bead must
pin the intended catalog behavior in runtime tests before changing the registry.

## Validation

The companion docs test keeps this record aligned with runtime behavior by
checking the matrix scope against `build_registry()`, MCP spec visibility, and
default versus experimental `tool.schema` output.
