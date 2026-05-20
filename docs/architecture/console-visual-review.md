# Console Agentic Visual Review

> Status: **shipped** — visual QA rubric for the React Console release gate.

Use this rubric after building the React Console and starting
`tt console serve` against the rich fixture.

## Screenshots

Capture desktop, tablet, and mobile screenshots for:

- `/`
- `/trades`
- `/reports`
- `/reports/pnl`
- `/reports/risk`
- `/calibration`
- `/evidence`
- `/journal`
- `/logs`

Recommended viewport widths: `390`, `768`, `1280`, and `1440`.

## Review Rubric

Block release for:

- overlapping text, controls, nav, tables, or charts;
- unreadable table columns at mobile or desktop widths;
- chart canvases with no visible data or unusable axis labels;
- loading, error, or empty states that leave the page visually blank;
- route-to-route visual inconsistency in header, nav, cards, or tables;
- color-only warning/caveat states;
- inaccessible focus order or missing semantic page landmarks.

Record route, viewport, screenshot path, finding, severity, and the
required fix. A release may proceed only when no blocking findings
remain.
