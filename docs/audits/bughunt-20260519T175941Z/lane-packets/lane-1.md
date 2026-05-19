What I did:
Reviewed the storage/events/data-integrity lane read-only for /home/hermes/code/trade-trace, focusing on:
- src/trade_trace/storage/**
- src/trade_trace/events/**
- src/trade_trace/models/ledger.py
- src/trade_trace/projections.py
- relevant ledger write paths/tests/docs

I inspected implementation, contracts/docs, and ran safe local reproductions against temporary TRADE_TRACE_HOME SQLite journals only. I did not edit files, create/update Beads, install packages, push, or mutate repo/user state.

Files opened/probed/search-reviewed:
- src/trade_trace/storage/database.py
- src/trade_trace/storage/migrations.py
- src/trade_trace/storage/edge_audit.py
- src/trade_trace/events/log.py
- src/trade_trace/events/unit_of_work.py
- src/trade_trace/events/semantic_keys.py
- src/trade_trace/models/ledger.py
- src/trade_trace/projections.py
- src/trade_trace/tools/ledger.py
- src/trade_trace/tools/_helpers.py
- tests/integration/test_projection_rebuild.py
- tests/integration/test_transactions.py
- tests/integration/test_ledger_event_emission.py
- docs/architecture/persistence.md
- docs/architecture/scoring.md
- broad searches over src/trade_trace, tests, docs for storage/event/projection/scoring/idempotency terms

Commands run/results:
- python3 temp-journal reproduction for forecast.supersede idempotent replay corruption: confirmed duplicate replacement forecast rows, only one forecast.created event, multiple supersedes edges/events.
- python3 temp-journal reproduction for forecast.supersede after resolved_final outcome: confirmed new replacement forecast receives no forecast_scores row despite existing current resolved_final outcome.
- Initial python command failed because python is not installed; reran with python3 successfully.
- All reproductions used tempfile homes and did not touch real journal state.

Files created/modified:
- None.

Issues encountered:
- None besides python executable absence; python3 worked.

Candidate records:

ID: storage-events-integrity-001

Title:
forecast.supersede retries with the same idempotency_key create extra replacement forecasts and supersedes edges while reusing the original forecast.created event

Severity:
P1

Confidence:
Confirmed

Domain:
storage-events-integrity

Bug class:
Idempotency / event-log integrity / append-only lineage corruption

Evidence type:
Code inspection + temp SQLite reproduction

Evidence:
Implementation:
- src/trade_trace/tools/ledger.py:1563-1720, _forecast_supersede
  - Opens one UnitOfWork and immediately inserts a new forecast row at lines 1636-1655.
  - Inserts forecast_outcomes at lines 1656-1667.
  - Emits forecast.created with caller idempotency_key at lines 1685-1691.
  - Then always inserts a new supersedes edge at lines 1693-1702.
  - Emits edge.created and forecast.superseded with idempotency_key=None at lines 1703-1720.
  - There is no pre-insert check_idempotency_replay for forecast.created/forecast.superseded, unlike _forecast_add at lines 625-641.

EventWriter behavior:
- src/trade_trace/events/log.py:222-243 returns the existing event on idempotent replay instead of inserting a new event.
- Because _forecast_supersede inserts the replacement forecast before emit_event, an idempotent replay can persist a new relational forecast row and then have EventWriter silently treat forecast.created as a replay of the first attempt.

Contract:
- docs/architecture/persistence.md:181-187 says same event_type/actor/idempotency_key returns the original event result and does not write again.
- docs/architecture/persistence.md:253-274 lists forecast.supersede as a retryable write requiring idempotency behavior.
- docs/architecture/persistence.md:278-289 says a single tool call’s primary write, cascades, events, outbox, and projections are one transaction and no partial state is committed.

Observed reproduction:
Temp-home script:
1. journal.init
2. venue.add, instrument.add, thesis.add, forecast.add
3. forecast.supersede prior_forecast_id=<prior>, idempotency_key="k-sup"
4. Repeat exact same forecast.supersede call with idempotency_key="k-sup"
5. Query forecasts/events/edges.

Observed output excerpt:
- First forecast.supersede returned id fc_qZ9IphqeHB0DYXp4
- Second replay returned id fc__MIEYQ4IBEi4w0yn
- forecasts table contained prior + both replacement forecasts:
  [('fc_W9_2InnkOr1_RrbO',), ('fc_qZ9IphqeHB0DYXp4',), ('fc__MIEYQ4IBEi4w0yn',)]
- forecast events:
  [('forecast.created', 'fc_W9_2InnkOr1_RrbO', 'k-f1'),
   ('forecast.created', 'fc_qZ9IphqeHB0DYXp4', 'k-sup'),
   ('forecast.superseded', 'fc_qZ9IphqeHB0DYXp4', None),
   ('forecast.superseded', 'fc__MIEYQ4IBEi4w0yn', None)]
- edges:
  [('fc__MIEYQ4IBEi4w0yn', 'fc_W9_2InnkOr1_RrbO', 'supersedes'),
   ('fc_qZ9IphqeHB0DYXp4', 'fc_W9_2InnkOr1_RrbO', 'supersedes')]

Failure mode:
An agent retry of forecast.supersede after a timeout/drop creates an additional forecast row and supersedes edge. The second forecast row has no matching forecast.created event, because EventWriter replays the first event. The retry response returns a different forecast id, violating the idempotency contract and corrupting forecast lineage.

Observed vs expected:
Observed:
- Same idempotency key + same semantic payload creates a new forecast row.
- Same prior forecast can be superseded by multiple retry-generated replacement forecasts.
- Event log no longer faithfully represents committed relational rows: duplicate replacement forecast has no forecast.created event.

Expected:
- Same idempotency key + same semantic payload returns original replacement forecast id with meta.idempotent_replay=true.
- No new forecast, forecast_outcomes, edge, forecast.superseded event, or outbox rows are written on replay.
- Event log and relational rows remain one-to-one for logical writes.

Reproduction / trace path:
Use the temp-journal script described above, or add an integration test that calls forecast.supersede twice with the same idempotency_key and asserts:
- COUNT(*) FROM forecasts WHERE thesis_id=<thesis> remains 2, not 3.
- Exactly one supersedes edge new -> prior exists.
- Second envelope data.id equals first envelope data.id.
- meta.idempotent_replay is true on second call.

Duplicate / overlap analysis:
This is related to the broader known idempotency theme, but materially different from “missing idempotency-key enforcement on write tools.” The key is present and accepted; the bug is that forecast.supersede performs relational writes before checking replay, so replay corrupts storage even though EventWriter’s idempotency machinery fires. It is also distinct from the existing “forecast.supersede commits replacement forecast before supersedes edge/event” theme: that prior bug is about cross-transaction atomicity; this one is about same-transaction replay ordering creating unaudited duplicate replacement forecasts.

Proposed Bead body:
forecast.supersede is not idempotent on retry even when the caller supplies the same idempotency_key. The handler inserts the replacement forecast and forecast_outcomes before invoking EventWriter for forecast.created. On replay, EventWriter returns the original event, but the newly inserted forecast/outcomes remain in the transaction and the handler then writes another supersedes edge and forecast.superseded event. This violates persistence.md §5.2/§5.3 and creates forecast rows not represented by forecast.created events.

Fix by checking the existing forecast.created/forecast.superseded idempotency record before any relational insert, returning the original replacement forecast id and not writing any rows on replay. Ensure cascaded edge.created/forecast.superseded events are not duplicated. Add regression coverage for exact replay and conflicting payload.

Acceptance criteria:
- Replaying forecast.supersede with the same idempotency_key and same semantic payload returns the original replacement forecast id.
- Second replay sets meta.idempotent_replay=true.
- Forecast count, forecast_outcomes count, supersedes edge count, events count, and outbox count do not increase on replay.
- Same idempotency_key with different structural payload returns IDEMPOTENCY_CONFLICT before any relational row is inserted.
- Regression test proves no forecast row exists without a corresponding forecast.created event after replay.

Validation command:
pytest tests/integration/test_ledger_event_emission.py tests/integration/test_idempotency.py -q

Risks / uncertainty:
- The design currently emits multiple events for forecast.supersede, but only forecast.created receives the caller key. The fix should define the primary event for replay carefully so the dispatcher returns the correct meta.event_id and data.id.
- Need to preserve existing atomicity fix for forecast.supersede; do not split back into multiple transactions.


ID: storage-events-integrity-002

Title:
forecast.supersede skips the forecast.created late auto-score trigger when an existing resolved_final outcome is already present

Severity:
P2

Confidence:
Confirmed

Domain:
storage-events-integrity

Bug class:
Scoring persistence invariant / event trigger parity / data completeness

Evidence type:
Docs-contract comparison + code inspection + temp SQLite reproduction

Evidence:
Docs contract:
- docs/architecture/scoring.md:330-344 says scoring trigger fires on two events:
  1. outcome.recorded with status=resolved_final
  2. forecast.created when a resolved_final outcome already exists and the forecast’s resolution time is past; late-recorded forecasts are scored immediately and flagged.
- docs/architecture/scoring.md:346-349 says both triggers run in the same transaction as the originating event so forecast_scores writes and scoring_state transitions are atomic.
- docs/architecture/scoring.md:273-276 says recovery path for a bad failed row is forecast.supersede to a new forecast row with corrected yes_label/outcome labels.
- docs/architecture/scoring.md:260-267 defines the hard invariant around scoring only current non-superseded resolved_final outcomes.

Implementation:
- src/trade_trace/tools/ledger.py:_forecast_add lines 645-717 checks for an existing head resolved_final outcome, injects late_recorded metadata, calls _score_one_forecast, and emits forecast.scored.
- src/trade_trace/tools/ledger.py:_forecast_supersede lines 1579-1585 explicitly says auto-scoring is intentionally not replicated and can be repaired by journal.rescan_scoring.
- _forecast_supersede then writes the new forecast and forecast.created event without calling _current_resolved_final_outcome, _score_one_forecast, or _emit_forecast_scored.

Observed reproduction:
Temp-home script:
1. journal.init
2. venue.add, instrument.add, thesis.add
3. forecast.add binary with ambiguous yes_label omitted, labels up/down
4. outcome.add resolved_final outcome_label=up
5. forecast.supersede the failed/scored prior forecast with explicit yes_label=up
6. Query forecast_scores for the new replacement id.

Observed output excerpt:
- forecast.supersede returned replacement id fc_qVM1pK1qyL6ZX4Oc.
- forecast_scores table contained only the original forecast score:
  [('fc_PMu-JePQYOq3zeTY', 'out_LE3GnBMpWMiLJ6c6', 0.16000000000000003, '{"outcome_id": "out_LE3GnBMpWMiLJ6c6"}')]
- New replacement forecast score count was 0.

Failure mode:
When forecast.supersede is used as the documented recovery path after a resolved_final outcome already exists, the replacement forecast is created and supersedes the prior forecast, but no forecast_scores row is written for the replacement. The forecast.created event path for normal forecast.add would have scored immediately; forecast.supersede bypasses that trigger.

Observed vs expected:
Observed:
- Replacement forecast remains logically pending/unscored even though a current non-superseded resolved_final outcome exists.
- Reports relying on forecast_scores miss the corrected replacement forecast until an operator manually runs journal.rescan_scoring.
- The “both triggers run inside the same transaction as originating event” contract is not satisfied for forecast.supersede-created forecasts.

Expected:
- A forecast row created by forecast.supersede should behave like any other forecast.created event for scoring triggers.
- If a current resolved_final outcome exists for the instrument, the replacement forecast should receive a forecast_scores row and forecast.scored event in the same transaction.
- If late, the replacement forecast/score should carry late_recorded metadata consistently with forecast.add.

Reproduction / trace path:
Use the temp-journal script described above, or add an integration test:
- Create instrument/thesis.
- Add forecast with ambiguous yes_label or old labels.
- Record resolved_final outcome.
- Call forecast.supersede with explicit yes_label and same outcome labels.
- Assert COUNT(*) FROM forecast_scores WHERE forecast_id=<replacement_id> == 1 and forecast.scored event exists for replacement.

Duplicate / overlap analysis:
This is not the existing “forecast.supersede commits replacement before supersedes edge/event” atomicity issue. It is also separate from idempotency enforcement: a single successful forecast.supersede call violates the scoring trigger contract by omitting the forecast.created auto-score side effect. The implementation comment acknowledges the omission, but the docs describe forecast.created scoring triggers and forecast.supersede recovery in a way that makes this a concrete persistence/reporting invariant break.

Proposed Bead body:
forecast.supersede creates a new forecast row and emits forecast.created, but it bypasses the same late auto-score trigger that forecast.add runs when a resolved_final outcome already exists. This contradicts scoring.md §6, where forecast.created is a scoring trigger and both triggers are atomic with the originating event. It also breaks the documented recovery path for yes_label_ambiguous failures: superseding with a corrected yes_label after resolution leaves the replacement unscored until manual rescan, so calibration/report substrates omit the corrected forecast.

Fix by sharing the forecast.add scoring path in forecast.supersede: derive the thesis instrument, find the current non-superseded resolved_final outcome, inject late_recorded metadata when applicable, write forecast_scores, and emit forecast.scored inside the same UnitOfWork as the replacement forecast and supersedes edge.

Acceptance criteria:
- forecast.supersede after a current resolved_final outcome writes a forecast_scores row for the replacement forecast.
- A forecast.scored event is emitted for that score in the same transaction.
- late_recorded metadata behavior matches forecast.add for forecasts created after outcome/resolution.
- On scoring failure, a score row with score NULL and metadata_json.failure_reason is written, matching _score_one_forecast behavior.
- Regression test covers recovery from ambiguous yes_label via forecast.supersede.

Validation command:
pytest tests/integration/test_scoring_lifecycle.py tests/integration/test_ledger_event_emission.py tests/integration/test_report_calibration.py -q

Risks / uncertainty:
- The existing code comment says auto-scoring was intentionally not replicated and suggests journal.rescan_scoring repair. That may reflect a deliberate implementation shortcut, but it conflicts with the broader scoring.md forecast.created trigger contract and recovery-path documentation.
- Need to avoid double-scoring when combined with idempotent replay fixes from candidate 001.