"""Golden pin: a composed bootstrap packet glosses every caveat code it
emits and points at the glossary doc (trade-trace-o1wr).

Before this, `report.bootstrap` dumped cryptic codes
(`BAD_OUTCOME_NOT_CANONICALLY_INFERRED`, `HARMFUL_OVERFIT_EDGE_BASED_ONLY`,
`NO_EXPECTED_MEMORY_SIGNAL`, ...) with no inline explanation, so a bot
could not tell which caveats mattered. The packet now carries
`caveats.caveat_glossary` (code -> one-line gloss) and
`caveats.caveat_glossary_doc` (pointer to the full doc).
"""

from __future__ import annotations

from tests.integration._bootstrap_helpers import conn_for as _conn
from tests.integration._bootstrap_helpers import seed_base as _seed_base
from trade_trace.reports.bootstrap import (
    CAVEAT_GLOSSARY,
    CAVEAT_GLOSSARY_DOC,
    compose_bootstrap_packet,
)

# Caveat-bearing fields the packet uses; mirrors _collect_caveat_codes so
# the golden test independently re-walks the packet rather than trusting
# the production walker. A caveat *code* is an identifier-shaped token
# (no whitespace); prose caveat sentences are excluded.
_CODE_KEYS = {"caveat_codes", "scope_caveat_codes", "caveat"}


def _is_code(value: object) -> bool:
    return isinstance(value, str) and bool(value) and not any(ch.isspace() for ch in value)


def _walk_codes(value: object, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, sub in value.items():
            if key == "caveat_glossary":
                continue
            if key in _CODE_KEYS:
                if isinstance(sub, list):
                    found.update(c for c in sub if _is_code(c))
                elif _is_code(sub):
                    found.add(sub)
            elif key.endswith("caveats") and isinstance(sub, list):
                found.update(c for c in sub if _is_code(c))
            else:
                _walk_codes(sub, found)
    elif isinstance(value, list):
        for item in value:
            _walk_codes(item, found)


def _packet(home):
    with _conn(home) as conn:
        _seed_base(conn)
        return compose_bootstrap_packet(
            conn,
            as_of="2026-01-20T00:00:00Z",
            budgets={
                "default_max_items_per_section": 20,
                "default_max_chars_per_section": 12000,
            },
        )


def test_packet_exposes_glossary_pointer_and_inline_glossary(home):
    packet = _packet(home)
    caveats = packet["caveats"]
    assert caveats["caveat_glossary_doc"] == CAVEAT_GLOSSARY_DOC
    assert isinstance(caveats["caveat_glossary"], dict)
    assert caveats["caveat_glossary"], "inline glossary should not be empty"


def test_every_code_in_packet_has_a_nonplaceholder_gloss(home):
    packet = _packet(home)
    glossary = packet["caveats"]["caveat_glossary"]

    present: set[str] = set()
    _walk_codes(packet, present)
    assert present, "expected the seeded packet to carry caveat codes"

    missing = sorted(code for code in present if code not in glossary)
    assert not missing, f"caveat codes present in packet but not glossed inline: {missing}"

    placeholder = "No gloss registered"
    unresolved = sorted(code for code in present if placeholder in glossary.get(code, ""))
    assert not unresolved, f"caveat codes fell back to the placeholder gloss: {unresolved}"


def test_glossary_only_contains_codes_actually_present(home):
    packet = _packet(home)
    glossary = packet["caveats"]["caveat_glossary"]
    present: set[str] = set()
    _walk_codes(packet, present)
    extra = sorted(set(glossary) - present)
    assert not extra, f"glossary contains codes not present in the packet: {extra}"


def test_cryptic_memory_codes_are_glossed_when_emitted(home):
    """The bead's exemplar codes must have human glosses registered."""
    for code in (
        "BAD_OUTCOME_NOT_CANONICALLY_INFERRED",
        "HARMFUL_OVERFIT_EDGE_BASED_ONLY",
        "NO_EXPECTED_MEMORY_SIGNAL",
    ):
        assert code in CAVEAT_GLOSSARY
        assert CAVEAT_GLOSSARY[code].strip()
