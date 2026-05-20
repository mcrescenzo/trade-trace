# Deadcode hunt 2026-05-20 preflight
- Mode: exhaustive backlog-materialization candidate discovery, starting read-only; Beads mutation only after matrix + advisor gate.
- Repo: `/home/hermes/code/trade-trace`
- HEAD: `73aee82b3cb5de934e10835c5f26425a6483813c`
- Branch status: `## main...origin/main`
- Tracked files: 283
- Existing same-family programs: closed `trade-trace-5lx` (2026-05-18 exhaustive) and `trade-trace-ldru` (2026-05-19 refresh). New full pass is justified because current HEAD contains major console/frontend/docs/migration changes and current manifest differs materially from prior manifests.
- Open Beads at preflight are 3 unrelated beta/product feature requests; no open deadcode backlog remains.

## Domain map
### python-core-storage-security
- Files: 43
- Paths/globs: src/trade_trace/__init__.py, src/trade_trace/clock.py, src/trade_trace/contracts, src/trade_trace/core.py, src/trade_trace/events, src/trade_trace/exporter.py, src/trade_trace/logging.py, src/trade_trace/models, src/trade_trace/projections.py, src/trade_trace/security, src/trade_trace/storage, src/trade_trace/timestamps.py, src/trade_trace/version.py
- Coverage priority: exhaustive direct/probed inspection, reference search, entrypoint/public/dynamic/docs/tests validation.
### tools-cli-mcp-reports
- Files: 36
- Paths/globs: src/trade_trace/cli.py, src/trade_trace/mcp_server.py, src/trade_trace/reports, src/trade_trace/tools
- Coverage priority: exhaustive direct/probed inspection, reference search, entrypoint/public/dynamic/docs/tests validation.
### console-backend-frontend
- Files: 32
- Paths/globs: frontend/console, src/trade_trace/console
- Coverage priority: exhaustive direct/probed inspection, reference search, entrypoint/public/dynamic/docs/tests validation.
### tests-fixtures
- Files: 120
- Paths/globs: tests
- Coverage priority: exhaustive direct/probed inspection, reference search, entrypoint/public/dynamic/docs/tests validation.
### docs-ci-config-audit
- Files: 52
- Paths/globs: .claude, .codex, .github, .gitignore, AGENTS.md, CLAUDE.md, LICENSE, README.md, SECURITY.md, docs, pyproject.toml
- Coverage priority: exhaustive direct/probed inspection, reference search, entrypoint/public/dynamic/docs/tests validation.

## Raw command snapshot

```text
pwd
/home/hermes/code/trade-trace

git-root
/home/hermes/code/trade-trace

git-status-sb
## main...origin/main

git-status-short

bd-where
/home/hermes/code/trade-trace/.beads
  database: /home/hermes/code/trade-trace/.beads/embeddeddolt

bd-stats

📊 Issue Database Status

Summary:
  Total Issues:           343
  Open:                   3
  In Progress:            0
  Blocked:                0
  Closed:                 340
  Ready to Work:          3

For more details, use 'bd list' to see individual issues.


bd-open
○ trade-trace-i1dy [● P2] [feature] [beta dogfood feature-request investigate product-opportunity review trade-trace] - Improve low-sample learning-loop report actionability
○ trade-trace-j0f8 [● P2] [feature] [beta dogfood feature-request investigate product-opportunity review trade-trace] - Add lightweight capture-now enrich-later flow for market ideas
○ trade-trace-zgea [● P2] [feature] [beta dogfood feature-request investigate product-opportunity review trade-trace] - Add guided journal bundle and next-action affordances

bd-deadcode-all
✓ trade-trace-5lx [P2] [epic] @Michael Crescenzo [dead-code deadcode-hunt deadcode:exhaustive-20260518 epic] - EPIC: exhaustive deadcode hunt 2026-05-18
✓ trade-trace-6vd [P2] [task] @Michael Crescenzo [dead-code deadcode-gate deadcode-hunt deadcode:exhaustive-20260518] - Final verification: exhaustive deadcode hunt 2026-05-18
✓ trade-trace-8bdd [P4] [task] @Michael Crescenzo [cleanup-candidate dead-code deadcode-hunt deadcode:refresh-20260519 domain:tests domain:tools] - Remove unused internal decision-matrix/test helpers
✓ trade-trace-ahz [P2] [bug] @Michael Crescenzo [bug dead-code deadcode-hunt deadcode:exhaustive-20260518 docs-truth domain:docs risk:stale-contract] - Reconcile docs that advertise unregistered CLI/tool command surfaces
✓ trade-trace-bmf [P4] [task] @Michael Crescenzo [cleanup-candidate dead-code deadcode-hunt deadcode:exhaustive-20260518 domain:tests] - Remove unused _all_columns helper from credential security tests
✓ trade-trace-cap6 [P2] [task] @Michael Crescenzo [dead-code deadcode-hunt deadcode:refresh-20260519 final-verification gate] - Final readback for deadcode refresh 2026-05-19
✓ trade-trace-cey [P2] [bug] [bug dead-code deadcode-hunt deadcode:exhaustive-20260518 docs-truth domain:docs risk:stale-contract] - Fix broken local markdown links after docs path moves
✓ trade-trace-cs0r [P3] [bug] @Michael Crescenzo [api-contract bug bughunt bughunt:exhaustive-refresh-20260519 dead-code deadcode-hunt deadcode:refresh-20260519 domain:reports domain:reports-memory needs-owner-confirmation public-api stale-contract] - report.compare advertises group_by values that are rejected at runtime
✓ trade-trace-ftnu [P3] [bug] @Michael Crescenzo [bug dead-code deadcode-hunt deadcode:refresh-20260519 docs-truth domain:docs domain:reports stale-contract] - Reconcile residual watch.stale docs with report.watchlist registry
✓ trade-trace-ldru [P2] [epic] [dead-code deadcode-hunt deadcode:refresh-20260519 epic] - Deadcode refresh 2026-05-19: materialize stale-code/docs cleanup backlog
✓ trade-trace-mehh [P2] [task] @Michael Crescenzo [dead-code deadcode-hunt deadcode:refresh-20260519 domain:docs domain:storage needs-owner-confirmation stale-contract] - Align optional embeddings docs and sqlite-vec capability reporting
✓ trade-trace-mky [P3] [task] @Michael Crescenzo [cleanup-candidate dead-code deadcode-hunt deadcode:exhaustive-20260518 domain:core-runtime needs-owner-confirmation public-api] - Decide disposition for unused events.write_event wrapper
✓ trade-trace-rzb [P2] [bug] [bug dead-code deadcode-hunt deadcode:exhaustive-20260518 docs-truth domain:docs risk:stale-contract] - Reconcile package/dependency docs with current pyproject embeddings posture
✓ trade-trace-xeq [P3] [task] @Michael Crescenzo [cleanup-candidate dead-code deadcode-hunt deadcode:exhaustive-20260518 domain:core-runtime needs-owner-confirmation public-api] - Decide disposition for unused process-global clock accessors
✓ trade-trace-yv9z [P3] [task] [dead-code deadcode-hunt deadcode:refresh-20260519 domain:reports needs-owner-confirmation public-api stale-contract] - Decide disposition for stale exported DOCUMENTED_GROUP_BY metadata

bd-duplicates
{
  "count": 2,
  "method": "mechanical",
  "pairs": [
    {
      "issue_a_id": "trade-trace-i1dy",
      "issue_a_title": "Improve low-sample learning-loop report actionability",
      "issue_b_id": "trade-trace-zgea",
      "issue_b_title": "Add guided journal bundle and next-action affordances",
      "method": "mechanical",
      "similarity": 0.40128093932957654
    },
    {
      "issue_a_id": "trade-trace-j0f8",
      "issue_a_title": "Add lightweight capture-now enrich-later flow for market ideas",
      "issue_b_id": "trade-trace-zgea",
      "issue_b_title": "Add guided journal bundle and next-action affordances",
      "method": "mechanical",
      "similarity": 0.3877391005407303
    }
  ],
  "schema_version": 1,
  "threshold": 0.35
}

bd-create-help-checked
Create a new issue (or batch from markdown/graph JSON)

Usage:
  bd create [title] [flags]

Aliases:
  create, new

Flags:
      --acceptance string       Acceptance criteria
      --append-notes string     Append to existing notes (with newline separator)
  -a, --assignee string         Assignee
      --body-file string        Read description from file (use - for stdin)
      --context string          Additional context for the issue
      --defer string            Defer until date (issue hidden from bd ready until then). Same formats as --due
      --deps strings            Dependencies in format 'type:id' or 'id' (e.g., 'discovered-from:bd-20,blocks:bd-15' or 'bd-20')
  -d, --description string      Issue description
      --design string           Design notes
      --design-file string      Read design from file (use - for stdin)
      --dry-run                 Preview what would be created without actually creating
      --due string              Due date/time. Formats: +6h, +1d, +2w, tomorrow, next monday, 2025-01-15
      --ephemeral               Create as ephemeral (short-lived, subject to TTL compaction)
  -e, --estimate int            Time estimate in minutes (e.g., 60 for 1 hour)
      --event-actor string      Entity URI who caused this event (requires --type=event)
      --event-category string   Event category (e.g., patrol.muted, agent.started) (requires --type=event)
      --event-payload string    Event-specific JSON data (requires --type=event)
      --event-target string     Entity URI or bead ID affected (requires --type=event)
      --external-ref string     External reference (e.g., 'gh-9', 'jira-ABC')
  -f, --file string             Create multiple issues from markdown file
      --force                   Force creation even if prefix doesn't match database prefix
      --graph string            Create a graph of issues with dependencies from JSON plan file
  -h, --help                    help for create
      --id string               Explicit issue ID (e.g., 'bd-42' for partitioning)
  -l, --labels strings          Labels (comma-separated)
      --metadata string         Set custom metadata (JSON string or @file.json to read from file)
      --mol-type string         Molecule type: swarm (multi-agent), patrol (recurring ops), work (default)
      --no-history              Skip Dolt commit history without making GC-eligible (for permanent agent beads)
      --no-inherit-labels       Don't inherit labels from parent issue
      --notes string            Additional notes
      --parent string           Parent issue ID for hierarchical child (e.g., 'bd-a3f8e9')
  -p, --priority string         Priority (0-4 or P0-P4, 0=highest) (default "2")
      --repo string             Target repository for issue (overrides auto-routing)
      --silent                  Output only the issue ID (for scripting)
      --skills string           Required skills for this issue
      --spec-id string          Link to specification document
      --stdin                   Read description from stdin (alias for --body-file -)
      --title string            Issue title (alternative to positional argument)
  -t, --type string             Issue type (bug|feature|task|epic|chore|decision); custom types require types.custom config; aliases: enhancement/feat→feature, dec/adr→decision (default "task")
      --validate                Validate description contains required sections for issue type
      --waits-for string        Spawner issue ID to wait for (creates waits-for dependency for fanout gate)
      --waits-for-gate string   Gate type: all-children (wait for all) or any-children (wait for first) (default "all-children")
      --wisp-type string        Wisp type for TTL-based compaction: heartbeat, ping, patrol, gc_report, recovery, error, escalation

Global Flags:
      --actor string              Actor name for audit trail (default: $BEADS_ACTOR, git user.name, $USER)
      --db string                 Database path (default: auto-discover .beads/*.db)
      --dolt-auto-commit string   Dolt auto-commit policy (off|on|batch). 'on': commit after each write. 'batch': defer commits to bd dolt commit; uncommitted changes persist in the working set until then. SIGTERM/SIGHUP flush pending batch commits. Default: off. Override via config key dolt.auto-commit
      --global                    Use the global shared-server database (beads_global)
      --json                      Output in JSON format
      --profile                   Generate CPU profile for performance analysis
  -q, --quiet                     Suppress non-essential output (errors only)
      --readonly                  Read-only mode: block write operations (for worker sandboxes)
      --sandbox                   Sandbox mode: disables auto-sync
  -v, --verbose                   Enable verbose/debug output

bd-dep-help-checked
Manage dependencies between issues.

When called with an issue ID and --blocks flag, creates a blocking dependency:
  bd dep <blocker-id> --blocks <blocked-id>

This is equivalent to:
  bd dep add <blocked-id> <blocker-id>

Examples:
  bd dep bd-xyz --blocks bd-abc    # bd-xyz blocks bd-abc
  bd dep add bd-abc bd-xyz         # Same as above (bd-abc depends on bd-xyz)

Usage:
  bd dep [issue-id] [flags]
  bd dep [command]

Available Commands:
  add         Add a dependency
  cycles      Detect dependency cycles
  list        List dependencies or dependents of one or more issues
  relate      Create a bidirectional relates_to link between issues
  remove      Remove a dependency
  tree        Show dependency tree
  unrelate    Remove a relates_to link between issues

Flags:
  -b, --blocks string   Issue ID that this issue blocks (shorthand for: bd dep add <blocked> <blocker>)
  -h, --help            help for dep

Global Flags:
      --actor string              Actor name for audit trail (default: $BEADS_ACTOR, git user.name, $USER)
      --db string                 Database path (default: auto-discover .beads/*.db)
      --dolt-auto-commit string   Dolt auto-commit policy (off|on|batch). 'on': commit after each write. 'batch': defer commits to bd dolt commit; uncommitted changes persist in the working set until then. SIGTERM/SIGHUP flush pending batch commits. Default: off. Override via config key dolt.auto-commit
      --global                    Use the global shared-server database (beads_global)
      --json                      Output in JSON format
      --profile                   Generate CPU profile for performance analysis
  -q, --quiet                     Suppress non-essential output (errors only)
      --readonly                  Read-only mode: block write operations (for worker sandboxes)
      --sandbox                   Sandbox mode: disables auto-sync
  -v, --verbose                   Enable verbose/debug output

Use "bd dep [command] --help" for more information about a command.

bd-children-help-checked
List all beads that are children of the specified parent bead.

This is a convenience alias for 'bd list --parent <id> --status all'.
Unlike plain 'bd list', children includes closed issues by default,
since the primary use case is inspecting all work under a parent.

Examples:
  bd children hq-abc123        # List all children of hq-abc123
  bd children hq-abc123 --json # List children in JSON format
  bd children hq-abc123 --pretty # Show children in tree format

Usage:
  bd children <parent-id> [flags]

Flags:
  -h, --help   help for children

Global Flags:
      --actor string              Actor name for audit trail (default: $BEADS_ACTOR, git user.name, $USER)
      --db string                 Database path (default: auto-discover .beads/*.db)
      --dolt-auto-commit string   Dolt auto-commit policy (off|on|batch). 'on': commit after each write. 'batch': defer commits to bd dolt commit; uncommitted changes persist in the working set until then. SIGTERM/SIGHUP flush pending batch commits. Default: off. Override via config key dolt.auto-commit
      --global                    Use the global shared-server database (beads_global)
      --json                      Output in JSON format
      --profile                   Generate CPU profile for performance analysis
  -q, --quiet                     Suppress non-essential output (errors only)
      --readonly                  Read-only mode: block write operations (for worker sandboxes)
      --sandbox                   Sandbox mode: disables auto-sync
  -v, --verbose                   Enable verbose/debug output
```
