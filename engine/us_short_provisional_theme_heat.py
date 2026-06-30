# -*- coding: utf-8 -*-
"""US-short provisional cross-sector THEME heat + market-confirmation producer (§4.3 provisional_theme_lane).

Design authority: docs/us_short_system_design.md §4.3 (provisional_theme_lane / 防偷看未来) + §4.2
("赛道 = ... 主题池内分位"). Web/X/LLM DISCOVER emerging cross-sector themes (AI storage / nuclear / quantum /
robotics …) but never decide alone; to compete for a §4.5 theme seat a provisional theme must pass a
MACHINE-JUDGED market confirmation. This engine PRODUCES the PRICE-DERIVED confirmation evidence + the raw
theme heat that engine/us_short_theme_heat.py (market_confirmation_passed / continuous_theme_score) and the
§4.2 35%-block assembly (engine/us_short_theme_block.py) consume.

Sibling of engine/us_short_industry_heat.py (the GICS half of the 35% block): both turn a group's member price
series into cross-pool-percentile heat, but a THEME's group is a DISCOVERED cross-sector member LIST (not a GICS
sector) and carries two extra §4.3 duties — a volume-confirmation metric and the ANTI-CIRCULARITY guard. PURE
(no network, no provider, NO A-share crossing); the real discovery feed + member list + price fetch is the
gated round-2 data layer (SR-PROVIDER-001).

§4.3 ANTI-CIRCULARITY / 防偷看未来 CONTRACT (documented, NOT enforceable here): the caller MUST pass (a) a member
list FROZEN by `observed_at` and (b) member price/volume series from INDEPENDENT market data — NOT the web/X/LLM
discovery source that proposed the theme (§4.3 "成员名单按 observed_at 冻结；breadth/volume/RS 一律用独立价格数据
算，不拿发现源自证"). The producer computes over EXACTLY the members it is handed and cannot see how they were
chosen, so this is a data-layer contract — the same boundary momentum / industry-heat draw for their injected
series.

This slice produces the PRICE/COUNT-DERIVED subset of the 7 §4.3 confirmation items —
theme_breadth_up_frac / theme_volume_confirm_frac / theme_leader_rs / theme_member_count — as pass flags + raw
metrics, plus the cross-theme PERCENTILE raw `theme_heat` (主题池内分位). The DISCOVERY-META items
(theme_source_count / theme_persistence_weeks / theme_fit_score) are INJECTED, not computed here. The
market-confirmation GATE (>= 3 of 7 + stock strong) and the continuous theme_score (heat × persistence × fit)
already live in engine/us_short_theme_heat.py and are NOT re-implemented. Windows/thresholds are §13.1 #32
forward priors. COVERAGE FAIL-CLOSED: a theme below MIN_THEME_MEMBERS usable members is `insufficient_members`
(no heat, no flags — a 2-name "theme" cannot self-confirm). All numeric inputs are strictly validated (reject
bool / NaN / Inf / numeric string; CLOSE/benchmark prices must be strictly positive, volumes non-negative).
"""
from __future__ import annotations

import math
from typing import Any

# §13.1 #32 forward priors (NOT frozen const; mirror the momentum / industry-heat lookbacks).
RS_WINDOW = 63          # 3-month relative-strength / leader window
BREADTH_WINDOW = 21     # 1-month breadth-up window
VOL_SURGE_SHORT = 10    # recent average-volume window
VOL_SURGE_LONG = 63     # baseline average-volume window
LEADER_FRAC = 0.25      # top quartile (by 3-month return) = the theme's leaders
MIN_THEME_MEMBERS = 3   # a theme needs >= this many usable members to be scored (§4.3 anti-self-confirm)

# Confirmation pass thresholds (§13.1 #32 forward priors) for the price/count-derived items.
BREADTH_PASS_FRAC = 0.5      # >= half the members up over the breadth window
VOL_SURGE_RATIO = 1.0        # a member is volume-confirmed when recent avg vol > baseline avg vol
VOL_CONFIRM_PASS_FRAC = 0.5  # >= half the members volume-confirmed
MEMBER_COUNT_PASS = 5        # >= this many members

NEUTRAL_PERCENTILE = 50.0
_MIN_HISTORY = RS_WINDOW + 1
_METRIC_KEYS = ("breadth_up_frac", "volume_confirm_frac", "leader_rs")


def _finite(x: Any) -> float | None:
    """Strict finite number → float, else None (rejects bool, numeric string, NaN/Inf)."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def _clean_series(series: Any, min_len: int, *, positive: bool = False) -> list[float] | None:
    """Ascending numeric series → list[float]; None if not a list / shorter than `min_len` / has a non-finite
    point — or, when `positive=True` (a CLOSE / benchmark PRICE series), any NON-POSITIVE point: a 0/negative
    price is invalid data, never heat/relative-strength evidence (same class as
    R-USSHORT-INDUSTRY-HEAT-NONPOSITIVE-CLOSE-FAILOPEN). A volume series (`positive=False`) rejects only
    negatives (a zero-volume day is valid). A bad point fails the WHOLE series (don't silently drop)."""
    if not isinstance(series, (list, tuple)) or len(series) < min_len:
        return None
    out = []
    for v in series:
        f = _finite(v)
        if f is None or (f <= 0.0 if positive else f < 0.0):
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


def _vol_surge(volumes: list[float]) -> float | None:
    """Recent short-window avg volume / longer baseline avg volume; None if the baseline is non-positive."""
    short_avg = sum(volumes[-VOL_SURGE_SHORT:]) / VOL_SURGE_SHORT
    long_avg = sum(volumes[-VOL_SURGE_LONG:]) / VOL_SURGE_LONG
    return short_avg / long_avg if long_avg > 0 else None


def _benchmark_return(spy_closes: Any, qqq_closes: Any, lookback: int) -> float | None:
    """Mean of the available SPY/QQQ returns over `lookback` (relative-strength baseline); None if neither
    benchmark has enough clean history (→ the relative-strength metric degrades to neutral, not a crash)."""
    rets = []
    for bench in (spy_closes, qqq_closes):
        s = _clean_series(bench, _MIN_HISTORY, positive=True)
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
        pct = 100.0 * ((i + j) / 2.0) / (n - 1)
        for k in range(i, j + 1):
            out[ordered[k]] = pct
        i = j + 1
    return out


def _theme_raw_metrics(members: list[dict], bench_rs: float | None) -> dict[str, Any]:
    """Price/volume-derived §4.3 sub-metrics for ONE theme's members (each = {ret_3m, ret_1m, vol_surge}).
    breadth_up_frac / leader_rs use the full member denominator (closes are mandatory). volume_confirm_frac is
    coverage-aware: its denominator is ALL members (missing/invalid volume = not confirmed), so partial volume
    coverage can't manufacture full confirmation. leader_rs is None only when no benchmark is available (the
    composite then neutral-fills it)."""
    n = len(members)
    ret_3m = [m["ret_3m"] for m in members if m["ret_3m"] is not None]
    ret_1m = [m["ret_1m"] for m in members if m["ret_1m"] is not None]
    breadth = sum(1 for r in ret_1m if r > 0) / len(ret_1m) if ret_1m else None
    # volume_confirm_frac is COVERAGE-AWARE (R-USSHORT-PROVISIONAL-THEME-HEAT-PARTIAL-VOLUME-COVERAGE-FAILOPEN):
    # the denominator is ALL members (a member with missing/invalid volume counts as NOT confirmed), so thin
    # volume coverage can't convert one surging member into 100% confirmation. It is the fraction of the theme's
    # members that are volume-confirmed, not the fraction of the covered subset.
    volume_confirm = sum(1 for m in members if m["vol_surge"] is not None and m["vol_surge"] > VOL_SURGE_RATIO) / n
    leaders = sorted(ret_3m, reverse=True)
    k = max(1, int(len(leaders) * LEADER_FRAC))
    leader_mean = sum(leaders[:k]) / k if leaders else None
    leader_rs = leader_mean - bench_rs if (leader_mean is not None and bench_rs is not None) else None
    return {"member_count": n, "breadth_up_frac": breadth,
            "volume_confirm_frac": volume_confirm, "leader_rs": leader_rs}


def _confirm_flags(metrics: dict[str, Any]) -> dict[str, bool]:
    """The price/count-derived subset of the 7 §4.3 confirmation items, as pass flags (feeds
    engine/us_short_theme_heat.py::market_confirmation_passed alongside the 3 injected discovery-meta items)."""
    breadth, volume = metrics["breadth_up_frac"], metrics["volume_confirm_frac"]
    leader_rs = metrics["leader_rs"]
    return {
        "theme_breadth_up_frac": breadth is not None and breadth >= BREADTH_PASS_FRAC,
        "theme_volume_confirm_frac": volume is not None and volume >= VOL_CONFIRM_PASS_FRAC,
        "theme_leader_rs": leader_rs is not None and leader_rs > 0.0,   # leaders beat the benchmark
        "theme_member_count": metrics["member_count"] >= MEMBER_COUNT_PASS,
    }


def provisional_theme_heat_block(themes_by_id: Any, *, spy_closes: Any = None, qqq_closes: Any = None) -> dict[str, Any]:
    """Map provisional themes → cross-theme PERCENTILE `theme_heat` + price-derived confirmation flags (§4.3).

    themes_by_id = {theme_id: {"members": {ticker: {"closes": <ascending closes>, "volumes": <ascending volumes>}}}}
    — each member list FROZEN by observed_at, series from INDEPENDENT price data (see the anti-circularity
    contract above). spy_closes / qqq_closes = the SPY/QQQ benchmark for relative strength.

    Per theme with >= MIN_THEME_MEMBERS usable members: compute breadth_up_frac / volume_confirm_frac / leader_rs,
    cross-theme percentile-rank each, equal-weight into a composite (missing metric → NEUTRAL percentile),
    re-percentile → the 0-100 `theme_heat` (主题池内分位), and emit the 4 price/count confirmation pass flags. A
    theme below MIN_THEME_MEMBERS is `insufficient_themes` and gets NO heat / NO flags (fail-closed self-confirm
    guard).

    Returns {theme_heat: {theme_id: 0-100}, confirm_flags: {theme_id: {item: bool}},
             theme_metrics: {theme_id: {member_count, breadth_up_frac, volume_confirm_frac, leader_rs}},
             insufficient_themes: [theme_id, ...], min_theme_members: int}.
    """
    if not isinstance(themes_by_id, dict):
        themes_by_id = {}
    bench_rs = _benchmark_return(spy_closes, qqq_closes, RS_WINDOW)

    # 1) per-theme usable members + returns/volume-surge (bad/short series drop out)
    theme_members: dict[str, list[dict]] = {}
    for theme_id, rec in themes_by_id.items():
        members_in = rec.get("members") if isinstance(rec, dict) else None
        if not isinstance(members_in, dict):
            theme_members[theme_id] = []
            continue
        rows = []
        for tkr, m in members_in.items():
            if not isinstance(m, dict):
                continue
            px = _clean_series(m.get("closes"), _MIN_HISTORY, positive=True)
            if px is None:
                continue
            vol = _clean_series(m.get("volumes"), VOL_SURGE_LONG)   # volumes: non-negative (zero-volume day valid)
            rows.append({
                "ticker": tkr,
                "ret_3m": _ret(px, RS_WINDOW),
                "ret_1m": _ret(px, BREADTH_WINDOW),
                "vol_surge": _vol_surge(vol) if vol is not None else None,
            })
        theme_members[theme_id] = rows

    # 2) per-theme raw metrics (only themes clearing MIN_THEME_MEMBERS)
    theme_metrics: dict[str, dict] = {}
    insufficient_themes: list[str] = []
    for theme_id, members in theme_members.items():
        if len(members) < MIN_THEME_MEMBERS:
            insufficient_themes.append(theme_id)
        else:
            theme_metrics[theme_id] = _theme_raw_metrics(members, bench_rs)

    # 3) cross-theme percentile per sub-metric → equal-weight composite (missing → NEUTRAL) → re-percentile
    per_metric_pct: dict[str, dict[str, float]] = {}
    for key in _METRIC_KEYS:
        raw = {t: m[key] for t, m in theme_metrics.items() if m[key] is not None}
        if raw:
            per_metric_pct[key] = _percentile_rank(raw)
    composite: dict[str, float] = {}
    for theme_id in theme_metrics:
        vals = [per_metric_pct[k][theme_id] if (k in per_metric_pct and theme_id in per_metric_pct[k])
                else NEUTRAL_PERCENTILE for k in _METRIC_KEYS]
        composite[theme_id] = sum(vals) / len(_METRIC_KEYS)
    theme_heat = _percentile_rank(composite)

    confirm_flags = {t: _confirm_flags(m) for t, m in theme_metrics.items()}
    return {
        "theme_heat": theme_heat,
        "confirm_flags": confirm_flags,
        "theme_metrics": theme_metrics,
        "insufficient_themes": sorted(insufficient_themes),
        "min_theme_members": MIN_THEME_MEMBERS,
    }
