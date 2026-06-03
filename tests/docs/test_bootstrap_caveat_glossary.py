"""Doc parity pins for the bootstrap caveat-code glossary (trade-trace-o1wr).

`report.bootstrap` emits terse uppercase/snake caveat codes throughout
the packet. To keep a stateless bot able to resolve them, every code in
`CAVEAT_GLOSSARY` (the source of the inline `caveats.caveat_glossary`)
must be documented in `docs/architecture/bootstrap-caveat-glossary.md`,
and vice versa. These tests fail on drift in either direction.
"""

from __future__ import annotations

import re
from pathlib import Path

from trade_trace.reports.bootstrap import CAVEAT_GLOSSARY, CAVEAT_GLOSSARY_DOC

ROOT = Path(__file__).resolve().parents[2]
GLOSSARY_DOC = ROOT / CAVEAT_GLOSSARY_DOC
CONTRACTS_DOC = ROOT / "docs" / "architecture" / "agent-continuity-contracts.md"

# Markdown table rows look like `| `code` | gloss |`.
_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|\s*$", re.MULTILINE)


def _documented_codes() -> dict[str, str]:
    text = GLOSSARY_DOC.read_text(encoding="utf-8")
    return {m.group(1): m.group(2) for m in _ROW_RE.finditer(text)}


def test_glossary_doc_path_constant_points_at_a_real_file():
    assert GLOSSARY_DOC.is_file(), f"{CAVEAT_GLOSSARY_DOC} does not exist on disk"


def test_every_glossary_code_is_documented_and_vice_versa():
    documented = _documented_codes()
    code_keys = set(CAVEAT_GLOSSARY)
    doc_keys = set(documented)
    missing_in_doc = sorted(code_keys - doc_keys)
    extra_in_doc = sorted(doc_keys - code_keys)
    assert not missing_in_doc, f"codes in CAVEAT_GLOSSARY but not the doc: {missing_in_doc}"
    assert not extra_in_doc, f"codes in the doc but not CAVEAT_GLOSSARY: {extra_in_doc}"


def test_glosses_match_between_code_and_doc():
    documented = _documented_codes()
    mismatched = {
        code: (gloss, documented[code])
        for code, gloss in CAVEAT_GLOSSARY.items()
        if documented.get(code) != gloss
    }
    assert not mismatched, f"gloss text drift between code and doc: {sorted(mismatched)}"


def test_contracts_doc_references_inline_glossary_and_doc():
    text = CONTRACTS_DOC.read_text(encoding="utf-8")
    assert "caveat_glossary" in text
    assert "bootstrap-caveat-glossary.md" in text


def test_no_gloss_is_empty():
    blank = sorted(code for code, gloss in CAVEAT_GLOSSARY.items() if not gloss.strip())
    assert not blank, f"empty gloss for codes: {blank}"
