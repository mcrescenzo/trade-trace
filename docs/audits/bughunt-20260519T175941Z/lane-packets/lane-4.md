Read-only bughunt completed for domain: docs-packaging-ci-contracts
Workspace: /home/hermes/code/trade-trace

Files modified/created: none.

Candidate records:

1.
id: DOC-CI-CONTRACT-001
title: Runtime tool.schema contract is false for most registered tools; docs instruct agents to rely on schemas that are null
severity: P2
confidence: confirmed
domain: docs-packaging-ci-contracts
bug_class: docs/contract truth mismatch
evidence_type: static docs + runtime registry probe + CLI probe

evidence:
- docs/PRD.md:532 says “Every tool has a JSON schema; report.filter_schema and journal.schema surface them at runtime.”
- docs/AI_AGENT_MCP_GETTING_STARTED.md:108 says “Use the returned JSON Schema and examples as the source of truth.”
- docs/AI_AGENT_MCP_GETTING_STARTED.md:162-163 instructs every write flow to call tool.schema and build payload from the schema.
- docs/AGENT_GUIDE.md:9, 69, 88, 91 similarly tells agents to use tool.schema for exact current fields / constrained target kinds.
- Runtime probe found 55 of 66 registered tools have json_schema == null.
- Example CLI probe:
  TRADE_TRACE_HOME=$(mktemp -d) python3 -m trade_trace.cli tool schema --tool memory.recall
  returned ok=true with:
  "json_schema": null, "example_minimal": null, "example_rich": null

failure mode:
Agents following the docs cannot build or validate payloads for most tools from tool.schema. They are told the schema is the source of truth, but the runtime source of truth is absent for tools including memory.recall, memory.reflect, memory.reindex, playbook.*, strategy.*, report.*, import.*, admin tools, and many source attachment tools.

observed vs expected:
- Observed: tool.schema exists but returns null json_schema for 55/66 tools.
- Expected per docs/PRD/agent guides: every tool exposes usable JSON Schema, and agents can build exact payloads from tool.schema.

reproduction/trace path:
1. cd /home/hermes/code/trade-trace
2. Run:
   python3 - <<'PY'
   import sys
   sys.path.insert(0,'src')
   from trade_trace.core import default_registry
   r=default_registry()
   missing=[n for n in r.names() if r.get(n).json_schema is None]
   print(len(missing), 'of', len(r.names()))
   print('\n'.join(missing))
   PY
3. Or probe one documented loop tool:
   TRADE_TRACE_HOME=$(mktemp -d) python3 -m trade_trace.cli tool schema --tool memory.recall

duplicate/overlap analysis:
- Not a duplicate of the provided existing themes. It is not about nonexistent CLI commands, Python executable naming, stale dependency docs, dashboard/P2 status, version tests, or broken local links.
- It overlaps generally with “contract docs contradicted by registered CLI/MCP/tool behavior,” but the concrete failure is materially different: the registered tool exists, but its introspection contract is absent/null for most tools.

proposed Bead body:
Title: tool.schema docs promise JSON schemas for every tool, but runtime returns null for most tools

Body:
The docs repeatedly instruct agents to use tool.schema as the source of truth for exact fields, enum values, constrained target kinds, and safe write payloads. PRD.md also states that every tool has a JSON schema. Runtime registry inspection contradicts this: 55 of 66 registered tools have json_schema == null, including core loop tools such as memory.recall, memory.reflect, playbook.propose_version, strategy.*, report.*, import.*, and admin tools.

Evidence:
- docs/PRD.md:532: “Every tool has a JSON schema…”
- docs/AI_AGENT_MCP_GETTING_STARTED.md:108, 162-163: agents should build payloads from returned JSON Schema.
- docs/AGENT_GUIDE.md:9, 69, 88, 91: tool.schema is used as exact field/source-of-truth guidance.
- Runtime:
  python3 registry probe reports 55 of 66 tools missing json_schema.
  `python3 -m trade_trace.cli tool schema --tool memory.recall` returns ok=true with `"json_schema": null`.

Impact:
Agent integrations following the documented contract cannot discover or validate most tool payloads from the registry. This breaks the agent-ready setup story and pushes callers back to stale snippets/manual docs.

acceptance criteria:
- Either every registered tool returns a non-null, useful json_schema from tool.schema, or the docs are narrowed to state exactly which tools have schemas/examples and how agents should discover fields for schema-less tools.
- AI_AGENT_MCP_GETTING_STARTED and AGENT_GUIDE no longer instruct agents to build every payload from tool.schema unless the runtime actually supports that.
- Add/adjust a contract test that fails if docs claim universal schemas while registry entries remain null.

validation command:
python3 - <<'PY'
import sys
sys.path.insert(0,'src')
from trade_trace.core import default_registry
r=default_registry()
missing=[n for n in r.names() if r.get(n).json_schema is None]
print(len(missing), 'missing schemas')
print('\n'.join(missing))
PY

risks/uncertainty:
- Some tools may intentionally omit schemas today; if so, the fix can be docs-only. The bug is the mismatch between docs and runtime contract, not necessarily the absence of schemas itself.


2.
id: DOC-CI-CONTRACT-002
title: PRD documents journal.init --enable-embeddings opt-in, but CLI silently ignores the flag and leaves embeddings disabled
severity: P3
confidence: confirmed
domain: docs-packaging-ci-contracts
bug_class: documented setup command/option is nonfunctional
evidence_type: static docs + CLI behavior probe

evidence:
- docs/PRD.md:60 says opt-in can be done via:
  `tt journal config_set embeddings.provider local` or `journal.init --enable-embeddings`
- Implementation of _journal_init in src/trade_trace/tools/journal.py:41-78 only reads optional home and always returns:
  "embeddings_provider": "none"
  "outbound_network_active": False
- Runtime probe:
  TRADE_TRACE_HOME=$tmp python3 -m trade_trace.cli journal init --enable-embeddings
  returned ok=true, but data.embeddings_provider was "none".
  Follow-up journal.status also reported embeddings_provider "none".

failure mode:
An operator or agent following PRD.md to enable embeddings at init receives a successful command but no embeddings opt-in happens. Because the generic CLI accepts arbitrary --key flags and handlers ignore unknown args, this is a silent no-op rather than a typed validation error.

observed vs expected:
- Observed: `tt journal init --enable-embeddings` succeeds and initializes a journal with embeddings_provider=none.
- Expected per PRD: the flag enables the local embeddings path or is not documented as supported. If unsupported, CLI should reject or docs should remove the flag.

reproduction/trace path:
1. cd /home/hermes/code/trade-trace
2. Run:
   tmp=$(mktemp -d)
   TRADE_TRACE_HOME=$tmp python3 -m trade_trace.cli journal init --enable-embeddings
   TRADE_TRACE_HOME=$tmp python3 -m trade_trace.cli journal status
   rm -rf "$tmp"
3. Observe both envelopes report embeddings_provider "none".

duplicate/overlap analysis:
- Related to the existing stale CLI/config docs theme, but materially different from the listed “tt config set/init/mcp” issue. This is a documented option on an existing registered command (`journal.init`) that is silently accepted and ignored.

proposed Bead body:
Title: PRD documents journal.init --enable-embeddings, but the flag is a silent no-op

Body:
PRD.md §2.4.1 says embeddings can be explicitly enabled via `journal.init --enable-embeddings`. The actual journal.init handler ignores this flag and always initializes with `embeddings_provider: "none"` and `outbound_network_active: false`. The CLI accepts unknown long flags into tool_args, so users get ok=true instead of a validation error.

Evidence:
- docs/PRD.md:60 documents `journal.init --enable-embeddings`.
- src/trade_trace/tools/journal.py:41-78 ignores all init args except home and hard-codes embeddings_provider none.
- Repro:
  tmp=$(mktemp -d)
  TRADE_TRACE_HOME=$tmp python3 -m trade_trace.cli journal init --enable-embeddings
  TRADE_TRACE_HOME=$tmp python3 -m trade_trace.cli journal status
  rm -rf "$tmp"
  Both outputs report embeddings_provider "none".

Impact:
Setup docs create false confidence that semantic/vector recall has been enabled. Downstream calls run with the default non-vector path despite an apparently successful opt-in command.

acceptance criteria:
- Either implement `journal.init --enable-embeddings` with explicit confirmation/network behavior consistent with the embeddings opt-in contract, or remove the flag from PRD/setup docs and point only to the supported `journal.config_set embeddings.provider local --confirm` flow.
- Unknown or unsupported flags for journal.init should not silently imply successful configuration in docs/examples.
- A validation/test path confirms the documented init command either enables embeddings or is no longer advertised.

validation command:
tmp=$(mktemp -d)
TRADE_TRACE_HOME=$tmp python3 -m trade_trace.cli journal init --enable-embeddings
TRADE_TRACE_HOME=$tmp python3 -m trade_trace.cli journal status
rm -rf "$tmp"

risks/uncertainty:
- This may be intentionally deferred in favor of journal.config_set. If so, docs-only correction is sufficient.
- The local model download path may require dependencies/network not exercised here; the confirmed bug is the silent no-op against the documented command.


Coverage accounting:

Files opened/read directly:
- /home/hermes/code/trade-trace/README.md
- /home/hermes/code/trade-trace/pyproject.toml
- /home/hermes/code/trade-trace/.github/workflows/ci.yml
- /home/hermes/code/trade-trace/.github/workflows/workflow.yml
- /home/hermes/code/trade-trace/AGENTS.md
- /home/hermes/code/trade-trace/CLAUDE.md
- /home/hermes/code/trade-trace/docs/AI_AGENT_MCP_GETTING_STARTED.md
- /home/hermes/code/trade-trace/docs/AGENT_GUIDE.md
- /home/hermes/code/trade-trace/docs/CLAUDE_CODE.md
- /home/hermes/code/trade-trace/docs/IDE_MCP_SETUP.md
- /home/hermes/code/trade-trace/src/trade_trace/cli.py
- /home/hermes/code/trade-trace/src/trade_trace/contracts/tool_registry.py
- /home/hermes/code/trade-trace/src/trade_trace/tools/journal.py
- /home/hermes/code/trade-trace/src/trade_trace/tools/admin.py
- /home/hermes/code/trade-trace/src/trade_trace/tools/memory.py

Search-reviewed/probed:
- Markdown inventory under repo, excluding historical audits for primary review.
- .github/workflows inventory.
- Registered tool names and schema status from trade_trace.core.default_registry.
- Docs content for commands/install/schema/tool.schema/config/model/memory references.
- Link check over README.md, docs/**/*.md excluding docs/audits, AGENTS.md, CLAUDE.md.
- Dependency/version references for pyproject/version/docs consistency.

Commands run/results:
- `python` registry probe: failed because `python` not found. This matches an existing known bug theme and was not reported as new.
- `python3` import probe for wrong module `trade_trace.registry`: ModuleNotFoundError; used to discover correct registry path.
- `python3` default_registry probe: succeeded; listed 66 registered tools.
- Markdown local link checker: succeeded; no missing local markdown links found in checked scope.
- Registry schema count probe: succeeded; found 55/66 tools with json_schema == null.
- CLI tool.schema probe for memory.recall: succeeded; returned json_schema null.
- CLI journal.init --enable-embeddings temp-home probe: succeeded but left embeddings_provider none; temp dir was removed.

Areas not inspected / why:
- Did not exhaustively read every architecture doc line-by-line due time; used targeted searches for install/setup/CLI/schema/packaging/CI contract claims, plus opened the agent-facing docs and primary packaging/CI files.
- Did not inspect historical docs/audits except initial inventory; out of primary scope except prior coverage sampling.
- Did not run package managers, installers, full tests, CI, or networked checks per read-only/no-installs constraints.
- Did not mutate Beads or repo files per instruction.

Side-effect caveats:
- No repository files were created, modified, or deleted.
- CLI probes created temporary directories under /tmp via mktemp; one temp-home probe was removed in-command. One earlier `TRADE_TRACE_HOME=$(mktemp -d) ... tool schema` command created an empty temporary directory outside the repo and did not remove it. No shared services, package installs, pushes, or Beads mutations were performed.