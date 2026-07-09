# Release final gate — v0.0.2

This document records the release decision boundary for the v0.0.2 prediction-market pivot. Manual/tagged releases still require explicit owner approval for the exact candidate SHA. Separately, the repository now has an owner-approved risky automation policy: every push to `main` may publish a stable PyPI post-release after CI computes a unique version and the publish workflow passes.

## Candidate boundary

- Target: v0.0.2 pre-release candidate.
- Product shape: local-first calibration journal, memory, and evaluation substrate for LLM prediction-market agents.
- Supported surfaces: MCP stdio, JSON-first CLI, and Python/reporting APIs.
- Default network posture: no outbound calls for first run or ordinary local operations.
- Adapter posture: Polymarket adapter disabled by default, explicit opt-in, agent-triggered, HTTPS-only, no default RPC URL.
- Embeddings posture: provider enum `none|local`; local ONNX/tokenizers assets are manually imported; remote/API embedding providers and keyring-backed embedding credentials are unsupported.
- Explicit non-goals: execution, broker/wallet credentials, financial advice, human dashboard/frontend, scheduler/fetch daemon, generic continuous-asset journal.

## Required proof before tag

Use `docs/RELEASE_CHECKLIST.md` as the canonical command checklist. Before any tag:

1. Static checks pass: `ruff check src tests`, `mypy src`.
2. Full tests pass from current HEAD: `PYTHONPATH=src pytest -q`.
3. Docs/security release gates pass, including docs truth tests, boundary audit, no-network default, endpoint policy, and URL scrubbing tests.
4. Public tool catalog is verified against runtime/schema expectations and documented as 82 public tools (the live `build_registry().public_names()` count; update this gate when the catalog count changes).
5. Fresh journal and offline market-bind smoke have been exercised.
6. Live Polymarket smoke is either completed with sanitized evidence or explicitly deferred because no disposable Polygon RPC URL / real test condition was provided. If deferred, release notes must say live-adapter smoke was not exercised.
7. Package build and fresh wheel smoke pass.
8. PyPI trusted-publisher / GitHub environment protection are verified for the selected publication path: automatic `main` post-release publishing or manual `v*` tag publishing.

## Safety publication rule

Do not publish manual/tagged releases from stale dated proof. If an older proof file lists historical pytest counts, package names, or tag names, treat it as a historical snapshot, not a live/current proof. Manual release candidates are proven only by current-head command output and fresh package/wheel smoke. Automatic `main` post-releases are proven by the GitHub Actions run for that exact commit.

## Repo-public audit evidence

`docs/audits/` is intentionally tracked for curated audit evidence. Those files are repo-public and may be cited as historical, sanitized support material, but they do not replace the fresh current-head release gates above.

## Approval rule

For manual/tagged releases, the maintainer must approve:

1. the exact public branch/export candidate,
2. the exact tag push,
3. the exact PyPI publication path.

No agent should infer manual/tagged-release approvals from green tests or from this document. The `main` branch auto-publish path is intentionally different: merge/push to `main` is the publication trigger, and the workflow computes the PyPI version as `<src-version>.post<git-commit-count>` without committing a version bump.
