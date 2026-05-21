# Lane audit packet: cli-mcp-tooling

Audit run: `repo-audit-20260521T173511Z`  
Scope fingerprint: `1901b8097953e720`  
Lane: `cli-mcp-tooling`  
Focus: CLI, MCP stdio, dispatcher/tool registry/schema/error envelopes.  
Mode: read-only audit; only this artifact was written.

## Executive summary

I reviewed the 27 manifest rows assigned to `cli-mcp-tooling` across bughunt, deadcode/reachability, technical-debt, and simplification lenses. I found **no additive candidates** that are sufficiently grounded and not already covered by recent closed audit-family work.

The current surfaces show evidence that the recent closed CLI/MCP backlog items have landed:

- CLI startup, unknown-command, malformed JSON, and stray-positional failures are centralized through `_emit_cli_error()` and emit typed JSON envelopes (`src/trade_trace/cli.py:249-276`, `src/trade_trace/cli.py:336-348`, `src/trade_trace/cli.py:356-375`, `src/trade_trace/cli.py:381-410`).
- CLI argument parsing now accumulates repeated flags and rejects stray positional arguments (`src/trade_trace/cli.py:61-131`).
- Tool registry collision detection is runtime-enforced at registration and validation time (`src/trade_trace/contracts/tool_registry.py:143-190`, `src/trade_trace/contracts/tool_registry.py:201-214`).
- The shared dispatcher applies actor validation, tool lookup, write idempotency enforcement, dry-run plumbing, ToolError/idempotency/sqlite exception conversion, non-dict result guards, and meta-hint propagation in one path for CLI and MCP (`src/trade_trace/core.py:111-275`).
- MCP stdio list/call surfaces are deliberately registry-only, validate call arguments manually, wrap stdio validation failures in Trade Trace envelopes, and set MCP transport hints (`src/trade_trace/mcp_server.py:45-74`, `src/trade_trace/mcp_server.py:121-138`, `src/trade_trace/mcp_server.py:171-213`).
- Schema derivation is centralized from examples and uses canonical `ReportFilter` shape for top-level filter payloads (`src/trade_trace/contracts/json_schema_derive.py:24-53`, `src/trade_trace/contracts/json_schema_derive.py:77-112`).

Targeted verification passed: `68 passed in 4.62s` for CLI/MCP/schema contract tests.

## Commands, searches, and probes run

- Parsed assigned manifest rows:
  - `python - <<'PY' ... yaml.safe_load(manifest-coverage-ledger.yaml) ... owner_lane == 'cli-mcp-tooling'`
- Read audit context artifacts:
  - `manifest-coverage-ledger.yaml` (paginated/preview)
  - `existing-audit-family-inventory.json`
  - `audit-plan.md`
- Read decisive source files:
  - `src/trade_trace/cli.py`
  - `src/trade_trace/mcp_server.py`
  - `src/trade_trace/contracts/tool_registry.py`
  - `src/trade_trace/contracts/json_schema_derive.py`
  - `src/trade_trace/core.py`
  - representative assigned tool files/registration sections including `tools/__init__.py`, `tools/_examples.py`, `tools/errors.py`, `tools/journal.py`, `tools/admin.py`
- Source-scoped searches:
  - `def dispatch|default_registry|register\(` in `src/trade_trace/*.py`
  - `TODO|FIXME|pragma: no cover|pass|NotImplemented|unsupported|stub` in `src/trade_trace/*.py`
  - test-surface search for `mcp|schema|UnknownCommand|stray|Malformed|tool_registry|json_schema`
- Registry/schema probe:
  - `python - <<'PY' from trade_trace.core import default_registry ... print tools/no_schema ... PY`
  - Result: `tools 75`; `no_schema 13`, all observed as read/no-argument/deferred/list/show/status-style tools rather than retryable write tools.
- Validation command:
  - `python -m pytest -q tests/contracts/test_cli_command_help.py tests/contracts/test_cli_name_uniqueness.py tests/contracts/test_json_schema_derivation.py tests/contracts/test_tool_schema_runtime_parity.py tests/integration/test_mcp_stdio_server.py tests/security/test_mcp_stdio_boundary.py tests/golden/test_cli_mcp_parity.py`
  - Result: `68 passed in 4.62s`.

## Duplicate/overlap review

Reviewed `existing-audit-family-inventory.json` for CLI/MCP-related closed items. Relevant closed matches include:

- `trade-trace-hd2r` — "SIMP-001: Centralize CLI and dispatcher error-envelope construction".
- `trade-trace-ads4` — "Stdio MCP validation failures bypass the Trade Trace error envelope".
- `trade-trace-pybt` — "CLI parser documents repeated/comma array flags but passes strings or last value".
- `trade-trace-kynj` — "Unknown CLI commands bypass the JSON error-envelope contract".
- `trade-trace-lum` — "Malformed CLI --*-json input bypasses JSON error-envelope contract".
- `trade-trace-30u` — "Choose strict or extensible semantics for ToolContext.meta_hints unknown keys".
- `trade-trace-r5k` — "Reject stray positional CLI tokens after valid command resolution".
- `trade-trace-3i33` — "Fill missing tool schemas and CLI help for agent-safe MCP usage".
- `trade-trace-il2f` — "SIMP-011: Single-source MCP setup docs and tool-registry discovery guidance".
- `trade-trace-pqp2` — "Pin future MCP stdio security boundary before transport implementation".

Observed current source lines indicate these areas are addressed rather than regressed. Therefore no `regression-of-closed` or `delta-only` materialization is recommended from this lane.

## Per-candidate records

No accepted candidates.

### Rejected / not materialized observations

#### Observation CLI-MCP-OBS-001 — read/status/deferred tools without explicit JSON schemas

- **candidate id**: `CLI-MCP-OBS-001`
- **title**: Some registered read/status/deferred tools have no explicit `json_schema`.
- **remediation_track**: none / rejected
- **owner_track**: cli-mcp-tooling
- **affected paths/symbols**:
  - `src/trade_trace/tools/journal.py:399-463` (`journal.init`, `journal.status`, `journal.schema`, `journal.rescan_scoring`, `journal.rebuild_projections` registrations)
  - `src/trade_trace/tools/admin.py:936-944` (`model.warm` deferred unsupported-capability registration)
  - registry probe also reported `resolve.pending`, `review.bundle`, `signal.scan`, `strategy.list`, `strategy.show`, `reflection.prompt_for_outcome` without schemas.
- **observed facts with file:line evidence**:
  - `ToolRegistry.register()` derives schemas only when `json_schema` is supplied or `example_minimal` is present (`src/trade_trace/contracts/tool_registry.py:169-174`).
  - `mcp_server._list_tools()` substitutes an empty object schema when a registration has no schema (`src/trade_trace/mcp_server.py:162-167`).
  - Write tools observed in this lane use examples/schema registration, e.g. `journal.config_set`, `model.import`, `memory.reindex`, `keyring.revoke` pass `**_examples_for(...)` (`src/trade_trace/tools/admin.py:905-970`), and example payloads are centralized in `WRITE_TOOL_EXAMPLES` (`src/trade_trace/tools/_examples.py:22-38`).
  - Targeted schema/runtime contract tests passed.
- **inferences**: For no-argument or primarily read/deferred tools, empty MCP schemas are acceptable under current contract tests. This is not sufficient evidence for a bug or debt candidate.
- **assumptions**: The current contract intentionally requires write tools to be schema-backed; read/list/status tools may expose `{}` when no arguments are accepted or when runtime validation handles optional fields.
- **open questions**: None requiring materialization; parent docs lane may separately decide whether every read tool should advertise optional args for ergonomics.
- **validation command/gap**: `test_write_tools_have_schemas.py` was not included in my targeted run, but `test_tool_schema_runtime_parity.py`, CLI help, JSON schema derivation, MCP stdio, and parity tests passed. Optional broader command: `python -m pytest -q tests/contracts/test_write_tools_have_schemas.py`.
- **prior_match_status**: `covered-by-closed` / `not-additive` relative to `trade-trace-3i33` and related schema-help work.
- **duplicate/overlap notes**: Similar to closed schema/help backlog; current evidence does not show a regression.
- **recommended disposition**: Reject; no Bead.
- **proposed Bead title/type/labels/acceptance if accepted**: N/A.

## Per-assigned-manifest-row treatment

| Manifest row | Path | Treatment | Notes |
| ---: | --- | --- | --- |
| 138 | `src/trade_trace/cli.py` | opened + contract-checked | Directly read. Checked CLI argument parsing, command resolution, error envelopes, NDJSON streaming, exit-code mapping. |
| 162 | `src/trade_trace/contracts/json_schema_derive.py` | opened + contract-checked | Directly read. Checked schema derivation, optional transport controls, ReportFilter special case. |
| 164 | `src/trade_trace/contracts/tool_registry.py` | opened + contract-checked | Directly read. Checked registration, CLI collision detection, metadata, schema derivation hook. |
| 172 | `src/trade_trace/mcp_server.py` | opened + contract-checked | Directly read. Checked tool specs, secret hint guard, stdio validation envelope, SDK server wiring. |
| 217 | `src/trade_trace/tools/__init__.py` | opened | Thin export module; no dead/reachability concern beyond `ToolError` export. |
| 218 | `src/trade_trace/tools/_examples.py` | opened + searched | Central write-tool examples for schema/help; sampled top section and used registry probe. |
| 219 | `src/trade_trace/tools/_helpers.py` | searched | Included in source-scoped search; helper use crosses tool handlers. No lane-specific candidate. |
| 220 | `src/trade_trace/tools/_report_filter_errors.py` | searched | Source search found centralized unsupported filter conversion; no CLI/MCP-specific issue. |
| 221 | `src/trade_trace/tools/admin.py` | opened + searched | Inspected registration block and schema/example use for admin/model/keyring tools. |
| 222 | `src/trade_trace/tools/csv_import.py` | searched | Registration/source search; no dispatcher/schema/error-envelope candidate. |
| 223 | `src/trade_trace/tools/decision_matrix.py` | searched | Registration/source search; no dispatcher/schema/error-envelope candidate. |
| 224 | `src/trade_trace/tools/errors.py` | opened | Directly read `ToolError` envelope exception type. |
| 225 | `src/trade_trace/tools/export.py` | searched | Registration/source search; no CLI/MCP-specific candidate. |
| 226 | `src/trade_trace/tools/fixture.py` | searched | Registration/source search; no CLI/MCP-specific candidate. |
| 227 | `src/trade_trace/tools/ideas.py` | searched | Registration/source search; write examples/schema covered by central registry probe. |
| 228 | `src/trade_trace/tools/imports.py` | searched | Registration/source search; import stubs noted but no lane-specific additive candidate. |
| 229 | `src/trade_trace/tools/journal.py` | opened + searched | Inspected registration block including `tool.schema`; no additive candidate. |
| 230 | `src/trade_trace/tools/journal_bundle_status.py` | searched | Registration/source search; no lane-specific candidate. |
| 231 | `src/trade_trace/tools/ledger.py` | searched | Registration/source search; large domain tool file outside decisive CLI/MCP claim except registry/examples. |
| 232 | `src/trade_trace/tools/market_scan.py` | searched | Registration/source search; no lane-specific candidate. |
| 233 | `src/trade_trace/tools/memory.py` | searched | Registration/source search; no lane-specific candidate. |
| 234 | `src/trade_trace/tools/playbook.py` | searched | Registration/source search; no lane-specific candidate. |
| 235 | `src/trade_trace/tools/reflection.py` | searched | Registration/source search; no lane-specific candidate. |
| 236 | `src/trade_trace/tools/reports.py` | searched | Registration/source search; filter-error centralization observed but no additive candidate. |
| 237 | `src/trade_trace/tools/review_bundle.py` | searched | Registration/source search; no CLI/MCP-specific candidate. |
| 238 | `src/trade_trace/tools/signals.py` | searched | Registration/source search; no CLI/MCP-specific candidate. |
| 239 | `src/trade_trace/tools/strategy.py` | searched | Registration/source search; no CLI/MCP-specific candidate. |

## Lens notes

### Bughunt / API contract

No accepted bug candidates. The historically problematic seams (unknown command, malformed `--*-json`, stray argv, MCP stdio validation, repeated CLI flags, schema/help discovery) have source evidence and passing targeted tests.

### Deadcode / reachability

No accepted dead-code candidates. The lane contains public CLI/MCP/tool surfaces registered through `build_registry()` (`src/trade_trace/core.py:51-77`). I did not use generated/cache/build artifacts for reachability claims. Deferred/stub tools such as `model.warm` and `journal.rescan_scoring` are explicitly registered public contracts with descriptions rather than unreachable code (`src/trade_trace/tools/admin.py:936-944`, `src/trade_trace/tools/journal.py:429-439`).

### Technical debt

No accepted technical-debt candidates. The most likely debt areas are covered by recent closed items and source evidence shows implemented centralization: CLI error envelope helper, registry schema derivation, meta-hint extensibility, and MCP stdio boundary validation.

### Simplification

No accepted simplification candidates. Error-envelope construction is already centralized on the CLI side (`_emit_cli_error`) and dispatch-side exception conversion is centralized in `dispatch()`. Tool examples and schema derivation are centralized enough that further abstraction would need stronger evidence than this lane found.

## Caveats

- I performed targeted rather than full-suite validation.
- For very large domain tool files (`ledger.py`, `memory.py`, `playbook.py`, etc.), I used source-scoped searches and registry/contract probes rather than line-by-line full reads because this lane's decisive scope is CLI/MCP/dispatcher/schema/error-envelope behavior.
- I did not create/update Beads and did not modify source, tests, product docs, package files, or configuration.

## Side-effect declaration

Only file created/modified by this subagent: `docs/reviews/repo-audit-20260521T173511Z/lane-cli-mcp-tooling.md`. No destructive commands, package-manager cleanup, installers, pushes, publishes, formatters, Beads writes, or shared-service mutations were run.
