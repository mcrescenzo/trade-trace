# Final Public PyPI Release Gate

> Status: **gate closed — operator-approved publish actions remain**.
> Recorded 2026-05-19 against the trade-trace-ak5p epic's
> post-piav, post-ox5c-plan HEAD.

## Closure rationale

Every **material** child bead under the
`trade-trace-ak5p` release-readiness epic is complete:

| Child bead | Status | Artifact |
|------------|--------|----------|
| trade-trace-piav | closed | HEAD scrub policy: `.beads/`, root `audits/`, generated `docs/audits/`, and generated `docs/reviews/` stay excluded from public HEAD; release evidence is limited to curated summary/proof docs. |
| trade-trace-ox5c | closed | `docs/RELEASE_HISTORY_REWRITE.md` — historical rewrite plan now superseded by the selected clean public export/branch strategy. |
| trade-trace-a468 | closed | `docs/RELEASE_PROOF.md` — full ruff / mypy / pytest / build / twine / fresh-install proof. |

Owner decisions recorded under the bead are reflected in
shipped surfaces:

- **Beads/private or raw audit/review artifacts not public** → `.beads/`,
  root `audits/`, generated `docs/audits/`, and generated `docs/reviews/`
  remain excluded from HEAD; .gitignore prevents accidental re-tracking.
  Public release evidence is limited to concise curated summary/proof docs,
  not raw run directories.
- **MCP required, not optional** → `pyproject.toml` lists
  `mcp>=1.0` under `dependencies` (the `[mcp]` extra is an
  empty back-compat alias).
- **PyPI README links to GitHub docs** → README.md links into
  `docs/` rather than inlining the full doc tree.
- **SECURITY.md uses GitHub Security Advisories** →
  `SECURITY.md:20` ("Please report vulnerabilities privately
  via GitHub Security…").
- **Target version is 0.0.1rc3** → `src/trade_trace/version.py`
  / `pyproject.toml` dynamic version resolve to `0.0.1rc3`.
- **Maintainer-only contribution posture for first release** →
  no CoC / governance ceremony added; release docs are minimal.

## Final-gate proof snapshot (historical, recorded 2026-05-19)

The command results below are preserved as a dated snapshot from the
original gate run. They are not a live/current proof for later HEADs;
rerun the commands in `docs/RELEASE_CHECKLIST.md` before publishing. In
particular, this historical snapshot predates the explicit Console gate
and full fresh-wheel script parity now required by the checklist, so it
must not be treated as evidence that the Console gate, `trade-trace`
entry point, optional extras, or browser/visual review are current.

| Gate | Result |
|------|--------|
| `ruff check src tests` | All checks passed |
| `mypy src` | Success: no issues found in 86 source files |
| `pytest -q` | 1200 passed, 5 skipped (documented opt-ins) — historical snapshot |
| `python -m build` | wheel + sdist built |
| `twine check --strict dist/*` | both PASSED |
| Fresh-venv `pip install dist/*.whl` | works |
| Fresh-venv `tt --help`, `trade-trace-mcp --help` | both render |
| Fresh-venv `pip check` | No broken requirements found |
| `git ls-files \| grep -E '^(\.beads/\|audits/\|docs/audits/\|docs/reviews/)'` | empty — private/raw artifact roots absent from tracked HEAD |
| `git ls-files docs/audits docs/reviews` | empty — generated audit/review run directories are internal and ignored |
| `git grep -l <owner-email>` against tracked HEAD | empty |
| `git grep -l '<local-home-path>'` against tracked HEAD | empty |
| Wheel surface scan | only `trade_trace/storage/edge_audit.py` matches `audit` (intentional — it's the audit-policy module, not an audit export) |

## Remaining operator-gated actions

These are explicitly **NOT** done by the closure of this gate.
They require the operator's explicit approval at execution
time:

1. **Create or publish the clean public branch/export** from the approved
   private HEAD after reviewing the export proof. This is the selected
   public-history strategy; it avoids rewriting private `main`.
2. **Tag the release** (`git tag v0.0.1rc3 && git push --tags`) only after
   separate approval for the exact public candidate SHA.
3. **Upload to PyPI** (via `twine upload` or the OIDC GitHub Actions
   workflow in `.github/workflows/workflow.yml`) only after separate approval.

Publishing a public branch, pushing a tag, and uploading to PyPI are shared
state actions; PyPI upload is write-once per version. The operator-approval boundary is
intentional and matches the project's CLAUDE.md guidance on
destructive / shared-state actions.

## How to use this gate

Close `trade-trace-jqae` after this document is reviewed.
The bead's acceptance reads: "All material child beads have
been resolved; fresh clean release proof passes; public-history
scan and package-content inspection are clean; no
publish/force-push happens without explicit final approval."

This document records each of those criteria's status:

- ✅ Material children resolved (table above).
- ✅ Release proof snapshot in `docs/RELEASE_PROOF.md` and the table
  above is historical evidence; rerun the checklist for current proof.
- ✅ Tracked-HEAD scan clean for private/raw roots (`.beads/`, root
  `audits/`, generated `docs/audits/`, generated `docs/reviews/`).
- ✅ Public-history strategy selected: clean single-commit export/branch with fresh reachable-history scan; no private-history rewrite or force-push is part of this path.
- ✅ "No publish/force-push happens without explicit final
  approval" — the injunction is the policy; this gate honors
  it by not running those commands.

This document is **not** current publish authority for any later
HEAD by itself. After the operator approves a public export candidate, the exact commit that will be
tagged/uploaded must first have a fresh `docs/RELEASE_CHECKLIST.md`
rerun recorded against that candidate SHA. The release becomes
shippable only when that candidate-specific proof records the exact
SHA and the outcomes of the checklist commands, and the operator then
approves the publish workflow for that same candidate.

The tag-triggered workflow is also not complete release proof by itself:
it runs the shared Python ruff/mypy/pytest gate, verifies package/tag
versions, builds, and checks distribution metadata, but it does not run
the Console Node/Vite gate, browser smoke, visual review, or install the
freshly built wheel for script/extra parity before upload.
