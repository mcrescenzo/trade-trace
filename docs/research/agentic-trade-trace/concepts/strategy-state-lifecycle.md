# Concept Dossier: Strategy State and Lifecycle

## 1. Question

Should Trade Trace treat strategy as a first-class agentic lifecycle object — an edge-thesis scope for memory, decisions, forecasts, reports, reviews, playbooks, bootstrap, and policy safety — rather than as a tag-like classifier; and if so, what state semantics are needed beyond the current active/archived strategy row?

## 2. Bottom Line

- Recommendation: adopt core.
- Confidence: high for strategy as a core scoping axis; medium for adding lifecycle states beyond `active`/`archived`.
- Why: Current docs and source already make strategies first-class, orthogonal to tags and playbooks, and usable for scoped reports/recall/reflection. The agentic research program strengthens this: fresh-session agents need bounded strategy context to avoid smearing lessons, forecasts, and performance across unrelated edge theses. However, richer statuses such as proposed/dormant/superseded are candidate semantics, not implementation-approved, because current implementation only supports `active` and `archived` and PRD explicitly defers strategy versioning until point-in-time hypothesis queries become load-bearing.

## 3. Agent-Specific Problem

A human trader can often remember that two trades belonged to different “setups,” that one setup is paused, or that a thesis was replaced by a newer hypothesis. A fresh-session LLM trading agent cannot rely on that implicit continuity. If strategy state is weak, the agent faces several agent-specific failures:

- It may retrieve reflections from the wrong edge thesis and apply stale lessons to unrelated decisions.
- It may evaluate calibration, P&L, playbook adherence, source quality, and non-actions as one blended population, hiding strategy-specific strengths and errors.
- It may keep acting on archived or regime-stale ideas because the startup context does not distinguish active, dormant, proposed, and superseded strategy states.
- It may promote a reflection into a global playbook rule when the lesson only applies inside one strategy scope.
- It may re-open an old strategy without preserving why it was paused, retired, or replaced.

For an agent-only product, strategy lifecycle is not a human organization convenience. It is a machine-readable boundary for context selection, review obligations, policy scope, replay case selection, and bootstrap prioritization.

## 4. Current Baseline

### Implemented behavior observed in source/tests

- `src/trade_trace/tools/strategy.py` defines first-class strategy tools and states that strategies are rows, not tags; each row has unique `slug`, `name`, optional `description`/`hypothesis`, and `status` in `active | archived` (`strategy.py:1-11`, `38`).
- `strategy.create` creates a strategy row, rejects invalid/duplicate slugs, defaults status to `active`, scans long-form description/hypothesis for secrets, and emits a `strategy.created` event (`strategy.py:59-161`).
- `strategy.list` defaults to active rows and can list archived or both via status filtering (`strategy.py:192-227`). Note: implementation uses `status='both'`, while PRD text says `status='all'`; this is a doc/source drift to preserve in downstream synthesis.
- `strategy.show` returns the strategy row by ID or slug but does not return the PRD-planned summary counts (`strategy.py:230-269`; baseline also flags this drift).
- `strategy.update` mutates description, hypothesis, status, and `meta_json`; `name` and `slug` are immutable; archive is expressed as `status='archived'`; updates emit `strategy.updated` events and idempotent replay returns original results (`strategy.py:272-383`).
- Integration tests cover registration, create/list/show/update, duplicate/invalid slug rejection, immutable name/slug, archive via update, idempotency behavior, archived strategy readability, and strategy-scoped memory recall (`tests/integration/test_strategy_tools.py:1-330`).
- `m010_strategy_id_new_row_triggers.py` enforces that new `decisions.strategy_id` and `theses.strategy_id` values refer to existing strategy rows while preserving `NULL` as canonical no-strategy state (`m010_strategy_id_new_row_triggers.py:11-29`).
- Strategy-scoped memory recall is tested by attaching a memory node to a strategy through an `about` edge and confirming `memory.recall(context={kind: "strategy", id})` does not demote the strategy-attached node (`test_strategy_tools.py:276-329`).

### Planning/documentation baseline

- `docs/PRD.md` defines strategies as named persistent entities grouping decisions, theses, and reviews under one edge thesis so the loop can run per strategy: scoped reports, scoped recall, and reflections targeting a strategy (`docs/PRD.md:117-120`).
- PRD locked decisions: strategies are first-class, orthogonal to playbooks and tags; MVP uses single nullable `strategy_id`; strategy rows are mutable with append-only audit; status is `active` or `archived`; tools use opaque `strategy_id`; reports use sentinel `"__none__"` to select rows with no strategy (`docs/PRD.md:121-131`).
- PRD explicitly says tags are free-form sub-classifiers and never substitute for a strategy (`docs/PRD.md:95-100`).
- PRD explicitly says playbooks codify process rules while strategies group edge theses; each axis is independent (`docs/PRD.md:79-83`, `289-292`).
- PRD open questions defer strategy versioning and many-to-many decision-strategy joins until dogfood shows point-in-time hypothesis queries or composite-row workarounds are insufficient (`docs/PRD.md:590-595`).
- Baseline research concludes strategies are implemented and agentically relevant, but current `strategy.show` is row-only and strategy versioning remains deferred (`01-current-system-baseline.md:31`, `76-83`).

### Research baseline

- Taxonomy classifies Strategy state and lifecycle as core and frames it as tracking named edge theses from active to archived with associated decisions, theses, reviews, reflections, diagnostics, and hypothesis evolution (`02-concept-taxonomy.md:45`).
- Foundational continuity says strategies are part of recorded facts and should feed startup context, lifecycle state, work obligations, and strategy-scoped recall (`foundational-continuity.md:60-78`, `122-125`).
- External synthesis says human journal patterns and memory/calibration needs strongly support strategy/setup segmentation as a strategy health/state primitive (`external-evidence.md:38-44`, `105-116`).
- Decision-control synthesis identifies strategy research as downstream of work queue, non-actions, playbook predicates, and quarantine because strategy reviews and scoped rules need decision-control context (`agent-decision-control-surface.md:191-194`, `224-232`).

## 5. Candidate Product Shape

Strategy should be understood as an **edge-thesis lifecycle**, not a tag, folder, or playbook. Conceptually, a strategy is a durable hypothesis about a repeatable source of edge or process pattern, with scoped evidence and state.

Candidate lifecycle semantics:

- **Proposed**: an agent has identified a possible edge thesis, but it is not yet eligible for active decision attribution. Useful for quarantine/research notes and preventing premature performance grouping. Current system has no draft/proposed state; this is a candidate future semantic.
- **Active**: current implemented status. The strategy is eligible for new theses, decisions, forecasts, memory recall context, scoped reports, and bootstrap inclusion.
- **Dormant**: not retired, but not currently pursued. Typical reasons: low sample size, regime uncertainty, missing sources, unresolved calibration concerns, or no current instruments. It should appear in periodic review/work queue but not dominate bootstrap like active strategies. Current system has no dormant state; today agents must emulate via `archived`, tags, or `meta_json`.
- **Archived**: current implemented status. Soft-retired; remains a valid target for historical rows and review/replay. Should not be used for new decisions except explicit reactivation/reopen semantics.
- **Superseded**: the strategy hypothesis has been replaced by a new strategy or materially changed version. This is different from archive: archive says “retired”; superseded says “do not apply old hypothesis; use successor.” Current rows can emit update events, but there is no first-class successor relationship or version table.

Candidate strategy review cadence:

- **After material outcome resolution**: if a resolved outcome affects a strategy’s calibration, P&L, source quality, or playbook adherence materially, surface a strategy-review obligation.
- **After sample thresholds**: e.g., after N decisions/forecasts under a strategy, produce low-N/sample-size caveats or request strategy review. Exact thresholds are open.
- **Time-based cadence**: surface stale active/dormant strategies for periodic review without creating an internal scheduler. The work queue/bootstrap should expose due reviews; external cron triggers the agent.
- **Before policy promotion**: any reflection promoted into playbook policy should state whether it is strategy-scoped or global and cite strategy-level evidence.
- **At bootstrap**: include active strategies by default, dormant/archived only when due or specifically queried, and proposed/superseded as caveated context if supported later.

Candidate strategy “health” view, conceptually read-only unless future evidence justifies durable state:

- status and lifecycle reason;
- current hypothesis and last hypothesis-change event;
- linked decisions/theses/forecasts/outcomes/reviews/reflections/playbook adherence;
- unresolved forecasts and stale watches under the strategy;
- source-quality and audit-readiness caveats;
- calibration/P&L/opportunity diagnostics with low-N warnings;
- quarantined reflections or policy candidates scoped to the strategy;
- successor/predecessor links if superseded semantics are adopted.

## 6. Required Data/State

Existing state already provides much of the spine:

- `strategies`: `id`, `name`, `slug`, `description`, `hypothesis`, `status`, timestamps, actor, and internal `meta_json` in source.
- Links from decisions and theses through `strategy_id`; PRD also describes reviews with `strategy_id`.
- Strategy as an allowed edge endpoint for memory/reflection links.
- Events: `strategy.created` and `strategy.updated` preserve an audit trail for mutations.
- Memory nodes/reflections/playbook rules can link to strategies through edges.
- Reports can filter by `strategy_id` and `"__none__"` sentinel per PRD and baseline.

Candidate additional conceptual state, if dogfood justifies it:

- Lifecycle state beyond `active | archived`: proposed, dormant, superseded, possibly with reason codes.
- Review cadence fields or derivable timestamps: last reviewed, review due, review reason, sample-size threshold reached, stale-by-time.
- Strategy lineage: predecessor/successor relationships for superseded strategies or materially changed hypotheses.
- Point-in-time hypothesis state: either reconstruct from `strategy.updated` events or promote to explicit versions if replay/reflection needs exact “what did the agent believe when decision X was made?” queries.
- Strategy-scoped policy candidates: quarantine status for reflections proposed as strategy-specific playbook rules.
- Dormancy/reactivation reasons: to distinguish intentionally paused strategies from forgotten active ones.

Important constraint: these are data/state needs for concept evaluation, not an implementation specification. Current product already has a minimal implemented strategy object; richer state should be adopted only if it materially improves bootstrap, recall, reviews, replay, or policy safety.

## 7. Machine Interface Implications

Future machine interfaces should keep strategies JSON-first and process-oriented:

- Agents need a way to list strategies by lifecycle state, with explicit counts and truncation/caveats. Current `strategy.list` handles active/archived/both but not proposed/dormant/superseded.
- Startup/bootstrap should include a bounded strategy section: active strategy summaries, due strategy reviews, unresolved forecasts/watches by strategy, quarantined strategy-scoped reflections, and low-N/stale caveats.
- `memory.recall` should continue to accept strategy context so recall can be narrowed to relevant edge-thesis memory.
- Reports should preserve filter semantics: omitted/null strategy filter means no filter; `"__none__"` means only unscoped records. This avoids accidental exclusion of pre-strategy or unclassified rows.
- Strategy “show” or health surfaces should return IDs for drilldown rather than prose-only summaries: linked decision IDs, forecast IDs, review IDs, reflection IDs, source-quality caveat IDs, and work-queue obligation IDs if such objects exist later.
- Strategy lifecycle updates, if later supported, should be explicit writes with idempotency and audit events, not silent inference from performance.
- Strategy outputs must not recommend market action. Allowed: “strategy review due,” “low sample size,” “hypothesis changed,” “unresolved forecasts under this strategy,” “archived strategy referenced by new decision,” “quarantined reflection candidate exists.” Forbidden: “enter this strategy,” “size up/down,” or “best strategy to trade.”

## 8. Evidence

- Repo evidence:
  - `src/trade_trace/tools/strategy.py:1-11`, `38`, `59-161`, `192-227`, `230-269`, `272-383`, `386-433` implements first-class strategy CRUD with active/archived status, soft archive, immutable slug/name, mutable hypothesis/description/status, and emitted events.
  - `tests/integration/test_strategy_tools.py:1-330` verifies tool registration, lifecycle mutations, archiving behavior, idempotency, and strategy-scoped recall.
  - `src/trade_trace/storage/migrations/m010_strategy_id_new_row_triggers.py:11-29` enforces new decision/thesis strategy references without rewriting history.
  - `docs/PRD.md:79-83`, `95-100`, `117-131`, `281-287`, `422-433`, `590-595` distinguishes strategies from tags/playbooks, defines active/archived rows, strategy report/recall filters, and open questions for versioning/many-to-many links.
  - `docs/research/agentic-trade-trace/01-current-system-baseline.md:31`, `76-83`, `87-93` notes implemented strategy support and current gaps/drift.
- External evidence, if used:
  - `external/human-trading-journal-patterns.md:26-33`, `98-105`, `148-163` supports strategy/setup segmentation and separation from tags/playbooks as common journal patterns, with vendor-source caveats.
  - `synthesis/external-evidence.md:38-44`, `84-116` says external research strengthens strategy state/lifecycle as a core/supporting axis for recall, reports, reflection, and strategy health.
- User-stated intent:
  - Research contract frames Trade Trace as an agent-only continuity, memory, calibration, and process-control substrate and includes durable tracking of strategies in scope (`00-research-contract.md:10-29`).
  - Task prompt asks specifically for strategy as edge-thesis lifecycle and scoping axis for agent memory, decisions, forecasts, performance, playbooks, reviews, and bootstrap, with active/archived/dormant/proposed/superseded semantics.
- Inferences:
  - Because fresh-session agents lack implicit memory, strategy state must scope retrieval and review obligations to prevent context pollution.
  - Because PRD treats strategies, tags, and playbooks as orthogonal, richer strategy lifecycle should not be implemented by overloading tags or playbook versions.
  - Because current source only supports active/archived, proposed/dormant/superseded should remain candidate semantics until dogfood proves their necessity.

## 9. Risks/Failure Modes

- Strategy/tag conflation: agents may use tags for edge thesis or strategy for ad hoc labels, destroying report and recall semantics.
- Strategy/playbook conflation: strategy-specific lessons may become global playbook rules, or process rules may be treated as edge hypotheses.
- Status sprawl: adding proposed/dormant/superseded too early may create lifecycle complexity without dogfood evidence.
- Stale active strategies: without dormant/review semantics, active rows may accumulate and poison bootstrap context.
- Archive misuse: archived may be overloaded to mean paused, invalid, superseded, low-confidence, or merely inactive.
- Mutable-hypothesis ambiguity: current update events preserve audit history, but agents may need easier point-in-time reconstruction for replay and reflection.
- Low-N overfitting: strategy performance or calibration may be treated as meaningful with too few cases.
- Survivorship bias: archived/superseded strategies may disappear from default views and make failed edge theses invisible.
- Advice creep: ranking strategies by “best” performance can become trade recommendation rather than retrospective diagnostics.
- Composite-strategy workaround loss: single strategy IDs may lose information when decisions naturally belong to multiple strategies.

## 10. Dependencies/Conflicts

Dependencies:

- Fresh-session bootstrap context pack: strategy state is a core section and filter for startup context.
- Decision and non-action lifecycle: strategy-scoped active/due/resolved/unreviewed states derive from decisions, watches, skips, holds, reviews, theses, forecasts, and outcomes.
- Agent work queue / next actions: strategy reviews, dormant re-checks, stale active strategies, and unresolved strategy-scoped forecasts become due process obligations.
- Recall receipts: strategy-scoped recall should be auditable so agents can know which strategy memories were returned and used.
- Reflection-to-policy quarantine: strategy-scoped reflections need evidence before becoming playbook policy, and promotion should preserve scope.
- Machine-checkable playbook predicates: predicate/adherence reports may be sliced by strategy but should not make strategy a rule container.
- Forecast-vs-market diagnostics and report surfaces: strategy is a key filter/grouping axis.
- Replay/regression: old cases need the strategy hypothesis and lifecycle state as of the original decision time.

Conflicts/tensions:

- Current implemented lifecycle is only `active | archived`; richer semantics conflict with PRD’s explicit deferred versioning/lifecycle simplicity unless dogfood proves need.
- `strategy.list` source accepts `both` while PRD describes `all`; downstream specs should resolve this doc/source drift before relying on a status enum name.
- Strategy versioning is attractive for replay, but the PRD intentionally defers it to avoid premature schema growth.
- Strategy-playbook coupling is tempting, but PRD explicitly keeps them orthogonal and defers a linking table.
- Strategy review cadence can look like scheduling; it must remain report/queue/bootstrap data, not daemon behavior.

## 11. Open Questions/Falsifiers

Open questions:

- Are `active` and `archived` sufficient if agents use metadata/reviews to express dormant/proposed/superseded states, or does this cause missed obligations and context poisoning?
- Should “proposed” strategies exist as strategies, memory nodes, or quarantined reflections until activated?
- Is “dormant” a status, a derived condition, or a work-queue/review state over an active/archived row?
- Should “superseded” be a strategy status, an edge relationship, an event-derived lineage, or a full strategy version concept?
- What review cadence is useful without creating scheduler scope: time-based, sample-count-based, outcome-triggered, or policy-promotion-triggered?
- When does point-in-time strategy hypothesis become load-bearing enough to justify explicit versions instead of event-log reconstruction?
- How should an agent reopen/reactivate an archived or dormant strategy without losing the reason it was paused?
- How should multi-strategy decisions be handled if composite strategy rows become too lossy?

Falsifiers:

- Dogfood shows agents can reliably bootstrap, recall, review, and replay strategy-scoped work using only `active | archived`, current events, report filters, and disciplined prose.
- Strategy-scoped reports/recall produce no materially better agent behavior than instrument/tag/playbook filtering.
- Rich statuses create confusion, inconsistent use, or noisy bootstrap sections without reducing missed obligations.
- Point-in-time hypothesis reconstruction from existing events is sufficient for replay and reflection in real cases.

## 12. Decision Hook

This dossier should feed:

- `trade-trace-9lgd` — cross-concept dependency/conflict map and ranked primitive recommendations.
- Replay/regression research — strategy hypothesis/state as original-context evidence.
- Forecast-vs-market diagnostics research — strategy as a key calibration/performance grouping axis.
- Multi-agent handoff research — strategy state as part of handoff/bootstrap context, if that deferred concept is revisited.

## 13. Side Effects

Files written:

- `docs/research/agentic-trade-trace/concepts/strategy-state-lifecycle.md`

Memory retained: none.  
External side effects: none.  
Implementation changes: none; no code, schemas, tests, README/PRD/VISION, Beads, config, or implementation-bearing files were edited.
