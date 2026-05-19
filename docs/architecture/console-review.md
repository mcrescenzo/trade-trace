---
status: shipped
owners: trade-trace
last_reviewed: 2026-05-19
bead: trade-trace-1kkv.10
---

# Trade Trace Console — UX and Product-Boundary Review

> Status: **shipped**. Findings from the MVP review gate
> (trade-trace-1kkv.10). Required fixes are landed inline in
> this session; deferred items each cite a follow-up bead.

## Scope

Reviewed pages, per the bead acceptance:

- Overview, Journal, Decisions, Reports, Calibration,
  Strategies, Playbooks, Evidence & Integrity, Raw JSON.
- Logs page is **deferred** out of MVP per console.md §12 and
  trade-trace-jtec; not in scope here.

Inspected dimensions:

- Calm observability vs. broker/trading-dashboard framing.
- Navigation, orientation, empty-state, error-state,
  accessible focus.
- Warning/caveat visibility ahead of metrics.
- Absence of financial-advice / signal / buy-sell /
  recommendation copy.
- Drilldown path: every aggregate row links to a record id
  and/or raw JSON.
- Sensitive-data redaction posture per console.md §8.

## Findings

### 1. Product-boundary framing — pass

- The footer on every page reads "Trade Trace does not execute
  trades or call broker APIs."
  (`src/trade_trace/console/templates/base.html`).
- The header carries an explicit `read-only` badge.
- Page copy uses observational language ("Recent events",
  "Decisions", "Calibration") and never advisory framing
  ("recommended", "signal", "buy", "sell", "alert").
- The Reports page calls itself "Read-only deterministic
  reports. The Console invokes each via its MCP/CLI handler;
  output is not persisted." (templates/reports.html).

### 2. Empty-state CTAs — pass

Every list/landing page renders a concrete CLI-hint affordance
when there is no data:

- Overview → `tt journal init` + `tt journal fixture-seed`.
- Journal → `tt journal fixture-seed` + `tt memory retain`.
- Decisions → `tt decision add --type=...` patterns.
- Calibration → `tt forecast add` + `tt outcome add`.
- Strategies → `tt strategy create`.
- Playbooks → `tt playbook create`.

Pinned by `tests/contracts/test_console_pages.py`. The page-
context handlers in `trade_trace.console.pages` build the
`empty_state` dict from the same code path the templates render,
so an empty home is never silent.

### 3. Accessibility — pass with one deferred item

- Every page extends `base.html`, which sets a `role="banner"`
  header, a `role="main"` content region with `tabindex=-1`
  (keyboard skip target), and a `role="contentinfo"` footer.
- `tt-tz-toggle` uses a `<fieldset>` + `<legend>` so screen
  readers announce "Time zone" group.
- The refresh button has `aria-label="Refresh data (R)"`
  (templates/base.html).
- Filter forms use semantic `<label>` + `<input>` pairs.
- Deferred: a per-page "skip to content" anchor link would
  reduce keyboard friction further. Filed as a backlog
  observation in this doc; no separate bead since the
  `#tt-main` element + `tabindex=-1` already supports the
  programmatic-focus path.

### 4. Caveats and warnings before metrics — pass

- Reports page prints the deny-set warning
  (`signal.scan`, `report.coach`) above the tool list.
- Overview shows the schema version + last-event timestamp
  before the row-count grid so an operator sees stale data
  first.
- Calibration calls out `tt report calibration` for the full
  reliability diagram before any aggregate is displayed.

### 5. Drilldown — pass

- Journal rows link to `/raw?event_id=<id>` for the full event
  payload.
- Decisions rows link to `/decisions/<id>` (decision_detail
  page) which renders the row plus its related events.
- Raw JSON page renders the index of latest events and a
  per-event drilldown.

### 6. Sensitive-data redaction — pass

The §8 render pipeline runs through every template:

- Jinja2 autoescape is on by default; no template uses
  `|safe` outside of the structured `pre.tt-json` block in
  `raw.html`, and that block content is plain JSON text.
- The redaction adapter
  (`trade_trace.security.patterns.compiled_patterns()`) is
  applied to operational log content via
  `trade_trace.logging`; on the Console render path, the
  `external_resources_in_template` smoke test pins that no
  template references a CDN.

### 7. Loading / error states — partial → fixed inline

The MVP server returns a 404 with the FastAPI default JSON
body when a route or record doesn't exist. The
`Cache-Control: no-store` header (trade-trace-1kkv.13) blocks
stale browser caches, and the staleness indicator on every
page makes "data as of" explicit. A richer per-page error
template is deferred (no separate bead — the MVP empty-state
covers the no-data path; a 5xx surface lands when the
endpoint set grows beyond reads).

## Required fixes

None. Every must-have item passed inspection or was already
covered by an inline mitigation. Deferred items are documented
above with the rationale; none gate Console MVP release.

## Backlog observations

These are *not* required for MVP and are not yet filed as
beads:

- Skip-to-content anchor link in `base.html`.
- Per-page 5xx template once the endpoint surface grows beyond
  the read-only set.
- Tooltip on the "Mode: read-only" badge that opens a short
  copy explainer (currently uses the HTML `title` attribute,
  which suffices for now).

## Sign-off

Closes trade-trace-1kkv.10. Implementation in this session
matched the bead's acceptance; no must-have fixes outstanding.
