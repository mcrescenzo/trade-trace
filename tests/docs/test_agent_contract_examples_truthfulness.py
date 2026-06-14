"""Regression checks for stale agent-facing docs examples.

These assertions intentionally target exact snippets that have drifted from
live CLI/help/schema contracts before. If a future compatibility alias is
made canonical, update the docs and this list together.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC_PATHS = [
    ROOT / "README.md",
    ROOT / "docs" / "AI_AGENT_MCP_GETTING_STARTED.md",
    ROOT / "docs" / "AGENT_GUIDE.md",
    ROOT / "docs" / "PRD.md",
    ROOT / "docs" / "architecture" / "reports.md",
    ROOT / "docs" / "architecture" / "security.md",
    ROOT / "docs" / "architecture" / "memory-layer.md",
    ROOT / "docs" / "architecture" / "contracts.md",
    ROOT / "docs" / "architecture" / "operability.md",
]
STALE_SNIPPETS = [
    "journal config_set embeddings.provider",
    "journal restore --from",
    # model.import's input arg is `path` (admin.py `_model_import` requires it
    # and the derived schema/CLI flag is now `--path`); `--src` was a drifted
    # spelling that always failed dispatch with "path is required".
    "tt model import --src",
    "model import --src",
    "model import <path>",
    # The `derived_from?` reflect signature is no longer stale: bead
    # trade-trace-qikt implemented the §10 edge-sugar fields, so the doc
    # now truthfully advertises them on memory.reflect.
]


def test_agent_facing_docs_do_not_publish_stale_cli_or_schema_examples():
    offenders: list[str] = []
    for path in DOC_PATHS:
        text = path.read_text(encoding="utf-8")
        for snippet in STALE_SNIPPETS:
            if snippet in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {snippet!r}")

    assert not offenders, "stale agent-facing docs examples found:\n" + "\n".join(offenders)


def test_agent_guide_memory_recall_example_matches_query_required_schema():
    text = (ROOT / "docs" / "AGENT_GUIDE.md").read_text(encoding="utf-8")

    assert '"tool":"memory.recall"' in text
    assert re.search(r'"tool":"memory\.recall","args":\{[^}]*"query"\s*:', text)
    assert "Use optional `context` only" in text
    assert "not a substitute for `query`" in text
    assert '"tool":"memory.recall","args":{"context"' not in text


def test_agent_guide_market_bind_example_includes_required_state_and_mechanism():
    # market_bind.py requires `source`, `external_id`, `state`, and `mechanism`
    # via _required_enum; a docs example that omits state/mechanism fails
    # dispatch with VALIDATION_ERROR for a cold agent copying it verbatim.
    text = (ROOT / "docs" / "AGENT_GUIDE.md").read_text(encoding="utf-8")

    bind_example = re.search(r'\{"tool":"market\.bind","args":\{[^\n]*\}\}', text)
    assert bind_example is not None, "AGENT_GUIDE market.bind example not found"
    snippet = bind_example.group(0)
    assert '"state"' in snippet, "market.bind example must include required `state`"
    assert '"mechanism"' in snippet, "market.bind example must include required `mechanism`"


def test_prd_memory_recall_contract_marks_query_required_and_context_optional():
    text = (ROOT / "docs" / "PRD.md").read_text(encoding="utf-8")

    assert "`memory.recall(query, context?" in text
    assert "`query` is required" in text
    assert "optional `context`" in text
    assert "does not replace `query`" in text
    assert "`memory.recall(query?, context?" not in text


def test_agent_facing_docs_do_not_imply_context_only_memory_recall_is_valid():
    offenders: list[str] = []
    stale_patterns = (
        "memory.recall(query?, context?",
        "memory.recall(context:",
        "memory.recall(context=",
        '"tool":"memory.recall","args":{"context"',
    )
    for path in DOC_PATHS:
        text = path.read_text(encoding="utf-8")
        for pattern in stale_patterns:
            if pattern in text:
                offenders.append(f"{path.relative_to(ROOT)} contains {pattern!r}")

    assert not offenders, "memory.recall context-only docs found:\n" + "\n".join(offenders)
