"""Provenance / source-quality hygiene per bead trade-trace-l9q.

Covers ≥6 named tests:

- stance-to-edge-type mapping per stance (`supports`, `contradicts`,
  `neutral`).
- Unknown stance / source kind rejected with VALIDATION_ERROR.
- Unknown endpoint target rejected with NOT_FOUND.
- the internal source-quality panel + report.coach surface each of the five
  diagnostics: missing on actual_enter, stale, contradictory,
  duplicated, sensitive.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from tests._mcp_helpers import mcp_default as _mcp
from trade_trace.contracts.tool_registry import ToolContext
from trade_trace.reports.tool_handlers.audit_quality import _report_source_quality
from trade_trace.tools.errors import ToolError


def _source_quality(home: Path, args: dict | None = None):
    payload = {"home": str(home), **(args or {})}
    ctx = ToolContext(
        tool="internal.source_quality",
        actor_id="agent:default",
        request_id="internal-source-quality-test",
        raw_args=payload,
    )
    try:
        return SimpleNamespace(
            ok=True,
            data=_report_source_quality(payload, ctx),
            error=None,
        )
    except ToolError as exc:
        return SimpleNamespace(
            ok=False,
            data=None,
            error=SimpleNamespace(
                code=exc.code,
                details=exc.details,
                message=exc.message,
            ),
        )


def _seed_thesis_and_decision(
    home: Path, *, decision_type: str = "actual_enter",
) -> dict:
    """Walk venue → instrument → thesis → forecast → decision and return
    every id so individual tests can attach sources or assert hygiene."""

    venue = _mcp(home, "venue.add",
                 {"name": "PM", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue,
        "asset_class": "prediction_market", "title": "X",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": "t",
    }).data["id"]
    fcst = _mcp(home, "forecast.add", {
        "thesis_id": thesis, "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
    }).data["id"]
    dec = _mcp(home, "decision.add", {
        "type": decision_type, "instrument_id": inst,
        "thesis_id": thesis, "forecast_id": fcst,
        "side": "yes", "quantity": 1, "price": 0.6,
        "idempotency_key": "00000000-0000-4000-8000-000000000000",
    }).data["id"]
    return {"venue": venue, "instrument": inst, "thesis": thesis,
            "forecast": fcst, "decision": dec}


def test_instrument_add_accepts_rich_audit_payload(home):
    venue = _mcp(home, "venue.add", {
        "name": "PM Rich", "kind": "prediction_market",
        "idempotency_key": "00000000-0000-4000-8000-000000000091",
    }).data["id"]
    env = _mcp(home, "instrument.add", {
        "venue_id": venue,
        "asset_class": "prediction_market",
        "title": "Rich contract",
        "external_id": "venue:contract-123",
        "symbol": "RICH-123",
        "currency_or_collateral": "USD",
        "expiration_or_resolution_at": "2026-05-22T20:00:00Z",
        "resolution_criteria_text": "Resolves according to official rules.",
        "contract_multiplier": 1.0,
        "metadata_json": {"event_type": "test"},
        "idempotency_key": "00000000-0000-4000-8000-000000000092",
    })
    assert env.ok, env
    assert env.data["id"].startswith("ins_")


def test_decision_add_echoes_snapshot_id_when_provided_and_allows_omission(home):
    seeds = _seed_thesis_and_decision(home)
    assert _mcp(home, "decision.add", {
        "type": "watch", "instrument_id": seeds["instrument"],
        "idempotency_key": "00000000-0000-4000-8000-000000000101",
    }).data["snapshot_id"] is None

    snap = _mcp(home, "snapshot.add", {
        "instrument_id": seeds["instrument"],
        "captured_at": "2026-05-20T12:00:00Z",
    }).data["id"]
    env = _mcp(home, "decision.add", {
        "type": "watch", "instrument_id": seeds["instrument"],
        "snapshot_id": snap,
        "idempotency_key": "00000000-0000-4000-8000-000000000102",
    })
    assert env.ok, env
    assert env.data["snapshot_id"] == snap


# -- 1. stance → edge_type mapping per stance value ------------------


@pytest.mark.parametrize(
    "stance,expected_edge_type",
    [
        ("supports", "supports"),
        ("contradicts", "contradicts"),
        ("neutral", "about"),  # decided: neutral → about (positional)
    ],
)
def test_stance_to_edge_type_mapping(home, stance, expected_edge_type):
    seeds = _seed_thesis_and_decision(home)
    src = _mcp(home, "source.add", {
        "kind": "url", "stance": stance, "uri": f"https://example.com/{stance}",
        "idempotency_key": f"00000000-0000-4000-8000-{stance:>012}"[:36],
    }).data["id"]
    env = _mcp(home, "source.attach_to_thesis", {
        "source_id": src, "target_id": seeds["thesis"],
        "idempotency_key": f"00000000-0000-4000-8000-attach-{stance:>4}"[:36],
    })
    assert env.ok, env
    assert env.data["edge_type"] == expected_edge_type


# -- 2. unknown stance / kind rejected ----------------------------


def test_unknown_stance_rejected(home):
    """SQLite CHECK constraint on sources.stance surfaces as
    VALIDATION_ERROR via the dispatcher's IntegrityError handler."""

    env = _mcp(home, "source.add", {
        "kind": "url", "stance": "bullish",  # not in enum
        "uri": "https://example.com/x",
        "idempotency_key": "00000000-0000-4000-8000-100000000001",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"


def test_unknown_source_kind_rejected(home):
    env = _mcp(home, "source.add", {
        "kind": "smoke_signals",  # not in enum
        "stance": "supports",
        "uri": "https://example.com/x",
        "idempotency_key": "00000000-0000-4000-8000-100000000002",
    })
    assert env.ok is False
    assert env.error.code.value == "VALIDATION_ERROR"


# -- 3. unknown endpoint target rejected (NOT_FOUND) -------------


def test_attach_to_missing_thesis_returns_not_found(home):
    src = _mcp(home, "source.add", {
        "kind": "url", "stance": "supports", "uri": "https://e.x/y",
        "idempotency_key": "00000000-0000-4000-8000-100000000003",
    }).data["id"]
    env = _mcp(home, "source.attach_to_thesis", {
        "source_id": src, "target_id": "thes_does_not_exist",
        "idempotency_key": "00000000-0000-4000-8000-100000000004",
    })
    assert env.ok is False
    assert env.error.code.value == "NOT_FOUND"
    assert env.error.details["entity_kind"] == "thesis"


def test_attach_to_missing_decision_returns_not_found(home):
    src = _mcp(home, "source.add", {
        "kind": "url", "stance": "supports", "uri": "https://e.x/y",
        "idempotency_key": "00000000-0000-4000-8000-100000000005",
    }).data["id"]
    env = _mcp(home, "source.attach_to_decision", {
        "source_id": src, "target_id": "dec_does_not_exist",
        "idempotency_key": "00000000-0000-4000-8000-100000000006",
    })
    assert env.ok is False
    assert env.error.code.value == "NOT_FOUND"
    assert env.error.details["entity_kind"] == "decision"


# -- 4. (a) missing_sources_on_actual_enter -----------------------


def test_missing_sources_on_actual_enter_fires(home):
    """positive: an actual_enter decision whose thesis has zero source
    attachments surfaces in the diagnostic."""

    seeds = _seed_thesis_and_decision(home, decision_type="actual_enter")
    env = _source_quality(home, {})
    assert env.ok, env
    diag = env.data["diagnostics"]["missing_sources_on_actual_enter"]
    assert diag["count"] == 1
    assert seeds["decision"] in diag["sample_ids"]["decisions"]


def test_missing_sources_silent_when_source_attached(home):
    """negative: attach one source → diagnostic is silent."""

    seeds = _seed_thesis_and_decision(home, decision_type="actual_enter")
    src = _mcp(home, "source.add", {
        "kind": "url", "stance": "supports", "uri": "https://e.x/y",
        "idempotency_key": "00000000-0000-4000-8000-200000000001",
    }).data["id"]
    _mcp(home, "source.attach_to_thesis", {
        "source_id": src, "target_id": seeds["thesis"],
        "idempotency_key": "00000000-0000-4000-8000-200000000002",
    })
    env = _source_quality(home, {})
    diag = env.data["diagnostics"]["missing_sources_on_actual_enter"]
    assert diag["count"] == 0


def test_missing_sources_silent_when_source_attached_directly_to_pm_records(home):
    seeds = _seed_thesis_and_decision(home, decision_type="actual_enter")
    src = _mcp(home, "source.add", {
        "kind": "url", "stance": "supports", "uri": "https://e.x/direct-pm",
        "idempotency_key": "00000000-0000-4000-8000-200000000101",
    }).data["id"]
    _mcp(home, "source.attach_to_decision", {
        "source_id": src, "target_id": seeds["decision"],
        "idempotency_key": "00000000-0000-4000-8000-200000000102",
    })

    env = _source_quality(home, {})
    diag = env.data["diagnostics"]["missing_sources_on_actual_enter"]
    assert diag["count"] == 0


# -- 5. (b) stale_sources -----------------------------------------


def test_stale_sources_fires_when_freshness_predates_decision(home):
    """positive: a source whose freshness_at is 100 days before the
    decision.created_at surfaces with staleness_days well above the
    7-day threshold."""

    seeds = _seed_thesis_and_decision(home)
    src = _mcp(home, "source.add", {
        "kind": "url", "stance": "supports", "uri": "https://e.x/y",
        "freshness_at": "2020-01-01T00:00:00Z",  # ancient
        "idempotency_key": "00000000-0000-4000-8000-300000000001",
    }).data["id"]
    _mcp(home, "source.attach_to_thesis", {
        "source_id": src, "target_id": seeds["thesis"],
        "idempotency_key": "00000000-0000-4000-8000-300000000002",
    })
    env = _source_quality(home, {})
    diag = env.data["diagnostics"]["stale_sources"]
    assert diag["count"] >= 1
    sample = next(s for s in diag["samples"] if s["id"] == src)
    assert sample["staleness_days"] > 7


def test_stale_sources_include_direct_decision_attachment_and_deduplicate(home):
    seeds = _seed_thesis_and_decision(home)
    src = _mcp(home, "source.add", {
        "kind": "url", "stance": "supports", "uri": "https://e.x/direct-stale",
        "freshness_at": "2020-01-01T00:00:00Z",
        "idempotency_key": "00000000-0000-4000-8000-300000000101",
    }).data["id"]
    _mcp(home, "source.attach_to_decision", {
        "source_id": src, "target_id": seeds["decision"],
        "idempotency_key": "00000000-0000-4000-8000-300000000102",
    })
    _mcp(home, "source.attach_to_thesis", {
        "source_id": src, "target_id": seeds["thesis"],
        "idempotency_key": "00000000-0000-4000-8000-300000000103",
    })

    env = _source_quality(home, {})
    diag = env.data["diagnostics"]["stale_sources"]
    matches = [s for s in diag["samples"] if s["id"] == src and s["decision_id"] == seeds["decision"]]
    assert len(matches) == 1
    assert matches[0]["staleness_days"] > 7


def test_stale_sources_silent_when_freshness_recent(home):
    """negative: a source freshness_at one hour before the decision's own
    `created_at` is well within the 7-day staleness window and must not
    fire. The original version subtracted from `datetime.now(UTC)`, which
    coupled the test to wall-clock skew (trade-trace-r85a); we now anchor
    the offset to the actual decision timestamp so the relative
    comparison stays deterministic."""

    import sqlite3
    from datetime import datetime, timedelta

    from trade_trace.storage.paths import db_path
    from trade_trace.timestamps import to_utc_iso8601

    seeds = _seed_thesis_and_decision(home)
    with sqlite3.connect(db_path(home)) as conn:
        row = conn.execute(
            "SELECT created_at FROM decisions WHERE id = ?",
            (seeds["decision"],),
        ).fetchone()
    assert row is not None
    dec_dt = datetime.fromisoformat(row[0].replace("Z", "+00:00"))
    recent = to_utc_iso8601((dec_dt - timedelta(hours=1)).isoformat())
    src = _mcp(home, "source.add", {
        "kind": "url", "stance": "supports", "uri": "https://e.x/recent",
        "freshness_at": recent,
        "idempotency_key": "00000000-0000-4000-8000-300000000003",
    }).data["id"]
    _mcp(home, "source.attach_to_thesis", {
        "source_id": src, "target_id": seeds["thesis"],
        "idempotency_key": "00000000-0000-4000-8000-300000000004",
    })
    env = _source_quality(home, {})
    diag = env.data["diagnostics"]["stale_sources"]
    assert diag["count"] == 0


# -- 6. (c) contradictory_sources --------------------------------


def test_contradictory_sources_fires_when_same_kind_disagrees(home):
    """positive: two news-kind sources attach to the same thesis, one
    supports and one contradicts → diagnostic catches it."""

    seeds = _seed_thesis_and_decision(home)
    sup = _mcp(home, "source.add", {
        "kind": "news_article", "stance": "supports",
        "uri": "https://e.x/sup",
        "idempotency_key": "00000000-0000-4000-8000-400000000001",
    }).data["id"]
    con = _mcp(home, "source.add", {
        "kind": "news_article", "stance": "contradicts",
        "uri": "https://e.x/con",
        "idempotency_key": "00000000-0000-4000-8000-400000000002",
    }).data["id"]
    _mcp(home, "source.attach_to_thesis", {
        "source_id": sup, "target_id": seeds["thesis"],
        "idempotency_key": "00000000-0000-4000-8000-400000000003",
    })
    _mcp(home, "source.attach_to_thesis", {
        "source_id": con, "target_id": seeds["thesis"],
        "idempotency_key": "00000000-0000-4000-8000-400000000004",
    })
    env = _source_quality(home, {})
    diag = env.data["diagnostics"]["contradictory_sources"]
    assert diag["count"] == 1
    sample = diag["samples"][0]
    assert sample["thesis_id"] == seeds["thesis"]
    assert sample["kind"] == "news_article"
    assert sup in sample["supports"]
    assert con in sample["contradicts"]


def test_contradictory_sources_silent_with_only_supports(home):
    seeds = _seed_thesis_and_decision(home)
    src = _mcp(home, "source.add", {
        "kind": "news_article", "stance": "supports",
        "uri": "https://e.x/s",
        "idempotency_key": "00000000-0000-4000-8000-400000000010",
    }).data["id"]
    _mcp(home, "source.attach_to_thesis", {
        "source_id": src, "target_id": seeds["thesis"],
        "idempotency_key": "00000000-0000-4000-8000-400000000011",
    })
    env = _source_quality(home, {})
    assert env.data["diagnostics"]["contradictory_sources"]["count"] == 0


# -- 7. (d) duplicated_sources -----------------------------------


def test_duplicated_sources_fires_on_repeated_content_hash(home):
    """positive: two source rows with the same content_hash attached to
    the same target surface in the duplicated diagnostic."""

    seeds = _seed_thesis_and_decision(home)
    src1 = _mcp(home, "source.add", {
        "kind": "url", "stance": "supports",
        "uri": "https://e.x/a", "content_hash": "deadbeef",
        "idempotency_key": "00000000-0000-4000-8000-500000000001",
    }).data["id"]
    src2 = _mcp(home, "source.add", {
        "kind": "url", "stance": "supports",
        "uri": "https://e.x/b", "content_hash": "deadbeef",
        "idempotency_key": "00000000-0000-4000-8000-500000000002",
    }).data["id"]
    _mcp(home, "source.attach_to_thesis", {
        "source_id": src1, "target_id": seeds["thesis"],
        "idempotency_key": "00000000-0000-4000-8000-500000000003",
    })
    _mcp(home, "source.attach_to_thesis", {
        "source_id": src2, "target_id": seeds["thesis"],
        "idempotency_key": "00000000-0000-4000-8000-500000000004",
    })
    env = _source_quality(home, {})
    diag = env.data["diagnostics"]["duplicated_sources"]
    assert diag["count"] == 1
    sample = diag["samples"][0]
    assert sample["content_hash"] == "deadbeef"
    assert sample["count"] == 2
    assert set(sample["source_ids"]) == {src1, src2}


def test_duplicated_sources_silent_when_hashes_differ(home):
    seeds = _seed_thesis_and_decision(home)
    for i, h_ in enumerate(["aaa", "bbb"]):
        src = _mcp(home, "source.add", {
            "kind": "url", "stance": "supports",
            "uri": f"https://e.x/{i}", "content_hash": h_,
            "idempotency_key": f"00000000-0000-4000-8000-50000000001{i}",
        }).data["id"]
        _mcp(home, "source.attach_to_thesis", {
            "source_id": src, "target_id": seeds["thesis"],
            "idempotency_key": f"00000000-0000-4000-8000-50000000002{i}",
        })
    env = _source_quality(home, {})
    assert env.data["diagnostics"]["duplicated_sources"]["count"] == 0


# -- 8. (e) sensitive_sources -----------------------------------


def test_sensitive_sources_fires_for_redacted_attachment(home):
    seeds = _seed_thesis_and_decision(home)
    src = _mcp(home, "source.add", {
        "kind": "url", "stance": "supports",
        "uri": "https://e.x/private", "redaction_status": "sensitive",
        "idempotency_key": "00000000-0000-4000-8000-600000000001",
    }).data["id"]
    _mcp(home, "source.attach_to_thesis", {
        "source_id": src, "target_id": seeds["thesis"],
        "idempotency_key": "00000000-0000-4000-8000-600000000002",
    })
    env = _source_quality(home, {})
    diag = env.data["diagnostics"]["sensitive_sources"]
    assert diag["count"] == 1
    assert src in diag["sample_ids"]["sources"]


def test_sensitive_sources_silent_for_default_redaction(home):
    seeds = _seed_thesis_and_decision(home)
    src = _mcp(home, "source.add", {
        "kind": "url", "stance": "supports",
        "uri": "https://e.x/public",
        "idempotency_key": "00000000-0000-4000-8000-600000000003",
    }).data["id"]
    _mcp(home, "source.attach_to_thesis", {
        "source_id": src, "target_id": seeds["thesis"],
        "idempotency_key": "00000000-0000-4000-8000-600000000004",
    })
    env = _source_quality(home, {})
    assert env.data["diagnostics"]["sensitive_sources"]["count"] == 0


# -- 9. coach embeds source-quality panel and surfaces callouts -----


def test_report_coach_surfaces_source_quality_callouts(home):
    """coach embeds the source-quality panel and emits a callout per
    diagnostic with count>0."""

    _seed_thesis_and_decision(home, decision_type="actual_enter")
    env = _mcp(home, "report.coach", {})
    assert env.ok, env
    coach = env.data
    assert "source_quality" in coach
    callouts = " ".join(coach["callouts"])
    # The seeded actual_enter decision has no attached source, so the
    # missing_sources diagnostic fires and the callout is present.
    assert "missing_sources_on_actual_enter" in callouts


# -- 10. empty journal returns no_data ------------------------------


def test_empty_db_returns_no_data_warning(home):
    env = _source_quality(home, {})
    assert env.ok
    assert env.data["summary"]["sample_warning"] == "no_data"


# -- 11. iyt: true count survives sample truncation ------------------


def test_diagnostic_count_reflects_true_total_when_samples_capped(home):
    """Per bead trade-trace-iyt: _bundle must report the true total
    even when sample_ids/samples are capped at MAX_SAMPLE_IDS. Before
    the fix, count tracked the capped list length and silently
    under-reported large hygiene problems."""

    from trade_trace.reports.source_quality import MAX_SAMPLE_IDS
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    venue = _mcp(home, "venue.add",
                 {"name": "PM", "kind": "prediction_market"}).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market", "title": "X",
    }).data["id"]
    total = MAX_SAMPLE_IDS + 5
    # Seed sensitive sources + edges attaching each to the instrument so
    # the sensitive_sources diagnostic catches every one. Direct SQL is
    # the only way to reach `redaction_status='sensitive'` (the source.add
    # tool surface doesn't expose the column).
    db = open_database(db_path(home), create_parent=False)
    try:
        for i in range(total):
            db.connection.execute(
                "INSERT INTO sources(id, kind, title, redaction_status, "
                "created_at, actor_id) VALUES (?, 'note', ?, 'sensitive', "
                "?, 'agent:default')",
                (f"src_iyt_{i:03d}", f"t{i}", "2026-05-19T12:00:00Z"),
            )
            db.connection.execute(
                "INSERT INTO edges(id, source_kind, source_id, target_kind, "
                "target_id, edge_type, created_at, actor_id) VALUES "
                "(?, 'source', ?, 'instrument', ?, 'about', ?, 'agent:default')",
                (f"edg_iyt_{i:03d}", f"src_iyt_{i:03d}", inst,
                 "2026-05-19T12:00:00Z"),
            )
        db.connection.commit()
    finally:
        db.close()

    env = _source_quality(home, {})
    assert env.ok, env
    diag = env.data["diagnostics"]["sensitive_sources"]
    assert diag["count"] == total, (
        f"diagnostic count must reflect true total ({total}); "
        f"got {diag['count']}"
    )
    assert diag["truncated"] is True
    assert len(diag["sample_ids"]["sources"]) == MAX_SAMPLE_IDS


def test_attach_dual_writes_inline_sources_for_forecast_decision_and_memory_node(home):
    import json

    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    seeds = _seed_thesis_and_decision(home)
    mem = _mcp(home, "memory.retain", {
        "node_type": "observation",
        "body": "Inline source projection fixture.",
        "idempotency_key": "00000000-0000-4000-8000-inline-mem001",
    }).data["id"]
    source = _mcp(home, "source.add", {
        "kind": "url", "stance": "supports", "title": "Inline source",
        "uri": "https://example.invalid/inline-source",
        "content_hash": "sha256:inline-source",
        "captured_at": "2026-05-20T00:00:00Z",
        "idempotency_key": "00000000-0000-4000-8000-inline-src001",
    }).data["id"]
    for tool, target in (
        ("source.attach_to_forecast", seeds["forecast"]),
        ("source.attach_to_decision", seeds["decision"]),
        ("source.attach_to_memory_node", mem),
    ):
        env = _mcp(home, tool, {
            "source_id": source, "target_id": target,
            "idempotency_key": f"00000000-0000-4000-8000-{tool[-8:].replace('_', '')}1"[:36],
        })
        assert env.ok, env

    db = open_database(db_path(home), create_parent=False)
    try:
        for table, row_id in (("forecasts", seeds["forecast"]), ("decisions", seeds["decision"]), ("memory_nodes", mem)):
            raw = db.connection.execute(f"SELECT metadata_json FROM {table} WHERE id = ?", (row_id,)).fetchone()[0]
            sources = json.loads(raw)["sources"]
            assert any(s["id"] == source and s["stance"] == "supports" and s["url"] == "https://example.invalid/inline-source" for s in sources)
    finally:
        db.close()


def _replace_decision_metadata_for_inline_source_test(home, decision_id: str, raw: str) -> None:
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    db = open_database(db_path(home), create_parent=False)
    try:
        db.connection.execute("DROP TRIGGER trg_decisions_no_update")
        db.connection.execute(
            "UPDATE decisions SET metadata_json = ? WHERE id = ?",
            (raw, decision_id),
        )
        db.connection.execute(
            """
            CREATE TRIGGER trg_decisions_no_update
            BEFORE UPDATE ON decisions
            BEGIN
                SELECT RAISE(ABORT, 'append-only invariant: UPDATE on decisions is forbidden; use a supersedes edge to record a correction (persistence.md §8)');
            END
            """
        )
        db.connection.commit()
    finally:
        db.close()


def test_source_quality_counts_inline_only_decision_sources(home):
    seeds = _seed_thesis_and_decision(home)
    _replace_decision_metadata_for_inline_source_test(
        home,
        seeds["decision"],
        '{"sources":[{"id":"inline_stale","kind":"url","title":"Old inline","stance":"supports","freshness_at":"2026-01-01T00:00:00Z","hash":"inline-hash","redaction_status":"sensitive"}]}',
    )

    env = _source_quality(home, {})
    assert env.ok, env
    assert env.data["summary"]["total_sources"] >= 1
    assert env.data["summary"]["total_source_attachments"] >= 1
    stale = env.data["diagnostics"]["stale_sources"]
    assert any(sample["id"] == "inline_stale" and sample["decision_id"] == seeds["decision"] for sample in stale["samples"])
    sensitive = env.data["diagnostics"]["sensitive_sources"]
    assert any(sample["id"] == "inline_stale" and sample["target_kind"] == "decision" for sample in sensitive["samples"])


def test_source_quality_tolerates_malformed_inline_metadata_in_summary(home):
    seeds = _seed_thesis_and_decision(home)
    _replace_decision_metadata_for_inline_source_test(
        home,
        seeds["decision"],
        '{not valid json',
    )

    env = _source_quality(home, {})
    assert env.ok, env
    assert env.data["summary"]["total_sources"] >= 0


def test_expanded_stance_sources_attach_to_resolution_market_records(home):
    seeds = _seed_thesis_and_decision(home)
    snap = _mcp(home, "snapshot.add", {
        "instrument_id": seeds["instrument"],
        "captured_at": "2026-05-20T12:00:00Z",
        "idempotency_key": "00000000-0000-4000-8000-xku0snap001",
    }).data["id"]
    out = _mcp(home, "resolution.add", {
        "instrument_id": seeds["instrument"],
        "resolved_at": "2026-05-22T20:30:00Z",
        "outcome_label": "yes",
        "status": "resolved_final",
        "idempotency_key": "00000000-0000-4000-8000-xku0out0001",
    }).data["id"]
    official = _mcp(home, "source.add", {
        "kind": "url", "stance": "official_source",
        "uri": "https://example.invalid/official",
        "publisher": "Official resolver",
        "content_hash": "sha256:official",
        "idempotency_key": "00000000-0000-4000-8000-xku0src0001",
    }).data["id"]
    rule = _mcp(home, "source.add", {
        "kind": "research_doc", "stance": "resolution_rule",
        "uri": "https://example.invalid/rules",
        "content_hash": "sha256:rule",
        "idempotency_key": "00000000-0000-4000-8000-xku0src0002",
    }).data["id"]

    for idem, tool, source_id, target_id in (
        ("00000000-0000-4000-8000-xku0att0001", "source.attach_to_instrument", rule, seeds["instrument"]),
        ("00000000-0000-4000-8000-xku0att0002", "source.attach_to_snapshot", official, snap),
        ("00000000-0000-4000-8000-xku0att0003", "source.attach_to_outcome", official, out),
    ):
        env = _mcp(home, tool, {
            "source_id": source_id,
            "target_id": target_id,
            "idempotency_key": idem,
        })
        assert env.ok, env
        assert env.data["edge_type"] == "about"
        assert env.data["evidence_stance"] in {"official_source", "resolution_rule"}

    env = _source_quality(home, {})
    assert env.ok, env
    official_diag = env.data["diagnostics"]["official_sources"]
    assert official_diag["count"] >= 2
    assert official in official_diag["sample_ids"]["sources"]
    rule_diag = env.data["diagnostics"]["resolution_rule_sources"]
    assert rule_diag["count"] == 1
    assert rule_diag["samples"][0]["contributing_ids"]["source_id"] == rule


# -- 12. zuyj: handler-layer stale_threshold_days guard --------------


@pytest.mark.parametrize("bad_value", [-1, True])
def test_source_quality_rejects_out_of_range_stale_threshold(home, bad_value):
    """Per bead trade-trace-zuyj: the `_report_source_quality` guard rejects
    a non-negative-integer `stale_threshold_days` at the tool layer.

    The JSON schema's `minimum: 0` constraint is only enforced at the stdio
    boundary; the in-process dispatch path used here reaches the handler
    guard directly, so these cases exercise the previously test-dead branch.
    `-1` is out of range; `True` is a bool, which is not a meaningful day
    count even though `isinstance(True, int)` is True."""

    env = _source_quality(home, {"stale_threshold_days": bad_value})
    assert env.ok is False, env
    assert env.error.code.value == "VALIDATION_ERROR"
    assert env.error.details["field"] == "stale_threshold_days"
    assert env.error.details["value"] == bad_value


def test_redacted_sensitive_source_text_is_not_persisted_or_reported(home):
    seeds = _seed_thesis_and_decision(home)
    src = _mcp(home, "source.add", {
        "kind": "note", "stance": "sensitive",
        "title": "protected provenance",
        "summary": "do not leak this protected summary",
        "excerpt": "do not leak this protected excerpt",
        "extracted_text": "do not leak this protected body",
        "content_hash": "sha256:protected",
        "redaction_status": "sensitive",
        "idempotency_key": "00000000-0000-4000-8000-xku0sens001",
    }).data["id"]
    _mcp(home, "source.attach_to_decision", {
        "source_id": src,
        "target_id": seeds["decision"],
        "idempotency_key": "00000000-0000-4000-8000-xku0sens002",
    })

    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path

    db = open_database(db_path(home), create_parent=False)
    try:
        row = db.connection.execute(
            "SELECT excerpt, extracted_text, summary, content_hash FROM sources WHERE id = ?",
            (src,),
        ).fetchone()
    finally:
        db.close()
    assert row == (None, None, None, "sha256:protected")

    env = _source_quality(home, {})
    samples = env.data["diagnostics"]["redacted_sources"]["samples"]
    sample = next(s for s in samples if s["id"] == src)
    assert sample["content_hash"] == "sha256:protected"
    assert "summary" not in sample
    assert "excerpt" not in sample
    assert "extracted_text" not in sample


# -- x0g6: missing_sources_on_actual_enter is not N+1 ----------------


def _seed_actual_enter_decision(home: Path, n: int) -> dict:
    """Seed an independent actual_enter decision (fresh venue/instrument/
    thesis/forecast chain) so several can coexist in one journal."""

    venue = _mcp(home, "venue.add", {
        "name": f"PM-{n}", "kind": "prediction_market",
        "idempotency_key": f"00000000-0000-4000-8000-x0g6venue{n:03d}",
    }).data["id"]
    inst = _mcp(home, "instrument.add", {
        "venue_id": venue, "asset_class": "prediction_market", "title": f"X{n}",
        "idempotency_key": f"00000000-0000-4000-8000-x0g6inst0{n:03d}",
    }).data["id"]
    thesis = _mcp(home, "thesis.add", {
        "instrument_id": inst, "side": "yes", "body": f"t{n}",
        "idempotency_key": f"00000000-0000-4000-8000-x0g6thes0{n:03d}",
    }).data["id"]
    fcst = _mcp(home, "forecast.add", {
        "thesis_id": thesis, "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.6},
            {"outcome_label": "no", "probability": 0.4},
        ],
        "idempotency_key": f"00000000-0000-4000-8000-x0g6fcst0{n:03d}",
    }).data["id"]
    dec = _mcp(home, "decision.add", {
        "type": "actual_enter", "instrument_id": inst,
        "thesis_id": thesis, "forecast_id": fcst,
        "side": "yes", "quantity": 1, "price": 0.6,
        "idempotency_key": f"00000000-0000-4000-8000-x0g6dec00{n:03d}",
    }).data["id"]
    return {"instrument": inst, "thesis": thesis, "forecast": fcst, "decision": dec}


def test_missing_sources_bulk_query_cost_is_fixed_not_n_plus_1(home):
    """Per bead trade-trace-x0g6: `_missing_sources_on_actual_enter` must
    probe edge coverage with a fixed number of bulk IN-list queries (one
    per coverage kind: thesis, decision, forecast), not one probe per
    decision row. We seed several actual_enter decisions and count the
    edges-table SELECTs the helper issues; the count must stay constant as
    the decision count grows."""

    import sqlite3

    from trade_trace.reports.source_quality import _missing_sources_on_actual_enter
    from trade_trace.storage.paths import db_path

    seeds = [_seed_actual_enter_decision(home, n) for n in range(5)]

    edge_probe_queries: list[str] = []

    def _trace(statement: str) -> None:
        normalized = " ".join(statement.split())
        if "FROM edges" in normalized:
            edge_probe_queries.append(normalized)

    with sqlite3.connect(db_path(home)) as conn:
        conn.set_trace_callback(_trace)
        result = _missing_sources_on_actual_enter(conn)
        conn.set_trace_callback(None)

    # All 5 decisions lack provenance → all surface in the diagnostic.
    assert result["count"] == 5
    surfaced = set(result["sample_ids"]["decisions"])
    assert surfaced == {s["decision"] for s in seeds}

    # Fixed cost: exactly 3 bulk edge queries regardless of D=5 decisions.
    # An N+1 implementation would issue up to 3*D = 15 edge probes here.
    assert len(edge_probe_queries) == 3, edge_probe_queries


def test_missing_sources_bulk_query_respects_mixed_coverage(home):
    """The bulk-query refactor must preserve per-kind coverage semantics:
    a decision whose thesis (or decision row, or forecast) has any attached
    source is silent, while a fully-bare decision still fires."""

    covered = _seed_actual_enter_decision(home, 10)
    bare = _seed_actual_enter_decision(home, 11)

    src = _mcp(home, "source.add", {
        "kind": "url", "stance": "supports", "uri": "https://e.x/x0g6-cov",
        "idempotency_key": "00000000-0000-4000-8000-x0g6cov00001",
    }).data["id"]
    _mcp(home, "source.attach_to_thesis", {
        "source_id": src, "target_id": covered["thesis"],
        "idempotency_key": "00000000-0000-4000-8000-x0g6cov00002",
    })

    env = _source_quality(home, {})
    diag = env.data["diagnostics"]["missing_sources_on_actual_enter"]
    surfaced = set(diag["sample_ids"]["decisions"])
    assert bare["decision"] in surfaced
    assert covered["decision"] not in surfaced
