from __future__ import annotations

import sqlite3

import pytest

from trade_trace.core import dispatch
from trade_trace.storage.paths import db_path


def _call(tool: str, args: dict, *, actor_id: str = "agent:auto-test"):
    return dispatch(tool, args, actor_id=actor_id)


def _init(home):
    env = _call("journal.init", {"home": str(home)}, actor_id="agent:init")
    assert env.ok, env


def _run_args(home, *, semantic_key: str = "run-1", status: str = "started") -> dict:
    return {
        "home": str(home),
        "semantic_key": semantic_key,
        "mode": "autonomous",
        "run_status": status,
        "run_id": "raw-run-alpha",
        "session_id": "raw-session-alpha",
        "actor_id_recorded": "agent:external-runner",
        "model_id": "model-a",
        "provider_id": "provider-a",
        "environment_label": "local-test",
        "policy_version": "policy-v1",
        "started_at": "2026-05-28T00:00:00.000Z",
        "ended_at": "2026-05-28T00:10:00.000Z" if status == "completed" else None,
        "as_of": "2026-05-28T00:00:00.000Z",
        "config_json": {"max_steps": 1},
        "provenance_json": {"source": "unit-test"},
        "idempotency_key": semantic_key,
    }


def _incident_args(
    home,
    *,
    semantic_key: str = "incident-1",
    idempotency_key: str | None = "incident-1",
    summary: str = "External system reported action blocked by policy.",
) -> dict:
    return {
        "home": str(home),
        "semantic_key": semantic_key,
        "incident_type": "blocked_action",
        "severity": "critical",
        "resolution_status": "unresolved",
        "run_id": "raw-run-alpha",
        "session_id": "raw-session-alpha",
        "occurred_at": "2026-05-28T00:05:00.000Z",
        "summary": summary,
        "evidence_state": "sparse",
        "link_ids": {"external_receipt_ids": ["eer_1"]},
        "evidence_refs": [{"kind": "local_artifact", "ref": "sha256://artifact"}],
        "provenance_json": {"source": "external-operator-report"},
        "idempotency_key": idempotency_key,
    }


def _incident_counts(home) -> tuple[int, int]:
    conn = sqlite3.connect(db_path(home))
    try:
        rows = conn.execute("SELECT COUNT(*) FROM autonomous_incident_records").fetchone()[0]
        events = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type = 'autonomous_incident.recorded'"
        ).fetchone()[0]
    finally:
        conn.close()
    return rows, events


def test_autonomous_run_record_idempotent_and_append_only(tmp_path):
    home = tmp_path / "home"
    _init(home)
    first = _call("autonomous_run.record", _run_args(home))
    assert first.ok, first
    assert first.data["schema_version"] == "autonomous_run.v1"
    assert first.data["run_status"] == "started"
    assert first.data["non_supervising"] is True
    assert first.data["non_executing"] is True

    replay = _call("autonomous_run.record", _run_args(home))
    assert replay.ok, replay
    assert replay.data["id"] == first.data["id"]
    assert replay.meta.idempotent_replay is True

    changed = _run_args(home)
    changed["model_id"] = "model-b"
    conflict = _call("autonomous_run.record", changed)
    assert not conflict.ok
    assert conflict.error is not None
    assert conflict.error.code == "IDEMPOTENCY_CONFLICT"

    conn = sqlite3.connect(db_path(home))
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only invariant: UPDATE"):
            conn.execute("UPDATE autonomous_run_records SET run_status = 'completed' WHERE id = ?", (first.data["id"],))
        conn.rollback()
        with pytest.raises(sqlite3.DatabaseError, match="append-only invariant: DELETE"):
            conn.execute("DELETE FROM autonomous_run_records WHERE id = ?", (first.data["id"],))
        conn.rollback()
    finally:
        conn.close()


def test_autonomous_incident_links_redacts_and_reports_blocked_fact(tmp_path):
    home = tmp_path / "home"
    _init(home)
    run = _call("autonomous_run.record", _run_args(home))
    assert run.ok, run

    incident = _call(
        "autonomous_incident.record",
        {
            "home": str(home),
            "semantic_key": "incident-blocked-1",
            "incident_type": "blocked_action",
            "severity": "critical",
            "resolution_status": "unresolved",
            "run_record_id": run.data["id"],
            "run_id": "raw-run-alpha",
            "session_id": "raw-session-alpha",
            "occurred_at": "2026-05-28T00:05:00.000Z",
            "summary": "External system reported action blocked by policy.",
            "evidence_state": "sparse",
            "link_ids": {
                "pretrade_intent_ids": ["pti_1"],
                "risk_check_receipt_ids": ["rcr_1"],
                "approval_record_ids": ["awr_1"],
                "external_receipt_ids": ["eer_1"],
                "reconciliation_record_ids": ["rec_1"],
                "policy_ids": ["pol_1"],
                "report_refs": ["report.risk"],
                "evidence_refs": ["sha256://artifact"],
                "strategy_id": "sensitive-strategy-name",
                "account_label": "sensitive-account-label",
                "actor_ids": ["sensitive-actor-1", "sensitive-actor-2"],
                "account_ids": ["sensitive-account-1"],
                "strategy_ids": ["sensitive-strategy-1"],
                "actor_labels": ["sensitive actor label"],
                "account labels": ["sensitive account label"],
                "strategy-labels": ["sensitive strategy label"],
                "actorId": "sensitive-camel-actor",
            },
            "evidence_refs": [{"kind": "local_artifact", "ref": "sha256://artifact"}],
            "provenance_json": {"source": "external-operator-report"},
            "idempotency_key": "incident-blocked-1",
        },
    )
    assert incident.ok, incident
    assert incident.data["imported_fact_only"] is True
    assert any(c["code"] == "external_control_fact_only" for c in incident.data["caveats"])
    assert any(c["code"] == "incident_evidence_sparse" for c in incident.data["caveats"])

    report = _call("autonomous_incident.report", {"home": str(home), "limit": 10})
    assert report.ok, report
    assert report.data["kind"] == "report.autonomous_incidents"
    assert report.data["count"] == 1
    redacted = report.data["recent_incidents"][0]
    assert redacted["run_id"] is None
    assert redacted["run_id_hash"]
    assert redacted["link_ids"]["strategy_id"].startswith("sha256:")
    assert redacted["link_ids"]["account_label"].startswith("sha256:")
    assert all(v.startswith("sha256:") for v in redacted["link_ids"]["actor_ids"])
    assert all(v.startswith("sha256:") for v in redacted["link_ids"]["account_ids"])
    assert all(v.startswith("sha256:") for v in redacted["link_ids"]["strategy_ids"])
    assert all(v.startswith("sha256:") for v in redacted["link_ids"]["actor_labels"])
    assert all(v.startswith("sha256:") for v in redacted["link_ids"]["account labels"])
    assert all(v.startswith("sha256:") for v in redacted["link_ids"]["strategy-labels"])
    assert redacted["link_ids"]["actorId"].startswith("sha256:")
    assert redacted["link_ids"]["external_receipt_ids"] == ["eer_1"]
    assert redacted["link_ids"]["report_refs"] == ["report.risk"]
    assert redacted["link_ids"]["evidence_refs"] == ["sha256://artifact"]
    assert "sensitive-actor-1" not in str(report.data)
    assert "sensitive account label" not in str(report.data)
    assert "sensitive-camel-actor" not in str(report.data)
    assert report.data["blocked_actions"][0]["id"] == incident.data["id"]
    assert report.data["unresolved_recovery_items"][0]["id"] == incident.data["id"]
    assert report.data["contributing_record_ids"]["autonomous_incident_records"] == [incident.data["id"]]
    assert report.data["contributing_record_ids"]["autonomous_run_records"] == [run.data["id"]]


def test_autonomous_incident_report_clamps_negative_limit_to_one(tmp_path):
    home = tmp_path / "home"
    _init(home)
    first = _call("autonomous_incident.record", _incident_args(home, semantic_key="incident-limit-1", idempotency_key="incident-limit-1"))
    assert first.ok, first
    second_args = _incident_args(home, semantic_key="incident-limit-2", idempotency_key="incident-limit-2")
    second_args["occurred_at"] = "2026-05-28T00:06:00.000Z"
    second = _call("autonomous_incident.record", second_args)
    assert second.ok, second

    report = _call("autonomous_incident.report", {"home": str(home), "limit": -5})

    assert report.ok, report
    assert report.data["count"] == 1
    assert report.data["recent_incidents"][0]["id"] == second.data["id"]


def test_autonomous_incident_record_idempotent_replay_no_extra_row_or_event(tmp_path):
    home = tmp_path / "home"
    _init(home)

    first = _call("autonomous_incident.record", _incident_args(home))
    assert first.ok, first
    assert _incident_counts(home) == (1, 1)

    replay = _call("autonomous_incident.record", _incident_args(home))
    assert replay.ok, replay
    assert replay.data["id"] == first.data["id"]
    assert replay.meta.idempotent_replay is True
    assert _incident_counts(home) == (1, 1)


def test_autonomous_incident_idempotency_conflict_no_extra_row_or_event(tmp_path):
    home = tmp_path / "home"
    _init(home)
    first = _call("autonomous_incident.record", _incident_args(home))
    assert first.ok, first
    assert _incident_counts(home) == (1, 1)

    changed = _incident_args(home, summary="Materially different blocked-action summary.")
    conflict = _call("autonomous_incident.record", changed)
    assert not conflict.ok
    assert conflict.error is not None
    assert conflict.error.code == "IDEMPOTENCY_CONFLICT"
    assert _incident_counts(home) == (1, 1)


def test_autonomous_incident_semantic_conflict_no_extra_row_or_event(tmp_path):
    home = tmp_path / "home"
    _init(home)
    first = _call("autonomous_incident.record", _incident_args(home))
    assert first.ok, first
    assert _incident_counts(home) == (1, 1)

    changed = _incident_args(
        home,
        semantic_key="incident-1",
        idempotency_key="incident-1-different-key",
        summary="Materially different blocked-action summary.",
    )
    conflict = _call("autonomous_incident.record", changed)
    assert not conflict.ok
    assert conflict.error is not None
    assert conflict.error.code == "IDEMPOTENCY_CONFLICT"
    assert conflict.error.details["code"] == "semantic_conflict"
    assert _incident_counts(home) == (1, 1)


def test_autonomous_incident_records_are_append_only(tmp_path):
    home = tmp_path / "home"
    _init(home)
    incident = _call("autonomous_incident.record", _incident_args(home))
    assert incident.ok, incident

    conn = sqlite3.connect(db_path(home))
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only invariant: UPDATE"):
            conn.execute("UPDATE autonomous_incident_records SET summary = 'changed' WHERE id = ?", (incident.data["id"],))
        conn.rollback()
        with pytest.raises(sqlite3.DatabaseError, match="append-only invariant: DELETE"):
            conn.execute("DELETE FROM autonomous_incident_records WHERE id = ?", (incident.data["id"],))
        conn.rollback()
    finally:
        conn.close()


def test_autonomous_records_reject_secret_payloads_before_persistence(tmp_path):
    home = tmp_path / "home"
    _init(home)
    bad = _run_args(home, semantic_key="secret-run")
    bad["config_json"] = {"private_key": "not persisted"}
    env = _call("autonomous_run.record", bad)
    assert not env.ok
    assert env.error is not None
    assert env.error.code == "VALIDATION_ERROR"

    conn = sqlite3.connect(db_path(home))
    try:
        rows = conn.execute("SELECT COUNT(*) FROM autonomous_run_records WHERE semantic_key = 'secret-run'").fetchone()[0]
    finally:
        conn.close()
    assert rows == 0
