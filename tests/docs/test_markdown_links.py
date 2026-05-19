"""Lightweight markdown link checker per bead trade-trace-05c / DEBT-004.

Walks README.md and every docs/**/*.md file, extracts relative links
(anything not http:/https:/mailto:), resolves them against the
linking file's parent, and asserts the target exists on disk. Anchors
(`#section`) are stripped before resolution — anchor coverage is a
deeper check we don't need today; the contract is "the file exists."

This is the lightweight link check the bead acceptance asks for, run
as part of the normal test suite so a future doc move can't silently
break navigation again.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINK_RE = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<href>[^)]+)\)")


def _candidate_files() -> list[Path]:
    files = [ROOT / "README.md"]
    files.extend(sorted(ROOT.glob("docs/**/*.md")))
    return [f for f in files if f.is_file()]


def _broken_links(file: Path) -> list[tuple[str, Path]]:
    text = file.read_text(encoding="utf-8")
    broken: list[tuple[str, Path]] = []
    for match in LINK_RE.finditer(text):
        href = match.group("href").strip()
        if not href:
            continue
        if href.startswith(("http://", "https://", "mailto:", "#")):
            continue
        path_part = href.split("#", 1)[0]
        if not path_part:
            continue
        target = (file.parent / path_part).resolve()
        if not target.exists():
            broken.append((href, target))
    return broken


def test_no_broken_relative_links_under_repo_root():
    """Every relative markdown link from README + docs/ must resolve to
    an existing file. Anchors are stripped before resolution."""

    all_broken: list[tuple[Path, str, Path]] = []
    for file in _candidate_files():
        for href, target in _broken_links(file):
            all_broken.append((file.relative_to(ROOT), href, target))

    assert not all_broken, (
        "broken markdown link(s) found:\n"
        + "\n".join(
            f"  {f}: {href!r} -> {target}"
            for f, href, target in all_broken
        )
    )
