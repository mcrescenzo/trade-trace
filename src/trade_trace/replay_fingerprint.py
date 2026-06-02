"""Non-secret replay identity fingerprints for dispatch trace reconciliation."""

from __future__ import annotations

import hmac
import json
from hashlib import sha256
from typing import Any

SCHEMA = "replay_fingerprint"
VERSION = 1
DOMAIN = "tracelab-replay-fingerprint-v1"
ALGORITHM = "HMAC-SHA256"


def canonical_replay_identity(event_type: str, actor_id: str, idempotency_key: str) -> bytes:
    """Versioned canonical bytes for replay identity.

    JSON array serialization avoids delimiter-collision ambiguities such as
    ("a", "b:c", "d") vs ("a:b", "c", "d").
    """

    return json.dumps(
        [DOMAIN, {"event_type": event_type, "actor_id": actor_id, "idempotency_key": idempotency_key}],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def compute_replay_fingerprint(
    *,
    secret: str | bytes,
    event_type: str,
    actor_id: str,
    idempotency_key: str,
) -> dict[str, Any]:
    """Return schema metadata and a lowercase keyed HMAC-SHA256 digest.

    The raw idempotency key and secret are inputs only; they are never returned.
    """

    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else secret
    digest = hmac.new(
        secret_bytes,
        canonical_replay_identity(event_type, actor_id, idempotency_key),
        sha256,
    ).hexdigest()
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "domain": DOMAIN,
        "algorithm": ALGORITHM,
        "event_type": event_type,
        "digest": digest,
    }
