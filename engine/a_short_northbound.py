"""Shared structured predicate for the A-short northbound market gate."""
from __future__ import annotations

import math
import numbers


NORTHBOUND_CSI300_SILENCE_THRESHOLD_PCT = -10.0
# Historical trigger frequency is not yet evidenced by a producer-backed
# lookback.  Keep the structured predicate available for comparison/tests, but
# do not let the current producer change a weekly production decision.
NORTHBOUND_MARKET_GATE_PRODUCTION_EFFECT_ENABLED = False


def _finite_number(value) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, numbers.Real)
        and math.isfinite(float(value))
    )


def classify_northbound_status(net_flow_5d) -> str:
    """Classify a CNY five-day flow without turning missing data into flat."""
    if not _finite_number(net_flow_5d):
        return "unknown"
    if float(net_flow_5d) < 0:
        return "outflow"
    if float(net_flow_5d) > 0:
        return "inflow"
    return "flat"


def should_block_new_entries(net_flow_5d, status: str, csi300_pct_change_window) -> bool:
    """Return the existing two-input silence predicate, fail-closed on missing facts."""
    return (
        status == "outflow"
        and _finite_number(net_flow_5d)
        and _finite_number(csi300_pct_change_window)
        and float(net_flow_5d) < 0
        and float(csi300_pct_change_window) < NORTHBOUND_CSI300_SILENCE_THRESHOLD_PCT
    )
