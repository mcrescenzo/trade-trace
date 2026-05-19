# trade-trace-mehh — Align optional embeddings docs and sqlite-vec capability reporting

Status: open
Type: task
Priority: P2
Labels: dead-code, deadcode-hunt, deadcode:refresh-20260519, domain:docs, domain:storage, needs-owner-confirmation, stale-contract

## Description

Context:
Domain: storage/docs optional embeddings capability.
Candidate: DC-REFRESH-001.

Dead-code / stale-contract claim:
`trade_trace.storage.database.has_sqlite_vec` appears unused internally while active docs and journal surfaces still present an inconsistent optional-embeddings capability story.

Evidence:
- `src/trade_trace/storage/database.py:173` defines `has_sqlite_vec`; excluding audits, reference search finds only this definition.
- `src/trade_trace/storage/database.py:154-155` uses `load_sqlite_vec_extension()` directly when persisted `embeddings.provider != "none"`.
- `src/trade_trace/tools/journal.py:63-75` sets `sqlite_vec_available = False` in `journal.init` rather than calling the helper.
- `docs/PRD.md:60` advertises `journal.init --enable-embeddings`, but live registry exposes `journal.init` without that option/behavior.
- `docs/PRD.md:113` says `sentence-transformers` is deferred to `[embeddings]`; `pyproject.toml` currently has `embeddings = ["sqlite-vec==0.1.6", "keyring>=25"]`.

Reference search scope:
Tracked `src`, `tests`, active docs, README, pyproject, excluding `docs/audits/**` and `audits/**` for final judgement.

Reference search commands / output summary:
- `git grep -n has_sqlite_vec -- ':!docs/audits/**' ':!audits/**'` -> definition only.
- `git grep -n 'enable-embeddings\|sentence-transformers' -- ':!docs/audits/**' ':!audits/**'` -> active PRD hits.
- `PYTHONPATH=src python3` registry enumeration -> `journal.init` exists; no `journal.init --enable-embeddings` schema/option.

Why it may be falsely alive:
`has_sqlite_vec` is importable and may be an intentional diagnostic/future status helper. Optional extension availability is environment-dependent, so removal needs owner confirmation.

Impact / risk of keeping:
Misleading capability and docs surfaces can confuse agents/operators about how embeddings are enabled, detected, and packaged.

Recommended action:
Decide whether to wire `has_sqlite_vec` into an intended status/init path, deprecate/remove it, or document it as a supported diagnostic helper; align PRD/pyproject/registry text either way.

Safe-removal validation:
If code changes, run embeddings/no-network focused tests. If docs-only, registry and pyproject readbacks must prove the docs no longer overclaim.

Duplicate check:
Overlaps closed docs cleanup beads `trade-trace-rzb`/`trade-trace-tka`, but this row combines current residual PRD dependency/command evidence with the currently unused capability helper; not a duplicate of an open bead as of the pre-mutation duplicate scan.

Acceptance criteria:
- Owner disposition recorded for `has_sqlite_vec`: supported API, internal helper to wire, or stale code to remove/deprecate.
- PRD optional-embeddings command/dependency text matches live registry and pyproject, or implementation/package metadata is changed intentionally.
- Validation output is attached: registry/pyproject readback and embeddings/no-network tests if code changes.

Provenance:
Discovered by repo-deadcode-hunt candidate DC-REFRESH-001 in docs/audits/deadcode-20260519T180524Z/candidate-matrix.json.


## Notes



## Acceptance

Owner disposition recorded; docs/registry/pyproject capability story aligns; validation output attached.
