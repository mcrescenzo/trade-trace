# Exporter secret-scanning adapter investigation (SIMP-016B)

> Status: **decision document for trade-trace-ypbp** (findings + plan). No code or
> test changes in this document; the implementation work is filed as
> a follow-up bead before close.

## Problem

`src/trade_trace/exporter.py` reaches into `trade_trace.security.patterns`
to grab a private attribute and re-export it under a public name:

```python
# src/trade_trace/exporter.py:249-250
from trade_trace.security import scan_text as _scan_text
from trade_trace.security.patterns import _compiled as SECRET_PATTERNS
```

`_compiled` is the live `dict[str, re.Pattern[str]]` registry inside
`security.patterns`. Importing it under a public name (`SECRET_PATTERNS`)
exposes a private symbol across a module boundary; the leading
underscore convention is a deliberate signal that the dict's identity
and shape are not part of the public contract.

`tests/security/test_redacted_exports.py` imports both `SECRET_PATTERNS`
and `scan_for_secrets` from `exporter.py`, so the leak is observable
to test callers too.

## Current observable surface

What the alias is actually used for:

1. **Test discovery**: `test_redacted_exports.py` asserts the four
   built-in pattern names (`api_key`, `slack_token`, `ethereum_address`,
   `jwt`) are present in `SECRET_PATTERNS`. It only iterates `.keys()`;
   the compiled regex value is not inspected.
2. **Exporter scan output shape**: `scan_for_secrets` is a thin wrapper
   around `_scan_text` that returns `{pattern, match, match_offset,
   match_length}` dicts (the operator-facing shape from
   `bead trade-trace-67sg`).

So the actual coupling is on **pattern names** + the **scan output
dict shape**, not on the compiled-regex object identity.

## Decision

**Add a public adapter at `trade_trace.security.patterns`,** then
migrate the exporter and tests:

- Expose `compiled_patterns() -> dict[str, re.Pattern[str]]`: returns a
  fresh dict snapshot of the active registry. The caller cannot mutate
  the live registry through it (the snapshot is what they hold, not the
  module-level dict). This replaces `from … import _compiled as
  SECRET_PATTERNS`.
- Keep `list_patterns()` (already public) as the name-and-source view.
- `exporter.py` and `tests/security/test_redacted_exports.py` switch
  to `compiled_patterns()`; the `SECRET_PATTERNS` alias is removed.
- `scan_for_secrets` stays where it is; it is the right contract
  (operator-facing dict shape) but currently lives on `exporter.py`.
  Leave it there for now — moving it to `security` would require
  changing every importer and adds little value beyond the rename.

### Why not just rename `_compiled` to `compiled`?

Tempting but worse:

- The registry is mutated by `register()` and `reset_patterns()`. A
  consumer that imports `compiled` once at module load gets a stale
  reference if registration changes the dict after import. The
  `compiled_patterns()` function returns a fresh snapshot per call,
  which sidesteps that footgun.
- The private name is documentation: callers SHOULD go through
  `scan_text` / `list_patterns()` / `register()`. A public alias would
  re-encode the "feel free to touch this dict" implication this bead is
  trying to remove.

### Behavior preservation

- `compiled_patterns()` returns the same pattern object identities the
  live registry holds, so `re.Pattern.search/findall` behavior is
  unchanged.
- The four built-in pattern names continue to surface in any consumer
  that previously iterated `SECRET_PATTERNS.keys()`.
- `scan_for_secrets` keeps its dict output contract per
  `trade-trace-67sg`.

## Validation plan

The follow-up bead must run these gates before close:

- `tests/security/test_redacted_exports.py` — every existing redaction
  test still passes.
- `tests/security/test_secret_pattern_writes.py` — every existing
  pattern-write rejection test still passes.
- `mypy src` and `ruff check src tests` clean.
- A direct unit test that `compiled_patterns()` returns a fresh dict
  snapshot (mutating the returned dict does not affect subsequent
  scan_text calls).

## Follow-up work

A follow-up bead carries the implementation (no design left to do):

- Add `compiled_patterns()` to `trade_trace.security.patterns`.
- Re-export from `trade_trace.security` `__init__.py` for parity
  with the existing `scan_text` re-export.
- Replace the `_compiled as SECRET_PATTERNS` import in `exporter.py`
  with a `compiled_patterns()` call cached at module import time, or
  delete the `SECRET_PATTERNS` alias entirely if the only callers are
  internal.
- Update `tests/security/test_redacted_exports.py` to import the new
  adapter; drop the `SECRET_PATTERNS` import.
