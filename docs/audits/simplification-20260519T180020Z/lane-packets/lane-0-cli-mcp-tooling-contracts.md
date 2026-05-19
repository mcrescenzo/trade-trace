# Read-only simplification review: cli-mcp-tooling-contracts

## What I did

- Read `/home/hermes/code/trade-trace/docs/audits/simplification-20260519T180020Z/domain-map.json`.
- Inspected all 26 assigned files for the `cli-mcp-tooling-contracts` domain using read-only file reads, AST summaries, and targeted content searches.
- Checked prior audit artifacts under `docs/audits` for duplicate/overlap signals.
- Did not edit files, create/update Beads, install packages, format, push, publish, or delete anything.

## Candidate records

### Candidate SIM-CLI-MCP-001

#### id
SIM-CLI-MCP-001

#### title
Introduce a shared CLI error-envelope helper to remove repeated hand-built envelope blocks

#### domain
cli-mcp-tooling-contracts

#### complexity class
Duplicate validation / transport-envelope boilerplate

#### file/function/line evidence
- `src/trade_trace/cli.py`
  - `MalformedJsonArgError` handling manually builds an `ErrorEnvelope`, dumps JSON, and returns `2`: lines 221-243.
  - `StrayPositionalArgsError` handling repeats the same envelope/dump/return structure: lines 244-268.
  - `CLINameCollisionError` startup handling also hand-builds and dumps an error envelope: lines 194-212.
  - The repeated fields differ only in `code`, `message`, `details`, `tool`, `actor_id`, `request_id`, and exit code.
- Related contract objects:
  - `ErrorEnvelope`, `ErrorBody`, `Meta`, `dump_envelope` imported at `cli.py` lines 22-28.
  - `dispatch()` already centralizes runtime tool exceptions into envelopes in `src/trade_trace/core.py` lines 182-252.

#### current behavior contract to preserve
- CLI emits machine-parseable JSON error envelopes on stdout for malformed JSON arguments and stray positional arguments.
- Exit code remains:
  - `2` for validation-shaped CLI input errors.
  - `1` for startup registry collision/storage-shaped error.
- Error envelope details remain stable:
  - malformed JSON includes `field`, `reason`, `decode_error`, `tool`.
  - stray positional args include `field`, `stray_positional_args`, `tool`.
  - registry collision includes `reason=cli_name_collision`, `conflict_kind`, `colliding`.
- `actor_id` and `request_id` semantics stay unchanged.
- No change to normal dispatch path, NDJSON list streaming, or human stderr hints.

#### complexity cost
- Three near-identical envelope construction blocks make future transport-envelope changes easy to apply inconsistently.
- Each block repeats `Meta(...)`, `ErrorBody(...)`, `model_dump(mode="json", exclude_none=True)`, `json.dumps(..., sort_keys=True)`, and `print(...)`.
- CLI startup/input parsing errors are outside `dispatch()`, so they need their own path, but the current duplication is larger than necessary.

#### expected benefit
- Smaller `main()` and clearer control flow around command parsing.
- One local helper becomes the obvious place to preserve stdout JSON shape for pre-dispatch CLI errors.
- Lower chance of future drift in envelope serialization options or request-id generation for parse errors.

#### suggested refactor shape
- Add a private helper in `cli.py`, for example:

  - `_print_cli_error_envelope(*, code, message, details, tool, actor_id, request_id) -> None`
  - or `_cli_error_envelope(...) -> ErrorEnvelope` plus a small `_print_envelope(...)`.

- Replace the three repeated manual `ErrorEnvelope` construction/dump/print blocks with calls to the helper.
- Keep helper private to `cli.py`; do not move into `core.py` unless a second transport needs it.

#### non-goals
- Do not alter `dispatch()` error handling.
- Do not change exit-code mapping.
- Do not redesign CLI parsing or introduce Click/Typer.
- Do not change JSON field ordering or envelope model definitions.

#### behavior-preservation plan
- Characterize current stdout/stderr/exit-code behavior for:
  - invalid `--*-json`.
  - stray positional argument after a known command.
  - injected registry collision if existing tests cover it.
- Refactor helper only after tests pin current envelope shape.
- Confirm `sort_keys=True` and `exclude_none=True` remain unchanged.

#### validation commands/gaps
- Existing validation:
  - `pytest tests/contracts tests/integration -q`
  - `pytest tests -q`
- More targeted likely useful:
  - `pytest tests/contracts/test_cli_* tests/integration/test_cli_* -q` if present.
  - If no specific tests exist for malformed JSON and stray positional handling, add/extend them before refactor.
- Gap: I did not run tests because this lane is read-only and the task requested review, not mutation/verification.

#### size
Small

#### risk
Low

#### priority
P3

#### confidence
High

#### why not taste
This is not about style preference; the same envelope-construction/serialization contract is repeated in three pre-dispatch error paths, increasing drift risk in a public CLI contract.

#### intentional complexity check
The complexity is partly intentional because pre-dispatch CLI failures cannot go through `dispatch()`. However, preserving that boundary does not require repeating envelope construction and JSON serialization three times.

#### duplicate/overlap notes
- Not a duplicate of `trade-trace-1kkv` dashboard work.
- Not a duplicate of `trade-trace-cpz2` idempotency-key enforcement.
- Not a duplicate of recent MCP/schema/security bug beads `trade-trace-hsnz`, `trade-trace-3i33`, or `trade-trace-aqpf`; this is a behavior-preserving simplification of CLI pre-dispatch envelope construction.
- Prior deadcode audit noted CLI/tool-surface docs drift, but this candidate is code-internal and contract-preserving.

#### proposed Bead body/acceptance
Body:
Refactor `src/trade_trace/cli.py` pre-dispatch error handling to use a shared private helper for constructing and printing CLI JSON error envelopes. Preserve current stdout envelope shape, `sort_keys=True`, `exclude_none=True`, actor/request metadata, and exit codes for malformed JSON args, stray positional args, and registry startup collision.

Acceptance:
- Malformed `--*-json` still emits a `VALIDATION_ERROR` envelope on stdout and exits `2`.
- Stray positional args after a known command still emit a `VALIDATION_ERROR` envelope on stdout and exits `2`.
- Registry CLI-name collision still emits the existing storage-shaped startup envelope and exits `1`.
- No changes to successful command output, NDJSON list streaming, or `--human` stderr hints.
- `pytest tests/contracts tests/integration -q` passes.

#### disposition recommendation
Create simplification Bead if the parent wants small, low-risk cleanup items; otherwise keep as opportunistic refactor when touching `cli.py` next.


---

### Candidate SIM-CLI-MCP-002

#### id
SIM-CLI-MCP-002

#### title
Factor dispatch exception-to-envelope mapping into small helpers

#### domain
cli-mcp-tooling-contracts

#### complexity class
Large dispatcher / repeated error-envelope construction

#### file/function/line evidence
- `src/trade_trace/core.py`
  - `dispatch()` is 155 lines: lines 101-255.
  - It includes nested exception handling for:
    - `ToolError`: lines 185-190.
    - `IdempotencyConflictError`: lines 191-206.
    - `sqlite3.IntegrityError`: lines 207-225.
    - `sqlite3.Error`: lines 226-235.
    - non-dict handler result invariant: lines 237-249.
  - `_apply_hints()` is nested in `dispatch()` at lines 161-180 and is called before every error return plus success return.
- Error contract types are imported at lines 17-23.
- The handler invocation itself is only lines 182-184; much of the function is mapping exceptions into envelopes.

#### current behavior contract to preserve
- CLI and MCP both call the same `dispatch()` path.
- Actor-id validation still occurs before tool lookup.
- Unknown tool returns `NOT_FOUND` with `entity_kind`, `tool`, and `known_tools`.
- `_allow_no_idempotency` sets `meta.idempotency_disabled`.
- `_dry_run` uses `DRY_RUN_FLAG` and always resets the context var in `finally`.
- `ctx.meta_hints` are applied before every error/success response.
- `ToolError`, `IdempotencyConflictError`, SQLite integrity/storage errors, and non-dict handler result preserve their exact `ErrorCode`, message, details, and meta behavior.

#### complexity cost
- `dispatch()` is a high-risk central contract path shared by CLI and MCP.
- Multiple return branches repeat the same `ErrorEnvelope(ErrorBody(...), meta=meta)` structure.
- The SQLite `IntegrityError` code-selection logic is embedded inside the already-large dispatch function.
- Future additions to error metadata or hint application require editing multiple branches.

#### expected benefit
- Smaller and easier-to-review dispatcher.
- Clearer separation:
  - request/context setup;
  - handler execution;
  - exception-to-error-body mapping;
  - envelope construction and hint application.
- Reduced chance of one error branch missing meta hint propagation.

#### suggested refactor shape
- Keep public `dispatch()` signature unchanged.
- Extract private helpers in `core.py`, for example:
  - `_apply_meta_hints(meta: Meta, hints: dict[str, Any]) -> None`
  - `_error_envelope(meta: Meta, code: ErrorCode, message: str, details: dict[str, Any]) -> ErrorEnvelope`
  - `_sqlite_integrity_code(message: str) -> ErrorCode`
  - `_idempotency_conflict_details(exc: IdempotencyConflictError) -> dict[str, Any]`
- `dispatch()` still owns ordering and context-var lifetime.
- Helpers should not call handlers or know about the registry.

#### non-goals
- Do not change `dispatch()` API.
- Do not change Pydantic envelope models.
- Do not merge CLI pre-dispatch parsing errors into `dispatch()`.
- Do not change any SQLite error categorization strings.
- Do not alter dry-run/idempotency behavior.

#### behavior-preservation plan
- Golden-check envelopes before/after for:
  - unknown tool.
  - invalid actor id.
  - `ToolError`.
  - idempotency conflict.
  - SQLite CHECK/FK/UNIQUE/append-only/other storage errors where tests exist.
  - handler returning non-dict via a test registry stub.
  - dry-run meta propagation.
  - custom `ctx.meta_hints` propagation including unknown keys.
- Refactor in small commits if allowed by parent workflow.

#### validation commands/gaps
- Existing validation:
  - `pytest tests/contracts tests/integration -q`
  - `pytest tests -q`
- Targeted useful tests:
  - `pytest tests/contracts/test_*envelope* tests/contracts/test_*mcp* tests/integration/test_idempotency.py -q`
  - Exact test names need discovery by parent if materializing.
- Gap: If there is no direct test for non-dict handler results or SQLite error classification, add focused unit tests before refactor.

#### size
Small-to-medium

#### risk
Medium because `dispatch()` is central contract code, but the refactor shape is bounded and behavior-preserving.

#### priority
P2

#### confidence
High

#### why not taste
The function is not merely “long”; it centralizes several independent error-envelope construction paths with repeated meta-hint application requirements. The simplification reduces contract drift risk in the core shared CLI/MCP dispatcher.

#### intentional complexity check
The exception mapping itself is intentional: this project exposes typed agent-facing envelopes instead of raw exceptions, and CLI/MCP parity depends on this. The proposal preserves that complexity but moves repeated mechanics into local helpers.

#### duplicate/overlap notes
- Not a duplicate of `trade-trace-cpz2`; this does not change idempotency-key enforcement.
- Not a duplicate of `trade-trace-hsnz`, `trade-trace-3i33`, or `trade-trace-aqpf`; those are recent MCP/schema/security dogfood bugs, while this is a bounded dispatcher simplification.
- Prior audits mention CLI/MCP contracts and idempotency bugs, but I found no prior simplification candidate specifically for factoring `dispatch()` exception mapping.

#### proposed Bead body/acceptance
Body:
Simplify `src/trade_trace/core.py::dispatch` by extracting private helpers for meta-hint application, error envelope construction, SQLite integrity error code classification, and idempotency conflict details. Preserve the public dispatch signature and exact envelope/error behavior.

Acceptance:
- `dispatch()` public API remains unchanged.
- Existing error envelopes for invalid actor id, unknown tool, `ToolError`, idempotency conflict, SQLite errors, and non-dict handler returns are unchanged.
- Dry-run context var is still reset in all paths.
- `ctx.meta_hints` still propagate on success and every error branch, including unknown extra meta keys.
- `pytest tests/contracts tests/integration -q` and `pytest tests -q` pass.

#### disposition recommendation
Create simplification Bead. This is a central contract hotspot where a bounded helper extraction has durable value.


---

### Candidate SIM-CLI-MCP-003

#### id
SIM-CLI-MCP-003

#### title
Use declarative registration tables for clusters of simple tool registrations

#### domain
cli-mcp-tooling-contracts

#### complexity class
Pass-through registration boilerplate / schema-registration drift

#### file/function/line evidence
- `src/trade_trace/tools/reports.py`
  - `register_report_tools()` spans lines 502-686.
  - It contains 16 repeated `registry.register(...)` calls, most differing only by tool name, handler, description, and occasional `example_minimal`: lines 508-686.
- `src/trade_trace/tools/ledger.py`
  - `register_ledger_tools()` lines 1736-1768 contains 15 registrations.
  - Several are one-line repeated write registrations: lines 1747-1761.
  - `_examples_for()` is local and only used to thread examples into selected registrations: lines 1739-1745.
- `src/trade_trace/tools/admin.py`
  - `register_admin_tools()` lines 755-839 contains repeated admin registrations.
- `src/trade_trace/tools/playbook.py`
  - `register_playbook_tools()` lines 558-626 contains repeated registrations.
- `src/trade_trace/tools/strategy.py`
  - `register_strategy_tools()` lines 397-433 contains repeated registrations.
- `src/trade_trace/tools/memory.py`
  - `register_memory_tools()` lines 1127-1174 contains repeated registrations.
- `src/trade_trace/contracts/tool_registry.py`
  - `ToolRegistry.register()` already has a compact common API for name, handler, description, write flag, examples, and JSON schema: lines 122-157.
- `src/trade_trace/tools/_examples.py`
  - `WRITE_TOOL_EXAMPLES` centralizes examples for only a subset of write tools: lines 22-168.

#### current behavior contract to preserve
- Registered tool names, handlers, CLI invocations, descriptions, `is_write`, examples, and JSON schemas remain identical.
- Registry collision detection remains in `ToolRegistry.register()` / `validate()`.
- `journal.schema` / `tool.schema` continue to expose the same registered schemas/descriptions/examples.
- No change to handler implementations.

#### complexity cost
- Long registration functions obscure the actual public tool surface.
- Adding or modifying a tool requires editing repeated `registry.register(...)` boilerplate.
- Examples/descriptions are distributed inconsistently:
  - some report tools have inline `example_minimal`;
  - ledger examples come from `_examples.py`;
  - many write tools have no examples despite `_examples.py` docstring saying “Each write tool exposes a minimal valid example”.
- Manual registration blocks increase risk of omitting `is_write=True`, examples, or schema metadata for future tools.

#### expected benefit
- Tool catalog becomes easier to audit and compare across CLI/MCP/schema surfaces.
- Reduced registration boilerplate in large modules.
- Easier future validation that all write tools have expected metadata.
- Lower schema/CLI drift risk without changing runtime behavior.

#### suggested refactor shape
- Start with one low-risk module, preferably `reports.py`, because many registrations are read-only and handler-specific behavior is outside the registration block.
- Define a private data structure, for example:
  - `_REPORT_TOOL_SPECS = ((name, handler, description, example_minimal), ...)`
  - or a small dataclass local to the module if readability benefits.
- `register_report_tools()` loops over the table and calls `registry.register(...)`.
- Keep special cases explicit in table fields, not hidden in conditionals.
- If successful, apply the same pattern to `ledger.py`/`admin.py`/`playbook.py` only where it reduces repetition without hiding meaningful logic.
- For ledger examples, consider moving the `_examples_for()` lookup to a small shared helper if multiple modules need it, but do not broaden scope prematurely.

#### non-goals
- Do not introduce dynamic plugin discovery.
- Do not change the registry API.
- Do not remove explicit imports or change public tool names.
- Do not change handler behavior.
- Do not force every tool to have examples in this refactor unless separately accepted as a contract cleanup.
- Do not collapse domain modules into a single global registry file.

#### behavior-preservation plan
- Before/after compare `build_registry()` output:
  - sorted names;
  - CLI invocations;
  - handler identity names;
  - `is_write`;
  - descriptions;
  - examples;
  - derived `json_schema`.
- Use `journal.schema` / `tool.schema` tests to ensure schemas/descriptions remain unchanged.
- Keep table order deterministic even though registry names are sorted by `names()`.

#### validation commands/gaps
- Existing validation:
  - `pytest tests/contracts tests/integration -q`
  - `pytest tests -q`
- Additional useful check:
  - small snapshot test over `[(name, cli_invocation, is_write, description, example_minimal, example_rich, json_schema)]` before/after if not already present.
- Gap: Existing tests may validate tool names and schemas but not exact descriptions; if descriptions are public agent-facing contract, add a focused guard before refactor.

#### size
Medium if limited to `reports.py`; medium-to-large if applied across all registration clusters.

#### risk
Low-to-medium. Runtime behavior should be unchanged, but public tool metadata is contract-sensitive.

#### priority
P3

#### confidence
Medium-high

#### why not taste
This is not simply preference for table-driven code. The public CLI/MCP/tool-schema surface is repeated across several large registration blocks, and registration metadata is contract-bearing. A declarative table makes omissions and drift easier to detect.

#### intentional complexity check
The explicit registration calls are intentionally simple and avoid dynamic discovery, which is good for security and MCP boundary clarity. The proposal keeps explicit, static registration data and does not introduce plugin loading, eval, entry points, or runtime discovery.

#### duplicate/overlap notes
- Not a duplicate of open console epic `trade-trace-1kkv`.
- Not a duplicate of `trade-trace-cpz2` idempotency-key enforcement.
- Not a duplicate of MCP/schema/security bug beads `trade-trace-hsnz`, `trade-trace-3i33`, or `trade-trace-aqpf`; this is metadata registration simplification, not a behavior bug.
- Prior deadcode audit explicitly treated registered tools as live and noted docs/tool-surface drift separately; this candidate preserves the live surface and targets maintainability of registration metadata.

#### proposed Bead body/acceptance
Body:
Convert one or more large repeated `register_*_tools()` blocks, starting with `src/trade_trace/tools/reports.py::register_report_tools`, to explicit declarative tool-spec tables iterated by the registration function. Preserve all tool names, handlers, CLI invocations, descriptions, write flags, examples, and schemas.

Acceptance:
- `build_registry()` before/after has identical tool names and CLI invocations.
- For refactored tools, `handler`, `description`, `is_write`, examples, and JSON schema are unchanged.
- No dynamic plugin discovery or runtime import expansion is introduced.
- `journal.schema` / `tool.schema` outputs remain compatible.
- `pytest tests/contracts tests/integration -q` and `pytest tests -q` pass.

#### disposition recommendation
Create as optional P3 simplification, preferably scoped initially to `reports.py` to validate the pattern.


---

## Reviewed but rejected leads

### Large handler functions in ledger/memory/playbook/admin
Evidence:
- `src/trade_trace/tools/ledger.py` has many long write handlers, including `_forecast_add` lines 568-726, `_decision_add` lines 791-926, `_forecast_supersede` lines 1565-1731.
- `src/trade_trace/tools/memory.py` has `_memory_recall` lines 594-830.
- `src/trade_trace/tools/playbook.py` has `_decision_record_adherence` lines 385-517.
- `src/trade_trace/tools/admin.py` has `_journal_config_set` lines 485-597.

Disposition:
- Rejected as a simplification candidate at this threshold because most complexity appears domain-specific and contract/security/idempotency-sensitive.
- There is some repeated `open_db_for_args` / `UnitOfWork` / `check_idempotency_replay` / `emit_event` boilerplate, but `src/trade_trace/tools/_helpers.py` already centralizes part of it, and broader transaction abstraction could easily become a behavior-changing rewrite.
- Some overlap with `trade-trace-cpz2` idempotency enforcement makes this risky to raise as a general simplification bead right now.

### MCP secret transport-hint scanner
Evidence:
- `src/trade_trace/mcp_server.py` defines `SECRET_TRANSPORT_HINT_KEYS` lines 24-50 and recursively checks tool specs in `_assert_no_secret_transport_hints()` lines 91-103.

Disposition:
- Rejected. Although it adds apparent complexity, it is intentional security boundary defense for MCP metadata exposure. Simplifying/removing it would be riskier than keeping it.

### `ToolRegistry.validate()` after registration-time collision checks
Evidence:
- `ToolRegistry.register()` detects duplicate names and CLI invocation collisions at lines 133-141.
- `ToolRegistry.validate()` re-walks the registry at lines 168-181.

Disposition:
- Rejected. The file docstring explicitly calls this defense-in-depth and CI/runtime parity, lines 5-8 and 168-170. Complexity is intentional and low cost.

### `resolve.record` alias for `outcome.add`
Evidence:
- `src/trade_trace/tools/ledger.py` registers `resolve.record` as alias for `_outcome_add` at lines 1755-1756.

Disposition:
- Rejected. This is public PRD compatibility surface, not dead pass-through complexity. Removing it would be behavior-breaking.

## Coverage accounting

### Files inspected
All assigned files were inspected:

1. `src/trade_trace/cli.py`
2. `src/trade_trace/contracts/envelope.py`
3. `src/trade_trace/contracts/errors.py`
4. `src/trade_trace/contracts/grammar.py`
5. `src/trade_trace/contracts/json_schema_derive.py`
6. `src/trade_trace/contracts/tool_registry.py`
7. `src/trade_trace/core.py`
8. `src/trade_trace/mcp_server.py`
9. `src/trade_trace/tools/__init__.py`
10. `src/trade_trace/tools/_examples.py`
11. `src/trade_trace/tools/_helpers.py`
12. `src/trade_trace/tools/admin.py`
13. `src/trade_trace/tools/csv_import.py`
14. `src/trade_trace/tools/decision_matrix.py`
15. `src/trade_trace/tools/errors.py`
16. `src/trade_trace/tools/fixture.py`
17. `src/trade_trace/tools/imports.py`
18. `src/trade_trace/tools/journal.py`
19. `src/trade_trace/tools/ledger.py`
20. `src/trade_trace/tools/memory.py`
21. `src/trade_trace/tools/playbook.py`
22. `src/trade_trace/tools/reflection.py`
23. `src/trade_trace/tools/reports.py`
24. `src/trade_trace/tools/review_bundle.py`
25. `src/trade_trace/tools/signals.py`
26. `src/trade_trace/tools/strategy.py`

### Not inspected
None.

### Commands/tools run
- Read `domain-map.json`.
- Ran an AST summary over assigned files to collect line counts, function counts, and long functions.
- Searched assigned source for registration/schema/idempotency/envelope patterns.
- Read targeted sections of:
  - `src/trade_trace/cli.py`
  - `src/trade_trace/core.py`
  - `src/trade_trace/mcp_server.py`
  - `src/trade_trace/contracts/tool_registry.py`
  - `src/trade_trace/tools/_helpers.py`
  - `src/trade_trace/tools/_examples.py`
  - `src/trade_trace/tools/ledger.py`
  - `src/trade_trace/tools/reports.py`
- Searched prior audit artifacts under `docs/audits` for overlap/duplicate notes.

### Caveats
- I did not run the test suite because this was a read-only review lane and no code changes were made.
- I did not inspect Beads DB with mutation-capable commands; overlap checks were limited to provided context and read-only audit artifacts.
- Line numbers are from the current workspace state at `/home/hermes/code/trade-trace`.

## Files created or modified
None.

## Issues encountered
- `python` was not available; reran the AST inspection with `python3`.
- A combined multi-path search using a space-separated path failed once; reran the search on `docs/audits` successfully.

## Summary of findings
- Found three bounded simplification candidates:
  1. Shared CLI pre-dispatch error-envelope helper.
  2. Helper extraction inside `core.dispatch()` for error-envelope mapping and meta hint application.
  3. Declarative tool registration tables for large repeated registration blocks, starting with `reports.py`.
- Rejected several tempting leads where complexity appears intentional for compatibility, security, public agent contracts, or idempotency-sensitive behavior.