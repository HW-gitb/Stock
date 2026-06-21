# -*- coding: utf-8 -*-
"""US-short macro-cluster concentration (§8 宏观集群集中度) — pseudo-diversification soft warning.

Design authority: docs/us_short_system_design.md §8; frozen warning vocab + v1 policy + high-warning
effects in presets/us_short_macro_cluster_governance_20260620.json (LOADED here).

The same-theme cap can't stop "different themes, one macro bet" (e.g. AI 存储 / 半导体 / AI 基建 /
数据中心核电 all in `ai_complex`). v1 is SOFT only — NO hard cap: `macro_cluster_warning_level` ∈
{none, elevated, high} from the cluster's exposure fraction; `high` → soft effects (risk_tag + lower
action_confidence + shrink model_position_size folded into 削减叠法 step ③ with NO extra compound +
report banner). The `macro_cluster` tag vocabulary is OPEN (not a closed enum). A hard cap is a §13.1
#31 forward item, not v1.

Frac thresholds are §13.1 #31 forward priors (module constants, not caller-overridable). A malformed /
out-of-domain exposure fails CLOSED to a conservative soft warning (`elevated`) — never the lenient
`none` for an unmeasurable concentration. `macro_cluster_high_effects` returns a COPY. Pure/offline; no
provider, no A-share crossing; §8 sizing consumes the warning + (soft) size adjustment.
"""
import copy
import json
import math
from pathlib import Path

_GOV_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_macro_cluster_governance_20260620.json"
_GOV = json.loads(_GOV_PATH.read_text(encoding="utf-8"))

WARNING_LEVELS = tuple(_GOV["warning_levels"])         # (none, elevated, high)
NO_HARD_CAP = bool(_GOV["v1_policy"]["no_hard_cap"])   # v1 = soft only

# §13.1 #31 forward priors (NOT frozen const), module constants.
HIGH_FRAC = 0.40        # cluster exposure >= this fraction → high
ELEVATED_FRAC = 0.25    # cluster exposure >= this fraction → elevated


def _finite_number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    return float(x) if math.isfinite(x) else None


def classify_macro_cluster_warning(exposure_frac):
    """§8 macro_cluster_warning_level from a cluster's exposure fraction (of total position). exposure ≥
    HIGH_FRAC → high; ≥ ELEVATED_FRAC → elevated; else none. v1 is SOFT only (no hard cap). A malformed /
    out-of-domain (non-number / bool / NaN / <0 / >1) exposure fails CLOSED to `elevated` — a conservative
    soft warning for a concentration it cannot measure, never the lenient `none`."""
    f = _finite_number(exposure_frac)
    if f is None or f < 0.0 or f > 1.0:
        return "elevated"                # fail closed: unmeasurable concentration → conservative soft warning
    if f >= HIGH_FRAC:
        return "high"
    if f >= ELEVATED_FRAC:
        return "elevated"
    return "none"


def macro_cluster_high_effects():
    """Frozen §8 high-warning SOFT effects (returned as a COPY). v1 = soft only: risk_tag + lower
    action_confidence + shrink model_position_size (folds into 削减叠法 step ③ '取最狠的一个', NO extra
    compound) + report banner; NO hard cap."""
    return copy.deepcopy(_GOV["high_warning_effects"])


def macro_cluster_effects_for(warning_level):
    """Soft effects for a warning level: `high` → the frozen high-warning soft effects; `elevated` /
    `none` → no size effect (elevated is a banner/flag only in v1). Raises ValueError on an unknown level
    (fail closed). v1 NEVER applies a hard cap."""
    if warning_level not in WARNING_LEVELS:
        raise ValueError(f"unknown macro_cluster_warning_level {warning_level!r}")
    if warning_level == "high":
        return {**macro_cluster_high_effects(), "hard_cap": False}   # v1 invariant: hard_cap stays False regardless of preset
    return {"hard_cap": False, "risk_tag": warning_level == "elevated", "shrink_model_position_size": False,
            "report_banner": warning_level == "elevated"}
