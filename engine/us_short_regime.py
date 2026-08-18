# -*- coding: utf-8 -*-
"""US-short market risk-regime engine (§7) — the worst_of risk axis → position cap.

Design authority: docs/us_short_system_design.md §7; frozen policy in
presets/us_short_regime_governance_20260620.json (consumed here).

Computes `market_risk_regime = worst_of(VIX, market_trend, breadth)` → position cap
(进攻 1.0 / 震荡 0.8 / 防御 0.5 / 极度防御 0.0), with anti-chatter (downgrade fast / upgrade
slow — an upgrade needs 2 consecutive better runs) and unknown-degradation (NEVER default
aggressive on incomplete data; missing critical → ≥ 防御; severe data loss → restricted).

This is the RISK axis ONLY (it caps size). The other axis — `theme_opportunity_state` — is
§4.3-theme-driven and its vocabulary is design-deferred (only 'extreme' appears, §8), so it
is intentionally OUT of this slice; the two-axis split (weak market + strong theme still
probes) is realized in §8 sizing, which consumes this cap plus the theme axis.

VIX is provider-authorization-gated (§3 / SR-PROVIDER-001): an unapproved/unavailable VIX is
just an `unknown` axis here (never fetched), and the regime falls back to trend+breadth. The
worst_of / anti-chatter / unknown / cap POLICY is frozen; the threshold VALUES (VIX 18/25/35,
trend/breadth lines) are §13.1 #3 forward priors, NOT frozen const. Pure/offline; affects
sizing / new-entry permission, NEVER a hard veto, NEVER replaces per-stock analysis. No
A-share crossing.
"""
import datetime as _dt
import json
import math
from pathlib import Path

# Frozen regime identity, severity ASCENDING (进攻 least defensive … 极度防御 most), §7.
REGIMES = ("进攻", "震荡", "防御", "极度防御")
_SEVERITY = {r: i for i, r in enumerate(REGIMES)}
UNKNOWN = "unknown"

# Frozen cap ladder (== presets/us_short_regime_governance_20260620.json market_risk_regime_caps;
# a conformance test triangulates engine == preset so this consumer copy cannot silently drift).
POSITION_CAP = {"进攻": 1.0, "震荡": 0.8, "防御": 0.5, "极度防御": 0.0}

_RISK_AXES = ("vix", "market_trend", "breadth")
CRITICAL_AXES = ("market_trend",)   # §7: the QQQ-required market trend is the critical axis
UPGRADE_CONFIRM_RUNS = 2            # frozen anti-chatter: an upgrade needs this many consecutive better runs

# §13.1 #3 forward priors (design-hinted VIX cut points 18/25/35), NOT frozen const.
VIX_CUTS = ((18.0, "进攻"), (25.0, "震荡"), (35.0, "防御"))  # value < cut → that regime; ≥ last bound → 极度防御

# §13.1 #3 forward priors for the first real market-axis producer.  These are
# deliberately kept here, outside the frozen governance preset.
MARKET_AXIS_MIN_SMA_POINTS = 50
MARKET_TREND_QQQ_DEFENSE_RATIO = 0.90
BREADTH_COVERAGE_MIN = 0.80
BREADTH_CUTS = ((0.60, "进攻"), (0.40, "震荡"), (0.25, "防御"))


MARKET_REGIME_STATE_FILENAME = "market_regime_state.json"
MARKET_REGIME_STATE_SCHEMA_NAME = "us_short_market_regime_state"
MARKET_REGIME_STATE_SCHEMA_VERSION = "1.0.0"
_MARKET_REGIME_STATE_KEYS = frozenset({"schema_name", "schema_version", "as_of", "market_risk_regime", "upgrade_count"})


class MarketRegimeStateError(ValueError):
    """The dated private market-regime state is missing or malformed."""


def _real_date(value, where):
    if not (isinstance(value, str) and len(value) == 8 and value.isascii() and value.isdigit()):
        raise MarketRegimeStateError(f"{where} must be strict YYYYMMDD")
    try:
        _dt.datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise MarketRegimeStateError(f"{where} is not a real date") from exc
    return value


def validate_market_regime_state(state, *, decision_date):
    """Validate the fixed five-key dated state used by the cross-week anti-chatter policy."""
    _real_date(decision_date, "decision_date")
    if not isinstance(state, dict) or set(state) != _MARKET_REGIME_STATE_KEYS:
        raise MarketRegimeStateError("market regime state top-level keys are invalid")
    if state["schema_name"] != MARKET_REGIME_STATE_SCHEMA_NAME \
            or state["schema_version"] != MARKET_REGIME_STATE_SCHEMA_VERSION:
        raise MarketRegimeStateError("market regime state schema is invalid")
    as_of = _real_date(state["as_of"], "market_regime_state.as_of")
    if as_of > decision_date:
        raise MarketRegimeStateError("market_regime_state.as_of cannot be future-dated")
    if state["market_risk_regime"] not in REGIMES:
        raise MarketRegimeStateError("market_regime_state.market_risk_regime is invalid")
    if type(state["upgrade_count"]) is not int or state["upgrade_count"] < 0:
        raise MarketRegimeStateError("market_regime_state.upgrade_count must be a nonnegative exact int")
    return state


def build_market_regime_state(decision_date, analysis):
    """Build the next dated state from the formal analysis result, not from a template or call-site override."""
    _real_date(decision_date, "decision_date")
    regime = analysis.get("regime") if isinstance(analysis, dict) else None
    if not isinstance(regime, dict):
        raise MarketRegimeStateError("formal analysis has no regime result")
    state = {
        "schema_name": MARKET_REGIME_STATE_SCHEMA_NAME,
        "schema_version": MARKET_REGIME_STATE_SCHEMA_VERSION,
        "as_of": decision_date,
        "market_risk_regime": regime.get("market_risk_regime"),
        "upgrade_count": regime.get("upgrade_count"),
    }
    validate_market_regime_state(state, decision_date=decision_date)
    return state


def load_market_regime_state(path, *, decision_date):
    """Load one selected prior dated state; absence is not a first-run signal."""
    path = Path(path)
    if not path.is_file():
        raise MarketRegimeStateError("market regime state is missing")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise MarketRegimeStateError("market regime state is unreadable") from exc
    validate_market_regime_state(state, decision_date=decision_date)
    return state


def classify_vix(value):
    """VIX value → risk regime tier (§13.1 #3 forward thresholds). None / non-finite → 'unknown'
    (never guessed; an unknown VIX degrades the regime via fallback, it does not pass as 进攻)."""
    try:
        v = float(value)
    except (TypeError, ValueError, OverflowError):   # an over-large raw FMP VIX int → unknown, not a bare crash
        return UNKNOWN
    if not math.isfinite(v):
        return UNKNOWN
    for cut, regime in VIX_CUTS:
        if v < cut:
            return regime
    return "极度防御"


def _iso_price_basis(value):
    if isinstance(value, str) and len(value) == 10 and value[4] == "-" and value[7] == "-":
        return value
    if isinstance(value, str) and len(value) == 8 and value.isdigit():
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    return value


def _sma50_snapshot(series, *, price_basis_date, session="RTH", adjustment_mode="split_adjusted"):
    """Return the current 50-close snapshot for one already envelope-validated series."""
    basis = _iso_price_basis(price_basis_date)
    if not isinstance(series, dict) or series.get("as_of") != basis:
        return None
    if series.get("session") != session or series.get("adjustment_mode") != adjustment_mode:
        return None
    points = series.get("points")
    if not isinstance(points, list):
        return None
    valid = []
    for point in points:
        if not isinstance(point, dict):
            continue
        date = point.get("date")
        close = point.get("close")
        if not isinstance(date, str) or date > basis:
            continue
        if isinstance(close, bool) or not isinstance(close, (int, float)):
            continue
        close = float(close)
        if math.isfinite(close) and close > 0.0:
            valid.append((date, close))
    valid.sort(key=lambda item: item[0])
    if len(valid) < MARKET_AXIS_MIN_SMA_POINTS or valid[-1][0] != basis:
        return None
    closes = [close for _, close in valid[-MARKET_AXIS_MIN_SMA_POINTS:]]
    sma50 = sum(closes) / MARKET_AXIS_MIN_SMA_POINTS
    return {"latest_close": closes[-1], "sma50": sma50, "above": closes[-1] >= sma50}


def classify_market_trend(
    series_by_ticker, *, price_basis_date, session="RTH", adjustment_mode="split_adjusted"
):
    """Classify SPY/QQQ against their own SMA50 using the current price basis only."""
    if not isinstance(series_by_ticker, dict):
        return UNKNOWN
    snapshots = {
        ticker: _sma50_snapshot(
            series_by_ticker.get(ticker),
            price_basis_date=price_basis_date,
            session=session,
            adjustment_mode=adjustment_mode,
        )
        for ticker in ("SPY", "QQQ")
    }
    if any(snapshot is None for snapshot in snapshots.values()):
        return UNKNOWN
    spy, qqq = snapshots["SPY"], snapshots["QQQ"]
    if spy["above"] and qqq["above"]:
        return "进攻"
    if spy["above"] or qqq["above"]:
        return "震荡"
    qqq_ratio = qqq["latest_close"] / qqq["sma50"]
    return "防御" if qqq_ratio > MARKET_TREND_QQQ_DEFENSE_RATIO else "极度防御"


def classify_breadth(
    eligible_tickers, series_by_ticker, *, price_basis_date, session="RTH", adjustment_mode="split_adjusted"
):
    """Classify Pass1-eligible breadth after the fixed 80% computability gate."""
    if not isinstance(eligible_tickers, list) or not eligible_tickers or not isinstance(series_by_ticker, dict):
        return UNKNOWN
    snapshots = [
        _sma50_snapshot(
            series_by_ticker.get(ticker),
            price_basis_date=price_basis_date,
            session=session,
            adjustment_mode=adjustment_mode,
        )
        for ticker in eligible_tickers
    ]
    computable = [snapshot for snapshot in snapshots if snapshot is not None]
    if len(computable) / len(eligible_tickers) < BREADTH_COVERAGE_MIN:
        return UNKNOWN
    ratio = sum(snapshot["above"] for snapshot in computable) / len(computable)
    for cut, regime in BREADTH_CUTS:
        if ratio >= cut:
            return regime
    return "极度防御"


def _more_defensive(a, b):
    return a if _SEVERITY[a] >= _SEVERITY[b] else b


def _bump(regime, steps):
    return REGIMES[min(_SEVERITY[regime] + steps, len(REGIMES) - 1)]


def compute_market_risk_regime(axis_regimes, prior_regime=None, prior_upgrade_count=0):
    """axis_regimes = {'vix': r|'unknown'|None, 'market_trend': ..., 'breadth': ...}, r ∈ REGIMES.

    Pipeline (frozen §7 policy): worst_of(available axes) → never-default-aggressive degradation on
    any missing/unknown axis (each missing axis adds a conservative downgrade tier; missing the
    critical trend axis floors at 防御; no axis usable → restricted + 极度防御) → anti-chatter vs the
    prior regime (a downgrade applies immediately; an upgrade needs UPGRADE_CONFIRM_RUNS consecutive
    better runs). Returns the effective regime, its frozen cap, new-entry permission, a restricted
    flag, the raw (pre-anti-chatter) regime, and the new upgrade-confirmation count. Pure."""
    present = {k: v for k, v in (axis_regimes if isinstance(axis_regimes, dict) else {}).items()
               if k in _RISK_AXES and v in _SEVERITY}        # keep only valid regime values
    missing = set(_RISK_AXES) - set(present)

    restricted = False
    if not present:                                          # severe: nothing usable → restricted, most defensive
        raw, restricted = "极度防御", True
    else:
        raw = None
        for v in present.values():
            raw = v if raw is None else _more_defensive(raw, v)   # worst_of
        if missing:                                          # never default aggressive: more missing → more defensive
            raw = _bump(raw, len(missing))                   # (each missing axis incl. an unavailable VIX = one tier)
        if missing.intersection(CRITICAL_AXES):              # missing the critical (QQQ-required) trend → ≥ 防御
            raw = _more_defensive(raw, "防御")

    # anti-chatter: downgrade (or equal) immediate; upgrade requires consecutive confirmation
    if prior_regime not in _SEVERITY:
        effective, upgrade_count = raw, 0
    elif _SEVERITY[raw] >= _SEVERITY[prior_regime]:          # same / more defensive → apply now
        effective, upgrade_count = raw, 0
    else:                                                    # less defensive (upgrade) → confirm first
        upgrade_count = prior_upgrade_count + 1
        if upgrade_count >= UPGRADE_CONFIRM_RUNS:
            effective, upgrade_count = raw, 0
        else:
            effective = prior_regime                         # hold the more-defensive prior until confirmed

    cap = POSITION_CAP[effective]
    return {
        "market_risk_regime": effective,
        "position_cap": cap,
        "new_entry_permitted": cap > 0.0,                    # 极度防御 cap 0 → no new entry (§8 consumes this)
        "restricted": restricted,
        "raw_regime": raw,
        "upgrade_count": upgrade_count,
        "missing_axes": sorted(missing),
    }
