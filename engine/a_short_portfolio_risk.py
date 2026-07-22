"""Deterministic M5.5/M5.5B portfolio concentration calculations.

This module deliberately contains no I/O, provider calls, or report rendering.
The weekly pipeline supplies as-of-bound security facts plus final tentative
share counts, then consumes the structured results to make the M6.7 action and
cash allocation agree.  Missing inputs are an explicit manual-review state;
they are never interpreted as a clean portfolio.
"""
from __future__ import annotations

import math
from collections import defaultdict

from engine.a_short_runtime_config import load_runtime_configuration

_RUNTIME_CONFIGURATION = load_runtime_configuration()
_PORTFOLIO_POLICY = _RUNTIME_CONFIGURATION["m67"]["portfolio_risk"]
SAME_SW_L2_THRESHOLD_PCT = _PORTFOLIO_POLICY["same_sw_l2_threshold_pct"]
NORTHBOUND_THRESHOLD_PCT = _PORTFOLIO_POLICY["northbound_threshold_pct"]
MARGIN_THRESHOLD_PCT = _PORTFOLIO_POLICY["margin_threshold_pct"]
LARGE_INDEX_THRESHOLD_PCT = _PORTFOLIO_POLICY["large_index_threshold_pct"]
SMALL_FLOAT_MV_THRESHOLD_PCT = _PORTFOLIO_POLICY["small_float_mv_threshold_pct"]
SMALL_FLOAT_MV_RMB = _PORTFOLIO_POLICY["small_float_mv_rmb"]
HIGH_RISK_HOLDING_CAP_MULTIPLIER = _PORTFOLIO_POLICY["high_risk_holding_cap_multiplier"]


def _format_rmb_yi(value: float) -> str:
    return f"{float(value) / 100_000_000.0:g}亿元"


def _high_risk_cap_reduction_pct() -> str:
    return f"{(1.0 - HIGH_RISK_HOLDING_CAP_MULTIPLIER) * 100.0:g}"


_FACTOR_SPECS = (
    ("northbound_holding_ratio_pct", "北向持股比例", NORTHBOUND_THRESHOLD_PCT),
    ("margin_balance_to_float_mv_pct", "融资余额/流通市值", MARGIN_THRESHOLD_PCT),
    ("large_index_component_pct", "50ETF/沪深300成分股", LARGE_INDEX_THRESHOLD_PCT),
    ("small_float_mv_pct", f"小流通市值(<{_format_rmb_yi(SMALL_FLOAT_MV_RMB)})", SMALL_FLOAT_MV_THRESHOLD_PCT),
)
_REQUIRED_FACT_FIELDS = (
    "sw_l2_key",
    "circ_mv_rmb",
    "northbound_holding_ratio_pct",
    "margin_balance_to_float_mv_pct",
    "is_large_index_component",
)


def _finite_number(value, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    if not math.isfinite(value):
        return None
    if minimum is not None and value < minimum:
        return None
    if maximum is not None and value > maximum:
        return None
    return value


def _string(value):
    value = str(value or "").strip()
    if not value or value.lower() in {"unknown", "未知", "none", "null"}:
        return None
    return value


def _valid_fact(fact, field, as_of):
    if not isinstance(fact, dict) or str(fact.get("as_of") or "") != str(as_of):
        return False
    value = fact.get(field)
    if field == "sw_l2_key":
        return _string(value) is not None
    if field == "is_large_index_component":
        return isinstance(value, bool)
    if field == "circ_mv_rmb":
        return _finite_number(value, minimum=0.0) is not None
    return _finite_number(value, minimum=0.0, maximum=100.0) is not None


def _missing_fields(assets, as_of):
    missing = []
    for asset in assets:
        code = str(asset.get("ts_code") or "?")
        fact = asset.get("fact") or {}
        value = _finite_number(asset.get("value_rmb"), minimum=0.0)
        if value is None or value <= 0:
            missing.append(f"{code}:position_value")
        for field in _REQUIRED_FACT_FIELDS:
            if not _valid_fact(fact, field, as_of):
                missing.append(f"{code}:{field}")
    return sorted(set(missing))


def _factor_values(assets):
    total = sum(float(asset["value_rmb"]) for asset in assets)
    if total <= 0:
        raise ValueError("portfolio value must be positive")
    return {
        "northbound_holding_ratio_pct": sum(
            float(asset["value_rmb"]) * float(asset["fact"]["northbound_holding_ratio_pct"])
            for asset in assets
        ) / total,
        "margin_balance_to_float_mv_pct": sum(
            float(asset["value_rmb"]) * float(asset["fact"]["margin_balance_to_float_mv_pct"])
            for asset in assets
        ) / total,
        "large_index_component_pct": 100.0 * sum(
            float(asset["value_rmb"]) for asset in assets
            if asset["fact"]["is_large_index_component"]
        ) / total,
        "small_float_mv_pct": 100.0 * sum(
            float(asset["value_rmb"]) for asset in assets
            if float(asset["fact"]["circ_mv_rmb"]) < SMALL_FLOAT_MV_RMB
        ) / total,
    }


def _industry_exposures(assets):
    total = sum(float(asset["value_rmb"]) for asset in assets)
    grouped = defaultdict(float)
    for asset in assets:
        grouped[str(asset["fact"]["sw_l2_key"])] += float(asset["value_rmb"])
    return [
        {"sw_l2_key": key, "value_pct": round(value * 100.0 / total, 4),
         "threshold_pct": SAME_SW_L2_THRESHOLD_PCT,
         "over_threshold": value * 100.0 / total > SAME_SW_L2_THRESHOLD_PCT}
        for key, value in sorted(grouped.items())
    ]


def _factor_rows(values, before_values, candidate_fact):
    rows = []
    for field, label, threshold in _FACTOR_SPECS:
        value = float(values[field])
        before = before_values.get(field)
        if field == "large_index_component_pct":
            adds = bool(candidate_fact["is_large_index_component"])
        elif field == "small_float_mv_pct":
            adds = float(candidate_fact["circ_mv_rmb"]) < SMALL_FLOAT_MV_RMB
        else:
            adds = before is None or float(candidate_fact[field]) > float(before)
        rows.append({
            "factor": field,
            "label": label,
            "value_pct": round(value, 4),
            "threshold_pct": threshold,
            "over_threshold": value > threshold,
            "candidate_adds_exposure": adds,
            "status": "over_threshold" if value > threshold else "clear",
        })
    return rows


def fact_from_normalized(normalized: dict, as_of: str, override: dict | None = None) -> dict:
    """Normalize one candidate/holding's factor inputs into a dated fact record.

    `override` is used by the bounded Tushare snapshot path.  A mismatched
    override date is ignored rather than silently crossing weekly batches.
    """
    raw = dict(normalized.get("portfolio_risk_facts") or {})
    code = str(normalized.get("ts_code") or "")
    if (isinstance(override, dict)
            and str(override.get("as_of") or "") == str(as_of)
            and (not override.get("ts_code") or str(override.get("ts_code")) == code)):
        raw.update({key: value for key, value in override.items() if key != "source"})
        source = str(override.get("source") or "tushare_portfolio_snapshot")
    elif isinstance(override, dict):
        # An explicitly supplied provider result for another stock/date is not
        # allowed to fall back silently to a different fact set.  Make it
        # visibly invalid so the allocator takes the manual-review path.
        return {
            "as_of": str(as_of), "source": "portfolio_risk_invalid_override",
            "sw_l2_key": None, "circ_mv_rmb": None,
            "northbound_holding_ratio_pct": None,
            "margin_balance_to_float_mv_pct": None,
            "is_large_index_component": None,
        }
    else:
        source = str(raw.get("source") or "analysis_input")
    return {
        "as_of": str(as_of),
        "source": source,
        "sw_l2_key": _string(raw.get("sw_l2_key")),
        "circ_mv_rmb": _finite_number(raw.get("circ_mv_rmb"), minimum=0.0),
        "northbound_holding_ratio_pct": _finite_number(raw.get("northbound_holding_ratio_pct"), minimum=0.0, maximum=100.0),
        "margin_balance_to_float_mv_pct": _finite_number(raw.get("margin_balance_to_float_mv_pct"), minimum=0.0, maximum=100.0),
        "is_large_index_component": raw.get("is_large_index_component")
        if isinstance(raw.get("is_large_index_component"), bool) else None,
    }


def build_context(normalized_list: list[dict], as_of: str, *, fact_overrides: dict | None = None,
                  account_positions: list[dict] | None = None, missing_holding_codes: list[str] | None = None) -> dict:
    """Build mutable allocation context from weekly-normalized rows.

    Existing holdings are valued from the same price clock as their M6.7 row.
    Any account holding missing that price clock is kept as an explicit unknown
    holding so later allocation fails closed instead of understating exposure.
    """
    overrides = fact_overrides or {}
    positions = {str(p.get("ts_code")): p for p in (account_positions or [])}
    existing, facts = [], {}
    seen_held = set()
    for normalized in normalized_list:
        code = str(normalized.get("ts_code") or "")
        if not code:
            continue
        fact = fact_from_normalized(normalized, as_of, overrides.get(code))
        facts[code] = fact
        stateful = normalized.get("stateful_risk") or {}
        position = stateful.get("position") or positions.get(code)
        if stateful.get("position_state") == "held" or position is not None:
            shares = _finite_number((position or {}).get("shares"), minimum=0.0)
            close = _finite_number(normalized.get("close"), minimum=0.0)
            existing.append({"ts_code": code, "value_rmb": None if shares is None or close is None else shares * close,
                             "fact": fact})
            seen_held.add(code)
    for code in sorted(set(missing_holding_codes or []) | (set(positions) - seen_held)):
        if code not in seen_held:
            existing.append({"ts_code": code, "value_rmb": None, "fact": facts.get(code, {"as_of": str(as_of)})})
    return {"as_of": str(as_of), "facts": facts, "existing": existing, "committed": [], "results": {}}


def not_applicable_result(ts_code: str, role: str, reason: str) -> dict:
    return {
        "ts_code": str(ts_code), "role": role, "status": "not_applicable", "action": "none",
        "evaluated": False, "candidate_value_rmb": None, "post_position_count": None,
        "same_sw_l2": None, "factor_exposures": [], "reasons": [reason], "missing_fields": [],
    }


def evaluate_candidate(context: dict, ts_code: str, candidate_value_rmb: float) -> dict:
    """Evaluate one *tentative* allocation against holdings plus prior commits."""
    as_of, code = str(context["as_of"]), str(ts_code)
    value = _finite_number(candidate_value_rmb, minimum=0.0)
    if value is None or value <= 0:
        return not_applicable_result(code, "candidate", "无有效试算买入金额，组合规则不适用")
    fact = context["facts"].get(code, {"as_of": as_of})
    before = list(context["existing"]) + list(context["committed"])
    after = before + [{"ts_code": code, "value_rmb": value, "fact": fact}]
    if len(after) < 2:
        return not_applicable_result(code, "candidate", "买入后持仓不足2只，M5.5B不适用") | {
            "candidate_value_rmb": round(value, 2), "post_position_count": len(after),
        }
    missing = _missing_fields(after, as_of)
    if missing:
        return {
            "ts_code": code, "role": "candidate", "status": "manual_review_required",
            "action": "observe_required", "evaluated": False, "candidate_value_rmb": round(value, 2),
            "post_position_count": len(after), "same_sw_l2": None, "factor_exposures": [],
            "reasons": ["组合集中度/因子共振数据未核查，本周不定量建仓"], "missing_fields": missing,
        }
    before_values = _factor_values(before) if before else {}
    values = _factor_values(after)
    same_before_value = sum(asset["value_rmb"] for asset in before
                            if asset["fact"]["sw_l2_key"] == fact["sw_l2_key"])
    same_value = sum(asset["value_rmb"] for asset in after
                     if asset["fact"]["sw_l2_key"] == fact["sw_l2_key"]) * 100.0 / sum(asset["value_rmb"] for asset in after)
    same = {"sw_l2_key": fact["sw_l2_key"], "value_pct": round(same_value, 4),
            "threshold_pct": SAME_SW_L2_THRESHOLD_PCT,
            "over_threshold": same_value > SAME_SW_L2_THRESHOLD_PCT}
    factors = _factor_rows(values, before_values, fact)
    factor_breaches = [row for row in factors if row["over_threshold"]]
    aligned = [row for row in factor_breaches if row["candidate_adds_exposure"]]
    # A diversified new industry may temporarily be 50% while a two-name
    # basket is being built.  M5.5 is a same-industry add guard, so it applies
    # only when this candidate increases an L2 already represented before it
    # was considered.  Keep the raw exposure visible in `same` either way.
    if same["over_threshold"] and same_before_value > 0:
        action = "replace"
        reasons = [f"同SW L2 {same['sw_l2_key']} 暴露 {same['value_pct']:.2f}% > 40%，建议替换"]
        status = "concentration_over_cap"
    elif aligned:
        action = "observe_required"
        reasons = [f"{row['label']} {row['value_pct']:.2f}% > {row['threshold_pct']:.0f}%，新增会加重该因子暴露"
                   for row in aligned]
        status = "factor_resonance_high_risk" if len(factor_breaches) >= 2 else "factor_resonance"
    else:
        action = "allow"
        reasons = (["组合因子已超线，但本候选不增加超线因子暴露"] if factor_breaches else ["组合集中度与四项因子均未超线"])
        status = "factor_resonance_high_risk" if len(factor_breaches) >= 2 else ("factor_resonance" if factor_breaches else "clear")
    return {
        "ts_code": code, "role": "candidate", "status": status, "action": action, "evaluated": True,
        "candidate_value_rmb": round(value, 2), "post_position_count": len(after), "same_sw_l2": same,
        "factor_exposures": factors, "reasons": reasons, "missing_fields": [],
    }


def commit_candidate(context: dict, projection: dict) -> None:
    """Commit only a permitted allocation; blocked candidates never consume cash/exposure."""
    if projection.get("action") not in {"allow", "none"}:
        return
    value = _finite_number(projection.get("candidate_value_rmb"), minimum=0.0)
    code = str(projection.get("ts_code") or "")
    if value is None or value <= 0 or not code:
        return
    context["committed"].append({"ts_code": code, "value_rmb": value,
                                 "fact": context["facts"].get(code, {"as_of": context["as_of"]})})


def final_summary(context: dict) -> dict:
    """Summarize the actual final holdings after blocked candidates were excluded."""
    assets = list(context["existing"]) + list(context["committed"])
    as_of = str(context["as_of"])
    if len(assets) < 2:
        return {
            "as_of": as_of, "status": "not_applicable", "positions_count": len(assets),
            "industry_exposures": [], "factor_exposures": [], "missing_fields": [],
            "daily_manual_review_required": False, "holding_single_position_cap_multiplier": 1.0,
            "reasons": ["最终持仓不足2只，M5.5B不适用"],
        }
    missing = _missing_fields(assets, as_of)
    if missing:
        return {
            "as_of": as_of, "status": "manual_review_required", "positions_count": len(assets),
            "industry_exposures": [], "factor_exposures": [], "missing_fields": missing,
            "daily_manual_review_required": True, "holding_single_position_cap_multiplier": 1.0,
            "reasons": ["组合事实不完整，不能将未核查当作无风险"],
        }
    values = _factor_values(assets)
    factors = _factor_rows(values, {}, assets[0]["fact"])
    for row in factors:
        row.pop("candidate_adds_exposure", None)
    breaches = [row for row in factors if row["over_threshold"]]
    industries = _industry_exposures(assets)
    over_industries = [row for row in industries if row["over_threshold"]]
    if len(breaches) >= 2:
        status = "factor_resonance_high_risk"
    elif breaches:
        status = "factor_resonance"
    elif over_industries:
        status = "concentration_over_cap"
    else:
        status = "clear"
    high = status == "factor_resonance_high_risk"
    return {
        "as_of": as_of, "status": status, "positions_count": len(assets),
        "industry_exposures": industries, "factor_exposures": factors, "missing_fields": [],
        "daily_manual_review_required": high,
        "holding_single_position_cap_multiplier": HIGH_RISK_HOLDING_CAP_MULTIPLIER if high else 1.0,
        "reasons": ([f"两项及以上因子超线：组合因子共振高危，持仓单只上限临时下调{_high_risk_cap_reduction_pct()}%，每日人工复核"] if high
                    else (["存在单项因子超线：不新增同方向暴露"] if breaches
                          else (["存在SW L2集中度超线：不新增同业暴露"] if over_industries
                                else ["组合集中度与四项因子均未超线"]))),
    }
