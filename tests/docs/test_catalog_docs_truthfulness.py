"""Docs-truthfulness guards for the public tool catalog and legacy tool naming.

Two release-blocking truthfulness invariants for the active operator/release
docs, both derived from the *live* registry so they self-update when the catalog
changes (a stale hard-coded count or an un-caveated legacy tool name fails the
build instead of silently drifting):

* trade-trace-skp3 — public tool-catalog counts in README / AGENT_GUIDE /
  RELEASE_FINAL_GATE / the generated catalog doc must match
  ``build_registry().public_names()`` (and the experimental delta).
* trade-trace-mx9m — names that the live registry hides as legacy or marks
  admin-only must not be presented as current canonical operator surfaces in
  the PRD / README without a back-compat / admin caveat.

Scope note (per the docs-taxonomy / docs-truthfulness doctrine): these guards
target the *catalog-presentation* surfaces an operator or agent would actually
read as "the current tools" — the §4.0/§4.4 tool-definition bullets, the
milestone write-tool list, and the ``tt model import`` setup commands. They do
not police every incidental mention of a folded name inside design narrative.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from trade_trace.core import build_registry

REPO = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def registry():
    return build_registry()


@pytest.fixture(scope="module")
def public_count(registry):
    return len(registry.public_names())


@pytest.fixture(scope="module")
def experimental_delta(registry):
    return len(registry.public_names(include_experimental=True)) - len(
        registry.public_names()
    )


# --------------------------------------------------------------------------
# trade-trace-skp3 — public catalog count truthfulness
# --------------------------------------------------------------------------

# (doc, regex with one int group capturing a *public-catalog* count claim)
PUBLIC_COUNT_CLAIMS = [
    ("README.md", r"(\d+) registry-generated tools"),
    ("docs/AGENT_GUIDE.md", r"(\d+)-tool public catalog"),
    ("docs/RELEASE_FINAL_GATE.md", r"documented as (\d+) public tools"),
    ("docs/architecture/v002-pm-pivot-catalog.md", r"(\d+)-tool public catalog"),
]


@pytest.mark.parametrize("rel,pattern", PUBLIC_COUNT_CLAIMS)
def test_public_catalog_counts_match_runtime(rel, pattern, public_count):
    text = _read(rel)
    matches = re.findall(pattern, text)
    assert matches, f"{rel}: expected a public-catalog count matching /{pattern}/"
    for m in matches:
        assert int(m) == public_count, (
            f"{rel}: doc claims {m} public tools but the runtime registry has "
            f"{public_count} (build_registry().public_names())"
        )


def test_readme_experimental_count_matches_runtime(experimental_delta):
    text = _read("README.md")
    m = re.search(r"A further (\d+) ", text)
    assert m, "README: expected 'A further N ... experimental tier' clause"
    assert int(m.group(1)) == experimental_delta, (
        f"README: claims {m.group(1)} experimental tools but the runtime delta "
        f"is {experimental_delta}"
    )


def test_pivot_catalog_verification_script_expected_counts(
    public_count, experimental_delta
):
    text = _read("docs/architecture/v002-pm-pivot-catalog.md")
    expected = [int(m) for m in re.findall(r"# Expected: (\d+)", text)]
    assert len(expected) >= 2, (
        "v002-pm-pivot-catalog.md §5: expected at least two '# Expected: N' "
        "comments (public count, then experimental delta)"
    )
    assert expected[0] == public_count, (
        f"§5 public-count check claims {expected[0]}, runtime has {public_count}"
    )
    assert expected[1] == experimental_delta, (
        f"§5 experimental-delta check claims {expected[1]}, runtime has "
        f"{experimental_delta}"
    )


# --------------------------------------------------------------------------
# trade-trace-mx9m — legacy / admin-hidden tools not presented as canonical
# --------------------------------------------------------------------------

# Original-MVP write/setup tool names that v0.0.2 folded into consolidated
# canonical tools (hidden legacy aliases) or gated as admin-only. These are the
# names an operator/agent would actually try to call as a current surface.
LEGACY_OPERATOR_TOOLS = (
    "venue.add",
    "instrument.add",
    "thesis.add",
    "forecast.supersede",
    "outcome.add",
    "resolve.pending",
    "resolve.record",
    "model.import",
)

# Unambiguous "this is not a current canonical surface" markers only. Domain
# terms that also read as caveats (e.g. a `supersedes` graph edge, "replaced
# row") are deliberately excluded so a bullet cannot pass on narrative alone.
CAVEAT_RE = re.compile(
    r"legacy|alias|back-?compat|deprecat|renamed|folded|hidden|admin|consolidat",
    re.I,
)


def _caveated(line: str) -> bool:
    """True if ``line`` carries a back-compat/admin caveat keyword.

    The tool tokens themselves are stripped first so a name like
    ``forecast.supersede`` cannot satisfy the check via its own 'supersed'
    substring.
    """
    stripped = line
    for name in LEGACY_OPERATOR_TOOLS:
        stripped = stripped.replace(name, "")
    return bool(CAVEAT_RE.search(stripped))


def _definition_bullet_lines(text: str, name: str) -> list[str]:
    """Lines that *define* ``name`` as a catalog tool: ``- `name`` / ``- **`name(``."""
    pat = re.compile(r"^\s*-\s*\*{0,2}`" + re.escape(name) + r"[(`]")
    return [line for line in text.splitlines() if pat.search(line)]


def test_named_operator_tools_are_hidden_in_registry(registry):
    """Premise guard: every name we caveat as legacy must really be non-public
    (legacy/experimental) or admin in the live registry, so this list cannot
    silently drift back to claiming a current tool is legacy."""
    for name in LEGACY_OPERATOR_TOOLS:
        reg = registry.by_name[name]
        assert reg.catalog_visibility != "public" or reg.is_admin, (
            f"{name}: registry now marks this public/non-admin — the doc "
            f"caveats and this guard need revisiting"
        )


@pytest.mark.parametrize(
    "name",
    [
        "venue.add",
        "instrument.add",
        "thesis.add",
        "forecast.supersede",
        "resolve.pending",
        "resolve.record",
    ],
)
def test_prd_catalog_definition_bullets_mark_legacy(name):
    text = _read("docs/PRD.md")
    bullets = _definition_bullet_lines(text, name)
    assert bullets, f"docs/PRD.md: no catalog-definition bullet found for {name}"
    for line in bullets:
        assert _caveated(line), (
            f"docs/PRD.md: catalog bullet for legacy tool {name} lacks a "
            f"back-compat caveat:\n  {line.strip()}"
        )


def test_prd_does_not_present_outcome_add_as_canonical():
    text = _read("docs/PRD.md")
    assert "`outcome.add` is the canonical name" not in text, (
        "docs/PRD.md still inverts the resolution write tool: resolution.add "
        "is the v0.0.2 canonical name; outcome.add is a legacy alias"
    )
    assert "`resolution.add`" in text, (
        "docs/PRD.md should name the canonical resolution.add tool"
    )


def test_prd_milestone_write_tool_list_is_caveated():
    text = _read("docs/PRD.md")
    lines = [line for line in text.splitlines() if "Core write tools per" in line]
    assert lines, "docs/PRD.md: expected a milestone 'Core write tools per §4.0' line"
    for line in lines:
        assert _caveated(line), (
            f"docs/PRD.md: milestone write-tool list names legacy tools without "
            f"a caveat:\n  {line.strip()}"
        )


def test_model_import_command_mentions_are_caveated():
    """Every operator-facing ``tt model import`` command line must flag that the
    tool is admin-tier / legacy-hidden, not a default operator surface."""
    for rel in ("README.md", "docs/PRD.md"):
        text = _read(rel)
        for line in text.splitlines():
            if "model import" in line and re.search(r"\btt\b", line):
                assert _caveated(line), (
                    f"{rel}: operator `tt model import` line lacks an "
                    f"admin/legacy caveat:\n  {line.strip()}"
                )
