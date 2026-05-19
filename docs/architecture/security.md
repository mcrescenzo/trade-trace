# Security: Threat Model and Mitigations

Status: clean planning draft. Date: 2026-05-18.
Source bead: trade-trace-4qf.

Companion docs: [operability.md](operability.md),
[contracts.md](contracts.md), [persistence.md](persistence.md),
[reports.md](reports.md).

## 1. Purpose

Trade Trace is a local-only journal/memory substrate. It does not execute
trades, hold custody of funds, or call brokers. The threat model is
therefore narrow but specific: a local user's machine, a single Python
process, and the persisted journal data.

This doc enumerates the assets, the realistic attackers, and the
mitigations that ship in MVP. It is not exhaustive; future surfaces
(remote sync, multi-user, hosted dashboard) will need their own
addendum.

## 2. Assets

| Asset | Where it lives | What it contains |
|---|---|---|
| Journal SQLite database | `$TRADE_TRACE_HOME/trade-trace.sqlite` | Every decision, thesis, forecast, outcome, source. The primary historical record. |
| JSONL export outbox | `$TRADE_TRACE_HOME/export/jsonl/<YYYY>/<MM>/<DD>/*.jsonl` | A redundant audit log: one file per committed event, replayable on a fresh DB (persistence.md §4). |
| Embeddings model weights | `$TRADE_TRACE_HOME/models/bge-small-en-v1.5/` (only after `embeddings.provider = local` or `tt model import --path ...`) | Local model artifacts verified against Trade Trace-pinned SHA-256/size lock data for an immutable HuggingFace revision. Source-provided manifests are not trusted. No agent input is sent over the network when `embeddings.provider = none` (the default). |
| OS keyring entry (P1) | OS keyring | When a hosted embeddings provider is wired (P1), the API key lives in the OS keyring, never in tool args. |

Notably *not* held: broker credentials, exchange API keys, wallet seed
phrases, signing keys. The PRD §2.8 product boundary forbids them; the
credential ban (§5 below) verifies the field surface in code.

## 3. Attacker Model

| Attacker | Capability | Realism |
|---|---|---|
| Local user (same UID) | Can read every file the journal owns. | Mitigation is file permissions (§4); a same-UID attacker can defeat them. The defense degrades gracefully — file perms are the floor, not the ceiling. |
| Other-UID user on the same host | Can read files unless `0600` perms are enforced. | Mitigated. |
| Package supply-chain | Malicious dependency could exfiltrate `$TRADE_TRACE_HOME` contents to a remote endpoint. | Partially mitigated: no outbound network at runtime by default (operability.md §10.1); embeddings download is opt-in. A compromised dependency could still execute code at install time — out of scope for MVP (the user reviewing `pip install` output is the gate). |
| Model-host phishing (P1) | If a hosted embeddings provider is wired, the host can see whatever text Trade Trace sends it to embed. | Mitigated by the redaction layer (sources tagged `sensitive`/`redacted`) and the opt-in flag. |
| Casual log leakage | Logs end up in a bug report, screen share, or chat paste. | Mitigated: log redactor (§5) strips secret-shaped substrings before write. |
| Casual export leakage | An operator shares a JSONL file or a `review.bundle` output without sanitizing. | Mitigated: bundle redaction rules (reports.md §5.3); export-time secret-shape warnings (operability.md §7); `sensitive` sources unconditionally omitted from bundles. |

## 4. File Permissions

- `$TRADE_TRACE_HOME` itself is created with mode `0700` (owner rwx;
  no group, no other).
- `$TRADE_TRACE_HOME/trade-trace.sqlite` is chmod-ed to `0600`
  immediately after creation, plus on any subsequent open if the
  current bits are wider (`src/trade_trace/storage/database.py`).
- Each JSONL export file is chmod-ed to `0600` after the atomic
  rename (`src/trade_trace/exporter.py::write_event_atomic`).
- Failures on platforms without POSIX permissions (Windows) are
  silently tolerated; the mitigation is best-effort, not load-bearing.

Tests pin the contract per acceptance: `tests/security/test_file_permissions.py`.

## 5. Secret-Pattern Scanning and Log Redaction

Per [operability.md](operability.md) §6.3 and bead trade-trace-sy1, the
MVP ships four registered patterns:

- `api_key` — `(sk-|pk_)[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}`
- `slack_token` — `xox[abprs]-[A-Za-z0-9-]+`
- `ethereum_address` — `0x[a-fA-F0-9]{40}`
- `jwt` — three base64url segments separated by `.`

Three layers consume the registry:

1. **Write-time guard**: every long-form free-text field is scanned
   before the row is inserted (full list in §6.5 below). A match
   raises `VALIDATION_ERROR` with `details.pattern_kind` and
   `details.match_offset` so the agent can strip the leaked bytes and
   retry. The secret never reaches the journal in the first place.
2. **Log redactor**: every log line passes through
   `trade_trace.security.redact_for_log()` before write. Matches are
   replaced by `REDACTED-<pattern_kind>`.
3. **Export-time warning**: `drain_outbox` scans the outgoing
   payload and appends a warning to the drain result (operability.md
   §7). The export still proceeds — the JSONL is an audit of what the
   journal contains, including any secret that slipped past the guard.
   The warning gives the operator a chance to redact before sharing.

Adding patterns at runtime via `trade_trace.security.register()` is
non-breaking. Tightening or removing built-in patterns requires a
contract version bump per [contracts.md](contracts.md) §8.

## 6. Credential Ban

The PRD §2.8 product boundary forbids broker, wallet, signing-key, and
seed-phrase fields. The ban is verified mechanically in
`tests/security/test_no_credentials.py`:

- No table column name in the DB schema matches the regex
  `wallet|broker|seed|signing|private_key|api_key`.
- No tool argument schema includes those field names.
- No `tool.description` mentions the words "credential", "wallet",
  "broker", or "private key".
- Tool handlers silently ignore any caller-supplied credential-shaped
  arguments (`api_key=...` on `venue.add` is dropped before the SQL
  binding).

Embeddings API keys (when a hosted provider is enabled in P1) are the
sole documented exception. Per the operability spec, they live in the
OS keyring; they never appear in tool args, schemas, or logs.

### 6.5 Free-text scan policy (bead trade-trace-7j1l)

Every persisted column whose contents are *long-form free text*
(notes, descriptions, reasons, pasted prose) is scanned by
`reject_if_contains_secrets` before the row is written. Narrow
identifier / enum / label columns are exempt because (a) their
contents come from controlled vocabularies and (b) rejecting common
identifiers would break ledger flow.

Scanned write-time:

| Tool                            | Field                                     |
|---------------------------------|-------------------------------------------|
| `thesis.add`                    | `body`, `falsification_criteria`, `exit_triggers`, `risk_notes`, `invalidation_condition`, `risk_unit_label` |
| `decision.add`                  | `reason`                                  |
| `decision.record_adherence`     | `reason`                                  |
| `instrument.add`                | `title`, `resolution_criteria_text`       |
| `forecast.add`                  | `resolution_rule_text`                    |
| `source.add`                    | `title`, `note`, `excerpt`, `extracted_text`, `summary` |
| `strategy.create` / `strategy.update` | `description`, `hypothesis`         |
| `playbook.create`               | `description`                             |
| `playbook.propose_version`      | `description`                             |
| `memory.retain` / `memory.reflect` | `body`, `title`                        |
| Every write tool                | `metadata_json` (recursively, including raw JSON strings) |

Exempt by design (documented, not scanned):

- Enum / vocabulary columns: `kind`, `side`, `status`, `stance`,
  `confidence_label`, `scoring_state`, `outcome_label`,
  `asset_class`, `node_type`, `playbook_status`, etc.
- Short identifier / label columns: `slug`, `name`, `tag`,
  `symbol`, `currency_or_collateral`, `external_id`,
  `yes_label`, `ref`, `uri`, `media_type`, `source_author`,
  `publisher`, `content_hash`, `hash_algorithm`,
  `license_or_terms_note`, `actor_id`, `agent_id`, `model_id`,
  `environment`, `run_id`, `request_id`, `review_by`.
- Reference / FK columns and timestamps: any `*_id`, `*_at`,
  `version`, `parent_*_id`, `provenance_reflection_node_id`.

Adding a new persisted free-text column to a migration requires:
1. Either calling `reject_if_contains_secrets` from the tool that
   writes it, **or** explicitly listing the column above as exempt.
2. A corresponding test in
   `tests/security/test_secret_pattern_writes.py`.

## 7. No Background Network, No Telemetry, No Auto-Update

- No HTTP client is constructed at startup. `journal.init` runs to
  completion with the network detached (`tests/security/test_no_network_default.py`).
- No analytics, telemetry, crash-reporter, or auto-update package is
  imported anywhere in `src/`. The grep audit in
  `tests/security/test_no_telemetry_packages.py` pins the set against
  the deny-list `{analytics, telemetry, sentry, mixpanel, segment,
  datadog, rollbar, posthog}`.
- The only opt-in outbound paths are embeddings providers. With the
  default `embeddings.provider = none`, Trade Trace creates no HTTP
  client, downloads no model files, and generates zero outbound traffic.
- The local embeddings path is behind an explicit network flag boundary:
  only `tt journal config_set --key embeddings.provider --value local
  --confirm` may perform the one-shot model download, and only when
  `$TRADE_TRACE_HOME/models/bge-small-en-v1.5/` is absent or fails
  verification against Trade Trace-pinned lock data. Re-running the switch
  after a verified model is present does not contact the network.
- The download allowlist is the pinned HuggingFace model repository URL
  `https://huggingface.co/BAAI/bge-small-en-v1.5/resolve/5c38ec7c405ec4b44b94cc5a9bb96e735b38267a/...`.
  That is consistent with the threat model because the operator has
  opted into local embeddings, no journal text or API key is uploaded,
  and every downloaded artifact is verified against Trade Trace-shipped
  relative-path, size, and SHA-256 lock entries before activation. The
  code does not fetch or trust a model repository manifest.
- Air-gapped installs use `tt model import --path <pre-staged
  BAAI/bge-small-en-v1.5> --confirm`. That path only reads local files,
  ignores any source-provided manifest as proof, rejects symlinks/path
  traversal, verifies the same pinned lock data, and copies only the
  allowlisted files into `$TRADE_TRACE_HOME/models/bge-small-en-v1.5/`;
  it performs zero outbound calls.

## 8. Redaction of `review.bundle` (Contract; Impl is P1)

Per [reports.md](reports.md) §5.3:

- `redaction_status = 'sensitive'` rows are **unconditionally omitted**
  from `review.bundle.data.sources`. The bundle's `caveats[]` records
  the omitted count.
- `redaction_status = 'redacted'` rows are included **with content
  stripped** — `body`, `extracted_text`, `excerpt`, `summary`, and
  `note` are dropped; metadata (kind, uri, retrieved_at, stance) is
  preserved.
- A final pass runs `redact_for_log()`-equivalent secret-pattern
  scrubbing over the bundle's outgoing strings.

MVP ships the contract surface and the omission rules; the full
bundle implementation lands in P1 per the reports.md §5.5 commitment.

## 9. Open Questions

1. **Embeddings provider keyring** — the OS keyring API is platform-
   specific; a P1 design doc will pin the library (`keyring` is the
   leading candidate) and the fallback behavior on headless hosts.
2. **Per-tool egress allowlist** — when network paths land, a per-tool
   allowlist (rather than process-wide on/off) would let an agent run
   `memory.recall` against a remote embedder without enabling
   arbitrary outbound traffic.
3. **Audit log of read operations** — `recall` and `report.*` are
   currently un-logged. A future audit-trail bead can decide whether to
   log them locally (privacy concern for the journal owner) or not.
