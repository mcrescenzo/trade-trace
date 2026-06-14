"""The highest-level docs (VISION.md, README.md) must never emit hype or
trade-advice language.

Bead trade-trace-w6wj (INV-7): the no-hype invariant
('No hype — we never claim edge or profitability we have not measured, and
nothing this project emits is financial advice') is enforced for registered
tool descriptions (tests/security/test_mvp_boundary_audit.py) and individual
report outputs (tests/integration/test_report_coach.py), but no CI gate read
the root-level VISION.md / README.md. A future edit that added 'edge
detection', 'guaranteed profit', or a bare 'buy recommendation' to either
document would have passed every test. This gate closes that hole.

Two complementary checks run over each document:

1. Affirmative hype/advice phrases are forbidden outright. These never have a
   legitimate place in the prose, negated or not (a doc would never write
   'no guaranteed profit' as a feature), so a plain regex is sufficient and
   matches the FORBIDDEN_PHRASES the bead names: buy/sell/trade
   recommendation, guaranteed profit, profit guarantee, risk-free profit.

2. The bare phrase 'financial advice' is allowed ONLY in a negated /
   disclaimer context. The whole point of these docs is to DISCLAIM financial
   advice ('Not financial advice:', 'never ... gives financial advice',
   'nothing this project emits is financial advice'), so we cannot forbid the
   words outright — that would fail on the current clean docs. Instead we
   assert every occurrence is immediately preceded by a negation. An
   affirmative 'this is financial advice' would have no preceding negation and
   trip the gate.

The literal coach FORBIDDEN_PHRASES tuple (single words like 'buy', 'sell',
'long', 'short') is asserted absent too, satisfying the bead's reference to
that set while keeping the single-word foot-guns out of the prose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from trade_trace.reports.coach import FORBIDDEN_PHRASES

ROOT = Path(__file__).resolve().parents[2]
DOCS = (ROOT / "VISION.md", ROOT / "README.md")

# Affirmative hype/advice phrases — forbidden in any context. These are the
# multi-word phrases the bead body / acceptance names; none of them has a
# legitimate (even negated) place in the prose.
AFFIRMATIVE_HYPE = re.compile(
    r"\b("
    r"buy recommendation|sell recommendation|trade recommendation|"
    r"recommended trade|guaranteed profit|profit guarantee|"
    r"risk[- ]free profit|guaranteed return|guaranteed edge"
    r")\b",
    re.IGNORECASE,
)

# The disclaimer phrase 'financial advice' is permitted only when negated. We
# work at sentence granularity: any sentence that mentions 'financial advice'
# must also carry a negation token. This is robust to how far the negation sits
# from the phrase and to intervening punctuation (the README disclaimer is a
# long clause: 'never places trades, stores ..., or gives financial advice').
FINANCIAL_ADVICE = re.compile(r"\bfinancial advice\b", re.IGNORECASE)
NEGATION_TOKEN = re.compile(
    r"\b(?:not|never|no|none|nothing|without|isn't|aren't|don't|doesn't)\b",
    re.IGNORECASE,
)
# Split on sentence-ish boundaries: '.', ':', ';', newlines, and list-bullet
# starts. Markdown bullets like '- **Not financial advice:**' are their own
# clause, and the colon in that heading terminates the clause cleanly.
_SENTENCE_SPLIT = re.compile(r"[.:;\n]+|(?:^|\n)\s*[-*]\s+")


def _financial_advice_clauses_are_all_negated(text: str) -> tuple[int, int]:
    """Return (total_mentions, negated_mentions) at clause granularity."""

    total = 0
    negated = 0
    for clause in _SENTENCE_SPLIT.split(text):
        if clause is None:
            continue
        mentions = len(FINANCIAL_ADVICE.findall(clause))
        if not mentions:
            continue
        total += mentions
        if NEGATION_TOKEN.search(clause):
            negated += mentions
    return total, negated


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_doc_exists(doc: Path) -> None:
    assert doc.is_file(), f"expected root-level doc to exist: {doc}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_doc_has_no_affirmative_hype_or_advice_phrases(doc: Path) -> None:
    text = doc.read_text(encoding="utf-8")
    matches = AFFIRMATIVE_HYPE.findall(text)
    assert matches == [], (
        f"{doc.name} contains forbidden hype/advice phrase(s): "
        f"{sorted(set(m.lower() for m in matches))}"
    )


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_doc_mentions_financial_advice_only_to_disclaim_it(doc: Path) -> None:
    """'financial advice' may appear, but only in a negated/disclaimer clause.

    An affirmative claim ('this is financial advice') has no preceding
    negation and fails. The current docs disclaim it ('Not financial
    advice:', 'never ... gives financial advice', 'nothing this project
    emits is financial advice') and pass.
    """

    text = doc.read_text(encoding="utf-8")
    total, negated = _financial_advice_clauses_are_all_negated(text)
    if total == 0:
        return  # absence is fine; nothing to disclaim
    assert negated == total, (
        f"{doc.name}: {total - negated} of {total} 'financial advice' "
        f"mention(s) are not in a negated/disclaimer clause — every "
        f"occurrence must be disclaimed (e.g. 'not financial advice')."
    )


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_doc_has_no_coach_forbidden_single_word_phrases(doc: Path) -> None:
    """The coach packet's FORBIDDEN_PHRASES tuple (the set the bead
    references) must also be absent from the prose. These are single words
    (buy, sell, profitable, long, short, recommended trade) that have no
    place in the highest-level docs even though they would be context in a
    report body."""

    text = doc.read_text(encoding="utf-8")
    pattern = re.compile(
        r"\b(" + "|".join(re.escape(p) for p in FORBIDDEN_PHRASES) + r")\b",
        re.IGNORECASE,
    )
    matches = pattern.findall(text)
    assert matches == [], (
        f"{doc.name} contains coach FORBIDDEN_PHRASES word(s): "
        f"{sorted(set(m.lower() for m in matches))}"
    )


def test_negated_guard_catches_an_affirmative_financial_advice_claim() -> None:
    """Guard the guard: an affirmative claim must NOT count as negated, or
    the disclaimer test would be a no-op."""

    affirmative = "These reports are financial advice and a buy signal"
    total, negated = _financial_advice_clauses_are_all_negated(affirmative)
    assert total == 1
    assert negated == 0


def test_negated_guard_accepts_the_documented_disclaimers() -> None:
    """The exact disclaimer forms used in the docs must register as negated."""

    for clause in (
        "reports are not financial advice",
        "- **Not financial advice:** reports are retrospective",
        "Trade Trace never places trades, stores broker or wallet "
        "credentials, phones home, or gives financial advice.",
        "nothing this project emits is financial advice",
    ):
        total, negated = _financial_advice_clauses_are_all_negated(clause)
        assert total >= 1 and negated == total, (
            f"documented disclaimer not recognized as negated: {clause!r} "
            f"(total={total}, negated={negated})"
        )
