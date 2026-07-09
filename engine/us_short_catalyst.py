# -*- coding: utf-8 -*-
"""US-short core_score CATALYST block (§4.2 catalyst sub-score, 25%) — pure rule-mapping engine.

Design authority: docs/us_short_system_design.md §4.2:
  core_score = 40% momentum + 35% theme + 25% catalyst − risk_downgrade
  催化剂 = 规则映射分（非分位）— a DETERMINISTIC rule-mapping score, NOT a percentile (unlike momentum/theme).
  催化剂细分 = 财报实际vs预期 + 分析师修正 + 8-K/订单/产品/监管 + LLM 语义；**仅已实现/当前**，未来事件不进
  选股分、归 §8.1 (engine/us_short_forward_events.py).

This module is PURE (no network, no provider, no A-share crossing). It consumes already-EXTRACTED per-ticker
catalyst signals (the FMP earnings/analyst + free SEC 8-K data layer supplies them later — that data layer is
provider-gated, SR-PROVIDER-001, exactly like the momentum slice's Massive grouped-daily layer) plus the frozen
catalyst governance contract (presets/us_short_catalyst_governance_20260630.json), and maps each ticker to a
0-100 catalyst block that engine/us_short_core_score.py consumes as its `catalyst` block.

Rule-mapping (a §13.1 #14 forward-calibratable prior, NOT validated alpha): score = clamp(NEUTRAL + Σ points,
score_bounds), where each REALIZED signal contributes governed additive points — earnings surprise % (5 buckets,
continuous), analyst-revision net signed INTEGER count (5 buckets), 8-K event class (positive/neutral/negative),
and an advisory LLM
semantic score (linearly scaled, capped small — advisory never dominates). A bullish realized catalyst lifts the
block above neutral; a bearish one drops it below.

REALIZED-ONLY (§4.2 仅已实现/当前): each signal carries an event date; a signal dated AFTER the run `as_of` is a
FUTURE event → EXCLUDED from the block (it belongs to §8.1 forward_events, never the selection score), and a
signal whose date is missing/unparseable is EXCLUDED as unverified (conservative — an unproven catalyst must not
lift the score). The engine enforces this EXCLUSION rule against caller-supplied dates; the PROVENANCE that those
dates are real/PIT is the gated data layer (the same boundary the momentum slice draws for PIT/alignment).

MISSING → NEUTRAL (§4.2 缺分量): a ticker with NO realized signal scores the NEUTRAL value (50) and is listed in
`neutral_fallback` so the caller applies its §4.2 data_quality degrade + tag (no fake coverage, no silent
re-normalisation). SCOPE: this block is the fundamental beat/miss + revision + 8-K + semantic SIGNAL strength
only; the good-data-BAD-price-REACTION soft penalty is the SEPARATE engine/us_short_risk_downgrade.py
(core_score = ... − risk_downgrade; §18.1 #26 两字段分离), not folded here. All numeric inputs are strictly
validated (reject bool / NaN / Inf / numeric string); dates are strict real-calendar YYYYMMDD.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path

_GOV_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_catalyst_governance_20260630.json"

# Frozen v1 governed schedule (== presets/us_short_catalyst_governance_20260630.json; a conformance test
# triangulates module const == preset so this consumer copy cannot silently drift — mirrors
# engine/us_short_eligibility_gate.py). Calibration of these §13.1 #14 priors is a reviewed
# schema+preset+module version bump, never a silent edit.
_V1_NEUTRAL = 50.0
_V1_SCORE_BOUNDS = {"min": 0.0, "max": 100.0}
_V1_EARNINGS_BOUNDS = {"big_beat_min": 10.0, "beat_min": 2.0, "miss_max": -2.0, "big_miss_max": -10.0}
_V1_EARNINGS_POINTS = {"big_beat": 20.0, "beat": 10.0, "inline": 0.0, "miss": -10.0, "big_miss": -20.0}
_V1_REVISION_BOUNDS = {"strong_positive_min": 3, "positive_min": 1, "negative_max": -1, "strong_negative_max": -3}
_V1_REVISION_POINTS = {"strong_positive": 15.0, "positive": 8.0, "neutral": 0.0, "negative": -8.0, "strong_negative": -15.0}
_V1_EVENT8K_POINTS = {"positive": 12.0, "neutral": 0.0, "negative": -12.0}
_V1_SEMANTIC_INPUT_BOUNDS = {"min": -1.0, "max": 1.0}
_V1_SEMANTIC_MAX_ABS_POINTS = 6.0
_V1_SCORING_CALIBER_ITEM_ID = 14

_REQUIRED_GOV_KEYS = {
    "schema_name", "schema_version", "as_of", "status",
    "neutral_catalyst_score", "score_bounds",
    "earnings_surprise", "analyst_revision", "event_8k", "semantic_advisory",
    "scoring_caliber_calibration_item_id", "notes",
}

EVENT_8K_CLASSES = ("positive", "neutral", "negative")


class CatalystGovernanceError(Exception):
    """The loaded catalyst governance artifact is malformed or has drifted from the frozen v1 contract
    (fail-closed)."""


def _is_finite_number(x):
    """Strict: a real finite number — rejects bool, None, strings, NaN/Inf, and an over-large int (a raw
    provider catalyst value, passed verbatim by catalyst_source, could carry one; math.isfinite() would
    raise OverflowError → treated as non-finite here, never a bare crash)."""
    if not isinstance(x, (int, float)) or isinstance(x, bool):
        return False
    try:
        return math.isfinite(x)
    except OverflowError:
        return False


def _finite(x):
    """Strict finite number → float, else None (so a malformed signal can't be parsed into a live value)."""
    return float(x) if _is_finite_number(x) else None


def _finite_int(x):
    """Strict SIGNED INTEGER count → int, else None. An analyst-revision NET is an event/count field, so a bool /
    string / NaN/Inf / fractional or integer-valued FLOAT (2.9 or 3.0) is malformed and is NOT scored — distinct
    from the genuinely continuous earnings-% / semantic-score fields, which use _finite (the codebase's
    count-vs-number whole-class input-validation discipline: count = isinstance int, not bool, not float)."""
    return x if isinstance(x, int) and not isinstance(x, bool) else None


def _parse_yyyymmdd(s):
    """Strict 8-ASCII-digit real-calendar YYYYMMDD → date, else None (rejects 20261399 / non-str / wrong width)."""
    if not (isinstance(s, str) and len(s) == 8 and s.isascii() and s.isdigit()):
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None


def _check_subdict(gov_sub, expected, label):
    """The governed sub-dict must have EXACTLY `expected`'s keys, each value == the frozen const (a float
    expected is compared as finite-number==; an int bound expected requires a strict non-bool int)."""
    if not isinstance(gov_sub, dict) or set(gov_sub) != set(expected):
        raise CatalystGovernanceError(f"{label} 键须恰为 {sorted(expected)}: {gov_sub!r}")
    for k, exp in expected.items():
        v = gov_sub[k]
        if isinstance(exp, float):
            if not _is_finite_number(v) or float(v) != exp:
                raise CatalystGovernanceError(f"{label}.{k} 偏离冻结 v1 prior {exp}（校准须 reviewed 版本变更）: {v!r}")
        else:  # int bucket bound
            if not (isinstance(v, int) and not isinstance(v, bool) and v == exp):
                raise CatalystGovernanceError(f"{label}.{k} 偏离冻结 v1 prior {exp}: {v!r}")


def validate_catalyst_governance(gov):
    """Fail-closed runtime gate: the loaded governance must BE the frozen v1 contract.

    Structural (closed-world top-level key set, types) + semantic (the governed v1 values — neutral / bounds /
    every bucket bound + point value / §13.1 #14 anchor — must equal the frozen consts). Metadata
    (schema_version / as_of / status / notes) is type-checked, not value-pinned. Returns the dict; else raises.
    """
    if not isinstance(gov, dict):
        raise CatalystGovernanceError("governance 须为 object")
    if set(gov) != _REQUIRED_GOV_KEYS:
        raise CatalystGovernanceError(
            f"governance 顶层键须恰为 {sorted(_REQUIRED_GOV_KEYS)}（closed-world）: {sorted(gov)}")
    if gov["schema_name"] != "us_short_catalyst_governance":
        raise CatalystGovernanceError(f"schema_name 非法: {gov['schema_name']!r}")
    if not (isinstance(gov["schema_version"], str) and gov["schema_version"]):
        raise CatalystGovernanceError("schema_version 须为非空字符串")
    if not (isinstance(gov["as_of"], str) and len(gov["as_of"]) == 8 and gov["as_of"].isascii()
            and gov["as_of"].isdigit()):
        raise CatalystGovernanceError(f"as_of 须为 8 位 ASCII YYYYMMDD: {gov['as_of']!r}")
    if _parse_yyyymmdd(gov["as_of"]) is None:
        raise CatalystGovernanceError(f"as_of 非真实日历日: {gov['as_of']!r}")
    if not (isinstance(gov["status"], str) and gov["status"].strip()):
        raise CatalystGovernanceError("status 须为非空字符串")
    if not (isinstance(gov["notes"], dict) and gov["notes"]):
        raise CatalystGovernanceError("notes 须为非空 object")

    # Governed v1 values — must equal the frozen consts (drift fails closed at runtime).
    nb = gov["neutral_catalyst_score"]
    if not _is_finite_number(nb) or float(nb) != _V1_NEUTRAL:
        raise CatalystGovernanceError(f"neutral_catalyst_score 偏离冻结 v1 {_V1_NEUTRAL}: {nb!r}")
    _check_subdict(gov["score_bounds"], _V1_SCORE_BOUNDS, "score_bounds")
    es = gov["earnings_surprise"]
    if not isinstance(es, dict) or set(es) != {"bucket_bounds_pct", "points"}:
        raise CatalystGovernanceError(f"earnings_surprise 键须恰为 ['bucket_bounds_pct','points']: {es!r}")
    _check_subdict(es["bucket_bounds_pct"], _V1_EARNINGS_BOUNDS, "earnings_surprise.bucket_bounds_pct")
    _check_subdict(es["points"], _V1_EARNINGS_POINTS, "earnings_surprise.points")
    ar = gov["analyst_revision"]
    if not isinstance(ar, dict) or set(ar) != {"bucket_bounds_net", "points"}:
        raise CatalystGovernanceError(f"analyst_revision 键须恰为 ['bucket_bounds_net','points']: {ar!r}")
    _check_subdict(ar["bucket_bounds_net"], _V1_REVISION_BOUNDS, "analyst_revision.bucket_bounds_net")
    _check_subdict(ar["points"], _V1_REVISION_POINTS, "analyst_revision.points")
    ek = gov["event_8k"]
    if not isinstance(ek, dict) or set(ek) != {"points"}:
        raise CatalystGovernanceError(f"event_8k 键须恰为 ['points']: {ek!r}")
    _check_subdict(ek["points"], _V1_EVENT8K_POINTS, "event_8k.points")
    sa = gov["semantic_advisory"]
    if not isinstance(sa, dict) or set(sa) != {"input_bounds", "max_abs_points"}:
        raise CatalystGovernanceError(f"semantic_advisory 键须恰为 ['input_bounds','max_abs_points']: {sa!r}")
    _check_subdict(sa["input_bounds"], _V1_SEMANTIC_INPUT_BOUNDS, "semantic_advisory.input_bounds")
    mp = sa["max_abs_points"]
    if not _is_finite_number(mp) or float(mp) != _V1_SEMANTIC_MAX_ABS_POINTS:
        raise CatalystGovernanceError(
            f"semantic_advisory.max_abs_points 偏离冻结 v1 {_V1_SEMANTIC_MAX_ABS_POINTS}: {mp!r}")
    cid = gov["scoring_caliber_calibration_item_id"]
    if not (isinstance(cid, int) and not isinstance(cid, bool) and cid == _V1_SCORING_CALIBER_ITEM_ID):
        raise CatalystGovernanceError(
            f"scoring_caliber_calibration_item_id 偏离冻结 §13.1 锚 {_V1_SCORING_CALIBER_ITEM_ID}: {cid!r}")
    return gov


def load_catalyst_governance(path=_GOV_PATH):
    """Load + fail-closed-validate the frozen catalyst governance artifact (offline; no network)."""
    with open(Path(path), encoding="utf-8") as f:
        gov = json.load(f)
    return validate_catalyst_governance(gov)


def _earnings_points(surprise_pct, gov):
    """Realized earnings surprise % (actual vs expected) → governed additive points (5 buckets); None if the
    value is malformed (not a usable signal). big_miss is tested before miss so a deep miss isn't mislabelled."""
    b, p = gov["earnings_surprise"]["bucket_bounds_pct"], gov["earnings_surprise"]["points"]
    s = _finite(surprise_pct)
    if s is None:
        return None
    if s >= b["big_beat_min"]:
        return p["big_beat"]
    if s >= b["beat_min"]:
        return p["beat"]
    if s <= b["big_miss_max"]:
        return p["big_miss"]
    if s <= b["miss_max"]:
        return p["miss"]
    return p["inline"]


def _revision_points(net, gov):
    """Realized analyst-revision net signed count → governed additive points (5 buckets). The net is a strict
    SIGNED INTEGER count: a bool / string / NaN/Inf / fractional or integer-valued float (2.9 / 3.0) is malformed
    → None (not scored). The bucket bounds are integer thresholds."""
    b, p = gov["analyst_revision"]["bucket_bounds_net"], gov["analyst_revision"]["points"]
    n = _finite_int(net)
    if n is None:
        return None
    if n >= b["strong_positive_min"]:
        return p["strong_positive"]
    if n >= b["positive_min"]:
        return p["positive"]
    if n <= b["strong_negative_max"]:
        return p["strong_negative"]
    if n <= b["negative_max"]:
        return p["negative"]
    return p["neutral"]


def _event8k_points(cls, gov):
    """Realized 8-K event class → governed additive points; None for an unknown / non-str class (not scored)."""
    p = gov["event_8k"]["points"]
    return p[cls] if isinstance(cls, str) and cls in p else None


def _semantic_points(score, gov):
    """Advisory LLM semantic score (clamped to input_bounds) → linearly-scaled points capped at ±max_abs_points;
    None if the value is malformed. Advisory only — the cap keeps it from dominating the rule-mapping."""
    sa = gov["semantic_advisory"]
    s = _finite(score)
    if s is None:
        return None
    s = max(sa["input_bounds"]["min"], min(sa["input_bounds"]["max"], s))   # clamp to [-1, 1]
    return s * sa["max_abs_points"]                                          # |result| <= max_abs_points


# Each catalyst signal = (value_key, date_key, points_fn). value + date are flat per-ticker keys; the gated
# data layer flattens FMP earnings/analyst + SEC 8-K into these. Order is display-only (points are additive).
_SIGNALS = (
    ("earnings_surprise_pct", "earnings_report_date", _earnings_points),
    ("analyst_revision_net", "analyst_revision_date", _revision_points),
    ("event_8k_class", "event_8k_date", _event8k_points),
    ("semantic_advisory_score", "semantic_advisory_date", _semantic_points),
)


def catalyst_block(signals_by_ticker, governance, *, as_of):
    """Map per-ticker REALIZED catalyst signals → a 0-100 rule-mapping catalyst block (§4.2, 25%).

    signals_by_ticker = {ticker: {<value_key>: ..., <date_key>: "YYYYMMDD", ...}}; governance = the catalyst
    governance dict (defensively re-validated here, fail-closed); as_of = the run decision date (strict YYYYMMDD).

    For each ticker: score = clamp(NEUTRAL + Σ realized-signal points, score_bounds). A signal contributes ONLY
    when its value is a valid governed input AND its date parses AND date <= as_of (REALIZED). A date > as_of is a
    FUTURE event (→ §8.1, excluded); a missing/unparseable date is UNVERIFIED (excluded, conservative); a
    malformed value is simply not a usable signal. A ticker with NO realized signal scores NEUTRAL and is listed
    in `neutral_fallback` (§4.2 缺分量 — the caller applies its data_quality degrade + tag).

    Returns {catalyst_block: {ticker: 0-100}, neutral_fallback: [ticker, ...],
             coverage_matrix: {ticker: {realized: [name], future_excluded: [name], unverified_excluded: [name]}},
             neutral_catalyst_score: float, as_of: str}.
    """
    as_of_d = _parse_yyyymmdd(as_of)
    if as_of_d is None:
        raise CatalystGovernanceError(f"as_of 须为真实日历 YYYYMMDD（无法判定已实现边界）: {as_of!r}")
    validate_catalyst_governance(governance)   # defensive: fail closed if a drifted/forged governance is passed
    neutral = governance["neutral_catalyst_score"]
    lo, hi = governance["score_bounds"]["min"], governance["score_bounds"]["max"]
    if not isinstance(signals_by_ticker, dict):
        signals_by_ticker = {}

    block, neutral_fallback, coverage_matrix = {}, [], {}
    for tkr, sig in signals_by_ticker.items():
        realized, future_excluded, unverified_excluded = [], [], []
        total = 0.0
        sig = sig if isinstance(sig, dict) else {}
        for value_key, date_key, pts_fn in _SIGNALS:
            if value_key not in sig:
                continue
            pts = pts_fn(sig.get(value_key), governance)
            if pts is None:
                continue                                  # malformed/unmappable value → not a usable signal
            ev = _parse_yyyymmdd(sig.get(date_key))
            if ev is None:
                unverified_excluded.append(value_key)     # value present but date missing/invalid → conservative
            elif ev > as_of_d:
                future_excluded.append(value_key)         # future → §8.1 forward_events, never the selection score
            else:
                realized.append(value_key)
                total += pts
        coverage_matrix[tkr] = {
            "realized": sorted(realized),
            "future_excluded": sorted(future_excluded),
            "unverified_excluded": sorted(unverified_excluded),
        }
        if realized:
            block[tkr] = max(lo, min(hi, neutral + total))
        else:
            block[tkr] = neutral                          # §4.2 缺分量: no realized catalyst → neutral block value
            neutral_fallback.append(tkr)
    return {
        "catalyst_block": block,
        "neutral_fallback": sorted(neutral_fallback),
        "coverage_matrix": coverage_matrix,
        "neutral_catalyst_score": neutral,
        "as_of": as_of,
    }
