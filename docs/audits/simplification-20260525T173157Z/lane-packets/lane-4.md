## What I did

Read-only simplification review for assigned domain `adapter-market-security` in `/home/hermes/code/trade-trace` at commit `d37136e9684138d9f9540f2a71860f36eba354f5`.

Inspected:

- `src/trade_trace/adapters/polymarket/**`
- `src/trade_trace/tools/adapter_polymarket.py`
- `src/trade_trace/tools/market_bind.py`
- `src/trade_trace/tools/market_scan.py`
- relevant security tests under `tests/security/`
- relevant integration tests under `tests/integration/`
- `docs/architecture/security.md`
- `docs/architecture/security-adapter-investigation.md`
- `docs/architecture/market-scan-contract.md`

Validation run:

```bash
python -m pytest \
  tests/integration/test_adapter_polymarket_offline.py \
  tests/integration/test_adapter_polymarket_no_rpc.py \
  tests/integration/test_market_scan_dry_run.py \
  tests/integration/test_market_scan_guided_e2e.py \
  tests/security/test_adapter_endpoint_policy.py \
  tests/security/test_adapter_url_scrubbing.py \
  -q
```

Result: `36 passed in 0.56s`

Also spot-ran:

```bash
python -m pytest \
  tests/security/test_adapter_endpoint_policy.py \
  tests/security/test_adapter_url_scrubbing.py \
  tests/integration/test_market_bind.py \
  -q
```

Result: `9 passed in 0.07s`

No files were created or modified.

---

## Coverage accounting

### In scope and reviewed

| Area | Files / evidence handles |
|---|---|
| Polymarket adapter client/config/retry/errors/cache | `src/trade_trace/adapters/polymarket/client.py`, `config.py`, `errors.py`, `retry.py`, `cache.py` |
| Adapter-backed tools | `src/trade_trace/tools/adapter_polymarket.py` |
| Market bind | `src/trade_trace/tools/market_bind.py` |
| Market scan dry-run/promote | `src/trade_trace/tools/market_scan.py` |
| Adapter/security tests | `tests/security/test_adapter_endpoint_policy.py`, `test_adapter_url_scrubbing.py`, `test_no_network_default.py`, `tests/integration/test_adapter_polymarket_offline.py`, `test_adapter_polymarket_no_rpc.py` |
| Market bind/scan tests | `tests/integration/test_market_bind.py`, `test_market_scan_dry_run.py`, `test_market_scan_guided_e2e.py` |
| Architecture contracts | `docs/architecture/security.md`, `security-adapter-investigation.md`, `market-scan-contract.md` |

### Explicitly avoided as prior/covered work

Did **not** propose candidates that duplicate known prior coverage:

- credential/secret-key vocabulary
- secret scanning public adapter
- no-network fixture consolidation
- endpoint policy/security adapter investigation
- market-scan guided contract
- explicit adapter/no default network boundary
- source.attach metadata
- weakening no-network-by-default or adapter opt-in behavior

---

# Candidate records

## AMS-SIMP-001 — Extract a shared `markets` row projection/serializer for bind, refresh, and cache-hit returns

**Complexity class:** duplication / schema-shape coupling / SQL projection drift

**Evidence**

Observed repeated hand-maintained `markets` column projections and tuple-to-dict mapping across:

- `src/trade_trace/tools/adapter_polymarket.py`
  - cache-hit `SELECT id,source,external_id,title,question,url,state,mechanism,resolution_source,ambiguity_kind,bound_via,metadata_json,venue_metadata_json,created_at FROM markets WHERE id=?` at lines 122–141
  - existing-row lookup/update path at lines 147–159
  - compatibility instrument projection at lines 179–185
- `src/trade_trace/tools/market_bind.py`
  - idempotency replay projection at lines 133–153
  - existing natural-key projection at lines 155–176
  - `_market_row_dict(row)` tuple-index serializer at lines 243–267

Current behavior is correct but brittle: the same conceptual market row shape is represented by several SQL strings and tuple index maps, with different field subsets.

**Observed facts**

- `market.bind` manually maps 22 columns in `_market_row_dict`.
- `adapter_polymarket._upsert_market` has a separate cache-hit return dict with a smaller but overlapping market shape.
- Existing behavior is well covered by `tests/integration/test_market_bind.py` and adapter tests.

**Inferences**

- A future `markets` schema or output-shape adjustment can easily update one projection but not another.
- This is accidental complexity, not intentional domain complexity.

**Assumptions**

- Public response shapes for `market.bind`, `market.refresh`, and cache-hit refresh should remain stable.
- No migration is desired.

**Open questions**

- Should adapter cache-hit responses intentionally omit fields like `opened_at`, `close_at`, `actor_id` that `market.bind` returns? If yes, helper should support explicit subset selection rather than forcing one superset.

**Behavior contract**

Preserve:

- exact existing SQL semantics
- current response keys for each public tool path
- idempotency replay metadata behavior
- adapter cache-hit behavior
- no network boundary

**Cost**

Small. Likely one helper module/function near `market_bind.py` or a private utility in `tools/_market_rows.py`.

**Benefit**

- Removes duplicated tuple-index mapping.
- Reduces schema-drift risk.
- Makes market row shape explicit and easier to audit.
- Simplifies future market-related changes without behavior changes.

**Refactor shape**

Add private helpers such as:

```python
MARKET_ROW_COLUMNS = (
    "id", "source", "external_id", "title", "question", "url", "state",
    "mechanism", "resolution_source", "ambiguity_kind", "bound_via",
    "opened_at", "close_at", "closed_for_trading_at", "resolving_at",
    "resolved_at", "voided_at", "ambiguous_at", "venue_metadata_json",
    "metadata_json", "created_at", "actor_id",
)

def market_select_sql(prefix: str = "") -> str: ...
def market_row_dict(row) -> dict[str, Any]: ...
def market_row_subset(row, keys: Iterable[str]) -> dict[str, Any]: ...
```

Then use it from:

- `market_bind._market_bind`
- `market_bind._market_row_dict`
- `adapter_polymarket._upsert_market` cache-hit path, if compatible

**Non-goals**

- Do not change public tool response keys.
- Do not alter the `markets` table schema.
- Do not merge manual `market.bind` and adapter-backed `market.refresh` behaviors.
- Do not change adapter opt-in/network behavior.

**Behavior-preservation plan**

1. Introduce helper with identical column order.
2. Replace one projection at a time.
3. Assert returned dicts are byte/field equivalent in existing tests.
4. Add a narrow unit test for helper column order if needed.

**Validation command/gap**

Run:

```bash
python -m pytest \
  tests/integration/test_market_bind.py \
  tests/integration/test_adapter_polymarket_offline.py \
  tests/integration/test_adapter_polymarket_no_rpc.py \
  tests/integration/test_market_fetch.py \
  -q
```

Gap: Existing tests likely catch functional behavior but may not pin every response key for adapter cache-hit. Add a minimal cache-hit response-shape assertion if changing that path.

**Size / risk / priority / confidence**

- Size: S
- Risk: Low
- Priority: P2
- Confidence: High

**Why-not-style**

This is not formatting/style. It removes duplicated schema coupling and tuple-index drift risk in a storage-facing boundary.

**Intentional complexity check**

The separation between manual bind and adapter refresh is intentional; the duplicate row projection is not. Keep behavioral separation, only centralize the row shape.

**Duplicate/overlap notes**

Does not duplicate prior known coverage. Related to market binding/scanning but not the already-covered guided market-scan contract.

**Proposed bead body / acceptance**

Title: `Simplify market row projection helpers across market.bind and Polymarket refresh`

Body:

- Add private market row projection/serialization helper.
- Replace duplicated `markets` SELECT column lists and tuple-index serializers in `market_bind.py` and compatible adapter cache-hit paths.
- Preserve exact public response shapes and idempotency behavior.
- No network/config/security behavior changes.

Acceptance:

- Existing market bind and adapter tests pass.
- Public `market.bind` replay and duplicate-natural-key responses are unchanged.
- Adapter refresh cache-hit response is unchanged or explicitly covered.
- No new network access paths.

**Coordinator disposition recommendation**

Accept as additive simplification candidate.

---

## AMS-SIMP-002 — Consolidate Polymarket HTTP/JSON-RPC retry loop without changing endpoint policy

**Complexity class:** control-flow duplication / security-sensitive egress boundary

**Evidence**

`src/trade_trace/adapters/polymarket/client.py` contains two similar bounded retry loops:

- `get_json()` lines 113–147
- `polygon_rpc()` lines 161–199

Both handle:

- enabled/config guard
- endpoint validation
- `httpx.ReadTimeout`
- generic `httpx.TransportError`
- retryable HTTP statuses
- invalid JSON
- sanitized endpoint details
- response logging
- bounded sleep/backoff

Differences are real but local:

- GET vs POST
- Gamma endpoint vs Polygon RPC endpoint
- JSON-RPC error classification in `polygon_rpc`
- error messages

**Observed facts**

- Endpoint allowlist and TLS validation are currently centralized in `_validate_endpoint`.
- Sanitization flows through `error_details(endpoint=...)`.
- Tests pin endpoint policy and scrubbing:
  - `tests/security/test_adapter_endpoint_policy.py`
  - `tests/security/test_adapter_url_scrubbing.py`
  - adapter retry tests in `tests/integration/test_adapter_polymarket_offline.py`

**Inferences**

- Duplicated retry loops increase the chance of future divergence in security or retry semantics.
- A private request helper could preserve endpoint validation while reducing duplicated exception/status handling.

**Assumptions**

- No new dependency or tenacity refactor is needed.
- Behavior should remain synchronous and explicit.
- Tests should not perform live network.

**Open questions**

- Should JSON-RPC error handling stay in `polygon_rpc()` after a shared HTTP JSON request helper returns the parsed payload? That is likely safest.

**Behavior contract**

Preserve:

- disabled-by-default fail-closed behavior
- HTTPS and allowed-host checks before HTTP client use
- retry count/backoff behavior
- retryable status semantics
- JSON-RPC retry semantics
- scrubbed endpoint details
- no response body logging
- current error codes/messages unless intentionally covered

**Cost**

Small-to-medium. Security-sensitive because it touches egress code, so refactor should be incremental.

**Benefit**

- Reduces duplicated retry/error code.
- Makes endpoint/error scrubbing consistency easier to audit.
- Lowers future drift risk between Gamma and Polygon RPC paths.

**Refactor shape**

Introduce a private helper, e.g.:

```python
def _request_json(
    self,
    *,
    method_label: str,
    endpoint: str,
    send: Callable[[httpx.Client], httpx.Response],
    timeout_message: str,
    transport_message: str,
    http_message: str,
) -> Any:
    ...
```

Use from:

- `get_json()`
- `polygon_rpc()`

Keep JSON-RPC payload error classification in `polygon_rpc()` after `_request_json`.

**Non-goals**

- Do not broaden allowed hosts.
- Do not change TLS policy.
- Do not add live-network tests.
- Do not change default adapter disabled behavior.
- Do not change retry constants.

**Behavior-preservation plan**

1. Add helper under `PolymarketClient`.
2. Port `get_json()` first and run adapter tests.
3. Port `polygon_rpc()` next, keeping JSON-RPC error handling outside helper.
4. Verify endpoint policy tests still prove rejection before client construction.

**Validation command/gap**

Run:

```bash
python -m pytest \
  tests/security/test_adapter_endpoint_policy.py \
  tests/security/test_adapter_url_scrubbing.py \
  tests/integration/test_adapter_polymarket_offline.py \
  tests/integration/test_adapter_polymarket_no_rpc.py \
  tests/integration/test_resolution_fetch.py \
  -q
```

Gap: Existing tests cover many retry branches, but may not explicitly assert HTTP client is not constructed for all invalid Polygon endpoint variants. If refactored, add one fake-client guard if absent.

**Size / risk / priority / confidence**

- Size: M
- Risk: Medium due to security-sensitive egress path
- Priority: P2
- Confidence: Medium-high

**Why-not-style**

This reduces duplicated fail-closed network and retry machinery in a security boundary; it is not a cosmetic change.

**Intentional complexity check**

Separate Gamma and Polygon endpoint policies are intentional. The repeated loop mechanics are accidental. Preserve separate validation inputs and JSON-RPC classification.

**Duplicate/overlap notes**

Adjacent to prior endpoint policy/security investigation, but not duplicative if scoped strictly to implementation deduplication after behavior is already characterized by tests. If coordinator considers endpoint policy active prior coverage, defer or mark design-first.

**Proposed bead body / acceptance**

Title: `Deduplicate Polymarket client retry/request loop while preserving endpoint policy`

Body:

- Extract shared private request/JSON retry helper for Gamma GET and Polygon RPC POST.
- Keep TLS/host allowlist validation and adapter-enabled checks unchanged.
- Keep JSON-RPC error classification behavior unchanged.
- Preserve endpoint scrubbing and no-body logging.

Acceptance:

- Existing adapter endpoint, URL scrubbing, offline, no-RPC, and resolution-fetch tests pass.
- No live network tests added.
- Invalid endpoint paths still fail before HTTP client construction.
- Error details remain scrubbed and response bodies remain absent.

**Coordinator disposition recommendation**

Accept, but treat as security-sensitive and require tests before merge.

---

## AMS-SIMP-003 — Generate or share `market.scan` schema/action metadata from the Pydantic model/constants to avoid duplicate contract drift

**Complexity class:** duplicated validation/schema metadata / public contract drift

**Evidence**

`src/trade_trace/tools/market_scan.py` defines the same input contract in multiple places:

- Pydantic model:
  - `MarketScanDryRunInput` lines 31–53
  - `MarketScanPromoteInput` lines 56–60
- manual JSON-schema-like dict:
  - `_SCHEMA` lines 79–103
  - `_PROMOTE_SCHEMA` lines 105–112
- examples:
  - `_EXAMPLE_MINIMAL` lines 62–68
  - `_EXAMPLE_RICH` lines 70–77
- allowed actions:
  - `_ALLOWED_ACTIONS = {"watch", "skip", "paper_enter"}` line 23
  - schema enum repeats `["watch", "skip", "paper_enter"]` line 93
  - runtime check message repeats action list line 177
  - registry metadata repeats action list in enum notes lines 473 and 487

Tests pin the schema and behavior:

- `tests/integration/test_market_scan_dry_run.py`
- `tests/integration/test_market_scan_guided_e2e.py`
- `docs/architecture/market-scan-contract.md`

**Observed facts**

- Runtime validation is Pydantic-based.
- Registry/tool schema is manually maintained.
- Allowed action vocabulary is central in one constant but repeated in schema/message metadata.

**Inferences**

- Future action or field additions can update runtime validation without updating schema/tool metadata, or vice versa.
- This is accidental public-contract duplication.

**Assumptions**

- Exact schema output shape may matter for tool consumers.
- A full Pydantic-generated JSON Schema switch might be too behavior-visible unless carefully normalized.

**Open questions**

- Are consumers depending on the exact handcrafted `_SCHEMA` dict shape/order, or only semantic contents?
- Does `tool.schema` expose this schema as a stable API requiring byte-level preservation?

**Behavior contract**

Preserve:

- `market.scan.dry_run` read-only / no DB writes
- no fetch/no advice/no trade execution boundary
- accepted inputs and current validation errors
- current tool schema semantics
- existing ordered call plan and promote hash behavior

**Cost**

Small if only sharing constants/schema fragments; medium if switching to generated Pydantic JSON Schema.

**Benefit**

- Reduces drift between validation and public schema.
- Easier to safely add/remove action vocabulary later.
- Makes the no-advice caller-selected action boundary easier to audit.

**Refactor shape**

Conservative additive approach:

1. Define stable action tuple once:

```python
_ALLOWED_ACTIONS = ("watch", "skip", "paper_enter")
_ALLOWED_ACTION_SET = frozenset(_ALLOWED_ACTIONS)
```

2. Reuse it in:
   - runtime enum check
   - schema enum
   - decision-matrix schema filter
   - error/recovery text
   - registry enum notes if feasible

3. Optionally add small schema builder:

```python
def _market_scan_schema(*, promote: bool = False) -> dict[str, Any]:
    ...
```

rather than maintaining `_SCHEMA` and `_PROMOTE_SCHEMA` as divergent literals.

Avoid a full Pydantic schema replacement unless the output compatibility is characterized.

**Non-goals**

- Do not change `market.scan` public input contract.
- Do not change promote hash canonicalization.
- Do not add advice/action selection.
- Do not change promote transaction semantics.
- Do not expose `market.scan.*` in default MCP catalog if intentionally hidden without `include_legacy=True`.

**Behavior-preservation plan**

1. Start by replacing repeated action literals with one tuple.
2. Add/adjust a test that schema enum equals the central allowed action tuple.
3. Only then consider schema-builder extraction.

**Validation command/gap**

Run:

```bash
python -m pytest \
  tests/integration/test_market_scan_dry_run.py \
  tests/integration/test_market_scan_guided_e2e.py \
  -q
```

Gap: Existing tests check key schema fragments, ordered calls, hash stability, no DB mutation, and e2e promotion. They likely do not byte-compare full `tool.schema`. If exact schema shape matters, add snapshot-style semantic assertions before larger refactor.

**Size / risk / priority / confidence**

- Size: S for action/schema-fragment sharing; M for full schema generation
- Risk: Low for conservative approach; medium for generated schema replacement
- Priority: P3
- Confidence: High for conservative candidate

**Why-not-style**

This addresses contract drift between runtime validation and exposed tool schema. It is not naming/formatting-only.

**Intentional complexity check**

The dry-run/promote contract is intentionally explicit and safety-focused. The duplication of the action enum and schema fragments is not essential to that safety; centralizing constants can preserve clarity.

**Duplicate/overlap notes**

Does not duplicate the already-shipped market-scan guided contract. This is an implementation simplification beneath that contract.

**Proposed bead body / acceptance**

Title: `Centralize market.scan action/schema metadata to reduce contract drift`

Body:

- Reuse one stable allowed-action tuple across runtime validation, JSON schema enum, error text, decision matrix filter, and registry notes.
- Optionally wrap `_SCHEMA`/`_PROMOTE_SCHEMA` construction in a small builder to avoid divergent literal copies.
- Preserve existing dry-run/promote behavior and public schema semantics.

Acceptance:

- Existing market-scan dry-run/promote integration tests pass.
- `tool.schema` for `market.scan.dry_run` and `market.scan.promote` still exposes `watch`, `skip`, `paper_enter`.
- Promote hash for existing test bundle remains stable.
- No DB writes or network calls are introduced in dry-run.

**Coordinator disposition recommendation**

Accept as low-risk additive simplification, preferably limited to central constants/schema builder rather than full Pydantic schema replacement.

---

## Candidates considered but rejected / not filed

### URL scrubbing path-token hardening

I noticed `scrub_endpoint()` strips scheme, credentials, query, and fragment, but intentionally preserves path segments. Tests currently assert this behavior, e.g. `tests/security/test_adapter_url_scrubbing.py` expects `/rpc/v2/APIKEY123` to remain in the scrubbed endpoint, and adapter tests expect path-like RPC values in some details. Prior coverage explicitly includes URL scrubbing/security boundaries. Changing this could be security-hardening, but it is not a behavior-preserving simplification and may duplicate prior work. Rejected for this lane.

### Tightening endpoint allowlist

`PolymarketClient` has explicit Gamma host and Polygon RPC host/suffix allowlists. This is security-sensitive and already covered by endpoint policy tests/investigation. No simplification proposed because behavior changes could weaken or unexpectedly narrow opt-in adapter behavior.

### `market.bind` adapter auto-upsert behavior

`market.bind` is documented as manual/local-only, but for `source == "polymarket"` and `bound_via != "manual"` it probes config and delegates to `_upsert_market()` if adapter is enabled. This appears intentional compatibility behavior and is covered by docstring comments explaining manual metadata exception and adapter separation. Changing it would alter public behavior and possibly duplicate prior explicit adapter/no-default-network boundary work. Rejected.

---

## Issues encountered

- None blocking.
- Some `read_file` outputs containing secret-shaped fixture strings were redacted/sanitized in display, making a few test source lines appear syntactically odd in tool output. Pytest confirmed the actual files are valid and passing.

---

## Files created or modified

None. Read-only review only.