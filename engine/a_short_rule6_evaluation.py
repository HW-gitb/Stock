"""Pure, fail-closed evaluators for the machine-computable A-short Rule6 checks.

Each function returns only ``pass``, ``fail``, or ``unknown``.  ``unknown`` is
deliberate: an incomplete provider payload must never be converted to a clean
Rule6 result.
"""

from __future__ import annotations

from math import isfinite
from typing import Mapping, Sequence

from engine.a_short_rule6_contract import RULE6_CONDITIONAL_NA_REASONS


# Frozen from skills/a_short_analysis/reference/v14.2_spec.md Rule 6.  The
# schema-bound preset mirrors this map; do not tune these values to outcomes.
RULE6_V142_THRESHOLDS = {
    "holder_below_5pct_after_ratio_lt_pct": 5.0,
    "iv_nobuild_percentile_gt": 90.0,
    "volume_stall_lookback_days": 5,
    "volume_stall_latest_volume_multiple_gt": 2.0,
    "volume_stall_pct_change_lt_pct": 2.0,
    "volume_stall_close_range_fraction_lte": 1.0 / 3.0,
    "cash_debt_asset_ratio_gt": 0.25,
    "margin_extreme_lookback_days": 10,
    "margin_extreme_growth_gt": 0.20,
    "margin_extreme_price_gain_lt": 0.05,
    "block_trade_lookback_days": 10,
    "block_trade_discount_gt": 0.07,
    "block_trade_discounted_trade_count_gte": 2,
    "block_trade_discounted_amount_cny_gt": 100_000_000.0,
    "short_selling_lookback_days": 5,
    "short_selling_balance_growth_gt": 1.0,
    "ar_growth_consecutive_quarters": 2,
    "ar_growth_to_revenue_growth_min": 2.0,
    "contract_liability_growth_to_ar_growth_min": 0.80,
}


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if isfinite(value) else None


def _result(status: str, metrics: dict | None = None, notes: str | None = None) -> dict:
    if status not in {"pass", "fail", "unknown", "not_applicable"}:
        raise ValueError(f"unsupported Rule6 evaluation status: {status}")
    return {
        "status": status,
        "severity": "hard_veto" if status == "fail" else ("watch" if status == "unknown" else "none"),
        "metrics": dict(metrics or {}),
        "notes": notes,
    }


def _valid_date8(value, as_of: str | None = None) -> bool:
    text = str(value or "")
    if len(text) != 8 or not text.isdigit():
        return False
    return as_of is None or text <= str(as_of)


def evaluate_holder_below_5pct(events: Sequence[Mapping], as_of: str) -> dict:
    """Check disclosed decreases that leave a holder below the 5% threshold."""
    if not isinstance(events, Sequence):
        return _result("unknown", notes="holder data unavailable")
    for event in events:
        if not isinstance(event, Mapping):
            return _result("unknown", notes="holder event malformed")
        if not _valid_date8(event.get("ann_date"), as_of):
            return _result("unknown", notes="holder event ann_date invalid or after as_of")
        if str(event.get("in_de") or "") != "DE":
            continue
        after_ratio = _number(event.get("after_ratio"))
        if after_ratio is None:
            return _result("unknown", notes="holder event missing after_ratio")
        if after_ratio < RULE6_V142_THRESHOLDS["holder_below_5pct_after_ratio_lt_pct"]:
            return _result("fail", {"after_ratio_pct": after_ratio, "ann_date": str(event["ann_date"])})
    return _result("pass", {"event_count": len(events)})


def evaluate_volume_stall(rows_desc: Sequence[Mapping]) -> dict:
    """Five-day-average volume stall: >2x volume, <2% rise, close in lower third."""
    expected = RULE6_V142_THRESHOLDS["volume_stall_lookback_days"] + 1
    if not isinstance(rows_desc, Sequence) or len(rows_desc) != expected:
        return _result("unknown", notes=f"need exactly {expected} daily rows")
    latest, history = rows_desc[0], rows_desc[1:]
    if not all(isinstance(row, Mapping) for row in rows_desc):
        return _result("unknown", notes="daily row malformed")
    latest_vol = _number(latest.get("vol"))
    latest_pct = _number(latest.get("pct_chg"))
    high, low, close = (_number(latest.get(key)) for key in ("high", "low", "close"))
    history_volumes = [_number(row.get("vol")) for row in history]
    if (latest_vol is None or latest_pct is None or high is None or low is None or close is None
            or any(value is None for value in history_volumes) or high <= low):
        return _result("unknown", notes="daily volume/price/range field incomplete")
    average_vol = sum(history_volumes) / len(history_volumes)
    lower_fraction = (close - low) / (high - low)
    hit = (
        latest_vol > average_vol * RULE6_V142_THRESHOLDS["volume_stall_latest_volume_multiple_gt"]
        and latest_pct < RULE6_V142_THRESHOLDS["volume_stall_pct_change_lt_pct"]
        and lower_fraction <= RULE6_V142_THRESHOLDS["volume_stall_close_range_fraction_lte"]
    )
    return _result(
        "fail" if hit else "pass",
        {"latest_vol": latest_vol, "average_prior_5d_vol": average_vol,
         "pct_chg": latest_pct, "close_range_fraction": lower_fraction},
    )


def evaluate_margin_extreme_accumulation(rzye_latest, rzye_oldest, price_latest, price_oldest,
                                         is_margin_eligible: bool | None = None) -> dict:
    """10-day financing growth >20% while price gain is below 5%.

    ``is_margin_eligible=False`` means the producer positively established the
    stock is not a margin target (absent from a *fetched* margin universe), so
    the rule does not apply.  ``None`` (universe unknown / fetch failed) keeps
    the fail-closed ``unknown`` path below -- a fetch failure never disables the
    check by masquerading as non-eligibility.
    """
    if is_margin_eligible is False:
        return _result("not_applicable", {"margin_eligible": False},
                       RULE6_CONDITIONAL_NA_REASONS["rule6_margin_extreme_accumulation"])
    latest, oldest, current_price, old_price = (
        _number(value) for value in (rzye_latest, rzye_oldest, price_latest, price_oldest)
    )
    if None in (latest, oldest, current_price, old_price) or oldest <= 0 or old_price <= 0:
        return _result("unknown", notes="margin or price baseline incomplete")
    margin_growth = (latest - oldest) / oldest
    price_gain = (current_price - old_price) / old_price
    hit = (margin_growth > RULE6_V142_THRESHOLDS["margin_extreme_growth_gt"]
           and price_gain < RULE6_V142_THRESHOLDS["margin_extreme_price_gain_lt"])
    return _result("fail" if hit else "pass", {
        "margin_growth": margin_growth,
        "price_gain": price_gain,
    })


def evaluate_short_selling_surge(rqye_latest, rqye_oldest, hedge_announcement_status: str | None,
                                 is_margin_eligible: bool | None = None) -> dict:
    """5-day short-balance surge, without guessing the required hedge-announcement leg.

    ``is_margin_eligible=False`` (positively non-margin) makes the rule not
    applicable; ``None`` (universe unknown) keeps the fail-closed ``unknown``.
    """
    if is_margin_eligible is False:
        return _result("not_applicable", {"margin_eligible": False},
                       RULE6_CONDITIONAL_NA_REASONS["rule6_short_selling_surge"])
    latest, oldest = (_number(value) for value in (rqye_latest, rqye_oldest))
    if latest is None or oldest is None or oldest < 0:
        return _result("unknown", notes="short-selling balance baseline incomplete")
    if oldest == 0:
        if latest == 0:
            return _result("pass", {"short_balance_growth": 0.0})
        return _result("unknown", notes="short-selling growth denominator is zero")
    growth = (latest - oldest) / oldest
    if growth <= RULE6_V142_THRESHOLDS["short_selling_balance_growth_gt"]:
        return _result("pass", {"short_balance_growth": growth})
    if hedge_announcement_status == "no_hedge_announcement":
        return _result("fail", {"short_balance_growth": growth})
    if hedge_announcement_status == "hedge_announcement":
        return _result("pass", {"short_balance_growth": growth})
    return _result("unknown", {"short_balance_growth": growth},
                   "hedge-announcement leg not structurally verified")


def evaluate_cash_debt_double_high(record: Mapping | None, as_of: str) -> dict:
    """Latest PIT-safe balance sheet: cash and short debt each exceed 25% of assets."""
    if not isinstance(record, Mapping):
        return _result("unknown", notes="balancesheet record unavailable")
    if not _valid_date8(record.get("ann_date"), as_of) or not _valid_date8(record.get("end_date"), as_of):
        return _result("unknown", notes="balancesheet PIT date invalid or after as_of")
    money_cap, st_borr, total_assets = (_number(record.get(key)) for key in ("money_cap", "st_borr", "total_assets"))
    if None in (money_cap, st_borr, total_assets) or total_assets <= 0:
        return _result("unknown", notes="balancesheet cash/debt/assets field incomplete")
    cash_ratio, debt_ratio = money_cap / total_assets, st_borr / total_assets
    hit = (cash_ratio > RULE6_V142_THRESHOLDS["cash_debt_asset_ratio_gt"]
           and debt_ratio > RULE6_V142_THRESHOLDS["cash_debt_asset_ratio_gt"])
    return _result("fail" if hit else "pass", {
        "cash_to_assets": cash_ratio, "short_debt_to_assets": debt_ratio,
        "observed_at": str(record["ann_date"]), "period": str(record["end_date"]),
    })


def evaluate_block_trade_discount(window_dates: Sequence[str], records_by_date: Mapping[str, Sequence[Mapping] | None]) -> dict:
    """At least two >7% discounted block trades whose combined value exceeds CNY 100m."""
    if not isinstance(window_dates, Sequence) or len(window_dates) != RULE6_V142_THRESHOLDS["block_trade_lookback_days"]:
        return _result("unknown", notes="block-trade window coverage incomplete")
    qualifying_count, qualifying_amount = 0, 0.0
    for trade_date in window_dates:
        rows = records_by_date.get(str(trade_date)) if isinstance(records_by_date, Mapping) else None
        if rows is None or not isinstance(rows, Sequence):
            return _result("unknown", notes=f"block-trade source unavailable for {trade_date}")
        for row in rows:
            if not isinstance(row, Mapping):
                return _result("unknown", notes=f"block-trade row malformed for {trade_date}")
            price, vol, close = (_number(row.get(key)) for key in ("price", "vol", "close"))
            if None in (price, vol, close) or price <= 0 or vol < 0 or close <= 0:
                return _result("unknown", notes=f"block-trade price/vol/close incomplete for {trade_date}")
            discount = (close - price) / close
            if discount > RULE6_V142_THRESHOLDS["block_trade_discount_gt"]:
                qualifying_count += 1
                # Tushare block_trade.vol is in 10k shares; price * vol * 10k is CNY.
                qualifying_amount += price * vol * 10_000.0
    hit = (qualifying_count >= RULE6_V142_THRESHOLDS["block_trade_discounted_trade_count_gte"]
           and qualifying_amount > RULE6_V142_THRESHOLDS["block_trade_discounted_amount_cny_gt"])
    return _result("fail" if hit else "pass", {
        "discounted_trade_count": qualifying_count,
        "discounted_amount_cny": qualifying_amount,
    })


def evaluate_ar_growth_gt_revenue_growth(period_revenue_yoy_pct: Sequence[Mapping],
                                         balance_by_period: Mapping[str, Mapping], as_of: str) -> dict:
    """Two consecutive YoY AR-growth breaches, excluding contract-liability-led growth."""
    required_count = RULE6_V142_THRESHOLDS["ar_growth_consecutive_quarters"]
    if not isinstance(period_revenue_yoy_pct, Sequence) or len(period_revenue_yoy_pct) != required_count:
        return _result("unknown", notes="need exactly two revenue-growth periods")
    quarter_hits, metrics = [], {}
    for index, item in enumerate(period_revenue_yoy_pct):
        if not isinstance(item, Mapping):
            return _result("unknown", notes="revenue-growth row malformed")
        period = str(item.get("period") or "")
        ann_date = item.get("ann_date")
        revenue_yoy = _number(item.get("revenue_yoy_pct"))
        if (not _valid_date8(period, as_of) or not _valid_date8(ann_date, as_of)
                or revenue_yoy is None):
            return _result("unknown", notes="revenue-growth PIT data incomplete")
        prior_period = f"{int(period[:4]) - 1:04d}{period[4:]}"
        current, prior = balance_by_period.get(period), balance_by_period.get(prior_period)
        if not isinstance(current, Mapping) or not isinstance(prior, Mapping):
            return _result("unknown", notes=f"balancesheet pair missing for {period}")
        if (not _valid_date8(current.get("ann_date"), as_of)
                or not _valid_date8(prior.get("ann_date"), as_of)):
            return _result("unknown", notes=f"balancesheet PIT date invalid for {period}")
        ar_now, ar_prior, cl_now, cl_prior = (
            _number(current.get("accounts_receiv")), _number(prior.get("accounts_receiv")),
            _number(current.get("contract_liab")), _number(prior.get("contract_liab")),
        )
        if None in (ar_now, ar_prior, cl_now, cl_prior) or ar_prior <= 0 or cl_prior <= 0:
            return _result("unknown", notes=f"AR/contract-liability field incomplete for {period}")
        ar_growth_pct = (ar_now - ar_prior) / ar_prior * 100.0
        contract_growth_pct = (cl_now - cl_prior) / cl_prior * 100.0
        exempt = contract_growth_pct >= (ar_growth_pct * RULE6_V142_THRESHOLDS["contract_liability_growth_to_ar_growth_min"])
        quarter_hit = (
            ar_growth_pct > revenue_yoy * RULE6_V142_THRESHOLDS["ar_growth_to_revenue_growth_min"]
            and not exempt
        )
        quarter_hits.append(quarter_hit)
        metrics[f"period_{index}"] = period
        metrics[f"revenue_ann_date_{index}"] = str(ann_date)
        metrics[f"ar_growth_pct_{index}"] = ar_growth_pct
        metrics[f"revenue_growth_pct_{index}"] = revenue_yoy
        metrics[f"contract_liability_growth_pct_{index}"] = contract_growth_pct
        metrics[f"contract_liability_exempt_{index}"] = exempt
    return _result("fail" if all(quarter_hits) else "pass", metrics)


def materialize_50etf_iv_rule6_check(checks: object, iv_percentile) -> list:
    """Replace only Rule6's IV placeholder from the validated weekly IV feed.

    A missing or malformed IV percentile remains ``unknown``.  Missing or
    duplicate Rule6 records are deliberately left for the completion gate to
    reject rather than being silently repaired here.
    """
    if not isinstance(checks, list):
        return []
    iv = _number(iv_percentile)
    output = []
    for item in checks:
        if not isinstance(item, Mapping) or item.get("id") != "rule6_50etf_iv":
            output.append(dict(item) if isinstance(item, Mapping) else item)
            continue
        updated = dict(item)
        metrics = dict(updated.get("metrics") or {})
        metrics["iv_percentile_252d"] = iv
        if iv is None:
            updated.update(status="unknown", severity="watch", metrics=metrics,
                           notes="50ETF IV feed unavailable or malformed")
        else:
            failed = iv > RULE6_V142_THRESHOLDS["iv_nobuild_percentile_gt"]
            updated.update(status="fail" if failed else "pass",
                           severity="hard_veto" if failed else "none",
                           metrics=metrics,
                           notes="Rule3 50ETF IV percentile")
        output.append(updated)
    return output
