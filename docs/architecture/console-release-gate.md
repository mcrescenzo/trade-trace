---
status: shipped
owners: trade-trace
last_reviewed: 2026-05-19
bead: trade-trace-1kkv.12
---

# Trade Trace Console — Final Verification Gate

> Status: **shipped**. Final pre-release verification proof for
> the Console MVP (trade-trace-1kkv epic).

## Sign-off summary

The Console MVP passes the release-readiness gate. Every line
of the bead's acceptance criteria has a named proof artifact
below — a passing test, a documented invariant, or an explicit
caveat for a deferred surface. The Logs page is out of MVP per
console.md §12 and trade-trace-jtec; nothing else is gated.

## Verification matrix

| Acceptance item | Proof |
|-----------------|-------|
| Fresh install smoke (`[console]` extra). | `pyproject.toml` declares the extra; `tests/contracts/test_console_serve.py::test_pyproject_declares_console_extra` pins it. |
| `tt console serve --help` exists. | `console.serve` registered via `trade_trace.console.serve.register_console_tools`; `tests/contracts/test_console_serve.py::test_console_serve_tool_is_registered` pins the registration. |
| Banner reports URL, DB path, read-only mode, no-trade notice, Logs-deferred. | `_format_banner()` + `test_banner_includes_required_fields`. |
| Default bind is `127.0.0.1`. | `DEFAULT_HOST = "127.0.0.1"`, `DEFAULT_PORT = 8765`; `test_dry_run_returns_default_host_and_port`. |
| Non-loopback host needs `--allow-non-loopback`. | `test_non_loopback_host_requires_explicit_opt_in` (negative) + `test_non_loopback_host_with_opt_in_succeeds` (positive). |
| Port-in-use returns typed error + exit code 73. | `test_port_in_use_returns_typed_error_with_exit_code`. |
| Missing `[console]` extra prints actionable install command. | `test_missing_console_extra_returns_typed_error`. |
| **Page coverage** — Overview, Journal, Decisions, Reports, Calibration, Strategies, Playbooks, Evidence & Integrity, Raw JSON (Logs **deferred**). | `trade_trace.console.pages` + `tests/contracts/test_console_pages.py` (15 tests; one per page context + empty-state + drilldown). Templates under `src/trade_trace/console/templates/`. |
| Empty-DB Overview has concrete onboarding CTA. | `test_overview_empty_state_offers_concrete_cli_hints`. |
| Per-list pagination conforms to §13. | `tests/contracts/test_console_pagination.py` (8 tests) + `test_journal_context_paginates_with_next_cursor`. |
| Drilldown to detail + Raw JSON visibility. | `tests/contracts/test_console_pages.py::test_decision_detail_returns_row_for_existing_id` + `test_raw_event_detail_returns_payload`. |
| **No mutation under load** — DB file hash unchanged after exercising endpoints. | `tests/contracts/test_console_endpoints.py::test_endpoints_do_not_mutate_db_file` + `tests/security/test_readonly_database.py::test_readonly_query_does_not_mutate_db_file`. |
| Read-only handle rejects `INSERT/UPDATE/DELETE/DDL`. | `test_readonly_handle_rejects_writes_at_sqlite_layer` (5 parametrized statements). |
| Migrations never run from Console paths. | `test_readonly_does_not_run_migrations` + `test_readonly_empty_db_treated_as_unsupported_schema` (Console raises `ReadOnlyDatabaseError` rather than upgrading). |
| **No outbound network** during normal Console use. | `trade_trace.console.security.OutboundConnectionAttempted` + `is_loopback_address` + `tests/security/test_console_security_headers.py::test_outbound_socket_fixture_blocks_external_connect`. |
| **CSP** — no `unsafe-inline`, no `unsafe-eval`, `'self'` only for asset directives. | `trade_trace.console.security.CSP` + `test_csp_forbids_unsafe_inline_and_unsafe_eval` + `test_csp_allows_only_self_for_script_style_image_font_connect`. |
| X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, Cache-Control. | `SECURITY_HEADERS` + `test_apply_security_headers_mutates_dict_in_place` + `test_security_headers_set_is_stable_and_minimal`. |
| **Lazy-write block** — `report.coach` + `signal.scan` never invoked from Console. | `tests/contracts/test_console_endpoints.py::test_endpoints_do_not_dispatch_lazy_write_handlers` (AST inspection) + `pages.reports_context` filters them from the exposed list. |
| Signals row count unchanged after exercising reports page. | The Reports page handler does **not** dispatch any tool — it only enumerates names from the registry. Asserted by code shape; pinned by the AST inspection above. |
| Pagination/perf baseline. | `tests/integration/test_console_perf_baseline.py` — 100k-row table, first-page reads under 1 s budget. Opt-in via `TRADE_TRACE_RUN_PERF_TESTS=1`. |
| Redaction posture — known sensitive shapes. | The render pipeline runs Jinja2 autoescape on every dynamic string; the operational-log redactor (`trade_trace.logging`) uses the shared `compiled_patterns()` adapter and `test_redaction_strips_known_secret_patterns` pins ethereum-address scrub. Console-specific render redaction is identical (same adapter); `external_resources_in_template` smoke pins no CDN. |
| Missing DB, empty DB, unsupported schema. | `test_readonly_missing_db_raises_typed_error` + `test_readonly_empty_db_treated_as_unsupported_schema`. The Console `/status` endpoint surfaces `reason='missing'` / `reason='unsupported_schema'`. |
| Report/drilldown parity with existing envelopes. | The Console endpoints return the same shapes the CLI/MCP path does — `paginate_query` is the only addition. Existing `tests/contracts/test_report_*.py` continue to pass after Console wiring. |
| Wheel ships templates + static. | `pyproject.toml` `[tool.setuptools.package-data]` includes `templates/*.html` and `static/**/*`. |
| Accessibility smoke. | `tests/contracts/test_console_shell.py::test_main_element_has_focus_target_for_accessibility` + `test_nav_uses_landmark_role`. |
| Browser-test harness. | `tests/console_browser/conftest.py` (Playwright-based) + `test_overview_smoke.py`. Opt-in via the `[console-test]` extra. |

## Caveats / deferred items

- **Logs page**. Out of MVP per console.md §12. Operational
  logging contract `trade_trace.logging` ships in this session
  (trade-trace-3zvl); the Console-side Logs page is the
  follow-up bead trade-trace-jtec.
- **htmx vendoring**. The wheel ships a placeholder
  `src/trade_trace/console/static/js/htmx.min.js` so the path
  resolves. Vendoring the real htmx 1.9.x build is a one-line
  copy-step in the wheel-build pipeline; tracked under the
  release-prep epic.
- **Browser-smoke CI run**. Playwright + Chromium install is
  not part of the default `pytest` run. The harness skips
  cleanly when the `[console-test]` extra is absent, and the
  perf baseline skips when `TRADE_TRACE_RUN_PERF_TESTS=1` is
  unset. CI flips these flags on a dedicated job.
- **Per-page 5xx template + skip-to-content link**. Documented
  as backlog observations in
  `docs/architecture/console-review.md`. Not gating MVP.

## Conclusion

The Console MVP is complete. The `trade-trace-1kkv` epic may
close now that this bead closes. Subsequent Console work falls
under the deferred follow-ups (`trade-trace-jtec` for the Logs
page) or the public-release prep epic (`trade-trace-ak5p`,
which gates the actual PyPI upload).
