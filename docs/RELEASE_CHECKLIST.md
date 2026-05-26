# v0.0.2 release checklist

Trade Trace v0.0.2 is a prediction-market-only, local-first release candidate. This checklist is pre-tag evidence, not permission to publish. Pushing a public branch, pushing a release tag, and PyPI publishing each require explicit owner approval for the exact candidate SHA.

## Release boundary

- Product: local calibration journal, memory, and evaluation substrate for LLM prediction-market agents.
- Default posture: offline/local by default; Polymarket adapter disabled unless explicitly configured and called.
- Non-goals: trade execution, broker/wallet credentials, financial advice, human dashboard/frontend, background scheduler/fetch daemon, default RPC endpoint, and generic continuous-asset trading journal support.
- Hard break: v0.0.1rc-style fixtures/imports are not silently migrated. Legacy imports must fail with explicit transform-required guidance.

## Required gates before a v0.0.2 tag

Run from a clean checkout and record the candidate SHA plus command output. Do not paste stale dated pytest counts into release notes; record the fresh current-HEAD result for each gate.

1. Install dev + embeddings extras:
   ```bash
   python -m pip install -e '.[dev,embeddings]'
   python -c "import onnxruntime, tokenizers"
   ```
2. Static lint:
   ```bash
   ruff check src tests
   ```
3. Type check:
   ```bash
   mypy src
   ```
4. Full test suite:
   ```bash
   PYTHONPATH=src pytest -q
   ```
5. Fresh journal smoke:
   ```bash
   tt journal init
   tt journal status
   ```
6. Offline/manual market-bind smoke, no adapter/network:
   ```bash
   tt market bind --external-id polymarket:test-condition --source manual --mechanism clob --state open
   ```
7. Manual live-adapter HITL gate (not CI, not default): only if the owner supplies a disposable Polygon RPC URL and real public Polymarket condition. Configure in a throwaway `$TRADE_TRACE_HOME`, run `market.bind`, `snapshot.fetch`, and `outcome.fetch` when applicable, and record sanitized evidence only. If not supplied, explicitly record: live-adapter smoke not exercised; mocked/offline adapter coverage only.
8. Documentation tests:
   ```bash
   PYTHONPATH=src pytest tests/docs -q
   ```
9. Documentation truthfulness review: README, SECURITY, PRD, VISION, agent guide, MCP setup, architecture docs, and this checklist must match runtime tool names and v0.0.2 scope.
10. Security suite:
    ```bash
    PYTHONPATH=src pytest tests/security -q
    ```
11. Boundary audit:
    ```bash
    PYTHONPATH=src pytest tests/security/test_mvp_boundary_audit.py -q
    ```
12. Offline-default adapter gate:
    ```bash
    PYTHONPATH=src pytest tests/security/test_no_network_default.py tests/integration/test_adapter_polymarket_no_rpc.py -q
    ```
13. Adapter URL/secret scrubbing gate:
    ```bash
    PYTHONPATH=src pytest tests/security/test_adapter_url_scrubbing.py tests/security/test_adapter_endpoint_policy.py -q
    ```
14. Opt-in perf smoke:
    ```bash
    TRADE_TRACE_RUN_PERF_TESTS=1 PYTHONPATH=src pytest -q tests/integration/test_bootstrap_perf_baseline.py tests/integration/test_adapter_perf_baseline.py
    ```
15. Package build:
    ```bash
    python -m build
    python -m twine check dist/*
    ```
16. Fresh wheel smoke in a new venv:
    ```bash
    python -m venv /tmp/trade-trace-v002-smoke
    /tmp/trade-trace-v002-smoke/bin/pip install dist/trade_trace-<version>-py3-none-any.whl
    /tmp/trade-trace-v002-smoke/bin/tt --help
    /tmp/trade-trace-v002-smoke/bin/trade-trace-mcp --help || true
    /tmp/trade-trace-v002-smoke/bin/pip check
    ```
17. Publication gate: verify PyPI trusted publisher / GitHub environment protection for the exact candidate before any tag or upload. Do not publish from local evidence alone.

## CI expectations

- Ordinary CI must run adapter tests with network disabled or mocked.
- Live adapter smoke is best-effort/manual and must not block default CI without explicit credentials.
- `.github/workflows/embeddings-smoke.yml` runs a non-blocking weekly/workflow_dispatch optional-dependencies smoke on macOS arm64 and Windows.

## Sanitization rules for release notes

Never paste RPC URLs with keys, request/response bodies, API tokens, private Beads audit dumps, raw emails, or unredacted logs. Acceptable evidence: command names, status codes, latency summaries, public condition IDs, generated market IDs, test counts, and scrubbed error envelopes.
