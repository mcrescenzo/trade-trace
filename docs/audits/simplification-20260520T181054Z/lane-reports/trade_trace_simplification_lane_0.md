# Lane 0 status: completed

What I did:
Inspected the CLI/MCP/tool registry/contracts lane read-only at /home/hermes/code/trade-trace, focusing on:
- src/trade_trace/cli.py
- src/trade_trace/mcp_server.py
- src/trade_trace/core.py
- src/trade_trace/contracts/*
- src/trade_trace/tools/_helpers.py
- src/trade_trace/tools/errors.py
- src/trade_trace/tools/_examples.py
- relevant tests under tests/contracts/ and tests/golden/

Validation run:
- pytest -q tests/contracts/test_cli_parse_kv_args.py tests/contracts/test_tool_schema_runtime_parity.py tests/contracts/test_cli_command_help.py tests/golden/test_cli_mcp_parity.py
- Result: 19 passed in 0.10s

Repository state:
- Read-only review only.
- No files created or modified.
- Current HEAD verified: ffcd97420bf44c846451bd5d39596d39437d6e3e on main.

Findings:
I found 3 bounded simplification candidates. Two look worth accepting/merging into existing agent ergonomics/schema work; one is small and lower priority.

Candidate id: cli-mcp-contracts-SIMP-001

Proposed title:
Centralize repeated tool example lookup helper used by register_* modules

Domain:
cli-mcp-contracts / tool registry / schema examples

Complexity class:
Duplication / schema plumbing drift

Evidence type/evidence:
The same local _examples_for helper is duplicated across multiple tool registration modules.

Command:
search_files pattern "def _examples_for\\(tool: str\\)" in src/trade_trace/tools

Evidence snippets:
- src/trade_trace/tools/ledger.py:1911-1917
  from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

      def _examples_for(tool: str) -> dict[str, Any]:
          ex = WRITE_TOOL_EXAMPLES.get(tool)
          if ex is None:
              return {"example_minimal": None, "example_rich": None}
          return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

- src/trade_trace/tools/memory.py:1159-1165 has the same helper
- src/trade_trace/tools/strategy.py:397-403 has the same helper
- src/trade_trace/tools/fixture.py:667-673 has the same helper
- src/trade_trace/tools/playbook.py:616-622 has the same helper
- src/trade_trace/tools/csv_import.py:403-409 has the same helper
- src/trade_trace/tools/imports.py:529-535 has the same helper

The helper is naturally coupled to:
- src/trade_trace/tools/_examples.py:22-383, WRITE_TOOL_EXAMPLES
- src/trade_trace/contracts/tool_registry.py:122-148, ToolRegistry.register derives json_schema from example_minimal

Current behavior contract:
Each registration call may pass:
- example_minimal
- example_rich

ToolRegistry.register then derives json_schema when example_minimal is present and json_schema is not explicitly provided.

Complexity cost:
Every tool module carries the same tiny adapter from WRITE_TOOL_EXAMPLES shape:
- {"minimal": ..., "rich": ...}
to ToolRegistry.register kwargs:
- {"example_minimal": ..., "example_rich": ...}

This creates multiple places to update if example metadata grows, and makes schema/example plumbing appear local despite being global contract machinery.

Expected benefit:
- One authoritative example-to-registration adapter.
- Less repeated code in registration modules.
- Lower risk of future schema/example drift if example fields expand.
- Easier tests around example registration behavior.

Suggested refactor shape:
Move the helper into src/trade_trace/tools/_examples.py, e.g.

def examples_for(tool: str) -> dict[str, Any]:
    ex = WRITE_TOOL_EXAMPLES.get(tool)
    if ex is None:
        return {"example_minimal": None, "example_rich": None}
    return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

Then replace local helpers with:
from trade_trace.tools._examples import examples_for

registry.register(..., **examples_for("venue.add"))

Non-goals:
- Do not change example payload contents.
- Do not change ToolRegistry.register schema derivation.
- Do not alter CLI/MCP schemas or tool.schema output shape.

Behavior-preservation plan:
- Pure mechanical refactor.
- Existing examples remain identical.
- Existing derived schemas remain identical because ToolRegistry.register receives the same kwargs.

Validation command/gap:
Run:
pytest -q tests/contracts/test_tool_schema_runtime_parity.py tests/contracts/test_agent_ergonomics.py tests/contracts/test_write_tools_have_schemas.py

Also run the targeted validation already run:
pytest -q tests/contracts/test_cli_parse_kv_args.py tests/contracts/test_tool_schema_runtime_parity.py tests/contracts/test_cli_command_help.py tests/golden/test_cli_mcp_parity.py

Size:
XS/S

Risk:
Low

Priority:
P2

Confidence:
High

Why not style:
This is not about naming or formatting. It removes seven duplicated copies of contract-relevant schema/example plumbing.

Why complexity may be intentional/false positive:
The helper may have been kept local to avoid importing WRITE_TOOL_EXAMPLES at module import time. But current code imports it inside register_* functions already; a shared examples_for imported inside those same functions preserves lazy import behavior.

Duplicate/overlap notes:
Likely merge into agent ergonomics epic if it owns help/schema/example contracts broadly. It is not the same as existing “tool schema runtime parity” bug fixes; this is a small structural cleanup after those fixes.

Proposed Bead title:
Centralize tool example registration helper

Proposed Bead body:
Multiple register_* modules define identical local _examples_for helpers to adapt WRITE_TOOL_EXAMPLES entries into ToolRegistry.register kwargs. Move the adapter into trade_trace.tools._examples as examples_for and update registration modules to use it. Preserve lazy import behavior and exact tool.schema/json_schema outputs.

Acceptance criteria:
- A single shared examples_for helper exists in trade_trace.tools._examples.
- Duplicated local _examples_for definitions are removed from tool registration modules.
- tool.schema catalog and per-tool outputs are byte/structurally equivalent before/after for representative write tools.
- tests/contracts/test_tool_schema_runtime_parity.py passes.
- tests/contracts/test_agent_ergonomics.py passes.
- tests/contracts/test_write_tools_have_schemas.py passes.

Coordinator disposition recommendation:
accept or merge into existing agent ergonomics/schema contracts work


Candidate id: cli-mcp-contracts-SIMP-002

Proposed title:
Unify CLI and MCP/tool.schema catalog projection from ToolRegistry

Domain:
cli-mcp-contracts / MCP catalog / tool.schema catalog / registry projection

Complexity class:
Duplicated projection logic / contract drift risk

Evidence type/evidence:
There are at least two registry-to-catalog projections over the same ToolRegistry data.

MCP projection:
- src/trade_trace/mcp_server.py:42-64
  def mcp_tool_specs(registry: ToolRegistry | None = None) -> list[dict[str, Any]]:
      reg = registry if registry is not None else default_registry()
      specs: list[dict[str, Any]] = []
      for name in reg.names():
          registration = reg.get(name)
          spec = {
              "name": registration.name,
              "description": registration.description,
              "input_schema": registration.json_schema or {},
              "is_write": registration.is_write,
          }
          _assert_no_secret_transport_hints(spec)
          specs.append(spec)
      return specs

tool.schema catalog projection:
- src/trade_trace/tools/journal.py:255-272
  if wanted is None:
      return {
          "tools": [
              {
                  "name": reg.name,
                  "cli_invocation": "tt " + " ".join(reg.cli_invocation),
                  "is_write": reg.is_write,
                  "has_example": reg.example_minimal is not None,
                  "json_schema": reg.json_schema,
              }
              for reg in sorted(registry.by_name.values(), key=lambda r: r.name)
          ],
      }

Tests explicitly assert these surfaces should stay aligned:
- tests/contracts/test_agent_ergonomics.py:115-158
  test_tool_schema_catalog_includes_json_schema_for_mcp_parity
  Comments say catalog mode “mirrors MCP list-tools”.

Current registry size observed:
Command:
python3 - <<'PY'
from trade_trace.core import default_registry
reg=default_registry()
print('tools', len(reg.names()))
print('write tools', sum(1 for n in reg.names() if reg.get(n).is_write))
print('schemas', sum(1 for n in reg.names() if reg.get(n).json_schema is not None))
print('no schema sample', [n for n in reg.names() if reg.get(n).json_schema is None][:20])
PY

Output:
tools 67
write tools 30
schemas 41
no schema sample ['journal.init', 'journal.rebuild_projections', 'journal.repair', 'journal.rescan_scoring', 'journal.schema', 'journal.status', 'model.warm', 'playbook.list', 'playbook.list_versions', 'playbook.show', 'reflection.prompt_for_outcome', 'report.calibration', 'report.calibration_integrity', 'report.decision_velocity', 'report.filter_schema', 'report.mistakes', 'report.playbook_adherence', 'report.pnl', 'report.risk', 'report.strengths']

Current behavior contract:
- MCP list-tools exposes name, description, input_schema, is_write.
- tool.schema catalog exposes name, cli_invocation, is_write, has_example, json_schema.
- MCP server’s SDK adapter maps mcp_tool_specs input_schema into types.Tool inputSchema.
- tool.schema tests require json_schema presence in catalog rows.

Complexity cost:
The same registry data is projected by separate code paths with different key names and slightly different null/default semantics:
- MCP: input_schema = registration.json_schema or {}
- tool.schema: json_schema = reg.json_schema, possibly None

This makes future changes to registry metadata, descriptions, schema defaults, or secret filtering easier to apply to one catalog and forget the other.

Expected benefit:
- One source of truth for public registry metadata.
- Lower contract drift risk between MCP list-tools and tool.schema.
- Easier to audit what tool metadata is exposed externally.
- Simpler tests: compare two views from one common projection rather than preserving hand-coded parity.

Suggested refactor shape:
Add a method/function near ToolRegistry, e.g. in contracts/tool_registry.py:

def tool_catalog(registry, *, include_cli=True, schema_key="json_schema", empty_schema_as_object=False) -> list[dict[str, Any]]:
    ...

Or add a ToolRegistration.to_public_spec(...) helper.

Then:
- mcp_tool_specs uses the shared projection with MCP key mapping.
- _tool_schema catalog uses the same projection with CLI fields included.
- Keep _assert_no_secret_transport_hints in MCP boundary or make it part of shared public projection if intentionally universal.

Non-goals:
- Do not change MCP protocol output.
- Do not change tool.schema response shape.
- Do not change schema derivation.
- Do not add dynamic discovery.

Behavior-preservation plan:
- Golden compare current mcp_tool_specs(default_registry()) with new mcp_tool_specs.
- Golden compare mcp_call("tool.schema", {}) data["tools"] before/after.
- Preserve MCP input_schema {} fallback for tools without schema.
- Preserve tool.schema json_schema None for tools without schema, because tests document homogeneous key presence with None allowed.

Validation command/gap:
Run:
pytest -q tests/contracts/test_agent_ergonomics.py tests/integration/test_mcp_stdio_server.py tests/security/test_mcp_stdio_boundary.py tests/contracts/test_tool_schema_runtime_parity.py

Already run related:
pytest -q tests/contracts/test_tool_schema_runtime_parity.py tests/golden/test_cli_mcp_parity.py
passed.

Size:
S/M

Risk:
Medium-low, because public contract surfaces are involved.

Priority:
P2

Confidence:
Medium-high

Why not style:
This reduces duplicated external contract projection logic and drift risk across CLI/MCP introspection surfaces. It is not merely moving code for aesthetics.

Why complexity may be intentional/false positive:
The two projections intentionally expose different fields and null semantics. A shared projection must preserve this, not force identical payloads. MCP also has boundary-specific secret transport hint checks that may intentionally remain local.

Duplicate/overlap notes:
This overlaps with the existing agent ergonomics epic covering help/schema/errors/actionability contracts broadly. Recommend merge there unless the coordinator wants a dedicated simplification bead.

Proposed Bead title:
Share registry catalog projection between MCP list-tools and tool.schema

Proposed Bead body:
mcp_server.mcp_tool_specs and tools.journal._tool_schema catalog mode independently project ToolRegistry metadata for public introspection. They differ in field names and schema None/{} semantics but are meant to remain contract-aligned. Introduce a shared registry public-spec projection while preserving each transport’s exact response shape.

Acceptance criteria:
- mcp_tool_specs output is unchanged for all currently registered tools.
- tool.schema catalog output is unchanged for all currently registered tools.
- The projection from ToolRegistration to public metadata is centralized.
- tests/contracts/test_agent_ergonomics.py passes.
- tests/integration/test_mcp_stdio_server.py passes.
- tests/security/test_mcp_stdio_boundary.py passes.
- tests/contracts/test_tool_schema_runtime_parity.py passes.

Coordinator disposition recommendation:
merge into agent ergonomics/schema contracts work


Candidate id: cli-mcp-contracts-SIMP-003

Proposed title:
Centralize CLI error-code-to-exit-code mapping

Domain:
cli-mcp-contracts / CLI error contract

Complexity class:
Small duplication / contract mapping drift

Evidence type/evidence:
CLI exit code mapping exists in two places.

Startup/CLI-parse error path:
- src/trade_trace/cli.py:221-248
  def _emit_cli_error(...):
      ...
      if code == ErrorCode.VALIDATION_ERROR:
          return 2
      if code == ErrorCode.INVARIANT_VIOLATION:
          return 3
      return 1

Post-dispatch envelope path:
- src/trade_trace/cli.py:466-476
  if body.get("ok"):
      return 0
  err_code = body.get("error", {}).get("code")
  if err_code == "VALIDATION_ERROR":
      return 2
  if err_code == "INVARIANT_VIOLATION":
      return 3
  return 1

Tests pin behavior:
- tests/contracts/test_agent_ergonomics.py:330-372
  test_exit_code_zero_on_success
  test_exit_code_two_on_validation_error
  test_exit_code_one_on_not_found
- tests/golden/test_cli_mcp_parity.py:103-140 also asserts VALIDATION_ERROR -> 2 and INVARIANT_VIOLATION -> 3.

Current behavior contract:
- Success: 0
- VALIDATION_ERROR: 2
- INVARIANT_VIOLATION: 3
- all other error classes: 1

Complexity cost:
Two independent mappings must stay aligned, one comparing ErrorCode enum values, one comparing serialized strings.

Expected benefit:
- One small helper documents the transport contract.
- Reduces chance of future mismatch if a new special exit mapping is added.
- Simplifies _emit_cli_error and main tail.

Suggested refactor shape:
Add a private helper in cli.py:

def _exit_code_for_error_code(code: ErrorCode | str | None) -> int:
    text = code.value if isinstance(code, ErrorCode) else code
    if text == ErrorCode.VALIDATION_ERROR.value:
        return 2
    if text == ErrorCode.INVARIANT_VIOLATION.value:
        return 3
    return 1

Use it in _emit_cli_error and final post-dispatch mapping.

Non-goals:
- Do not change exit code values.
- Do not change envelope structure.
- Do not change stdout/stderr discipline.

Behavior-preservation plan:
- Existing tests should be sufficient.
- Add a narrow unit test for _exit_code_for_error_code if desired, but not necessary if current behavior tests remain.

Validation command/gap:
Run:
pytest -q tests/contracts/test_agent_ergonomics.py tests/golden/test_cli_mcp_parity.py

Already run:
pytest -q tests/golden/test_cli_mcp_parity.py
passed.

Size:
XS

Risk:
Low

Priority:
P3

Confidence:
High

Why not style:
The mapping is a behavioral contract and is duplicated across separate error paths. Centralizing reduces contract drift, not just visual noise.

Why complexity may be intentional/false positive:
The current duplication is very small and explicit. Keeping the two mappings inline may be considered more readable than adding another helper. This is why priority is P3.

Duplicate/overlap notes:
Overlaps with agent ergonomics epic insofar as it owns errors/actionability contracts broadly. Could be batched with other CLI error contract cleanup.

Proposed Bead title:
Centralize CLI exit code mapping

Proposed Bead body:
CLI maps error envelopes to process exit codes in both _emit_cli_error and the final post-dispatch path. Extract one private helper that accepts ErrorCode or serialized code string and returns the existing contract values: 0 success handled separately, 2 VALIDATION_ERROR, 3 INVARIANT_VIOLATION, 1 everything else.

Acceptance criteria:
- _emit_cli_error and main’s final error path use one shared mapping helper.
- CLI exit code behavior is unchanged.
- tests/contracts/test_agent_ergonomics.py passes.
- tests/golden/test_cli_mcp_parity.py passes.

Coordinator disposition recommendation:
defer or merge into agent ergonomics/errors cleanup


Rejected / not recommended as simplification beads:

1. ToolRegistry.validate redundancy
Evidence:
- ToolRegistry.register detects duplicate names and CLI invocation collisions at registration time: src/trade_trace/contracts/tool_registry.py:134-142.
- ToolRegistry.validate re-checks collisions across by_name: src/trade_trace/contracts/tool_registry.py:170-183.
Why rejected:
The code comments explicitly state validate is defense-in-depth at process startup. It may catch manual mutations of by_name/by_cli or future registration changes. Cost is tiny and intentional.

2. Lazy _ToolError in contracts.grammar
Evidence:
- src/trade_trace/contracts/grammar.py:16-27 uses late-bound ToolError to avoid import cycle.
Why rejected:
The comments cite a known import cycle. Moving ToolError into contracts could simplify architecture, but this is broader and could ripple across tools. Not bounded enough for this lane without a larger import-boundary review.

3. CLI argparse-only parser rewrite
Evidence:
- src/trade_trace/cli.py:8-10 explicitly states argparse is intentional to avoid third-party CLI dependency.
Why rejected:
Replacing with Typer/Click is rewrite-sized and violates the explicit intentional complexity note.

Coverage accounting:

Files/areas inspected:
- src/trade_trace/cli.py
- src/trade_trace/mcp_server.py
- src/trade_trace/core.py
- src/trade_trace/contracts/tool_registry.py
- src/trade_trace/contracts/envelope.py
- src/trade_trace/contracts/errors.py
- src/trade_trace/contracts/json_schema_derive.py
- src/trade_trace/contracts/grammar.py
- src/trade_trace/contracts/report_filter.py
- src/trade_trace/tools/_helpers.py
- src/trade_trace/tools/errors.py
- src/trade_trace/tools/_examples.py
- src/trade_trace/tools/journal.py around tool.schema
- tests/golden/test_cli_mcp_parity.py
- tests/contracts/test_cli_parse_kv_args.py
- tests/contracts/test_tool_schema_runtime_parity.py
- tests/contracts/test_cli_command_help.py
- tests/contracts/test_agent_ergonomics.py

Commands run:
- git status --short && git rev-parse HEAD && git branch --show-current
- search_files for relevant Python files under src/trade_trace and tests
- read_file on the files listed above
- search_files for example_minimal/json_schema/_examples_for/optional_keys usage
- search_files for _examples_for duplication
- pytest -q tests/contracts/test_cli_parse_kv_args.py tests/contracts/test_tool_schema_runtime_parity.py tests/contracts/test_cli_command_help.py tests/golden/test_cli_mcp_parity.py
- python3 script to count registry tools/schemas:
  - tools 67
  - write tools 30
  - schemas 41

Areas not inspected:
- Full implementation internals of all tool handlers beyond schema/example registration edges.
- Console UI internals, except registry import edge in core.py.
- Full docs/contracts text.
- Beads database, by instruction not to create/update Beads and because this lane was code-evidence focused.

Caveats:
- Existing parent workflow mentions seam-refresh bughunt already covers MCP envelope and report/playbook bugs; I avoided reporting envelope correctness bugs.
- Existing agent ergonomics epic broadly owns help/schema/errors/actionability contracts. Candidates SIMP-002 and SIMP-003 should probably be merged into that work rather than opened as standalone backlog items.
- Review was read-only; no files were edited.
