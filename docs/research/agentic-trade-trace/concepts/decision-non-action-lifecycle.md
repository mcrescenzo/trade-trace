# Concept Dossier: Decision and Non-Action Lifecycle

## 1. Question

Should Trade Trace adopt a unified decision lifecycle in which trades, watches, skips, holds, thesis changes, invalidations, reviews, forecasts, outcomes, source attachments, playbook adherence, and reflection handoff are treated as one auditable machine-readable process for fresh-session LLM trading agents?

## 2. Bottom Line

- Recommendation: adopt core
- Confidence: high
- Why: Current source and planning docs already model most of this lifecycle: `decision.add` supports a closed set of trade and non-trade decision types; forecasts carry resolution rules and auto-scoring hooks; `watch` rows can carry review deadlines; sources attach to theses/forecasts/decisions; playbook adherence is normalized; reports surface stale watches, unscored forecasts, missing reflections, and missing adherence. The remaining gap is not the absence of ledger tables, but the absence of a canonical agent-session lifecycle that tells a fresh LLM what unresolved intent exists, what must be reviewed next, and how non-actions should be closed or reflected instead of disappearing between sessions.

## 3. Agent-Specific Problem

A human trader may remember why they watched, skipped, held, deferred, or invalidated an idea even if the journal is sparse. A fresh-session LLM trading agent has no such continuity. If a cron-triggered agent records only executed trades, then the most important negative space vanishes:

- a watched opportunity loses its original trigger and revisit deadline;
- a skipped market loses the reason it was rejected and cannot teach future avoidance or missed-opportunity lessons;
- a hold/defer decision looks like no decision at all unless explicitly recorded;
- an invalidated or updated thesis may leave later agents with stale reasoning unless linked to the old thesis and reviewed;
- an unresolved forecast may never be scored if it is not surfaced as due work;
- a playbook override becomes unlearnable unless the rule, status, reason, and outcome are joined later;
- a later reflection cannot distinguish “agent remembered prior context and ignored it” from “prior context was never retrieved.”

This concept matters because non-actions are not inert for an LLM agent. They are durable intent, deferred obligations, and calibration data. Without structure, a new session sees only the latest prompt and whatever records it happens to query, so unresolved intent is silently dropped.

## 4. Current Trade Trace Baseline

### Implemented behavior observed in source

- Decision types are a closed, validated set. `DECISION_MATRIX` includes `watch`, `skip`, `paper_enter`, `paper_exit`, `actual_enter`, `actual_exit`, `add`, `reduce`, `hold`, `invalidate_thesis`, `update_thesis`, `resolved`, and `review`, with required/optional/forbidden fields per type (`src/trade_trace/tools/decision_matrix.py:16-82`, `142-189`).
- `decision.add` enforces that matrix, rejects secret-shaped rationale text, stores tags, segmentation fields, `review_by`, strategy/playbook references, risk/edge estimates, metadata, and emits a `decision.created` event (`src/trade_trace/tools/ledger.py:853-1006`).
- `paper_enter` has local projection behavior only: it writes a `position_events` open event and rebuilds local positions; other decision types are ledger rows, not execution (`src/trade_trace/tools/ledger.py:1007-1024`).
- Forecasts carry `resolution_at`, `yes_label`, `resolution_rule_text`, outcome probabilities, segmentation, scoring state, and late-recording metadata when applicable (`src/trade_trace/tools/ledger.py:640-788`).
- Outcomes can trigger auto-scoring for supported forecasts when `resolved_final` is recorded, per baseline source inspection (`docs/research/agentic-trade-trace/01-current-system-baseline.md:25-28`).
- Source attachment tools exist for theses, decisions, forecasts, and memory nodes (`docs/research/agentic-trade-trace/01-current-system-baseline.md:55`). `market.scan.dry_run` can plan source attachments to thesis, forecast, and decision (`src/trade_trace/tools/market_scan.py:255-288`).
- `market.scan.dry_run/promote` already packages caller-supplied `watch`, `skip`, and `paper_enter` bundles into venue/instrument/snapshot/source/thesis/forecast/decision/reflection calls, with deterministic child idempotency keys and explicit no-fetch/no-advice/no-execution checks (`src/trade_trace/tools/market_scan.py:1-6`, `22-24`, `154-306`, `370-459`).
- `report.watchlist` lists outstanding `watch` decisions and surfaces both age-based stale status and `review_by` overdue status (`src/trade_trace/reports/watchlist.py:1-13`, `50-100`).
- `report.unscored_forecasts` lists pending supported forecasts past `resolution_at` without a non-superseded `resolved_final` outcome (`src/trade_trace/reports/unscored.py:1-7`, `31-95`).
- `memory.reflect` writes a reflection node plus an `about` edge to a ledger/memory target in one transaction, preventing orphan reflection rows on that path (`src/trade_trace/tools/memory.py:462-540`).
- Playbook version proposals require a provenance reflection node (`src/trade_trace/tools/playbook.py:407-462`).
- Coach/report hygiene detects sampled decisions lacking attached reflections and playbook-scoped decisions lacking adherence rows (`src/trade_trace/reports/coach.py:360-392`).
- `review.bundle` selects decisions and walks to related sources, reflections, playbook versions, theses, forecasts, outcomes, and positions, returning deterministic data without LLM commentary or trade recommendations (`src/trade_trace/tools/review_bundle.py:1-13`, `140-220`).

### Planning/doc evidence

- Vision principle: “Every decision is reviewable. Trades, skips, watches, paper trades, and thesis updates all create reviewable artifacts. A skipped trade is as important as an entered one” (`docs/VISION.md:40-42`).
- Vision persona: the LLM agent records known context, decides whether to watch/skip/paper/enter/exit/hold/add/reduce/invalidate/update, receives grading, recalls past observations/rules, and writes reflections/playbook updates (`docs/VISION.md:53-61`).
- PRD lists the same 13 decision types and describes `watch` review deadlines, record-only actual decisions, local-only paper projection, decision tags, and playbook rule adherence rows (`docs/PRD.md:194-238`).
- PRD states forecasts should record resolution rules to reduce hindsight ambiguity and distinguishes scoring support/state (`docs/PRD.md:175-184`).
- PRD defines sources as caller-supplied provenance and explicitly says Trade Trace never fetches URLs or local paths automatically (`docs/PRD.md:260-268`).

### Gaps and drift relevant to this concept

- There is no single named lifecycle primitive that ties thesis creation, forecast creation, decision/non-action, source attachment, playbook adherence, outcome, review, reflection, and closure state into one inspectable object.
- `watch` has `review_by` and watchlist reporting, but `skip`, `hold`, `update_thesis`, `invalidate_thesis`, and `review` do not have equally explicit closure/revisit semantics beyond decision type, reason, and later reports.
- `market.scan` standardizes only `watch`, `skip`, and `paper_enter`; broader lifecycle transitions such as `hold`, `paper_exit`, `invalidate_thesis`, `update_thesis`, and `review` remain lower-level `decision.add` uses.
- Current reflection and playbook adherence are agent-driven. The system can surface hygiene gaps, but it does not enforce that every lifecycle transition has a reflection, adherence rows, source links, or outcome linkage.
- Review rows are documented in PRD, but the baseline artifact did not establish an implemented `review.add` primitive; current review handoff appears centered on `decision.type='review'`, `review.bundle`, reports, and `memory.reflect`.

## 5. Candidate Product Shape

The core product shape should be a conceptual lifecycle, not a new implementation commitment:

1. **Idea intake / thesis state**
   - Agent records or reuses instrument, snapshot, sources, thesis, and optional strategy.
   - Thesis has falsification/exit/risk notes where applicable.

2. **Forecast state**
   - Agent records probability-bearing forecast before outcome, with `resolution_at`, `resolution_rule_text`, and source attachments.
   - Forecast lifecycle includes pending, scored, failed/ambiguous, superseded, or late-recorded caveats.

3. **Decision / non-action state**
   - Agent records one of the validated decision types.
   - Non-actions are not second-class: `watch`, `skip`, `hold`, `defer`-like watches/holds, `invalidate_thesis`, `update_thesis`, and `review` are lifecycle transitions.
   - Each row should be interpretable as either an exposure-changing action, a local-paper action, a record-only actual action, a non-action, a thesis-state transition, or a review marker.

4. **Evidence attachment state**
   - Sources attach to thesis, forecast, decision, and later reflections where useful.
   - Source stance and freshness should be preserved so later agents can audit whether the decision was evidence-backed, contradicted, or unsupported.

5. **Process adherence state**
   - If a playbook version was in scope, the agent records considered/followed/overridden/not-applicable rows with reasons.
   - Overrides are later reviewable against outcomes, but the system should not decide whether the override was good trading advice.

6. **Pending obligation state**
   - Watches with `review_by`, unresolved forecasts past `resolution_at`, open/paper positions, stale watches, missing sources, missing adherence, and decisions without reflections become inspectable pending work for later sessions.

7. **Outcome / closure state**
   - Agent records outcomes supplied by caller-side research; Trade Trace scores supported forecasts and retains ambiguous/provisional/disputed statuses.
   - Decisions and non-actions should be reviewable even when no trade occurred.

8. **Review / reflection handoff state**
   - Reports and review bundles gather decision context.
   - Agent writes reflection linked to decision/thesis/forecast/strategy/period as appropriate.
   - Repeated or high-confidence reflections may later support playbook version proposals, but only through explicit provenance.

9. **Lifecycle inspection state**
   - A fresh session should be able to ask: “What active or unresolved decision intents exist, why were they created, what evidence did they use, what was due, what resolved, what needs reflection, and which playbook rules were followed or overridden?”

## 6. Required Data / State

This concept depends primarily on existing primitives:

- **Ledger entities:** instruments, snapshots, theses, forecasts, forecast outcomes, decisions, outcomes, positions/position events where relevant.
- **Decision state:** `type`, `reason`, `review_by`, `side`, quantity/price where allowed, strategy/playbook references, tags, risk/edge fields, common segmentation fields, metadata.
- **Forecast state:** `resolution_at`, `resolution_rule_text`, outcome probabilities, scoring support/state, yes label, late-recorded flag, supersession/invalidated semantics.
- **Source state:** source rows, stance, freshness/retrieval/content metadata, redaction status, edges to thesis/forecast/decision/memory node.
- **Playbook state:** playbook version id on decisions; decision-playbook-rule rows with status and reason.
- **Memory/reflection state:** reflection nodes linked by `about` edges; possible supports/contradicts/supersedes edges through `memory.link` where appropriate.
- **Strategy state:** strategy id on thesis/decision/review scopes, active/archived status for context boundaries.
- **Work/review signals:** watchlist overdue/stale rows, unscored forecasts, coach hygiene callouts, review bundles.
- **Agent attribution:** `agent_id`, `model_id`, `environment`, `run_id`, actor id, idempotency key, event log.

Potential lifecycle statuses can be derived conceptually rather than added immediately: active watch, overdue watch, skipped closed, skipped later contradicted by outcome, hold awaiting next review, forecast due/unscored/scored, thesis superseded/invalidated, decision reflected/unreflected, playbook adherence missing/present, source evidence missing/present/stale.

## 7. Machine Interface Implications

Agent-facing surfaces should remain CLI/MCP/JSON-first and local-only. Conceptually, the lifecycle implies these interface expectations:

- `decision.add` remains the canonical low-level write for lifecycle transitions, using the decision matrix and idempotency semantics.
- `market.scan.dry_run/promote` is the best current high-level intake shape for scanner-style `watch`, `skip`, and `paper_enter` decisions because it returns checks, missing fields, ordered calls, child idempotency keys, and no-advice/no-fetch boundaries.
- A fresh-session agent should inspect reports before acting: `report.watchlist`, `report.unscored_forecasts`, `report.open_positions`/current exposure where relevant, `report.playbook_adherence`, `report.source_quality`, `report.audit_readiness`, `report.coach`, and `review.bundle`.
- Lifecycle reads should return IDs and compact state, not prose-only summaries: decision ids, thesis ids, forecast ids, source ids, memory node ids, playbook version ids, due timestamps, caveats, and missing-hygiene flags.
- Source and recall provenance should be explicit. Source attachments prove external/caller-supplied evidence; recall receipts prove internal memory retrieval. This dossier treats recall receipts as a dependency, not as part of the decision lifecycle itself.
- The machine interface should distinguish record-only, paper-only, and actual-external-but-journaled decisions. It must not imply order placement or market-data fetching.
- Review/reflection handoff should be structured as “records requiring agent judgment,” not deterministic advice. Reports can surface missing reflection/adherence and outcome context; the agent writes subjective interpretation.

## 8. Evidence

- Repo evidence:
  - Research contract defines the program scope as fresh-session continuity and durable tracking of theses, forecasts, decisions, non-actions, strategies, reflections, playbook rules, and recall behavior; it prohibits implementation and network fetches (`docs/research/agentic-trade-trace/00-research-contract.md:8-16`, `22-39`).
  - Current-system baseline states Trade Trace already implements ledger tables, source/evidence attachment, forecast scoring, memory graph, strategies, playbooks, reports, and `market.scan` while identifying taxonomy/usage gaps (`docs/research/agentic-trade-trace/01-current-system-baseline.md:3-8`, `21-39`, `40-49`).
  - Taxonomy merges decision lifecycle and non-actions as the canonical “Decision and non-action lifecycle,” with downstream decision/process synthesis (`docs/research/agentic-trade-trace/02-concept-taxonomy.md:35-49`, `52-58`).
  - Vision and PRD explicitly include skips, watches, holds, thesis updates, invalidations, and reviews as reviewable decision artifacts (`docs/VISION.md:40-42`, `53-61`; `docs/PRD.md:194-238`).
  - Source inspection confirms runtime validation of decision types and report surfaces for stale watches and unscored forecasts (`src/trade_trace/tools/decision_matrix.py:16-82`; `src/trade_trace/reports/watchlist.py:1-13`; `src/trade_trace/reports/unscored.py:1-7`).
- External evidence, if used: none. No network fetches were run.
- User-stated intent:
  - The prompt states Phase 0 taxonomy merged decision lifecycle and non-actions conceptually and instructs this dossier to treat watch/skip/hold/defer/invalidate/update/review as part of the same lifecycle.
  - The prompt states the LLM trading agent differs from a human trader because non-actions and unresolved intent vanish across fresh sessions unless structured.
  - The prompt requests focus on current decision types, thesis/forecast/outcome lifecycle, non-actions, source attachment, playbook adherence, review/reflection handoff, and gaps.
- Inferences:
  - The current substrate is strong enough to support a core lifecycle concept without inventing execution, market-data fetching, or human UI.
  - The biggest product gap is a canonical lifecycle/inspection protocol that prevents non-actions and pending obligations from becoming invisible to future sessions.
  - `market.scan` is a promising high-level intake path, but its limited action set means it cannot be the whole lifecycle interface.

## 9. Risks and Failure Modes

- **Context poisoning:** Low-quality reasons, source summaries, or reflections can pollute future agent context if retrieved without caveats.
- **False closure:** A `skip` or `hold` may be treated as done even when it should generate a later review, missed-opportunity check, or source refresh.
- **Stale unresolved intent:** Watches without `review_by`, forecasts without outcomes, and decisions without reflections can accumulate and overwhelm bootstrap context.
- **Over-logging:** If every micro-hesitation becomes a decision row, reports and recall may become noisy. The lifecycle needs thresholds for materiality.
- **Retrospective rationalization:** Forecasts or theses recorded after outcomes can create false calibration unless late-recording flags and created-at ordering are respected.
- **Playbook overfitting:** A single bad outcome or subjective reflection might drive premature rule changes unless reflection-to-policy quarantine is observed.
- **Advice boundary drift:** Lifecycle reports may be mistaken for trade recommendations. Interfaces must keep returning evidence, due work, and diagnostics rather than “buy/sell/enter” advice.
- **Execution confusion:** `actual_enter`/`actual_exit` rows are journal records only. Agents must not infer that Trade Trace placed or can place orders.
- **Ambiguous defer semantics:** There is no explicit `defer` decision type today. Defer-like behavior must currently be represented as `watch` with `review_by`, `hold`, or `review`, which may be semantically lossy.

## 10. Dependencies and Conflicts

Dependencies:

- **Fresh-session bootstrap context pack:** downstream consumer; needs lifecycle state to decide what to show at session start.
- **Agent work queue / next actions:** derives pending obligations from watches, unscored forecasts, stale sources, missing reflections/adherence, and unresolved reviews.
- **Recall receipts:** should attach or relate memory retrieval evidence to lifecycle decisions and reviews.
- **Strategy lifecycle:** scopes decisions, forecasts, reviews, and reflections so lifecycle signals are not smeared across unrelated strategies.
- **Reflection-to-policy quarantine:** consumes decision/outcome/review context before allowing playbook evolution.
- **Machine-checkable playbook predicates:** depends on structured decision/snapshot/forecast fields and adherence rows.
- **Forecast-vs-market diagnostics and replay/regression:** consume recorded lifecycle state and outcomes.

Conflicts / boundaries:

- Must not become execution, routing, alerting, or market-data fetching.
- Must not become a human dashboard or generic task manager.
- Must preserve the ledger/memory distinction: decisions/outcomes are strict ledger facts; reflections and playbook rules are agent-authored beliefs/policy candidates.
- Must avoid making subjective mistake classification a system judgment. Trade Trace can package evidence and reports; the agent reflects.

## 11. Open Questions / Falsifiers

- Is the current 13-value decision enum sufficient, or does `defer` deserve first-class representation rather than being encoded as `watch.review_by`, `hold`, or `review`?
- Should `skip` ever support a `review_by` or “missed-opportunity review” obligation, or is skip intentionally terminal unless later selected by reports/replay?
- How should lifecycle closure be represented without introducing mutable state that conflicts with append-only decisions? Derived status from later decisions/outcomes may be enough, but this needs synthesis.
- What is the minimum source/forecast/reason requirement for each decision type so non-actions are useful without creating write friction?
- Should every playbook-scoped decision require explicit adherence rows, or is hygiene reporting enough?
- What thresholds keep non-action logging from becoming noisy while preserving important unresolved intent?
- How should invalidated/updated theses be joined to superseding thesis rows and forecasts in read surfaces?
- Falsifier: if dogfood shows agents reliably recover non-actions and pending obligations from existing reports without a unifying lifecycle concept, this may be a supporting concept rather than a core primitive.
- Falsifier: if decision lifecycle recommendations require scheduler behavior, broker execution, market-data fetches, or human approval workflow, the concept should be narrowed or rejected.

## 12. Decision Hook

This dossier should be consumed by `trade-trace-53tq` and `trade-trace-t4sr` for decision/process synthesis and first-phase concept classification. It should also feed later work on fresh-session bootstrap, work queue / next actions, recall receipts, reflection-to-policy quarantine, and replay/regression.

## Side Effects

Files written:

- `/home/hermes/code/trade-trace/docs/research/agentic-trade-trace/concepts/decision-non-action-lifecycle.md`

Memory retained: none.

External side effects: none; no network fetches were run.

Implementation changes: none; no code, schemas, tests, README/PRD/VISION, Beads, config, or other files were edited.
