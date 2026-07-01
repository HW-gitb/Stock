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

PIT + clock (Cut 3b, the input-rework half; mirrors engine/us_short_industry_heat.py Cut 3a and
engine/us_short_momentum.py Cut 2): each member / benchmark is an already-fetched PIT-bearing dated series
({as_of, session, adjustment_mode, points:[{date, close, volume?}]}). Each series is PIT-cut to its `as_of` (a
point dated AFTER as_of is BLOCKED — no look-ahead) over a strictly-ascending unique date axis, and ALL valid
series (members + benchmarks) must share ONE (as_of, session, adjustment_mode) decision clock — a non-uniform
clock is fail-closed (`ProvisionalThemeHeatError`), so heat is never computed from mixed-as-of / cross-adjustment
data. Exact within-window member↔benchmark daily-date alignment is the GATED data-layer assembly's contract (R5
rationale: alignment is only meaningfully enforced where series are assembled with provenance); this engine
enforces the PIT cut + the uniform decision clock. The sub-metric math below is unchanged from the prior
bare-array version. The LIVE discovery / member-list / price assembly stays gated (SR-PROVIDER-001).

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
forward priors. COVERAGE FAIL-CLOSED: a theme below MIN_THEME_MEMBERS usable members is `insufficient_themes`
(no heat, no flags — a 2-name "theme" cannot self-confirm). All numeric inputs are strictly validated (reject
bool / NaN / Inf / numeric string; CLOSE/benchmark prices must be strictly positive, volumes non-negative).
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any

from engine.us_short_eligibility_gate import canonical_us_ticker  # the repo's single US ticker identity policy

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


def _clean_series(series: Any) -> list[float] | None:
    """Ascending daily CLOSE / benchmark price series → list[float]; None if not a list / shorter than
    _MIN_HISTORY / has a non-finite OR NON-POSITIVE point. A price is strictly positive — a 0/negative price is
    invalid data, never heat/relative-strength evidence (same class as
    R-USSHORT-INDUSTRY-HEAT-NONPOSITIVE-CLOSE-FAILOPEN). A bad point fails the WHOLE series (don't silently drop).
    Only the KEPT (<=as_of) closes reach here (future points are PIT-cut upstream by `_parse_dated_series`), so a
    future malformed close cannot reject a valid current series. Mirrors engine/us_short_industry_heat.py."""
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


def _vol_surge(volumes: list) -> float | None:
    """Recent short-window avg volume / longer baseline avg volume over the VOL_SURGE_LONG tail; None if the
    tail is shorter than VOL_SURGE_LONG, has ANY missing (None) point, or the baseline is non-positive. Only the
    tail it averages needs coverage — an earlier gap must not over-omit a computable surge (mirrors
    engine/us_short_momentum.py). `volumes` is the [float|None,...] list from `_parse_dated_series`, where a
    negative / non-finite / missing volume is already mapped to None (a valid zero is kept)."""
    if len(volumes) < VOL_SURGE_LONG:
        return None
    window = volumes[-VOL_SURGE_LONG:]
    if any(v is None for v in window):
        return None
    long_avg = sum(window) / VOL_SURGE_LONG
    if long_avg <= 0:
        return None
    short_avg = sum(window[-VOL_SURGE_SHORT:]) / VOL_SURGE_SHORT
    return short_avg / long_avg


class ProvisionalThemeHeatError(ValueError):
    """The injected series carry a non-uniform decision clock (mixed as_of / session / adjustment_mode) — heat
    is never computed from inconsistent-clock data (fail-closed). Mirrors industry_heat.IndustryHeatError."""


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


def _nonblank_no_drift(s: Any) -> bool:
    """A meaningful nonblank canonical metadata string: a str that is non-empty AND carries no whitespace-only
    value and no leading/trailing-whitespace drift (`s == s.strip()`). A `'   '` clock or a `' RTH '` drift is
    NOT a real decision clock (R-USSHORT-PROVISIONAL-THEME-IDENTITY-AND-CLOCK-VALIDATION-GAP finding B/C)."""
    return isinstance(s, str) and s.strip() != "" and s == s.strip()


def _parse_dated_series(series: Any) -> dict | None:
    """Validate + PIT-cut a date/as_of/session/adjustment-bearing series ->
    {as_of: date, session: str, adjustment_mode: str, closes: [float,...], volumes: [float|None,...]} or None
    (fail-closed).

    PIT: a point dated AFTER `as_of` is BLOCKED (excluded — its VALUE is not even validated, so a future
    non-finite close/volume can never over-reject an otherwise-valid ≤as_of series; no look-ahead). The RAW
    point axis must be strictly ascending + unique by date BEFORE the cut (corrupt/duplicated -> None). The KEPT
    (≤as_of) closes go through `_clean_series` (finite + strictly POSITIVE + >= _MIN_HISTORY after the cut → an
    IPO/short/non-positive name -> None). Each kept volume is finite-and-non-negative or None (a NEGATIVE /
    non-finite / missing volume -> None so `vol_surge` is UNAVAILABLE for that window, never a corrupt average; a
    valid zero is kept). Own copy mirroring engine/us_short_momentum.py's parser + this engine's positive-close
    `_clean_series` (the established per-engine-helper convention)."""
    if not (isinstance(series, dict) and set(series) == _DATED_SERIES_KEYS):
        return None
    as_of = _valid_date(series["as_of"])
    if as_of is None:
        return None
    session, adj = series["session"], series["adjustment_mode"]
    if not (_nonblank_no_drift(session) and _nonblank_no_drift(adj)):   # reject whitespace-only / drift clock
        return None
    pts = series["points"]
    if not isinstance(pts, list) or not pts:
        return None
    kept_closes: list = []
    kept_vols: list = []
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
        if d <= as_of:                        # PIT cut: future points BLOCKED (value not even validated)
            kept_closes.append(p["close"])    # raw; _clean_series validates finiteness + positivity of USED data
            fv = _finite(p["volume"]) if p.get("volume") is not None else None
            kept_vols.append(fv if (fv is None or fv >= 0.0) else None)   # negative/non-finite/missing -> None
    closes = _clean_series(kept_closes)       # finite + strictly positive + MIN history floor (post-cut)
    if closes is None:
        return None
    return {"as_of": as_of, "session": session, "adjustment_mode": adj,
            "closes": closes, "volumes": kept_vols}


def _benchmark_return(spy_closes: Any, qqq_closes: Any, lookback: int) -> float | None:
    """Mean of the available SPY/QQQ returns over `lookback` (relative-strength baseline); None if neither
    benchmark has enough clean history (→ the relative-strength metric degrades to neutral, not a crash). Takes
    the PIT-cut benchmark closes (already parsed); `_clean_series` re-validates defensively."""
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


def _canonical_theme_ids(themes_by_id: dict) -> dict:
    """Normalize + fail-closed-validate the theme IDs (R-USSHORT-PROVISIONAL-THEME-IDENTITY-AND-CLOCK-VALIDATION
    -GAP finding B): each `theme_id` MUST be a nonblank string; the documented normalization is surrounding-
    whitespace strip. A non-string / blank ID, or two IDs normalizing to the SAME value, is fail-closed (raise
    ProvisionalThemeHeatError) — never a raw mixed-type `sorted()` TypeError or an ambiguous serialized key.
    Returns {normalized_id: rec}."""
    out: dict[str, Any] = {}
    for tid, rec in themes_by_id.items():
        if not (isinstance(tid, str) and tid.strip()):
            raise ProvisionalThemeHeatError(f"theme_id 须为非空字符串（fail-closed，非 {tid!r}）")
        norm = tid.strip()
        if norm in out:
            raise ProvisionalThemeHeatError(f"theme_id 规范化后重复 {norm!r}（歧义，fail-closed；不静默合并）")
        out[norm] = rec
    return out


def _canonical_members(members_in: dict, *, theme_id: str) -> dict:
    """Re-key ONE theme's {ticker: series} by the repo's canonical US ticker BEFORE any member is counted
    (R-USSHORT-PROVISIONAL-THEME-IDENTITY-AND-CLOCK-VALIDATION-GAP finding A). An invalid / non-string /
    cross-market (A-share) key `canonical_us_ticker` rejects is EXCLUDED (it must never contribute to
    member_count / breadth / volume / leader_rs / heat / flags; a shrunk member list is fail-closed). Two keys
    canonicalizing to the SAME US ticker are ambiguous aliases -> raise ProvisionalThemeHeatError (fail closed;
    NEVER silently deduplicate or count the aliases). Only canonical UNIQUE US identities remain."""
    out: dict[str, Any] = {}
    for k, v in members_in.items():
        ck = canonical_us_ticker(k)
        if ck is None:
            continue                          # invalid / non-string / A-share -> reject (excluded, not counted)
        if ck in out:
            raise ProvisionalThemeHeatError(
                f"theme {theme_id!r} 成员规范化后重复 ticker {ck!r}（别名歧义，fail-closed；不静默去重/不双计）")
        out[ck] = v
    return out


def provisional_theme_heat_block(themes_by_id: Any, *, spy_series: Any = None, qqq_series: Any = None) -> dict[str, Any]:
    """Map provisional themes → cross-theme PERCENTILE `theme_heat` + price-derived confirmation flags (§4.3).

    themes_by_id = {theme_id: {"members": {ticker: <PIT-bearing dated series>}}} — each member list FROZEN by
    observed_at, each series = {as_of, session, adjustment_mode, points:[{date, close, volume?}]} from INDEPENDENT
    price data (see the anti-circularity contract above). spy_series / qqq_series = the SPY/QQQ benchmark dated
    series.

    IDENTITY + CLOCK VALIDATION (fail-closed, R-USSHORT-PROVISIONAL-THEME-IDENTITY-AND-CLOCK-VALIDATION-GAP):
    every `theme_id` must be a nonblank string (surrounding-whitespace-normalized; a normalization collision
    raises); every member key is canonicalized by the repo's `canonical_us_ticker` BEFORE it is counted — an
    invalid / non-string / cross-market (A-share) key is EXCLUDED, and two keys aliasing to the same US ticker
    raise (never silent dedup / count-both), so ONLY canonical unique US identities feed member_count / breadth /
    volume / leader_rs / heat / flags; `session` / `adjustment_mode` must be nonblank with no whitespace drift.

    Each series is PIT-cut to its as_of (future points BLOCKED) and ALL valid series (members + benchmarks) must
    share ONE (as_of, session, adjustment_mode) decision clock — a non-uniform clock is fail-closed
    (`ProvisionalThemeHeatError`). Exact within-window member↔benchmark daily-date alignment is the gated
    assembly's contract (R5 rationale); the sub-metric math is unchanged from the prior bare-array version.

    Per theme with >= MIN_THEME_MEMBERS usable members: compute breadth_up_frac / volume_confirm_frac / leader_rs,
    cross-theme percentile-rank each, equal-weight into a composite (missing metric → NEUTRAL percentile),
    re-percentile → the 0-100 `theme_heat` (主题池内分位), and emit the 4 price/count confirmation pass flags. A
    theme below MIN_THEME_MEMBERS is `insufficient_themes` and gets NO heat / NO flags (fail-closed self-confirm
    guard).

    Returns {theme_heat: {theme_id: 0-100}, confirm_flags: {theme_id: {item: bool}},
             theme_metrics: {theme_id: {member_count, breadth_up_frac, volume_confirm_frac, leader_rs}},
             insufficient_themes: [theme_id, ...], min_theme_members: int}. Raises ProvisionalThemeHeatError on a
    non-uniform decision clock, a blank/non-string/collision theme_id, or a member alias (post-canonical) collision.
    """
    if not isinstance(themes_by_id, dict):
        themes_by_id = {}
    themes_by_id = _canonical_theme_ids(themes_by_id)   # nonblank-string IDs, strip-normalized, collision fail-closed
    clocks: set = set()
    spy_p = _parse_dated_series(spy_series)
    qqq_p = _parse_dated_series(qqq_series)
    for bp in (spy_p, qqq_p):
        if bp is not None:
            clocks.add((bp["as_of"], bp["session"], bp["adjustment_mode"]))
    bench_rs = _benchmark_return(spy_p["closes"] if spy_p else None,
                                 qqq_p["closes"] if qqq_p else None, RS_WINDOW)

    # 1) per-theme usable members + returns/volume-surge (bad/short/non-positive/future series drop out)
    theme_members: dict[str, list[dict]] = {}
    for theme_id, rec in themes_by_id.items():
        members_in = rec.get("members") if isinstance(rec, dict) else None
        if not isinstance(members_in, dict):
            theme_members[theme_id] = []
            continue
        # canonical US identity BEFORE counting: invalid/cross-market keys excluded, alias collisions fail-closed
        canon_members = _canonical_members(members_in, theme_id=theme_id)
        rows = []
        for tkr, m_series in canon_members.items():
            parsed = _parse_dated_series(m_series)
            if parsed is None:
                continue
            clocks.add((parsed["as_of"], parsed["session"], parsed["adjustment_mode"]))
            px = parsed["closes"]
            rows.append({
                "ticker": tkr,
                "ret_3m": _ret(px, RS_WINDOW),
                "ret_1m": _ret(px, BREADTH_WINDOW),
                "vol_surge": _vol_surge(parsed["volumes"]),
            })
        theme_members[theme_id] = rows

    # uniform decision clock (Cut 3b): every valid member + benchmark series must share one as_of/session/adjustment
    if len(clocks) > 1:
        raise ProvisionalThemeHeatError(
            "provisional_theme_heat 输入序列时钟不统一（须同一 as_of/session/adjustment_mode；fail-closed）: "
            + str(sorted(str(c) for c in clocks)))

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
