import json

from scripts.catalog_census import aggregate_dispatch_jsonl, tool_mention_counts

NAMES = [
    "report.calibration",
    "report.calibration_integrity",
    "report.mistakes",
    "market.bind",
]


def test_counts_exact_tool_mentions() -> None:
    text = "ran report.calibration then market.bind, then report.calibration again"
    counts = tool_mention_counts([text], NAMES)

    assert counts["report.calibration"] == 2
    assert counts["market.bind"] == 1
    assert counts["report.mistakes"] == 0


def test_longer_name_is_not_double_counted_as_prefix() -> None:
    text = "report.calibration_integrity flagged nothing"
    counts = tool_mention_counts([text], NAMES)

    assert counts["report.calibration_integrity"] == 1
    assert counts["report.calibration"] == 0


def test_mentions_inside_paths_or_snake_prose_do_not_count() -> None:
    text = "see src/report.calibration_helpers.py and xreport.calibration"
    counts = tool_mention_counts([text], NAMES)

    assert counts["report.calibration"] == 0


def test_every_known_name_present_in_result_even_at_zero() -> None:
    counts = tool_mention_counts(["nothing here"], NAMES)

    assert set(counts) == set(NAMES)


def test_aggregate_dispatch_jsonl_counts_tool_field() -> None:
    lines = [
        json.dumps({"tool": "report.calibration", "ok": True}),
        json.dumps({"tool": "report.calibration", "ok": False}),
        json.dumps({"tool": "market.bind", "ok": True}),
        "not json at all",
    ]
    counts = aggregate_dispatch_jsonl(lines)

    assert counts["report.calibration"] == 2
    assert counts["market.bind"] == 1
