from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "analysis_input_minimal.json"


def load_minimal_analysis_input_payload() -> dict[str, Any]:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    payload["market"] = "A"
    payload["horizon"] = "short"
    payload["source"]["notes"] = ["synthetic fixture for tests; not real candidates"]
    payload["universe_summary"] = {
        "listed_count": None,
        "after_l0_count": None,
        "full_count": 2,
        "watch_count": 2,
        "final_count": 1,
        "excluded_counts": {
            "unlock": 0,
            "suspended": 0,
            "relisted": 0,
            "holder_reduction_veto_10d": 0,
        },
    }
    payload["market_context"] = {
        "trade_calendar": {
            "latest_trade_date": payload["trade_date"],
            "next_trade_date": None,
            "is_pre_holiday_window": False,
            "holiday_days_ahead": None,
        },
        "market_regime": {
            "status": "unknown",
            "confidence": "unknown",
            "position_cap_single_pct": None,
            "position_cap_total_pct": None,
            "min_reward_risk": None,
            "triggers": [],
        },
        "volatility": {
            "iv_symbol": "50ETF",
            "iv_value": None,
            "iv_percentile_252d": None,
            "iv_change_abs_1d_pctpt": None,
            "rule3_status": "unknown",
            "awakening_status": "unknown",
            "cash_reclaim_pct": None,
        },
        "breadth": {
            "limit_up_count": None,
            "limit_down_count": None,
            "limit_up_index_pct_change": None,
            "consecutive_board_height": None,
            "csi300_pct_change_window": None,
        },
        "liquidity": {
            "market_turnover_amount": None,
            "median_amount_20d": None,
        },
        "northbound": {
            "net_flow_5d": None,
            "status": "unknown",
        },
    }
    payload["account_context"] = {
        "mode": "new_entry",
        "available_cash": None,
        "total_equity": None,
        "current_gross_exposure": None,
        "positions": [],
    }
    payload["state_refs"] = {
        "positions": "state/a_short/positions.json",
        "veto_log": "state/a_short/veto_log.json",
        "circuit_breaker": "state/a_short/circuit_breaker.json",
        "execution_log": "state/a_short/execution_log.csv",
    }

    for candidate in payload["candidates"]:
        _normalize_candidate(candidate)
    return payload


def _normalize_candidate(candidate: dict[str, Any]) -> None:
    ts_code = str(candidate.get("ts_code") or "")
    candidate["exchange"] = "SZ" if ts_code.endswith(".SZ") else "SH"
    candidate["analysis_role"] = "watch"

    technical = candidate["technical"]
    technical.update({
        "pct_5d": None,
        "pct_20d": None,
        "pct_5d_n": None,
        "pct_20d_n": None,
        "pct_60d": None,
        "drawdown_20d": None,
        "avg_amount_5d": None,
        "avg_amount_20d": None,
        "moving_averages": {"ma5": None, "ma10": None, "ma20": None, "ma60": None},
        "direction_lock": "unknown",
    })
    technical["support"]["method"] = "technical"
    technical["resistance"]["method"] = "technical"
    technical["atr"].update({"atr_window": 14, "ex_rights_adjusted": True})

    candidate["capital_flow"] = {
        "moneyflow": {"big_order_ratio": None, "net_inflow_5d": None, "divergence_flag": None},
        "margin": {
            "balance": None,
            "balance_change_5d_pct": None,
            "balance_change_10d_pct": None,
            "balance_to_float_mv_pct": None,
            "extreme_accumulation": None,
        },
        "northbound": {
            "holding_ratio": None,
            "consecutive_net_sell_days": None,
            "net_sell_to_total_share_pct": None,
        },
        "block_trade": {
            "discount_trade_count_10d": None,
            "avg_discount_pct": None,
            "amount_10d": None,
        },
    }
    candidate["event_risk"] = {
        "rule6_checks": [],
        "regulatory": {
            "has_inquiry_or_concern_48h": None,
            "negative_depth": "pending_llm",
            "evidence": [],
        },
        "holder_reduction": {
            "active_plan": False,
            "completed_3m_pct_share": None,
            "completed_3m_amount": None,
            "reduce_penalty": None,
        },
        "unlock": {"unlock_pct": None, "unlock_date": None, "large_unlock_flag": False},
        "suspension": {"is_suspended": False, "recent_suspension_5d": None},
        "delisting": {
            "st_flag": False,
            "delisting_warning": False,
            "non_standard_audit": None,
            "negative_net_asset": None,
        },
    }
    candidate["catalyst"] = {
        "concepts": [],
        "concept_strength_score": candidate["scores"].get("cat_score"),
        "policy_news": [],
        "earnings": {"has_recent_report": None, "is_primary_catalyst": None},
        "time_window": "unknown",
    }
    candidate["liquidity"] = {
        "avg_amount_5d": None,
        "avg_amount_20d": None,
        "yesterday_amount": None,
        "spread_pct": None,
        "one_minute_capacity": None,
        "position_amount_cap": None,
        "split_order_required": None,
        "turnover_rate": None,
    }
    candidate["volatility"] = {
        "hv_252d": None,
        "iv_hv_ratio": None,
        "iv_hv_position_cut_pct": None,
    }
    candidate["analyst"] = {
        "coverage_count": None,
        "target_price_mean": None,
        "downgrade_count_1m": None,
        "target_below_current": None,
    }
    candidate["portfolio_impact"] = {
        "same_sw_l2_exposure_after_buy_pct": None,
        "factor_exposures": [
            {"factor": "sw_l2_industry", "value": None, "threshold": 40, "status": "unknown"}
        ],
        "correlation_action": "unknown",
    }
    candidate["derived_flags"].update({
        "has_crash_veto": False,
        "is_lock": False,
        "is_breakout": False,
    })
    for task in candidate["llm_tasks"]:
        if task.get("status") == "pending":
            task["status"] = "pending_llm"


def cloned_minimal_analysis_input_payload() -> dict[str, Any]:
    return deepcopy(load_minimal_analysis_input_payload())
