"""Closed event-type enum coverage per bead trade-trace-0r1.

Each user-callable write path must emit exactly the expected event_type
row in the `events` table. The bead's runnable invariant: a per-fixture
write produces exactly one event of the expected type, and no spurious
unrelated events.

Coverage applies to the 13 non-playbook event types from the closed enum
(per the 0r1 adaptation note in its bead body):

  decision.created, outcome.recorded, forecast.scored, forecast.superseded,
  memory_node.retained, edge.created, source.attached, strategy.created,
  strategy.updated, plus the M1 ledger events that share the registry
  (venue.created, instrument.created, snapshot.added, thesis.created,
  source.added, forecast.created).

playbook_rule.followed / playbook_rule.overridden / playbook.proposed_version
are validated within the playbook bead (fbq) per the 0r1 adaptation.
memory_node.invalidated requires a memory.invalidate write tool that has
not landed in MVP. signal.emitted / import.row_committed are not surfaced
through user-callable write paths in MVP.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.events import EventWriter
from trade_trace.events.semantic_keys import SEMANTIC_KEYS
from trade_trace.storage import apply_pending_migrations, open_database
from trade_trace.storage.paths import db_path


def _count_events(home: Path, event_type: str) -> int:
    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = ?", (event_type,),
        ).fetchone()
    finally:
        db.close()
    return int(row[0])


def _seed_venue_instrument(home: Path) -> tuple[str, str]:
    venue = _mcp(home, "venue.add",
                 {"name": "PM", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market", "title": "X",
    }).data["id"]
    return venue, inst


# -- per-event-type emission tests ------------------------------------


def test_venue_created_event_emitted(home):
    _mcp(home, "venue.add", {
        "name": "Kalshi", "kind": "prediction_market",
        "idempotency_key": "00000000-0000-4000-8000-event-venue1",
    })
    assert _count_events(home, "venue.created") == 1


def test_instrument_created_event_emitted(home):
    venue, _inst = _seed_venue_instrument(home)
    assert _count_events(home, "instrument.created") == 1


def test_snapshot_added_event_emitted(home):
    _venue, inst = _seed_venue_instrument(home)
    _mcp(home, "snapshot.add", {
        "instrument_id": inst,
        "captured_at": "2026-05-18T14:00:00Z",
        "idempotency_key": "00000000-0000-4000-8000-event-snap01",
    })
    assert _count_events(home, "snapshot.added") == 1


def test_thesis_created_event_emitted(home):
    _venue, inst = _seed_venue_instrument(home)
    _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "thesis",
        "idempotency_key": "00000000-0000-4000-8000-event-thes01",
    })
    assert _count_events(home, "thesis.created") == 1


def test_forecast_created_event_emitted(home):
    _venue, inst = _seed_venue_instrument(home)
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "thesis",
    }).data["id"]
    _mcp(home, "forecast.add", {
        "thesis_id": thesis, "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.5},
            {"outcome_label": "no", "probability": 0.5},
        ],
        "idempotency_key": "00000000-0000-4000-8000-event-fcst01",
    })
    assert _count_events(home, "forecast.created") == 1


def test_decision_created_event_emitted(home):
    _venue, inst = _seed_venue_instrument(home)
    _mcp(home, "decision.add", {
        "type": "skip", "instrument_id": inst, "reason": "spread too wide",
        "idempotency_key": "00000000-0000-4000-8000-event-deci01",
    })
    assert _count_events(home, "decision.created") == 1


def test_outcome_recorded_event_emitted(home):
    _venue, inst = _seed_venue_instrument(home)
    _mcp(home, "outcome.add", {
        "instrument_id": inst,
        "resolved_at": "2026-05-18T16:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
        "idempotency_key": "00000000-0000-4000-8000-event-outc01",
    })
    assert _count_events(home, "outcome.recorded") == 1


def test_forecast_scored_event_emitted_on_resolution(home):
    """outcome.add auto-scores any pending binary forecast on the same
    instrument; the auto-score path emits a forecast.scored event."""

    _venue, inst = _seed_venue_instrument(home)
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "t",
    }).data["id"]
    _mcp(home, "forecast.add", {
        "thesis_id": thesis, "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    })
    _mcp(home, "outcome.add", {
        "instrument_id": inst,
        "resolved_at": "2026-05-18T16:00:00Z",
        "outcome_label": "yes", "status": "resolved_final",
        "idempotency_key": "00000000-0000-4000-8000-event-scor01",
    })
    assert _count_events(home, "forecast.scored") == 1


def test_forecast_superseded_event_emitted(home):
    _venue, inst = _seed_venue_instrument(home)
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "t",
    }).data["id"]
    prior = _mcp(home, "forecast.add", {
        "thesis_id": thesis, "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.5},
            {"outcome_label": "no", "probability": 0.5},
        ],
    }).data["id"]
    _mcp(home, "forecast.supersede", {
        "prior_forecast_id": prior,
        "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.7},
            {"outcome_label": "no", "probability": 0.3},
        ],
        "idempotency_key": "00000000-0000-4000-8000-event-sup001",
    })
    assert _count_events(home, "forecast.superseded") == 1


def test_source_added_event_emitted(home):
    _mcp(home, "source.add", {
        "kind": "url", "stance": "supports",
        "uri": "https://example.com/x",
        "idempotency_key": "00000000-0000-4000-8000-event-srcadd",
    })
    assert _count_events(home, "source.added") == 1


def test_source_attached_event_emitted(home):
    _venue, inst = _seed_venue_instrument(home)
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "t",
    }).data["id"]
    src = _mcp(home, "source.add", {
        "kind": "url", "stance": "supports", "uri": "https://e.x/y",
        "idempotency_key": "00000000-0000-4000-8000-event-srca01",
    }).data["id"]
    _mcp(home, "source.attach_to_thesis", {
        "source_id": src, "target_id": thesis,
        "idempotency_key": "00000000-0000-4000-8000-event-srca02",
    })
    assert _count_events(home, "source.attached") == 1


def test_memory_node_retained_event_emitted(home):
    _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "obs",
        "idempotency_key": "00000000-0000-4000-8000-event-memr01",
    })
    assert _count_events(home, "memory_node.retained") == 1


def test_edge_created_event_emitted_by_memory_link(home):
    a = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "a",
        "idempotency_key": "00000000-0000-4000-8000-event-edge01",
    }).data["id"]
    b = _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "b",
        "idempotency_key": "00000000-0000-4000-8000-event-edge02",
    }).data["id"]
    _mcp(home, "memory.link", {
        "source_kind": "memory_node", "source_id": a,
        "target_kind": "memory_node", "target_id": b,
        "edge_type": "about",
        "idempotency_key": "00000000-0000-4000-8000-event-edge03",
    })
    # memory.reflect also emits edge.created; this isolated case
    # exercises only memory.link, so the count is 1.
    assert _count_events(home, "edge.created") == 1


def test_strategy_created_event_emitted(home):
    _mcp(home, "strategy.create", {
        "name": "Strat", "slug": "strat-event",
        "idempotency_key": "00000000-0000-4000-8000-event-stra01",
    })
    assert _count_events(home, "strategy.created") == 1


def test_strategy_updated_event_emitted(home):
    sid = _mcp(home, "strategy.create", {
        "name": "Strat", "slug": "strat-upd-event",
        "idempotency_key": "00000000-0000-4000-8000-event-stra02",
    }).data["id"]
    _mcp(home, "strategy.update", {
        "strategy_id": sid, "description": "new",
        "idempotency_key": "00000000-0000-4000-8000-event-stra03",
    })
    assert _count_events(home, "strategy.updated") == 1


# -- cross-cutting invariants ---------------------------------------


def test_decision_add_emits_no_unrelated_event_types(home):
    """Per acceptance: exactly-once-per-write-path. decision.add
    must NOT emit memory_node.retained, edge.created, or any other
    spurious row."""

    _venue, inst = _seed_venue_instrument(home)
    _mcp(home, "decision.add", {
        "type": "skip", "instrument_id": inst, "reason": "spread too wide",
        "idempotency_key": "00000000-0000-4000-8000-event-deci02",
    })
    # decision.add emits decision.created only (plus the M1 ledger
    # writes that seeded the fixture). Confirm no memory or edge events.
    assert _count_events(home, "memory_node.retained") == 0
    assert _count_events(home, "edge.created") == 0
    assert _count_events(home, "source.attached") == 0
    assert _count_events(home, "strategy.created") == 0
    assert _count_events(home, "decision.created") == 1


def test_memory_retain_emits_no_edge_event(home):
    """memory.retain emits memory_node.retained only; the edge.created
    event surfaces only on memory.reflect / memory.link / source.attach."""

    _mcp(home, "memory.retain", {
        "node_type": "observation", "body": "isolated retain",
        "idempotency_key": "00000000-0000-4000-8000-event-iso001",
    })
    assert _count_events(home, "memory_node.retained") == 1
    assert _count_events(home, "edge.created") == 0


def test_unknown_event_type_rejected_at_write(tmp_path):
    """EventWriter raises KeyError when handed an event_type not in the
    semantic_keys registry — the closed-enum guard documented in
    persistence.md §5.2."""

    home = tmp_path / "home"
    db = open_database(db_path(home))
    try:
        apply_pending_migrations(db.connection)
        writer = EventWriter(db.connection)
        with pytest.raises(KeyError):
            writer.write(
                event_type="bogus.value",
                subject_kind="x", subject_id="y",
                payload={}, actor_id="agent:default",
                idempotency_key="00000000-0000-4000-8000-rejected-01",
            )
    finally:
        db.close()


def test_semantic_keys_registry_covers_each_expected_event_type():
    """Pin the registry: every event type that bead 0r1 cites must
    appear in SEMANTIC_KEYS. If a future PR removes one without bumping
    the contract version, this test fires."""

    required = {
        "decision.created", "outcome.recorded", "forecast.scored",
        "forecast.superseded", "memory_node.retained",
        "memory_node.invalidated", "edge.created", "source.attached",
        "strategy.created", "strategy.updated", "signal.emitted",
        "import.row_committed", "playbook.proposed_version",
        "playbook_rule.followed", "playbook_rule.overridden",
    }
    missing = required - set(SEMANTIC_KEYS)
    assert missing == set(), f"semantic_keys registry missing: {missing}"
