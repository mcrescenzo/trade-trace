# Console Release Gate

> Status: **shipped** — release checklist for the React/Vite Console.

## Required Gates

| Gate | Evidence |
|---|---|
| `[console]` extra installs server runtime only. | `pyproject.toml` contains FastAPI/Uvicorn. |
| `tt console serve` contract remains stable. | `tests/contracts/test_console_serve.py`. |
| SPA routes serve the prebuilt app shell. | `tests/contracts/test_console_http_routes.py`. |
| `/api/console/*` endpoints return typed JSON. | HTTP route tests plus endpoint/read-model tests. |
| DB remains unchanged after Console reads. | `tests/contracts/test_console_endpoints.py` and read-only DB tests. |
| Lazy-write handlers blocked. | Adapter/endpoints tests pin `signal.scan` and `report.coach`. |
| CSP/no external assets. | `tests/security/test_console_security_headers.py`. |
| Wheel ships app assets. | `tests/contracts/test_console_shell.py`. |
| Frontend typecheck, unit tests, and production build pass. | `npm --prefix frontend/console run test` and `npm --prefix frontend/console run build`. |
| Browser smoke passes. | `tests/console_browser/`. |
| Agentic visual review completed. | Saved review notes using `console-visual-review.md`. |

## Standard Command Set

```bash
npm --prefix frontend/console ci
npm --prefix frontend/console run test
npm --prefix frontend/console run build
pytest tests/contracts/test_console_serve.py tests/contracts/test_console_http_routes.py
pytest tests/contracts/test_console_shell.py tests/contracts/test_console_dashboard_a11y.py
pytest tests/contracts/test_console_charting.py
pytest tests/security/test_console_security_headers.py
pytest tests/console_browser/
```

Run the broader integration suite when report/read-model internals
change.
