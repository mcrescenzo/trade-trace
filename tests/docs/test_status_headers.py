"""Every doc under `docs/architecture/` must carry a `Status:` header
per trade-trace-qea7 (taxonomy from trade-trace-qa2g / SIMP-014).

The header lives in a markdown blockquote within the first ten lines
of the file and is one of:

- `> Status: **shipped** ...` — capability docs matching the live
  registry/tests.
- `> Status: **design — not implemented** ...` — proposed behavior.
- `> Status: **partial — ...** ...` — surfaces that are partially
  shipped; the note must call out which section is live.
- `> Status: **decision document for trade-trace-<id>** ...` — per-bead
  findings docs.

The test fails when a new doc is added without the header.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE_DIR = ROOT / "docs" / "architecture"

STATUS_LINE_RE = re.compile(
    r"^>\s*Status:\s*\*\*("
    r"shipped"
    r"|design — not implemented"
    r"|partial — .+"
    r"|decision document for trade-trace-[a-z0-9]+"
    # `contract precursor` and `contract draft` cover docs that define
    # the durable contract a future surface must implement, before any
    # corresponding tool/table/CLI ships. Tracked in docs-taxonomy.md.
    r"|contract precursor"
    r"|contract draft"
    r")\*\*",
)


def test_every_architecture_doc_has_a_status_header():
    """Walk every `docs/architecture/*.md`. The first ten lines must
    contain a `> Status: **<category>**` line matching one of the
    documented values."""

    missing: list[tuple[Path, list[str]]] = []
    for doc in sorted(ARCHITECTURE_DIR.glob("*.md")):
        head = doc.read_text(encoding="utf-8").splitlines()[:10]
        if not any(STATUS_LINE_RE.match(line) for line in head):
            missing.append((doc.relative_to(ROOT), head))
    assert not missing, (
        "doc(s) missing the `> Status:` header (see "
        "docs/architecture/docs-taxonomy.md):\n"
        + "\n".join(f"  {p}\n    first lines: {head!r}" for p, head in missing)
    )
