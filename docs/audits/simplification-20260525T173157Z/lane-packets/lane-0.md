## Read-only simplification review lane report: `contracts-cli-mcp`

### Coverage accounting

**Repository / commit checked**
- Workdir: `/home/hermes/code/trade-trace`
- `git rev-parse HEAD`: `d37136e9684138d9f9540f2a71860f36eba354f5`
- `git status --short`: no output observed before hash, indicating no tracked/untracked changes surfaced by the command.

**Files opened / probed**
- `src/trade_trace/cli.py`
- `src/trade_trace/core.py`
- `src/trade_trace/mcp_server.py`
- `src/trade_trace/contracts/tool_registry.py`
- `src/trade_trace/contracts/envelope.py`
- `src/trade_trace/contracts/json_schema_derive.py`
- `src/trade_trace/contracts/report_filter.py`
- `src/trade_trace/contracts/grammar.py`
- `src/trade_trace/contracts/errors.py`
- `tests/golden/test_cli_mcp_parity.py`
- `tests/integration/test_mcp_stdio_server.py`
- `tests/contracts/test_cli_parse_kv_args.py`
- `tests/contracts/test_tool_schema_runtime_parity.py`
- `tests/contracts/test_write_tools_have_schemas.py`
- `tests/contracts/test_envelope.py`
- `tests/contracts/test_min_sample_validation_parity.py`
- `tests/security/test_mcp_stdio_boundary.py`
- `docs/architecture/contracts.md`

**Commands run**
- `git status --short && git rev-parse HEAD`
- Search for `jsonschema.validate` under `src/trade_trace`
- Search for `_build_stdio_server|validate_input=False|Input validation error` under `tests`

**Areas not deeply inspected**
- Individual tool handler internals outside the assigned dispatcher/contracts surface.
- Storage internals, reports internals, Polymarket adapter implementation.
- Broad docs style outside `docs/architecture/contracts.md`.
- Full test execution was not run; this was a read-only review lane and evidence was gathered by source/test inspection plus safe commands.

**Files created or modified**
- None.

---

# Candidate CLCM-001

## id
`CLCM-001`

## title
Unify CLI and MCP-stdio schema-validation policy behind a shared contract helper

## domain
`contracts-cli-mcp`

## complexity class
Contract drift / duplication / behavior-preserving validation centralization

## coordinator disposition recommendation
`accept`

## size
Small-to-medium

## risk
Medium, because schema validation is a public transport behavior and existing stdio tests intentionally pin full validation for some cases.

## priority
Medium

## confidence
High that duplication/drift exists; medium that the exact behavior-preserving refactor should be done now because some current divergence appears intentional.

---

## observed facts

1. The CLI performs JSON Schema validation locally in `main`, but only converts a selected set of validators into a CLI-side error envelope.
   - Evidence:
     - `src/trade_trace/cli.py:436-443` documents that CLI validation is narrowed so handlers keep ownership of friendlier `type`, `enum`, and `required` messages.
     - `src/trade_trace/cli.py:444-448` defines `_NUMERIC_BOUND_VALIDATORS`.
     - `src/trade_trace/cli.py:455-475` calls `jsonschema.validate`, emits an envelope only when `exc.validator in _NUMERIC_BOUND_VALIDATORS`, and otherwise falls through to the handler.

2. The MCP stdio boundary performs full JSON Schema validation and converts every `jsonschema.ValidationError` into a stdio boundary `VALIDATION_ERROR` envelope.
   - Evidence:
     - `src/trade_trace/mcp_server.py:197-214` looks up the registration schema, calls `jsonschema.validate(instance=arguments, schema=schema)`, and returns `_stdio_validation_error(...)` for any `jsonschema.ValidationError`.
     - There is no corresponding validator allowlist in `mcp_server.py`.

3. The in-process MCP shim used by many parity tests does not perform schema validation before dispatch.
   - Evidence:
     - `src/trade_trace/mcp_server.py:99-125` defines `mcp_call`, which directly calls `dispatch(...)` and then sets `envelope.meta.mcp_transport_hints = {}`.
     - `tests/golden/test_cli_mcp_parity.py:60-67` uses `mcp_call(...)` for MCP-side parity, not `_build_stdio_server`.

4. There is already a narrow stdio-vs-CLI parity test for negative numeric bounds, suggesting this drift has caused at least one past bug and now requires special-case coverage.
   - Evidence:
     - `tests/contracts/test_min_sample_validation_parity.py:1-18` says the CLI previously skipped MCP-stdio schema-derived `minimum: 1` constraints.
     - `tests/contracts/test_min_sample_validation_parity.py:42-53` drives `_build_stdio_server()` directly so stdio schema validation runs.
     - `tests/contracts/test_min_sample_validation_parity.py:64-93` separately asserts stdio and CLI reject negative `min_sample` with `validator == "minimum"`.

5. Stdio boundary tests intentionally pin full schema validation for `required`.
   - Evidence:
     - `tests/security/test_mcp_stdio_boundary.py:243-269` registers `boundary.echo` with `required: ["message"]`, calls stdio with `{}`, and asserts a `VALIDATION_ERROR` envelope with `validator == "required"`.

6. The docs state parity goals but explicitly exempt byte identity and transport metadata.
   - Evidence:
     - `docs/architecture/contracts.md:33-45` requires schema/error/envelope equivalence while excluding MCP framing, stdio streaming, transport metadata, and CLI prose byte identity.

---

## inferences

1. There are currently at least three validation paths:
   - CLI partial schema-boundary validation in `cli.py`.
   - MCP stdio full schema-boundary validation in `mcp_server.py`.
   - Dispatcher/handler validation reached by `mcp_call` and by CLI for non-allowlisted schema failures.

2. This creates accidental complexity because future schema-validation policy changes must be replicated or consciously diverged across multiple files and test styles.

3. The divergence is behaviorally meaningful:
   - CLI intentionally lets `required`, `type`, and `enum` failures fall through to handler logic for friendlier messages.
   - MCP stdio currently intercepts those same validator classes before dispatch.

4. Because `tests/golden/test_cli_mcp_parity.py` uses `mcp_call`, it does not fully exercise real MCP stdio validation behavior. Separate stdio tests partially compensate.

---

## assumptions

1. Public stdio behavior is intended to remain stable unless explicitly changed.
2. The desired simplification should preserve currently pinned behavior unless maintainers intentionally decide to broaden parity.
3. Existing handler-level validation produces more domain-specific messages for at least some `required`, `type`, and `enum` failures, as stated in `cli.py:440-474`.

---

## open questions

1. Should MCP stdio continue to enforce all schema validators at the boundary, or should it match the CLI’s narrowed validator policy so handlers own `required`, `type`, and `enum` errors?
2. If stdio keeps full validation, should the policy be documented as an intentional transport divergence from CLI and in-process MCP?
3. Should `mcp_call` remain a pure dispatch shim, or should tests that claim MCP transport parity use a stdio/server helper whenever schema-boundary behavior matters?

---

## current behavior contract

- CLI:
  - Parses flags, applies global transport flags, validates only selected schema validators locally, dispatches otherwise.
  - Numeric/pattern/length/item bound failures become CLI-side `VALIDATION_ERROR` envelopes before handler dispatch.
  - Required/type/enum failures are intentionally left to handlers where possible.

- MCP stdio:
  - Requires arguments to be an object.
  - Applies full JSON Schema validation before dispatch.
  - Any schema failure becomes a stdio boundary `VALIDATION_ERROR`.

- In-process `mcp_call`:
  - Directly invokes shared `dispatch`.
  - Adds `meta.mcp_transport_hints = {}`.
  - Does not validate schema at MCP boundary.

---

## complexity cost

- Duplicate policy: both `cli.py` and `mcp_server.py` directly call `jsonschema.validate`, but with different failure-handling semantics.
- Hidden transport drift: parity tests using `mcp_call` can pass while real stdio behavior differs for schema errors.
- Special-case test scaffolding: `test_min_sample_validation_parity.py` must drive stdio directly to cover behavior not present in `mcp_call`.
- Future schema policy changes require editing or auditing multiple modules and multiple test styles.

---

## expected benefit

- A shared helper would make intentional divergence explicit and local.
- Future schema-boundary changes would be easier to reason about.
- CLI/MCP parity tests could call the same helper or assert known differences cleanly.
- Reduces chance of another validator-class drift like the negative `min_sample` issue documented in `tests/contracts/test_min_sample_validation_parity.py`.

---

## suggested refactor shape

Introduce a small contract-layer helper, for example in `src/trade_trace/contracts/schema_validation.py`:

```python
@dataclass(frozen=True)
class SchemaValidationFailure:
    message: str
    field: str | None
    validator: str
    validator_value: Any

CLI_BOUNDARY_VALIDATORS = frozenset({
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "multipleOf", "minLength", "maxLength", "minItems", "maxItems",
    "pattern",
})

def validate_input_schema(
    *,
    instance: dict[str, Any],
    schema: dict[str, Any] | None,
    boundary_policy: Literal["cli_narrow", "stdio_full"],
) -> SchemaValidationFailure | None:
    ...
```

Then:
- `cli.py` calls the helper with `boundary_policy="cli_narrow"`.
- `mcp_server.py` calls the helper with `boundary_policy="stdio_full"` if current behavior is preserved.
- The helper owns construction of normalized failure details:
  - `tool`
  - `field`
  - `validator`
  - `validator_value`

Optional stronger simplification if behavior owners agree:
- Use one shared policy for both CLI and stdio, likely the current CLI-narrow policy, so handlers own friendly `required`, `type`, and `enum` messages on both transports.
- This would require updating `tests/security/test_mcp_stdio_boundary.py:243-269` if `required` stops being a stdio-boundary failure.

---

## non-goals

- Do not change the envelope model.
- Do not change tool registration or schema derivation.
- Do not remove handler-level validation.
- Do not rewrite CLI parsing.
- Do not broaden into report/storage internals.

---

## behavior-preservation plan

If preserving current behavior:
1. Add the shared helper with two named policies matching today’s behavior.
2. Move `_NUMERIC_BOUND_VALIDATORS` from `cli.py:444-448` into the helper as the CLI policy.
3. Replace CLI’s local `jsonschema.validate` block at `cli.py:455-475` with helper call.
4. Replace MCP stdio’s local `jsonschema.validate` block at `mcp_server.py:197-214` with helper call.
5. Keep `_stdio_validation_error(...)` envelope emission and `_emit_cli_error(...)` exit mapping unchanged.
6. Add/adjust tests to assert:
   - CLI still rejects `minimum` failures.
   - Stdio still rejects `required` failures if preserving full stdio validation.
   - CLI still lets a known handler-owned validator class fall through, if such a test already exists or can be bounded.

If changing behavior to unified parity:
1. First create explicit failing characterization tests for one `required` or `enum` discrepancy between CLI and stdio.
2. Decide desired message/details contract.
3. Update docs and tests together.

---

## validation command / gap

Suggested validation commands:
- `pytest tests/contracts/test_min_sample_validation_parity.py`
- `pytest tests/security/test_mcp_stdio_boundary.py`
- `pytest tests/golden/test_cli_mcp_parity.py`
- `pytest tests/contracts/test_tool_schema_runtime_parity.py`

Validation gap:
- Existing golden parity tests use `mcp_call`, not real stdio validation, so they do not fully protect CLI-vs-stdio schema-boundary behavior.

---

## why-not-style

This is not a formatting or naming concern. The evidence shows two concrete implementations of schema validation with materially different validator policies and separate tests to compensate. The proposed change reduces accidental duplication while preserving public behavior through named policies.

---

## intentional complexity / false-positive check

Some complexity is intentional:
- `cli.py:440-474` intentionally narrows validation so handlers can return friendlier messages.
- `mcp_server.py:179` uses `@server.call_tool(validate_input=False)`, then implements its own envelope-shaped validation, likely to avoid raw SDK validation errors and preserve Trade Trace envelopes.
- `tests/security/test_mcp_stdio_boundary.py:243-269` intentionally pins stdio boundary schema-validation failures.

Therefore, the recommendation is not to blindly remove validation. The simplification is to centralize and name the policy so the intentional divergence is visible and testable.

---

## duplicate / overlap notes vs prior beads

- This overlaps conceptually with prior “CLI/MCP parity” and “tool-schema derivation” work but does not duplicate the listed closed coverage:
  - It is not proposing general CLI/dispatcher error-envelope centralization.
  - It is not proposing schema derivation changes.
  - It is specifically about duplicated schema-validation policy between CLI and MCP stdio, plus the mismatch between stdio and `mcp_call` parity coverage.
- The existing `trade-trace-cms2`-style coverage appears to have patched one validator class (`minimum`) rather than centralizing the broader policy.

---

## proposed Bead title

Centralize CLI/MCP stdio input-schema validation policy

## proposed Bead body

The CLI and MCP stdio transports both perform JSON Schema validation before dispatch, but the validation policy is duplicated and differs by transport. CLI validates only a narrow set of schema validators before dispatch so handlers retain friendly `required`/`type`/`enum` messages (`src/trade_trace/cli.py:436-475`). MCP stdio validates the full schema and converts every `jsonschema.ValidationError` into a boundary `VALIDATION_ERROR` (`src/trade_trace/mcp_server.py:197-214`). In-process `mcp_call` bypasses schema validation entirely (`src/trade_trace/mcp_server.py:99-125`), so golden parity tests using it do not cover real stdio schema-boundary behavior.

Create a small shared contract helper that runs schema validation and returns normalized failure details under an explicit policy, e.g. `cli_narrow` and `stdio_full`. Wire CLI and MCP stdio through the helper while preserving current behavior. This makes the intentional transport divergence explicit and avoids future validator drift like the negative `min_sample` issue covered by `tests/contracts/test_min_sample_validation_parity.py`.

## proposed acceptance criteria

- A shared helper owns schema validation and normalized failure detail extraction for CLI and MCP stdio.
- CLI behavior remains unchanged for:
  - numeric/bound validation failures becoming CLI-side `VALIDATION_ERROR`;
  - handler-owned `required`/`type`/`enum` failures where currently intentional.
- MCP stdio behavior remains unchanged unless explicitly decided otherwise:
  - wrong non-object `arguments` still returns the existing Trade Trace error envelope;
  - full schema validation still rejects `required` failures if preserving current behavior.
- Existing tests pass:
  - `tests/contracts/test_min_sample_validation_parity.py`
  - `tests/security/test_mcp_stdio_boundary.py`
  - `tests/golden/test_cli_mcp_parity.py`
  - `tests/contracts/test_tool_schema_runtime_parity.py`
- New or updated test documents that `mcp_call` is an in-process dispatch shim and does not represent stdio boundary validation, or moves schema-boundary parity tests to a shared stdio helper.

---

# Rejected / deferred observations

## R-001: CLI command help and MCP tool spec both render metadata

**Disposition:** `reject`

**Evidence**
- CLI help prints metadata sections in `src/trade_trace/cli.py:206-227`.
- MCP specs fold usage summary and first example into description in `src/trade_trace/mcp_server.py:66-78`.

**Why rejected**
- This is partly transport-specific presentation, not obvious accidental complexity.
- Prior coverage explicitly included docs single-sourcing / self-describing metadata, so this risks duplicating closed work.
- No clear bounded behavior-preserving simplification emerged beyond style-level extraction.

---

## R-002: `ToolRegistry.mark` cannot explicitly clear nullable metadata fields

**Disposition:** `defer`

**Evidence**
- `ToolRegistry.mark` parameters default to `None`, and `replace(... redirect=(redirect if redirect is not None else reg.redirect))` preserves existing values at `src/trade_trace/contracts/tool_registry.py:250-272`.
- Overlay passes `redirect=None` for folded/removed tools at `src/trade_trace/core.py:150-157`.

**Why deferred**
- Current observed use does not need to clear a pre-existing redirect because initial `redirect` is already `None`.
- This is a latent API limitation rather than current accidental complexity with demonstrated cost.
- No behavior-preservation need was proven in assigned scope.

---

## R-003: Local `_NUMERIC_BOUND_VALIDATORS` constant inside `main`

**Disposition:** `merge into CLCM-001`

**Evidence**
- Defined inside `main` at `src/trade_trace/cli.py:444-448`.

**Why merged**
- On its own, this is too small and style-adjacent.
- It becomes material as part of centralizing schema-validation policy across CLI and MCP stdio.

---

# Final summary

- I performed a read-only review of the assigned contracts/CLI/MCP/registry/envelope/schema surface.
- I found one concrete additive simplification candidate: centralize schema-validation policy for CLI and MCP stdio while preserving current behavior via explicit named policies.
- I rejected/deferred smaller observations that were either intentional transport presentation, already-covered prior work, or lacked demonstrated current cost.
- I created no files, modified no files, and created/updated no Beads or issues.
- No issues encountered.