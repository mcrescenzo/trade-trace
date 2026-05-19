Context:
security-config-ops — src/trade_trace/tools/admin.py

Observed behavior:
Confirmed restore copies traversal path outside requested home.

Expected behavior:
Restore rejects absolute/traversal paths and constrains output under TRADE_TRACE_HOME before copy.

Evidence:
primary_evidence.txt restore runtime recheck: manifest path ../../evil.txt restored /tmp/evil.txt outside home; admin.py copies home / entry[path] without normalization.

Failure mode / impact:
Tampered backup can write/corrupt files outside journal home with process permissions.

## Steps to Reproduce
python3 -m pytest tests/security/test_restore_manifest_paths.py -q

Duplicate check:
Compared against existing open and closed bughunt items in preflight_prior_bughunt_readback.txt. Evidence threshold met; no exact duplicate found in prior open/closed bughunt readback. Possible overlap: none.

Suggested fix direction:
Repair the cited contract/runtime path with the smallest behavior-preserving change; add the listed regression proof.

Validation:
python3 -m pytest tests/security/test_restore_manifest_paths.py -q

Acceptance criteria:
- Restore rejects traversal/absolute/drive paths and resolved outputs outside home
- Valid journal.backup manifests still restore
- Regression proves no outside file is created for malicious manifest

Provenance:
Discovered by repo-bughunt candidate CAND-009 in domain security-config-ops.