"""US-short scoring-seam composer (batch5->batch4 Cut 6-d).

Pure offline glue. It consumes the three validated component projections from
Cut 6-a/b/c plus explicit risk_downgrade inputs, composing the same core_score
surface for both weekend selection (`selection_inputs.per_ticker`) and weekend
analysis rows (`score_blocks` + `risk_downgrade`).

It does not fetch data, run providers, write DataHub state, or wire a runner.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from engine.us_short_core_score import CORE_COMPONENTS, PRIMARY_PROFILE, PROFILE_NAMES, core_score
from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_overextension import validate_overextension_result
from engine.us_short_risk_downgrade import validate_risk_downgrade_input
from engine.us_short_seam_catalyst import (
    COVERAGE_DISPOSITIONS as CATALYST_COVERAGE_DISPOSITIONS,
    OUTPUT_KEYS as CATALYST_OUTPUT_KEYS,
)
from engine.us_short_seam_momentum import (
    COVERAGE_DISPOSITIONS as MOMENTUM_COVERAGE_DISPOSITIONS,
    _PROJECTION_OUTPUT_KEYS as MOMENTUM_OUTPUT_KEYS,
)
from engine.us_short_seam_theme import (
    COVERAGE_DISPOSITIONS as THEME_COVERAGE_DISPOSITIONS,
    OUTPUT_KEYS as THEME_OUTPUT_KEYS,
)


BINDING_PATH = Path(__file__).resolve().parent.parent / "docs" / "us_short_seam_score_binding_20260702.json"

COMPONENT_KEYS = ("momentum", "theme", "catalyst")
SCORE_BLOCK_KEYS = tuple(CORE_COMPONENTS)
OUTPUT_KEYS = (
    "selection_inputs",
    "analysis_by_ticker",
    "coverage_by_ticker",
    "target_tickers",
    "scoring_profile",
    "scored_component_counts",
)
THEME_MOMENTUM_NEUTRAL_SCORE = 0.0
COMPONENT_VALUE_KEYS = {
    "momentum": MOMENTUM_OUTPUT_KEYS[0],
    "theme": THEME_OUTPUT_KEYS[0],
    "catalyst": CATALYST_OUTPUT_KEYS[0],
}
_BLOCK_MIN, _BLOCK_MAX = 0.0, 100.0

_COMPONENT_SPECS = {
    "momentum": {
        "value_key": COMPONENT_VALUE_KEYS["momentum"],
        "dispositions": set(MOMENTUM_COVERAGE_DISPOSITIONS),
    },
    "theme": {
        "value_key": COMPONENT_VALUE_KEYS["theme"],
        "dispositions": set(THEME_COVERAGE_DISPOSITIONS),
    },
    "catalyst": {
        "value_key": COMPONENT_VALUE_KEYS["catalyst"],
        "dispositions": set(CATALYST_COVERAGE_DISPOSITIONS),
    },
}


class ScoreSeamError(ValueError):
    """Malformed component projection, risk map, or target identity for Cut 6-d."""


# §4.3 过热分档: a chasing_extreme ticker's theme-heat score is stripped back to the momentum+catalyst base by
# recomputing its core_score under the `theme_off` named profile (theme weight → 0, reallocated to momentum/
# catalyst; §4.2/§12.2) AND zeroing its theme_momentum_score (so it cannot hold a §4.5 theme seat). This is a
# PER-TICKER override applied ONLY to a run's chasing tickers, on TOP of the run's track scoring_profile — a
# DIFFERENT mechanism from a §12.2 WHOLE-TRACK theme_off shadow (scoring_profile="theme_off" for ALL tickers, an
# attribution comparison). The two are NOT conflated: the strip is opt-in per compose call (overextension_by_ticker)
# and leaves non-chasing tickers on the track profile. The SAME effective profile is recorded on the analysis row
# so the §4.2 one-core_score-per-run reconciliation (us_short_weekend_analysis._analyze_one) still holds.
_THEME_STRIP_PROFILE = "theme_off"
if _THEME_STRIP_PROFILE not in PROFILE_NAMES:   # fail fast at import if the scoring governance renames the profile
    raise ScoreSeamError(f"theme_off strip profile missing from scoring governance: {PROFILE_NAMES}")


def load_binding():
    return json.loads(BINDING_PATH.read_text(encoding="utf-8"))


def _require_exact_dict(value, *, name):
    if type(value) is not dict:
        raise ScoreSeamError(f"{name} must be an exact dict: {type(value).__name__}")
    return value


def _require_exact_list(value, *, name):
    if type(value) is not list:
        raise ScoreSeamError(f"{name} must be an exact list: {type(value).__name__}")
    return value


def _require_exact_str(value, *, name):
    if type(value) is not str:
        raise ScoreSeamError(f"{name} must be exact str: {type(value).__name__}")
    return value


def _key_set(value, *, name):
    _require_exact_dict(value, name=name)
    out = set()
    for key in value:
        out.add(_require_exact_str(key, name=f"{name} key"))
    return out


def _canonical_ticker(raw, *, where):
    _require_exact_str(raw, name=f"{where} ticker")
    ticker = canonical_us_ticker(raw)
    if ticker is None:
        raise ScoreSeamError(f"{where} ticker must be a canonicalizable US ticker")
    return ticker


def _canonical_targets(target_tickers):
    if type(target_tickers) is not list and type(target_tickers) is not tuple:
        raise ScoreSeamError(f"target_tickers must be exact list/tuple: {type(target_tickers).__name__}")
    out = []
    seen = set()
    for raw in target_tickers:
        ticker = _canonical_ticker(raw, where="target")
        if ticker in seen:
            raise ScoreSeamError(f"target_tickers contains duplicate canonical ticker: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    return out


def _finite_block_value(value, *, name):
    if type(value) is not int and type(value) is not float:
        raise ScoreSeamError(f"{name} must be exact int/float in [0,100]: {type(value).__name__}")
    try:
        out = float(value)
    except OverflowError as exc:
        raise ScoreSeamError(f"{name} must be finite in [0,100]") from exc
    if not math.isfinite(out) or out < _BLOCK_MIN or out > _BLOCK_MAX:
        raise ScoreSeamError(f"{name} must be finite in [0,100]")
    return out


def _exact_count(value, *, name):
    if type(value) is not int or value < 0:
        raise ScoreSeamError(f"{name} must be an exact non-negative int: {type(value).__name__}")
    return value


def _canonical_score_map(raw, *, name):
    _require_exact_dict(raw, name=name)
    out = {}
    for raw_ticker, raw_score in raw.items():
        ticker = _canonical_ticker(raw_ticker, where=name)
        if ticker in out:
            raise ScoreSeamError(f"{name} contains duplicate canonical ticker: {ticker}")
        out[ticker] = _finite_block_value(raw_score, name=f"{name}[{ticker}]")
    return out


def _canonical_ticker_list(raw, *, name):
    _require_exact_list(raw, name=name)
    out = []
    seen = set()
    for raw_ticker in raw:
        ticker = _canonical_ticker(raw_ticker, where=name)
        if ticker in seen:
            raise ScoreSeamError(f"{name} contains duplicate canonical ticker: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    return out


def _canonical_coverage(raw, *, name, allowed_dispositions):
    _require_exact_dict(raw, name=name)
    out = {}
    for raw_ticker, raw_disposition in raw.items():
        ticker = _canonical_ticker(raw_ticker, where=name)
        if ticker in out:
            raise ScoreSeamError(f"{name} contains duplicate canonical ticker: {ticker}")
        disposition = _require_exact_str(raw_disposition, name=f"{name}[{ticker}]")
        if disposition not in allowed_dispositions:
            raise ScoreSeamError(f"{name}[{ticker}] disposition drifted from component seam contract")
        out[ticker] = disposition
    return out


def _validate_projection(component, projection, targets):
    spec = _COMPONENT_SPECS[component]
    value_key = spec["value_key"]
    expected_keys = {value_key, "neutral_fill_tickers", "coverage", "target_count", "scored_count"}
    _require_exact_dict(projection, name=f"{component}_projection")
    actual_keys = _key_set(projection, name=f"{component}_projection")
    if actual_keys not in (expected_keys, expected_keys | {"source_binding"}):
        raise ScoreSeamError(f"{component}_projection keys drifted from the Cut 6-d contract")

    values = _canonical_score_map(projection[value_key], name=value_key)
    neutral_fill = _canonical_ticker_list(projection["neutral_fill_tickers"], name=f"{component}.neutral_fill_tickers")
    coverage = _canonical_coverage(
        projection["coverage"],
        name=f"{component}.coverage",
        allowed_dispositions=spec["dispositions"],
    )
    target_set = set(targets)
    value_set = set(values)
    neutral_set = set(neutral_fill)
    if value_set & neutral_set:
        raise ScoreSeamError(f"{component} projection has scored/neutral overlap")
    if value_set | neutral_set != target_set:
        raise ScoreSeamError(f"{component} projection scored+neutral partition must exactly cover targets")
    if set(coverage) != target_set:
        raise ScoreSeamError(f"{component} coverage must exactly cover targets")
    if _exact_count(projection["target_count"], name=f"{component}.target_count") != len(targets):
        raise ScoreSeamError(f"{component}.target_count must equal target count")
    if _exact_count(projection["scored_count"], name=f"{component}.scored_count") != len(values):
        raise ScoreSeamError(f"{component}.scored_count must equal scored value count")
    return {"values": values, "neutral_fill": neutral_fill, "coverage": coverage}


def _validate_risk_map(risk_downgrade_by_ticker, targets):
    _require_exact_dict(risk_downgrade_by_ticker, name="risk_downgrade_by_ticker")
    out = {}
    for raw_ticker, raw_risk in risk_downgrade_by_ticker.items():
        ticker = _canonical_ticker(raw_ticker, where="risk_downgrade_by_ticker")
        if ticker in out:
            raise ScoreSeamError(f"risk_downgrade_by_ticker contains duplicate canonical ticker: {ticker}")
        _require_exact_dict(raw_risk, name=f"risk_downgrade_by_ticker[{ticker}]")
        _require_exact_dict(raw_risk.get("components"), name=f"risk_downgrade_by_ticker[{ticker}].components")
        try:
            out[ticker] = validate_risk_downgrade_input(raw_risk)
        except ValueError as exc:
            raise ScoreSeamError(f"{ticker}: malformed risk_downgrade input") from exc
    if set(out) != set(targets):
        raise ScoreSeamError("risk_downgrade_by_ticker must exactly cover targets")
    return out


def _validated_theme_strip_targets(overextension_by_ticker, targets):
    """Validate the injected §4.3 overextension map (fail-closed, EXACT target coverage — mirroring the
    projection / risk maps) and return the set of targets whose theme-heat score must be stripped.

    None → no strip (the map is OPTIONAL; a §12.2 whole-track theme_off shadow or any non-overextension compose
    omits it, so the whole-track shadow is NOT conflated with this per-ticker strip). A PRESENT map must
    canonically cover the targets EXACTLY, each value a well-formed classify_overextension result (legal
    overextension_state + the exact state-bound strips/flags effect contract) — else fail closed (缺数据≠安全: a
    malformed or contradictory injected record must not silently skip/add an effect)."""
    if overextension_by_ticker is None:
        return set()
    _require_exact_dict(overextension_by_ticker, name="overextension_by_ticker")
    strip, seen = set(), set()
    for raw_ticker, record in overextension_by_ticker.items():
        ticker = _canonical_ticker(raw_ticker, where="overextension_by_ticker")
        if ticker in seen:
            raise ScoreSeamError(f"overextension_by_ticker contains duplicate canonical ticker: {ticker}")
        seen.add(ticker)
        _require_exact_dict(record, name=f"overextension_by_ticker[{ticker}]")
        try:
            validate_overextension_result(record)
        except ValueError as exc:
            raise ScoreSeamError(f"overextension_by_ticker[{ticker}] violated the §4.3 tier contract") from exc
        strips = record["strips_theme_score"]
        if strips is True:
            strip.add(ticker)
    if seen != set(targets):
        raise ScoreSeamError("overextension_by_ticker must exactly cover targets")
    return strip


def compose_score_inputs(
    *,
    target_tickers,
    momentum_projection,
    theme_projection,
    catalyst_projection,
    risk_downgrade_by_ticker,
    theme_opportunity_state,
    scoring_profile=PRIMARY_PROFILE,
    overextension_by_ticker=None,
):
    """Compose Cut 6 component projections into selection + analysis scoring inputs.

    Missing component blocks are omitted from `score_blocks`, letting `core_score`
    apply its neutral-block rule. `theme_momentum_score` is the scored theme block
    when present, else 0.0, so neutral/missing theme evidence cannot occupy
    theme-momentum seats.

    `overextension_by_ticker` (optional §4.3 injected map) strips theme for chasing_extreme
    tickers: such a ticker's core_score is recomputed under the `theme_off` profile (theme
    weight → 0) and its theme_momentum_score is zeroed (no §4.5 theme seat). The SAME effective
    profile is recorded on its analysis row, so the one-core_score-per-run reconciliation in
    us_short_weekend_analysis._analyze_one holds. Absent map / non-chasing ticker → unchanged
    behavior. A per-ticker strip is distinct from a §12.2 whole-track theme_off shadow
    (scoring_profile="theme_off" for ALL tickers) — see _THEME_STRIP_PROFILE.
    """
    if type(scoring_profile) is not str:
        raise ScoreSeamError(f"scoring_profile must be exact str: {type(scoring_profile).__name__}")
    if scoring_profile not in PROFILE_NAMES:   # fail closed up front — a per-ticker theme_off strip must not let
        raise ScoreSeamError(f"unknown scoring_profile: {scoring_profile!r}")   # an all-chasing run silently bypass
    _require_exact_str(theme_opportunity_state, name="theme_opportunity_state")
    targets = _canonical_targets(target_tickers)
    projections = {
        "momentum": _validate_projection("momentum", momentum_projection, targets),
        "theme": _validate_projection("theme", theme_projection, targets),
        "catalyst": _validate_projection("catalyst", catalyst_projection, targets),
    }
    risks = _validate_risk_map(risk_downgrade_by_ticker, targets)
    theme_strip_targets = _validated_theme_strip_targets(overextension_by_ticker, targets)

    selection_per_ticker = {}
    analysis_by_ticker = {}
    coverage_by_ticker = {}
    for ticker in targets:
        blocks = {}
        for component in COMPONENT_KEYS:
            value = projections[component]["values"].get(ticker)
            if value is not None:
                blocks[component] = value
        # §4.3 chasing_extreme strip: recompute under theme_off (theme weight → 0) and zero theme_momentum_score.
        # The SAME effective profile rides onto the analysis row below, so the §4.2 one-core_score-per-run
        # reconciliation still holds; a non-chasing ticker keeps the run's track profile.
        stripped = ticker in theme_strip_targets
        effective_profile = _THEME_STRIP_PROFILE if stripped else scoring_profile
        try:
            score = core_score(blocks, effective_profile, risk_downgrade_points=risks[ticker]["points"])
        except KeyError as exc:
            raise ScoreSeamError(f"unknown scoring_profile: {effective_profile!r}") from exc

        selection_per_ticker[ticker] = {
            "core_score": score["core_score"],
            "theme_momentum_score": (THEME_MOMENTUM_NEUTRAL_SCORE if stripped
                                     else projections["theme"]["values"].get(ticker, THEME_MOMENTUM_NEUTRAL_SCORE)),
        }
        analysis_by_ticker[ticker] = {
            "score_blocks": blocks,
            "risk_downgrade": risks[ticker],
            "scoring_profile": effective_profile,
        }
        coverage_by_ticker[ticker] = {
            component: projections[component]["coverage"][ticker]
            for component in COMPONENT_KEYS
        }

    return {
        "selection_inputs": {
            "theme_opportunity_state": theme_opportunity_state,
            "per_ticker": selection_per_ticker,
        },
        "analysis_by_ticker": analysis_by_ticker,
        "coverage_by_ticker": coverage_by_ticker,
        "target_tickers": list(targets),
        "scoring_profile": scoring_profile,
        "scored_component_counts": {
            component: len(projections[component]["values"])
            for component in COMPONENT_KEYS
        },
    }
