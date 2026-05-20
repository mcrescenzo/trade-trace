# Vendored Chart.js (trade-trace-ycag)

This directory holds the pinned Chart.js asset the reporting product
loads from `static/vendor/chartjs/chart.umd.min.js`. The file is
intentionally **not** committed to the repo: the bootstrap script
(`static/js/chart-bootstrap.js`) checks for its presence and tells the
operator what to do when it's missing.

## Pinned version

- **Library:** Chart.js
- **Version:** `4.4.3`
- **Distribution:** UMD minified (`chart.umd.js` minified ≈ 200 KiB)
- **License:** MIT (vendor `LICENSE-chart.js.txt` alongside the asset)
- **Upstream source-of-truth:** the official GitHub release tag
  `https://github.com/chartjs/Chart.js/releases/tag/v4.4.3`
- **Expected filename:** `chart.umd.min.js`

## Installation (operator step)

The asset is downloaded once and committed (or shipped as part of the
`[console]` wheel). It is **not** fetched at runtime.

```bash
# From the repo root, with network access to GitHub:
cd src/trade_trace/console/static/vendor/chartjs
curl -L -o chart.umd.min.js \
    https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.js
curl -L -o LICENSE-chart.js.txt \
    https://raw.githubusercontent.com/chartjs/Chart.js/v4.4.3/LICENSE.md

# Pin the SHA in `src/trade_trace/console/security.py::CHARTJS_SHA256`
# (the security/CSP test asserts the on-disk file matches).
sha256sum chart.umd.min.js
```

After the download:

- The dashboards render charts via `chart-bootstrap.js` reading
  `<script type="application/json" data-chart="<canvas-id>">` blocks
  emitted by the Jinja templates.
- The CSP test in `tests/security/test_console_security_headers.py`
  verifies the asset is loaded as `script-src 'self'` only (no CDN /
  no `unsafe-inline` / no `unsafe-eval`).
- The packaging test in `tests/integration/test_console_perf_baseline.py`
  (or a dedicated `tests/integration/test_console_chart_asset.py`)
  verifies the pinned SHA matches.

## Why no CDN

Per `docs/architecture/console.md` §Threat model and
`docs/architecture/reporting-product.md` §1, the Console is loopback-
only and the CSP forbids non-`'self'` script sources. Using a CDN
would violate the no-outbound-network guarantee, the CSP test, and
the threat model.

## Why this file is not committed

Committing a 200 KiB minified bundle bloats the repo and complicates
upgrades (every version bump churns a binary-looking file in the
diff). The operator runs the curl above once; CI / release pipelines
script the same step. Reversing this decision = `git add` the asset
and update this README.

## Cross-references

- Architecture decision: `docs/architecture/reporting-product.md` §7.1
- Bead: trade-trace-ycag
- Bootstrap script: `src/trade_trace/console/static/js/chart-bootstrap.js`
- Security test: `tests/security/test_console_security_headers.py`
