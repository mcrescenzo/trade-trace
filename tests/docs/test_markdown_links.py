"""Lightweight markdown link checker per bead trade-trace-05c / DEBT-004,
extended for anchor resolution and canonical-source drift per bead
trade-trace-ensw / SIMP-015.

Walks README.md and every docs/**/*.md file, extracts relative links
(anything not http:/https:/mailto:), resolves them against the
linking file's parent, and asserts the target exists on disk.

In addition (SIMP-015):
- Cross-file anchors (`path/to/doc.md#section`) are resolved against the
  target file's heading slugs. Linking to a non-existent anchor fails.
- A small canonical-source drift check verifies `pyproject.toml`
  `version` matches `src/trade_trace/version.py` `__version__` — every
  release bump must touch both surfaces; the publish workflow re-checks
  the same invariant, but this test catches drift in PRs that touch
  only one.

Anchor coverage is intentionally GitHub-slug-shaped (lowercase, spaces
→ hyphens, punctuation stripped) because that's how GitHub renders the
docs viewed by humans. The slug rule below is the documented subset.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LINK_RE = re.compile(r"\[(?P<text>[^\]]*)\]\((?P<href>[^)]+)\)")
HEADING_RE = re.compile(r"^(?P<level>#{1,6})\s+(?P<text>.+?)\s*$", re.MULTILINE)
ANCHOR_SLUG_STRIP = re.compile(r"[^\w\- ]")


def _candidate_files() -> list[Path]:
    files = [ROOT / "README.md"]
    files.extend(sorted(ROOT.glob("docs/**/*.md")))
    return [f for f in files if f.is_file()]


def _slugify(heading_text: str) -> str:
    """Approximate GitHub's heading-to-anchor slug. Lowercase, strip
    punctuation except hyphens, collapse whitespace to single hyphens."""

    text = heading_text.strip().lower()
    text = ANCHOR_SLUG_STRIP.sub("", text)
    text = re.sub(r"\s+", "-", text)
    return text


def _anchors_in(file: Path) -> set[str]:
    """Return the set of GitHub-style anchor slugs derived from headings
    in `file`."""

    return {
        _slugify(m.group("text"))
        for m in HEADING_RE.finditer(file.read_text(encoding="utf-8"))
    }


def _link_problems(file: Path) -> list[tuple[str, str]]:
    """Return `[(href, problem)]` for every broken link or anchor in the
    file. Local anchor links (`#section` within the same file) are
    validated against `file`'s own headings."""

    text = file.read_text(encoding="utf-8")
    problems: list[tuple[str, str]] = []
    own_anchors: set[str] | None = None
    for match in LINK_RE.finditer(text):
        href = match.group("href").strip()
        if not href:
            continue
        if href.startswith(("http://", "https://", "mailto:")):
            continue
        path_part, _, anchor = href.partition("#")
        if not path_part:
            # In-file anchor `#section`.
            if not anchor:
                continue
            if own_anchors is None:
                own_anchors = _anchors_in(file)
            if anchor not in own_anchors:
                problems.append((href, "anchor not found in linking file"))
            continue
        target = (file.parent / path_part).resolve()
        if not target.exists():
            problems.append((href, f"target file does not exist: {target}"))
            continue
        if anchor and target.suffix == ".md":
            if anchor not in _anchors_in(target):
                problems.append(
                    (href, f"anchor #{anchor} not found in {target.name}"),
                )
    return problems


def test_no_broken_relative_links_under_repo_root():
    """Every relative markdown link from README + docs/ must resolve to
    an existing file, and any cross-file `#anchor` must match a heading
    slug in the target file."""

    all_problems: list[tuple[Path, str, str]] = []
    for file in _candidate_files():
        for href, problem in _link_problems(file):
            all_problems.append((file.relative_to(ROOT), href, problem))

    assert not all_problems, (
        "broken markdown link(s) found:\n"
        + "\n".join(
            f"  {f}: {href!r} -> {problem}"
            for f, href, problem in all_problems
        )
    )


# -- canonical-source drift (trade-trace-ensw / SIMP-015) --------------


def test_pyproject_version_matches_module_version():
    """`pyproject.toml` `[project] version` and `src/trade_trace/version.py
    __version__` must agree on every commit. The publish workflow's
    `Verify tag matches package versions` step re-checks the same
    invariant, but this test catches drift at PR time so we never push
    a tag-mismatched build to PyPI."""

    import tomllib

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    pyproject_version = pyproject["project"]["version"]

    module = (ROOT / "src" / "trade_trace" / "version.py").read_text(encoding="utf-8")
    m = re.search(r'__version__\s*=\s*[\'"]([^\'"]+)[\'"]', module)
    assert m is not None, "could not extract __version__ from version.py"
    module_version = m.group(1)

    assert pyproject_version == module_version, (
        f"pyproject.toml version {pyproject_version!r} does not match "
        f"src/trade_trace/version.py __version__ {module_version!r}; "
        "see docs/RELEASE_CHECKLIST.md"
    )
