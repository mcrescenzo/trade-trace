// Chart bootstrap for the reporting product (trade-trace-ycag).
//
// The reporting dashboards render charts by emitting one Jinja block
// per chart:
//
//   <canvas id="chart-pnl-equity" class="tt-chart"></canvas>
//   <script type="application/json" data-chart="chart-pnl-equity">
//     {"type": "line", "data": {...}, "options": {...}}
//   </script>
//
// This script walks every `<script type="application/json"
// data-chart="...">` block, parses the JSON config, and constructs a
// Chart.js instance on the matching canvas. The config IS the
// server-rendered metric set; no client-side math happens here
// (per reporting-product.md §1.6 + §7.1).
//
// CSP compatibility: the parser uses `JSON.parse`, NOT `eval`. The
// `script-src` policy stays `'self'` because this file lives under
// `/static/js/` and the chart config blocks are inert JSON (the
// `type="application/json"` flag tells the browser not to execute
// them).
//
// Missing-asset behavior: if `window.Chart` is undefined (the
// operator has not vendored `chart.umd.min.js` yet — see
// vendor/chartjs/README.md), every chart canvas is replaced with a
// caveat panel telling the operator what to do. Dashboards still
// render their evidence tables, so missing charts degrade
// gracefully.

(function () {
    "use strict";

    function escapeHtml(text) {
        return String(text)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#x27;");
    }

    function renderMissingAssetCaveat(canvas) {
        const panel = document.createElement("aside");
        panel.className = "tt-chart-missing-asset-caveat";
        panel.setAttribute("role", "note");
        panel.innerHTML = (
            '<strong>Chart asset not loaded.</strong>' +
            ' The reporting product requires the vendored Chart.js' +
            ' asset at <code>static/vendor/chartjs/chart.umd.min.js</code>.' +
            ' Run the curl from <code>vendor/chartjs/README.md</code>' +
            ' to install it. Numeric evidence below is unaffected.'
        );
        canvas.replaceWith(panel);
    }

    function renderOneChart(scriptElement) {
        const canvasId = scriptElement.dataset.chart;
        if (!canvasId) {
            return;
        }
        const canvas = document.getElementById(canvasId);
        if (canvas === null) {
            return;
        }
        if (typeof window.Chart === "undefined") {
            renderMissingAssetCaveat(canvas);
            return;
        }
        let config;
        try {
            config = JSON.parse(scriptElement.textContent || "{}");
        } catch (err) {
            const panel = document.createElement("aside");
            panel.className = "tt-chart-parse-error";
            panel.setAttribute("role", "alert");
            panel.innerHTML = (
                "<strong>Chart config did not parse:</strong> " +
                escapeHtml(err.message)
            );
            canvas.replaceWith(panel);
            return;
        }
        // Chart.js exposes the constructor on `window.Chart` when
        // loaded via UMD. The dashboards never re-render the same
        // canvas, so we don't keep a registry of instances here.
        new window.Chart(canvas, config);
    }

    function bootstrapAllCharts() {
        const scripts = document.querySelectorAll(
            'script[type="application/json"][data-chart]'
        );
        scripts.forEach(renderOneChart);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bootstrapAllCharts);
    } else {
        bootstrapAllCharts();
    }
})();
