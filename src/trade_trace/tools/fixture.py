"""`tt fixture seed` per bead trade-trace-8dv.

Builds a deterministic dogfood dataset against a fresh journal: ≥30
decisions across the 13 types (except `hold`), ≥10 reflections, ≥5
resolved binary forecasts (auto-scored), 2 strategies, 1 playbook with
1 version + 1 rule, the stale-watch / unscored / ambiguous /
disputed / void / sensitive-source diagnostics fixtures, and provenance
edges.

Determinism is enforced by injecting CLOCK_OVERRIDE for the duration of
the seed call. Three invocations on a fresh home produce byte-identical
DBs (modulo the SQLite WAL — the test hashes table contents, not the
file).

The seed surface is `journal.fixture_seed`; the CLI maps it to
`tt journal fixture_seed --target=mvp-eval`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.tools._helpers import (
    CLOCK_OVERRIDE,
    reset_deterministic_id_counter,
)
from trade_trace.tools.errors import ToolError

FIXTURE_TARGETS = ("mvp-eval",)


# Anchor timestamp used as the deterministic clock during seeding.
_ANCHOR = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _journal_fixture_seed(
    args: dict[str, Any], ctx: ToolContext,
) -> dict[str, Any]:
    """Populate a fresh journal with the deterministic mvp-eval fixture.

    Args:
      target: required; must be 'mvp-eval' in MVP. Extending the surface
        to more fixture profiles is a follow-up.
      home: optional override for $TRADE_TRACE_HOME.

    Output: a summary of created entity counts so the caller can branch
    on which fixture profile populated which row counts. The values
    correspond to the bead's acceptance row-count requirements.
    """

    target = args.get("target", "mvp-eval")
    if target not in FIXTURE_TARGETS:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"target must be one of {FIXTURE_TARGETS}; got {target!r}",
            details={"field": "target", "value": target,
                     "allowed": list(FIXTURE_TARGETS)},
        )
    home = args.get("home")

    token = CLOCK_OVERRIDE.set(_ANCHOR)
    reset_deterministic_id_counter()
    from trade_trace.core import _reset_deterministic_request_id_counter

    _reset_deterministic_request_id_counter()
    try:
        counts = _seed_mvp_eval(home=home, registry=ctx.raw_args.get(
            "_registry") if isinstance(ctx.raw_args, dict) else None)
    finally:
        CLOCK_OVERRIDE.reset(token)
    return {
        "target": target,
        "counts": counts,
        "anchor": _ANCHOR.isoformat(),
    }


_ID_PREFIX_BY_TOOL: dict[str, str] = {
    "venue.add": "ven",
    "instrument.add": "ins",
    "snapshot.add": "snp",
    "thesis.add": "th",
    "forecast.add": "fc",
    "decision.add": "dec",
    "outcome.add": "out",
    "source.add": "src",
    "memory.retain": "mem",
    "memory.reflect": "mem",
    "memory.link": "edg",
    "strategy.create": "strat",
    "playbook.create": "pbk",
    "playbook.propose_version": "pbv",
    "decision.record_adherence": "adh",
    "source.attach_to_thesis": "edg",
    "source.attach_to_decision": "edg",
    "source.attach_to_forecast": "edg",
    "source.attach_to_memory_node": "edg",
}


def _call(home: str | None, tool: str, args: dict, *, suffix: str) -> Any:
    """Internal dispatcher helper that always passes a deterministic
    idempotency_key + id + actor_id so reruns hit the replay path
    cleanly. Deterministic ids are the load-bearing piece — without
    them, secrets.token_urlsafe in new_id() produces different ids per
    run, defeating the byte-equal determinism contract."""

    from trade_trace.core import dispatch  # late import: avoids cycle

    payload = {**args}
    if home is not None:
        payload["home"] = home
    payload.setdefault(
        "idempotency_key",
        f"00000000-0000-4000-8000-fxt-{_deterministic_token(suffix)}",
    )
    # Inject a deterministic id derived from suffix when the tool
    # accepts an `id` arg and the caller didn't supply one.
    prefix = _ID_PREFIX_BY_TOOL.get(tool)
    if prefix is not None and "id" not in payload:
        payload["id"] = f"{prefix}_{_deterministic_token('id-' + suffix)}"
    # memory.reflect writes a memory_node AND an about-edge in the same
    # call. The node id comes from the `id` arg; the edge id needs a
    # separate `edge_id` arg.
    if tool == "memory.reflect" and "edge_id" not in payload:
        payload["edge_id"] = f"edg_{_deterministic_token('edge-' + suffix)}"
    env = dispatch(tool, payload, actor_id="agent:fixture")
    if not env.ok:
        raise RuntimeError(
            f"fixture seed dispatch failed on tool={tool!r} suffix={suffix!r}: "
            f"{env.error.code} {env.error.message}"
        )
    return env.data


def _deterministic_token(suffix: str) -> str:
    """Deterministic 12-char token derived from a string suffix. Used
    for idempotency_keys so re-running fixture seed on the same DB
    replays cleanly."""

    # secrets isn't deterministic; we just hash the suffix and trim.
    import hashlib
    h = hashlib.sha256(suffix.encode("utf-8")).hexdigest()
    return h[:12]


def _seed_mvp_eval(*, home: str | None, registry: Any) -> dict[str, int]:
    """Walk the full fixture: venues, instruments, theses, forecasts,
    decisions across decision types, reflections, sources, strategy,
    playbook, adherence. The order is fixed for byte-identical replay.
    """

    counts = {
        "venues": 0, "instruments": 0, "theses": 0, "forecasts": 0,
        "decisions": 0, "outcomes": 0, "reflections": 0, "sources": 0,
        "strategies": 0, "playbooks": 0, "playbook_versions": 0,
        "playbook_rules": 0, "adherence_rows": 0,
    }

    # 2 venues / 2 strategies.
    venue1 = _call(home, "venue.add", {
        "name": "Polymarket", "kind": "prediction_market",
    }, suffix="venue-1").get("id")
    # NOTE: venue.kind enum is {exchange, broker, prediction_market,
    # dex, otc, manual}. Use 'exchange' for the equities-style venue.
    venue2 = _call(home, "venue.add", {
        "name": "Equities-Sim", "kind": "exchange",
    }, suffix="venue-2").get("id")
    counts["venues"] = 2

    strat_active = _call(home, "strategy.create", {
        "name": "Earnings momentum", "slug": "earnings-momentum",
        "hypothesis": "Post-earnings drift on AI demand surprises.",
    }, suffix="strat-active").get("id")
    strat_archived = _call(home, "strategy.create", {
        "name": "Retired liquidity edge", "slug": "retired-liquidity",
        "hypothesis": "Pre-resolution mispricing on thin markets.",
        "status": "active",
    }, suffix="strat-archived").get("id")
    _call(home, "strategy.update", {
        "strategy_id": strat_archived, "status": "archived",
    }, suffix="strat-archived-archive")
    counts["strategies"] = 2

    # 8 instruments seed → enough to sprinkle decisions across.
    instruments: list[str] = []
    for i in range(8):
        ins = _call(home, "instrument.add", {
            "venue_id": venue1 if i < 5 else venue2,
            "asset_class": "prediction_market" if i < 5 else "equity",
            "title": f"FixtureInst-{i:02d}",
            "currency_or_collateral": "USD",
        }, suffix=f"inst-{i}").get("id")
        instruments.append(ins)
    counts["instruments"] = 8

    # 10 theses (one per instrument, with two re-targeting the same
    # instrument for the stale-watch / contradictory-source fixture).
    theses: list[str] = []
    for i in range(10):
        inst = instruments[i % len(instruments)]
        t = _call(home, "thesis.add", {
            "instrument_id": inst, "side": "yes" if i % 2 == 0 else "no",
            "body": f"Fixture thesis #{i:02d}: deterministic-replay anchor.",
            "strategy_id": strat_active if i < 6 else None,
        }, suffix=f"thesis-{i}").get("id")
        theses.append(t)
    counts["theses"] = 10

    # 5 binary forecasts on the first 5 theses; resolve them so they
    # autoscore.
    for i in range(5):
        thesis = theses[i]
        _call(home, "forecast.add", {
            "thesis_id": thesis, "kind": "binary", "yes_label": "yes",
            "outcomes": [
                {"outcome_label": "yes", "probability": 0.5 + i * 0.08},
                {"outcome_label": "no", "probability": 0.5 - i * 0.08},
            ],
        }, suffix=f"forecast-{i}")
        counts["forecasts"] += 1

    # Outcomes that auto-score forecasts (use the same instrument id as
    # the thesis). Advance the clock so outcome.created_at is strictly
    # AFTER each forecast.created_at — otherwise the dogfood-protocol §2.2
    # late_recorded check fires (forecast.created_at >= outcome.created_at)
    # and every forecast gets stamped late, which excludes them from
    # report.calibration.
    instrument_for_thesis: dict[str, str] = {}
    for i in range(10):
        instrument_for_thesis[theses[i]] = instruments[i % len(instruments)]
    for i in range(5):
        thesis = theses[i]
        outcome_now = _ANCHOR + timedelta(days=7 + i)
        token2 = CLOCK_OVERRIDE.set(outcome_now)
        try:
            _call(home, "outcome.add", {
                "instrument_id": instrument_for_thesis[thesis],
                "resolved_at": (_ANCHOR + timedelta(days=14 + i)).isoformat(),
                "outcome_label": "yes" if i % 2 == 0 else "no",
                "status": "resolved_final",
            }, suffix=f"outcome-final-{i}")
        finally:
            CLOCK_OVERRIDE.reset(token2)
        counts["outcomes"] += 1

    # Hygiene-corner outcomes: 1 ambiguous, 1 disputed, 1 resolved_provisional,
    # 1 void.
    for status, suffix in (
        ("ambiguous", "amb"),
        ("disputed", "disp"),
        ("resolved_provisional", "prov"),
        ("void", "void"),
    ):
        _call(home, "outcome.add", {
            "instrument_id": instruments[5],
            "resolved_at": (_ANCHOR + timedelta(days=30)).isoformat(),
            "outcome_label": "yes", "status": status,
        }, suffix=f"outcome-{suffix}")
        counts["outcomes"] += 1

    # 30 decisions across types. Note: decision.add does NOT need
    # idempotency, but we supply one for replay parity.
    decision_specs: list[tuple[str, dict[str, Any]]] = []
    decision_types_to_seed = [
        # type, count
        ("watch", 4), ("skip", 4), ("paper_enter", 4), ("paper_exit", 2),
        ("actual_enter", 4), ("actual_exit", 2), ("add", 2), ("reduce", 2),
        ("invalidate_thesis", 1), ("update_thesis", 1), ("resolved", 2),
        ("review", 2),
    ]
    seq = 0
    for dtype, n in decision_types_to_seed:
        for _ in range(n):
            seq += 1
            # Repeating tags across multiple decisions so report.mistakes
            # has a tag group with count >= 3 — the c1r dogfood-scenario
            # PRD §10.2 #10 criterion needs a pattern the agent didn't
            # preempt.
            tags = ["liquidity-ignored"] if seq % 3 == 0 else (
                ["pre-earnings"] if seq % 5 == 0 else None
            )
            decision_specs.append(
                (f"dec-{seq:03d}", _build_decision_args(
                    dtype, instruments, theses, seq=seq,
                    strategy_id=strat_active if seq % 4 == 0 else None,
                    tags=tags,
                ))
            )
    decision_ids: list[str] = []
    for suffix, dargs in decision_specs:
        d = _call(home, "decision.add", dargs, suffix=suffix)
        decision_ids.append(d["id"])
    counts["decisions"] = len(decision_ids)

    # 10 reflections — bound to specific outcomes/decisions via memory.reflect.
    reflection_ids: list[str] = []
    for i in range(10):
        # Bind to a decision (proven by orphan-invariant test).
        target = decision_ids[i % len(decision_ids)]
        env = _call(home, "memory.reflect", {
            "target_kind": "decision", "target_id": target,
            "body": f"Reflection #{i:02d}: noted pattern around fixture decisions.",
            "importance": 6 + (i % 3),
        }, suffix=f"reflection-{i}")
        reflection_ids.append(env["id"])
    counts["reflections"] = 10

    # 3 sources: 1 stale, 1 contradictory, 1 sensitive.
    stale_src = _call(home, "source.add", {
        "kind": "url", "stance": "supports",
        "uri": "https://example.com/stale-article",
        "freshness_at": (_ANCHOR - timedelta(days=120)).isoformat(),
    }, suffix="source-stale").get("id")
    contradict_src = _call(home, "source.add", {
        "kind": "news_article", "stance": "contradicts",
        "uri": "https://example.com/contradict",
    }, suffix="source-contradict").get("id")
    sensitive_src = _call(home, "source.add", {
        "kind": "note", "stance": "neutral",
        "uri": "https://example.com/sensitive",
        "redaction_status": "sensitive",
    }, suffix="source-sensitive").get("id")
    counts["sources"] = 3

    # Attach: stale source → first thesis; contradict source on same
    # thesis as a supports-source pair → contradictory_sources fires.
    supports_partner = _call(home, "source.add", {
        "kind": "news_article", "stance": "supports",
        "uri": "https://example.com/contradict-pair",
    }, suffix="source-pair").get("id")
    counts["sources"] += 1
    _call(home, "source.attach_to_thesis", {
        "source_id": stale_src, "target_id": theses[0],
    }, suffix="attach-stale")
    _call(home, "source.attach_to_thesis", {
        "source_id": contradict_src, "target_id": theses[0],
    }, suffix="attach-contradict")
    _call(home, "source.attach_to_thesis", {
        "source_id": supports_partner, "target_id": theses[0],
    }, suffix="attach-supports-partner")
    _call(home, "source.attach_to_decision", {
        "source_id": sensitive_src, "target_id": decision_ids[0],
    }, suffix="attach-sensitive")

    # 1 playbook with 1 version + 1 rule + adherence on a decision.
    playbook = _call(home, "playbook.create", {
        "name": "Fixture Playbook", "description": "Eval-harness playbook.",
    }, suffix="playbook-1").get("id")
    counts["playbooks"] = 1
    rule_node = _call(home, "memory.retain", {
        "node_type": "playbook_rule",
        "body": "Fixture rule: do not enter when spread > 8% of expected edge.",
        "importance": 8,
    }, suffix="playbook-rule-1").get("id")
    counts["playbook_rules"] = 1
    version = _call(home, "playbook.propose_version", {
        "playbook_id": playbook,
        "provenance_reflection_node_id": reflection_ids[0],
        "description": "Initial rule set.",
    }, suffix="playbook-version-1").get("id")
    counts["playbook_versions"] = 1

    # Adherence: one followed + one overridden, on two different decisions.
    _call(home, "decision.record_adherence", {
        "decision_id": decision_ids[0], "playbook_version_id": version,
        "rule_node_id": rule_node, "status": "followed",
    }, suffix="adherence-followed")
    _call(home, "decision.record_adherence", {
        "decision_id": decision_ids[1], "playbook_version_id": version,
        "rule_node_id": rule_node, "status": "overridden",
        "reason": "edge clear despite rule",
    }, suffix="adherence-overridden")
    counts["adherence_rows"] = 2

    # Unscored forecast: add a forecast whose resolution_at has passed
    # but no resolved_final outcome on its instrument.
    _call(home, "forecast.add", {
        "thesis_id": theses[7], "kind": "binary", "yes_label": "yes",
        "outcomes": [
            {"outcome_label": "yes", "probability": 0.5},
            {"outcome_label": "no", "probability": 0.5},
        ],
        "resolution_at": (_ANCHOR - timedelta(days=1)).isoformat(),
    }, suffix="forecast-unscored")
    counts["forecasts"] += 1

    # Provenance edges from theses back to a recalled memory node — the
    # c1r dogfood criterion (PRD §10.2 #11 / #15) needs at least one
    # `derived_from` or `supports` edge from a thesis to a memory_node
    # to evidence that recall actually motivated downstream writing.
    observation_for_recall = _call(home, "memory.retain", {
        "node_type": "observation",
        "body": "Liquidity compression near resolution is the recurring "
                "pattern that motivated the next thesis.",
        "importance": 7,
    }, suffix="observation-for-recall")["id"]
    _call(home, "memory.link", {
        "source_kind": "thesis", "source_id": theses[2],
        "target_kind": "memory_node", "target_id": observation_for_recall,
        "edge_type": "derived_from",
    }, suffix="edge-thesis-derived-from-memory")
    # And a strategy-scoped one: a thesis on the active strategy cites
    # a memory via `supports`.
    _call(home, "memory.link", {
        "source_kind": "thesis", "source_id": theses[0],
        "target_kind": "memory_node", "target_id": observation_for_recall,
        "edge_type": "supports",
    }, suffix="edge-thesis-supports-memory")

    return counts


def _build_decision_args(
    dtype: str, instruments: list[str], theses: list[str], *,
    seq: int, strategy_id: str | None, tags: list[str] | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": dtype,
        "instrument_id": instruments[seq % len(instruments)],
    }
    # The decision-required-field matrix is enforced at the tool layer;
    # we supply the minimum set per type so the fixture seeds cleanly.
    if dtype in {"paper_enter", "actual_enter", "add"}:
        base.update({"thesis_id": theses[seq % len(theses)],
                      "side": "yes", "quantity": 1, "price": 0.5})
    elif dtype in {"paper_exit", "actual_exit", "reduce"}:
        base.update({"thesis_id": theses[seq % len(theses)],
                      "side": "yes", "quantity": 1, "price": 0.6})
    elif dtype == "skip":
        base.update({"reason": "spread > expected edge"})
    elif dtype == "watch":
        base.update({"thesis_id": theses[seq % len(theses)]})
    elif dtype == "invalidate_thesis":
        base.update({"thesis_id": theses[seq % len(theses)],
                      "reason": "data changed"})
    elif dtype == "update_thesis":
        base.update({"thesis_id": theses[seq % len(theses)]})
    elif dtype == "resolved":
        # Resolved decisions reference an instrument that has a forecast
        # in the fixture; the type marker indicates the agent recognized
        # the outcome.
        base.update({"thesis_id": theses[seq % len(theses)]})
    elif dtype == "review":
        base.update({"review_by": (_ANCHOR + timedelta(days=7)).isoformat()})
    if strategy_id is not None:
        base["strategy_id"] = strategy_id
    if tags is not None:
        base["tags"] = tags
    return base


def register_fixture_tools(registry: ToolRegistry) -> None:
    from trade_trace.tools._examples import WRITE_TOOL_EXAMPLES

    def _examples_for(tool: str) -> dict[str, Any]:
        ex = WRITE_TOOL_EXAMPLES.get(tool)
        if ex is None:
            return {"example_minimal": None, "example_rich": None}
        return {"example_minimal": ex.get("minimal"), "example_rich": ex.get("rich")}

    registry.register(
        "journal.fixture_seed",
        _journal_fixture_seed,
        is_write=True,
        **_examples_for("journal.fixture_seed"),
        description=(
            "Populate the journal with a deterministic fixture for the "
            "MVP eval harness (bead trade-trace-8dv). Required arg "
            "target='mvp-eval' (only profile in MVP). The seed runs "
            "under a frozen clock so three invocations on a fresh home "
            "produce byte-identical content."
        ),
    )
