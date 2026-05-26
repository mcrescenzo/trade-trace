# Agent Instructions

This file is the agent-facing entry point. See
[`CLAUDE.md`](./CLAUDE.md) for the same beads-integration block plus
the project-specific build/test/architecture pointers; both files are
kept in sync by `bd init`'s generated section below. The
non-interactive-shell guidance in the next section is unique to this
file and is the only AGENTS.md-specific content.

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**
```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:ca08a54f -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

## Session Completion

**Scope (bead trade-trace-9zy / DEBT-005)**: this protocol applies to
**mutating, authorized work sessions**. Sessions that are explicitly
read-only or no-push are exempt as documented under "When NOT to push"
below. Any session that produces commits defaults to the full
mandatory workflow.

**When ending a mutating work session**, you MUST complete ALL steps
below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW (mutating sessions only):**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   bd dolt push
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES (mutating sessions only):**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds

**When NOT to push (exempt session lanes):**

The mandatory workflow does NOT apply to:

- Read-only audit / investigation sessions where the user
  explicitly instructed "do not modify anything", "audit only",
  "read-only review", or similar. Don't open Beads with
  `bd update --claim` or `bd close`; don't commit; don't push.
- Delegated subagent runs where a parent agent retains commit/push
  authority. The subagent reports findings; the parent decides
  what lands on `main`.
- Sessions with an explicit user "don't push" directive.
- Pre-existing pre-flight failures unrelated to the session's
  work: stop and ask before pushing unrelated state forward.

In every exempt case end the session with a written handoff
describing what was found, what was changed (if anything), and why
the push step was skipped. Do not silently skip the push step in a
mutating session — that's a workflow violation, not an exemption.
<!-- END BEADS INTEGRATION -->

## Persistent Memory (`bd remember`)

`bd remember "<text>" [--key slug]` stores text in the beads DB that
`bd prime` injects into every future session — shared via Dolt across
agents and accounts. Search with `bd memories <keyword>`; remove with
`bd forget <key>`; pass `--key` so future edits update in place
(without it, the key is auto-derived from content and the next edit
lands under a different key).

**Save** durable, non-obvious knowledge that passes the *3-month test*
(*if I re-read this in 3 months, will it still be true and would I
have wished I knew it?*): hidden constraints not visible in code,
"we tried X and it doesn't work because Y" failure modes, conventions
the codebase doesn't enforce, cross-bead decisions that don't fit in
any one bead.

**Don't save** bead-state snapshots ("N beads ready", refinement
narratives — query `bd ready` / `bd list` in the moment), activity
logs, anything that belongs in a bead's `--design` / `--notes` /
`--acceptance` field, anything `grep` or `git log` would find, or
plan-file paths (they rot).

**Hygiene**: `bd memories <keyword>` before saving to avoid
duplicates; fix or `bd forget` memories that go stale — rotted memory
in the prime stream is worse than no memory.
