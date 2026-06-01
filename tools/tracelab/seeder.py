"""TraceLab Polymarket Gamma sidecar seeder.

Selects near-term binary YES/NO Gamma markets, binds them through the public
Trade Trace tool surface, snapshots them, and records a watch marker so existing
watchlist/work_queue reports can surface the seeded set.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from trade_trace.mcp_server import mcp_call

GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
ALLOWED_GAMMA_HOST = "gamma-api.polymarket.com"
DEFAULT_ARTIFACT_NAME = "tracelab_seeded_condition_ids.json"


class SeederAbort(RuntimeError):
    """Hard abort for schema drift, budget exhaustion, or unsafe config."""

    def __init__(
        self,
        message: str,
        *,
        candidates: list["Candidate"] | None = None,
        gamma_requests: int | None = None,
        histogram: dict[str, int] | None = None,
    ) -> None:
        super().__init__(message)
        self.candidates = candidates
        self.gamma_requests = gamma_requests
        self.histogram = histogram



@dataclass
class GammaBudget:
    cap: int
    used: int = 0

    def spend(self) -> None:
        if self.used >= self.cap:
            raise SeederAbort(f"Gamma request budget exhausted: {self.used}/{self.cap}")
        self.used += 1


@dataclass
class Candidate:
    gamma_market_id: str
    condition_id: str
    question: str | None
    end_date: str
    liquidity: float | None = None
    volume: float | None = None


@dataclass
class DiscoveryResult:
    candidates: list[Candidate]
    gamma_requests: int
    histogram: dict[str, int]
    complete: bool = True
    abort_reason: str | None = None

    @property
    def candidate_count(self) -> int:
        return len(self.candidates)

    def __iter__(self):  # Backward-compatible unpacking as (candidates, gamma_requests).
        yield self.candidates
        yield self.gamma_requests


@dataclass
class SeedResult:
    artifact_path: str
    gamma_requests: int
    candidate_count: int
    accepted_count: int
    bound_count: int
    snapshotted_count: int
    condition_ids: list[str] = field(default_factory=list)
    market_ids: list[str] = field(default_factory=list)
    complete: bool = True
    abort_reason: str | None = None
    histogram: dict[str, int] = field(default_factory=dict)


def _decode_json_list(value: Any, *, field: str, market_id: str) -> list[Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise SeederAbort(f"Gamma schema drift: {field} for market {market_id} is not valid JSON") from exc
    if not isinstance(value, list):
        raise SeederAbort(f"Gamma schema drift: {field} for market {market_id} is {type(value).__name__}, expected list/JSON list string")
    return value


def _outcome_label(outcome: Any) -> str:
    if isinstance(outcome, str):
        return outcome.strip().lower()
    if isinstance(outcome, dict):
        return str(outcome.get("name") or outcome.get("label") or outcome.get("outcome") or "").strip().lower()
    return ""


def is_binary_yes_no_market(raw: dict[str, Any]) -> bool:
    """Decode Gamma's JSON-string outcomes and accept exactly {yes,no}."""

    market_id = str(raw.get("id") or raw.get("marketId") or raw.get("conditionId") or "unknown")
    if raw.get("market_type") == "scalar" or raw.get("type") == "scalar" or raw.get("isScalar"):
        return False
    if "outcomes" not in raw and "tokens" not in raw:
        return False
    outcomes = _decode_json_list(raw.get("outcomes", raw.get("tokens")), field="outcomes", market_id=market_id)
    labels = {_outcome_label(outcome) for outcome in outcomes}
    return len(outcomes) == 2 and labels == {"yes", "no"}


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def rejection_reason_for_market(raw: dict[str, Any], *, as_of: datetime, min_days: int, max_days: int, min_liquidity: float) -> str | None:
    if not is_binary_yes_no_market(raw):
        return "non_binary"
    condition_id = raw.get("conditionId") or raw.get("condition_id")
    if not condition_id:
        return "missing_condition_id"
    gamma_market_id = raw.get("id") or raw.get("marketId") or raw.get("gammaMarketId")
    if not gamma_market_id:
        return "missing_market_id"
    end_dt = _parse_datetime(raw.get("endDate") or raw.get("close_at") or raw.get("end_date"))
    if end_dt is None:
        return "missing_end_date"
    lower = as_of + timedelta(days=min_days)
    upper = as_of + timedelta(days=max_days)
    if not (lower <= end_dt <= upper):
        return "outside_window"
    liquidity = _float_or_none(raw.get("liquidity") or raw.get("liquidityNum"))
    if liquidity is not None and liquidity < min_liquidity:
        return "low_liquidity"
    return None


def candidate_from_market(raw: dict[str, Any], *, as_of: datetime, min_days: int, max_days: int, min_liquidity: float) -> Candidate | None:
    if rejection_reason_for_market(raw, as_of=as_of, min_days=min_days, max_days=max_days, min_liquidity=min_liquidity):
        return None
    condition_id = raw.get("conditionId") or raw.get("condition_id")
    gamma_market_id = raw.get("id") or raw.get("marketId") or raw.get("gammaMarketId")
    end_dt = _parse_datetime(raw.get("endDate") or raw.get("close_at") or raw.get("end_date"))
    liquidity = _float_or_none(raw.get("liquidity") or raw.get("liquidityNum"))
    volume = _float_or_none(raw.get("volume") or raw.get("volumeNum"))
    return Candidate(str(gamma_market_id), str(condition_id), raw.get("question") or raw.get("title"), end_dt.isoformat().replace("+00:00", "Z"), liquidity, volume)

def _confirm_gamma_allowlist(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme != "https" or parsed.netloc != ALLOWED_GAMMA_HOST:
        raise SeederAbort(f"Gamma host not allowlisted: {base_url}")
    return base_url.rstrip("/")


def fetch_gamma_markets(base_url: str, *, budget: GammaBudget, limit: int, offset: int, timeout_seconds: int) -> list[dict[str, Any]]:
    base = _confirm_gamma_allowlist(base_url)
    query = urllib.parse.urlencode({"limit": limit, "offset": offset, "active": "true", "closed": "false", "order": "endDate", "ascending": "true"})
    url = f"{base}/markets?{query}"
    budget.spend()
    req = urllib.request.Request(url, headers={"User-Agent": "trade-trace-tracelab-seeder/0.1"})
    with urllib.request.urlopen(req, timeout=timeout_seconds) as response:  # noqa: S310 - allowlisted URL only
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict):
        items = payload.get("markets") or payload.get("data") or payload.get("items")
    else:
        items = payload
    if not isinstance(items, list):
        raise SeederAbort("Gamma schema drift: /markets did not return a list")
    if any(not isinstance(item, dict) for item in items):
        raise SeederAbort("Gamma schema drift: /markets item was not an object")
    return items


def _initial_histogram() -> dict[str, int]:
    return {
        "pages_scanned": 0,
        "items_scanned": 0,
        "non_binary": 0,
        "missing_condition_id": 0,
        "missing_market_id": 0,
        "missing_end_date": 0,
        "outside_window": 0,
        "low_liquidity": 0,
        "duplicate_condition_id": 0,
        "accepted": 0,
    }


def discover_candidates(*, base_url: str = GAMMA_BASE_URL, request_cap: int = 100, target: int = 50, page_size: int = 100, timeout_seconds: int = 10, as_of: datetime | None = None, min_days: int = 7, max_days: int = 14, min_liquidity: float = 0.0, fetch_page: Callable[..., list[dict[str, Any]]] = fetch_gamma_markets) -> DiscoveryResult:
    budget = GammaBudget(request_cap)
    as_of = as_of or datetime.now(UTC)
    candidates: list[Candidate] = []
    seen_conditions: set[str] = set()
    histogram = _initial_histogram()
    offset = 0
    try:
        while len(candidates) < target:
            page = fetch_page(base_url, budget=budget, limit=page_size, offset=offset, timeout_seconds=timeout_seconds)
            if not page:
                break
            histogram["pages_scanned"] += 1
            for raw in page:
                histogram["items_scanned"] += 1
                reason = rejection_reason_for_market(raw, as_of=as_of, min_days=min_days, max_days=max_days, min_liquidity=min_liquidity)
                if reason is not None:
                    histogram[reason] += 1
                    continue
                cand = candidate_from_market(raw, as_of=as_of, min_days=min_days, max_days=max_days, min_liquidity=min_liquidity)
                if cand is None:
                    histogram["non_binary"] += 1
                    continue
                if cand.condition_id in seen_conditions:
                    histogram["duplicate_condition_id"] += 1
                    continue
                candidates.append(cand)
                seen_conditions.add(cand.condition_id)
                histogram["accepted"] += 1
                if len(candidates) >= target:
                    break
            offset += len(page)
            if len(page) < page_size:
                break
    except SeederAbort as exc:
        if exc.candidates is None:
            exc.candidates = candidates
        if exc.gamma_requests is None:
            exc.gamma_requests = budget.used
        if exc.histogram is None:
            exc.histogram = histogram
        raise
    return DiscoveryResult(candidates, budget.used, histogram, complete=True)

def _ok_data(envelope: Any) -> dict[str, Any]:
    if not getattr(envelope, "ok", False):
        raise SeederAbort(f"public tool call failed: {envelope}")
    return dict(envelope.data)


def bind_snapshot_and_mark(home: str, candidates: list[Candidate], *, artifact_path: Path, sleep_seconds: float = 0.0, gamma_requests: int = 0, histogram: dict[str, int] | None = None) -> SeedResult:
    condition_ids: list[str] = []
    market_ids: list[str] = []
    bound = 0
    snapshotted = 0
    for cand in candidates:
        bind = _ok_data(mcp_call("market.bind", {"home": home, "source": "polymarket", "external_id": cand.gamma_market_id, "idempotency_key": f"tracelab-seed-bind:{cand.gamma_market_id}"}))
        bound += 1
        market_id = bind["id"]
        snap = _ok_data(mcp_call("snapshot.fetch", {"home": home, "market_id": market_id, "at": "now", "idempotency_key": f"tracelab-seed-snapshot:{cand.gamma_market_id}"}))
        snapshotted += 1
        _ok_data(mcp_call("decision.add", {
            "home": home,
            "instrument_id": market_id,
            "snapshot_id": snap["id"],
            "type": "watch",
            "side": "yes",
            "reason": f"tracelab_seeded polymarket_gamma_market={cand.gamma_market_id} condition_id={cand.condition_id}",
            "review_by": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "tags": ["tracelab_seeded", "polymarket_gamma", "binary_yes_no", "near_term"],
            "metadata_json": json.dumps({"tracelab_seeded": True, "condition_id": cand.condition_id, "gamma_market_id": cand.gamma_market_id}),
            "idempotency_key": f"tracelab-seed-watch:{cand.condition_id}",
        }))
        condition_ids.append(cand.condition_id)
        market_ids.append(market_id)
        if sleep_seconds:
            time.sleep(sleep_seconds)
    histogram = histogram or (_initial_histogram() | {"accepted": len(candidates)})
    _write_artifact(
        artifact_path,
        candidates=candidates,
        condition_ids=condition_ids,
        dry_run=False,
        complete=True,
        gamma_requests=gamma_requests,
        histogram=histogram,
    )
    return SeedResult(str(artifact_path), gamma_requests, len(candidates), len(candidates), bound, snapshotted, condition_ids, market_ids, histogram=histogram)


def _write_artifact(
    path: Path,
    *,
    candidates: list[Candidate],
    condition_ids: list[str] | None = None,
    dry_run: bool,
    complete: bool,
    gamma_requests: int,
    histogram: dict[str, int],
    abort_reason: str | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = condition_ids if condition_ids is not None else [c.condition_id for c in candidates]
    payload = {
        "condition_ids": ids,
        "markets": [c.__dict__ for c in candidates],
        "dry_run": dry_run,
        "complete": complete,
        "abort_reason": abort_reason,
        "gamma_requests": gamma_requests,
        "candidate_count": len(candidates),
        "histogram": dict(histogram),
        "written_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def seed(*, home: str, artifact_path: str | None = None, dry_run: bool = False, **kwargs: Any) -> SeedResult:
    path = Path(artifact_path) if artifact_path else Path(home) / DEFAULT_ARTIFACT_NAME
    try:
        discovery = discover_candidates(**kwargs)
    except SeederAbort as exc:
        candidates = exc.candidates or []
        requests = exc.gamma_requests or 0
        histogram = exc.histogram or _initial_histogram()
        if artifact_path:
            _write_artifact(path, candidates=candidates, dry_run=dry_run, complete=False, abort_reason=str(exc), gamma_requests=requests, histogram=histogram)
        raise
    candidates = discovery.candidates
    requests = discovery.gamma_requests
    if dry_run:
        _write_artifact(path, candidates=candidates, dry_run=True, complete=True, gamma_requests=requests, histogram=discovery.histogram)
        return SeedResult(str(path), requests, len(candidates), len(candidates), 0, 0, [c.condition_id for c in candidates], [], histogram=discovery.histogram)
    return bind_snapshot_and_mark(home, candidates, artifact_path=path, gamma_requests=requests, histogram=discovery.histogram)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--artifact-path")
    parser.add_argument("--request-cap", type=int, default=100)
    parser.add_argument("--target", type=int, default=50)
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=int, default=10)
    parser.add_argument("--base-url", default=GAMMA_BASE_URL)
    parser.add_argument("--min-days", type=int, default=7)
    parser.add_argument("--max-days", type=int, default=14)
    parser.add_argument("--min-liquidity", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    result = seed(home=args.home, artifact_path=args.artifact_path, dry_run=args.dry_run, base_url=args.base_url, request_cap=args.request_cap, target=args.target, page_size=args.page_size, timeout_seconds=args.timeout_seconds, min_days=args.min_days, max_days=args.max_days, min_liquidity=args.min_liquidity)
    print(json.dumps(result.__dict__, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
