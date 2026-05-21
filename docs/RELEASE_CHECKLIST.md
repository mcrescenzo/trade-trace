# Release checklist

Trade Trace publishes pre-releases via the
[`Publish to PyPI`](../.github/workflows/workflow.yml) workflow.
Releases are gated on a `v<version>` tag that matches `pyproject.toml`
and `src/trade_trace/version.py`, but the tag-triggered workflow is not
complete release proof by itself. The GitHub Actions lane only runs the
shared Python ruff/mypy/pytest gate, verifies the tag/package version,
builds distributions, runs `twine check`, and then waits on the PyPI
environment before trusted publishing. Console release proof, fresh wheel
smoke, and any GitHub/PyPI remote environment-protection checks below are
manual candidate evidence unless a future workflow explicitly automates
them.

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

Record the candidate SHA, tag name, command outputs, and any skipped
manual gate with a reason before pushing the release tag. A green PR/main
CI run or a pushed tag is not sufficient proof that the candidate is
ready to publish.

```bash
ruff check src tests
mypy src
pytest -q                       # record the fresh current-HEAD result
python -m build                 # no warnings; SPDX license + classifiers
python -m twine check dist/*    # PASSED on both wheel and sdist
```

Run the Console release gate from
[`docs/architecture/console-release-gate.md`](architecture/console-release-gate.md)
unless the candidate explicitly excludes Console changes and records that
rationale. The current CI/publish workflows do **not** run the Node/Vite,
browser, or visual-review portions of this gate automatically.

```bash
npm --prefix frontend/console ci
npm --prefix frontend/console run test
npm --prefix frontend/console run build
pytest tests/contracts/test_console_serve.py tests/contracts/test_console_http_routes.py
pytest tests/contracts/test_console_shell.py tests/contracts/test_console_dashboard_a11y.py
pytest tests/contracts/test_console_charting.py
pytest tests/security/test_console_security_headers.py
pytest tests/console_browser/
```

Also record the required Console visual review evidence (or the explicit
reason it is not applicable) using `console-visual-review.md` as described
by the Console gate.

Smoke the wheel in a fresh venv built from the exact candidate. This is
manual candidate proof today; CI/publish does not install the freshly
built artifact before upload. Cover every shipped console script plus
optional extras that apply to the candidate.

```bash
python -m venv /tmp/rc-smoke
/tmp/rc-smoke/bin/pip install dist/trade_trace-<version>-py3-none-any.whl
/tmp/rc-smoke/bin/tt --help
/tmp/rc-smoke/bin/trade-trace --help
/tmp/rc-smoke/bin/trade-trace-mcp --help    # or `echo | trade-trace-mcp`
/tmp/rc-smoke/bin/pip check

# When Console is in the release lane, also smoke its runtime extra:
/tmp/rc-smoke/bin/pip install 'dist/trade_trace-<version>-py3-none-any.whl[console]'
/tmp/rc-smoke/bin/tt console serve --help
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
4. GitHub Actions reruns only the shared Python test gate, verifies the
   tag/package version, builds, and runs `twine check`. It does not rerun
   the manual Console gate or fresh-wheel smoke above.
5. If the `pypi` environment is protected, the operator separately
   verifies the GitHub/PyPI trusted-publishing settings and approves that
   environment for the same candidate SHA. Remote environment protection
   configuration is human verification, not evidence produced by this
   checklist.

Do not publish stable `0.0.1` until the owner records explicit approval.
