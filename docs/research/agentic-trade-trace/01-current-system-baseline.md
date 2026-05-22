# Current Trade Trace Capability Baseline

## 1. Bottom Line

Trade Trace is already implemented as more than a simple log: the inspected source shows a local SQLite-backed journal with append-only ledger tables, event/idempotency envelopes, source/evidence attachment, binary/categorical/scalar forecast record shapes, automatic binary Brier scoring on resolved outcomes, reports, a typed memory graph, first-class strategies, advisory playbooks, MCP/CLI parity through a shared registry/dispatcher, and a guided `market.scan` dry-run/promote bundle flow.

The current system is close to the intended agent-only continuity substrate in core primitives: it can preserve theses, decisions, outcomes, reflections, strategy context, playbook versions, recall telemetry, and segmentation metadata (`agent_id`, `model_id`, `environment`, `run_id`). The main baseline gaps for the next research phase are not “no primitives,” but taxonomy/usage gaps: how agents should reliably write useful memories/reflections/playbook rules, how to retrieve them at decision time, how to avoid noisy memory accretion, how to use strategy boundaries, and where current docs/status overstate, understate, or drift from live behavior.

Important implementation-vs-doc distinction: `README.md` and `docs/PRD.md` state broad shipped status, and much of that is corroborated by source inspection. However, this artifact did not run the full test suite or exercise end-to-end journal calls; conclusions are based on static source/docs inspection plus registry enumeration.

## 2. Product Boundary Observed

Observed boundary is consistent across README, Vision, PRD, MCP adapter, and market-scan source:

- **Local-first journal/memory/calibration substrate.** README describes “local, open-source, AI-only journal, memory, and calibration substrate” and supported surfaces as CLI, MCP, and Python/library reporting APIs (`README.md:3-11`, `README.md:40-41`).
- **Not an executor.** README and Vision explicitly exclude order signing, wallet handling, broker credentials, and trade routing (`README.md:108-117`; `docs/VISION.md:20-29`). Source reinforces this: `decision.add` records `actual_*` decisions only; `paper_enter` creates local projection rows but no external action (`src/trade_trace/tools/ledger.py:851-1027`).
- **Not a market data fetcher.** Vision and PRD say Trade Trace never queries external venues/market data and expects caller-supplied data (`docs/VISION.md:22-24`, `docs/PRD.md:49-67`). `market.scan.dry_run` explicitly says no fetch/no advice/no writes (`src/trade_trace/tools/market_scan.py:1-6`, `154-306`).
- **Agent/machine surfaces only.** No human Console UI is shipped per README (`README.md:40-41`, `112-114`). CLI/MCP share the same dispatcher and registry (`src/trade_trace/core.py:1-8`, `50-75`, `109-121`).
- **Retrospective decision support, not advice.** `market.scan` returns caller-selected actions and `no_advice_boundary`; reports/coach are deterministic aggregation, not recommendations (`src/trade_trace/tools/market_scan.py:154-306`; `docs/PRD.md:386-388`).

## 3. Current Implemented/Documented Primitives Table

| Capability | Current evidence | Implemented/planned/partial | Agentic relevance | Gaps/risks |
|---|---|---:|---|---|
| Ledger: venues/instruments/snapshots/theses/forecasts/decisions/outcomes | PRD core tables (`docs/PRD.md:147-300`); migration creates tables and indexes (`src/trade_trace/storage/migrations/m003_m1_ledger.py:29-385`); write handlers in ledger tool (`src/trade_trace/tools/ledger.py:154-1117`) | Implemented | Preserves decision context, thesis, snapshot, forecast, outcome, and local position projection for future sessions | Richness depends on caller discipline; `actual_*` are journal-only unless linked to positions; `paper_exit` close semantics not inferred in inspected handler (`ledger.py:203-205` documented; implementation around `851-1027`) |
| Append-only event/idempotency | README security (`README.md:132-138`); dispatcher enforces write `idempotency_key` (`src/trade_trace/core.py:156-180`); migration append-only triggers (`m003_m1_ledger.py:386-432`) | Implemented | Makes cron/fresh-session retries safe and audit trail stable | Strategy rows are mutable by design with update events; projections mutable. Agents must understand append-only correction model. |
| Forecast scoring/calibration | README auto-scoring (`README.md:84-87`); `_outcome_add` autoscores resolved_final (`ledger.py:1098-1117`); `_autoscore_pending_forecasts` and `_score_one_forecast` (`ledger.py:1120+`) | Implemented for binary; docs discuss broader scoring | Supports objective calibration feedback across sessions | PRD states MVP binary; source accepts categorical/scalar validation but scoring support needs closer verification. This artifact did not inspect all scoring functions past `ledger.py:1200`. |
| Reports | Tool registry includes many `report.*`; schemas in `tools/reports.py:85-269`; report implementations imported (`tools/reports.py:26-44`) | Implemented broad surface | Agents can query calibration, mistakes/strengths, P&L, watchlist, unscored forecasts, source quality, audit readiness, risk/opportunity, compare, strategy performance, current exposure | Static inspection did not verify every report's SQL correctness. Docs still contain language implying some reports were deferred while registry shows shipped (`docs/PRD.md:390-396` vs `515-525` and registry). |
| Memory graph | README status (`README.md:17-20`); PRD memory graph (`docs/PRD.md:302-340`); source `memory.retain/reflect/link/recall` (`src/trade_trace/tools/memory.py:1-24`, `177-722`) | Implemented | Stores observations/reflections/playbook rules with edges, recall, recall telemetry, bi-temporal validity | Raw `memory.retain` can create reflection nodes without about-edge; safe path is `memory.reflect` (`memory.py:180-188`, `462-540`). Agent taxonomy/guidance is still critical. |
| Memory recall | BM25/temporal/graph plus optional semantic (`memory.py:682-722`, `725-773`, `891-999`, `1042-1088`) | Implemented; semantic appears deterministic/local-stub gated by provider | Gives fresh sessions prior reflections/rules by query/context, including strategy context | Relevance quality depends on query quality, node quality, and graph edges. API embedding provider comments indicate no actual network OpenAI embedding call in inspected code (`memory.py:1050-1057`), so docs around API embeddings may be aspirational/partial. |
| Strategies | PRD §2.12/§4.6 (`docs/PRD.md:117-145`, `422-433`); source strategy tools (`src/trade_trace/tools/strategy.py:1-12`, `59-433`); registry includes `strategy.*` | Implemented | Groups decisions/theses/reviews/reflections by edge thesis; enables scoped recall/reports | `strategy.show` source returns row only; PRD planned summary counts (`docs/PRD.md:428`) not observed in implementation (`strategy.py:230-269`). Strategy versioning remains deferred (`docs/PRD.md:593-594`). |
| Playbooks/adherence | PRD §4.3 (`docs/PRD.md:398-407`); source playbook tools and `decision.record_adherence` (`src/trade_trace/tools/playbook.py:1-29`, `50-112`, `407+`) | Implemented advisory loop | Lets agents codify process learning and record followed/overridden/not-applicable | No automatic rule engine; rule content lives as memory nodes and adherence must be recorded by agent. Need taxonomy for rule granularity and override reasons. |
| `market.scan` | Architecture contract listed in README (`README.md:166-168`); source dry-run/promote (`src/trade_trace/tools/market_scan.py:1-6`, `31-60`, `154-306`, `370-459`, `462-490`) | Implemented | Converts caller-supplied research bundle into deterministic journal call plan; useful entry point for agents scanning markets | `dry_run` is read-only; `promote` executes child writes sequentially, not physical transaction rollback (`market_scan.py:458`). Only `watch`, `skip`, `paper_enter` actions allowed (`market_scan.py:22-24`). |
| CLI/MCP parity | README (`README.md:62-90`, `105-106`); registry maps names to CLI (`tool_registry.py:1-8`, `59-68`); core shared dispatcher (`core.py:1-8`); MCP adapter uses registry/dispatch (`mcp_server.py:45-74`, `92-118`) | Implemented architecture | Agents can use same semantics through MCP or CLI; `tool.schema` discovers contracts | This artifact did not inspect full CLI argument parsing. MCP SDK validates schemas where available (`mcp_server.py:171-213`). |
| Security/no-network/no-execution | README security (`README.md:119-146`); MCP stdio no network listen (`mcp_server.py:1-7`, `226-241`); credential rejection in ledger/strategy/playbook/memory (`ledger.py:54-127`; `strategy.py:68-72`; `playbook.py:121-123`; `memory.py:216-218`) | Implemented in inspected paths | Safe local substrate for agent logs without accidentally becoming broker/data connector | Did not inspect all security tests. Optional embeddings/model tools need separate verification for actual network behavior. |
| Segmentation fields | PRD common metadata (`docs/PRD.md:133-145`); migration columns on theses/forecasts/decisions/outcomes (`m003_m1_ledger.py:116-119`, `147-150`, `215-218`, `255-258`); handlers call `common_metadata` (`ledger.py:389-390`, `672`, `858`, `1038`; `memory.py:247`, `690`) | Implemented on major rows | Enables longitudinal comparison by agent/model/environment/run | Snapshots segmentation is documented but not present in inspected M003 snapshot table (`m003_m1_ledger.py:71-89`) and `_snapshot_add` does not call `common_metadata` (`ledger.py:303-368`). Possible doc/status drift. |
| Sources/evidence | PRD sources (`docs/PRD.md:260-269`); migration sources/edges (`m003_m1_ledger.py:267-337`); source attach tools in registry | Implemented | Lets agents later audit what evidence supported/contradicted a thesis/decision/forecast/memory | Need inspect attach handlers in rest of `ledger.py` for exact endpoint validation; not fully read in this pass. |
| Imports/export/backup/restore | README status (`README.md:20-21`); registry includes `import.*`, `export.drain`, `journal.backup/restore` | Implemented surfaces present | Supports continuity/import/export for external agent pipelines | Source not inspected deeply; no verification beyond registry/docs. |

## 4. Baseline Against Proposed Agentic Concepts

- **Continuity memory for cron/fresh sessions:** Implemented substrate exists: `memory.retain`, `memory.reflect`, `memory.recall`, recall telemetry, strategy context, and segmentation fields. Current gap is operational taxonomy: what should an agent write before/after decisions so later recall is useful rather than noisy.
- **Decision ledger vs memory layer:** The architecture distinguishes immutable ledger facts from flexible graph memory (`docs/VISION.md:47-49`). Source supports this with ledger tables/events and `memory_nodes` plus `edges` (`m003_m1_ledger.py`, `memory.py`). Phase 1 should preserve this distinction: do not turn memory nodes into a second ledger.
- **Theses/strategies/decisions/performance linkage:** Theses, forecasts, decisions, outcomes, strategies, playbooks, and edges are all present. Strategies are first-class, not tags (`strategy.py:1-12`). Phase 1 can build on strategies as the “edge thesis” level.
- **Reflection loop:** `reflection.prompt_for_outcome` is registered; `memory.reflect` atomically stores reflection + `about` edge. Playbook version updates require a reflection node provenance (`playbook.py:407-463`). Current gap: no automatic reflection generation and no subjective mistake adjudication, by design.
- **Calibration loop:** Binary auto-scoring and report surfaces exist. Calibration usefulness depends on enough scored forecasts and disciplined forecast creation before outcome. Phase 1 taxonomy should emphasize resolution-rule capture and avoiding late-recorded/rationalized forecasts.
- **Playbook loop:** Playbooks and normalized adherence exist, but are advisory. Agents must create `playbook_rule` memory nodes, propose versions, and record adherence/overrides. Phase 1 should define when a reflection becomes a rule, rule scope, and override semantics.
- **Market-scan as agent intake:** `market.scan.dry_run/promote` is a promising higher-level intake path for agent-selected watch/skip/paper-enter bundles while preserving no-fetch/no-advice boundaries. It may be the easiest way to standardize rich journal capture.
- **Multi-agent/model calibration:** Segmentation fields exist on several major rows and reports compare can group by `agent_id`, `model_id`, `strategy_id`, environment, etc. (`docs/PRD.md:390-392`; registry includes `report.compare`). Potential drift around snapshots segmentation should be resolved before relying on it.

## 5. Current Machine Interfaces

Observed registry names from `trade_trace.core.default_registry().names()`:

- Ledger/source/resolution: `venue.add`, `instrument.add`, `snapshot.add`, `thesis.add`, `forecast.add`, `forecast.supersede`, `decision.add`, `outcome.add`, `resolve.pending`, `resolve.record`, `source.add`, `source.attach_to_thesis`, `source.attach_to_decision`, `source.attach_to_forecast`, `source.attach_to_memory_node`.
- Memory/reflection: `memory.retain`, `memory.reflect`, `memory.link`, `memory.recall`, `memory.reindex`, `reflection.prompt_for_outcome`.
- Strategies/playbooks: `strategy.create`, `strategy.list`, `strategy.show`, `strategy.update`, `playbook.create`, `playbook.list`, `playbook.show`, `playbook.list_versions`, `playbook.propose_version`, `playbook.adherence`, `decision.record_adherence`.
- Reports/review: `report.calibration`, `report.calibration_integrity`, `report.coach`, `report.compare`, `report.current_exposure`, `report.decision_velocity`, `report.exposure_anomalies`, `report.filter_schema`, `report.mistakes`, `report.open_positions`, `report.opportunity`, `report.playbook_adherence`, `report.pnl`, `report.risk`, `report.source_quality`, `report.strategy_performance`, `report.strengths`, `report.unscored_forecasts`, `report.watchlist`, `report.audit_readiness`, `review.bundle`, `signal.scan`.
- Bundle/scan/import/export/admin: `market.scan.dry_run`, `market.scan.promote`, `journal.bundle.plan`, `journal.bundle.status`, `import.validate`, `import.commit`, `import.csv_fills`, `export.drain`, `journal.init`, `journal.status`, `journal.schema`, `journal.config_set`, `journal.backup`, `journal.restore`, `journal.rebuild_projections`, `journal.rescan_scoring`, `journal.repair`, `journal.fixture_seed`, `tool.schema`, `idea.capture`, `model.import`, `model.warm`, `keyring.revoke`.

Machine-interface architecture:

- `ToolRegistry` stores canonical `subject.verb` names and derives CLI invocation by splitting on dots (`tool_registry.py:1-8`, `59-68`).
- `core.dispatch` validates actor identity, idempotency on writes, optional dry-run, calls the same handler for CLI/MCP, and returns typed envelopes (`core.py:109-274`).
- MCP tool specs are generated from the registry; no plugin discovery/eval/exec at boundary (`mcp_server.py:45-74`). MCP calls use `dispatch` (`mcp_server.py:92-118`).
- Stdio MCP server only uses stdin/stdout, with `MCP_ACTOR_ID` or default `agent:mcp-default` (`mcp_server.py:32-42`, `218-241`).

## 6. Security/Scope Boundaries

- **No trading execution:** Product docs repeatedly exclude execution (`README.md:108-117`; `docs/VISION.md:20-29`; `docs/PRD.md:463-469`). Source behavior observed: `market.scan` states no execution/no advice/no fetch (`market_scan.py:1-6`, `295-306`); `decision.add` creates local position projection only for `paper_enter` and otherwise records rows (`ledger.py:851-1027`).
- **No default outbound network:** README says fresh init/MCP startup make zero outbound calls and no telemetry (`README.md:119-146`). MCP adapter is stdio-only (`mcp_server.py:1-7`, `218-241`). `market.scan` does not fetch source URLs and records caller-supplied provenance only (`market_scan.py:162-168`).
- **Credential handling:** Ledger rejects credential-shaped metadata and secret-like free text in key paths (`ledger.py:54-127`, `216-219`, `377-383`, `856-861`); strategy/playbook/memory scan long-form fields (`strategy.py:68-72`, `playbook.py:121-123`, `memory.py:216-218`). MCP tool specs assert no secret transport hints (`mcp_server.py:77-90`).
- **Append-only invariants:** Source/event tables are intended append-only; migration triggers forbid UPDATE/DELETE on major ledger tables (`m003_m1_ledger.py:386-432`). `positions` is an allowed mutable projection.
- **Opt-in embeddings ambiguity:** Docs describe optional local/API embedding paths. Inspected `memory.py` semantic rank uses stored vectors and deterministic query embeddings; `api:openai` branch checks keyring presence but comments say no OpenAI/network embedding call is implemented there (`memory.py:1050-1057`). Model import/warm tooling was not inspected.

## 7. Doc or Status Drift / Uncertainties

1. **Snapshots segmentation drift:** PRD states segmentation fields ship on `snapshots` (`docs/PRD.md:145`), but inspected M003 `snapshots` table lacks `agent_id/model_id/environment/run_id` and `_snapshot_add` does not use `common_metadata` (`m003_m1_ledger.py:71-89`; `ledger.py:303-368`). Could be added by a later migration not inspected; verify before relying on snapshot segmentation.
2. **Report status drift:** PRD has both deferred-language and shipped-language for comparison/strategy/risk/opportunity/review-bundle/market-scan (`docs/PRD.md:390-396` vs `515-525`). Registry shows shipped tool surfaces, but exact completeness was not verified.
3. **`strategy.show` summary counts:** PRD says `strategy.show` returns summary counts once joins are wired (`docs/PRD.md:428`); inspected implementation returns only row fields (`strategy.py:230-269`).
4. **Memory reflect edge-sugar drift:** Source explicitly rejects docs-mentioned `derived_from/supports/contradicts/supersedes` sugar on `memory.reflect` as deferred; callers must use `memory.link` (`memory.py:335-459`).
5. **Embedding docs vs implementation:** README/PRD mention optional local and OpenAI API embeddings; inspected recall implementation does not call OpenAI and uses deterministic query stub when provider/key exists (`memory.py:1021-1057`). Needs deeper inspection of `memory.reindex`, `model.import`, `model.warm`, and docs before stating full embedding capability.
6. **Forecast scoring breadth:** PRD says binary MVP; source validates categorical/scalar inputs. Static inspection did not establish whether non-binary scores are supported or record-only.
7. **Source attachment validation:** Registry confirms source attach tools; this pass did not read the later `ledger.py` sections containing those handlers.
8. **Tests not run:** No test suite was run; no live DB was initialized; no end-to-end MCP/CLI parity calls were executed.

## 8. Implications for Taxonomy and Phase 1

- Treat **ledger facts**, **agent beliefs**, **reflections**, **procedural rules**, and **strategy hypotheses** as separate taxonomic classes. The code already encodes that separation; Phase 1 should not blur it.
- Define memory write standards: when to create `observation` vs `reflection` vs `playbook_rule`; required links; recommended `importance`, `confidence_base`, `decay_rate_per_day`, `valid_from/valid_to`, and tags.
- Define agent-session protocols for cron/fresh sessions: recall before thesis, write thesis/forecast/decision, resolve/scoring later, prompt reflection after outcome, promote rule when repeated enough, record adherence on later decisions.
- Use strategies as a first-class “edge thesis” axis, not as tags. Phase 1 should specify strategy lifecycle, archive semantics, and how strategy-scoped recall/reporting should be used.
- `market.scan` can become a canonical intake template for agent market reviews because it enforces caller-supplied data, required resolution criteria, checks, child idempotency keys, and optional reflection attachment.
- Segmentation fields (`agent_id/model_id/environment/run_id`) should be elevated in taxonomy for multi-agent/model calibration, but first verify exact schema coverage across migrations.
- Playbook taxonomy needs guardrails: rules are advisory memory nodes with adherence rows, not executable constraints. Phase 1 should define rule granularity and override reason vocabulary.
- Report taxonomy should distinguish objective system metrics from agent-authored judgments. `report.coach` and deterministic reports should feed prompts/reflections, not become advice.

## 9. Evidence Trail

Files inspected:

- `README.md`: product status, install/quickstart, boundaries, security/no-network/no-credentials/no-telemetry, docs index (`README.md:3-23`, `49-90`, `92-117`, `119-146`, `151-180`).
- `docs/VISION.md`: product boundary, principles, four-layer loop, strategy-scoped learning, safety posture (`docs/VISION.md:8-29`, `38-49`, `64-109`, `163-170`, `172-185`).
- `docs/PRD.md`: MVP/post-MVP scope, CLI/MCP parity, no fetch, embeddings, ledger schema, memory graph, reports, playbooks, resolution, sources, strategies, imports, milestones, DoD/open questions (`docs/PRD.md:9-29`, `45-67`, `117-145`, `147-340`, `342-445`, `471-601`).
- `docs/architecture/*.md`: file list inspected via search included contracts, memory-layer, scoring, reports, persistence, operability, market-scan-contract, security, current-exposure-agent-contract, imports, risk/opportunity, dogfood-protocol. Detailed line reads were not performed for all architecture docs in this pass.
- `src/trade_trace/core.py`: shared registry/dispatcher, idempotency, dry-run, envelope handling (`core.py:1-8`, `50-75`, `109-274`).
- `src/trade_trace/contracts/tool_registry.py`: registry, CLI invocation mapping, collision validation, schema metadata (`tool_registry.py:1-8`, `59-68`, `74-190`).
- `src/trade_trace/mcp_server.py`: stdio MCP, registry tool specs, schema validation, dispatch bridge, actor identity (`mcp_server.py:1-7`, `32-42`, `45-74`, `92-118`, `141-241`).
- `src/trade_trace/tools/ledger.py`: ledger/source/security/idempotency/scoring/decision handlers read in representative detail (`ledger.py:1-12`, `54-127`, `154-368`, `371-481`, `484-788`, `851-1117`, `1120-1200`).
- `src/trade_trace/tools/memory.py`: memory node/edge/recall implementation, recall ranking, strategy context, semantic stub, registration (`memory.py:1-24`, `63-76`, `177-333`, `335-540`, `565-722`, `725-999`, `1001-1088`, `1147-1200`).
- `src/trade_trace/tools/market_scan.py`: dry-run/promote contracts and no-fetch/no-advice boundaries (`market_scan.py:1-6`, `22-24`, `31-60`, `154-306`, `370-490`).
- `src/trade_trace/tools/reports.py`: report schemas/imports/handlers for calibration/playbook/source/audit/current exposure overview (`reports.py:1-13`, `26-44`, `85-269`, `502-650`).
- `src/trade_trace/tools/strategy.py`: strategy create/list/show/update implementation (`strategy.py:1-12`, `59-433`).
- `src/trade_trace/tools/playbook.py`: playbook/adherence surface and validation (`playbook.py:1-29`, `50-112`, `118-236`, `301-500`).
- `src/trade_trace/storage/migrations/m003_m1_ledger.py`: M1 schema, segmentation columns, append-only triggers (`m003_m1_ledger.py:8-27`, `29-385`, `386-432`).
- Registry enumeration via local Python in repo: confirmed current tool names listed in §5.

## 10. Side Effects

- Files written: `/home/hermes/code/trade-trace/docs/research/agentic-trade-trace/01-current-system-baseline.md`.
- Files modified besides this artifact: none.
- Memory retained: none.
- External/network side effects: none; no network fetches were run.
- Implementation changes: none.
- Other local side effects: one read-only Python command imported `trade_trace.core` and printed registry names; no journal DB initialization or writes were performed by that command.
