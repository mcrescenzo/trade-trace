"""Catalog usage census: tally registered-tool mentions across dogfood artifacts.

Retroactive evidence source: dispatch tracing was never enabled during the
2026-06 dogfood runs, so the only historical usage signal is tool-name mentions
in the run narratives and protocol docs. Forward evidence source: dispatch JSONL
(see aggregate_dispatch_jsonl) once TRADE_TRACE_DISPATCH_TRACE is enabled in the
harness.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

DEFAULT_SOURCES = (
    "docs/ax-dogfood/runs",
    "docs/ax-dogfood/registry.md",
    "docs/architecture/dogfood-protocol.md",
    "docs/architecture/agent-continuity-scorecard.md",
)


def tool_mention_counts(texts: Iterable[str], tool_names: Iterable[str]) -> Counter[str]:
    """Count exact-token mentions of each registered tool name.

    Boundary rules: a mention must not be preceded or followed by a word
    character, dot, underscore, or path separator, so
    ``report.calibration_integrity`` never also counts as
    ``report.calibration``, and file paths do not count.
    """

    names = list(tool_names)
    patterns = {
        name: re.compile(rf"(?<![\w./]){re.escape(name)}(?![\w.])") for name in names
    }
    counts: Counter[str] = Counter({name: 0 for name in names})
    for text in texts:
        for name, pattern in patterns.items():
            counts[name] += len(pattern.findall(text))
    return counts


def aggregate_dispatch_jsonl(lines: Iterable[str]) -> Counter[str]:
    """Tally the ``tool`` field of dispatch-trace JSONL lines."""

    counts: Counter[str] = Counter()
    for line in lines:
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        tool = record.get("tool") if isinstance(record, dict) else None
        if isinstance(tool, str) and tool:
            counts[tool] += 1
    return counts


def _gather_texts(repo_root: Path, sources: Iterable[str]) -> list[str]:
    texts: list[str] = []
    for source in sources:
        path = repo_root / source
        if path.is_dir():
            texts.extend(child.read_text(encoding="utf-8") for child in sorted(path.glob("*.md")))
        elif path.is_file():
            texts.append(path.read_text(encoding="utf-8"))
    return texts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--dispatch-jsonl", default=None)
    args = parser.parse_args()

    from trade_trace.core import default_registry

    registry = default_registry()
    all_names = sorted(registry.by_name)
    public = set(registry.public_names())

    repo_root = Path(__file__).resolve().parent.parent
    texts = _gather_texts(repo_root, DEFAULT_SOURCES)
    counts = tool_mention_counts(texts, all_names)

    dispatch_counts: Counter[str] = Counter()
    if args.dispatch_jsonl:
        dispatch_path = Path(args.dispatch_jsonl)
        if dispatch_path.is_file():
            with dispatch_path.open(encoding="utf-8") as handle:
                dispatch_counts = aggregate_dispatch_jsonl(handle)

    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "tool": name,
            "public": name in public,
            "narrative_mentions": counts[name],
            "dispatch_count": dispatch_counts.get(name, 0),
        }
        for name in all_names
    ]
    (out / "census.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")

    lines = [
        "| tool | public | narrative mentions | dispatches |",
        "|---|---|---|---|",
    ]
    for row in sorted(rows, key=lambda item: (item["narrative_mentions"], item["dispatch_count"])):
        lines.append(
            f"| {row['tool']} | {row['public']} | "
            f"{row['narrative_mentions']} | {row['dispatch_count']} |"
        )
    (out / "census.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out / 'census.json'} and {out / 'census.md'}")


if __name__ == "__main__":
    main()
