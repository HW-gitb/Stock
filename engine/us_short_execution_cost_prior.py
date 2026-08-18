# -*- coding: utf-8 -*-
"""One offline US-short execution-cost prior used by the existing cost consumers."""
from __future__ import annotations

import math


COMMISSION_FEE = 0.001
SLIPPAGE_BPS = 0.0
_MAX_BARS = 20
_MIN_PAIRS = 15
_MAX_ONE_WAY_FRACTION = 0.01
_SPREAD_KEYS = frozenset({"round_trip_spread_fraction", "spread_source"})


class ExecutionCostPriorError(ValueError):
    """The arrived execution-cost inputs cannot support a cost decision."""


def _finite_number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _positive(value):
    number = _finite_number(value)
    return number if number is not None and number > 0.0 else None


def _usable_bars(bars):
    if not isinstance(bars, list):
        return []
    out = []
    for bar in bars[-_MAX_BARS:]:
        if not isinstance(bar, dict):
            continue
        high, low, close, volume = (_positive(bar.get(key)) for key in ("high", "low", "close", "volume"))
        if (high is not None and low is not None and close is not None and volume is not None
                and low <= close <= high):
            out.append((high, low, close))
    return out


def _chl_spread(bars):
    valid = _usable_bars(bars)
    if len(valid) - 1 < _MIN_PAIRS:
        return None
    eta = [(math.log(high) + math.log(low)) / 2.0 for high, low, _ in valid]
    closes = [math.log(close) for _, _, close in valid]
    samples = [(closes[index] - eta[index]) * (closes[index] - eta[index + 1])
               for index in range(len(valid) - 1)]
    if any(not math.isfinite(value) for value in samples):
        return None
    ordered = sorted(samples)
    ordered[0] = ordered[1] = ordered[2]
    ordered[-1] = ordered[-2] = ordered[-3]
    mean = sum(ordered) / len(ordered)
    spread = math.sqrt(max(4.0 * mean, 0.0))
    return spread if math.isfinite(spread) and spread > 0.0 else None


def _adv_spread(bars, adv_usd):
    adv = _positive(adv_usd)
    price = None
    if isinstance(bars, list):
        for bar in bars[-_MAX_BARS:]:
            if isinstance(bar, dict):
                candidate = _positive(bar.get("close"))
                if candidate is not None:
                    price = candidate
    if adv is None or price is None or adv < 5_000_000.0:
        return None, "unavailable"
    if adv >= 100_000_000.0:
        bucket_bps = 2.0
    elif adv >= 25_000_000.0:
        bucket_bps = 5.0
    elif adv >= 10_000_000.0:
        bucket_bps = 12.0
    else:
        bucket_bps = 25.0
    one_way = max(bucket_bps / 10000.0, 0.005 / price)
    if not math.isfinite(one_way) or one_way > _MAX_ONE_WAY_FRACTION:
        return None, "unavailable_too_wide"
    return 2.0 * one_way, "adv_bucket_v1"


def build_execution_cost_prior(bars, *, adv_usd):
    """Return the full round-trip spread fraction and its honest source."""
    chl = _chl_spread(bars)
    if chl is not None:
        if chl / 2.0 <= _MAX_ONE_WAY_FRACTION:
            return {"round_trip_spread_fraction": chl, "spread_source": "modeled_chl_winsor_v1"}
        return {"round_trip_spread_fraction": None, "spread_source": "unavailable_too_wide"}
    spread, source = _adv_spread(bars, adv_usd)
    return {"round_trip_spread_fraction": spread, "spread_source": source}


def usable_spread_fraction(prior):
    if not isinstance(prior, dict) or set(prior) != _SPREAD_KEYS:
        raise ExecutionCostPriorError("execution_cost_prior is missing or malformed")
    fraction = _finite_number(prior.get("round_trip_spread_fraction"))
    source = prior.get("spread_source")
    if (fraction is None or fraction < 0.0 or not isinstance(source, str) or not source.strip()
            or source.startswith("unavailable")):
        raise ExecutionCostPriorError("execution spread prior is unavailable")
    return fraction, source


def dollar_costs(prior, *, shares, reference_price):
    """Convert one usable round-trip spread prior into the existing dollar-cost shape."""
    if isinstance(shares, bool) or not isinstance(shares, int) or shares < 1:
        raise ExecutionCostPriorError("shares must be a positive integer")
    price = _positive(reference_price)
    if price is None:
        raise ExecutionCostPriorError("reference_price must be positive")
    fraction, _source = usable_spread_fraction(prior)
    notional = shares * price
    return {
        "commission_round_trip": notional * COMMISSION_FEE,
        "slippage_dollars": notional * SLIPPAGE_BPS / 10000.0,
        "spread_dollars": notional * fraction,
    }


__all__ = [
    "COMMISSION_FEE",
    "SLIPPAGE_BPS",
    "ExecutionCostPriorError",
    "build_execution_cost_prior",
    "dollar_costs",
    "usable_spread_fraction",
]
