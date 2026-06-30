# -*- coding: utf-8 -*-
"""US-short industry (GICS) heat producer (§4.3 硬分主力 = 官方行业组) — pure engine.

Design authority: docs/us_short_system_design.md §4.3 + §4.2 ("赛道 = GICS/主题池内分位"):
  the 35% theme/track block's INDUSTRY half = GICS official-industry strength. §4.3 names five inputs —
  行业强度 / 赛道内上涨广度 / 创新高比例 / 龙头强度 / 相对 SPY/QQQ 强度 — all from FMP price + GICS
  classification (no paid sector ETF). This engine PRODUCES the raw per-stock `industry_heat_score` that the
  §4.2 35%-block assembly (engine/us_short_theme_block.py) and the per-stock theme-heat scorer
  (engine/us_short_theme_heat.py) consume as their `industry_heat_score` input.

This is the THEME-side analog of engine/us_short_momentum.py::compute_momentum_features: PURE (no network, no
provider, NO A-share crossing — it does NOT import the A-share engine/egs_industry_heat.py), it consumes
already-fetched PIT-bearing dated CLOSE series grouped by GICS sector (each = {as_of, session, adjustment_mode,
points:[{date, close, volume?}]}; + the SPY/QQQ benchmark dated series; the real GICS classification + price
fetch is the gated round-2 data layer, SR-PROVIDER-001), computes per-sector heat sub-metrics, then maps each
sector to a 0-100 cross-sector PERCENTILE (§4.2 "GICS 池内分位") that every member stock inherits.

PIT + clock (R-USSHORT-BATCH5-MOMENTUM-COVERAGE-PIT-COMPARABILITY-GAP analog, Cut 3a, input-rework half): each
series is PIT-cut to its `as_of` (a point dated AFTER as_of is BLOCKED — no look-ahead) over a strictly-ascending
unique date axis, and ALL valid series (members + benchmarks) must share ONE (as_of, session, adjustment_mode)
clock — a non-uniform clock is fail-closed (`IndustryHeatError`), so heat is never computed from mixed-as-of /
cross-adjustment data. Exact within-window daily-date alignment of members vs the benchmark is the GATED data-layer
assembly's contract (R5 rationale: alignment is only meaningfully enforced where series are assembled with
provenance); this engine enforces the PIT cut + the uniform decision clock. The sub-metric math below is unchanged
from the prior bare-array version. The LIVE Massive/GICS assembly stays gated (Cut 3b, SR-PROVIDER-001).

§4.3 SELF-CERTIFICATION CONTRACT (documented, not enforceable here): the caller MUST pass the BASE universe /
full GICS peer group — NOT the candidate pool / Top15 / a manual watchlist (§4.3 "不能用候选池/Top15/人工
watchlist 自证"). A sector's heat is computed over ALL its passed members; passing only a hand-picked subset
would self-certify. The producer cannot know which universe it was handed (the data layer owns that), so this
is a documented contract — the same boundary the momentum slice draws for its injected series.

v1 sub-metrics (each a §13.1 #32 / #14 forward-calibratable prior, NOT validated alpha) — per GICS sector:
  * group_rel_strength = sector mean 3-month return − benchmark 3-month return   (行业强度 = 相对 SPY/QQQ)
  * breadth_up_frac    = fraction of members with a positive 1-month return        (赛道内上涨广度)
  * new_high_frac      = fraction of members whose latest close == max of the trailing window (创新高比例)
  * leader_rs          = mean 3-month return of the top-quartile members − benchmark (龙头强度)
Each sub-metric is cross-sectionally percentile-ranked across sectors, equal-weighted into a composite (a
MISSING sub-metric fills the NEUTRAL percentile, never re-weighting the rest), and the composite is
re-percentiled → the 0-100 sector `industry_heat_score` (equal-weight-of-percentiles is robust to scale/outliers,
no z-score tuning; mirrors the momentum design). The cross-sectional industry⊥theme orthogonalization
(防双重计数) is NOT here — it belongs to the §4.2 35%-block assembly (theme_block). The provisional cross-sector
THEME heat (§4.3 provisional_theme_lane) is a SEPARATE producer, not this slice.

COVERAGE FAIL-CLOSED (§4.3 / mirrors momentum min-coverage): a sector with fewer than MIN_SECTOR_MEMBERS members
carrying enough history is `insufficient_members` — its members get NO industry heat (not a fake neutral), so a
1-2 name "sector" cannot manufacture heat. All numeric inputs are strictly validated (reject bool / NaN / Inf /
numeric string AND non-positive close prices); a member with no GICS sector, too-short, or non-positive-priced
history simply does not contribute (and a sector emptied that way falls to insufficient_sectors, emitting no heat).
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

# §13.1 #32 / #14 forward priors (NOT frozen const; mirror the momentum lookbacks).
RS_WINDOW = 63         # 3-month relative-strength / leader window (≈ 63 trading days)
BREADTH_WINDOW = 21    # 1-month breadth-up window (≈ 21 trading days)
NEW_HIGH_WINDOW = 63   # trailing window for the "at a new high" test
LEADER_FRAC = 0.25     # top quartile (by 3-month return) = the sector's leaders
MIN_SECTOR_MEMBERS = 3    # a sector needs >= this many members with usable history to be scored
_MIN_HISTORY = RS_WINDOW + 1   # need a 3-month return to contribute the strength metrics

NEUTRAL_PERCENTILE = 50.0
METRIC_KEYS = ("group_rel_strength", "breadth_up_frac", "new_high_frac", "leader_rs")


def _finite(x: Any) -> float | None:
    """Strict finite number → float, else None (rejects bool, numeric string, NaN/Inf)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _clean_series(series: Any) -> list[float] | None:
    """Ascending daily CLOSE price series → list[float]; None if not a list / shorter than _MIN_HISTORY / has a
    non-finite OR NON-POSITIVE point. A stock close is strictly positive — a 0/negative price is invalid data,
    never heat evidence (R-USSHORT-INDUSTRY-HEAT-NONPOSITIVE-CLOSE-FAILOPEN: an all-zero/negative member would
    otherwise pass `at_new_high` and manufacture new_high_frac heat). A bad point fails the WHOLE series (a hole
    would corrupt the return/new-high math). Also cleans the SPY/QQQ benchmark, so a non-positive benchmark is
    likewise rejected (→ relative strength degrades to neutral, never used as evidence)."""
    if not isinstance(series, (list, tuple)) or len(series) < _MIN_HISTORY:
        return None
    out = []
    for v in series:
        f = _finite(v)
        if f is None or f <= 0.0:
            return None
        out.append(f)
    return out


def _ret(series: list[float], lookback: int) -> float | None:
    """Simple return over `lookback` trading days; None if too short or the base price is non-positive."""
    if len(series) < lookback + 1:
        return None
    base = series[-1 - lookback]
    if base <= 0:
        return None
    return series[-1] / base - 1.0


class IndustryHeatError(ValueError):
    """The injected series carry a non-uniform decision clock (mixed as_of / session / adjustment_mode) — heat
    is never computed from inconsistent-clock data (fail-closed)."""


_DATED_SERIES_KEYS = {"as_of", "session", "adjustment_mode", "points"}
_POINT_REQUIRED = {"date", "close"}
_POINT_ALLOWED = {"date", "close", "volume"}


def _valid_date(s: Any):
    """Strict YYYY-MM-DD -> datetime.date, else None (no other format / no timezone games)."""
    if not (isinstance(s, str) and len(s) == 10):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_dated_series(series: Any) -> dict | None:
    """Validate + PIT-cut a date/as_of/session/adjustment-bearing CLOSE series ->
    {as_of: date, session: str, adjustment_mode: str, closes: [float,...]} or None (fail-closed).

    PIT: a point dated AFTER `as_of` is BLOCKED (excluded — no look-ahead); the RAW point axis must be strictly
    ascending + unique by date BEFORE the cut (corrupt/duplicated -> None). The kept closes go through THIS
    engine's `_clean_series` (finite + strictly POSITIVE + >= _MIN_HISTORY after the cut → an IPO/short/
    non-positive name -> None). Own copy mirroring engine/us_short_momentum.py's parser but using the
    non-positive-rejecting `_clean_series` (the established per-engine-helper convention)."""
    if not (isinstance(series, dict) and set(series) == _DATED_SERIES_KEYS):
        return None
    as_of = _valid_date(series["as_of"])
    if as_of is None:
        return None
    session, adj = series["session"], series["adjustment_mode"]
    if not (isinstance(session, str) and session and isinstance(adj, str) and adj):
        return None
    pts = series["points"]
    if not isinstance(pts, list) or not pts:
        return None
    kept: list[Any] = []
    prev = None
    for p in pts:
        if not (isinstance(p, dict) and _POINT_REQUIRED <= set(p) <= _POINT_ALLOWED):
            return None
        d = _valid_date(p["date"])
        if d is None:
            return None
        if prev is not None and d <= prev:
            return None                       # raw axis must be strictly ascending + unique (corrupt -> None)
        prev = d
        if d <= as_of:
            kept.append(p["close"])           # PIT cut: future points BLOCKED; _clean_series validates value
    closes = _clean_series(kept)              # finite + strictly positive + MIN history floor (post-cut)
    if closes is None:
        return None
    return {"as_of": as_of, "session": session, "adjustment_mode": adj, "closes": closes}


def _benchmark_return(spy_closes: Any, qqq_closes: Any, lookback: int) -> float | None:
    """Mean of the available SPY/QQQ returns over `lookback` (the relative-strength baseline); None if neither
    benchmark has enough clean history (→ the relative-strength metrics degrade to neutral, not a crash)."""
    rets = []
    for bench in (spy_closes, qqq_closes):
        s = _clean_series(bench)
        if s is not None:
            r = _ret(s, lookback)
            if r is not None:
                rets.append(r)
    return sum(rets) / len(rets) if rets else None


def _percentile_rank(values: dict[str, float]) -> dict[str, float]:
    """Map {key: raw value} -> {key: percentile 0-100} by cross-sectional rank. Ties share the average rank.
    A single value -> 50.0 (mid; can't rank against peers). Empty -> {}."""
    if not values:
        return {}
    keys = list(values)
    if len(keys) == 1:
        return {keys[0]: NEUTRAL_PERCENTILE}
    ordered = sorted(keys, key=lambda k: values[k])
    n = len(ordered)
    out: dict[str, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[ordered[j + 1]] == values[ordered[i]]:
            j += 1
        pct = 100.0 * ((i + j) / 2.0) / (n - 1)   # average rank position of the tie group → 0-100
        for k in range(i, j + 1):
            out[ordered[k]] = pct
        i = j + 1
    return out


def _sector_raw_metrics(members: list[dict], bench_rs: float | None) -> dict[str, Any]:
    """Raw §4.3 sub-metrics for ONE sector's members (each member = {ret_3m, ret_1m, at_new_high}). A metric
    whose inputs are unavailable (no benchmark / no member return) is None and the composite neutral-fills it."""
    n = len(members)
    ret_3m = [m["ret_3m"] for m in members if m["ret_3m"] is not None]
    ret_1m = [m["ret_1m"] for m in members if m["ret_1m"] is not None]
    grp_mean_3m = sum(ret_3m) / len(ret_3m) if ret_3m else None
    group_rel = grp_mean_3m - bench_rs if (grp_mean_3m is not None and bench_rs is not None) else None
    breadth = sum(1 for r in ret_1m if r > 0) / len(ret_1m) if ret_1m else None
    new_high = sum(1 for m in members if m["at_new_high"]) / n
    leaders = sorted(ret_3m, reverse=True)
    k = max(1, int(len(leaders) * LEADER_FRAC))
    leader_mean = sum(leaders[:k]) / k if leaders else None
    leader_rs = leader_mean - bench_rs if (leader_mean is not None and bench_rs is not None) else None
    return {"members": n, "group_rel_strength": group_rel, "breadth_up_frac": breadth,
            "new_high_frac": new_high, "leader_rs": leader_rs}


def industry_heat_block(members_by_ticker: Any, *, spy_series: Any = None, qqq_series: Any = None) -> dict[str, Any]:
    """Map per-ticker {sector, series} → a 0-100 cross-sector PERCENTILE `industry_heat_score` per ticker (§4.3).

    members_by_ticker = {ticker: {"sector": <GICS str>, "series": <PIT-bearing dated CLOSE series>}} — the BASE
    universe / GICS peer group (NOT the candidate pool; see the self-certification contract above). spy_series /
    qqq_series = the SPY/QQQ benchmark dated series. Each series is PIT-cut to its as_of (future points BLOCKED)
    and ALL valid series (members + benchmarks) must share ONE (as_of, session, adjustment_mode) decision clock —
    a non-uniform clock is fail-closed (`IndustryHeatError`). Exact within-window member↔benchmark daily-date
    alignment is the gated assembly's contract (R5 rationale); the sub-metric math is unchanged from the prior
    bare-array version.

    Per GICS sector with >= MIN_SECTOR_MEMBERS usable members: compute the four §4.3 sub-metrics, cross-sectionally
    percentile-rank each across sectors, equal-weight into a composite (missing sub-metric → NEUTRAL percentile),
    re-percentile the composite → the sector `industry_heat_score`, which every member stock inherits. A sector
    below MIN_SECTOR_MEMBERS is `insufficient_members` and its members get NO heat (fail-closed, no fake neutral).

    Returns {industry_heat_by_ticker: {ticker: 0-100}, sector_heat: {sector: 0-100},
             sector_metrics: {sector: {members, group_rel_strength, breadth_up_frac, new_high_frac, leader_rs}},
             insufficient_sectors: [sector, ...], min_sector_members: int}. Raises IndustryHeatError on a
    non-uniform decision clock.
    """
    if not isinstance(members_by_ticker, dict):
        members_by_ticker = {}
    clocks: set = set()
    spy_p = _parse_dated_series(spy_series)
    qqq_p = _parse_dated_series(qqq_series)
    for bp in (spy_p, qqq_p):
        if bp is not None:
            clocks.add((bp["as_of"], bp["session"], bp["adjustment_mode"]))
    bench_rs = _benchmark_return(spy_p["closes"] if spy_p else None,
                                 qqq_p["closes"] if qqq_p else None, RS_WINDOW)

    # 1) per-member PIT-cut series + returns, grouped by GICS sector (bad/short/non-positive/sectorless drop out).
    #    `seen_sectors` records every sector that appeared with a valid GICS label, so a sector whose members are
    #    ALL dropped (e.g. all non-positive closes) still falls to insufficient_sectors, not silently vanishing.
    by_sector: dict[str, list[dict]] = {}
    seen_sectors: set[str] = set()
    for tkr, rec in members_by_ticker.items():
        if not isinstance(rec, dict):
            continue
        sector = rec.get("sector")
        if not isinstance(sector, str) or not sector.strip():
            continue
        sector = sector.strip()
        seen_sectors.add(sector)
        parsed = _parse_dated_series(rec.get("series"))
        if parsed is None:
            continue
        clocks.add((parsed["as_of"], parsed["session"], parsed["adjustment_mode"]))
        px = parsed["closes"]
        by_sector.setdefault(sector, []).append({
            "ticker": tkr,
            "ret_3m": _ret(px, RS_WINDOW),
            "ret_1m": _ret(px, BREADTH_WINDOW),
            "at_new_high": px[-1] >= max(px[-NEW_HIGH_WINDOW:]),
        })

    # uniform decision clock (Cut 3a): every valid member + benchmark series must share one as_of/session/adjustment
    if len(clocks) > 1:
        raise IndustryHeatError(
            "industry_heat 输入序列时钟不统一（须同一 as_of/session/adjustment_mode；fail-closed）: "
            + str(sorted(str(c) for c in clocks)))

    # 2) per-sector raw sub-metrics over EVERY seen sector (a sector thinned below the gate by dropped members —
    #    including one emptied entirely — falls to insufficient_sectors and emits no heat, never neutral/positive)
    sector_metrics: dict[str, dict] = {}
    insufficient_sectors: list[str] = []
    for sector in seen_sectors:
        members = by_sector.get(sector, [])
        if len(members) < MIN_SECTOR_MEMBERS:
            insufficient_sectors.append(sector)
        else:
            sector_metrics[sector] = _sector_raw_metrics(members, bench_rs)

    # 3) cross-sector percentile per sub-metric
    per_metric_pct: dict[str, dict[str, float]] = {}
    for key in METRIC_KEYS:
        raw = {s: m[key] for s, m in sector_metrics.items() if m[key] is not None}
        if raw:
            per_metric_pct[key] = _percentile_rank(raw)

    # 4) composite per sector = mean of the 4 sub-metric percentiles (missing → NEUTRAL), then re-percentile
    composite: dict[str, float] = {}
    for sector in sector_metrics:
        vals = [per_metric_pct[k][sector] if (k in per_metric_pct and sector in per_metric_pct[k])
                else NEUTRAL_PERCENTILE for k in METRIC_KEYS]
        composite[sector] = sum(vals) / len(METRIC_KEYS)
    sector_heat = _percentile_rank(composite)

    # 5) every member of a scored sector inherits that sector's heat (insufficient sectors → no member heat)
    industry_heat_by_ticker: dict[str, float] = {}
    for sector, members in by_sector.items():
        if sector in sector_heat:
            for m in members:
                industry_heat_by_ticker[m["ticker"]] = sector_heat[sector]

    return {
        "industry_heat_by_ticker": industry_heat_by_ticker,
        "sector_heat": sector_heat,
        "sector_metrics": sector_metrics,
        "insufficient_sectors": sorted(insufficient_sectors),
        "min_sector_members": MIN_SECTOR_MEMBERS,
    }
