# Pre-Publish Release Proof

> Status: **proof artifact** for trade-trace-a468. Recorded
> 2026-05-19 against the post-piav commit. This is historical proof; the
> current public-history strategy is a clean public export/branch from
> approved HEAD, with separate approval required before any public branch,
> tag, or PyPI publish action.

## Commands run and their outcomes

| Gate | Command | Result |
|------|---------|--------|
| Lint | `ruff check src tests` | `All checks passed!` |
| Types | `mypy src` | `Success: no issues found in 86 source files` |
| Tests | `pytest -q` | `1200 passed, 5 skipped` (skips are the documented opt-ins: perf baselines, dogfood full-suite) |
| Build | `python -m build` | `Successfully built trade_trace-0.0.1rc3.tar.gz and trade_trace-0.0.1rc3-py3-none-any.whl` |
| Twine | `twine check --strict dist/*` | Both wheel and sdist `PASSED` |
| CLI smoke | `tt --help` (fresh venv) | renders usage block |
| MCP smoke | `trade-trace-mcp --help` (fresh venv) | exits 0 |
| Pip check | `pip check` (fresh venv) | `No broken requirements found.` |
| Journal init smoke | `tt journal init --home /tmp/tt-fresh-home` | ok=true, schema_version=10 |
| Console help smoke | `tt console serve --help` (fresh venv) | renders flag block |

## Wheel and sdist surface

The wheel contains only the intended public files:

- `trade_trace/` (Python source tree, including `console/`,
  `contracts/`, `events/`, `models/`, `reports/`, `security/`,
  `storage/`, `tools/`).
- `trade_trace/console/static/app/index.html`.
- `trade_trace/console/static/app/assets/*`.
- `LICENSE`, `METADATA`, `WHEEL`, `entry_points.txt`,
  `top_level.txt`, `RECORD`.

It does **not** contain:

- `.beads/` (Beads metadata).
- `audits/` or `docs/audits/` (audit run artifacts).
- Any local `*.sqlite` or runtime data.

Smoke scan (`zipfile -l dist/...whl | grep -iE 'beads|audits|hermes'`):
only `trade_trace/storage/edge_audit.py` matches — that's the
audit-policy source file, not the audit-export tree. Acceptable.

## Public-artifact scan

Run against tracked files at the intended release commit
(post-piav, post-ox5c-plan):

| Scan | Result |
|------|--------|
| `git ls-files \| grep -E '^\.beads/\|^audits/\|^docs/audits/'` | empty |
| `git grep -l '<owner-email>'` | empty |
| `git grep -l '<local-home-path>'` | empty |

The above proves the **HEAD-only** scrub is complete. Old
private commits may still hold prior blobs. The selected public strategy is
to publish a clean single-commit export/branch from approved HEAD rather
than rewriting private history. The PyPI upload itself ships
the wheel/sdist (which were never derived from the offending
blobs); the rewrite affects only what someone sees if they
`git clone` and `git log -p` through history.

## Final operator approval

The following destructive / shared-state actions remain
operator-gated. The agent will not perform them without explicit
approval:

1. Approve and publish the clean public export/branch candidate.
2. Tag the release (`git tag v0.0.1rc3 && git push --tags`).
3. Upload to PyPI (`twine upload dist/*` or the OIDC-gated GitHub
   Actions release workflow that lives in
   `.github/workflows/workflow.yml`).

Each of these is reversible only with substantial effort; the
operator-approval boundary is intentional.
