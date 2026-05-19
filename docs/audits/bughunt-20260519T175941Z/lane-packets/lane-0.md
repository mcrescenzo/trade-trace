summary:
  what_i_did:
    - Performed read-only review of CLI/MCP/contracts/tool surfaces under /home/hermes/code/trade-trace.
    - Opened and inspected primary in-scope implementation files:
      - src/trade_trace/cli.py
      - src/trade_trace/mcp_server.py
      - src/trade_trace/core.py
      - src/trade_trace/contracts/tool_registry.py
      - src/trade_trace/contracts/json_schema_derive.py
      - src/trade_trace/contracts/report_filter.py
      - src/trade_trace/contracts/envelope.py
      - src/trade_trace/tools/memory.py
      - src/trade_trace/tools/reports.py
      - src/trade_trace/tools/ledger.py
    - Compared implementation against docs/architecture/contracts.md and relevant tests/docs.
    - Ran safe local probes only; no repository edits, package installs, Beads mutations, pushes, or destructive commands.

candidate_findings:
  - id: cli-contract-unknown-command-raw-systemexit
    title: Unknown CLI commands bypass the JSON error-envelope contract
    severity: P2
    confidence: confirmed
    domain: cli-mcp-contracts-tools
    bug_class: cli_error_envelope_contract
    evidence_type: source_review_and_runtime_probe
    evidence:
      - "docs/architecture/contracts.md:36-40 requires error-equal/envelope-equal results; lines 160-188 define every error as {ok:false,error,meta}; line 187 says meta has the same shape even on error."
      - "src/trade_trace/cli.py:122-137 _invocation_from_args raises SystemExit with raw text when no CLI invocation matches."
      - "src/trade_trace/cli.py:218 calls _invocation_from_args outside any try/except that would convert this to ErrorEnvelope."
      - "src/trade_trace/core.py:129-143 dispatch would return a typed NOT_FOUND ErrorEnvelope for unknown tools, but unknown CLI invocations never reach dispatch."
      - "tests/golden/test_journal_status_parity.py:78-95 says in docstring 'An unknown tool returns a NOT_FOUND error envelope', but the assertion only checks non-zero and catches SystemExit, so the contract violation is not tested."
      - "Runtime probe: TRADE_TRACE_HOME=$(mktemp -d) python3 -m trade_trace.cli nonexistent tool returned rc=1, stdout empty, stderr raw 'unknown command: nonexistent tool ... available commands ...'."
    failure_mode: >
      Agent callers invoking an invalid CLI command get no parseable JSON envelope on stdout, despite the contract stating errors are returned as ErrorEnvelope with stable code/details/meta. This makes CLI and MCP diverge: MCP/core unknown tool calls produce NOT_FOUND envelopes, while CLI command-resolution failures are raw argparse/SystemExit text.
    observed_vs_expected:
      observed: "rc=1; stdout is empty; stderr contains raw text beginning 'unknown command: nonexistent tool'."
      expected: "stdout contains a JSON ErrorEnvelope, likely code NOT_FOUND with details.entity_kind='tool', details.tool, known_tools, and meta.tool/actor_id/request_id/contract_version; exit code non-zero."
    reproduction_trace_path:
      - "cd /home/hermes/code/trade-trace"
      - "TRADE_TRACE_HOME=$(mktemp -d) python3 -m trade_trace.cli nonexistent tool"
      - "Observe empty stdout and raw stderr instead of JSON envelope."
    duplicate_overlap_analysis: >
      Not a duplicate of the existing malformed --*-json envelope bug. That bug concerns JSON argument decoding after a known tool is resolved; this one is the earlier command-resolution path for unknown CLI invocations. It also differs from stale docs about nonexistent commands: this is a live behavior contract failure for any typo/unregistered command.
    proposed_bead_body: |
      Unknown CLI commands currently raise SystemExit from _invocation_from_args before dispatch(), producing raw stderr and empty stdout. This violates docs/architecture/contracts.md §3-§4 error-envelope contract and CLI/MCP parity: dispatch() already returns NOT_FOUND ErrorEnvelope for unknown tool names, but invalid CLI invocations never reach it.

      Evidence:
      - src/trade_trace/cli.py:122-137 raises SystemExit for unknown commands.
      - src/trade_trace/cli.py:218 calls it outside conversion to ErrorEnvelope.
      - src/trade_trace/core.py:129-143 has the desired NOT_FOUND envelope behavior.
      - tests/golden/test_journal_status_parity.py:78-95 docstring claims an envelope but only asserts non-zero.

      Repro:
      TRADE_TRACE_HOME=$(mktemp -d) python3 -m trade_trace.cli nonexistent tool
      Actual: rc=1, stdout empty, raw stderr.
      Expected: stdout JSON ErrorEnvelope with code NOT_FOUND and standard meta.
    acceptance_criteria:
      - "Unknown CLI invocations return a JSON ErrorEnvelope on stdout."
      - "Error code is NOT_FOUND or another documented stable code with details.entity_kind='tool'."
      - "meta.tool, meta.actor_id, meta.request_id, and meta.contract_version are present."
      - "Exit code remains non-zero."
      - "Golden/contract test asserts parseable JSON, not only non-zero/SystemExit."
      - "Known-command stray args and malformed --*-json behavior remain unchanged."
    validation_command: >
      TRADE_TRACE_HOME=$(mktemp -d) python3 -m trade_trace.cli nonexistent tool 2>/tmp/tt.err | python3 -m json.tool
    risks_uncertainty: >
      Tool name for meta on an unmapped CLI command needs a chosen convention, e.g. '<unknown>' or the raw joined tokens. The failure itself is confirmed.

  - id: cli-contract-array-flags-not-implemented
    title: CLI parser documents repeated/comma array flags but passes strings or last value
    severity: P2
    confidence: confirmed
    domain: cli-mcp-contracts-tools
    bug_class: cli_argument_contract_mismatch
    evidence_type: source_review_and_python_probe
    evidence:
      - "docs/architecture/contracts.md:52-54 states args keys become long flags, arrays use repeated flags or comma-separated list, and objects use --<key>-json."
      - "src/trade_trace/cli.py:63-119 _parse_kv_args has no array handling. Repeated flags overwrite prior values at line 112; comma-separated values remain strings."
      - "Probe: _parse_kv_args(['--node-types','observation','--node-types','reflection']) returned {'node_types': 'reflection'}."
      - "Probe: _parse_kv_args(['--node-types','observation,reflection']) returned {'node_types': 'observation,reflection'}."
      - "src/trade_trace/tools/memory.py:638-645 memory.recall expects node_types to be a non-empty list, so both documented CLI encodings fail or silently drop values."
      - "src/trade_trace/tools/memory.py:663-669 memory.recall similarly expects strategies to be a non-empty list."
    failure_mode: >
      Agents following the published CLI contract cannot pass array-valued arguments via repeated flags or comma-separated lists. Repeated flags silently keep only the last value; comma lists remain a string and then fail downstream validation for tools that require lists. This breaks documented CLI/MCP parity for array args and can silently broaden/narrow operations if the overwritten list member was intended as part of a filter.
    observed_vs_expected:
      observed:
        repeated_flags: "{'node_types': 'reflection'}"
        comma_list: "{'node_types': 'observation,reflection'}"
      expected:
        repeated_flags: "{'node_types': ['observation', 'reflection']}"
        comma_list: "{'node_types': ['observation', 'reflection']}"
    reproduction_trace_path:
      - "cd /home/hermes/code/trade-trace"
      - "python3 - <<'PY'\nfrom trade_trace.cli import _parse_kv_args\nprint(_parse_kv_args(['--node-types','observation','--node-types','reflection']))\nprint(_parse_kv_args(['--node-types','observation,reflection']))\nPY"
      - "For end-to-end behavior, initialize a temp journal and call memory recall with --node-types observation,reflection; it will not reach memory.recall as a list."
    duplicate_overlap_analysis: >
      Not a duplicate of source.add schema/example mismatch or malformed --*-json. This is the generic CLI transport's documented array encoding contract being unimplemented. It affects any tool arg that expects list values, including memory.recall node_types/strategies and likely report filters if exposed through non-json convenience flags later.
    proposed_bead_body: |
      The CLI contract says arrays may be passed as repeated flags or comma-separated lists, but _parse_kv_args only stores scalar values. Repeating a flag overwrites the previous value, and comma-separated values are left as plain strings.

      Evidence:
      - docs/architecture/contracts.md:52-54 documents array encoding.
      - src/trade_trace/cli.py:63-119 parses each --key value as one scalar and writes out[domain_key] = value.
      - memory.recall expects node_types and strategies as lists in src/trade_trace/tools/memory.py:638-669.
      - Probe:
        _parse_kv_args(['--node-types','observation','--node-types','reflection'])
        -> {'node_types': 'reflection'}
        _parse_kv_args(['--node-types','observation,reflection'])
        -> {'node_types': 'observation,reflection'}

      This breaks CLI/MCP parity for array arguments and makes docs-following agent calls fail or silently lose values.
    acceptance_criteria:
      - "Repeated scalar flags accumulate into a list for array-capable args, or docs are corrected to require --*-json only."
      - "Comma-separated documented array values are split consistently, or docs are corrected."
      - "No regression for scalar flags where repeat should remain invalid or last-value semantics are explicitly documented."
      - "Add contract tests for _parse_kv_args repeated flag and comma-list behavior using a real list-valued tool argument such as memory.recall node_types."
    validation_command: >
      python3 - <<'PY'
      from trade_trace.cli import _parse_kv_args
      assert _parse_kv_args(['--node-types','observation','--node-types','reflection'])['node_types'] == ['observation','reflection']
      assert _parse_kv_args(['--node-types','observation,reflection'])['node_types'] == ['observation','reflection']
      PY
    risks_uncertainty: >
      Generic comma splitting can be unsafe for string fields that legitimately contain commas. A schema-aware parser or docs correction to require --node-types-json may be safer than blanket splitting. The current mismatch is confirmed.

  - id: mcp-contract-many-tools-advertise-empty-input-schema
    title: MCP tool catalog exposes empty input schemas for most registered tools
    severity: P2
    confidence: confirmed
    domain: cli-mcp-contracts-tools
    bug_class: mcp_schema_contract_gap
    evidence_type: source_review_and_registry_probe
    evidence:
      - "docs/architecture/contracts.md:31-35 says every tool's input schema is exposed from the single registry used by both transports, and registered examples are auto-derived into JSON Schema when a tool does not supply an explicit schema."
      - "src/trade_trace/contracts/tool_registry.py:142-146 only derives json_schema if example_minimal is not None; otherwise json_schema remains None."
      - "src/trade_trace/mcp_server.py:80-84 maps missing registration.json_schema to input_schema: {} in mcp_tool_specs."
      - "src/trade_trace/mcp_server.py:153-157 sends inputSchema={} or {'type':'object','properties':{}} to the MCP SDK."
      - "Probe over default_registry/mcp_tool_specs: tool_count 66, empty_schema_count 55."
      - "Examples from empty-schema list: journal.init, journal.status, memory.recall, memory.reflect, memory.link, report.calibration, report.filter_schema, source.attach_to_thesis, strategy.create, strategy.update, tool.schema."
      - "src/trade_trace/tools/memory.py:1127-1174 registers all memory tools without example_minimal/json_schema, despite handlers requiring fields like node_type/body or query."
      - "src/trade_trace/tools/reports.py:508-518 registers report.filter_schema without schema, despite accepting optional mode validation/serialization."
    failure_mode: >
      MCP clients receive permissive or empty schemas for most tools, so validate_input=True cannot catch missing required fields, wrong shapes, or discover required arguments before invocation. This violates the schema-equal/introspection contract and makes agent tool planning unreliable. It also weakens MCP-side input validation compared with the documented design.
    observed_vs_expected:
      observed: "55 of 66 registered tools produce input_schema == {} from mcp_tool_specs/default registry."
      expected: "Every public tool has a meaningful JSON Schema, either explicit or derived, with required top-level fields and object/list shapes."
    reproduction_trace_path:
      - "cd /home/hermes/code/trade-trace"
      - "python3 - <<'PY'\nfrom trade_trace.core import default_registry\nfrom trade_trace.mcp_server import mcp_tool_specs\nreg=default_registry()\nempty=[s['name'] for s in mcp_tool_specs(reg) if s['input_schema']=={}]\nprint('tool_count', len(reg.names()), 'empty_schema_count', len(empty))\nprint(empty[:80])\nPY"
    duplicate_overlap_analysis: >
      Not a duplicate of the known source.add schema/example mismatch. That known issue is one tool with incorrect schema/example alignment. This finding is broader and concerns the MCP catalog exposing no schema at all for the majority of tools because registry registrations omit both example_minimal and explicit json_schema.
    proposed_bead_body: |
      MCP tool listing currently exposes empty input schemas for most registered tools. The contract says every tool's input schema is exposed from the shared registry and examples are auto-derived when explicit schemas are absent. In practice ToolRegistry only derives schemas when example_minimal is present; many tool registrations omit examples, and mcp_tool_specs converts missing schemas to {}.

      Evidence:
      - docs/architecture/contracts.md:31-35 states the schema exposure contract.
      - src/trade_trace/contracts/tool_registry.py:142-146 leaves json_schema=None when no example_minimal/json_schema is supplied.
      - src/trade_trace/mcp_server.py:80-84 exposes registration.json_schema or {}.
      - Probe: 66 tools registered, 55 with empty MCP input_schema.
      - Empty-schema tools include journal.init, memory.recall, memory.reflect, report.calibration, strategy.create, strategy.update, tool.schema.

      Consequence: MCP validate_input=True cannot validate or help agents discover required inputs for most tools.
    acceptance_criteria:
      - "All public tools returned by mcp_tool_specs have non-empty object input_schema with properties."
      - "Required top-level fields match handler requirements for write/read tools."
      - "Optional transport/control fields remain optional."
      - "Contract test fails if any registered public tool has input_schema == {} unless explicitly allowlisted as zero-arg."
      - "Zero-arg tools, if any, use {'type':'object','properties':{},'additionalProperties':false} or an intentional documented shape rather than unconstrained {}."
    validation_command: >
      python3 - <<'PY'
      from trade_trace.core import default_registry
      from trade_trace.mcp_server import mcp_tool_specs
      empty=[s['name'] for s in mcp_tool_specs(default_registry()) if not s['input_schema'] or s['input_schema']=={}]
      assert not empty, empty
      PY
    risks_uncertainty: >
      Some tools may intentionally accept flexible/advanced payloads, but the contract still promises exposed schemas. A small allowlist for true no-arg tools may be appropriate. The current 55/66 empty-schema count is confirmed.

coverage_accounting:
  files_opened:
    primary:
      - /home/hermes/code/trade-trace/src/trade_trace/cli.py
      - /home/hermes/code/trade-trace/src/trade_trace/mcp_server.py
      - /home/hermes/code/trade-trace/src/trade_trace/core.py
      - /home/hermes/code/trade-trace/src/trade_trace/contracts/tool_registry.py
      - /home/hermes/code/trade-trace/src/trade_trace/contracts/json_schema_derive.py
      - /home/hermes/code/trade-trace/src/trade_trace/contracts/report_filter.py
      - /home/hermes/code/trade-trace/src/trade_trace/contracts/envelope.py
      - /home/hermes/code/trade-trace/docs/architecture/contracts.md
    directly_relevant:
      - /home/hermes/code/trade-trace/src/trade_trace/tools/memory.py
      - /home/hermes/code/trade-trace/src/trade_trace/tools/reports.py
      - /home/hermes/code/trade-trace/src/trade_trace/tools/ledger.py
      - /home/hermes/code/trade-trace/tests/golden/test_journal_status_parity.py
    search_reviewed:
      - /home/hermes/code/trade-trace/tests/contracts/*
      - /home/hermes/code/trade-trace/tests/golden/*
      - /home/hermes/code/trade-trace/docs/IDE_MCP_SETUP.md
      - /home/hermes/code/trade-trace/docs/CLAUDE_DESKTOP.md
      - /home/hermes/code/trade-trace/docs/CLAUDE_CODE.md
      - /home/hermes/code/trade-trace/docs/AI_AGENT_MCP_GETTING_STARTED.md
      - /home/hermes/code/trade-trace/docs/AGENT_GUIDE.md
      - historical audit search hits under docs/audits for duplicate analysis
  commands_run:
    - command: "python - <<'PY' ... PY"
      result: "Failed because python executable not found; rc=127. This was non-mutating."
    - command: "python3 probe for _parse_kv_args and mcp_tool_specs"
      result: >
        Confirmed repeated array flags overwrite prior value, comma arrays remain strings,
        and default registry has 66 tools with 55 empty MCP input schemas.
    - command: "TRADE_TRACE_HOME=$(mktemp -d) python3 -m trade_trace.cli nonexistent tool"
      result: >
        Confirmed rc=1, stdout empty, stderr raw unknown-command text; no JSON envelope.
  areas_not_inspected_or_limited:
    - "Did not perform exhaustive line-by-line review of every tool module outside direct CLI/MCP/schema relevance."
    - "Did not run full pytest suite; only safe targeted Python probes were needed for these contract findings."
    - "Did not inspect storage internals except where tool behavior required it; storage was out of scope unless needed to prove contract failure."
    - "Did not start long-running MCP stdio server; reviewed mcp_server.py and in-process mcp_tool_specs/mcp_call behavior instead."
  side_effect_caveats:
    - "No repository files were edited or created."
    - "No Beads were created/updated/closed."
    - "No package managers/installers/destructive commands were run."
    - "Temp files/directories under /tmp were created by shell probes, including mktemp TRADE_TRACE_HOME and /tmp/tt_out /tmp/tt_err from the unknown-command probe."
    - "No shared service or project DB mutation was performed; TRADE_TRACE_HOME was temp-scoped for CLI runtime probe."

files_created_or_modified: []