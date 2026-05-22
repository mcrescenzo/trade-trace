from __future__ import annotations

import json
import subprocess
import sys

from tests.integration.test_bootstrap_read_model import _counts, _seed_base
from trade_trace.core import dispatch
from trade_trace.storage.paths import db_path


def _dump(env):
    return env.model_dump(mode="json", exclude_none=True)


def test_report_bootstrap_dispatch_minimal_packet_and_meta(home):
    import sqlite3

    with sqlite3.connect(db_path(home)) as conn:
        _seed_base(conn)
        before = _counts(conn)

    env = dispatch(
        "report.bootstrap",
        {"home": str(home), "as_of": "2026-01-20T00:00:00Z", "filter": {}},
        request_id="bootstrap-minimal-request-0000001",
    )
    body = _dump(env)

    with sqlite3.connect(db_path(home)) as conn:
        after = _counts(conn)

    assert body["ok"] is True
    assert after == before
    assert body["meta"]["tool"] == "report.bootstrap"
    assert body["meta"]["bootstrap_contract_version"] == "bootstrap.v0"
    assert body["meta"]["bootstrap_kind"] == "agent.bootstrap"
    data = body["data"]
    assert data["kind"] == "agent.bootstrap"
    assert data["metadata"]["as_of"] == "2026-01-20T00:00:00.000Z"
    assert data["metadata"]["side_effects"] == []
    assert data["hard_constraints"]["local_read_synthesis_only"] is True
    assert data["caveats"]["hard_boundary_caveats"]
    assert data["filter"]["broadening"]


def test_report_bootstrap_dispatch_large_truncated_packet_absence_caveats(home):
    import sqlite3

    with sqlite3.connect(db_path(home)) as conn:
        _seed_base(conn)

    env = dispatch(
        "report.bootstrap",
        {
            "home": str(home),
            "as_of": "2026-01-20T00:00:00Z",
            "filter": {"strategy_ids": ["strat-a"]},
            "budgets": {"max_chars_total": 6000},
        },
        request_id="bootstrap-truncated-request-001",
    )
    body = _dump(env)

    assert body["ok"] is True
    assert body["meta"]["truncated"] is True
    data = body["data"]
    assert data["truncation"]["is_partial"] is True
    assert data["omitted_counts"]["packet"]["max_total_chars"] == 1
    assert "max_total_chars" in data["caveats"]["truncation_caveats"]
    assert len(json.dumps(data, sort_keys=True, separators=(",", ":"))) <= 6000


def test_report_bootstrap_dispatch_unsupported_filter_is_validation_envelope(home):
    import sqlite3

    with sqlite3.connect(db_path(home)) as conn:
        _seed_base(conn)

    env = dispatch(
        "report.bootstrap",
        {
            "home": str(home),
            "as_of": "2026-01-20T00:00:00Z",
            "filter": {"symbols": ["ABC"]},
        },
        request_id="bootstrap-validation-request-1",
    )
    body = _dump(env)

    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "unsupported bootstrap filter" in body["error"]["message"]
    assert body["error"]["details"]["tool"] == "report.bootstrap"


def test_report_bootstrap_dispatch_list_filter_is_validation_envelope(home):
    import sqlite3

    with sqlite3.connect(db_path(home)) as conn:
        _seed_base(conn)

    env = dispatch(
        "report.bootstrap",
        {
            "home": str(home),
            "as_of": "2026-01-20T00:00:00Z",
            "filter": [],
        },
        request_id="bootstrap-list-filter-validation-1",
    )
    body = _dump(env)

    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "bootstrap filter must be an object" in body["error"]["message"]
    assert body["error"]["details"]["tool"] == "report.bootstrap"


def test_report_bootstrap_dispatch_string_filter_is_validation_envelope_without_traceback(home):
    import sqlite3

    with sqlite3.connect(db_path(home)) as conn:
        _seed_base(conn)

    env = dispatch(
        "report.bootstrap",
        {
            "home": str(home),
            "as_of": "2026-01-20T00:00:00Z",
            "filter": "x",
        },
        request_id="bootstrap-string-filter-validation-1",
    )
    body = _dump(env)

    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "bootstrap filter must be an object" in body["error"]["message"]
    assert "Traceback" not in json.dumps(body)
    assert body["error"]["details"]["tool"] == "report.bootstrap"


def test_report_bootstrap_cli_list_filter_json_is_validation_envelope_without_traceback(home):
    import sqlite3

    with sqlite3.connect(db_path(home)) as conn:
        _seed_base(conn)

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "trade_trace.cli",
            "report",
            "bootstrap",
            "--home",
            str(home),
            "--as-of",
            "2026-01-20T00:00:00Z",
            "--filter-json",
            "[]",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    combined = proc.stdout + proc.stderr

    assert proc.returncode != 0
    body = json.loads(proc.stdout)
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert "bootstrap filter must be an object" in body["error"]["message"]
    assert "Traceback" not in combined


def test_report_bootstrap_cli_help_and_invocation(home):
    import sqlite3

    with sqlite3.connect(db_path(home)) as conn:
        _seed_base(conn)

    help_proc = subprocess.run(
        [sys.executable, "-m", "trade_trace.cli", "report", "bootstrap", "--help"],
        text=True,
        capture_output=True,
        check=True,
    )
    help_text = help_proc.stdout
    for expected in (
        "Tool: report.bootstrap",
        "--as-of <string>",
        "--filter <object>",
        "--sections <array>",
        "--budgets <object>",
        "no fetch",
        "no execution",
        "no scheduler",
        "no trading advice",
        "kind='agent.bootstrap'",
    ):
        assert expected in help_text

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "trade_trace.cli",
            "report",
            "bootstrap",
            "--home",
            str(home),
            "--as-of",
            "2026-01-20T00:00:00Z",
            "--filter-json",
            "{}",
        ],
        text=True,
        capture_output=True,
        check=True,
    )
    body = json.loads(proc.stdout)
    assert body["ok"] is True
    assert body["data"]["kind"] == "agent.bootstrap"
    assert body["meta"]["tool"] == "report.bootstrap"
