Read-only technical-debt review summary for security boundaries + network/credential/redaction tests
Repo: /home/hermes/code/trade-trace
Commit reviewed: a33e676ec9d22d6ec268686424521a3d2586f9dd
Mode: read-only; no files edited, no Beads/issues created.

What I did
- Inspected the security-specific implementation and tests:
  - src/trade_trace/security/patterns.py
  - tests/security/test_secret_pattern_writes.py
  - tests/security/test_redacted_exports.py
  - tests/security/test_no_network_default.py
  - tests/security/test_file_permissions.py
  - tests/security/test_no_credentials.py
- Cross-checked security-sensitive boundaries in:
  - src/trade_trace/exporter.py
  - src/trade_trace/mcp_server.py
  - src/trade_trace/tools/_helpers.py
  - src/trade_trace/tools/ledger.py
  - src/trade_trace/storage/paths.py
  - src/trade_trace/events/log.py
- Searched for credential/secret/redaction/network terms across src/trade_trace.
- Checked repository status and confirmed the requested commit is checked out, but the working tree already had unrelated modifications/untracked audit artifacts before this review.

Coverage accounting
- Covered:
  - Secret-pattern registry and log redaction.
  - Write-time secret guard helper and currently guarded fields.
  - Export-time warning behavior and full-local export semantics.
  - No-network default tests for journal.init/status/schema.
  - File permission tests for DB and exported JSONL.
  - Credential schema/column/surface tests.
  - MCP in-process boundary shape.
  - Home path resolution and storage path handling.
- Not executed:
  - I did not run pytest because this lane was explicitly read-only and pytest would likely mutate .pytest_cache / pycache in the already-dirty workspace.
- Existing duplicate/theme note:
  - I avoided embedding opt-in/provider/reindex items as requested. One no-network candidate below mentions embeddings only as a broader network-boundary test gap, not provider/reindex functionality.

Structured candidates

Candidate SEC-01: Write-time secret detection is field-specific and leaves many persisted free-text/metadata surfaces unguarded

Evidence
- The generic write guard is src/trade_trace/tools/_helpers.py:144-177, and its docstring says it is used for “thesis.body, source.excerpt, decision.reason”.
- Actual call sites found in src/trade_trace/tools/ledger.py:
  - thesis.body guarded at line 297.
  - decision.reason guarded at line 665.
  - source.excerpt and source.extracted_text guarded at lines 1114-1115.
- Multiple persisted free-text or metadata-like fields are not guarded before storage/export:
  - thesis risk_notes, falsification_criteria, exit_triggers, etc. are inserted around ledger.py:352-364 without secret scanning.
  - source.summary, uri, title, license_or_terms_note, metadata_json are stored around ledger.py:1139-1185 without secret scanning.
  - metadata_json is accepted generically by _store_metadata_json at ledger.py:49-56, returning a raw JSON string unchanged if the caller supplies a string.
  - playbook/memory tools store description/reason/metadata_json without using reject_if_contains_secrets, e.g. playbook.py lines 58-59, 261-262, 399-400 from search results.
- tests/security/test_secret_pattern_writes.py intentionally covers only three guarded fields in its header: “Four registered patterns × three guarded free-text fields = 12 negative test slots”, despite source.extracted_text also being guarded now.

Risk
- Security-hardening debt, not a confirmed exploit in normal flows.
- A user/agent can accidentally persist secret-shaped material into unguarded fields, then full-local export deliberately writes raw payloads. This weakens the “credential/no secret persistence” expectation outside the three or four blessed fields.
- The risk is higher for metadata_json because it is a generic escape hatch and can contain arbitrary key/value content.

Bounded paydown
- Define a small “secret-scanned persisted input fields” allowlist/denylist policy for all write tools.
- Apply reject_if_contains_secrets recursively to:
  - all persisted free-text fields, or
  - all user-supplied string fields except known safe identifiers/enums/timestamps.
- Add recursive scanning for metadata_json/liquidity_depth_json or explicitly document metadata_json as full-local sensitive and test that policy.
- Update tests/security/test_secret_pattern_writes.py to enumerate every persisted user text/JSON field, not only thesis.body/source.excerpt/decision.reason.

Validation/gap
- Add parameterized tests that attempt representative secrets in:
  - thesis.risk_notes, falsification_criteria, exit_triggers.
  - source.summary, extracted_text, uri/title/license_or_terms_note/metadata_json.
  - forecast.resolution_rule_text.
  - playbook description/rules/adherence reason.
  - memory reflection/content/metadata surfaces if applicable.
- Verify both DB rows and events table payload_json do not retain rejected secrets.

Duplicate notes
- Distinct from embedding-provider opt-in debt.
- Related to existing secret write/export tests but not a duplicate: current tests explicitly cover only a subset.

Disposition recommendation
- Create backlog item: security-hardening / test-debt.
- Priority: Medium-high because it protects accidental credential persistence, but current tests and docs appear to scope MVP guards narrowly.


Candidate SEC-02: “No credentials” test asserts silent drops but misses explicit metadata_json credential injection

Evidence
- tests/security/test_no_credentials.py states: “Credential-shaped args passed to any write tool MUST be silently ignored … or rejected outright.”
- The venue/instrument/decision tests pass credential-shaped unknown top-level args and then assert metadata_json lacks those keys.
- However, ledger.py _store_metadata_json accepts caller-provided metadata_json directly:
  - src/trade_trace/tools/ledger.py:49-56:
    - if value is str, return value unchanged.
    - otherwise json.dumps(value).
- venue.add stores metadata_json directly at ledger.py:88 and inserts it at ledger.py:116-119.
- The current test does not pass:
  - metadata_json={"api_key": "..."}
  - metadata_json='{"api_key": "..."}'
  - nested metadata_json={"nested": {"private_key": "..."}}

Risk
- Security-hardening/test-debt.
- The no-credential guarantee can be bypassed via explicit metadata_json, even though the existing test suite gives confidence that credential-shaped top-level unknown args are dropped.
- This is especially important because metadata_json is exposed in event payloads and JSONL export.

Bounded paydown
- Decide and document one of:
  1. metadata_json is allowed to contain arbitrary local-only sensitive data, and docs/tests should stop implying broad credential exclusion; or
  2. metadata_json must reject credential-shaped keys/values recursively.
- If option 2, implement a shared recursive credential/secret scanner for JSON-like values before _store_metadata_json returns.
- Add tests for dict and string metadata_json inputs across representative write tools.

Validation/gap
- Negative tests should assert rejected envelopes include field="metadata_json" and pattern_kind/key path details.
- DB/event payload scan should verify no raw secret or credential key remains.

Duplicate notes
- Related to SEC-01 but narrower: credential-key policy drift in tests and metadata_json behavior.

Disposition recommendation
- Create backlog item: config/security contract drift + test-debt.
- Priority: Medium.


Candidate SEC-03: Export-time secret warnings intentionally omit match locations/counts and do not surface file/path context

Evidence
- exporter.scan_for_secrets returns pattern and raw match at src/trade_trace/exporter.py:196-203.
- drain_outbox scans the emitted JSONL line and appends warnings with only:
  - event_id
  - event_type
  - sorted pattern names
  at exporter.py:318-327.
- tests/security/test_redacted_exports.py asserts only pattern presence, not counts, paths, JSON field paths, offsets, or whether multiple matches were collapsed.

Risk
- Observability-debt/security-hardening.
- Current behavior is safer than exposing raw matches in result.secret_warnings, but it gives operators limited information to locate/redact the event safely.
- If multiple secrets or fields are present, the warning collapses detail and may understate cleanup scope.

Bounded paydown
- Keep raw secret bytes out of envelopes.
- Extend warning details with non-sensitive location metadata:
  - exported file path relative to TRADE_TRACE_HOME.
  - count by pattern.
  - byte offsets or JSON pointer paths after parsing, without raw match values.
  - maybe first N redacted snippets using redact_for_log.
- Add tests ensuring raw secret values are not present in warning envelopes.

Validation/gap
- Tests should verify:
  - multiple secrets produce accurate counts.
  - warning output excludes m["match"] values.
  - field/path context survives nested payloads.

Duplicate notes
- Complements existing redacted export tests; not a duplicate because current tests only assert warning presence and raw full-local file content.

Disposition recommendation
- Create backlog item: observability-debt/security-hardening.
- Priority: Medium.


Candidate SEC-04: Network boundary tests cover only journal.init/status/schema and socket connect/getaddrinfo, not registered tool surface or import-time side effects

Evidence
- tests/security/test_no_network_default.py monkeypatches socket.socket.connect and socket.getaddrinfo.
- It only exercises:
  - journal.init
  - journal.status
  - journal.schema
  - init/status/reinit loop
- There are many read/report/write tools whose descriptions claim local-only behavior, e.g. reports.py search result around lines 418-419 says “No external fetching, no credibility scoring.”
- mcp_server.py is only an in-process shim; serve_stdio is a NotImplemented placeholder at mcp_server.py:49-66.
- No test was found that iterates the full default_registry under a network-deny fixture for representative calls, nor a static import audit for requests/httpx/urllib/socket usage across src/trade_trace.

Risk
- Test-debt/security-boundary.
- The air-gap/no-network promise may regress in a tool outside journal.init/status/schema without test detection.
- Monkeypatching only connect/getaddrinfo catches many TCP attempts, but static dependency or subprocess-based network calls could slip through.

Bounded paydown
- Add a registry-wide no-network smoke suite:
  - journal/report/schema/status read paths.
  - representative write paths on a temp home.
  - import.validate with nonexistent path.
  - export.drain.
- Add static tests rejecting direct imports/usages of requests, httpx, urllib.request, socket, subprocess network shell commands, except explicit allowlisted modules.
- Add subprocess-level CLI tests under a denied network sandbox if feasible.

Validation/gap
- Include a fixture that patches:
  - socket.create_connection
  - socket.socket.connect/connect_ex
  - socket.getaddrinfo
  - optionally urllib/request/http client entry points if dependencies are added.
- Confirm no test requires internet and no provider calls occur by default.

Duplicate notes
- Avoids existing embedding opt-in/provider/reindex backlog. This is a general network boundary regression net.

Disposition recommendation
- Create backlog item: security-boundary test-debt.
- Priority: Medium-high due to project’s explicit air-gap promise.


Candidate SEC-05: MCP boundary is an in-process shim with no tests for future stdio/auth/tool exposure constraints

Evidence
- src/trade_trace/mcp_server.py:49-66 defines serve_stdio as a placeholder raising NotImplementedError.
- The comments say future wiring will register every tool and dispatch incoming calls through mcp_call.
- Current mcp_call at mcp_server.py:20-46 accepts arbitrary tool_name/args and passes through to dispatch, then sets mcp_transport_hints = {}.
- tests/security use mcp_call directly, but no security-specific tests assert:
  - stdio transport is unavailable/non-listening by default.
  - future MCP server must not bind TCP.
  - tool registry exposure excludes unsafe/internal helpers.
  - actor_id/request_id cannot smuggle credentials into logs/errors.

Risk
- Investigation/design debt.
- Not a current exploit because stdio MCP server is unimplemented.
- However, the boundary will become security-sensitive when implemented, and current tests could pass while a future MCP transport accidentally binds a network listener or exposes internal/admin tools.

Bounded paydown
- Before implementing serve_stdio, add failing contract tests or design docs that pin:
  - stdio only; no TCP listener by default.
  - all exposed tools come from default_registry only.
  - no dynamic import/exec tool registration.
  - transport hints contain no secrets and no host/network addresses unless explicitly configured.
  - actor_id/request_id validation applies identically to CLI/MCP.

Validation/gap
- Add static no-listen tests for mcp_server.
- Add transport parity test including error envelopes and redaction behavior.
- Add test that serve_stdio remains stdio-only or is explicitly opt-in if network transport is ever added.

Duplicate notes
- Distinct from existing MCP parity tests and from embedding/provider network debt.

Disposition recommendation
- Create backlog item: investigation/design + security-boundary test-debt.
- Priority: Medium; becomes high before MCP transport implementation.


Candidate SEC-06: File permission tests verify DB and final JSONL, but not directories, temp files, WAL/SHM, backups, or config files

Evidence
- tests/security/test_file_permissions.py verifies:
  - SQLite DB mode 0600.
  - exported JSONL final file mode 0600.
- exporter.write_event_atomic writes tmp file, fsyncs, renames, then chmods only the final path at exporter.py:130-142.
- There is no test here for:
  - temporary .jsonl.tmp permissions before rename.
  - export/jsonl parent directory permissions.
  - SQLite WAL/SHM files if WAL mode is enabled.
  - config/state files such as config table external files if added later.
  - backup/import artifacts.
- storage.paths.py only resolves paths; no boundary around symlinks or directory permissions was observed.

Risk
- Security-hardening/test-debt.
- On a permissive umask, transient tmp files or directories may be more broadly readable until final chmod.
- Directory execute/read bits may reveal file names/event types even if files are 0600.

Bounded paydown
- Create files with restrictive opener/mode from the start rather than chmod after write where possible.
- Add tests under permissive umask 0o022/0o000 for:
  - DB, WAL/SHM if present.
  - temp export files during interrupted writes.
  - parent directory modes, likely 0700.
- Decide whether directory names/event type leakage is acceptable and document it.

Validation/gap
- Simulate failed write before os.replace to inspect .tmp mode.
- Add POSIX-only tests similar to current file permission test.

Duplicate notes
- Extends existing file permission test rather than replacing it.

Disposition recommendation
- Create backlog item: security-hardening + test-debt.
- Priority: Medium.


Candidate SEC-07: Secret pattern registry accepts arbitrary runtime regex without ReDoS guard or timeout

Evidence
- src/trade_trace/security/patterns.py register() accepts a string or compiled re.Pattern and compiles/stores it globally at lines 80-110.
- scan_text applies every registered regex to user text with pattern.finditer at lines 126-145.
- redact_for_log repeatedly rescans up to len(text)+1 iterations at lines 148-179.
- tests/security/test_secret_pattern_writes.py validates custom pattern registration and invalid regex/name, but not catastrophic backtracking or performance caps.

Risk
- Security-hardening/integration-provider-drift.
- If plugins/tests/users can register custom patterns, a pathological regex can make writes/log redaction/export scanning CPU-expensive or hang on crafted input.
- Current built-ins appear simple, so this is hardening debt rather than a confirmed bug.

Bounded paydown
- Restrict runtime registration to trusted/test contexts or document it as process-local unsafe extension.
- Add guardrails:
  - max regex source length.
  - optional use of the regex module with timeout, or RE2-style safe engine if available.
  - scan input length cap/truncation for log redaction/export warnings.
- Add tests with known pathological patterns only if timeout mechanism exists; otherwise static rejection tests.

Validation/gap
- Bench tests or unit tests ensuring scan_text/redact_for_log complete under bounded time on long inputs.
- Verify built-in pattern set remains safe.

Duplicate notes
- Distinct from provider/plugin embedding debt; this is specifically secret-pattern extension safety.

Disposition recommendation
- Create backlog item: security-hardening.
- Priority: Low-medium unless runtime register is exposed to untrusted plugins/users.


Candidate SEC-08: Export full-local raw secret behavior is well-tested but shareable/redacted export boundary remains deferred/ambiguous

Evidence
- tests/security/test_redacted_exports.py explicitly pins full-local behavior:
  - export proceeds on secrets.
  - raw secret remains in JSONL.
  - warning is surfaced.
- The module docstring says “sources.redaction_status = sensitive is excluded from review.bundle … tested elsewhere” and “export path deliberately does NOT filter”.
- src/trade_trace/tools/review_bundle.py search result indicates redaction passes are P1 and current tool returns UNSUPPORTED_CAPABILITY/deferred.
- This is an intentional MVP decision, but security-sensitive docs/users may infer “redacted exports” from test names while actual export is full-local.

Risk
- Config-drift/security-boundary.
- Operators may confuse full-local export with shareable/export-redacted behavior.
- The absence of an implemented shareable/redacted surface means the current safe workflow is “do not share JSONL exports”; that should remain explicit in docs/CLI warnings.

Bounded paydown
- Rename or clarify tests/docs to distinguish:
  - full-local export with warning.
  - shareable/redacted export not yet supported.
- Add CLI/tool result fields indicating export_mode="full_local_raw" and shareable=false.
- Add tests that review.bundle or any future shareable export excludes redaction_status=sensitive and secret-shaped content.

Validation/gap
- Test any user-facing export.drain envelope text/hints once CLI command exists.
- Confirm README/PRD make “full-local raw export” unmistakable.

Duplicate notes
- This is adjacent to existing full-local test coverage but focuses on boundary communication and future shareable export.

Disposition recommendation
- Create backlog item: config-drift/docs + security-boundary test-debt.
- Priority: Medium.


No confirmed exploit/bug claimed
- I did not produce a concrete failing runtime proof because this review was read-only and I avoided executing tests that could mutate caches.
- The strongest concrete code-level risk is metadata_json accepting raw credential/secret content while the credential tests imply broader exclusion. That may be a policy bug or an intentional local-only escape hatch; it needs design clarification.

Files created or modified
- None by me.

Issues encountered
- The working tree was already dirty before my review:
  - Modified files under src/trade_trace/events and src/trade_trace/reports.
  - Untracked audits/ and docs/audits/.
- I avoided writing, formatting, installing, deleting, or running mutation-prone test commands.