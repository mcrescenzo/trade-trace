# Docs taxonomy: shipped vs. designed (SIMP-014)

> Status: **decision document for trade-trace-qa2g** (findings + recommendation).
> No doc moves or markdown rewrites in this document — the
> implementation lands as a follow-up bead.

## Problem

The architecture docs under `docs/architecture/` mix two very
different audiences:

- **Capability docs** that describe behavior an agent or operator can
  rely on today: `contracts.md`, `persistence.md`, `operability.md`,
  `memory-layer.md`, `scoring.md`, `imports.md`, `reports.md`,
  `security.md`, `dogfood-protocol.md`.
- **Design docs** that describe planned or proposed behavior that
  hasn't shipped: `http-sse-subscribe.md` (explicitly proposed; PRD
  lists HTTP/SSE as P1), `forecastbench-compatibility.md` (described
  as exact ForecastBench compat — not implemented),
  `risk-units.md` and `opportunity-analysis.md` (P1 design surfaces
  with partial stub columns in storage; reports landed).
- **Decision / findings docs** filed against specific beads:
  `position-reopen-semantics.md`, `schema-meta-diagnostics.md`,
  `security-adapter-investigation.md`, `release-gate-consolidation.md`.

README.md and AGENT_GUIDE.md cross-link into all three categories
without a status marker, and a careful reader has to compare with the
registry / tests to find out which docs describe shipped behavior.

## Goals

Pick a taxonomy that is:

1. **Cheap to apply**: no broad markdown rewrites; each doc gets a
   one-line status marker near the top, then lives in the right
   directory.
2. **Cheap to read**: a reader scanning a doc can decide in one second
   whether the contents describe today's behavior or a future plan.
3. **Cheap to maintain**: when a design ships, the marker flips and
   the doc (optionally) moves; no fanned-out cross-references break.

## Recommendation

### Taxonomy

Three categories, each with a top-of-file header line:

- `> Status: **shipped** as of YYYY-MM-DD` for capability docs that
  match the current registry/tests. Examples: `contracts.md`,
  `persistence.md`, `operability.md`, `memory-layer.md`, `scoring.md`,
  `reports.md`, `security.md`, `dogfood-protocol.md`.
- `> Status: **design — not implemented**` for docs describing
  planned behavior. Examples: `http-sse-subscribe.md`,
  `forecastbench-compatibility.md`. The `risk-units.md` and
  `opportunity-analysis.md` files describe partial implementations,
  so they get `Status: **partial — see §N for the shipped subset**`.
- `> Status: **decision document for trade-trace-<id>**` for
  per-bead findings that codify behavior or plan an implementation.
  The investigation docs added during the no-tech-debt / SIMP
  workstreams already fit this pattern — they get a status header
  that names the bead and links to the follow-up implementation
  bead if any.

The header is a markdown blockquote so it renders inline on GitHub
and PyPI without any extra theme.

### Directory shape

Keep all three categories under `docs/architecture/` for now. Moving
design or decision docs into subdirectories breaks every cross-link
in README and the existing architecture docs; the markdown link
checker added in trade-trace-ensw catches the breakage but the
cleanup PR would be enormous. The status header is the affordance;
the directory layout is a follow-up if the file count grows.

### Implementation shape (for the follow-up bead)

1. Add the status header to every existing doc under
   `docs/architecture/`. Each file gets one of:
   - shipped + a date inferred from `git log -1 --format=%cd
     -- <file>`
   - design — not implemented
   - partial + a one-line note pointing at the shipped subset
   - decision document for `trade-trace-<id>` + a follow-up bead link
2. Update README and AGENT_GUIDE.md cross-links to flag any design or
   partial doc inline (e.g. `[forecastbench-compatibility.md][design]`).
3. Add a tiny test under `tests/docs/test_status_headers.py` that
   walks `docs/architecture/*.md` and asserts every file has a
   `Status:` line in its first ten lines. New files inherit the
   discipline.

### Why not split into `docs/architecture/{shipped,design,decisions}/`?

- Breaks every cross-link in the repo (and PyPI README, since README
  links into these docs).
- Forces an authoring decision about "where does this fit" on every
  PR; the status header lets the doc stay in the same place across
  status changes.
- The link checker (`tests/docs/test_markdown_links.py` per
  trade-trace-ensw) would need a one-time fixup to update every
  reference. That's not a behavioral problem but it is busy work.

## Out of scope

- Renaming or merging docs (e.g., consolidating `risk-units.md` and
  `opportunity-analysis.md`).
- Rewriting README to remove the long shipped/deferred narrative; the
  PyPI-friendly rewrite already shipped under `trade-trace-28b9`.
- Deleting design docs whose feature is no longer planned. Each such
  decision needs its own bead so the design context survives.

## Validation plan (follow-up bead)

- `tests/docs/test_markdown_links.py` continues to pass after every
  header is added.
- The new `tests/docs/test_status_headers.py` test enforces the
  header on every existing architecture doc and any future addition.
- No source code or tests outside `tests/docs/` are touched.
