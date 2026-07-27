# -*- coding: utf-8 -*-
"""US-short §4.3/§4.5 source-bound theme selection actions.

This is the selection-side consumer of the lifecycle action table.  It accepts the current decision's
theme identity/source/lifecycle/leader/origin facts before Top15 selection, rather than trying to repair
theme seats later in basket sizing.  It is pure/offline: sources must supply the contract; this module
never invents a lifecycle state, a cross-industry theme, or a watchlist identity.
"""
from __future__ import annotations

import hashlib
import json
import math

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_theme_lifecycle import THEME_STATES, lifecycle_effects


THEME_SELECTION_MODES = (
    "industry_heat_v1_cross_industry_disabled",
    "provisional_cross_industry_enabled",
)
THEME_SOURCES = ("industry_heat_v1", "gics_established", "provisional_discovered")
MEMBERSHIP_ORIGINS = ("automatic_discovery", "manual_watchlist")
OVEREXTENSION_STATES = ("none", "warning", "chasing_extreme")
_CONTRACT_KEYS = {
    "as_of", "mode", "cross_industry_provisional_enabled", "theme_opportunity_state", "per_ticker",
}
_AUDIT_KEYS = {"heat_threshold", "per_ticker"}
_ROW_KEYS = {
    "theme_id", "theme_source", "theme_lifecycle_state", "theme_leader_rs", "membership_origin",
    "market_confirmed", "individual_theme_gate_passed", "overextension_state", "macro_cluster",
}

# §4.5 / §13 #29 forward priors.  These are selection rules, not execution sizing caps.
AUTO_DISCOVERY_MIN = 2
MANUAL_WATCHLIST_MAX = 2
SAME_THEME_SEAT_MAX = 3
_ACTIVE_STATES = frozenset({"provisional_active", "confirmed_active"})


class ThemeSelectionError(ValueError):
    """The decision-date theme selection contract is malformed or cannot safely fill a theme seat."""


def _finite_number(value, *, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ThemeSelectionError(f"{where} 须为有限数")
    try:
        out = float(value)
    except OverflowError as exc:
        raise ThemeSelectionError(f"{where} 须为有限数") from exc
    if not math.isfinite(out):
        raise ThemeSelectionError(f"{where} 须为有限数")
    return out


def _canonical_theme_id(value, *, where):
    if not isinstance(value, str) or not value.strip():
        raise ThemeSelectionError(f"{where} 须为非空 str")
    return value.strip().casefold()


def validate_theme_selection_contract(contract, *, expected_tickers, decision_date, theme_opportunity_state):
    """Validate and canonicalize the source-bound §4.3/§4.5 selection contract.

    The enclosing selection-input provenance binds this injected contract to its source artifact; this local
    boundary additionally binds its `as_of` and opportunity state to the decision currently being selected.
    Every candidate must have exactly one source-bound theme identity.  Cross-industry provisional themes are
    structurally impossible while the explicit industry-v1 mode is active.
    """
    if not (isinstance(contract, dict) and _CONTRACT_KEYS <= set(contract)
            and set(contract) - _CONTRACT_KEYS <= {"hot_excluded_audit"}):
        raise ThemeSelectionError("theme_selection_contract 顶层键漂移")
    if contract["as_of"] != decision_date:
        raise ThemeSelectionError("theme_selection_contract.as_of 必须等于本次 decision_date")
    mode = contract["mode"]
    if mode not in THEME_SELECTION_MODES:
        raise ThemeSelectionError("theme_selection_contract.mode 非法")
    enabled = contract["cross_industry_provisional_enabled"]
    if type(enabled) is not bool or enabled != (mode == "provisional_cross_industry_enabled"):
        raise ThemeSelectionError("theme_selection_contract 跨行业开关与 mode 不一致")
    if contract["theme_opportunity_state"] != theme_opportunity_state:
        raise ThemeSelectionError("theme_selection_contract theme_opportunity_state 与 selection 输入不一致")
    if not isinstance(contract["per_ticker"], dict):
        raise ThemeSelectionError("theme_selection_contract.per_ticker 须为 dict")

    expected, out, theme_identity = set(), {}, {}
    for raw_ticker in expected_tickers:
        ticker = canonical_us_ticker(raw_ticker)
        if ticker is None or ticker in expected:
            raise ThemeSelectionError("expected_tickers 含非法或重复 canonical ticker")
        expected.add(ticker)
    for raw_ticker, row in contract["per_ticker"].items():
        ticker = canonical_us_ticker(raw_ticker)
        if ticker is None or ticker in out:
            raise ThemeSelectionError("theme_selection_contract.per_ticker 含非法或重复 canonical ticker")
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            raise ThemeSelectionError(f"theme_selection_contract.per_ticker[{raw_ticker!r}] 字段漂移")
        source = row["theme_source"]
        lifecycle = row["theme_lifecycle_state"]
        origin = row["membership_origin"]
        overextension = row["overextension_state"]
        if source not in THEME_SOURCES or lifecycle not in THEME_STATES:
            raise ThemeSelectionError(f"{ticker} theme_source/lifecycle 非法")
        if origin not in MEMBERSHIP_ORIGINS or overextension not in OVEREXTENSION_STATES:
            raise ThemeSelectionError(f"{ticker} membership_origin/overextension_state 非法")
        if type(row["market_confirmed"]) is not bool or type(row["individual_theme_gate_passed"]) is not bool:
            raise ThemeSelectionError(f"{ticker} market confirmation / individual gate 须为 bool")
        if mode == "industry_heat_v1_cross_industry_disabled" and source != "industry_heat_v1":
            raise ThemeSelectionError("行业热度 v1 模式不得注入 provisional 跨行业主题")
        canonical_theme_id = _canonical_theme_id(row["theme_id"], where=f"{ticker}.theme_id")
        macro_cluster = _canonical_theme_id(row["macro_cluster"], where=f"{ticker}.macro_cluster")
        theme_level_identity = (source, lifecycle, row["market_confirmed"], macro_cluster)
        prior_identity = theme_identity.get(canonical_theme_id)
        if prior_identity is not None and prior_identity != theme_level_identity:
            raise ThemeSelectionError(
                "same theme_id must carry one source/lifecycle/market-confirmation identity")
        theme_identity[canonical_theme_id] = theme_level_identity
        out[ticker] = {
            "theme_id": canonical_theme_id,
            "theme_source": source,
            "theme_lifecycle_state": lifecycle,
            "theme_leader_rs": _finite_number(row["theme_leader_rs"], where=f"{ticker}.theme_leader_rs"),
            "membership_origin": origin,
            "market_confirmed": row["market_confirmed"],
            "individual_theme_gate_passed": row["individual_theme_gate_passed"],
            "overextension_state": overextension,
            "macro_cluster": macro_cluster,
        }
    if set(out) != expected:
        raise ThemeSelectionError("theme_selection_contract.per_ticker 须恰覆盖 Pass2-clean candidates")
    audit = None
    if "hot_excluded_audit" in contract:
        raw_audit = contract["hot_excluded_audit"]
        if not isinstance(raw_audit, dict) or set(raw_audit) != _AUDIT_KEYS:
            raise ThemeSelectionError("hot_excluded_audit 顶层键漂移")
        threshold = _finite_number(raw_audit["heat_threshold"], where="hot_excluded_audit.heat_threshold")
        if threshold < 0.0 or not isinstance(raw_audit["per_ticker"], dict):
            raise ThemeSelectionError("hot_excluded_audit threshold/per_ticker 非法")
        heat_by_ticker = {}
        for raw_ticker, value in raw_audit["per_ticker"].items():
            ticker = canonical_us_ticker(raw_ticker)
            if ticker is None or ticker in heat_by_ticker:
                raise ThemeSelectionError("hot_excluded_audit.per_ticker 含非法/重复 ticker")
            score = _finite_number(value, where=f"hot_excluded_audit.per_ticker[{ticker}]")
            if score < 0.0:
                raise ThemeSelectionError("hot_excluded_audit heat score 须非负")
            heat_by_ticker[ticker] = score
        audit = {"heat_threshold": threshold, "per_ticker": heat_by_ticker}
    digest = hashlib.sha256(
        json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {"mode": mode, "per_ticker": out, "contract_digest": digest,
            "hot_excluded_audit": audit}


def theme_seat_plan(*, metadata_by_ticker, scores_by_ticker, theme_seat_budget):
    """Return ordered automatic and remaining candidates plus lifecycle-adjusted per-theme seat caps.

    `cooling` gets floor(theme-seat-budget × 0.5), `decayed`/`retired` get zero, and every active theme is
    limited to three seats for the §4.5 crowding downgrade.  The caller applies caps only when a true theme
    seat is added, so core/theme overlap rolls the seat forward instead of consuming capacity.
    """
    if type(theme_seat_budget) is not int or isinstance(theme_seat_budget, bool) or theme_seat_budget < 0:
        raise ThemeSelectionError("theme_seat_budget 须为非负 int")
    if set(metadata_by_ticker) != set(scores_by_ticker):
        raise ThemeSelectionError("theme metadata / score identity 不一致")

    eligible, limits = [], {}
    for ticker, meta in metadata_by_ticker.items():
        score = scores_by_ticker[ticker]
        theme_score = _finite_number(score.get("theme_momentum_score"), where=f"{ticker}.theme_momentum_score")
        _finite_number(score.get("core_score"), where=f"{ticker}.core_score")
        effects = lifecycle_effects(meta["theme_lifecycle_state"])
        limit = min(SAME_THEME_SEAT_MAX, int(math.floor(theme_seat_budget * effects["theme_seats_multiplier"])))
        limits[meta["theme_id"]] = min(limits.get(meta["theme_id"], limit), limit)
        # The stricter provisional bar (market confirmation + individual gate) is keyed on EITHER a
        # provisional_discovered source OR a provisional_active lifecycle — a source can label a theme
        # `industry_heat_v1` yet still assert a `provisional_active` lifecycle, and that unconfirmed
        # provisional-active name must not take a theme seat on the source label alone. Using OR (not replacing
        # the source key) keeps the existing bar for a discovered theme in any non-active lifecycle too.
        needs_provisional_gate = (
            meta["theme_source"] == "provisional_discovered"
            or meta["theme_lifecycle_state"] == "provisional_active"
        )
        provisional_ok = (
            not needs_provisional_gate
            or (meta["market_confirmed"] and meta["individual_theme_gate_passed"]
                and meta["theme_lifecycle_state"] in _ACTIVE_STATES)
        )
        manual_ok = meta["membership_origin"] != "manual_watchlist" or meta["market_confirmed"]
        if effects["in_theme_table"] and limit > 0 and theme_score > 0.0 and provisional_ok and manual_ok:
            eligible.append(ticker)

    order_key = lambda ticker: (
        -float(scores_by_ticker[ticker]["theme_momentum_score"]),
        -float(scores_by_ticker[ticker]["core_score"]),
        -metadata_by_ticker[ticker]["theme_leader_rs"],
        ticker,
    )
    ranked = sorted(eligible, key=order_key)
    automatic = [ticker for ticker in ranked if metadata_by_ticker[ticker]["membership_origin"] == "automatic_discovery"]
    return {"automatic": automatic, "ranked": ranked, "theme_limits": limits}


def strong_theme_leader_upgrades(*, selected_tickers, metadata_by_ticker, selection_ranks, theme_opportunity_state,
                                 maximum):
    """Apply the §4.5 Top6-15 leader-upgrade action before downstream analysis consumes selection output."""
    if type(maximum) is not int or isinstance(maximum, bool) or maximum < 0:
        raise ThemeSelectionError("leader upgrade maximum 须为非负 int")
    if theme_opportunity_state not in ("strong", "extreme") or maximum == 0:
        return []
    candidates = []
    for ticker in selected_tickers:
        meta = metadata_by_ticker[ticker]
        if selection_ranks[ticker] <= 5 or meta["overextension_state"] == "chasing_extreme":
            continue
        if meta["theme_lifecycle_state"] not in _ACTIVE_STATES:
            continue
        if (meta["theme_source"] == "provisional_discovered"
                or meta["theme_lifecycle_state"] == "provisional_active") and not (
            meta["market_confirmed"] and meta["individual_theme_gate_passed"]
        ):
            continue
        candidates.append(ticker)
    return sorted(candidates, key=lambda ticker: (-metadata_by_ticker[ticker]["theme_leader_rs"], ticker))[:maximum]
