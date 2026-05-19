# Release checklist

Trade Trace publishes pre-releases via the
[`Publish to PyPI`](../.github/workflows/workflow.yml) workflow.
Releases are gated on a `v<version>` tag that matches `pyproject.toml`
and `src/trade_trace/version.py`.

## Version + tag policy

- The package stays on `0.0.x` pre-releases until the owner approves
  a stable `0.0.1` cut. Each release is a `0.0.1rc<N>` (e.g.
  `0.0.1rc3`).
- All three version surfaces must agree before tagging:
  - `pyproject.toml` → `[project] version`
  - `src/trade_trace/version.py` → `__version__`
  - the git tag (stripped of its `v` prefix)
- The publish workflow re-checks all three and aborts on mismatch.
  See the `Verify tag matches package versions` step in
  [`workflow.yml`](../.github/workflows/workflow.yml).

## Pre-publish checks (run from a clean checkout)

```bash
ruff check src tests
mypy src
pytest -q                       # 1059 passed expected
python -m build                 # no warnings; SPDX license + classifiers
python -m twine check dist/*    # PASSED on both wheel and sdist
```

Smoke the wheel in a fresh venv:

```bash
python -m venv /tmp/rc-smoke
/tmp/rc-smoke/bin/pip install dist/trade_trace-<version>-py3-none-any.whl
/tmp/rc-smoke/bin/tt --help
/tmp/rc-smoke/bin/trade-trace-mcp --help    # or `echo | trade-trace-mcp`
/tmp/rc-smoke/bin/pip check
```

Scan refs intended for publication for leftover Beads/audit artifacts,
personal info, or secret-shaped strings (see trade-trace-piav,
trade-trace-ox5c).

## Cut a release

1. Bump version in `pyproject.toml` and `src/trade_trace/version.py`.
2. Commit on `main`. Open a PR; require maintainer approval.
3. After merge, tag the merge commit: `git tag v0.0.1rc<N>` and push.
4. GitHub Actions builds, verifies version triple, and publishes via
   OIDC trusted publishing.

Do not publish stable `0.0.1` until the owner records explicit approval.
