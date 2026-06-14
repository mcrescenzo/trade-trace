"""Command-specific CLI help exposes schema-derived tool flags."""

from __future__ import annotations

from trade_trace.cli import main as cli_main


def test_venue_add_help_includes_schema_flags(capsys):
    rc = cli_main(["venue", "add", "--help"])

    out = capsys.readouterr()
    help_text = out.out + out.err
    assert rc == 0
    assert "usage: tt [global options] venue add [tool options]" in help_text
    assert "Tool: venue.add" in help_text
    assert "--name <string>  required" in help_text
    assert "--kind <string>  required" in help_text
    assert "--idempotency-key <string>  required" in help_text


def test_decision_add_help_includes_schema_flags_and_json_conventions(capsys):
    rc = cli_main(["decision", "add", "--help"])

    out = capsys.readouterr()
    help_text = out.out + out.err
    assert rc == 0
    assert "Tool: decision.add" in help_text
    assert "--instrument-id <string>  required" in help_text
    assert "--type <string>  required" in help_text
    assert "--idempotency-key <string>  required" in help_text
    assert "--metadata-json <object>" in help_text
    assert "--tags <array>" in help_text
    assert "JSON convention" in help_text
    assert "Repeating a flag accumulates values into a list" in help_text


def test_top_level_help_remains_global_only(capsys):
    rc = cli_main(["--help"])

    out = capsys.readouterr()
    help_text = out.out + out.err
    assert rc == 0
    assert "Trade Trace CLI" in help_text
    assert "--actor-id" in help_text
    assert "tool options from schema" not in help_text
    assert "--instrument-id" not in help_text


def test_report_playbook_adherence_help_advertises_scoping_args(capsys):
    rc = cli_main(["report", "playbook_adherence", "--help"])

    out = capsys.readouterr()
    help_text = out.out + out.err
    assert rc == 0
    assert "Tool: report.playbook_adherence" in help_text
    assert "--filter <object>  optional" in help_text
    assert "--playbook-id <string>  optional" in help_text
    assert "--strategy-id <string>  optional" in help_text


def test_playbook_propose_version_help_advertises_optional_lineage_fields(capsys):
    rc = cli_main(["playbook", "propose_version", "--help"])

    out = capsys.readouterr()
    help_text = out.out + out.err
    assert rc == 0
    assert "--playbook-id <string>  required" in help_text
    assert "--provenance-reflection-node-id <string>  required" in help_text
    assert "--parent-version-id <string>  optional" in help_text
    assert "--description <string>  optional" in help_text
    assert "--metadata-json <object>  optional" in help_text
