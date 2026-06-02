from __future__ import annotations

import json
import stat
import zipfile
from pathlib import Path

import pytest

import tools.tracelab.teardown as teardown
from tools.tracelab.teardown import run_teardown, scan_archive


def _write_json(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_teardown_refuses_without_destroy_confirmation(initialized_home, tmp_path):
    trace = tmp_path / "dispatch.jsonl"
    trace.write_text("{}\n", encoding="utf-8")
    cfg = _write_json(tmp_path / "run-config.json", {"network": {"polymarket": {"enabled": False}}})

    with pytest.raises(RuntimeError, match="confirm_destroy"):
        run_teardown(
            home=initialized_home,
            dispatch_trace_path=trace,
            evidence_archive_dir=tmp_path / "evidence",
            final_backup_dest_root=tmp_path / "backups",
            quiescence_window="paused",
            confirm_destroy=False,
            network_config_path=cfg,
            quiesced=True,
        )

    assert initialized_home.exists()


def test_teardown_refuses_when_network_not_explicitly_disabled(initialized_home, tmp_path):
    trace = tmp_path / "dispatch.jsonl"
    trace.write_text("{}\n", encoding="utf-8")
    cfg = _write_json(tmp_path / "run-config.json", {"network": {"polymarket": {"enabled": True}}})

    with pytest.raises(RuntimeError, match="network.polymarket.enabled"):
        run_teardown(
            home=initialized_home,
            dispatch_trace_path=trace,
            evidence_archive_dir=tmp_path / "evidence",
            final_backup_dest_root=tmp_path / "backups",
            quiescence_window="paused",
            confirm_destroy=True,
            network_config_path=cfg,
            quiesced=True,
        )

    assert initialized_home.exists()


def test_teardown_archive_sanitizes_includes_scorecard_backup_and_destroys_home(initialized_home, tmp_path):
    raw_key = "idem-RAW-SECRET-KEY-1234567890"
    sentinel = "TRADE_TRACE_DISPATCH_REPLAY_SECRET"
    trace = tmp_path / "dispatch.jsonl"
    trace.write_text(
        json.dumps({"tool": "paper.enter", "idempotency_key": raw_key, "note": sentinel}) + "\n",
        encoding="utf-8",
    )
    transcript = tmp_path / "transcript.txt"
    transcript.write_text(f"free text sentinel-secret and {raw_key}\n", encoding="utf-8")
    transcript.chmod(0o600)
    cfg = _write_json(tmp_path / "run-config.json", {"network": {"polymarket": {"enabled": False}}})
    substrate = _write_json(
        tmp_path / "substrate.json",
        {
            "overall_status": "PASS",
            "throughput_scored": False,
            "invariants": [
                {
                    "name": "quiesced_backup_restore_byte_identical",
                    "status": "PASS",
                    "evidence": {"original_sha256": "a" * 64, "restored_sha256": "a" * 64},
                }
            ],
        },
    )

    result = run_teardown(
        home=initialized_home,
        dispatch_trace_path=trace,
        evidence_archive_dir=tmp_path / "evidence",
        final_backup_dest_root=tmp_path / "backups",
        quiescence_window="b12-final-paused",
        confirm_destroy=True,
        network_config_path=cfg,
        quiesced=True,
        transcript_paths=[transcript],
        raw_idempotency_keys=[raw_key],
        substrate_json_path=substrate,
        minimum_n=1,
        archive_name="evidence",
    )

    assert result.archive_path.exists()
    assert not initialized_home.exists()
    assert not result.final_backup_dir.exists()
    assert scan_archive(result.archive_path, [raw_key])["ok"] is True
    assert not any(p.is_file() and stat.S_IMODE(p.stat().st_mode) == 0o600 and "transcript" in p.name for p in tmp_path.rglob("*"))

    with zipfile.ZipFile(result.archive_path) as zf:
        names = set(zf.namelist())
        assert "reports/scorecard.md" in names
        assert "reports/substrate-invariants.json" in names
        assert "final_quiesced_backup/trade-trace.sqlite" in names
        assert "final_quiesced_backup/manifest.json" in names
        assert "manifest.json" in names
        scorecard = zf.read("reports/scorecard.md").decode()
        dispatch = zf.read("captures/dispatch-trace.jsonl").decode()
        archived_transcript = zf.read("transcripts/transcript.txt").decode()

    assert "# TraceLab run scorecard" in scorecard
    assert raw_key not in dispatch
    assert "idempotency_key" not in dispatch
    assert sentinel not in dispatch
    assert raw_key not in archived_transcript
    assert "sentinel-secret" not in archived_transcript


def test_teardown_scans_backup_text_and_cleans_backup_on_scan_failure(initialized_home, tmp_path, monkeypatch):
    trace = tmp_path / "dispatch.jsonl"
    trace.write_text("{}\n", encoding="utf-8")
    cfg = _write_json(tmp_path / "run-config.json", {"network": {"polymarket": {"enabled": False}}})
    substrate = _write_json(tmp_path / "substrate.json", {"overall_status": "PASS", "invariants": []})
    backups = tmp_path / "backups"
    evidence = tmp_path / "evidence"

    def fail_scan(root, raw_keys=()):
        assert (root / "final_quiesced_backup" / "tracelab-backup.json").exists()
        return {"ok": False, "findings": [{"path": "final_quiesced_backup/tracelab-backup.json", "pattern": "forbidden secret/idempotency literal"}]}

    monkeypatch.setattr(teardown, "scan_tree_for_secrets", fail_scan)

    with pytest.raises(RuntimeError, match="sanitized evidence scan failed"):
        run_teardown(
            home=initialized_home,
            dispatch_trace_path=trace,
            evidence_archive_dir=evidence,
            final_backup_dest_root=backups,
            quiescence_window="paused",
            confirm_destroy=True,
            network_config_path=cfg,
            quiesced=True,
            substrate_json_path=substrate,
            archive_name="evidence",
        )

    assert initialized_home.exists()
    assert not any(backups.glob("final-quiesced-*"))
    assert not any(evidence.glob(".*-staging-*"))
    assert not (evidence / "evidence.zip").exists()


def test_backup_text_files_are_scanned_but_db_files_are_skipped(tmp_path):
    raw_key = "idem-RAW-SECRET-KEY-1234567890"
    tree = tmp_path / "tree"
    backup = tree / "final_quiesced_backup"
    captures = tree / "captures"
    reports = tree / "reports"
    backup.mkdir(parents=True)
    captures.mkdir(parents=True)
    reports.mkdir(parents=True)
    (backup / "trade-trace.sqlite").write_bytes(b"idempotency_key in binary db is not text evidence")
    (backup / "tracelab-backup.json").write_text(f'{{"idempotency_key": "{raw_key}"}}\n', encoding="utf-8")
    (captures / "leak.db").write_text(f'{{"idempotency_key": "{raw_key}"}}\n', encoding="utf-8")
    (reports / "leak.sqlite").write_text("TRADE_TRACE_DISPATCH_REPLAY_SECRET\n", encoding="utf-8")

    tree_scan = teardown.scan_tree_for_secrets(tree, [raw_key])
    assert tree_scan["ok"] is False
    assert any(f["path"] == "final_quiesced_backup/tracelab-backup.json" for f in tree_scan["findings"])
    assert any(f["path"] == "captures/leak.db" for f in tree_scan["findings"])
    assert any(f["path"] == "reports/leak.sqlite" for f in tree_scan["findings"])
    assert not any(f["path"] == "final_quiesced_backup/trade-trace.sqlite" for f in tree_scan["findings"])

    archive = tmp_path / "evidence.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(backup / "trade-trace.sqlite", "final_quiesced_backup/trade-trace.sqlite")
        zf.write(backup / "tracelab-backup.json", "final_quiesced_backup/tracelab-backup.json")
        zf.write(captures / "leak.db", "captures/leak.db")
        zf.write(reports / "leak.sqlite", "reports/leak.sqlite")

    archive_scan = scan_archive(archive, [raw_key])
    assert archive_scan["ok"] is False
    assert any(f["path"] == "final_quiesced_backup/tracelab-backup.json" for f in archive_scan["findings"])
    assert any(f["path"] == "captures/leak.db" for f in archive_scan["findings"])
    assert any(f["path"] == "reports/leak.sqlite" for f in archive_scan["findings"])
    assert not any(f["path"] == "final_quiesced_backup/trade-trace.sqlite" for f in archive_scan["findings"])


def test_teardown_refuses_evidence_archive_inside_disposable_home(initialized_home, tmp_path):
    trace = tmp_path / "dispatch.jsonl"
    trace.write_text("{}\n", encoding="utf-8")
    cfg = _write_json(tmp_path / "run-config.json", {"network": {"polymarket": {"enabled": False}}})

    with pytest.raises(ValueError, match="evidence archive inside disposable home"):
        run_teardown(
            home=initialized_home,
            dispatch_trace_path=trace,
            evidence_archive_dir=initialized_home / "evidence",
            final_backup_dest_root=tmp_path / "backups",
            quiescence_window="paused",
            confirm_destroy=True,
            network_config_path=cfg,
            quiesced=True,
        )

    assert initialized_home.exists()
    assert not (tmp_path / "backups").exists()
