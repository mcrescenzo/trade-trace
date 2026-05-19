"""Telemetry / auto-update / crash-reporter ban audit per bead trade-trace-4qf.

The MVP must never silently phone home. The acceptance criterion is a
grep audit: no source file under `src/` may import or string-match any
of the documented telemetry packages.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

SRC_ROOT = Path(__file__).resolve().parents[2] / "src"


BANNED_PACKAGES = (
    "sentry_sdk",
    "sentry",
    "mixpanel",
    "segment",
    "datadog",
    "ddtrace",
    "rollbar",
    "posthog",
    "amplitude",
    "honeycomb",
    "newrelic",
)


def _iter_python_sources() -> list[Path]:
    return sorted(p for p in SRC_ROOT.rglob("*.py")
                  if "__pycache__" not in p.parts)


@pytest.mark.parametrize("package", BANNED_PACKAGES)
def test_no_source_imports_telemetry_package(package):
    """Grep the source tree for `import <package>` or `from <package>`.
    The deny-list pins the contract; adding a new banned package is a
    one-line update with no other change."""

    import_re = re.compile(
        rf"(^|\n)\s*(from|import)\s+{re.escape(package)}(\.|\s|$)",
    )
    offending: list[str] = []
    for path in _iter_python_sources():
        text = path.read_text(encoding="utf-8")
        if import_re.search(text):
            offending.append(str(path.relative_to(SRC_ROOT)))
    assert offending == [], (
        f"banned telemetry package {package!r} imported in: {offending}"
    )


def test_pyproject_declares_no_telemetry_dependencies():
    """The package's declared deps must not include any banned name —
    a transitive dep can sneak in without an explicit `import`, so the
    pyproject manifest is the second line of defense."""

    pyproject = (Path(__file__).resolve().parents[2] / "pyproject.toml")
    if not pyproject.exists():
        pytest.skip("pyproject.toml not present")
    text = pyproject.read_text(encoding="utf-8")
    for package in BANNED_PACKAGES:
        # Match `package` as a dep entry: either bare or with version
        # specifier `package>=...`, `package~=`, etc.
        pat = re.compile(rf"(^|\n)\s*['\"]?{re.escape(package)}['\"]?[\s=<>~!]")
        assert not pat.search(text), (
            f"pyproject.toml declares banned dependency {package!r}"
        )
