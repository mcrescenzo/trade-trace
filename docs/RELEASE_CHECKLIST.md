# Release checklist

Trade Trace publishes pre-releases via the
[`Publish to PyPI`](../.github/workflows/workflow.yml) workflow.
Releases are gated on a `v<version>` tag that matches `pyproject.toml`
and `src/trade_trace/version.py`.

## Version + tag policy

- The package stays on `0.0.x` pre-releases until the owner approves
  a stable `0.0.1` cut. Each release is a `0.0.1rc<N>` (e.g.
  `0.0.1rc3`).
- `pyproject.toml` uses dynamic versioning and reads the package
  version from `src/trade_trace/version.py` (`__version__`). The
  source version and the git tag (stripped of its `v` prefix) must
  agree before tagging.
- The publish workflow builds from that dynamic version source and
  aborts if the tag does not match the package metadata. See the
  `Verify tag matches package versions` step in
  [`workflow.yml`](../.github/workflows/workflow.yml).

## Pre-publish checks (run from a clean checkout)

```bash
ruff check src tests
mypy src
pytest -q                       # record the fresh current-HEAD result
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

Scan refs intended for publication for leftover private/raw
Beads/audit artifacts, personal info, or secret-shaped strings (see
trade-trace-piav, trade-trace-ox5c):

```bash
git ls-files | grep -E '^(\.beads/|audits/)'  # must be empty
git ls-files | grep -E '^docs/audits/'         # intentionally non-empty:
                                                # curated repo-public audit docs
```

Do not treat dated pytest counts in older release proof documents as
current proof. Rerun `pytest -q` for the current HEAD and record the
fresh result, or explicitly label any reused count as historical
snapshot evidence.

## Cut a release

1. Bump `src/trade_trace/version.py` (`__version__`). `pyproject.toml`
   reads this dynamically; do not add a separate static project version.
2. Commit on `main`. Open a PR; require maintainer approval.
3. After merge, tag the merge commit: `git tag v0.0.1rc<N>` and push.
4. GitHub Actions builds, verifies version triple, and publishes via
   OIDC trusted publishing.

Do not publish stable `0.0.1` until the owner records explicit approval.
