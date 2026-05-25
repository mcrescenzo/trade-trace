"""PRD §2.4.1 / VISION §safety promise: MVP makes no outbound network calls
on a fresh `journal.init`. Air-gappable on first run.

The test monkeypatches `socket.socket.connect` with a raising stub for the
duration of the call, so any code path attempting an outbound TCP connection
fails the test immediately. DNS lookups via `socket.getaddrinfo` are similarly
caught.
"""

from __future__ import annotations

from pathlib import Path

from trade_trace.mcp_server import mcp_call


def test_journal_init_no_network(no_outbound_connect_or_dns, tmp_path: Path):
    """`journal.init` on a fresh home must not open a socket."""

    env = mcp_call("journal.init", {"home": str(tmp_path / "home")})
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    assert body["data"]["outbound_network_active"] is False


def test_journal_status_no_network(no_outbound_connect_or_dns, tmp_path: Path):
    """`journal.status` against an uninitialized home must not open a socket."""

    env = mcp_call("journal.status", {"home": str(tmp_path / "home")})
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True
    assert body["data"]["outbound_network_active"] is False


def test_journal_schema_no_network(no_outbound_connect_or_dns):
    """`journal.schema` is in-process Pydantic; no network ever."""

    env = mcp_call("journal.schema", {})
    body = env.model_dump(mode="json", exclude_none=True)
    assert body["ok"] is True


def test_init_then_status_then_reinit_no_network(no_outbound_connect_or_dns, tmp_path: Path):
    """A representative idempotent loop must not open a socket."""

    home = str(tmp_path / "home")
    for tool in ("journal.init", "journal.status", "journal.init", "journal.status"):
        env = mcp_call(tool, {"home": home})
        body = env.model_dump(mode="json", exclude_none=True)
        assert body["ok"] is True, body


# -- registry-wide representative smoke per bead trade-trace-2ifs ----
#
# The previous tests only covered journal.init/status/schema. Per
# DEBT-038, the air-gap guarantee must hold across the whole tool
# registry — adding more tools later cannot silently introduce a
# network code path. This block exercises a representative slice
# spanning every functional cluster (ledger writes, memory, reports,
# review.bundle, strategies, playbooks, signals, source.* attachers)
# under the same no_network fixture. Each tool is run with the
# minimum inputs needed to return a typed envelope (ok or a typed
# error); any outbound TCP connect or DNS lookup attempt during the
# run fails the test via the fixture's raising stubs.


def _initialized_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    env = mcp_call("journal.init", {"home": str(home)})
    assert env.ok, env
    return home


def _add_venue_and_instrument(home: Path) -> dict[str, str]:
    venue = mcp_call("venue.add", {
        "home": str(home), "name": "PM",
        "kind": "prediction_market",
    }).model_dump(mode="json", exclude_none=True)
    inst = mcp_call("instrument.add", {
        "home": str(home),
        "venue_id": venue["data"]["id"],
        "asset_class": "prediction_market",
        "title": "Smoke",
    }).model_dump(mode="json", exclude_none=True)
    return {"venue_id": venue["data"]["id"],
            "instrument_id": inst["data"]["id"]}


# Each row: (tool name, callable producing kwargs from `home` and
# any seed dict). The smoke run threads the seed dict between rows so
# downstream tools see a consistent journal state.
_NO_NETWORK_SMOKE_ROWS: list[tuple[str, str]] = [
    # Ledger writes
    ("venue.add", "venue"),
    ("instrument.add", "instrument"),
    ("thesis.add", "thesis"),
    ("forecast.add", "forecast"),
    ("decision.add", "decision"),
    ("source.add", "source"),
    # Reports + bundle (cover every report.* family)
    ("report.filter_schema", "noop"),
    ("report.calibration", "noop"),
    ("report.pnl", "noop"),
    ("report.watchlist", "noop"),
    ("report.unscored_forecasts", "noop"),
    ("report.mistakes", "noop"),
    ("report.strengths", "noop"),
    ("report.decision_velocity", "noop"),
    ("report.coach", "noop"),
    ("report.source_quality", "noop"),
    ("report.audit_readiness", "noop"),
    ("report.calibration_integrity", "noop"),
    ("report.playbook_adherence", "noop"),
    ("review.bundle", "noop"),
    # Memory layer
    ("memory.retain", "memory"),
    ("memory.recall", "memory_recall"),
    # Strategies, playbooks, signals
    ("strategy.create", "strategy"),
    ("playbook.create", "playbook"),
    ("signal.scan", "noop"),
    # Tool introspection + journal lifecycle
    ("tool.schema", "tool_schema"),
    ("journal.schema", "noop"),
    ("journal.status", "noop"),
    ("journal.repair", "noop"),
]


def _make_kwargs(tool: str, home: Path, seed: dict[str, str]) -> dict:
    """Return the smallest valid args for `tool`. Pulls ids out of
    `seed` for tools that need them."""

    base: dict = {"home": str(home)}
    if tool == "venue.add":
        return {**base, "name": "Smoke", "kind": "prediction_market"}
    if tool == "instrument.add":
        return {**base, "venue_id": seed["venue_id"],
                "asset_class": "prediction_market", "title": "Smoke"}
    if tool == "thesis.add":
        return {**base, "instrument_id": seed["instrument_id"],
                "side": "yes", "body": "smoke"}
    if tool == "forecast.add":
        return {**base, "thesis_id": seed["thesis_id"], "kind": "binary",
                "yes_label": "yes",
                "outcomes": [
                    {"outcome_label": "yes", "probability": 0.5},
                    {"outcome_label": "no", "probability": 0.5},
                ]}
    if tool == "decision.add":
        return {**base, "instrument_id": seed["instrument_id"],
                "type": "skip"}
    if tool == "source.add":
        return {**base, "kind": "note", "title": "smoke note"}
    if tool == "memory.retain":
        return {**base, "node_type": "observation",
                "body": "smoke memory body"}
    if tool == "memory.recall":
        return {**base, "query": "smoke"}
    if tool == "strategy.create":
        return {**base, "slug": "smoke-strat", "name": "Smoke"}
    if tool == "playbook.create":
        return {**base, "slug": "smoke-pb", "name": "Smoke"}
    if tool == "tool.schema":
        return {**base, "tool": "journal.init"}
    if tool == "report.filter_schema":
        return {}
    if tool == "report.decision_velocity":
        return {**base, "bucket": "day"}
    if tool == "report.watchlist":
        return {**base, "mode": "all"}
    return base


def _absorb_seed(tool: str, env, seed: dict[str, str]) -> dict[str, str]:
    """Capture ids the next tool will need from the response."""

    if not env.ok:
        return seed
    data = env.data or {}
    if tool == "venue.add":
        seed = {**seed, "venue_id": data["id"]}
    elif tool == "instrument.add":
        seed = {**seed, "instrument_id": data["id"]}
    elif tool == "thesis.add":
        seed = {**seed, "thesis_id": data["id"]}
    elif tool == "forecast.add":
        seed = {**seed, "forecast_id": data["id"]}
    elif tool == "decision.add":
        seed = {**seed, "decision_id": data["id"]}
    return seed


def test_no_outbound_network_across_representative_tool_registry(
    no_outbound_connect_or_dns, tmp_path: Path,
):
    """Run a representative slice of the registry under the no-network
    fixture. Any tool that opens a socket fails the test immediately
    via the AssertionError raised by the stubbed connect/getaddrinfo.

    Each call must return a typed envelope (ok=True or a typed
    error). A typed error is acceptable — the contract is "no
    outbound network", not "every tool succeeds against an empty
    DB"."""

    home = _initialized_home(tmp_path)
    seed: dict[str, str] = {}
    for tool, _seed_kind in _NO_NETWORK_SMOKE_ROWS:
        kwargs = _make_kwargs(tool, home, seed)
        env = mcp_call(tool, kwargs)
        # Either ok or a typed error envelope — what we're asserting
        # is that no socket call happened, not that the tool's
        # business logic accepted the smoke input. The no_network
        # fixture raises AssertionError on any outbound attempt,
        # which would surface here as a test failure regardless of
        # envelope shape.
        assert env.ok or env.error.code is not None, (
            f"{tool} returned an untyped failure: {env}"
        )
        seed = _absorb_seed(tool, env, seed)


def test_export_drain_runs_under_no_network(no_outbound_connect_or_dns, tmp_path: Path):
    """Export drain is the highest-risk tool because the docs originally
    mentioned remote sync as a future hook. Confirm the on-disk JSONL
    drain path never touches the network."""

    home = _initialized_home(tmp_path)
    ids = _add_venue_and_instrument(home)
    decision_env = mcp_call("decision.add", {
        "home": str(home),
        "instrument_id": ids["instrument_id"], "type": "skip",
        "reason": "smoke",
    })
    assert decision_env.ok

    # Enable JSONL outbox and drain through the public surface.
    mcp_call("journal.config_set", {
        "home": str(home), "key": "outbox.jsonl_enabled", "value": "true",
        "confirm": True,
    })
    drain = mcp_call("export.drain", {"home": str(home)})
    # Either drains cleanly or returns a typed error. The contract is
    # that nothing in this call path opens a socket.
    assert drain.ok or drain.error.code is not None


# -- static dependency audit per bead trade-trace-2ifs --------------
#
# A stronger guard than the runtime fixture: walk the src/ tree and
# fail the test if any module imports a network-capable library or
# uses subprocess in a way that could reach the network. The allowlist
# contains only documented, opt-in network paths; any new use must be
# explicitly added here with a justification comment and docs/bead coverage.


_DEFAULT_FORBIDDEN_IMPORTS = (
    "import requests",
    "from requests",
    "import httpx",
    "from httpx",
    "import aiohttp",
    "from aiohttp",
    "import urllib3",
    "from urllib3",
    "import urllib.request",
    "from urllib.request",
    "import urllib.parse",  # parse alone is safe but flagging guides reviewers
    "import openai",
    "from openai",
    "import anthropic",
    "from anthropic",
    "import google.generativeai",
    "import boto3",
    "from boto3",
    "import paramiko",
    "from paramiko",
)
"""Stdlib + third-party identifiers that can produce outbound network
traffic. urllib.parse is intentionally listed even though parse is
network-free — it surfaces accidental imports of urllib.request via
the same module path."""

_ALLOWED_NETWORK_IMPORT_FILES: tuple[str, ...] = (
    # trade-trace-89x: `model.import` may lazily download the pinned
    # bge-small local embedding model only after the operator has opted into
    # `embeddings.provider=local` and trusted model files are missing. Default
    # journal.init/status/schema and representative registry smoke tests above
    # still run under the socket/DNS no_network fixture, preserving the default
    # air-gap guarantee.
    "src/trade_trace/tools/admin.py",
    # trade-trace-mmze: opt-in Polymarket adapter client imports httpx only in
    # the adapter code path. journal.init/status/schema remain offline and the
    # adapter fails closed unless network.polymarket.enabled=true.
    "src/trade_trace/adapters/polymarket/client.py",
)
"""Paths under src/ allowed to import a forbidden network library.
Narrow by design — default MVP behavior makes no outbound calls. Adding an
entry here requires the bead acceptance criteria and security docs to justify
the opt-in boundary without weakening default air-gap behavior."""


def test_no_forbidden_network_imports_in_src():
    """Static audit: src/ must not import any network-capable library
    unless its file path is on the explicit allowlist. The allowlist is
    intentionally tiny because the default air-gap promise (PRD §2.4.1,
    VISION safety §) is a first-class invariant. Adding a real network
    dependency is a docs + bead change, not a silent import."""

    assert _ALLOWED_NETWORK_IMPORT_FILES == (
        "src/trade_trace/tools/admin.py",
        "src/trade_trace/adapters/polymarket/client.py",
    ), (
        "Only reviewed opt-in network paths may import network libraries; future "
        "network imports need explicit docs + bead review and must not weaken "
        "default no-network behavior."
    )

    root = Path(__file__).resolve().parents[2] / "src" / "trade_trace"
    offenders: list[tuple[Path, str, int]] = []
    for py_path in root.rglob("*.py"):
        rel = py_path.relative_to(root.parent.parent)
        if str(rel) in _ALLOWED_NETWORK_IMPORT_FILES:
            continue
        text = py_path.read_text(encoding="utf-8")
        # urllib.parse is parse-only and ships with stdlib; allow it
        # in this audit by stripping the parse case from the scan.
        for forbidden in _DEFAULT_FORBIDDEN_IMPORTS:
            if forbidden == "import urllib.parse":
                continue  # parse is network-free; listed for reviewer visibility
            for line_no, line in enumerate(text.splitlines(), start=1):
                stripped = line.split("#", 1)[0].rstrip()
                if forbidden in stripped:
                    offenders.append((rel, forbidden, line_no))

    assert not offenders, (
        "src/ imports forbidden network library/SDK without an "
        "allowlist entry; either remove the import or, if the air-gap "
        "promise has been revised, update _ALLOWED_NETWORK_IMPORT_FILES.\n"
        + "\n".join(f"  {p}:{ln}  {pattern!r}" for p, pattern, ln in offenders)
    )


def test_no_subprocess_in_src_runtime_paths():
    """Static audit: subprocess imports in src/ are a smell because
    they could shell out to curl/wget/ssh and reach the network.
    The only acknowledged subprocess use in MVP is in tests (which
    are outside src/); src/ itself must remain subprocess-free unless
    a new tool explicitly justifies it here."""

    root = Path(__file__).resolve().parents[2] / "src" / "trade_trace"
    allowlist: set[str] = set()
    offenders: list[tuple[Path, int, str]] = []
    for py_path in root.rglob("*.py"):
        rel = py_path.relative_to(root.parent.parent)
        if str(rel) in allowlist:
            continue
        text = py_path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            stripped = line.split("#", 1)[0]
            if (
                "import subprocess" in stripped
                or "from subprocess" in stripped
            ):
                offenders.append((rel, line_no, line.strip()))

    assert not offenders, (
        "subprocess imports found in src/. If you need to shell out, "
        "add the file to the allowlist in this test with a justification "
        "(and confirm the call site is bounded so it cannot reach the "
        "network).\n"
        + "\n".join(f"  {p}:{ln}  {snippet}" for p, ln, snippet in offenders)
    )
