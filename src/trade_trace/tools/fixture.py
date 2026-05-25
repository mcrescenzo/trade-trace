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

from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, Literal

from trade_trace.contracts.errors import ErrorCode
from trade_trace.contracts.tool_registry import ToolContext, ToolRegistry
from trade_trace.tools._helpers import (
    CLOCK_OVERRIDE,
    reset_deterministic_id_counter,
)
from trade_trace.tools.errors import ToolError

FIXTURE_TARGETS = ("mvp-eval-pm", "forecast-only-pm", "mvp-eval-rich", "agent-continuity-loop")


# Anchor timestamp used as the deterministic clock during seeding.
_ANCHOR = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

_FixtureCounts = dict[str, int]


@dataclass(frozen=True)
class _FixtureSeedContext:
    """Immutable runtime context shared by all fixture builders."""

    home: str | None
    registry: Any


@dataclass(frozen=True)
class _FixtureBuilderProfile:
    """A public fixture target as an ordered list of deterministic builders."""

    target: str
    builders: Sequence[Callable[[_FixtureSeedContext, _FixtureCounts], _FixtureCounts]]


class _FrozenFixtureClock(AbstractContextManager[None]):
    """Freeze all fixture builders to the shared deterministic anchor."""

    def __enter__(self) -> None:
        self._token = CLOCK_OVERRIDE.set(_ANCHOR)
        reset_deterministic_id_counter()
        from trade_trace.core import _reset_deterministic_request_id_counter

        _reset_deterministic_request_id_counter()
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        CLOCK_OVERRIDE.reset(self._token)
        return False


def _journal_fixture_seed(
    args: dict[str, Any], ctx: ToolContext,
) -> dict[str, Any]:
    """Populate a fresh journal with the deterministic mvp-eval fixture.

    Args:
      target: optional; must be one of the supported fixture profiles.
      home: optional override for $TRADE_TRACE_HOME.

    Output: a summary of created entity counts so the caller can branch
    on which fixture profile populated which row counts. The values
    correspond to the bead's acceptance row-count requirements.
    """

    target = args.get("target", "mvp-eval-pm")
    if target not in FIXTURE_TARGETS:
        raise ToolError(
            ErrorCode.VALIDATION_ERROR,
            f"target must be one of {FIXTURE_TARGETS}; got {target!r}",
            details={"field": "target", "value": target,
                     "allowed": list(FIXTURE_TARGETS)},
        )
    home = args.get("home")

    registry = ctx.raw_args.get(
        "_registry") if isinstance(ctx.raw_args, dict) else None
    seed_ctx = _FixtureSeedContext(home=home, registry=registry)
    with _FrozenFixtureClock():
        counts = _run_fixture_profile(target, seed_ctx)
    return {
        "target": target,
        "counts": counts,
        "anchor": _ANCHOR.isoformat(),
    }


def _run_fixture_profile(target: str, ctx: _FixtureSeedContext) -> _FixtureCounts:
    """Execute a public fixture target's builders in declared order."""

    profile = FIXTURE_PROFILES[target]
    counts: _FixtureCounts = {}
    for builder in profile.builders:
        counts = builder(ctx, counts)
    return counts


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
    "market.bind": "mkt",
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


def _seed_mvp_eval_rich_overlay(
    *,
    home: str | None,
    registry: Any,
    counts: dict[str, int],
) -> dict[str, int]:
    """Extend the mvp-eval seed with traded position lifecycles + risk
    budgets needed by the reporting product overhaul (trade-trace-dnwh).

    Adds: 5 closed positions (2 winners, 2 losers, 1 breakeven), 4
    open positions (2 with mark, 2 without), a low-N "rich-only-N1"
    strategy with a single decision, and a couple of decisions that
    carry `declared_risk_amount` so report.risk has both included and
    missing-risk rows to chart.

    The seed writes `position_events` rows directly via SQL and then
    rebuilds the positions projection so the dashboards see canonical
    rows. Decisions are still written through `decision.add` so the
    matrix invariants and idempotency contract apply.
    """

    from trade_trace.projections import rebuild_positions
    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path, resolve_home

    home_path = resolve_home(home)
    db = open_database(db_path(home_path), create_parent=False)
    try:
        venue_row = db.connection.execute(
            "SELECT id FROM venues WHERE name = ?", ("Equities-Sim",),
        ).fetchone()
        if venue_row is None:
            raise RuntimeError(
                "mvp-eval-rich requires the mvp-eval seed to run first; "
                "Equities-Sim venue missing"
            )
        rich_venue = venue_row[0]
    finally:
        db.close()

    rich_strategy = _call(home, "strategy.create", {
        "name": "Rich-only single", "slug": "rich-only-n1",
        "hypothesis": "Low-N group used to exercise sample-warning paths.",
    }, suffix="rich-strategy").get("id")
    counts["strategies"] = counts.get("strategies", 0) + 1

    # 9 instruments for the rich overlay so trades don't collide with
    # mvp-eval's positions.
    rich_instruments: list[str] = []
    for i in range(9):
        inst = _call(home, "instrument.add", {
            "venue_id": rich_venue,
            "asset_class": "equity",
            "title": f"RichInst-{i:02d}",
            "currency_or_collateral": "USD",
        }, suffix=f"rich-inst-{i}").get("id")
        rich_instruments.append(inst)
    counts["instruments"] = counts.get("instruments", 0) + 9

    rich_thesis_ids: list[str] = []
    for i, inst in enumerate(rich_instruments):
        t = _call(home, "thesis.add", {
            "instrument_id": inst, "side": "long",
            "body": f"Rich fixture thesis #{i:02d}: equity momentum.",
            "strategy_id": rich_strategy if i == 0 else None,
        }, suffix=f"rich-thesis-{i}").get("id")
        rich_thesis_ids.append(t)
    counts["theses"] = counts.get("theses", 0) + 9

    # 5 closed positions: 2 winners, 2 losers, 1 breakeven.
    # Risk budget on 2 of the closed winners + 1 loser.
    closed_specs = [
        # (entry_price, exit_price, qty, declared_risk_amount, label)
        (0.40, 0.55, 100, 30.0, "closed-winner-1"),
        (0.30, 0.42, 100, 25.0, "closed-winner-2"),
        (0.50, 0.40, 100, 20.0, "closed-loser-1"),
        (0.60, 0.45, 100, None, "closed-loser-2"),
        (0.45, 0.45, 100, None, "closed-breakeven"),
    ]
    enter_decision_ids: list[str] = []
    exit_decision_ids: list[str] = []
    for i, (entry, exit_, qty, risk, label) in enumerate(closed_specs):
        inst = rich_instruments[i]
        thesis = rich_thesis_ids[i]
        enter_args: dict[str, Any] = {
            "type": "paper_enter",
            "instrument_id": inst,
            "thesis_id": thesis,
            "side": "long",
            "quantity": qty,
            "price": entry,
        }
        if risk is not None:
            enter_args["declared_risk_amount"] = risk
            enter_args["declared_risk_unit"] = "dollar"
        enter_id = _call(home, "decision.add", enter_args,
                         suffix=f"rich-{label}-enter")["id"]
        enter_decision_ids.append(enter_id)
        exit_id = _call(home, "decision.add", {
            "type": "paper_exit",
            "instrument_id": inst,
            "thesis_id": thesis,
            "side": "long",
            "quantity": qty,
            "price": exit_,
        }, suffix=f"rich-{label}-exit")["id"]
        exit_decision_ids.append(exit_id)
    counts["decisions"] = counts.get("decisions", 0) + len(closed_specs) * 2

    # 4 open positions: 2 with mark, 2 without.
    open_specs = [
        # (entry_price, qty, declared_risk_amount, mark_price | None, label)
        (0.35, 100, 18.0, 0.50, "open-marked-up"),
        (0.55, 100, None, 0.42, "open-marked-down"),
        (0.20, 100, None, None, "open-unmarked-1"),
        (0.80, 100, 12.0, None, "open-unmarked-2"),
    ]
    open_decision_ids: list[str] = []
    for i, (entry, qty, risk, mark_price, label) in enumerate(open_specs):
        inst = rich_instruments[5 + i]
        thesis = rich_thesis_ids[5 + i]
        enter_args = {
            "type": "paper_enter",
            "instrument_id": inst,
            "thesis_id": thesis,
            "side": "long",
            "quantity": qty,
            "price": entry,
        }
        if risk is not None:
            enter_args["declared_risk_amount"] = risk
            enter_args["declared_risk_unit"] = "dollar"
        enter_id = _call(home, "decision.add", enter_args,
                         suffix=f"rich-{label}-enter")["id"]
        open_decision_ids.append(enter_id)
        # snapshot.add for the open positions that should be marked. The
        # marks land in the `snapshots` table, which `_latest_snapshot_price`
        # queries during rebuild_positions to populate unrealized_pnl.
        if mark_price is not None:
            mark_ts = (_ANCHOR + timedelta(days=21, hours=i)).isoformat()
            _call(home, "snapshot.add", {
                "instrument_id": inst,
                "captured_at": mark_ts,
                "price": mark_price,
            }, suffix=f"rich-{label}-mark")
    counts["decisions"] = counts.get("decisions", 0) + len(open_specs)

    # Write position_events + marks directly so the rebuild produces
    # the lifecycle states (closed / open w-mark / open wo-mark) that
    # the dashboards exercise.
    db = open_database(db_path(home_path), create_parent=False)
    try:
        with db.transaction():
            base_ts = _ANCHOR + timedelta(days=20)
            seq = 0
            for i, ((entry, exit_, qty, _risk, _label), enter_id, exit_id) in enumerate(
                zip(closed_specs, enter_decision_ids, exit_decision_ids, strict=True)
            ):
                inst = rich_instruments[i]
                position_id = f"pos_rich_closed_{i:02d}"
                open_ts = (base_ts + timedelta(hours=seq)).isoformat()
                close_ts = (base_ts + timedelta(hours=seq + 1)).isoformat()
                db.connection.execute(
                    "INSERT INTO position_events(id, position_id, instrument_id, "
                    "decision_id, event_type, quantity_delta, price, fees, "
                    "slippage, created_at, actor_id) "
                    "VALUES (?, ?, ?, ?, 'open', ?, ?, 0, 0, ?, 'agent:fixture')",
                    (f"pev_rich_open_{i:02d}", position_id, inst, enter_id,
                     qty, entry, open_ts),
                )
                db.connection.execute(
                    "INSERT INTO position_events(id, position_id, instrument_id, "
                    "decision_id, event_type, quantity_delta, price, fees, "
                    "slippage, created_at, actor_id) "
                    "VALUES (?, ?, ?, ?, 'close', ?, ?, 0, 0, ?, 'agent:fixture')",
                    (f"pev_rich_close_{i:02d}", position_id, inst, exit_id,
                     -qty, exit_, close_ts),
                )
                seq += 2

            for i, ((entry, qty, _risk, _mark_price, _label), enter_id) in enumerate(
                zip(open_specs, open_decision_ids, strict=True)
            ):
                inst = rich_instruments[5 + i]
                position_id = f"pos_rich_open_{i:02d}"
                open_ts = (base_ts + timedelta(hours=seq)).isoformat()
                db.connection.execute(
                    "INSERT INTO position_events(id, position_id, instrument_id, "
                    "decision_id, event_type, quantity_delta, price, fees, "
                    "slippage, created_at, actor_id) "
                    "VALUES (?, ?, ?, ?, 'open', ?, ?, 0, 0, ?, 'agent:fixture')",
                    (f"pev_rich_open2_{i:02d}", position_id, inst, enter_id,
                     qty, entry, open_ts),
                )
                seq += 1

            rebuild_positions(db.connection)
    finally:
        db.close()

    counts.setdefault("rich_closed_positions", len(closed_specs))
    counts.setdefault("rich_open_positions", len(open_specs))
    return counts


def _build_mvp_eval_base_journal(
    ctx: _FixtureSeedContext,
    counts: _FixtureCounts,
) -> _FixtureCounts:
    """Base deterministic journal primitives and diagnostic overlays.

    This preserves the historical mvp-eval row order and IDs by delegating to
    the original builder body as one ordered profile step. Smaller extraction
    can now happen behind this profile boundary without changing the public
    target contract.
    """

    if counts:
        raise RuntimeError("mvp-eval base builder must start from empty counts")
    return _seed_mvp_eval(home=ctx.home, registry=ctx.registry)


def _build_mvp_eval_rich_reporting_overlay(
    ctx: _FixtureSeedContext,
    counts: _FixtureCounts,
) -> _FixtureCounts:
    """Reporting/position overlay for mvp-eval-rich."""

    return _seed_mvp_eval_rich_overlay(
        home=ctx.home,
        registry=ctx.registry,
        counts=counts,
    )


def _build_agent_continuity_loop_overlay(
    ctx: _FixtureSeedContext,
    counts: _FixtureCounts,
) -> _FixtureCounts:
    """Add deterministic agent-continuity loop artifacts.

    The base/rich profiles provide fresh-session recovery material, stale
    obligations, low-N diagnostics, replay candidates, and local report inputs.
    This overlay adds an auditable recall receipt with downstream use/misuse
    evidence plus a quarantined policy candidate reflection. It is local-only:
    no fetching, execution, scheduler, broker, wallet, or model-runner behavior.
    """

    from trade_trace.storage import open_database
    from trade_trace.storage.paths import db_path, resolve_home

    home_path = resolve_home(ctx.home)
    db = open_database(db_path(home_path), create_parent=False)
    try:
        row = db.connection.execute(
            """
            SELECT d.id, d.instrument_id, d.strategy_id
            FROM decisions d
            WHERE d.strategy_id IS NOT NULL
            ORDER BY d.id
            LIMIT 1
            """
        ).fetchone()
        helpful = db.connection.execute(
            """
            SELECT target_id FROM edges
            WHERE source_kind='thesis' AND target_kind='memory_node'
              AND edge_type IN ('supports', 'derived_from')
            ORDER BY id LIMIT 1
            """
        ).fetchone()
        stale = db.connection.execute(
            """
            SELECT id FROM memory_nodes
            WHERE node_type='reflection'
            ORDER BY id LIMIT 1
            """
        ).fetchone()
    finally:
        db.close()
    if row is None or helpful is None or stale is None:
        raise RuntimeError("agent-continuity-loop requires mvp-eval seed artifacts")
    decision_id, instrument_id, strategy_id = row
    helpful_memory_id = helpful[0]
    stale_memory_id = stale[0]

    db = open_database(db_path(home_path), create_parent=False)
    try:
        with db.transaction():
            db.connection.execute(
                """
                INSERT INTO memory_recall_events(
                    recall_id, query, strategies_used, node_ids_returned,
                    context_json, limit_k, as_of, created_at, actor_id,
                    agent_id, model_id, environment, run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "rec_agent_continuity_0001",
                    "fresh session recovery obligations memory use misuse",
                    '["bm25","graph"]',
                    f'["{helpful_memory_id}","{stale_memory_id}"]',
                    f'{{"instrument_id":"{instrument_id}","strategy_id":"{strategy_id}"}}',
                    5,
                    (_ANCHOR + timedelta(days=40)).isoformat(),
                    (_ANCHOR + timedelta(days=40)).isoformat(),
                    "agent:fixture",
                    "agent-continuity-fixture",
                    "local-fixture-model",
                    "paper",
                    "run-agent-continuity-001",
                ),
            )
            db.connection.execute(
                """
                INSERT INTO edges(id, source_kind, source_id, target_kind,
                                  target_id, edge_type, created_at, actor_id)
                VALUES (?, 'decision', ?, 'memory_node', ?, 'supports', ?, 'agent:fixture')
                """,
                ("edg_agent_continuity_recall_used", decision_id, helpful_memory_id,
                 (_ANCHOR + timedelta(days=40, minutes=1)).isoformat()),
            )
            db.connection.execute(
                """
                INSERT INTO edges(id, source_kind, source_id, target_kind,
                                  target_id, edge_type, created_at, actor_id)
                VALUES (?, 'decision', ?, 'memory_node', ?, 'contradicts', ?, 'agent:fixture')
                """,
                ("edg_agent_continuity_recall_contradicted", decision_id, stale_memory_id,
                 (_ANCHOR + timedelta(days=40, minutes=2)).isoformat()),
            )
    finally:
        db.close()

    _call(ctx.home, "memory.reflect", {
        "target_kind": "decision",
        "target_id": decision_id,
        "body": "Quarantined process candidate: require more local evidence before changing playbook rules.",
        "importance": 7,
        "meta_json": {
            "policy_candidate": {
                "status": "quarantined",
                "candidate_statement": "Require scoped review before promoting this process lesson.",
                "scope": {"strategy_id": strategy_id},
                "evidence": {
                    "reflection_ids": [stale_memory_id],
                    "support_case_count": 1,
                    "contradiction_case_count": 1,
                    "caveats": ["fixture_quarantine", "single_reflection_not_policy"],
                },
            }
        },
    }, suffix="agent-continuity-quarantined-policy")

    counts["recall_receipts"] = counts.get("recall_receipts", 0) + 1
    counts["policy_quarantine_reflections"] = counts.get("policy_quarantine_reflections", 0) + 1
    return counts


def _pm_market_args(i: int, *, loop: str, state: str = "open") -> dict[str, Any]:
    close_at = (_ANCHOR + timedelta(days=10 + i)).isoformat()
    return {
        "source": "polymarket",
        "external_id": f"fixture-{loop}-{i:02d}",
        "title": f"PM fixture {loop} market {i:02d}",
        "question": f"Will fixture event {loop}-{i:02d} resolve YES?",
        "url": f"https://polymarket.example.invalid/event/{loop}-{i:02d}",
        "state": state,
        "mechanism": "clob",
        "resolution_source": "market_contract",
        "bound_via": "manual",
        "opened_at": (_ANCHOR - timedelta(days=3)).isoformat(),
        "close_at": close_at,
        "venue_metadata_json": {
            "outcomes": ["YES", "NO"],
            "condition_id": f"0xfixture{loop.replace('-', '')}{i:02d}",
        },
        "metadata_json": {
            "fixture": "trade-trace-j8g8",
            "loop": loop,
            "refetchable_adapter_cache": False,
        },
    }


def _build_forecast_only_pm_loop(
    ctx: _FixtureSeedContext,
    counts: _FixtureCounts,
) -> _FixtureCounts:
    """Seed five PM markets with forecasts only and no decisions.

    This target is used for forecast-only evaluation loops: it binds
    manual/local Polymarket-shaped markets, attaches instruments/theses,
    and records binary forecasts without any trading decisions.
    """

    venue = _call(ctx.home, "venue.add", {
        "name": "Polymarket", "kind": "prediction_market",
    }, suffix="pm-forecast-venue").get("id")
    counts["venues"] = counts.get("venues", 0) + 1
    for i in range(5):
        market = _call(ctx.home, "market.bind", _pm_market_args(i, loop="forecast-only"), suffix=f"pm-forecast-market-{i}").get("id")
        inst = _call(ctx.home, "instrument.add", {
            "venue_id": venue,
            "asset_class": "prediction_market",
            "title": f"Forecast-only PM {i:02d}",
            "currency_or_collateral": "USDC",
            "metadata_json": {"market_id": market, "loop": "forecast-only"},
        }, suffix=f"pm-forecast-inst-{i}").get("id")
        thesis = _call(ctx.home, "thesis.add", {
            "instrument_id": inst,
            "side": "yes" if i % 2 == 0 else "no",
            "body": f"Forecast-only PM thesis {i:02d}: estimate binary event probability before close.",
        }, suffix=f"pm-forecast-thesis-{i}").get("id")
        _call(ctx.home, "forecast.add", {
            "thesis_id": thesis,
            "kind": "binary",
            "yes_label": "yes",
            "resolution_at": (_ANCHOR + timedelta(days=10 + i)).isoformat(),
            "outcomes": [
                {"outcome_label": "yes", "probability": 0.42 + i * 0.05},
                {"outcome_label": "no", "probability": 0.58 - i * 0.05},
            ],
            "rationale_body": f"Forecast-only PM rationale {i:02d} based on local fixture signals.",
        }, suffix=f"pm-forecast-fc-{i}")
        counts["markets"] = counts.get("markets", 0) + 1
        counts["instruments"] = counts.get("instruments", 0) + 1
        counts["theses"] = counts.get("theses", 0) + 1
        counts["forecasts"] = counts.get("forecasts", 0) + 1
    return counts


def _build_mvp_eval_pm_loop(
    ctx: _FixtureSeedContext,
    counts: _FixtureCounts,
) -> _FixtureCounts:
    """Seed an eight-market Polymarket trading loop plus forecast-only overlay."""

    venue = _call(ctx.home, "venue.add", {
        "name": "Polymarket Trading", "kind": "prediction_market",
    }, suffix="pm-trading-venue").get("id")
    strat = _call(ctx.home, "strategy.create", {
        "name": "PM fixture trading loop",
        "slug": "pm-fixture-trading-loop",
        "hypothesis": "Local-only Polymarket binary markets can be evaluated via disciplined forecasts and paper decisions.",
    }, suffix="pm-trading-strategy").get("id")
    counts["venues"] = counts.get("venues", 0) + 1
    counts["strategies"] = counts.get("strategies", 0) + 1
    decision_types = ["watch", "skip", "paper_enter", "paper_exit", "actual_enter", "actual_exit", "add", "reduce"]
    for i in range(8):
        market = _call(ctx.home, "market.bind", _pm_market_args(i, loop="trading"), suffix=f"pm-trading-market-{i}").get("id")
        inst = _call(ctx.home, "instrument.add", {
            "venue_id": venue,
            "asset_class": "prediction_market",
            "title": f"Trading PM {i:02d}",
            "currency_or_collateral": "USDC",
            "metadata_json": {"market_id": market, "loop": "trading"},
        }, suffix=f"pm-trading-inst-{i}").get("id")
        thesis = _call(ctx.home, "thesis.add", {
            "instrument_id": inst,
            "side": "yes" if i % 2 == 0 else "no",
            "body": f"Trading PM thesis {i:02d}: local-only edge estimate for binary market.",
            "strategy_id": strat,
        }, suffix=f"pm-trading-thesis-{i}").get("id")
        _call(ctx.home, "forecast.add", {
            "thesis_id": thesis,
            "kind": "binary",
            "yes_label": "yes",
            "resolution_at": (_ANCHOR + timedelta(days=12 + i)).isoformat(),
            "outcomes": [
                {"outcome_label": "yes", "probability": 0.35 + i * 0.04},
                {"outcome_label": "no", "probability": 0.65 - i * 0.04},
            ],
            "rationale_body": f"Trading PM forecast rationale {i:02d}; no live adapter data used.",
        }, suffix=f"pm-trading-fc-{i}")
        dtype = decision_types[i]
        dargs = _build_decision_args(dtype, [inst], [thesis], seq=0, strategy_id=strat)
        dargs["instrument_id"] = inst
        dargs["thesis_id"] = thesis if dtype not in {"skip"} else dargs.get("thesis_id", thesis)
        if dtype == "skip":
            dargs["reason"] = "PM fixture: spread wider than local edge estimate"
        _call(ctx.home, "decision.add", dargs, suffix=f"pm-trading-decision-{i}")
        counts["markets"] = counts.get("markets", 0) + 1
        counts["instruments"] = counts.get("instruments", 0) + 1
        counts["theses"] = counts.get("theses", 0) + 1
        counts["forecasts"] = counts.get("forecasts", 0) + 1
        counts["decisions"] = counts.get("decisions", 0) + 1
    return _build_forecast_only_pm_loop(ctx, counts)


FIXTURE_PROFILES: dict[str, _FixtureBuilderProfile] = {
    "mvp-eval-pm": _FixtureBuilderProfile(
        target="mvp-eval-pm",
        builders=(_build_mvp_eval_pm_loop,),
    ),
    "forecast-only-pm": _FixtureBuilderProfile(
        target="forecast-only-pm",
        builders=(_build_forecast_only_pm_loop,),
    ),
    "mvp-eval-rich": _FixtureBuilderProfile(
        target="mvp-eval-rich",
        builders=(
            _build_mvp_eval_base_journal,
            _build_mvp_eval_rich_reporting_overlay,
        ),
    ),
    "agent-continuity-loop": _FixtureBuilderProfile(
        target="agent-continuity-loop",
        builders=(
            _build_mvp_eval_base_journal,
            _build_mvp_eval_rich_reporting_overlay,
            _build_agent_continuity_loop_overlay,
        ),
    ),
}


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
        is_write=False,
        **_examples_for("journal.fixture_seed"),
        description=(
            "Populate the journal with a deterministic fixture for the "
            "MVP eval harness (bead trade-trace-8dv). Optional arg "
            "target selects one of the supported fixture profiles. The seed runs "
            "under a frozen clock so three invocations on a fresh home "
            "produce byte-identical content."
        ),
    )
