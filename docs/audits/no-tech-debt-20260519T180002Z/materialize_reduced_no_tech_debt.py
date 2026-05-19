#!/usr/bin/env python3
"""Materialize reduced no-tech-debt backlog after advisor/user review.

This script is intentionally repo-local and audit-friendly: it writes body files,
creates only narrowed/accepted Beads, relates duplicate owner Beads to the epic,
and records command output for readback.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
from datetime import datetime, timezone

REPO = pathlib.Path(__file__).resolve().parents[3]
RUN = pathlib.Path(__file__).resolve().parent
BODIES = RUN / "bead-bodies"
VERIFICATION = RUN / "verification"
BODIES.mkdir(parents=True, exist_ok=True)
VERIFICATION.mkdir(parents=True, exist_ok=True)

EPIC_ID = "trade-trace-gm28"
RUN_LABEL = "debt-run:20260519-no-tech-debt"

CREATES = [
    {
        "spec_id": "NTD-001",
        "title": "Add release distribution metadata validation before PyPI publish",
        "type": "task",
        "priority": "P3",
        "domain": "build-package-ci-release",
        "track": "maintenance",
        "risk": "low",
        "body": """Context:
Release/package validation debt surfaced by the no-tech-debt run 20260519T180002Z.

Technical-debt claim:
The tag-gated release workflow builds and publishes distributions without an explicit package metadata/README validation step such as `twine check`, and the local dev extras do not include a distribution metadata checker.

Evidence:
- .github/workflows/workflow.yml:66-72 installs only `build` and runs `python -m build`.
- .github/workflows/workflow.yml:80-97 downloads the dist artifact and publishes with `pypa/gh-action-pypi-publish@release/v1`.
- pyproject.toml:20-24 dev extras include pytest, ruff, and mypy but not build/twine or equivalent release metadata validation.

Carrying cost / risk:
A malformed long_description, package metadata issue, or README rendering problem can fail late in the publish path or produce a degraded package artifact. This is low-risk maintenance debt, not evidence of a current broken release.

Target paydown:
Add a bounded release validation step and local parity path: build distributions, run metadata validation, and document/run the same command locally without broad packaging redesign.

Non-goals / boundaries:
- Do not redesign packaging, versioning, or release automation beyond metadata validation.
- Do not publish, tag, or change package identity.

Routing / classification:
Maintenance, P3, low risk. This is intentionally not P1/P2 because the risk is release hygiene rather than a reproduced runtime defect.

Validation:
- python3 -m build
- python3 -m twine check dist/*
- Existing CI test/lint commands still pass.

Duplicate check:
Compared against live open Beads and existing console packaging work. Not a duplicate because console packaging Beads cover the future dashboard package, while this row covers the existing root Python package release workflow.

Acceptance criteria:
- Release workflow validates distribution metadata before publish.
- Local dev/release docs or extras expose the same validation command.
- Validation commands pass on a fresh dist build.
- No unrelated release/publishing changes.

Provenance:
repo-no-tech-debt 20260519T180002Z, reduced materialization row NTD-001.
""",
    },
    {
        "spec_id": "NTD-002",
        "title": "Investigate schema/meta diagnostics for non-table migrations",
        "type": "task",
        "priority": "P2",
        "domain": "storage-persistence-events-schema",
        "track": "investigation",
        "risk": "medium",
        "body": """Context:
Migration/schema recovery diagnostic debt surfaced by the no-tech-debt run 20260519T180002Z.

Technical-debt claim:
The stale meta/schema mismatch guard only reasons about tables first created by migrations. Column-only and trigger-only migrations are listed with empty table sets, so stale meta rows after those migrations can fall through to opaque SQLite DDL errors instead of actionable diagnostics.

Evidence:
- src/trade_trace/storage/migrations.py:1133-1138 documents `_MIGRATION_TABLES_CREATED` as table-creation based and says migrations 004, 009, and 010 have empty lists because they only add columns/triggers.
- src/trade_trace/storage/migrations.py:1148,1155 list migrations 004 and 010 as `[]`.
- src/trade_trace/storage/migrations.py:1183-1213 checks only future migration-created tables against sqlite_master.
- Lane probe reported a stale-meta replay through migration 004 producing `OperationalError: duplicate column name: risk_unit_label` instead of `SchemaMetaMismatchError`.

Carrying cost / risk:
Operators recovering from partial restores or stale meta rows may get raw SQLite errors for column/trigger drift even though the system appears to have a schema/meta diagnostic guard. Migration recovery behavior is high-blast-radius enough to require investigation before direct implementation.

Target paydown:
Investigate and propose the smallest safe extension to schema/meta diagnostics for non-table migrations: column presence, trigger presence, or an explicit documented limitation.

Non-goals / boundaries:
- Do not change migration ordering or repair historical DBs automatically.
- Do not broaden recovery semantics without documented operator guidance.

Routing / classification:
Investigation, P2, medium risk because migration/schema behavior has recovery blast radius.

Validation:
- Add/adjust in-memory migration tests covering stale meta around migration 004 and migration 010.
- Existing migration policy tests pass.

Duplicate check:
Distinct from prior table-created stale-meta guard work because this row is specifically about column/trigger-only migrations left out of `_MIGRATION_TABLES_CREATED`.

Acceptance criteria:
- Investigation documents whether column/trigger drift should be detected, explicitly out-of-scope, or handled by a separate repair workflow.
- If a fix is chosen, regression tests demonstrate typed diagnostics for non-table stale-meta drift.
- Operator-facing error or docs remain actionable and conservative.

Provenance:
repo-no-tech-debt 20260519T180002Z, reduced materialization row NTD-002.
""",
    },
    {
        "spec_id": "NTD-003",
        "title": "Decide semantic-key event policy alignment",
        "type": "task",
        "priority": "P3",
        "domain": "storage-persistence-events-schema",
        "track": "design",
        "risk": "low",
        "body": """Context:
Event/semantic-key policy drift surfaced by the no-tech-debt run 20260519T180002Z.

Technical-debt claim:
The audit found policy drift between semantic-key coverage and event-type policy, but this is a contract/design seam rather than a direct maintenance fix.

Evidence:
- Lane review covered src/trade_trace/events/semantic_keys.py, src/trade_trace/events/log.py, src/trade_trace/events/unit_of_work.py, and tests/contracts/test_event_enum_coverage.py.
- The lane classified the issue as semantic policy alignment, not a concrete failing behavior.

Carrying cost / risk:
Event taxonomy drift makes it harder to know whether new write paths need semantic keys, enum coverage, replay behavior, or migration hooks. Without a design decision, implementation tasks will either overfit tests or create inconsistent policy.

Target paydown:
Produce a small design decision: which event types require semantic keys, which are intentionally excluded, how tests enforce the boundary, and what validation command proves coverage.

Non-goals / boundaries:
- Do not rename existing event types or rewrite event storage as part of this decision.
- Do not create broad replay or migration work from this bead; create follow-ups only after the policy is settled.

Routing / classification:
Design, P3, low risk. Advisor specifically recommended downgrading this from direct paydown to design/investigation.

Validation:
- Design note references concrete files and chosen enforcement tests.
- Follow-up implementation beads, if any, name exact event families and validation commands.

Duplicate check:
No live duplicate was found by title scan; related storage/integrity bughunt Beads remain concrete failures and should not absorb this policy decision.

Acceptance criteria:
- Event semantic-key policy is explicitly documented.
- Tests/gaps needed to enforce the policy are listed as concrete follow-ups or shown to already exist.
- No behavior-changing code lands under this design bead without a follow-up task.

Provenance:
repo-no-tech-debt 20260519T180002Z, reduced materialization row NTD-003.
""",
    },
    {
        "spec_id": "NTD-004",
        "title": "Validate memory.link playbook_version endpoints against playbook_versions",
        "type": "task",
        "priority": "P2",
        "domain": "domain-tools-ledger-memory-playbook",
        "track": "maintenance",
        "risk": "medium",
        "body": """Context:
Memory/playbook graph validation debt surfaced by the no-tech-debt run 20260519T180002Z.

Technical-debt claim:
`memory.link` accepts `playbook_version` as a valid endpoint kind but does not verify that the target row exists in `playbook_versions`, even though that table now exists.

Evidence:
- src/trade_trace/tools/memory.py:69-73 includes `playbook_version` in VALID_MEMORY_ENDPOINTS.
- src/trade_trace/tools/memory.py:77-89 maps endpoint kinds to backing tables but omits `playbook_version`.
- src/trade_trace/tools/memory.py:90-94 says `review` and `playbook_version` lack backing tables in MVP/P1, which is stale because playbook infrastructure has landed.
- src/trade_trace/tools/memory.py:471-477 returns without checking when ENDPOINT_TABLES has no mapping.

Carrying cost / risk:
The graph can claim a validated edge to a phantom playbook version, weakening playbook provenance, review bundle traceability, and orphan detection.

Target paydown:
Add `playbook_version` endpoint existence validation against `playbook_versions` and cover missing/existing endpoint cases. If edge-audit orphan detection needs a separate change, create or link a follow-up rather than over-broadening this task.

Non-goals / boundaries:
- Do not redesign memory edge kinds or playbook version storage.
- Do not alter `review` endpoint behavior unless explicitly evidenced separately.

Routing / classification:
Maintenance, P2, medium risk. This is the direct endpoint-validation portion; broader edge-audit coverage remains separable.

Validation:
- Add/adjust tests for `memory.link` rejecting a missing playbook_version target with NOT_FOUND.
- Add/adjust tests accepting an existing playbook_version target.
- Existing playbook and memory link tests pass.

Duplicate check:
No live duplicate was found in open-title scans. This is distinct from broader MCP schema/dogfood issues because it is a storage validation boundary.

Acceptance criteria:
- `memory.link` validates playbook_version IDs against playbook_versions.
- Stale comments/docs around playbook_version lacking a backing table are corrected.
- Tests prove missing and existing playbook_version endpoints.
- No unrelated memory edge behavior changes.

Provenance:
repo-no-tech-debt 20260519T180002Z, reduced materialization row NTD-004.
""",
    },
    {
        "spec_id": "NTD-005",
        "title": "Design JSONL replay taxonomy for landed write surfaces",
        "type": "task",
        "priority": "P2",
        "domain": "domain-tools-ledger-memory-playbook",
        "track": "design",
        "risk": "medium",
        "body": """Context:
Import/replay design debt surfaced by the no-tech-debt run 20260519T180002Z.

Technical-debt claim:
Newer memory, playbook, and strategy write surfaces need a documented replay taxonomy before implementation tasks can safely decide which events are replayable, ignored, migrated, or rejected.

Evidence:
- Lane review covered src/trade_trace/tools/imports.py plus memory.py, playbook.py, strategy.py and relevant JSONL/import replay tests.
- The lane classified this as taxonomy/design debt, not a reproduced import failure with one obvious fix.

Carrying cost / risk:
Without a clear taxonomy, import/replay code can grow ad hoc branches that silently skip landed writes or replay them inconsistently. This affects portability and disaster-recovery confidence.

Target paydown:
Write a narrow replay taxonomy for landed write event families: memory, playbook, strategy, and any explicit exclusions. The output should name follow-up implementation tasks only after the policy is settled.

Non-goals / boundaries:
- Do not implement replay behavior inside this design bead.
- Do not change import/export formats without a follow-up task and compatibility check.

Routing / classification:
Design, P2, medium risk. Advisor recommended downgrading this from direct paydown to design.

Validation:
- Design artifact lists event families, replay action, compatibility notes, and candidate tests.
- Follow-up tasks, if created, include exact fixture/JSONL validation commands.

Duplicate check:
Distinct from bughunt rows about stale tests or specific broken import paths; this owns the policy taxonomy before implementation.

Acceptance criteria:
- A replay taxonomy decision exists for memory/playbook/strategy write surfaces.
- Each event family has an explicit replay/ignore/reject/migrate disposition and validation plan.
- Any implementation work is split into bounded follow-up Beads.

Provenance:
repo-no-tech-debt 20260519T180002Z, reduced materialization row NTD-005.
""",
    },
    {
        "spec_id": "NTD-006",
        "title": "Validate memory.retain meta_json object shape at direct retain boundary",
        "type": "task",
        "priority": "P2",
        "domain": "domain-tools-ledger-memory-playbook",
        "track": "maintenance",
        "risk": "medium",
        "body": """Context:
Memory-layer JSON validation debt surfaced by the no-tech-debt run 20260519T180002Z.

Technical-debt claim:
The direct `memory.retain` path serializes `meta_json` without asserting that it is an object, while adjacent normalization paths already reject non-object decoded meta_json.

Evidence:
- src/trade_trace/tools/memory.py:100-114 routes memory.retain into `_memory_retain_in_uow`.
- src/trade_trace/tools/memory.py:157 sets `meta_json = json.dumps(args.get("meta_json") or {}, sort_keys=True)`, which can serialize non-object JSON such as lists or strings instead of enforcing object shape.
- src/trade_trace/tools/memory.py:337-354 shows adjacent normalization logic that parses string meta_json and raises VALIDATION_ERROR when it does not decode to an object.

Carrying cost / risk:
Memory node metadata becomes schema-loose at the primary write boundary. Downstream recall, filters, and event payload consumers may assume object-shaped metadata and fail late or silently ignore unexpected shapes.

Target paydown:
Normalize and validate direct memory.retain meta_json so omitted/null becomes `{}`, JSON strings decode to objects or fail, and non-object decoded values produce VALIDATION_ERROR with a stable field detail.

Non-goals / boundaries:
- Do not introduce per-node-type metadata schemas in this task.
- Do not change valid object metadata semantics.

Routing / classification:
Maintenance, P2, medium risk.

Validation:
- Tests for omitted/null meta_json producing `{}`.
- Tests for JSON object string accepted.
- Tests for JSON list/string/scalar rejected with VALIDATION_ERROR field=meta_json.
- Existing memory.retain and recall tests pass.

Duplicate check:
No live duplicate was found by title scan. This is distinct from security metadata credential rows and from reflect-tag normalization.

Acceptance criteria:
- Direct memory.retain enforces object-shaped meta_json consistently.
- Error envelope details are stable for invalid meta_json.
- Existing object-shaped metadata behavior is preserved.
- No per-type schema redesign.

Provenance:
repo-no-tech-debt 20260519T180002Z, reduced materialization row NTD-006.
""",
    },
    {
        "spec_id": "NTD-007",
        "title": "Investigate projection rebuild diagnostics for corrupt memory recall JSON",
        "type": "task",
        "priority": "P2",
        "domain": "reports-projections-export",
        "track": "investigation",
        "risk": "medium",
        "body": """Context:
Projection rebuild observability debt surfaced by the no-tech-debt run 20260519T180002Z.

Technical-debt claim:
`rebuild_memory_node_stats` silently skips memory_recall_events rows whose `node_ids_returned` is corrupt JSON, making projection rebuilds appear successful while under-reporting source event problems.

Evidence:
- src/trade_trace/projections.py:327-339 documents rebuilding memory_node_stats from every memory_recall_events row.
- src/trade_trace/projections.py:349-352 selects all memory_recall_events in order.
- src/trade_trace/projections.py:355-358 catches `json.JSONDecodeError` and `continue`s with no count, warning, error, or diagnostic.

Carrying cost / risk:
Recovery/rebuild paths can create a clean-looking projection from incomplete source events. Operators cannot distinguish “no recall happened” from “recall rows were skipped.” The desired behavior needs a compatibility decision before implementation.

Target paydown:
Investigate and choose whether corrupt rows should fail rebuild, be counted in diagnostics, produce warnings, or be quarantined. Add a reproducible corrupt-state fixture for the chosen behavior.

Non-goals / boundaries:
- Do not change projection semantics without deciding compatibility with existing corrupt historical data.
- Do not broaden report/projection redesign.

Routing / classification:
Investigation, P2, medium risk. Advisor recommended investigation unless a reproducible corrupt-state fixture and behavior contract are added.

Validation:
- Corrupt memory_recall_events fixture/probe exists.
- Chosen behavior is covered by tests and documented in projection/recovery expectations.
- Existing projection rebuild idempotence tests still pass.

Duplicate check:
No live duplicate was found by title scan. This is distinct from concrete report bugs that attach wrong entities or advertise rejected group_by values.

Acceptance criteria:
- Investigation records fail/warn/count/quarantine decision for corrupt node_ids_returned JSON.
- Regression test proves the chosen behavior.
- Rebuild return/diagnostics are actionable and do not silently hide skipped source rows.

Provenance:
repo-no-tech-debt 20260519T180002Z, reduced materialization row NTD-007.
""",
    },
    {
        "spec_id": "NTD-008",
        "title": "Decide position_id reopen semantics for replay and projections",
        "type": "task",
        "priority": "P1",
        "domain": "reports-projections-export",
        "track": "design",
        "risk": "high",
        "body": """Context:
Position/replay semantic debt surfaced by the no-tech-debt run 20260519T180002Z.

Technical-debt claim:
The audit identified unsettled semantics around `position_id` reopen behavior during replay/projection rebuild. This is a domain contract decision, not a direct cleanup task.

Evidence:
- Lane review covered src/trade_trace/projections.py, src/trade_trace/exporter.py, and report/export/projection tests.
- Advisor review explicitly classified position_id reopen semantics as product/domain behavior requiring design first.

Carrying cost / risk:
Position identity affects replay determinism, projections, reports, and downstream auditability. A direct implementation task would force an executor to invent domain policy mid-fix.

Target paydown:
Decide and document whether reopening a position should preserve an identity, create a new identity linked to the old one, or be represented through explicit lifecycle events. Name the validation tests needed after the decision.

Non-goals / boundaries:
- Do not implement behavior changes in this design bead.
- Do not rewrite position storage, reports, or import/export without follow-up Beads.

Routing / classification:
Design, P1, high risk because it touches domain semantics and persistence/replay contracts.

Validation:
- Decision document states the chosen position_id reopen model and compatibility implications.
- Follow-up Beads include exact replay/projection/report tests.

Duplicate check:
No live duplicate was found by title scan. Related forecast/report bugs remain separate concrete failures.

Acceptance criteria:
- Reopen semantics are explicitly decided with examples.
- Compatibility and migration/replay implications are documented.
- Implementation follow-ups, if required, are split and bounded.

Provenance:
repo-no-tech-debt 20260519T180002Z, reduced materialization row NTD-008.
""",
    },
    {
        "spec_id": "NTD-009",
        "title": "Harden log redaction behavior beyond secret scan input cap",
        "type": "task",
        "priority": "P2",
        "domain": "security-boundaries",
        "track": "maintenance",
        "risk": "medium",
        "body": """Context:
Security-boundary debt surfaced by the no-tech-debt run 20260519T180002Z.

Technical-debt claim:
The same MAX_SCAN_INPUT_BYTES cap is used for write-time secret scanning and log redaction. The cap may be defensible for validation CPU bounds, but log redaction claims should not silently leave tail secrets unredacted.

Evidence:
- src/trade_trace/security/patterns.py:87-93 defines MAX_SCAN_INPUT_BYTES and says only the prefix is scanned beyond the cap.
- src/trade_trace/security/patterns.py:158-176 truncates scan_text inputs to the cap.
- src/trade_trace/security/patterns.py:190-197 documents redact_for_log as replacing every secret match so logs never carry original secret bytes.
- src/trade_trace/security/patterns.py:205 makes redact_for_log call scan_text(out), inheriting prefix-only scanning.

Carrying cost / risk:
A secret-like value after the cap can remain in redacted logs. Operators will trust redacted logs as a last-resort safety boundary, so silent tail bypass is materially different from rejecting overlarge write input.

Target paydown:
Split validation-scan policy from log-redaction policy, or otherwise make redaction fail closed/truncate safely for over-cap strings. Preserve ReDoS/CPU safeguards.

Non-goals / boundaries:
- Do not relax write-time secret validation or remove scan caps without a replacement bound.
- Do not broaden into unrelated secret-pattern false positives; trade-trace-aqpf owns a known Polymarket false-positive issue.

Routing / classification:
Maintenance/security-hardening, P2, medium risk. Offset semantics discovered in the lane are not included here unless a separate API/design decision proves they share the same fix.

Validation:
- Test that redact_for_log does not leak a secret after the scan cap or explicitly emits a safe failure/truncation marker.
- Existing secret-pattern tests still pass.
- Performance/CPU bound remains documented.

Duplicate check:
Related to but distinct from trade-trace-aqpf, which covers public Polymarket condition IDs as false positives; this row covers tail redaction bypass.

Acceptance criteria:
- Log redaction handles over-cap inputs safely.
- Validation scan caps remain bounded.
- Tests cover tail-secret behavior.
- No unrelated pattern registry or false-positive changes.

Provenance:
repo-no-tech-debt 20260519T180002Z, reduced materialization row NTD-009.
""",
    },
]

MERGES = [
    {
        "id": "trade-trace-kynj",
        "row": "CLI unknown-command JSON envelope",
        "reason": "Merged instead of fresh no-tech-debt bead; live bughunt bead already owns the concrete bug.",
    },
    {
        "id": "trade-trace-pybt",
        "row": "CLI argument grammar/parser behavior",
        "reason": "Merged/related; live bughunt bead owns repeated/comma array parser contract failure.",
    },
    {
        "id": "trade-trace-68ew",
        "row": "Golden parity developer-home leak",
        "reason": "Merged into existing golden parity/test-harness bug.",
    },
    {
        "id": "trade-trace-boqe",
        "row": "Golden/NDJSON stale review.bundle expectation",
        "reason": "Merged into existing test expectation bug rather than generic coverage debt.",
    },
    {
        "id": "trade-trace-3i33",
        "row": "MCP stdio/schema/help coverage",
        "reason": "Related rather than duplicated; existing bead owns missing tool schemas/help for agent-safe MCP usage.",
    },
    {
        "id": "trade-trace-0tdt",
        "row": "PRD embeddings flag docs drift",
        "reason": "Merged into existing docs-truth bug for journal.init --enable-embeddings no-op.",
    },
    {
        "id": "trade-trace-mehh",
        "row": "Embeddings/sqlite-vec docs capability drift",
        "reason": "Merged into existing deadcode/docs-truth bead.",
    },
    {
        "id": "trade-trace-ftnu",
        "row": "Residual report/watch docs drift",
        "reason": "Merged into existing stale report docs bead.",
    },
    {
        "id": "trade-trace-cs0r",
        "row": "Report compare docs/API contract drift",
        "reason": "Merged into existing public API stale-contract bug.",
    },
]

DEFERRED = [
    {"row": "test fixture idempotency enforcement", "reason": "Deferred/merge-only due live dirty-history contamination and existing idempotency work; do not create fresh until clean-tree reproduction."},
    {"row": "markdown/link checker gap", "reason": "Weak without concrete broken anchor/link evidence or release gate failure."},
    {"row": "dogfood fixture isolation", "reason": "Weak without concrete cross-test contamination evidence."},
    {"row": "security match offset semantics", "reason": "Design/API semantics; not materialized with redaction-cap task."},
    {"row": "edge-audit playbook_version orphan coverage", "reason": "Split from direct memory.link endpoint validation; create later only if separate edge-audit evidence warrants it."},
]

log: list[dict[str, object]] = []
created_ids: list[str] = []
related_existing: list[str] = []

def run_bd(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(["bd", *args], cwd=REPO, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    log.append({"cmd": ["bd", *args], "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
    if check and proc.returncode != 0:
        raise RuntimeError(f"bd command failed: {' '.join(['bd', *args])}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return proc

def relate(a: str, b: str) -> None:
    proc = run_bd(["dep", "relate", a, b], check=False)
    # Existing relation or alternate graph edge should not abort materialization.
    if proc.returncode != 0 and "already" not in (proc.stderr + proc.stdout).lower():
        raise RuntimeError(f"relate failed: {a} {b}\n{proc.stdout}\n{proc.stderr}")

# Pre snapshots
for name, args in {
    "pre_dep_cycles.txt": ["dep", "cycles"],
    "pre_dep_list_epic.txt": ["dep", "list", EPIC_ID],
    "pre_graph_epic.txt": ["graph", EPIC_ID],
}.items():
    p = run_bd(args, check=False)
    (VERIFICATION / name).write_text(f"$ bd {' '.join(args)}\nrc={p.returncode}\n\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}\n")

# Write matrix/disposition artifacts before mutation.
prewrite_packet = {
    "repo": str(REPO),
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "epic_id": EPIC_ID,
    "mode": "reduced backlog-materialization after advisor/user gate",
    "create_specs": [{k: v for k, v in item.items() if k != "body"} for item in CREATES],
    "merge_specs": MERGES,
    "deferred_rows": DEFERRED,
    "blocked_live_probe_caveat": "Do not retry bd show trade-trace-cpz2; prior tool run was blocked by policy/user denial. Idempotency row is therefore deferred/merge-only, not freshly materialized.",
}
(RUN / "prewrite-materialization-packet.json").write_text(json.dumps(prewrite_packet, indent=2, sort_keys=True))

# Create new narrowed Beads.
for item in CREATES:
    body_path = BODIES / f"{item['spec_id']}.md"
    body_path.write_text(item["body"])
    labels = [
        "tech-debt",
        "repo-no-tech-debt",
        RUN_LABEL,
        f"domain:{item['domain']}",
        f"track:{item['track']}",
        f"risk:{item['risk']}",
    ]
    proc = run_bd([
        "create",
        item["title"],
        "--type", item["type"],
        "--priority", item["priority"],
        "--labels", ",".join(labels),
        "--body-file", str(body_path.relative_to(REPO)),
        "--acceptance", "See description acceptance criteria and provenance.",
        "--json",
    ])
    obj = json.loads(proc.stdout)
    item["created_id"] = obj["id"]
    created_ids.append(obj["id"])
    relate(EPIC_ID, obj["id"])

# Relate/update existing owner Beads for merged rows.
note_prefix = "repo-no-tech-debt 20260519T180002Z disposition: "
for merge in MERGES:
    note = f"{note_prefix}{merge['row']} was merged/related here rather than duplicated. {merge['reason']} Epic: {EPIC_ID}."
    run_bd(["update", merge["id"], "--append-notes", note])
    relate(EPIC_ID, merge["id"])
    related_existing.append(merge["id"])

# Create final verification gate blocked by new narrowed beads and merged live owners.
blockers = created_ids + related_existing
final_body = BODIES / "FINAL-verification.md"
final_body.write_text("""Context:
Final verification gate for repo-no-tech-debt run 20260519T180002Z.

This task stays open while materialized/merged no-tech-debt backlog items remain unresolved. It is not proof that the repo is debt-free; it is the closeout gate for the reduced materialization program after advisor/user review.

Materialized and merged blocker IDs:
{blockers}

Deferred / not materialized:
{deferred}

Validation / close rule:
- Every blocker is closed, explicitly deferred/superseded, or has a documented human decision.
- Coverage/disposition artifacts are present under docs/audits/no-tech-debt-20260519T180002Z.
- bd dep cycles reports no cycles.
- Duplicate scan has a disposition note.
- Candidate-integrity readback confirms created/related Beads include evidence, carrying cost/risk, bounded paydown or design/investigation boundary, validation/gap, duplicate rationale, labels, and provenance.
""".format(
        blockers="\n".join(f"- {bid}" for bid in blockers),
        deferred="\n".join(f"- {d['row']}: {d['reason']}" for d in DEFERRED),
    )
)
proc = run_bd([
    "create",
    "Final verification: reduced no-tech-debt backlog 2026-05-19",
    "--type", "task",
    "--priority", "P2",
    "--labels", ",".join(["tech-debt", "repo-no-tech-debt", RUN_LABEL, "final-gate"]),
    "--body-file", str(final_body.relative_to(REPO)),
    "--acceptance", "See description close rule and blocker list.",
    "--json",
])
final_id = json.loads(proc.stdout)["id"]
relate(EPIC_ID, final_id)
for bid in blockers:
    run_bd(["dep", "add", final_id, bid])

# Post snapshots and disposition matrix.
matrix = []
for item in CREATES:
    matrix.append({
        "spec_id": item["spec_id"],
        "title": item["title"],
        "coordinator_disposition": "materialized",
        "materialized_bead_id": item["created_id"],
        "track": item["track"],
        "risk": item["risk"],
        "domain": item["domain"],
    })
for merge in MERGES:
    matrix.append({
        "title": merge["row"],
        "coordinator_disposition": "merged_into_existing",
        "merged_into_bead_id": merge["id"],
        "reason": merge["reason"],
    })
for deferred in DEFERRED:
    matrix.append({
        "title": deferred["row"],
        "coordinator_disposition": "deferred_not_materialized",
        "reason": deferred["reason"],
    })
(RUN / "central-debt-matrix-reduced.json").write_text(json.dumps(matrix, indent=2, sort_keys=True))

for name, args in {
    "post_dep_cycles.txt": ["dep", "cycles"],
    "post_dep_list_epic.txt": ["dep", "list", EPIC_ID],
    "post_graph_epic.txt": ["graph", EPIC_ID],
    "post_dep_list_final_gate.txt": ["dep", "list", final_id],
    "post_open_no_tech.txt": ["list", "--status", "open", "--flat", "--limit", "0", "--sort", "id"],
    "post_in_progress.txt": ["list", "--status", "in_progress", "--flat", "--limit", "0", "--sort", "id"],
}.items():
    p = run_bd(args, check=False)
    (VERIFICATION / name).write_text(f"$ bd {' '.join(args)}\nrc={p.returncode}\n\nSTDOUT:\n{p.stdout}\nSTDERR:\n{p.stderr}\n")

readback_ids = created_ids + related_existing + [final_id, EPIC_ID]
readbacks = {}
for bid in readback_ids:
    p = run_bd(["show", bid, "--json"], check=False)
    readbacks[bid] = {"returncode": p.returncode, "stdout": p.stdout, "stderr": p.stderr}
(VERIFICATION / "readbacks.json").write_text(json.dumps(readbacks, indent=2, sort_keys=True))

out = {
    "epic_id": EPIC_ID,
    "created_ids": created_ids,
    "related_existing_ids": related_existing,
    "final_gate_id": final_id,
    "deferred_rows": DEFERRED,
    "command_log": log,
}
(RUN / "mutation-output.json").write_text(json.dumps(out, indent=2, sort_keys=True))

summary_md = f"""# No-tech-debt reduced materialization 2026-05-19

Epic: {EPIC_ID}
Final gate: {final_id}

## New narrowed Beads
{chr(10).join(f'- {item["created_id"]}: {item["title"]} ({item["track"]}, {item["priority"]})' for item in CREATES)}

## Existing Beads reused instead of duplicated
{chr(10).join(f'- {m["id"]}: {m["row"]} — {m["reason"]}' for m in MERGES)}

## Deferred / not materialized
{chr(10).join(f'- {d["row"]}: {d["reason"]}' for d in DEFERRED)}

## Notes
- This is a reduced materialization after advisor/user review, not a claim that the repo has no tech debt.
- Idempotency fixture debt was not freshly materialized because the prior `bd show trade-trace-cpz2` probe was denied and must not be retried in this session.
- Relation-based epic membership is used for navigation; final-gate blocking dependencies are used for closeout sequencing.
"""
(RUN / "materialization-summary.md").write_text(summary_md)

print(json.dumps({"created_ids": created_ids, "related_existing_ids": related_existing, "final_gate_id": final_id}, indent=2))
