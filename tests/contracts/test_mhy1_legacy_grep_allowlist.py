from __future__ import annotations

import json
import subprocess
from fnmatch import fnmatch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_PATH = ROOT / "tests" / "allowlists" / "mhy1_legacy_grep_allowlist.json"
TERMS = (
    "forecast_outcomes",
    "thesis_id",
    "source.attach",
    "meta_json",
    "instrument_id",
    "venue_id",
)


def _term_in_line(term: str, line: str) -> bool:
    return term in line


def test_mhy1_legacy_grep_hits_are_reviewed_or_deferred() -> None:
    allowlist = json.loads(ALLOWLIST_PATH.read_text())
    entries = allowlist["allowed"]
    result = subprocess.run(
        [
            "git",
            "grep",
            "-n",
            "-E",
            r"forecast_outcomes|thesis_id|source\.attach|meta_json|instrument_id|venue_id",
            "--",
            "src",
            "tests",
            "docs",
            ":!tests/allowlists/mhy1_legacy_grep_allowlist.json",
            ":!tests/contracts/test_mhy1_legacy_grep_allowlist.py",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode in (0, 1), result.stderr

    unreviewed: list[str] = []
    for hit in result.stdout.splitlines():
        path, _line_no, text = hit.split(":", 2)
        hit_terms = [term for term in TERMS if _term_in_line(term, text)]
        for term in hit_terms:
            if not any(
                term in entry["terms"] and fnmatch(path, entry["pattern"])
                for entry in entries
            ):
                unreviewed.append(f"{term}: {path}: {text.strip()}")

    assert not unreviewed, "Unreviewed mhy1 legacy grep hits:\n" + "\n".join(unreviewed[:200])
