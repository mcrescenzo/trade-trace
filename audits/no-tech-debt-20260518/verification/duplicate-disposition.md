# Duplicate scan disposition — no-tech-debt 20260518

Raw final scan: verification/duplicates-final.json; reported pairs: 100.

Disposition summary: mechanical scan is dominated by intentional template/shared-provenance overlap after bulk materialization. The accepted beads share standard sections (Evidence, Target paydown, Validation, Duplicate check, Provenance) and common labels, which inflates similarity. This is not treated as a pass/fail boolean.

Representative high-similarity pair dispositions:
- trade-trace-d4k / trade-trace-wmz: Keep separate: ReportFilter semantic filtering vs storage timestamp invariant boundary; different owners, files, validations, and remediation tracks.
- trade-trace-dhm / trade-trace-wmz: Keep separate: events append-only triggers vs timestamp invariant policy; both schema design but different DB objects and tests.
- trade-trace-qfxw / trade-trace-7j1l: Keep separate: concrete metadata_json credential bypass bug vs broader secret-surface policy/design. qfxw can be fixed/tested independently.
- trade-trace-4rp / trade-trace-29u0: Keep separate: nested full-suite subprocess removal vs fixture_seed wall-clock perf assertion; both test-debt, different tests/fixes.
- trade-trace-eo4 / trade-trace-qc7: Keep separate: malformed payload drain crash vs event_type filename sanitization; both exporter hardening, different failure modes/tests.
- trade-trace-67sg / trade-trace-7j1l: Keep separate: export warning/shareability boundary vs write-time scanning policy; adjacent security domain but distinct operational surfaces.

Intentional merges already made before materialization: DEBT-009 -> trade-trace-74b, DEBT-010 -> trade-trace-0r7, DEBT-030 -> trade-trace-9gs, DEBT-042 -> trade-trace-67sg. DEBT-032 deferred; DEBT-043 rejected as already-deferred/stub/open-work scope.

Action: no post-materialization duplicate closures. Future executors may merge adjacent implementation work only after reading bead bodies and confirming same root cause + same validation path.
