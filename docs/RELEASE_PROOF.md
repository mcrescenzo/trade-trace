# Release proof — v0.0.2 candidate

This file is a template for the current v0.0.2 release proof packet. It intentionally contains no stale pass counts. Fill it only with fresh current-HEAD evidence for the exact candidate SHA.

## Candidate

- Candidate SHA: `<fill after final verification>`
- Version/tag candidate: `v0.0.2` or the owner-approved pre-release tag
- Scope: prediction-market-only local-first pivot
- Live adapter smoke: `completed with sanitized evidence` or `deferred — no disposable RPC/test condition supplied`

## Required command evidence

Record exact output or an attached sanitized artifact for each gate:

| Gate | Command / evidence | Result |
|---|---|---|
| Dev + embeddings install | `python -m pip install -e '.[dev,embeddings]'` and `python -c "import onnxruntime, tokenizers"` | `<fill>` |
| Lint | `ruff check src tests` | `<fill>` |
| Types | `mypy src` | `<fill>` |
| Full tests | `PYTHONPATH=src pytest -q` | `<fill>` |
| Docs tests | `PYTHONPATH=src pytest tests/docs -q` | `<fill>` |
| Security suite | `PYTHONPATH=src pytest tests/security -q` | `<fill>` |
| Boundary audit | `PYTHONPATH=src pytest tests/security/test_mvp_boundary_audit.py -q` | `<fill>` |
| Offline/no-network adapter gates | no-network default + no-RPC adapter tests | `<fill>` |
| URL/secret scrubbing | adapter URL scrubbing + endpoint policy tests | `<fill>` |
| Perf smoke | `TRADE_TRACE_RUN_PERF_TESTS=1 ...` | `<fill>` |
| Package build | `python -m build` and `python -m twine check dist/*` | `<fill>` |
| Fresh wheel smoke | install candidate wheel in a new venv and run `tt --help`, `trade-trace-mcp --help`, `pip check` | `<fill>` |

## Release boundary assertion

The candidate remains:

- local/offline by default,
- prediction-market-only for v0.0.2,
- no trade execution,
- no broker or wallet credentials,
- no default RPC endpoint,
- no remote/API embeddings,
- no human dashboard/frontend,
- no background scheduler/fetch daemon.

## Publication approvals

Do not fill these unless Michael explicitly approves the exact action and candidate SHA.

- Public branch/export approved: `<yes/no + evidence>`
- Tag push approved: `<yes/no + evidence>`
- PyPI publication approved: `<yes/no + evidence>`
