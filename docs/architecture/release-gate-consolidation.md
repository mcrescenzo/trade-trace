# Release quality-gate consolidation (SIMP-013)

> Status: **findings + plan** for bead `trade-trace-42vr`. No code or
> workflow changes in this document. Implementation lands as a
> follow-up bead.

## Problem

Two GitHub Actions workflows ship identical test jobs:

- `.github/workflows/ci.yml` runs `ruff` / `mypy` / `pytest` across
  Python 3.11/3.12/3.13 on every PR and push to `main`.
- `.github/workflows/workflow.yml` runs the same job on `v*` tags
  before building and publishing to PyPI.

The publish workflow's leading comment ("the publish workflow keeps
its own internal test gate as a safety net") makes the duplication
intentional, but every workflow tweak (Python version matrix,
dependency cache, new gate command) must be applied twice. A reviewer
fixing one workflow can easily forget the other.

Separately, the package version is duplicated:

- `pyproject.toml` `[project] version`
- `src/trade_trace/version.py` `__version__`

The publish workflow has a custom shell step that asserts the git tag,
pyproject value, and module value all agree before building. Adding
`tests/docs/test_markdown_links.py::test_pyproject_version_matches_module_version`
(`trade-trace-ensw`) pinned the same invariant at PR time, but the
source of truth still lives in two places.

## Choices considered

### A. Reusable workflow for the test gate

Extract the test matrix into a `workflow_call`-triggered workflow
file, e.g. `.github/workflows/_test.yml`. Both `ci.yml` and
`workflow.yml` then `uses: ./.github/workflows/_test.yml` instead of
inlining the job.

**Pros:** one source of truth for the gate steps; any change to Python
matrix / cache / ruff/mypy/pytest invocations updates both surfaces at
once.
**Cons:** small refactor; reviewers need to follow the `uses:` link to
read the steps.
**Recommendation:** **adopt**. This is the clean fix for the gate
duplication.

### B. Composite action

Same idea, but as a composite action under `.github/actions/test-gate/`.
**Pros:** can be invoked from any step, not just a job.
**Cons:** composite actions can't define their own job matrix, so we'd
still need a per-Python-version matrix at the caller level. Worse
ergonomics than the reusable workflow.
**Recommendation:** skip.

### C. Single-source the package version

Two viable shapes:

C1. **`pyproject.toml` → `version.py`**: setuptools `dynamic` config
   reads `__version__` from the module. `version.py` becomes the
   canonical source.

   ```toml
   [project]
   dynamic = ["version"]

   [tool.setuptools.dynamic]
   version = {attr = "trade_trace.version.__version__"}
   ```

C2. **`version.py` → `pyproject.toml`**: `version.py` reads the
   installed package metadata at import time:

   ```python
   from importlib.metadata import version as _pkg_version
   __version__ = _pkg_version("trade-trace")
   ```

   `pyproject.toml` stays canonical; `version.py` is a thin re-export.

C1 is the pattern setuptools documentation explicitly endorses for
this use case. C2 fails at editable-install boundaries when the
package metadata is missing (e.g. `pip install -e .` before the
`.egg-info` exists) and adds a runtime cost. **Recommendation:**
adopt C1.

## Recommendation

The follow-up implementation bead lands two narrow changes:

1. **Extract reusable test workflow.** New file
   `.github/workflows/_test.yml` declares the matrix + the four steps
   (install, ruff, mypy, pytest) under `on: workflow_call`. `ci.yml`
   and `workflow.yml` replace their inlined `test:` job with
   `uses: ./.github/workflows/_test.yml`. The publish workflow's
   `build` job continues to `needs: test` per current ordering. No
   semantic change to the gate.

2. **Single-source version on `version.py`.** Add
   `[project] dynamic = ["version"]` and
   `[tool.setuptools.dynamic] version = {attr =
   "trade_trace.version.__version__"}` to `pyproject.toml`. Remove
   the literal `version = "0.0.1rc3"` line. Drop the
   `test_pyproject_version_matches_module_version` test (now
   structurally impossible) and instead add
   `test_module_version_renders_correctly_in_wheel`: build with
   `python -m build`, unzip the wheel, assert `Version: <expected>`
   appears in METADATA. The publish workflow's existing tag-vs-version
   check stays.

## Compatibility and migration

- Existing publish flow ordering is preserved (`test` → `build` →
  `publish`).
- The version-tag check in `workflow.yml` keeps validating the git tag
  against `version.py`; only the pyproject side moves to dynamic.
- A clean rebuild verifies the dynamic version resolves: `python -m
  build` will fail loudly if setuptools can't import
  `trade_trace.version`. That's the right failure shape.
- `pip install -e .` keeps working — setuptools resolves the dynamic
  version by importing the package at install time.

## Out of scope

- Replacing setuptools with another build backend (hatch, flit). The
  dynamic-attr pattern works under setuptools; changing backend is a
  separate, larger decision.
- Adding setuptools-scm or git-tag-driven versioning. The current
  human-pinned version flow has known semantics (operator bumps in
  the same PR as the work); auto-versioning is a different policy.
- Caching the wheel build across CI/publish runs.
