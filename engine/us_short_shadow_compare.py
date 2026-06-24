# -*- coding: utf-8 -*-
"""US-short §12.2 赛道权重比较轨 — batch-3 (#13/#24): shadow scoring_profile selection comparison (projection).

Design authority: docs/us_short_system_design.md §12.2 (赛道权重比较轨 + 错过成绩单, shadow-only) / §4.2
(scoring_profile 命名权重档). Borrows the A-share comparison-track ENGINEERING scaffold
(schemas/a_short_theme_overlay_comparison: track=comparison_non_production + a ship-gate-isolation boundary
block + baseline-vs-overlay rank diff), NOT A-share market rules.

Re-scores the SAME PIT-frozen eligible candidate pool under EVERY frozen scoring_profile
(presets/us_short_scoring_profile_governance_20260620.json — single source; ``balanced`` 40/35/25 = the v1
primary / sole live ``model_paper`` track, ``theme_plus`` / ``theme_aggressive`` / ``theme_off`` = shadow
comparison only) and takes a FIXED ``top_n`` deterministic selection per profile, so the comparison answers the
§12.2 question "does reweighting the 35% theme block change which eligible names get selected?" (是否常错过强赛道 /
加重赛道权重是否真更好). ``theme_off`` (theme weight = 0) is the attribution baseline: the ``balanced`` − ``theme_off``
selection diff (``vs_balanced['theme_off']``) IS the theme weight's marginal selection contribution (#24).

§12.2 honesty invariants enforced structurally:
  * 禁止挑样本: FIXED ``top_n`` + DETERMINISTIC ranking (core_score desc, ticker asc tie-break) — the full TopN
    of every profile is emitted in order, never a hand-picked subset of after-the-fact winners;
  * ship-gate 隔离 (#13): the output carries a FROZEN boundary block (production / is_buy_advice /
    shadow_counts_ship_gate / changes_primary_selection all False) — a shadow profile can NEVER count toward
    ship-gate or change the live (balanced) selection;
  * ``balanced`` = sole primary (#13): every profile's weights / role / live_eligible / shadow_only are pinned to
    a reviewed const (``_FROZEN_PROFILES``) and runtime-enforced on BOTH the loaded preset (``_check_governance``)
    AND the emitted artifact (``validate_shadow_comparison``) — a post-review drift (a reweighted ``theme_off``, a
    shadow turned live, a second primary, a tampered output weight/role/flag) fails closed; ``theme_off`` stays
    theme-weight 0 (the #24 attribution baseline). ``_check_governance`` ALSO verifies the SCORER's own
    (``core_score``'s separately-loaded) effective weights equal the const before selecting, so a selection can
    never be scored under non-frozen weights while the artifact declares the frozen ones.

This is a PURE in-memory projection: the per-profile selections carry tickers (private-tier, §11.6) and MUST be
routed through the private persister + a de-identified tracked summary in a LATER slice — this cut does NOT
persist, does NOT compute paper NAV / the two-way full-caliber scorecard (§12.2 双向全口径), does NOT run the
anti-self-deception upgrade gate (§12.2 升级闸), and does NOT apply the §12.1 corporate-action evaluability
carryover (all since landed downstream: engine.us_short_paper_scorecard / _scorecard_comparison /
_paper_nav_drawdown / _paper_eval_gate, engine.us_short_upgrade_gate). Pure / offline: arithmetic on dicts via engine.us_short_core_score; no
provider / live / DataHub / network; no A-share crossing. Malformed input / a drifted governance preset fails
closed (``ShadowCompareError``).
"""
from __future__ import annotations

import json
from pathlib import Path

from engine.us_short_core_score import core_score, profile_weights, PRIMARY_PROFILE, PROFILE_NAMES

_GOV_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_scoring_profile_governance_20260620.json"
_GOV = json.loads(_GOV_PATH.read_text(encoding="utf-8"))
_PROFILES = _GOV["profiles"]
_MIN_COMPARISON_WEEKS = _GOV["min_comparison_weeks"]

# The REVIEWED, design-locked §4.2/§12.2 profile contract (v1 priors). The preset is the single source the engine
# LOADS, but a preset edit or an output tamper must be runtime-enforced against THIS const-pin — else a post-review
# weight / role / flag drift (a reweighted theme_off, a shadow turned live, a second primary) could validate as
# contract-clean (the same self-authoring-bypass class the lifecycle threshold authority is pinned against).
# Forward calibration (§13 #1/#28) is a REVIEWED change that updates this const AND the preset together; theme_off
# MUST stay theme-weight 0 (the #24 attribution baseline) and non-live shadow-only.
_FROZEN_PRIMARY = "balanced"
_FROZEN_PROFILES = {
    "balanced":         {"weights": {"momentum": 0.40,   "theme": 0.35, "catalyst": 0.25},   "role": "primary",                                  "live_eligible": True,  "shadow_only": False},
    "theme_plus":       {"weights": {"momentum": 0.30,   "theme": 0.50, "catalyst": 0.20},   "role": "shadow_comparison",                        "live_eligible": False, "shadow_only": True},
    "theme_aggressive": {"weights": {"momentum": 0.25,   "theme": 0.55, "catalyst": 0.20},   "role": "shadow_comparison",                        "live_eligible": False, "shadow_only": True},
    "theme_off":        {"weights": {"momentum": 0.6154, "theme": 0.0,  "catalyst": 0.3846}, "role": "attribution_baseline_and_rollback_anchor", "live_eligible": False, "shadow_only": True},
}

_TRACK = "comparison_non_production"
# the frozen ship-gate-isolation boundary EVERY comparison artifact carries (mirrors the A-share
# comparison-track boundary block); a shadow profile can never count ship-gate / change the live selection
_BOUNDARY = {
    "production": False,
    "is_buy_advice": False,
    "shadow_counts_ship_gate": False,
    "changes_primary_selection": False,
}
_SELECTION_KEYS = {"ticker", "rank", "core_score"}
_VS_KEYS = {"balanced_only", "shadow_extra", "overlap_count"}


class ShadowCompareError(ValueError):
    """Raised when the candidate pool, top_n, or the loaded scoring_profile governance violates the §12.2 contract."""


def _pos_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x > 0


def _assert_frozen_profile(name, prof, where) -> None:
    """Assert ONE profile's weights / role / live_eligible / shadow_only EXACTLY match the reviewed const-pin
    (``_FROZEN_PROFILES``) — a tampered weight / role / flag in the loaded preset (``where='governance'``) or in
    the emitted artifact (``where='output'``) fails closed. Extra keys (preset ``value_source`` / output
    ``selection``) are ignored; the bool flags use identity so a truthy non-bool (``1`` / ``"yes"``) is refused."""
    frozen = _FROZEN_PROFILES[name]
    if not isinstance(prof, dict):
        raise ShadowCompareError("%s profile %r must be a dict, got %r" % (where, name, type(prof).__name__))
    if prof.get("weights") != frozen["weights"]:
        raise ShadowCompareError("%s profile %r weights must be the frozen %r, got %r" % (where, name, frozen["weights"], prof.get("weights")))
    if prof.get("role") != frozen["role"]:
        raise ShadowCompareError("%s profile %r role must be %r, got %r" % (where, name, frozen["role"], prof.get("role")))
    if prof.get("live_eligible") is not frozen["live_eligible"]:
        raise ShadowCompareError("%s profile %r live_eligible must be %r, got %r" % (where, name, frozen["live_eligible"], prof.get("live_eligible")))
    if prof.get("shadow_only") is not frozen["shadow_only"]:
        raise ShadowCompareError("%s profile %r shadow_only must be %r, got %r" % (where, name, frozen["shadow_only"], prof.get("shadow_only")))


def _check_governance() -> None:
    """Fail closed unless the LOADED scoring_profile preset matches the reviewed §4.2/§12.2 const-pin
    (``_FROZEN_PROFILES``) EXACTLY: the preset (and core_score's PROFILE_NAMES) declare EXACTLY the frozen profile
    set, PRIMARY_PROFILE == the frozen primary (``balanced``), and every profile's weights / role / live_eligible /
    shadow_only equal the const-pin — so a post-review preset edit (a reweighted theme_off, a shadow turned live, a
    second primary) cannot validate. ``balanced`` stays the sole primary/live track; ``theme_off`` stays the
    theme-weight-0 shadow baseline (#24)."""
    # self-check the const-pin itself (a careless edit to _FROZEN_PROFILES must not silently create a second
    # primary or lose the theme_off=0 baseline)
    if ([n for n, p in _FROZEN_PROFILES.items()
         if p["role"] == "primary" and p["live_eligible"] is True and p["shadow_only"] is False] != [_FROZEN_PRIMARY]
            or _FROZEN_PROFILES["theme_off"]["weights"]["theme"] != 0.0):
        raise ShadowCompareError("_FROZEN_PROFILES invariant broken (sole primary %r + theme_off theme==0 baseline)" % (_FROZEN_PRIMARY,))
    if set(_PROFILES) != set(_FROZEN_PROFILES) or set(PROFILE_NAMES) != set(_FROZEN_PROFILES):
        raise ShadowCompareError(
            "scoring_profile governance must declare EXACTLY %s, got preset=%s core_score_names=%s"
            % (sorted(_FROZEN_PROFILES), sorted(map(str, _PROFILES)), sorted(map(str, PROFILE_NAMES))))
    if PRIMARY_PROFILE != _FROZEN_PRIMARY:
        raise ShadowCompareError("PRIMARY_PROFILE must be the frozen primary %r, got %r" % (_FROZEN_PRIMARY, PRIMARY_PROFILE))
    for name in _FROZEN_PROFILES:
        _assert_frozen_profile(name, _PROFILES[name], "governance")
        # The SCORER's OWN effective weights (core_score's separately-loaded governance, which _select scores
        # through) must ALSO equal the frozen const — else a selection could be scored under non-frozen weights
        # while the artifact declares the frozen ones (a scorer-DEPENDENCY drift, distinct from this module's
        # _PROFILES; verified here BEFORE any _select call so a drifted scorer never produces a frozen-looking
        # selection).
        scorer_weights = profile_weights(name)
        if scorer_weights != _FROZEN_PROFILES[name]["weights"]:
            raise ShadowCompareError(
                "core_score profile %r weights must be the frozen %r, got %r (scorer-governance drift)"
                % (name, _FROZEN_PROFILES[name]["weights"], scorer_weights))


def _validate_pool(scored_pool):
    """Structural fail-closed check of the PIT-frozen eligible pool → list of (ticker, blocks, risk_downgrade_points).
    Each row must be a dict with a non-blank string ``ticker`` (UNIQUE across the pool — a duplicate identity makes
    the selection set-diffs ill-defined) and a dict ``blocks``; ``risk_downgrade_points`` is optional (default 0.0,
    its malformed-value contract is core_score's). Raises ``ShadowCompareError``."""
    if not isinstance(scored_pool, list):
        raise ShadowCompareError("scored_pool must be a list, got %r" % (type(scored_pool).__name__,))
    seen, out = set(), []
    for i, row in enumerate(scored_pool):
        if not isinstance(row, dict):
            raise ShadowCompareError("scored_pool[%d] must be a dict, got %r" % (i, type(row).__name__))
        ticker = row.get("ticker")
        if not isinstance(ticker, str) or not ticker.strip():
            raise ShadowCompareError("scored_pool[%d].ticker must be a non-blank string, got %r" % (i, ticker))
        ticker = ticker.strip()
        if ticker in seen:
            raise ShadowCompareError("duplicate ticker %r in scored_pool (selection set-diffs need unique identities)" % (ticker,))
        seen.add(ticker)
        blocks = row.get("blocks")
        if not isinstance(blocks, dict):
            raise ShadowCompareError("scored_pool[%d=%s].blocks must be a dict, got %r" % (i, ticker, type(blocks).__name__))
        out.append((ticker, blocks, row.get("risk_downgrade_points", 0.0)))
    return out


def _select(pool, profile, top_n):
    """Deterministic FIXED top_n selection for one profile: score every candidate via core_score under ``profile``,
    rank by (core_score DESC, ticker ASC) — a reproducible, cherry-pick-proof order — and take the first top_n."""
    scored = [(ticker, core_score(blocks, profile=profile, risk_downgrade_points=rd)["core_score"])
              for ticker, blocks, rd in pool]
    scored.sort(key=lambda t: (-t[1], t[0]))
    return [{"ticker": t, "rank": r + 1, "core_score": cs} for r, (t, cs) in enumerate(scored[:top_n])]


def build_shadow_comparison(scored_pool, *, top_n):
    """§12.2 shadow scoring_profile selection comparison over a PIT-frozen eligible pool.

    ``scored_pool`` = list of ``{"ticker": str, "blocks": {momentum/theme/catalyst: 0-100},
    "risk_downgrade_points": float (optional)}``; ``top_n`` = the FIXED selection size (positive int). Returns
    ``{track, primary_profile, top_n, pool_size, min_comparison_weeks, profiles, vs_balanced, boundary}`` where
    ``profiles[name]`` = ``{role, shadow_only, live_eligible, weights, selection:[{ticker,rank,core_score}]}`` and
    ``vs_balanced[shadow]`` = the balanced↔shadow selection set-diff. The result is re-validated through
    ``validate_shadow_comparison`` before return. Raises ``ShadowCompareError`` on malformed input / governance
    drift. The result is PRIVATE-tier (carries tickers) — persistence / de-id is a later slice."""
    _check_governance()
    if not _pos_int(top_n):
        raise ShadowCompareError("top_n must be a positive int, got %r" % (top_n,))
    pool = _validate_pool(scored_pool)
    profiles = {}
    for name in _FROZEN_PROFILES:                          # the output carries the FROZEN const-pin contract values
        frozen = _FROZEN_PROFILES[name]
        profiles[name] = {
            "role": frozen["role"],
            "shadow_only": frozen["shadow_only"],
            "live_eligible": frozen["live_eligible"],
            "weights": dict(frozen["weights"]),
            "selection": _select(pool, name, top_n),       # core_score scores from its frozen preset (== const, verified above)
        }
    balanced_set = {row["ticker"] for row in profiles[_FROZEN_PRIMARY]["selection"]}
    vs_balanced = {}
    for name in _FROZEN_PROFILES:
        if name == _FROZEN_PRIMARY:
            continue
        shadow_set = {row["ticker"] for row in profiles[name]["selection"]}
        vs_balanced[name] = {
            "balanced_only": sorted(balanced_set - shadow_set),   # balanced picks the shadow drops (for theme_off: the theme-weight marginal, #24)
            "shadow_extra": sorted(shadow_set - balanced_set),    # picks the shadow weight pulls in that balanced misses
            "overlap_count": len(balanced_set & shadow_set),
        }
    result = {
        "track": _TRACK,
        "primary_profile": _FROZEN_PRIMARY,
        "top_n": top_n,
        "pool_size": len(pool),
        "min_comparison_weeks": _MIN_COMPARISON_WEEKS,
        "profiles": profiles,
        "vs_balanced": vs_balanced,
        "boundary": dict(_BOUNDARY),
    }
    validate_shadow_comparison(result)
    return result


def validate_shadow_comparison(result) -> None:
    """Fail-closed §12.2 output-contract gate — self-checks the artifact rather than trusting the deriver: the
    frozen track / boundary / primary_profile / min_comparison_weeks; profiles cover EXACTLY the frozen profile
    set; EXACTLY one profile is primary/live; every selection is a deterministic (core_score DESC, ticker ASC),
    rank-1..k, len==min(top_n,pool_size), unique-ticker ranking (禁止挑样本); and every vs_balanced set-diff is
    consistent with the selections. Raises ``ShadowCompareError``."""
    if not isinstance(result, dict):
        raise ShadowCompareError("result must be a dict, got %r" % (type(result).__name__,))
    if result.get("track") != _TRACK:
        raise ShadowCompareError("track must be %r, got %r" % (_TRACK, result.get("track")))
    if result.get("boundary") != _BOUNDARY:
        raise ShadowCompareError("boundary must be the frozen ship-gate-isolation block %r, got %r" % (_BOUNDARY, result.get("boundary")))
    if result.get("primary_profile") != _FROZEN_PRIMARY:
        raise ShadowCompareError("primary_profile must be %r, got %r" % (_FROZEN_PRIMARY, result.get("primary_profile")))
    if result.get("min_comparison_weeks") != _MIN_COMPARISON_WEEKS:
        raise ShadowCompareError("min_comparison_weeks must be the frozen %r, got %r" % (_MIN_COMPARISON_WEEKS, result.get("min_comparison_weeks")))
    top_n = result.get("top_n")
    if not _pos_int(top_n):
        raise ShadowCompareError("top_n must be a positive int, got %r" % (top_n,))
    pool_size = result.get("pool_size")
    if not (isinstance(pool_size, int) and not isinstance(pool_size, bool) and pool_size >= 0):
        raise ShadowCompareError("pool_size must be a non-negative int, got %r" % (pool_size,))
    profiles = result.get("profiles")
    if not isinstance(profiles, dict) or set(profiles) != set(_FROZEN_PROFILES):
        raise ShadowCompareError(
            "profiles must cover EXACTLY %s, got %s"
            % (sorted(_FROZEN_PROFILES), sorted(map(str, profiles)) if isinstance(profiles, dict) else type(profiles).__name__))
    expected_len = min(top_n, pool_size)
    for name in _FROZEN_PROFILES:
        prof = profiles[name]
        _assert_frozen_profile(name, prof, "output")   # weights / role / live_eligible / shadow_only == frozen const-pin (locks the exposed contract)
        sel = prof.get("selection")
        if not isinstance(sel, list) or len(sel) != expected_len:
            raise ShadowCompareError(
                "profiles[%r].selection must be a list of len %d (min(top_n,pool_size)), got %r"
                % (name, expected_len, sel if not isinstance(sel, list) else "len=%d" % len(sel)))
        prev_score, prev_ticker, seen_t = None, None, set()
        for r, row in enumerate(sel):
            if not isinstance(row, dict) or set(row) != _SELECTION_KEYS:
                raise ShadowCompareError("profiles[%r].selection[%d] must have EXACTLY %s, got %r" % (name, r, sorted(_SELECTION_KEYS), row))
            if row["rank"] != r + 1 or isinstance(row["rank"], bool):
                raise ShadowCompareError("profiles[%r].selection[%d].rank must be %d, got %r" % (name, r, r + 1, row["rank"]))
            t = row["ticker"]
            if not isinstance(t, str) or not t.strip() or t in seen_t:
                raise ShadowCompareError("profiles[%r].selection[%d].ticker must be a unique non-blank string, got %r" % (name, r, t))
            seen_t.add(t)
            sc = row["core_score"]
            if not isinstance(sc, (int, float)) or isinstance(sc, bool):
                raise ShadowCompareError("profiles[%r].selection[%d].core_score must be a number, got %r" % (name, r, sc))
            if prev_score is not None and (sc > prev_score or (sc == prev_score and t < prev_ticker)):
                raise ShadowCompareError("profiles[%r].selection not in deterministic (core_score desc, ticker asc) order at index %d" % (name, r))
            prev_score, prev_ticker = sc, t

    vs = result.get("vs_balanced")
    shadow_names = [n for n in _FROZEN_PROFILES if n != _FROZEN_PRIMARY]
    if not isinstance(vs, dict) or set(vs) != set(shadow_names):
        raise ShadowCompareError(
            "vs_balanced must cover EXACTLY the shadow profiles %s, got %s"
            % (sorted(shadow_names), sorted(map(str, vs)) if isinstance(vs, dict) else type(vs).__name__))
    balanced_set = {row["ticker"] for row in profiles[_FROZEN_PRIMARY]["selection"]}
    for name in shadow_names:
        shadow_set = {row["ticker"] for row in profiles[name]["selection"]}
        d = vs[name]
        if not isinstance(d, dict) or set(d) != _VS_KEYS:
            raise ShadowCompareError("vs_balanced[%r] must have EXACTLY %s, got %r" % (name, sorted(_VS_KEYS), d))
        if d["balanced_only"] != sorted(balanced_set - shadow_set):
            raise ShadowCompareError("vs_balanced[%r].balanced_only is inconsistent with the selections" % (name,))
        if d["shadow_extra"] != sorted(shadow_set - balanced_set):
            raise ShadowCompareError("vs_balanced[%r].shadow_extra is inconsistent with the selections" % (name,))
        if d["overlap_count"] != len(balanced_set & shadow_set):
            raise ShadowCompareError("vs_balanced[%r].overlap_count is inconsistent with the selections" % (name,))
