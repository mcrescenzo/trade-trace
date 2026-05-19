Read-only technical-debt review complete for build/package/CI/config/Beads metadata lane.

What I did:
- Inspected all assigned in-scope files:
  - /home/hermes/code/trade-trace/pyproject.toml
  - /home/hermes/code/trade-trace/.github/workflows/workflow.yml
  - /home/hermes/code/trade-trace/.gitignore
  - /home/hermes/code/trade-trace/AGENTS.md
  - /home/hermes/code/trade-trace/CLAUDE.md
  - /home/hermes/code/trade-trace/LICENSE
  - /home/hermes/code/trade-trace/.beads/README.md
  - /home/hermes/code/trade-trace/.beads/config.yaml
  - /home/hermes/code/trade-trace/.beads/metadata.json
  - /home/hermes/code/trade-trace/.beads/.gitignore
- Probed related evidence files only where needed:
  - /home/hermes/code/trade-trace/src/trade_trace/version.py
  - /home/hermes/code/trade-trace/tests/test_smoke.py
  - /home/hermes/code/trade-trace/README.md install section
- Ran read-only/safe commands:
  - git status --short
  - git ls-files for tracked scope and generated artifacts
  - git diff -- assigned files
  - bd --readonly list --status open --json
  - PYTHONPATH=src python3 import/version probe
  - python3 TOML parse of pyproject
  - content searches for workflow triggers/build docs/version references

Side-effect caveats:
- No files were edited.
- No packages were installed.
- No tests/formatters/builds were run because this lane is read-only and the repo already has parent/other-agent working-tree modifications plus cache artifacts.
- No Beads were created or updated.
- bd was invoked with --readonly.

Workspace state observed:
- Assigned files had no diff.
- Existing unrelated modifications were present in source files, and audits/docs/audits were untracked/parent-created.
- No tracked generated artifacts matched __pycache__, .pyc, .pytest_cache, .ruff_cache, .remember, dist, build, or egg-info.

Candidate records:

1. id: build-ci-version-smoke-drift-001
title: Release CI currently runs a smoke test that asserts the old package version
domain: build-package-ci-release
debt class: config-drift / release-blocking test drift
remediation_track: bug

evidence:
- pyproject.toml:7
  snippet: version = "0.0.1rc0"
- src/trade_trace/version.py:1
  snippet: __version__ = "0.0.1rc0"
- tests/test_smoke.py:6-9
  snippet:
  def test_package_importable():
      import trade_trace

      assert trade_trace.__version__ == "0.0.1"
- .github/workflows/workflow.yml:38-39
  snippet:
  - name: Pytest
    run: pytest
- Read-only probe:
  command:
  PYTHONPATH=src python3 - <<'PY'
  import trade_trace
  print(trade_trace.__version__)
  print(trade_trace.__version__ == '0.0.1')
  PY
  output:
  0.0.1rc0
  False

carrying cost/risk:
- Any tag publish workflow that reaches pytest will fail on the smoke test before build/publish, even though pyproject.toml and src/trade_trace/version.py agree.
- The version bump process now has three version truth surfaces: pyproject, version.py, and a hard-coded test assertion. The workflow only verifies tag/pyproject/version.py in the build job, so this stale test is an untracked release gate.

bounded paydown action:
- Replace the hard-coded "0.0.1" in tests/test_smoke.py with the current release version or, preferably, make the smoke test assert importability plus consistency with src/trade_trace/version.py / package metadata rather than duplicating a literal.
- If literal version assertions are intentionally used, document the required update step in the release checklist and keep it in the workflow’s tag/version verification logic.

non-goals/boundaries:
- Do not redesign versioning, introduce dynamic versioning, or alter the release workflow beyond keeping existing gates coherent.
- Do not conflate with the broader pre-release publish workflow theme unless that existing work already covers stale tests as a release blocker.

validation command/gap:
- Suggested validation:
  - python3 -m pytest tests/test_smoke.py -q
  - python3 -m pytest -q
  - On CI path: tag dry-run or workflow run confirming pytest passes before build.
- Validation gap in this lane: did not run pytest because lane is read-only and the working tree has unrelated modifications/cache state.

risk: medium
priority: P1
confidence: high

routing justification:
- Route to build/package/CI because the failure is triggered by the publish workflow’s pytest gate and by release version metadata drift.
- It is not just a test nit: it blocks the configured release path.

why not style/speculation:
- Concrete conflicting literals exist in tracked files, and a read-only import probe confirms the assertion condition is false.

intentional-debt/false-positive check:
- pyproject.toml and version.py both intentionally say 0.0.1rc0.
- The workflow explicitly checks tag, pyproject, and version.py consistency, which supports 0.0.1rc0 as the current intended package version.
- No evidence found that tests/test_smoke.py intentionally pins a previous stable version.

duplicate notes:
- Existing open theme to avoid: “pre-release v0.0.1rc0 publish workflow.”
- This may be related, but the specific stale smoke-test assertion is a distinct release blocker. If the existing publish workflow bead already includes pytest failure from tests/test_smoke.py, dedupe into that bead; otherwise create as a narrow child/fix.

proposed bead title:
- Fix stale smoke-test version assertion blocking 0.0.1rc0 release CI

proposed bead body:
- The release workflow runs pytest before building/publishing. Current package metadata is 0.0.1rc0 in pyproject.toml and src/trade_trace/version.py, but tests/test_smoke.py still asserts trade_trace.__version__ == "0.0.1". A read-only probe showed import returns 0.0.1rc0 and the old assertion condition is false. Update the smoke test to assert version consistency without duplicating stale literals, or update the release checklist/workflow if literals remain intentional.

proposed acceptance:
- tests/test_smoke.py no longer asserts the obsolete 0.0.1 literal.
- pyproject.toml and src/trade_trace/version.py remain consistent.
- python3 -m pytest tests/test_smoke.py -q passes.
- Full CI pytest gate passes for the release workflow.

disposition recommendation:
- Accept unless duplicate coverage exists under the pre-release publish workflow work item.


2. id: ci-coverage-trigger-gap-002
title: Quality gates run only on version tags, not on pull requests or main-branch pushes
domain: build-package-ci-release
debt class: ops-deploy-debt / tooling-drift
remediation_track: maintenance

evidence:
- .github/workflows/workflow.yml:1-6
  snippet:
  name: Publish to PyPI

  on:
    push:
      tags:
        - 'v*'
- .github/workflows/workflow.yml:32-39
  snippet:
  - name: Ruff
    run: ruff check src tests

  - name: Mypy
    run: mypy src

  - name: Pytest
    run: pytest
- Search of .github/workflows for pull_request/workflow_dispatch/branches found only tag push trigger plus quality-gate commands:
  output included:
  .github/workflows/workflow.yml:4:  push:
  .github/workflows/workflow.yml:33:        run: ruff check src tests
  .github/workflows/workflow.yml:36:        run: mypy src
  .github/workflows/workflow.yml:39:        run: pytest

carrying cost/risk:
- Ruff, mypy, and pytest are configured, but the only GitHub Actions trigger is release-tag publication.
- Regressions can merge to main undetected by CI and surface only at publish time.
- The release workflow combines validation, packaging, and publishing; this increases the cost/risk of discovering routine quality failures late.

bounded paydown action:
- Split or extend CI so quality gates run on pull_request and main-branch pushes.
- Keep publish on tags, but make publish depend on the same reusable/tested quality gate or duplicate the test job safely.
- Optionally add workflow_dispatch for manual pre-release verification without publishing.

non-goals/boundaries:
- Do not change packaging metadata or PyPI publishing mechanics unless needed to share jobs.
- Do not require new tools beyond the already-declared dev extras and existing ruff/mypy/pytest commands.
- Do not address the separate stale smoke-test version assertion here except as a dependency/known blocker.

validation command/gap:
- Suggested validation:
  - GitHub Actions dry run / workflow syntax validation.
  - Open a PR or push a branch and confirm ruff, mypy, pytest run without publish permissions.
  - Confirm tag push still performs build + publish after tests.
- Validation gap in this lane: cannot exercise GitHub Actions remotely from read-only local review.

risk: medium
priority: P2
confidence: high

routing justification:
- Directly affects CI/release coverage and operational release safety.
- The fix is bounded to .github/workflows/workflow.yml.

why not style/speculation:
- The absence of pull_request/main triggers is directly visible in the only workflow file.
- The configured quality gates are real and currently only run in the publish path.

intentional-debt/false-positive check:
- It may be intentional for an early project to run CI only at release, but the presence of ruff/mypy/pytest gates and a publish workflow means regressions are currently detected at the most expensive point.
- No separate CI workflow was found in .github/workflows during this lane.

duplicate notes:
- Not the same as the existing “pre-release v0.0.1rc0 publish workflow” theme unless that existing bead explicitly includes non-release CI coverage.
- If a parent audit already has a “add PR CI” candidate, dedupe there.

proposed bead title:
- Run ruff, mypy, and pytest on PR/main CI instead of only during tag publish

proposed bead body:
- The only GitHub Actions workflow is “Publish to PyPI” and it triggers only on push tags matching v*. It contains ruff, mypy, and pytest gates, but they do not run on pull requests or normal main pushes. Add PR/main CI coverage or split the test job into a reusable quality workflow so routine regressions fail before release tagging, while keeping PyPI publish restricted to tags/environment.

proposed acceptance:
- A workflow triggers on pull_request and main push and runs ruff check src tests, mypy src, and pytest.
- Tag-based publish remains restricted to v* tags and PyPI environment/id-token permissions.
- Publish job still depends on successful tests.
- Workflow syntax validates.

disposition recommendation:
- Accept as maintenance debt unless already tracked in a broader CI hardening bead.


3. id: agent-doc-contract-drift-003
title: Agent instruction files contain duplicated/generated Beads boilerplate, mandatory push rules, and placeholder build commands
domain: repo config / Beads metadata / docs-contract-drift
debt class: docs-contract-drift / config-drift
remediation_track: maintenance

evidence:
- AGENTS.md:3 and AGENTS.md:39-44 duplicate Beads intro/quick reference:
  snippets:
  line 3: This project uses **bd** (beads) for issue tracking. Run `bd prime` for full workflow context.
  line 39: <!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
  line 42: This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.
- AGENTS.md:61-83 imposes universal push semantics:
  snippets:
  line 61: **When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.
  line 68: 4. **PUSH TO REMOTE** - This is MANDATORY:
  line 80: - Work is NOT complete until `git push` succeeds
  line 82: - NEVER say "ready to push when you are" - YOU must push
- CLAUDE.md:53-61 has placeholder build/test commands:
  snippet:
  ## Build & Test

  _Add your build and test commands here_

  ```bash
  # Example:
  # npm install
  # npm test
  ```
- pyproject.toml:19-23 and .github/workflows/workflow.yml:32-39 show actual Python quality commands exist:
  snippets:
  dev = [
      "pytest>=8",
      "ruff>=0.5",
      "mypy>=1.10",
  ]
  and workflow runs ruff check src tests, mypy src, pytest.

carrying cost/risk:
- Agents reading CLAUDE.md get npm placeholder commands in a Python package that already has real ruff/mypy/pytest gates.
- AGENTS.md and CLAUDE.md both contain generated Beads session-completion rules that require mutating/pushing. That can conflict with delegated read-only audit lanes, local-only review tasks, or environments where pushing is forbidden.
- Duplicated Beads boilerplate increases drift risk when Beads integration text changes.

bounded paydown action:
- Consolidate agent instructions so AGENTS.md and CLAUDE.md point to one authoritative Beads workflow block or clarify generated sections are subordinate to task-specific instructions.
- Replace placeholder npm build/test section in CLAUDE.md with actual commands:
  - pip install -e ".[dev]"
  - ruff check src tests
  - mypy src
  - pytest
- Scope mandatory push language to normal implementation sessions only, with explicit exception for read-only/audit/delegated tasks and user/system instructions that prohibit mutation.

non-goals/boundaries:
- Do not remove Beads usage.
- Do not change Beads database contents.
- Do not redesign agent workflow; only remove contradictory/stale repo-local instructions and placeholders.

validation command/gap:
- Suggested validation:
  - Manual read-through of AGENTS.md and CLAUDE.md confirms no placeholder npm commands remain.
  - Confirm Beads instructions remain present and accurate.
  - Confirm read-only/task-specific override language exists.
- Validation gap in this lane: no edits performed, so validation is proposed only.

risk: low-to-medium
priority: P3
confidence: high

routing justification:
- This is repo config / agent metadata debt, not product code.
- It affects future agent operations and can cause accidental prohibited side effects or wrong validation commands.

why not style/speculation:
- The files contain concrete placeholder commands for the wrong ecosystem and unconditional push instructions that conflict with common delegated/read-only task modes.
- The actual Python commands are present in pyproject/workflow, proving drift.

intentional-debt/false-positive check:
- The generated Beads block is likely intentional, but duplication plus unscoped “must push” rules are risky when task-level instructions prohibit mutation.
- CLAUDE.md placeholders appear to be template residue, not intentional documentation.

duplicate notes:
- Existing open agent-ready docs themes cover AGENT_GUIDE/client docs/README truthfulness, not specifically AGENTS.md/CLAUDE.md repo instruction hygiene.
- If parent considers all agent docs under the agent-ready docs QC bead, route as a sub-finding rather than a separate bead.

proposed bead title:
- Clean up AGENTS.md/CLAUDE.md agent workflow drift and Python quality-gate placeholders

proposed bead body:
- AGENTS.md duplicates Beads intro/quick-reference material and includes unconditional session-completion rules requiring git/bd pushes. CLAUDE.md contains generated Beads push rules plus a placeholder “Build & Test” section with npm examples, while pyproject/workflow define the real Python dev gates: pip install -e ".[dev]", ruff check src tests, mypy src, pytest. Consolidate or scope the generated Beads workflow so read-only/delegated tasks can obey stricter instructions, and replace placeholder build/test commands with the real project commands.

proposed acceptance:
- CLAUDE.md lists the real Python build/test commands and no npm placeholder remains.
- AGENTS.md and CLAUDE.md avoid duplicate/conflicting Beads boilerplate or clearly identify one authoritative block.
- Mandatory push/session-completion wording is scoped to normal mutating implementation sessions and explicitly yields to read-only/user/system constraints.
- Beads usage instructions remain available.

disposition recommendation:
- Accept as low-risk maintenance debt, or attach to existing agent-ready docs QC if that bead is expanded to include AGENTS.md/CLAUDE.md.


Skipped / not recommended as Beads:
- pyproject.toml license table uses license = { text = "MIT" }. This may be modernized eventually, but current evidence does not show a concrete carrying cost for this project; rejected as packaging style/modernization.
- Missing classifiers/project.urls in pyproject.toml. Useful polish for publishing, but no concrete failure or risk found; rejected as release metadata enhancement unless a publish policy requires it.
- .gitignore broad *.db and *.sqlite patterns. Potentially broad, but current git ls-files probe did not show tracked generated artifacts and no concrete fixture conflict was found; rejected as speculative.
- .beads/config.yaml export.auto: false. Could affect backup/export behavior, but no concrete mismatch was proven from assigned files; rejected as insufficient evidence.
- .beads/README.md generic install instructions. Generic but not clearly harmful; rejected as low-value doc polish.
- LICENSE looked consistent with pyproject MIT declaration; no candidate.
- .beads/metadata.json and .beads/.gitignore looked internally consistent; no candidate.

Coverage accounting:
- Assigned files opened: 10/10.
- Related evidence files opened/probed: 3.
- Commands/searches run:
  - git status --short
  - git ls-files scoped checks
  - git diff on assigned files
  - bd --readonly list --status open --json
  - python3 TOML parse
  - PYTHONPATH=src python3 import/version probe
  - content searches for version/build/workflow triggers/docs references
- Grouped/skipped areas:
  - Full source/test behavior outside release/config evidence was not audited except for version.py and tests/test_smoke.py.
  - Beads internal runtime database contents were not mutated; only open issue metadata was read with bd --readonly.
  - Parent-created audit artifacts and unrelated modified source files were not reviewed for this lane.
- Files created or modified: none.
- Issues encountered:
  - `python` command was absent; retried successfully with `python3`.
  - Working tree had unrelated modifications/untracked audit artifacts before this lane; I did not modify them.