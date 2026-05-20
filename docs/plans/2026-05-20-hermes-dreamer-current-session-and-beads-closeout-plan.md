# Hermes/Dreamer Current-Session Resolver and Beads Closeout Guardrail Implementation Plan

> **For Hermes:** Use the `subagent-driven-development` skill to implement this plan task-by-task. For any Hermes Agent core change, load `hermes-agent`; for Beads operations, load `beads-cli-safety-and-sync`; for final review, consult the advisor with the evidence packet described below.

**Goal:** Implement two related hardening proposals discovered during Trade Trace agent-workbench planning: (P1) make Beads post-compaction closeout proof explicit and non-duplicative, and (P2) make Dreamer `/dreamer-review current` resolve the invoking durable Hermes transcript deterministically instead of relying on newest-file heuristics or manual session sorting.

**Architecture:** P1 is a documentation/skill consolidation, not new runtime behavior. P2 is a runtime + Dreamer workspace change: a shared Dreamer session resolver must resolve exactly one transcript path, while Hermes core must pass the durable session id/path into slash-skill expansion, especially in gateway contexts where today only a routing key is available at expansion time.

**Tech Stack / Repos:**
- Trade Trace planning artifact location: `/home/hermes/code/trade-trace/docs/plans/`
- Hermes Agent core: `/home/hermes/.hermes/hermes-agent`
- Dreamer workspace: `/home/hermes/.hermes/profiles/dreamer/dreamer-workspace`
- Skills: `/home/hermes/.hermes/skills/software-development/...`
- Beads project tracking for this artifact: `trade-trace-8fe8`

---

## 0. Investigation Summary

### User-facing problem

The previous agent feedback said the product loop is conceptually strong, but agents still have too much to infer. The immediate implementation-plan follow-up identified two supporting infrastructure improvements:

1. **Beads closeout proof after compaction:** resumed agents must not treat a context-compaction summary as proof that a Beads graph is healthy, execution-ready, or pushed.
2. **Dreamer current-session targeting:** `/dreamer-review current` should review the invoking session, not the newest recent session, a Dreamer profile session, an advisor/subagent session, or a gateway routing key.

### Evidence gathered

#### P1 evidence: guardrail already partially exists

- Canonical-ish reference exists:
  - `/home/hermes/.hermes/skills/software-development/beads-program-planning/references/context-compaction-closeout-proof.md`
  - It says a context-compaction summary is “a map, not proof.”
  - It defines a minimum live proof set and local-vs-remote completion wording.
- Existing second-review closeout doc links the rule:
  - `/home/hermes/.hermes/skills/software-development/beads-program-planning/references/existing-epic-second-review-closeout.md`
- Redundant overlapping doc also exists:
  - `/home/hermes/.hermes/skills/software-development/beads-program-planning/references/post-compaction-closeout-live-proof.md`
- Search did **not** find a direct reference from:
  - `/home/hermes/.hermes/skills/software-development/beads-program-planning/SKILL.md`

Conclusion: P1 should be treated as consolidation/surfacing, not net-new design.

#### P2 evidence: Dreamer current-session resolver is not implemented

- Manual Dreamer review helper has a local resolver:
  - `/home/hermes/.hermes/profiles/dreamer/dreamer-workspace/bin/dreamer_session_review.py`
  - `resolve_session()` currently lives in that file.
  - It rejects `--session-id current` and `${HERMES_SESSION_ID}`.
- Deterministic Dreamer intake helper only supports explicit `--session-path` or broad scan:
  - `/home/hermes/.hermes/profiles/dreamer/dreamer-workspace/bin/dreamer_memory_qa.py`
  - It has no `--current-session` or `--session-id` path.
- No shared resolver module currently exists:
  - no `bin/dreamer_session_resolver.py`
- Existing Dreamer docs already describe the intended behavior:
  - `/home/hermes/.hermes/skills/software-development/dreamer-review/references/current-session-resolver-implementation-plan-2026-05-20.md`
  - `/home/hermes/.hermes/skills/software-development/dreamer-review/references/session-targeting-invariants.md`
  - `/home/hermes/.hermes/skills/software-development/dreamer-review/references/current-session-targeting-resolver.md`

Conclusion: P2 needs implementation, not only documentation.

#### Hermes runtime evidence

- CLI path is mostly okay:
  - `/home/hermes/.hermes/hermes-agent/cli.py:8250-8252`
  - `build_skill_invocation_message(..., task_id=self.session_id)` passes the durable CLI session id.
- Live environment during investigation had a real durable session id:
  - `HERMES_SESSION_ID=20260520_134843_1d1f4e`
  - matching path: `/home/hermes/.hermes/sessions/session_20260520_134843_1d1f4e.json`
- Gateway path is not okay:
  - `/home/hermes/.hermes/hermes-agent/gateway/run.py:7443-7445`
  - `build_skill_invocation_message(..., task_id=_quick_key)` passes `_quick_key`.
  - `_quick_key` is computed earlier at `/home/hermes/.hermes/hermes-agent/gateway/run.py:6535` and is a routing/session key.
  - Durable session creation happens later at `/home/hermes/.hermes/hermes-agent/gateway/run.py:7851` via `session_entry = self.session_store.get_or_create_session(source)`.
- Session context is incomplete for this use:
  - `/home/hermes/.hermes/hermes-agent/gateway/session_context.py` defines `_SESSION_ID`.
  - `set_session_vars()` does not accept/set `session_id`.
  - `/home/hermes/.hermes/hermes-agent/gateway/run.py:_set_session_env()` passes `session_key`, but not durable `session_id`.
- Agent init already knows the transcript path shape:
  - `/home/hermes/.hermes/hermes-agent/agent/agent_init.py:893-904`
  - sets `HERMES_SESSION_ID`
  - sets `agent.session_log_file = ~/.hermes/sessions/session_<session_id>.json`
- TUI likely works but still needs regression tests:
  - TUI generates session IDs with timestamp/uuid shape.
  - Existing tests cover compression reanchor in `/home/hermes/.hermes/hermes-agent/tests/test_lazy_session_regressions.py:129-203`.

Conclusion: P2 must include Hermes core plumbing. A Dreamer-only resolver would still fail for gateway slash commands.

#### Pre-existing dirty state caveat

At investigation time, Hermes core had unrelated dirty files:

```text
/home/hermes/.hermes/hermes-agent/plugins/memory/hindsight/__init__.py
/home/hermes/.hermes/hermes-agent/tests/plugins/memory/test_hindsight_provider.py
```

Do not touch, stage, revert, or “clean up” these files as part of this plan unless Michael explicitly authorizes it. They are unrelated to this implementation.

---

## 1. Advisor Input Summary

The advisor agreed with the core direction and refined the plan:

- Treat P1 as consolidation/surfacing, not new design.
- Avoid two competing Beads closeout guardrail docs.
- For P2, separate resolver semantics from call-site plumbing.
- Gateway must pass durable transcript `session_id`, not `_quick_key`.
- Do not teach Dreamer that a routing key is a valid transcript id.
- Extend session context/env to expose durable `HERMES_SESSION_ID` and optionally `HERMES_SESSION_PATH`.
- Add tests that prove gateway slash expansion works, not just isolated resolver unit tests.
- Add a final evidence-based advisor review before claiming implementation complete.

---

## 2. Non-Goals

- Do not implement Trade Trace product features in this plan.
- Do not rewrite Dreamer into a mutating system. Dreamer remains artifact-only/proposal-only.
- Do not broaden Dreamer nightly intake behavior.
- Do not infer current session from newest session file.
- Do not copy raw transcript content into Dreamer artifacts.
- Do not touch unrelated dirty Hermes core files.
- Do not force `bd dolt push`, remote Beads publication, or Git remote operations unless the active repo policy or Michael explicitly requires them for the implementation session.

---

## 3. P1 Implementation: Beads Post-Compaction Closeout Proof Guardrail

### Desired behavior

Any agent resuming Beads planning/materialization/refresh/closeout after compaction or handoff must rerun live proof before claiming graph health, execution-readiness, local persistence, or remote publication.

A compaction summary may orient the agent. It is not proof.

### Task 1: Consolidate canonical Beads compaction-proof docs

**Objective:** Ensure there is one authoritative guardrail reference.

**Files:**
- Modify: `/home/hermes/.hermes/skills/software-development/beads-program-planning/references/context-compaction-closeout-proof.md`
- Modify or remove/replace: `/home/hermes/.hermes/skills/software-development/beads-program-planning/references/post-compaction-closeout-live-proof.md`

**Steps:**
1. Read both existing files.
2. Move any unique useful wording from `post-compaction-closeout-live-proof.md` into `context-compaction-closeout-proof.md`.
3. Either:
   - replace `post-compaction-closeout-live-proof.md` with a short pointer to the canonical file, or
   - remove it if no skill/reference links require it.
4. Search all skills for references to the duplicate filename before deleting.

**Verification:**

```bash
rg "post-compaction-closeout-live-proof|context-compaction-closeout-proof" /home/hermes/.hermes/skills/software-development
```

Expected:
- one canonical doc contains the full rule;
- duplicate doc is either absent or clearly says it is superseded by the canonical doc;
- no broken references remain.

### Task 2: Surface the guardrail in the main Beads planning skill

**Objective:** Ensure agents see the guardrail without knowing the reference file exists.

**Files:**
- Modify: `/home/hermes/.hermes/skills/software-development/beads-program-planning/SKILL.md`

**Steps:**
1. Find the final verification/closeout section in `SKILL.md`.
2. Add a concise mandatory note:
   - after compaction or resumed handoff, reread live Beads state;
   - do not close from summary alone;
   - use `references/context-compaction-closeout-proof.md`.
3. Keep the wording short; the detailed proof set belongs in the canonical reference.

**Verification:**

```bash
python3 - <<'PY'
from pathlib import Path
p = Path('/home/hermes/.hermes/skills/software-development/beads-program-planning/SKILL.md')
text = p.read_text()
assert 'context-compaction-closeout-proof.md' in text
assert 'summary' in text.lower() and 'proof' in text.lower()
print('ok')
PY
```

Expected: `ok`.

### Task 3: Link from adjacent closeout skills where appropriate

**Objective:** Prevent agents using nearby Beads closeout skills from missing the rule.

**Files to inspect first:**
- `/home/hermes/.hermes/skills/software-development/beads-sync-closeout/SKILL.md`
- `/home/hermes/.hermes/skills/software-development/beads-program-orchestrator/SKILL.md`
- `/home/hermes/.hermes/skills/software-development/beads-closeout-proof/SKILL.md`

**Steps:**
1. Read each candidate skill.
2. Add only short pointers where the skill genuinely covers resumed Beads closeout after compaction.
3. Do not duplicate the proof checklist in multiple files.

**Verification:**

```bash
rg "context-compaction-closeout-proof" /home/hermes/.hermes/skills/software-development/beads-*
```

Expected: only relevant skills link to the canonical reference.

### P1 acceptance criteria

- `beads-program-planning/SKILL.md` directly points to the compaction closeout proof rule.
- There is only one canonical proof checklist.
- Duplicate/overlapping docs are removed or clearly forwarded.
- The canonical reference distinguishes:
  - read-only reviews;
  - local Beads proof;
  - Dolt remote publication;
  - Git remote publication;
  - code-test/build proof when code changed.
- No remote publication claims are allowed without actual verified remote commands.

---

## 4. P2 Implementation: Dreamer Deterministic Current-Session Resolver

## 4.1 Shared resolver module

### Desired behavior

Dreamer helpers should resolve “current” to exactly one durable Hermes transcript. They should never infer from newest files when current-session metadata is missing.

### Task 4: Create shared resolver module

**Objective:** Centralize exact-session resolution for Dreamer helpers.

**Files:**
- Create: `/home/hermes/.hermes/profiles/dreamer/dreamer-workspace/bin/dreamer_session_resolver.py`
- Test: `/home/hermes/.hermes/profiles/dreamer/dreamer-workspace/tests/test_session_resolver.py`

**Resolver API sketch:**

```python
@dataclass(frozen=True)
class ResolvedSession:
    session_id: str
    profile: str
    path: Path
    basename: str
    path_sha256: str
    size_bytes: int
    mtime: str
    source: str  # explicit_path | explicit_id | env_path | env_id

class SessionResolutionError(Exception):
    def __init__(self, code: str, message: str, candidates: list[dict[str, str]] | None = None): ...
```

**Core functions:**

```python
def discover_session_roots(base_home: Path | None = None) -> dict[str, Path]: ...

def resolve_session_target(
    *,
    session_path: str | None = None,
    session_id: str | None = None,
    profile: str | None = None,
    current_session: bool = False,
    allow_any_path: bool = False,
    env: Mapping[str, str] | None = None,
    base_home: Path | None = None,
) -> ResolvedSession: ...
```

**Resolution precedence:**
1. Explicit `--session-path`
2. Explicit real `--session-id` plus optional `--profile`
3. `--current-session` via env path:
   - `DREAMER_TARGET_SESSION_PATH`
   - `HERMES_SESSION_PATH`
4. `--current-session` via env id:
   - `DREAMER_TARGET_SESSION_ID`
   - `HERMES_SESSION_ID`
5. Fail closed.

**Reject:**
- bare `current` unless `current_session=True`;
- `${HERMES_SESSION_ID}` or other unresolved template literals;
- missing transcript files;
- session ids that resolve to more than one profile without explicit `--profile`;
- gateway routing-key-looking values when no transcript file exists;
- newest-file fallback.

**Sanitized diagnostics:**
- Candidates may include profile, basename, size, mtime, path hash.
- Do not include transcript content, message bodies, tool args, tool output, or raw snippets.

### Task 5: Add resolver unit tests

**Objective:** Lock down resolver semantics before integrating scripts.

**Files:**
- Create: `/home/hermes/.hermes/profiles/dreamer/dreamer-workspace/tests/test_session_resolver.py`

**Test cases:**
1. `--session-path` resolves one file.
2. `--session-id --profile` resolves one file.
3. `--session-id` with duplicate matches across profiles fails with `ambiguous_session_id`.
4. missing id/path fails with `session_not_found`.
5. bare `current` fails without `current_session=True`.
6. `${HERMES_SESSION_ID}` fails as unresolved template.
7. `--current-session` resolves from env path.
8. `--current-session` resolves from env id.
9. env path takes precedence over env id.
10. sanitized error does not contain raw transcript text.

**Verification:**

```bash
cd /home/hermes/.hermes/profiles/dreamer/dreamer-workspace
python3 -m pytest tests/test_session_resolver.py -q
```

Expected: all tests pass.

## 4.2 Integrate resolver into Dreamer scripts

### Task 6: Update manual review helper

**Objective:** Replace local resolver logic in `dreamer_session_review.py` with shared resolver.

**Files:**
- Modify: `/home/hermes/.hermes/profiles/dreamer/dreamer-workspace/bin/dreamer_session_review.py`
- Test: add/extend tests as needed.

**Steps:**
1. Import `resolve_session_target` from `dreamer_session_resolver.py`.
2. Replace local `resolve_session()` body with shared resolver call or remove local function entirely.
3. Add CLI flag:

```python
ap.add_argument('--current-session', action='store_true')
```

4. Keep existing flags:
   - `--session-path`
   - `--session-id`
   - `--profile`
   - `--allow-any-session-path` for controlled fixtures only.
5. Ensure dry-run output includes exactly one selected target with sanitized metadata.

**Verification:**

```bash
cd /home/hermes/.hermes/profiles/dreamer/dreamer-workspace
python3 bin/dreamer_session_review.py --session-id current --dry-run
```

Expected: fail closed with clear error unless `--current-session` is supplied and durable env is present.

```bash
HERMES_SESSION_ID=<known-id> python3 bin/dreamer_session_review.py --current-session --dry-run
```

Expected: resolves exactly one session or fails closed if the known id has no transcript.

### Task 7: Update deterministic memory QA helper

**Objective:** Let current-session Dreamer intake use exact target resolution rather than broad 24-hour scan.

**Files:**
- Modify: `/home/hermes/.hermes/profiles/dreamer/dreamer-workspace/bin/dreamer_memory_qa.py`
- Test: `/home/hermes/.hermes/profiles/dreamer/dreamer-workspace/tests/test_memory_qa.py`

**Steps:**
1. Add CLI flags:

```python
p.add_argument('--session-id')
p.add_argument('--profile')
p.add_argument('--current-session', action='store_true')
```

2. Use shared resolver when any exact target flag is set:
   - `--session-path`
   - `--session-id`
   - `--current-session`
3. Preserve broad/no-target window scan exactly as today.
4. In exact-target mode, mark selected session as direct.
5. Include selected target metadata in report without raw content.

**Verification:**

```bash
cd /home/hermes/.hermes/profiles/dreamer/dreamer-workspace
python3 -m pytest tests/test_memory_qa.py -q
python3 bin/dreamer_memory_qa.py --current-session --output-format json
```

Expected:
- tests pass;
- `--current-session` selects exactly one session if env is valid;
- no fallback to broad scan.

### Task 8: Preserve artifact-only guarantees

**Objective:** Ensure resolver integration does not make Dreamer mutate memory, skills, or raw transcript artifacts.

**Files:**
- Modify tests in Dreamer workspace as needed.

**Required assertions:**
- `raw_content_copied == false`
- `memory_changed == false`
- `skills_changed == false`
- selected session count is exactly 1 in current-session mode
- `review-metadata.json` uses path hash/basename, not raw transcript content

**Verification:**

```bash
cd /home/hermes/.hermes/profiles/dreamer/dreamer-workspace
python3 bin/dreamer_memory_qa.py --current-session --write-artifacts --output-format markdown
python3 bin/validate_workspace.py --check
```

Expected:
- validation passes;
- artifacts contain sanitized target metadata only.

---

## 5. Hermes Core Runtime Plumbing

## 5.1 Gateway slash expansion must use durable session ids

### Current failure mode

In gateway slash handling, the skill command is expanded before durable `session_entry` is created:

```python
# gateway/run.py currently
msg = build_skill_invocation_message(
    cmd_key, user_instruction, task_id=_quick_key
)
```

`_quick_key` is a routing/session key, not necessarily a durable transcript id. Dreamer must not learn to treat it as valid.

### Task 9: Add a gateway helper to resolve durable session info before skill expansion

**Objective:** Ensure slash-skill template expansion has durable session id/path.

**Files:**
- Modify: `/home/hermes/.hermes/hermes-agent/gateway/run.py`
- Test: relevant gateway/slash tests under `/home/hermes/.hermes/hermes-agent/tests/`

**Implementation options:**

Preferred option: resolve/create `session_entry` before skill expansion in a small helper that preserves topic recovery and does not break the running-agent sentinel.

Sketch:

```python
def _resolve_invocation_session_entry_for_skill(self, source):
    # Apply the same topic-recovery semantics needed for session identity.
    recovered = self._recover_telegram_topic_thread_id(source)
    if recovered is not None:
        source = dataclasses.replace(source, thread_id=recovered)
    entry = self.session_store.get_or_create_session(source)
    return source, entry
```

Then pass explicit template variables to skill expansion, if supported, or extend `build_skill_invocation_message()` to accept them:

```python
msg = build_skill_invocation_message(
    cmd_key,
    user_instruction,
    task_id=session_entry.session_id,
    template_vars={
        'session_id': session_entry.session_id,
        'session_path': str(self.session_store_or_agent_session_path(session_entry.session_id)),
        'session_key': session_entry.session_key,
    },
)
```

If `build_skill_invocation_message()` cannot accept `template_vars` today, add that capability in the smallest backward-compatible way.

**Do not:**
- pass `_quick_key` as the durable id;
- change global routing semantics;
- let current-session resolve from newest file;
- duplicate session creation in a way that rotates/reset sessions incorrectly.

### Task 10: Add gateway regression test for skill expansion session id

**Objective:** Prove the gateway path expands slash skills with durable transcript id.

**Files:**
- Add/modify Hermes core tests, likely near skill/slash command tests.

**Test shape:**
1. Create a fake source whose routing key differs from durable session id.
2. Configure a skill command template that includes the current session id variable or uses `task_id` in the generated invocation.
3. Run the gateway slash handling path far enough to call `build_skill_invocation_message()`.
4. Assert generated message contains durable `session_entry.session_id`, not `_quick_key`.

**Verification:**

```bash
cd /home/hermes/.hermes/hermes-agent
python3 -m pytest <new-or-existing-gateway-skill-test> -q
```

Expected: test fails on current code and passes after the fix.

## 5.2 Expose durable session id/path in session context

### Task 11: Extend session context variables

**Objective:** Make `HERMES_SESSION_ID` and optionally `HERMES_SESSION_PATH` available in gateway task context.

**Files:**
- Modify: `/home/hermes/.hermes/hermes-agent/gateway/session_context.py`
- Modify: `/home/hermes/.hermes/hermes-agent/gateway/run.py`
- Test: `/home/hermes/.hermes/hermes-agent/tests/...`

**Steps:**
1. Add optional `session_id` parameter to `set_session_vars()`.
2. Set `_SESSION_ID` in the returned tokens list.
3. Clear `_SESSION_ID` in `clear_session_vars()`.
4. Optionally add `_SESSION_PATH` and `HERMES_SESSION_PATH` to `_VAR_MAP`.
5. Update `_set_session_env()` to pass `context.session_id` or the known `session_entry.session_id`.
6. Ensure CLI fallback via `os.environ` continues to work.

**Verification:**

```bash
cd /home/hermes/.hermes/hermes-agent
python3 -m pytest tests/run_agent/test_session_id_env.py -q
```

Add a gateway-specific test proving `get_session_env('HERMES_SESSION_ID')` returns the durable id in gateway context.

## 5.3 Expose transcript path where practical

### Task 12: Add current session path support

**Objective:** Let Dreamer resolve `--current-session` from a path directly when available.

**Files:**
- Modify Hermes core where env/template variables are set.
- Possibly modify `agent/agent_init.py` if centralizing path exposure there.

**Path convention:**

```text
<resolved Hermes home>/sessions/session_<session_id>.json
```

**Steps:**
1. Add `HERMES_SESSION_PATH` to CLI runtime env if not already present.
2. Add `HERMES_SESSION_PATH` to gateway context/env after durable id is known.
3. Prefer passing path as a template variable to skills over relying only on process env.
4. Keep env lower precedence than explicit CLI flags in Dreamer resolver.

**Verification:**
- CLI: running a tool/script inside a session can read `HERMES_SESSION_PATH` and the file exists after transcript persistence.
- Gateway: skill expansion receives a path matching the durable id.
- Dreamer resolver accepts path but still validates existence and root safety.

## 5.4 TUI current-session regression coverage

### Task 13: Add or extend TUI tests

**Objective:** Ensure TUI current-session targeting remains valid before and after compression.

**Files:**
- Modify: `/home/hermes/.hermes/hermes-agent/tests/test_lazy_session_regressions.py`
- Or add a new TUI slash/current-session test file.

**Steps:**
1. Reuse existing compression reanchor fixture pattern.
2. Assert skill expansion/session context sees pre-compression durable id before compression.
3. Simulate compression rotation.
4. Assert later current-session resolution sees post-compression durable id.

**Verification:**

```bash
cd /home/hermes/.hermes/hermes-agent
python3 -m pytest tests/test_lazy_session_regressions.py -q
```

Expected: existing tests continue to pass and new current-session assertions pass.

---

## 6. Dreamer Skill and Documentation Update

### Task 14: Update `dreamer-review` skill instructions

**Objective:** Make the new current-session flow the default operator guidance.

**Files:**
- Modify: `/home/hermes/.hermes/skills/software-development/dreamer-review/SKILL.md`
- Possibly modify:
  - `references/current-session-resolver-implementation-plan-2026-05-20.md`
  - `references/session-targeting-invariants.md`
  - `references/current-session-targeting-resolver.md`

**Steps:**
1. Replace “future resolver” wording with the implemented command once P2 lands:

```bash
python3 bin/dreamer_memory_qa.py --current-session --write-artifacts --output-format markdown
```

2. Keep explicit `--session-path` as the manual escape hatch.
3. State that broad/default scan remains only for nightly or explicitly multi-session intake.
4. State that current means the invoking durable Hermes transcript.

**Verification:**

```bash
rg "--current-session|future resolver|newest" /home/hermes/.hermes/skills/software-development/dreamer-review
```

Expected:
- current-session docs describe the implemented resolver;
- no stale wording tells agents to manually sort newest session files as normal flow.

---

## 7. End-to-End Verification Plan

### Dreamer workspace verification

```bash
cd /home/hermes/.hermes/profiles/dreamer/dreamer-workspace
python3 -m pytest tests -q
python3 bin/validate_workspace.py --check
```

Expected:
- tests pass;
- workspace validator passes.

### Dreamer current-session smoke

Use a known session id/path in controlled mode first:

```bash
cd /home/hermes/.hermes/profiles/dreamer/dreamer-workspace
HERMES_SESSION_ID=<known-session-id> \
python3 bin/dreamer_memory_qa.py --current-session --write-artifacts --output-format markdown
```

Expected:
- exactly one selected session;
- no raw content copied;
- no memory/skill mutations;
- report identifies target session by id/path hash/basename.

### Hermes core tests

Run targeted tests first:

```bash
cd /home/hermes/.hermes/hermes-agent
python3 -m pytest tests/run_agent/test_session_id_env.py -q
python3 -m pytest tests/test_lazy_session_regressions.py -q
python3 -m pytest <new-gateway-skill-session-id-test> -q
```

Then run broader relevant suites if local time permits:

```bash
python3 -m pytest tests/agent tests/run_agent tests/test_lazy_session_regressions.py -q
```

### Live slash-path smoke

After Hermes core changes are installed/restarted in the active runtime:

1. Trigger `/dreamer-review current` from CLI.
2. Trigger equivalent from a gateway surface if available.
3. Verify the Dreamer report selected the invoking durable transcript, not newest file and not advisor/subagent sessions.

The live slash-path smoke is required because unit tests alone do not prove runtime deployment/restart behavior.

---

## 8. Advisor Closeout Gate

Before claiming implementation complete, consult the advisor with a concrete closeout packet. Do not ask “does this look good?”

### Required advisor packet

Include:
- original user request and refined implementation goal;
- exact files changed;
- P1 canonical doc readback and duplicate-disposition summary;
- P2 resolver API summary;
- Dreamer test outputs;
- Hermes core test outputs;
- live slash-path smoke result or explicit reason it was not possible;
- artifact-only guarantees for Dreamer;
- dirty-tree status for each touched repo;
- explicit completion claim you plan to make to Michael.

### Required advisor verdict

Ask for one of:
- `APPROVED`: implementation is complete enough to report;
- `REVISE`: blockers or must-fix issues remain.

If advisor returns `REVISE`, apply or explicitly reject each recommendation with evidence-backed rationale, rerun affected tests/readbacks, and ask for a final check again before claiming completion.

If advisor tool fails, times out, or is unavailable, do not treat that as approval. Use an independent read-only reviewer/delegate as fallback and label it as fallback review.

---

## 9. Rollout Sequence

1. **P1 docs consolidation first**
   - low risk;
   - immediately improves Beads closeout behavior;
   - prevents duplicate doctrine drift.
2. **Dreamer shared resolver module + unit tests**
   - establish exact semantics before touching scripts.
3. **Dreamer script integrations**
   - manual review helper;
   - memory QA helper;
   - artifact-only tests.
4. **Hermes core session plumbing**
   - gateway durable session id before skill expansion;
   - session context/env id/path;
   - TUI regression coverage.
5. **Dreamer skill docs update**
   - only after code behavior exists.
6. **End-to-end smoke and advisor closeout**
   - prove actual runtime behavior, not just docs or isolated units.

---

## 10. Final Acceptance Criteria

P1 is complete when:
- `beads-program-planning/SKILL.md` surfaces the post-compaction proof rule.
- one canonical reference owns the proof checklist.
- duplicate references are removed or forwarded.
- local-vs-remote/push wording is explicit and truthful.

P2 is complete when:
- Dreamer has a shared resolver module.
- `dreamer_session_review.py` and `dreamer_memory_qa.py` both use it.
- `--current-session` resolves only from durable env/path/id signals.
- broad/no-target Dreamer intake behavior remains unchanged.
- Gateway slash expansion passes durable transcript id/path, not `_quick_key`.
- CLI current-session behavior still works.
- TUI current-session behavior works before and after compression reanchor.
- Unit tests and targeted integration tests pass.
- A live current-session smoke selects exactly one invoking transcript.
- Dreamer artifacts remain sanitized and mutation-free.
- Advisor closeout returns `APPROVED`, or all `REVISE` items are resolved and re-reviewed.

---

## 11. Implementation Safety Notes

- Keep explicit CLI args higher precedence than env.
- Keep env higher precedence than any fallback discovery.
- Never implement a newest-file fallback for “current.”
- Never accept a gateway routing key as a transcript id unless a matching transcript file exists and root validation passes.
- Avoid broad changes to Hermes routing/session reset behavior.
- Protect unrelated dirty Hermes core files.
- Keep Dreamer proposal artifacts private/sanitized.
- For Beads and Git closeout, distinguish local DB/readback, Dolt remote publication, source Git commit, and source Git push.
