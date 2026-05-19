# ForecastBench compatibility investigation

Status: deferred; investigation artifact only.
Access date: 2026-05-19.
Bead: trade-trace-pty.

## Source/schema evidence

Verified sources inspected on 2026-05-19:

- ForecastBench code repository: https://github.com/forecastingresearch/forecastbench, cloned at commit `12e4a3bbf648cc4fc56ff26193e84a5e0f82958b`.
- ForecastBench dataset repository: https://github.com/forecastingresearch/forecastbench-datasets, cloned at commit `e37c2325e7a0860fe81293701d79882b708d7adf`.
- ForecastBench docs page: https://www.forecastbench.org/docs/.
- Dataset examples inspected locally from `/tmp/forecastbench-datasets/datasets/question_sets/latest-llm.json` and `/tmp/forecastbench-datasets/datasets/resolution_sets/2026-04-26_resolution_set.json`.
- Code schema inspected locally from `/tmp/forecastbench/src/_schemas.py` and `/tmp/forecastbench/src/_fb_types.py`.

ForecastBench does not expose a single standalone JSON Schema file in the inspected repository. The current machine-readable contract found in code is the Pandera dataframe schema in `src/_schemas.py`:

- `QuestionFrame`: `id`, `question`, `background`, `url`, `resolved`, `forecast_horizons`, `freeze_datetime_value`, `freeze_datetime_value_explanation`, `market_info_resolution_criteria`, `market_info_open_datetime`, `market_info_close_datetime`, `market_info_resolution_datetime`.
- `ResolutionFrame`: `id`, `date`, `value`.
- `ExplodedQuestionSetFrame`: `id`, `source`, `direction`, `forecast_due_date`, `resolution_date`.
- `ResolveReadyFrame`: `ExplodedQuestionSetFrame` plus `resolved`, `resolved_to`, `market_value_on_due_date`.

The public dataset JSON shape is not identical to the internal dataframe names. Example `question_sets/latest-llm.json` has top-level `forecast_due_date`, `question_set`, and `questions`; each question includes fields such as `id`, `source`, `question`, `resolution_criteria`, `background`, `market_info_open_datetime`, `market_info_close_datetime`, `market_info_resolution_criteria`, `url`, `freeze_datetime`, `freeze_datetime_value`, `freeze_datetime_value_explanation`, `source_intro`, and `resolution_dates`. Example `resolution_sets/*_resolution_set.json` has top-level `forecast_due_date`, `question_set`, and `resolutions`; each resolution includes `id`, `source`, `direction`, `resolution_date`, `resolved_to`, and `resolved`.

ForecastBench is a dynamic benchmark pipeline for benchmark-authored/sampled question sets and forecast collection. The public docs state datasets and leaderboards are updated nightly, and the architecture samples balanced question sets for LLMs and humans every two weeks. No public submission/export JSON schema for arbitrary third-party journal exports was found in the inspected README/docs/code paths.

## Mapping matrix

| ForecastBench field / concept | Status | Trade Trace source field(s) | Conversion notes |
|---|---:|---|---|
| Question set top-level `forecast_due_date` | Lossy optional | `forecasts.created_at`, `forecasts.valid_from`, or export-run cutoff | Trade Trace records per-forecast creation/validity, not a single benchmark due date. A synthetic export batch date would be lossy. |
| Question set top-level `question_set` | Unsupported/synthetic | Export file name or generated batch id | Trade Trace has no native benchmark question-set identity. Could generate metadata, but it would not be ForecastBench-authored. |
| Question `id` | Supported with caveat | `instruments.id` or stable export id derived from `forecasts.id` | ForecastBench IDs are question IDs from its source bank. Trade Trace IDs are local ledger IDs. Exporting local IDs is structurally possible but not semantically equivalent. |
| Question `source` | Lossy supported | `venues.kind`, `snapshots.source`, `sources.publisher`, `sources.uri`, `instruments.asset_class` | ForecastBench source is a normalized upstream source name (`manifold`, `acled`, etc.). Trade Trace can approximate from venue/source metadata but has no required normalized ForecastBench source enum. |
| Question `question` | Supported | `instruments.title` plus optional `forecasts.yes_label` | For binary event markets, instrument title usually maps. For equities/options/futures, a forecast may need a generated natural-language question, which is lossy. |
| Question `resolution_criteria` | Supported | `instruments.resolution_criteria_text` or `forecasts.resolution_rule_text` | Trade Trace has explicit resolution rule text. Need precedence rules when both are present. |
| Question `background` | Lossy optional | `theses.body`, attached `sources.summary`/`excerpt`, `instruments.metadata_json` | ForecastBench background is question context. Trade Trace thesis is the agent's reasoning and may include private strategy/process data; exporting it as background can leak or distort provenance. |
| Question `market_info_open_datetime` | Optional/lossy | `instruments.created_at`, `snapshots.captured_at`, or venue metadata | Trade Trace does not require the market's true open time. Earliest local snapshot is not equivalent. |
| Question `market_info_close_datetime` | Optional/lossy | `instruments.expiration_or_resolution_at`, `forecasts.resolution_at` | Close time and resolution time can differ. Trade Trace often tracks resolution horizon but not market close. |
| Question `market_info_resolution_datetime` | Optional/lossy | `instruments.expiration_or_resolution_at`, `forecasts.resolution_at`, `outcomes.resolved_at` | ForecastBench source schema has both close/resolution concepts; Trade Trace may only have forecast resolution horizon or actual outcome resolution. |
| Question `market_info_resolution_criteria` | Supported | `instruments.resolution_criteria_text`, `forecasts.resolution_rule_text` | Same as `resolution_criteria`; field duplication/naming differs between internal and dataset shape. |
| Question `url` | Optional supported | `sources.uri`, `snapshots.source_url`, `instruments.external_id` with venue metadata | Trade Trace stores URLs as metadata only and never fetches them automatically. Missing URL is common for manual/paper forecasts. |
| Question `resolved` | Supported | latest non-superseded `outcomes.status` and `forecasts.scoring_state` | Map final resolved outcomes to true; provisional/ambiguous/disputed/void/cancelled need policy. |
| Question `forecast_horizons` / dataset `resolution_dates` | Optional/lossy | `forecasts.resolution_at` | ForecastBench supports one or more horizons/resolution dates; Trade Trace forecast row has one `resolution_at`. Multiple horizons require multiple forecasts or synthetic array with one item. |
| Question `freeze_datetime` | Optional/lossy | `forecasts.created_at`, `snapshots.captured_at` | ForecastBench freezes market value at a benchmark-defined time. Trade Trace records agent-supplied snapshots; no guarantee a snapshot exists at benchmark freeze. |
| Question `freeze_datetime_value` | Optional/lossy | `snapshots.implied_probability`, `snapshots.mid`, `snapshots.price` | For prediction markets, implied probability maps well if present. For securities, price is not a probability and needs unsupported transformation unless explicitly modeled. |
| Question `freeze_datetime_value_explanation` | Optional/synthetic | Literal based on source field, `snapshots.source` | Can generate, e.g. `The local snapshot implied_probability`, but not necessarily ForecastBench's market value explanation. |
| Question `source_intro` | Unsupported/synthetic | None | ForecastBench prompt text is benchmark-specific. Trade Trace has no equivalent field. |
| Resolution `id` | Supported with caveat | same export id as question | Must be identical to exported question id; local ids are not ForecastBench bank ids. |
| Resolution `source` | Lossy supported | same as question `source` | Same source-normalization caveat. |
| Resolution `direction` | Mostly unsupported | `theses.side`, `decisions.side`, `forecast_outcomes.outcome_label` | ForecastBench direction is used by exploded question sets/combo resolutions. Trade Trace side is trading posture; outcome labels are not equivalent for composite directions. Null is safe for simple binary rows. |
| Resolution `resolution_date` / internal `date` | Supported | `outcomes.resolved_at` date or `forecasts.resolution_at` | Actual `outcomes.resolved_at` is best for resolved rows; unresolved rows can only use forecast horizon. Time-of-day is lost if emitting date. |
| Resolution `resolved_to` / internal `value` | Supported for binary/scalar only | `outcomes.outcome_value`, `outcomes.outcome_label` | Binary/scalar numeric outcomes map. Categorical labels cannot map to a numeric `resolved_to` without a label dictionary and are unsupported/lossy. |
| Resolution `resolved` | Supported | `outcomes.status == resolved_final` and not superseded | Non-final statuses need explicit policy; ForecastBench `resolved` bool cannot carry ambiguity/dispute/void reason. |
| `market_value_on_due_date` | Optional/lossy | snapshot nearest forecast due date: `implied_probability`, `mid`, or `price` | Trade Trace does not guarantee a due-date market snapshot; nearest-snapshot interpolation would be lossy and may be misleading. |
| Forecast submission probability | Not found as public export schema | `forecast_outcomes.probability` for yes/no | ForecastBench public dataset schema contains question/resolution data; inspected docs did not reveal a third-party forecast-submission export schema. Trade Trace probabilities are available, but target format is unverified. |
| Forecast rationale/reasoning | Unsupported as ForecastBench field | `theses.body`, `decisions.reason`, attached sources | No verified ForecastBench export field was found for rationale. Export would be product-specific, not compatibility. |
| Trade Trace decisions/positions/P&L/fees/slippage/playbook/reviews | Unsupported by ForecastBench | `decisions`, `position_events`, `positions`, `reviews`, playbook tables | ForecastBench evaluates forecasting accuracy, not trading execution/process. Including these would be outside the verified schema. |

## Feasibility assessment and risks

A narrow, ForecastBench-inspired export of Trade Trace binary event forecasts is feasible as a local interoperability format, but verified ForecastBench compatibility is not implementation-ready.

Key blockers:

1. No standalone public JSON Schema or documented third-party export/submission schema was found. The best evidence is internal Pandera dataframe schemas and public generated dataset examples.
2. ForecastBench question IDs and question sets are benchmark-controlled. Trade Trace local instruments/forecasts can be shaped similarly, but they are not members of ForecastBench's sampled question bank.
3. ForecastBench distinguishes market/source metadata that Trade Trace does not require: market open/close/resolution datetimes, freeze datetime/value, source intro, and multi-horizon resolution dates.
4. Trade Trace includes trading-specific data (decisions, positions, P&L, fees, slippage, playbook/review process) that ForecastBench does not represent.
5. Probability conversion is safe only for binary forecasts with explicit `yes_label` and two `forecast_outcomes` summing to 1. Scalar/categorical forecasts, market prices, and directional security trades are lossy or unsupported.
6. Privacy/provenance risk: using `theses.body` or attached source excerpts as ForecastBench `background` can leak private reasoning or conflate evidence with benchmark background.

## Outcome

Explicit deferral with rationale.

Do not implement a production `ForecastBench` export in this bead. The current external contract is insufficiently verified for a compatibility claim, and a faithful export would require product decisions about generated question IDs, eligible forecast types, source normalization, privacy redaction, and unresolved/ambiguous outcome policy.

Implementation-ready follow-up bead specs, if the project wants a ForecastBench-inspired local export later:

1. Define `forecastbench-inspired` export contract: JSON fixture schema owned by Trade Trace, with explicit name that does not claim upstream compatibility.
2. Implement deterministic export for eligible rows only: binary forecasts with one explicit YES probability, linked instrument title/rule, optional snapshot implied probability, and final binary outcome if available.
3. Add redaction and eligibility tests: exclude theses/sources by default unless caller opts into rationale/background export.
4. Add fixture validation against a checked-in Trade Trace-owned JSON Schema derived from this artifact, not against upstream ForecastBench unless upstream publishes a submission schema.
5. Revisit upstream compatibility only if ForecastBench publishes a stable forecast submission/export schema or API contract.

## Docs posture

Current `docs/PRD.md` already avoids an overclaim: it says ForecastBench export is ForecastBench-inspired/TBD until the external schema is verified, and lists schema verification/compatible export as future work. That posture is correct.

A minimal docs update may link this artifact from the PRD open question/P1 item, but no broad claim removal is required. Any future user-facing docs should say `ForecastBench-inspired` unless backed by a verified upstream schema and deterministic validation fixture.
