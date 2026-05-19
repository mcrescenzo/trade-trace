Read-only review complete for cli-mcp-contracts-tooling.

What I did:
- Inspected the assigned paths:
  - src/trade_trace/cli.py
  - src/trade_trace/mcp_server.py
  - src/trade_trace/contracts/*.py
  - src/trade_trace/tools/_examples.py
  - src/trade_trace/tools/_helpers.py
  - src/trade_trace/tools/errors.py
  - tests/contracts/*
  - tests/golden/*
- Also read src/trade_trace/core.py and src/trade_trace/tools/journal.py where dispatch and tool.schema behavior live.
- Ran safe read-only commands:
  - git status --short && git rev-parse HEAD
  - PYTHONPATH=src pytest -q tests/contracts tests/golden --collect-only
  - PYTHONPATH=src pytest -q tests/golden/test_cli_mcp_parity.py tests/contracts/test_agent_ergonomics.py::test_tool_schema_catalog_lists_every_registered_tool tests/golden/test_journal_status_parity.py::test_cli_error_envelope_for_unknown_tool
  - PYTHONPATH=src python3 snippets to enumerate registry schema/example coverage and exercise CLI parsing/unknown-token behavior.

Repository state note:
- Current HEAD matched requested commit: a33e676ec9d22d6ec268686424521a3d2586f9dd.
- Working tree already had unrelated modifications/untracked audit docs before my review:
  - Modified: src/trade_trace/events/log.py, src/trade_trace/events/unit_of_work.py, several report modules, src/trade_trace/tools/journal.py
  - Untracked: audits/, docs/audits/
- I did not create or modify any files.

Validation run:
- Targeted collect:
  - 119 tests collected from tests/contracts and tests/golden.
- Targeted execution:
  - 6 passed in 0.16s.

Candidate technical-debt findings:

1. CLI silently ignores stray positional tokens after a valid command

Domain/lens:
- CLI/MCP contract drift
- Test debt
- Agent ergonomics / tooling drift

Evidence:
- src/trade_trace/cli.py lines 174-175:
  - _invocation_from_args() returns the longest matching command and leaves the rest as remaining args.
  - _parse_kv_args() only consumes tokens beginning with --; non-flag tokens are skipped.
- src/trade_trace/cli.py lines 43-47:
  - If a token does not start with "--", parser increments and continues.
- Reproduction command:
  - PYTHONPATH=src python3 -m trade_trace.cli journal status unexpected-token; echo rc=$?
- Observed result:
  - Returns ok=true journal.status envelope.
  - Exit code rc=0.
  - The unexpected positional token is silently ignored.

Concrete risk / carrying cost:
- CLI users and agents can issue malformed commands that appear successful, causing false-positive automation results.
- CLI/MCP parity becomes weaker: MCP has a strict tool name + JSON args shape, while CLI accepts accidental extra words without surfacing VALIDATION_ERROR.
- Shell-scripted agent workflows can hide prompt/argument construction bugs, especially when a copied command appends an accidental token.

Bounded paydown:
- After resolving the registered CLI invocation, reject any remaining non-flag positional tokens before _parse_kv_args().
- Return a typed error envelope rather than argparse prose if possible:
  - code: VALIDATION_ERROR
  - details: {field: "argv", unexpected_tokens: [...]}
- Preserve existing --key value and --key-json parsing behavior.

Validation:
- Add tests under tests/contracts or tests/golden:
  - tt journal status unexpected-token returns non-zero, likely exit code 2.
  - stdout remains a JSON error envelope.
  - valid current commands still pass.
  - CLI/MCP parity tests continue passing.


2. ToolContext meta_hints advertises extensible metadata, but dispatch silently drops all unknown hint keys

Domain/lens:
- Envelope/schema contract debt
- Integration-provider drift
- Type-schema debt

Evidence:
- src/trade_trace/contracts/tool_registry.py lines 78-82:
  - ToolContext.meta_hints is documented as a “write-back surface” for handlers that need to populate envelope meta.* fields.
  - It lists standard keys, but the surrounding language implies meta.* extensibility.
- src/trade_trace/contracts/envelope.py line 32:
  - Meta uses ConfigDict(extra="allow"), so the envelope model allows extra metadata fields.
- src/trade_trace/core.py lines 159-162:
  - _apply_hints() only applies keys if key in Meta.model_fields.
  - Any custom/extra meta_hints are silently ignored despite Meta allowing extra fields.

Concrete risk / carrying cost:
- Future report/tool authors may set ctx.meta_hints["new_contract_field"] expecting it to appear, because Meta.extra allows it and ToolContext describes meta_hints as the meta write-back surface.
- The silent drop creates contract drift that is hard to detect: tests may pass for existing standard fields while new envelope metadata never reaches agents.
- MCP/provider-specific transport metadata additions risk disappearing unless every new field is manually added to Meta.model_fields.

Bounded paydown:
- Pick one contract stance and encode it:
  1. Strict stance: document meta_hints as closed to Meta.model_fields and raise/return INVARIANT_VIOLATION if a handler emits an unknown hint.
  2. Extensible stance: let _apply_hints() set extra fields using setattr(meta, key, value) for all ctx.meta_hints, relying on Meta.extra="allow".
- Prefer adding a small helper such as apply_meta_hints(meta, hints) with tests.

Validation:
- Unit test a fake registered handler that sets ctx.meta_hints["custom_hint"] = "x".
- Assert either:
  - custom_hint appears in dump_envelope(), if extensible stance is chosen; or
  - dispatch returns INVARIANT_VIOLATION / test catches an explicit failure, if strict stance is chosen.
- Regression-test existing standard hints:
  - event_id
  - dry_run
  - sample_warning
  - mcp_transport_hints


3. tool.schema registry surface exposes json_schema but registry never populates it for any tool

Domain/lens:
- Type-schema debt
- Docs-contract drift
- Tooling drift

Important non-duplication note:
- This is adjacent to the existing “inputSchema auto-derive” open theme, so I would not file this as a duplicate if that bead already covers registry schema population end-to-end.
- Distinct root cause observed here: the current public tool.schema response has a json_schema field wired through ToolRegistration, but every registered tool currently returns null, and tests only check example payloads for a small subset of write tools.

Evidence:
- src/trade_trace/contracts/tool_registry.py lines 99-102:
  - ToolRegistration includes json_schema: dict[str, Any] | None = None.
- src/trade_trace/tools/journal.py lines 269-285:
  - tool.schema returns "json_schema": reg.json_schema.
- Registry enumeration command:
  - PYTHONPATH=src python3 - <<'PY'
    from trade_trace.core import build_registry
    r=build_registry()
    print('tools', len(r.names()))
    for n in r.names():
        reg=r.get(n)
        if reg.json_schema is None:
            print('NO_SCHEMA', n, 'write' if reg.is_write else 'read')
    PY
- Observed result:
  - tools 61
  - Every listed tool printed NO_SCHEMA, including venue.add, decision.add, report.calibration, memory.retain, strategy.create, tool.schema itself.
- src/trade_trace/tools/journal.py lines 108-113 docstring for journal.schema says:
  - “Future write tools register their own schemas; this is the bootstrap version.”
- tests/contracts/test_agent_ergonomics.py lines 80-95:
  - tool.schema tests assert examples and metadata, but do not assert json_schema is present/non-null.

Concrete risk / carrying cost:
- Agents calling tool.schema see a schema field that is always null, so they must fall back to examples or docs.
- The registry has an apparently intended schema contract but no completeness gate, so newly added tools can continue shipping without machine-readable input contracts.
- This increases MCP/server wiring cost later because the registry cannot currently act as the authoritative tool-schema source.

Bounded paydown:
- If existing open inputSchema auto-derive bead is intended to cover this, explicitly include:
  - populate ToolRegistration.json_schema for all public tools, or remove/rename the field until it is supported.
  - add a registry completeness test that all registered tools expose either json_schema or an explicit reason/schema_status.
- If not covered, define minimal JSON schemas manually for current public tools and gate new registrations.

Validation:
- Add a contract test:
  - for every registry.by_name value, tool.schema(tool=name)["json_schema"] is a dict with type/object/properties, or schema_status == "not_available" with bounded reason.
- Verify generated MCP input schemas use the same registry source.
- Keep existing tests/contracts/test_agent_ergonomics.py passing.


4. Write-tool example coverage is partial and not enforced beyond seven MVP ledger tools

Domain/lens:
- Docs-contract drift
- Agent ergonomics test debt
- Tooling drift

Important non-duplication note:
- This overlaps with the existing “agent-ready QC” theme. I would only file this if that bead does not already require complete example coverage for every write tool.

Evidence:
- src/trade_trace/tools/_examples.py defines examples only for:
  - venue.add
  - instrument.add
  - thesis.add
  - forecast.add
  - decision.add
  - outcome.add
  - source.add
- tests/contracts/test_agent_ergonomics.py lines 74-77 hard-code only those seven tools in WRITE_TOOLS_WITH_EXAMPLES.
- Registry enumeration command showed write tools without examples:
  - decision.record_adherence
  - forecast.supersede
  - journal.backup
  - journal.config_set
  - journal.fixture_seed
  - journal.restore
  - memory.link
  - memory.reflect
  - memory.reindex
  - memory.retain
  - model.import
  - playbook.create
  - playbook.propose_version
  - snapshot.add
  - source.attach_to_decision
  - source.attach_to_forecast
  - source.attach_to_memory_node
  - source.attach_to_thesis
  - strategy.create
  - strategy.update

Concrete risk / carrying cost:
- tool.schema presents “has_example” and per-tool examples as an agent bootstrap mechanism, but many mutating tools lack minimal payloads.
- Agents must infer required args from docs/source or trial-and-error, increasing invalid calls.
- Because the test hard-codes the seven example-backed tools instead of deriving all is_write registrations, new write tools can be added without examples unnoticed.

Bounded paydown:
- Decide whether every is_write tool must have example_minimal.
- If yes:
  - add examples for all is_write registrations.
  - change the test to derive WRITE_TOOLS_WITH_EXAMPLES from build_registry() where reg.is_write.
- If no:
  - add an explicit example_status / not_applicable_reason field to tool.schema.

Validation:
- Contract test:
  - all reg.is_write tools have example_minimal or documented example_status.
  - each example dry-runs successfully where safe/applicable.
- Keep the existing seven example dry-run checks, but expand coverage incrementally.


Coverage accounting:

Reviewed in-scope implementation:
- src/trade_trace/cli.py: complete.
- src/trade_trace/mcp_server.py: complete.
- src/trade_trace/contracts/errors.py: complete.
- src/trade_trace/contracts/envelope.py: complete.
- src/trade_trace/contracts/grammar.py: complete.
- src/trade_trace/contracts/report_filter.py: complete.
- src/trade_trace/contracts/tool_registry.py: complete.
- src/trade_trace/tools/_examples.py: complete.
- src/trade_trace/tools/_helpers.py: complete.
- src/trade_trace/tools/errors.py: complete.

Reviewed closely related implementation needed to understand contracts:
- src/trade_trace/core.py: dispatch, registry construction, envelope hint application.
- src/trade_trace/tools/journal.py: tool.schema and journal.schema behavior.
- src/trade_trace/tools/ledger.py registration section for example wiring.

Reviewed tests:
- tests/contracts/test_agent_ergonomics.py
- tests/contracts/test_cli_name_uniqueness.py via collect and relevant assertions
- tests/contracts/test_envelope.py
- tests/contracts/test_grammar.py via collect and relevant assertions
- tests/contracts/test_report_envelope_completeness.py
- tests/golden/test_cli_mcp_parity.py
- tests/golden/test_journal_status_parity.py

Issues encountered:
- python was not available as python; used python3.
- Initial import failed without PYTHONPATH=src; reran with PYTHONPATH=src.
- Did not edit files, did not create/update beads, did not run installs/formatters, and did not push anything.