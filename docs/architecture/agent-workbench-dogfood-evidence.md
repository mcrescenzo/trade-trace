# Agent workbench dogfood evidence retention

Status: active convention for the agent-native workbench ergonomics beta/dogfood program.

Companion docs: [MVP Dogfood and Provenance Protocol](dogfood-protocol.md), [Agent guide](../AGENT_GUIDE.md).

## 1. Purpose and privacy boundary

This document defines how this repository retains beta/dogfood evidence for the agent-native workbench ergonomics program without checking private operator data into git.

The goal is to make future evaluations and Beads notes auditable while preserving the privacy boundary:

- Checked-in evidence must be sanitized, durable, and useful to future reviewers.
- Raw/private dogfood artifacts remain local or ignored unless they are explicitly redacted into a sanitized packet.
- Beads notes cite sanitized repo evidence or clearly state that supporting raw evidence is private/ignored and unavailable to the public repo.

This convention addresses the trade-trace-73zr evidence gap reported by the completed inventory artifact `docs/audits/agent-workbench-contract-drift-20260520T1846Z.md`: no obvious repo-local beta dogfood transcript/artifact files were found. The fix is a future-facing retention process, not a retrospective claim that hidden artifacts exist.

## 2. Allowed and prohibited checked-in artifacts

Allowed checked-in artifacts are repo-safe materials that do not expose private transcripts, identities, account data, secrets, or machine-specific paths. Prefer concise evidence that can survive public review.

Allowed examples:

- Sanitized dogfood summaries under tracked docs paths, for example `docs/architecture/agent-workbench-dogfood-evidence.md` updates or a future tracked summary under `docs/evidence/` if that directory is introduced intentionally.
- Redacted evidence packets that contain only excerpts necessary to validate a behavior, with private content replaced by stable placeholders such as `<operator>`, `<local-path>`, `<account-id>`, or `<secret-redacted>`.
- Schemas, checklists, command outlines, test names, evaluation criteria, and aggregate findings.
- Links to tracked code, tests, docs, or sanitized artifacts.
- Explicit absence records, for example: "inventory checked paths X/Y/Z on date T and found no sanitized beta evidence packet."

Prohibited checked-in artifacts:

- Raw private transcripts from agents, chats, shells, IDEs, Beads sessions, support channels, or workbench beta runs.
- Secrets, API keys, tokens, credentials, auth headers, private URLs, broker/customer identifiers, account IDs, wallet IDs, emails, phone numbers, or personal names unless already public and necessary.
- Local absolute paths, machine names, home-directory usernames, process lists, environment dumps, or editor/session metadata.
- Raw `docs/audits/` run exports or other ignored audit artifacts unless they have been deliberately sanitized and moved to a tracked evidence location.
- Full database dumps, `.sqlite` files, Beads internal state, `.dolt/`, `.beads/`, or logs that include unreviewed payloads.

When in doubt, do not commit the artifact. Produce a sanitized summary instead.

## 3. Ignored/local artifact locations and raw-run naming

Raw beta/dogfood evidence belongs in ignored/local locations. Current ignored locations include `docs/audits/`, `audits/`, `.beads/`, `.dolt/`, SQLite databases, and common cache/build directories in `.gitignore`.

Recommended local raw-run layout:

```text
docs/audits/agent-workbench-dogfood/<UTC timestamp>-<short-slug>/
```

Use this naming convention:

```text
YYYYMMDDTHHMMSSZ-<program-or-bead>-<short-purpose>/
```

Examples:

```text
docs/audits/agent-workbench-dogfood/20260520T184600Z-trade-trace-73zr-contract-drift/
docs/audits/agent-workbench-dogfood/20260521T101500Z-beta-workbench-shell-ergonomics/
```

Raw-run directories may contain private transcripts, local command logs, screenshots, run manifests, or temporary notes, but they must stay ignored. If a raw run supports a public claim, create a sanitized summary or packet in a tracked docs path and cite that tracked artifact instead of the raw directory.

## 4. Sanitized summary template and required fields

Every checked-in dogfood evidence summary should include these fields. Use `not collected`, `not applicable`, or `absent` explicitly rather than implying evidence exists.

```markdown
# <Short evidence title>

Status: sanitized summary
Program/bead: <agent-workbench ergonomics / bead id if applicable>
Raw evidence location: ignored/local only, <relative ignored directory or "not retained">
Sanitization reviewer: <role or handle, no private identity required>
Sanitized on: <YYYY-MM-DD>

## Scope
- Workbench surface evaluated:
- Scenario or task:
- Date/time window in UTC:
- Tools/transports involved:

## Evidence retained in repo
- Tracked artifact paths:
- Relevant tests/docs/code links:
- Beads note references, if any:

## Findings
- What worked:
- What failed or was confusing:
- User-visible impact:
- Reproducibility notes:

## Privacy/redaction notes
- Redactions applied:
- Private data excluded:
- Local paths/account IDs/secrets checked absent from this summary: yes/no

## Validation/eval hooks
- How future inventory/eval beads should find this evidence:
- Keywords/headings to search:
- If evidence is absent, exact absence statement to record:

## Follow-ups
- Open questions:
- Related beads/issues:
```

Minimum required fields for any shorter packet are: program/bead, scope, UTC date/time window, repo-retained artifact paths, finding summary, privacy/redaction notes, and validation/eval hooks.

## 5. Beads note citation convention

Future Beads notes should cite checked-in sanitized evidence, not raw private artifacts. Use relative repository paths and stable headings when possible.

Preferred citation format:

```text
Evidence: docs/architecture/agent-workbench-dogfood-evidence.md#<heading> (<one-line finding>)
```

For a dedicated sanitized packet:

```text
Evidence: docs/evidence/<packet>.md#findings (<one-line finding>)
```

If raw/private evidence was reviewed but cannot be checked in, Beads notes may say so without leaking details:

```text
Private raw evidence reviewed in ignored docs/audits/agent-workbench-dogfood/YYYYMMDDTHHMMSSZ-<slug>/; public sanitized summary: <tracked path>#<heading>.
```

If no sanitized evidence exists, the note must record absence truthfully:

```text
No tracked sanitized beta dogfood evidence packet found as of <YYYY-MM-DD>; raw/private evidence, if any, remains ignored and was not used for public validation.
```

Do not paste transcript excerpts, local absolute paths, private account identifiers, or operator identities into Beads notes.

## 6. Validation and eval usage

Future inventory/eval beads should look for dogfood evidence in this order:

1. Tracked docs with explicit headings/keywords: `agent-workbench-dogfood-evidence`, `dogfood evidence`, `sanitized summary`, `agent-native workbench ergonomics`, `trade-trace-73zr`.
2. Any intentionally introduced tracked evidence directory, such as `docs/evidence/`, if present and not ignored.
3. Tests or docs that reference sanitized evidence packets.
4. Ignored raw-run directories only to confirm local private evidence exists for the current operator; do not cite or require them for public repo validation.

Eval beads must distinguish these states:

- `present`: tracked sanitized evidence exists and is cited by path/heading.
- `absent`: no tracked sanitized evidence exists; record the searched paths and date.
- `private-only`: ignored/local raw artifacts exist but no sanitized packet is tracked; record that public validation cannot rely on them.
- `not checked`: the eval did not inspect evidence locations; do not infer presence.

This makes the trade-trace-73zr gap actionable: future evals can either cite a sanitized artifact or record a precise absence instead of silently treating ignored audit output as durable evidence.

## 7. Program linkage and trade-trace-73zr gap

The agent-native workbench ergonomics program needs dogfood evidence that is useful to agents and maintainers across sessions. This repo should retain only the sanitized layer needed to answer questions such as:

- Which workbench surface was evaluated?
- What task or scenario exposed the ergonomics issue?
- Which public code, docs, schema, or tests support the conclusion?
- What private/raw data was excluded?
- How should a future Beads note or eval cite the finding?

For trade-trace-73zr specifically, the absence of repo-local beta dogfood artifacts is now represented as a process requirement: every future beta/dogfood run that supports a public program claim should either land a sanitized summary in tracked docs or leave an explicit tracked absence statement. Raw ignored audit files alone are insufficient evidence for public validation.
