# Final Public PyPI Release Gate

> Status: **gate closed — operator-approved publish actions remain**.
> Recorded 2026-05-19 against the trade-trace-ak5p epic's
> post-piav, post-ox5c-plan HEAD.

## Closure rationale

Every **material** child bead under the
`trade-trace-ak5p` release-readiness epic is complete:

| Child bead | Status | Artifact |
|------------|--------|----------|
| trade-trace-piav | closed | HEAD scrub: `.beads/`, `audits/`, `docs/audits/` untracked; .gitignore hardened. |
| trade-trace-ox5c | closed | `docs/RELEASE_HISTORY_REWRITE.md` — executable plan for the history rewrite + remote force-push. |
| trade-trace-a468 | closed | `docs/RELEASE_PROOF.md` — full ruff / mypy / pytest / build / twine / fresh-install proof. |

Owner decisions recorded under the bead are reflected in
shipped surfaces:

- **Beads/audit artifacts not public** → piav untracked them
  from HEAD; .gitignore prevents re-tracking.
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

## Final-gate proofs (re-verified)

| Gate | Result |
|------|--------|
| `ruff check src tests` | All checks passed |
| `mypy src` | Success: no issues found in 86 source files |
| `pytest -q` | 1200 passed, 5 skipped (documented opt-ins) |
| `python -m build` | wheel + sdist built |
| `twine check --strict dist/*` | both PASSED |
| Fresh-venv `pip install dist/*.whl` | works |
| Fresh-venv `tt --help`, `trade-trace-mcp --help` | both render |
| Fresh-venv `pip check` | No broken requirements found |
| `git ls-files \| grep -E '^\.beads/\|^audits/\|^docs/audits/'` | empty |
| `git grep -l <owner-email>` against tracked HEAD | empty |
| `git grep -l '/home/hermes'` against tracked HEAD | empty |
| Wheel surface scan | only `trade_trace/storage/edge_audit.py` matches `audit` (intentional — it's the audit-policy module, not an audit export) |

## Remaining operator-gated actions

These are explicitly **NOT** done by the closure of this gate.
They require the operator's explicit approval at execution
time:

1. **Execute the history rewrite** per
   `docs/RELEASE_HISTORY_REWRITE.md`. Required to scrub
   owner email/name and audit artifacts from *prior* commits;
   HEAD is already clean.
2. **Force-push** the rewritten history to `origin/main`.
3. **Tag the release** (`git tag v0.0.1rc3 && git push --tags`).
4. **Upload to PyPI** (via `twine upload` or the OIDC GitHub
   Actions workflow in `.github/workflows/workflow.yml`).

Each step is reversible only with substantial effort
(force-push) or not reversible at all (PyPI upload is
write-once per version). The operator-approval boundary is
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
- ✅ Release proof in `docs/RELEASE_PROOF.md`.
- ✅ Tracked-HEAD scan clean (rows in the gate-proofs table).
- ⏳ Full-history scan blocked on operator-approved rewrite.
- ✅ "No publish/force-push happens without explicit final
  approval" — the injunction is the policy; this gate honors
  it by not running those commands.

The release is **shippable** the moment the operator runs the
plan in `docs/RELEASE_HISTORY_REWRITE.md` and approves the
publish workflow.
