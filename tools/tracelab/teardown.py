"""Safe TraceLab teardown sidecar.

The teardown path is deliberately conservative: it verifies the local network
kill switch, records a truthful quiescence confirmation, takes one final
confirmed journal backup, assembles a sanitized evidence archive, scans it, and
only then destroys an explicitly confirmed disposable TRADE_TRACE_HOME.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import tempfile
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tools.tracelab.backup import BackupSidecarResult, run_backup_once
from tools.tracelab.scorecard import ScorecardInputs, build_scorecard
from tools.tracelab.substrate_invariants import check_substrate_invariants
from trade_trace.storage.paths import DB_FILENAME

RAW_KEY_RE = re.compile(r'("?idempotency_key"?\s*[:=]\s*)?(ttik|idem|secret|key)[-_:/A-Za-z0-9]{12,}', re.IGNORECASE)
SECRET_RE = re.compile(r"TRADE_TRACE_DISPATCH_REPLAY_SECRET|sentinel[-_ ]?secret|secret[_-]?token|[A-Fa-f0-9]{40,}")
FORBIDDEN_LITERAL_RE = re.compile(r"idempotency_key|TRADE_TRACE_DISPATCH_REPLAY_SECRET|sentinel[-_ ]?secret", re.IGNORECASE)
LONG_HEX_RE = re.compile(r"[A-Fa-f0-9]{40,}")


@dataclass(frozen=True)
class TeardownResult:
    archive_path: Path
    final_backup_dir: Path
    substrate_report_path: Path
    scorecard_path: Path
    manifest_path: Path
    destroyed_home: Path
    scan_report: dict[str, Any]
    backup: BackupSidecarResult


def _timestamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _load_json(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    with Path(path).open("r", encoding="utf-8") as fh:
        value = json.load(fh)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object in {path}")
    return value


def verify_network_disabled(*, config_path: str | Path | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    """Refuse unless Polymarket/network is explicitly disabled."""

    source = "env"
    value: Any = None
    if config_path is not None:
        cfg = _load_json(config_path) or {}
        value = ((cfg.get("network") or {}).get("polymarket") or {}).get("enabled")
        source = str(config_path)
    else:
        e = env if env is not None else os.environ
        raw = e.get("TRADE_TRACE_NETWORK_POLYMARKET_ENABLED") or e.get("POLYMARKET_NETWORK_ENABLED")
        value = raw.lower() in {"1", "true", "yes", "on"} if raw is not None else None
    if value is not False:
        raise RuntimeError("refusing teardown: network.polymarket.enabled must be explicitly false")
    return {"source": source, "network.polymarket.enabled": False}


def assert_safe_disposable_home(home: str | Path) -> Path:
    h = Path(home).expanduser().resolve()
    cwd = Path.cwd().resolve()
    user_home = Path.home().resolve()
    repo_root = Path(__file__).resolve().parents[2]
    forbidden = {Path("/").resolve(), cwd, user_home, repo_root}
    if h in forbidden or repo_root in h.parents or user_home == h:
        raise ValueError(f"unsafe teardown home: {h}")
    tmp_root = Path(tempfile.gettempdir()).resolve()
    if tmp_root not in h.parents:
        raise ValueError(f"refusing non-temporary teardown home: {h}")
    if not h.exists() or not h.is_dir():
        raise ValueError(f"home does not exist or is not a directory: {h}")
    return h


def _redact_text(text: str, raw_keys: Iterable[str]) -> str:
    out = text
    for key in raw_keys:
        if key:
            out = out.replace(key, "[REDACTED-KEY]")
    out = re.sub(r'"idempotency_key"\s*:\s*"[^"]*"', '"idempotency key redacted": "[REDACTED]"', out)
    out = re.sub(r"idempotency_key\s*=\s*\S+", "idempotency key redacted=[REDACTED]", out)
    out = out.replace("idempotency_key", "idempotency key")
    out = RAW_KEY_RE.sub("[REDACTED-KEY]", out)
    out = SECRET_RE.sub("[REDACTED-SECRET]", out)
    return out


def _copy_sanitized(src: Path, dst: Path, raw_keys: Iterable[str]) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        text = src.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ValueError(f"refusing binary capture in sanitized archive: {src}") from None
    dst.write_text(_redact_text(text, raw_keys), encoding="utf-8")


def scan_tree_for_secrets(root: Path, raw_keys: Iterable[str] = ()) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative_path = path.relative_to(root)
        if _is_db_or_binary_backup_file(relative_path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for key in raw_keys:
            if key and key in text:
                findings.append({"path": str(relative_path), "pattern": "raw configured key"})
        if FORBIDDEN_LITERAL_RE.search(text):
            findings.append({"path": str(relative_path), "pattern": "forbidden secret/idempotency literal"})
        for line in text.splitlines():
            # SHA-256 checksum evidence is intentionally retained in substrate
            # invariant and backup reports. Treat other long hex free-text as a
            # likely pasted secret/address/tx hash that should not survive in
            # sanitized evidence.
            if LONG_HEX_RE.search(line) and "sha256" not in line.lower():
                findings.append({"path": str(relative_path), "pattern": "long hex free-text"})
    return {"ok": not findings, "findings": findings}


def _copytree(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _is_db_or_binary_backup_file(path: Path) -> bool:
    return path.parts[:1] == ("final_quiesced_backup",) and path.suffix in {
        ".sqlite",
        ".db",
        ".sqlite-wal",
        ".sqlite-shm",
        ".db-wal",
        ".db-shm",
    }


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _has_0600_capture(path: Path) -> bool:
    capture_names = ("capture", "dispatch", "transcript")
    return path.is_file() and stat.S_IMODE(path.stat().st_mode) == 0o600 and any(s in path.name.lower() for s in capture_names)


def run_teardown(
    *,
    home: str | Path,
    dispatch_trace_path: str | Path,
    evidence_archive_dir: str | Path,
    final_backup_dest_root: str | Path,
    quiescence_window: str,
    confirm_destroy: bool,
    network_config_path: str | Path | None = None,
    quiesced: bool = False,
    capture_paths: Iterable[str | Path] = (),
    transcript_paths: Iterable[str | Path] = (),
    raw_idempotency_keys: Iterable[str] = (),
    substrate_json_path: str | Path | None = None,
    scorecard_path: str | Path | None = None,
    metric_rollup_json: str | Path | None = None,
    skill_metrics_json: str | Path | None = None,
    reconcile_json: str | Path | None = None,
    health_json: str | Path | None = None,
    run_config_json: str | Path | None = None,
    minimum_n: int | None = None,
    archive_name: str | None = None,
) -> TeardownResult:
    if not confirm_destroy:
        raise RuntimeError("refusing teardown without confirm_destroy=True")
    if not quiesced:
        raise RuntimeError("refusing teardown without explicit quiesced=True confirmation")
    safe_home = assert_safe_disposable_home(home)
    kill = verify_network_disabled(config_path=network_config_path)
    evidence_root = Path(evidence_archive_dir).expanduser().resolve()
    if _is_relative_to(evidence_root, safe_home):
        raise ValueError(f"refusing evidence archive inside disposable home: {evidence_root}")

    backup = run_backup_once(home=safe_home, dest_root=final_backup_dest_root, quiescence_window=quiescence_window, keep=7, backup_name=f"final-quiesced-{_timestamp()}")
    if not backup.ok:
        raise RuntimeError(f"final journal.backup failed: {backup.envelope}")

    staging: Path | None = None
    archive_path: Path | None = None
    try:
        evidence_root.mkdir(parents=True, exist_ok=True)
        staging = evidence_root / f".{archive_name or 'tracelab-teardown'}-staging-{_timestamp()}"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)

        _copytree(backup.backup_dir, staging / "final_quiesced_backup")
        _copy_sanitized(Path(dispatch_trace_path), staging / "captures" / "dispatch-trace.jsonl", raw_idempotency_keys)
        for src in [Path(p) for p in capture_paths]:
            _copy_sanitized(src, staging / "captures" / src.name, raw_idempotency_keys)
        for src in [Path(p) for p in transcript_paths]:
            _copy_sanitized(src, staging / "transcripts" / src.name, raw_idempotency_keys)

        if substrate_json_path:
            substrate = _load_json(substrate_json_path) or {}
        else:
            substrate = check_substrate_invariants(
                run_db_path=safe_home / DB_FILENAME,
                home=safe_home,
                dispatch_trace_path=dispatch_trace_path,
                backup_dest_root=Path(final_backup_dest_root) / "b14-roundtrip",
                quiescence_window=quiescence_window,
            )
        substrate_path = staging / "reports" / "substrate-invariants.json"
        substrate_path.parent.mkdir(parents=True, exist_ok=True)
        substrate_path.write_text(json.dumps(substrate, sort_keys=True, indent=2) + "\n", encoding="utf-8")

        if scorecard_path:
            scorecard_text = _redact_text(Path(scorecard_path).read_text(encoding="utf-8"), raw_idempotency_keys)
        else:
            scorecard_text = build_scorecard(ScorecardInputs(
                substrate=substrate,
                metric_rollup=_load_json(metric_rollup_json),
                skill_metrics=_load_json(skill_metrics_json),
                reconcile=_load_json(reconcile_json),
                health=_load_json(health_json),
                run_config=_load_json(run_config_json) if run_config_json and Path(run_config_json).exists() else None,
                db_path=safe_home / DB_FILENAME,
                minimum_n=minimum_n,
            ))
            scorecard_text = _redact_text(scorecard_text, raw_idempotency_keys)
        sc_path = staging / "reports" / "scorecard.md"
        sc_path.write_text(scorecard_text, encoding="utf-8")

        manifest = {
            "schema_version": "1",
            "created_at": _timestamp(),
            "kill_switch": kill,
            "quiescence": {"confirmed": True, "window": quiescence_window},
            "final_backup": {"path_in_archive": "final_quiesced_backup", "confirm": True, "source": str(backup.backup_dir)},
            "scorecard": "reports/scorecard.md",
            "substrate_invariants": "reports/substrate-invariants.json",
        }
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")

        scan = scan_tree_for_secrets(staging, raw_idempotency_keys)
        if not scan["ok"]:
            raise RuntimeError(f"sanitized evidence scan failed: {scan['findings']}")
        (staging / "scan-report.json").write_text(json.dumps(scan, sort_keys=True, indent=2) + "\n", encoding="utf-8")

        archive_base = evidence_root / (archive_name or f"tracelab-teardown-evidence-{_timestamp()}")
        archive_path = Path(shutil.make_archive(str(archive_base), "zip", staging))
        scan_zip = scan_archive(archive_path, raw_idempotency_keys)
        if not scan_zip["ok"]:
            raise RuntimeError(f"archive secret scan failed: {scan_zip['findings']}")
        shutil.rmtree(staging)
        staging = None
        owned_capture_paths = [Path(dispatch_trace_path), *[Path(p) for p in capture_paths], *[Path(p) for p in transcript_paths]]
        shutil.rmtree(safe_home)
        if backup.backup_dir.exists():
            shutil.rmtree(backup.backup_dir)
        b14_roundtrip_root = Path(final_backup_dest_root) / "b14-roundtrip"
        if b14_roundtrip_root.exists():
            shutil.rmtree(b14_roundtrip_root)
        for capture in owned_capture_paths:
            if capture.exists() and capture.is_file():
                capture.unlink()

        outside_0600 = [str(p) for p in evidence_root.parent.rglob("*") if p.exists() and _has_0600_capture(p) and archive_path not in p.parents]
        if outside_0600:
            raise RuntimeError(f"0600 capture files remain outside archive: {outside_0600}")
    except Exception:
        if archive_path is not None:
            archive_path.unlink(missing_ok=True)
        if staging is not None and staging.exists():
            shutil.rmtree(staging)
        if backup.backup_dir.exists():
            shutil.rmtree(backup.backup_dir)
        raise

    return TeardownResult(archive_path, backup.backup_dir, substrate_path, sc_path, manifest_path, safe_home, scan_zip, backup)


def scan_archive(archive_path: str | Path, raw_keys: Iterable[str] = ()) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    with zipfile.ZipFile(archive_path) as zf:
        for info in zf.infolist():
            if info.is_dir() or _is_db_or_binary_backup_file(Path(info.filename)):
                continue
            try:
                text = zf.read(info).decode("utf-8")
            except UnicodeDecodeError:
                continue
            for key in raw_keys:
                if key and key in text:
                    findings.append({"path": info.filename, "pattern": "raw configured key"})
            if FORBIDDEN_LITERAL_RE.search(text):
                findings.append({"path": info.filename, "pattern": "forbidden secret/idempotency literal"})
            for line in text.splitlines():
                if LONG_HEX_RE.search(line) and "sha256" not in line.lower():
                    findings.append({"path": info.filename, "pattern": "long hex free-text"})
    return {"ok": not findings, "findings": findings}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Safe TraceLab teardown with sanitized evidence archive")
    p.add_argument("--home", required=True)
    p.add_argument("--dispatch-trace", required=True)
    p.add_argument("--evidence-archive-dir", required=True)
    p.add_argument("--final-backup-dest-root", required=True)
    p.add_argument("--quiescence-window", required=True)
    p.add_argument("--network-config-json")
    p.add_argument("--quiesced", action="store_true")
    p.add_argument("--confirm-destroy", action="store_true")
    p.add_argument("--capture", action="append", default=[])
    p.add_argument("--transcript", action="append", default=[])
    p.add_argument("--raw-idempotency-key", action="append", default=[])
    p.add_argument("--substrate-json")
    p.add_argument("--scorecard")
    p.add_argument("--metric-rollup-json")
    p.add_argument("--skill-metrics-json")
    p.add_argument("--reconcile-json")
    p.add_argument("--health-json")
    p.add_argument("--run-config-json")
    p.add_argument("--minimum-n", type=int)
    p.add_argument("--archive-name")
    ns = p.parse_args(argv)
    result = run_teardown(
        home=ns.home,
        dispatch_trace_path=ns.dispatch_trace,
        evidence_archive_dir=ns.evidence_archive_dir,
        final_backup_dest_root=ns.final_backup_dest_root,
        quiescence_window=ns.quiescence_window,
        confirm_destroy=ns.confirm_destroy,
        network_config_path=ns.network_config_json,
        quiesced=ns.quiesced,
        capture_paths=ns.capture,
        transcript_paths=ns.transcript,
        raw_idempotency_keys=ns.raw_idempotency_key,
        substrate_json_path=ns.substrate_json,
        scorecard_path=ns.scorecard,
        metric_rollup_json=ns.metric_rollup_json,
        skill_metrics_json=ns.skill_metrics_json,
        reconcile_json=ns.reconcile_json,
        health_json=ns.health_json,
        run_config_json=ns.run_config_json,
        minimum_n=ns.minimum_n,
        archive_name=ns.archive_name,
    )
    print(json.dumps({"ok": True, "archive_path": str(result.archive_path), "destroyed_home": str(result.destroyed_home), "final_backup_dir": str(result.final_backup_dir)}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
