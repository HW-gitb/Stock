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

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_result_effects import extend_result_effects
from engine.us_short_weekend_sizing import size_rows

_GOV_PATH = Path(__file__).resolve().parent.parent / "presets" / "us_short_macro_cluster_governance_20260620.json"
_GOV = json.loads(_GOV_PATH.read_text(encoding="utf-8"))

WARNING_LEVELS = tuple(_GOV["warning_levels"])         # (none, elevated, high)
NO_HARD_CAP = bool(_GOV["v1_policy"]["no_hard_cap"])   # v1 = soft only
HIGH_SIZE_MULTIPLIER = float(_GOV["high_warning_effects"]["size_multiplier"])
HIGH_CONFIDENCE_CAP = float(_GOV["high_warning_effects"]["confidence_cap"])
UNKNOWN_CLUSTER = "unclassified_conservative"

# §13.1 #31 forward priors (NOT frozen const), module constants.
HIGH_FRAC = 0.40        # cluster exposure >= this fraction → high
ELEVATED_FRAC = 0.25    # cluster exposure >= this fraction → elevated


def _finite_number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    try:
        return float(x) if math.isfinite(x) else None
    except OverflowError:                       # huge int (e.g. 10**400) → not finite (mirror weekend_cash guard)
        return None


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


class MacroClusterError(ValueError):
    """Macro-cluster source facts or two-pass sizing inputs are malformed."""


def _positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _cluster(value):
    return value.strip().casefold() if isinstance(value, str) and value.strip() else None


def _provisional_amount(row):
    sizing = row.get("sizing") if isinstance(row, dict) else None
    fields = row.get("price", {}).get("action_fields", {}) if isinstance(row, dict) else {}
    shares = sizing.get("desired_model_shares") if isinstance(sizing, dict) and sizing.get("status") == "sized" else None
    entry = fields.get("valid_entry_high") if isinstance(fields, dict) else None
    if not (_positive_int(shares) and _finite_number(entry) is not None and float(entry) > 0.0):
        return None
    try:
        amount = float(shares) * float(entry)
    except OverflowError:                       # huge share count → unmeasurable (fail closed)
        return None
    return amount if math.isfinite(amount) and amount > 0.0 else None


def apply_macro_cluster_two_pass(result, *, sizing_context, existing_positions, as_of):
    """Run one side-effect-free provisional sizing pass, append macro effects, then size once from original rows.

    ``existing_positions`` is a private in-memory projection with exact rows
    ``{ticker, shares, mark_price, macro_cluster}``.  It is never persisted here.  Missing/unmeasurable existing
    exposure makes every row conservatively ``elevated`` and the downstream portfolio-capacity gate remains
    responsible for blocking new builds.
    """
    if not (isinstance(result, dict) and isinstance(result.get("rows"), list)):
        raise MacroClusterError("result 须为含 rows 的 dict")
    if not isinstance(existing_positions, list):
        raise MacroClusterError("existing_positions 须为 list")
    bucket = sizing_context.get("short_bucket_dollars") if isinstance(sizing_context, dict) else None
    if _finite_number(bucket) is None or float(bucket) <= 0.0:
        raise MacroClusterError("sizing_context.short_bucket_dollars 须为正有限数")
    bucket = float(bucket)
    provisional = size_rows(result, sizing_context=sizing_context)
    exposure, measurable = {}, True
    seen_positions = set()
    for position in existing_positions:
        if not (isinstance(position, dict)
                and set(position) == {"ticker", "shares", "mark_price", "macro_cluster"}):
            raise MacroClusterError("existing_positions[] 字段漂移")
        ticker = canonical_us_ticker(position["ticker"])
        cluster = _cluster(position["macro_cluster"])
        shares, mark = position["shares"], _finite_number(position["mark_price"])
        if ticker is None or ticker in seen_positions:
            raise MacroClusterError("existing_positions 含非法/重复 ticker")
        seen_positions.add(ticker)
        if not (_positive_int(shares) and mark is not None and mark > 0.0 and cluster is not None):
            measurable = False
            continue
        try:
            amount = float(shares) * mark
        except OverflowError:                   # huge share count → unmeasurable (mirror weekend_cash guard)
            amount = float("inf")
        if not math.isfinite(amount) or amount <= 0.0:
            measurable = False
            continue
        exposure[cluster] = exposure.get(cluster, 0.0) + amount

    provisional_by_ticker = {}
    for row in provisional["rows"]:
        ticker = canonical_us_ticker(row.get("ticker")) if isinstance(row, dict) else None
        if ticker is None or ticker in provisional_by_ticker:
            raise MacroClusterError("provisional rows 含非法/重复 ticker")
        provisional_by_ticker[ticker] = row
        if row.get("final_action") != "建仓":
            continue
        theme = row.get("theme_context")
        cluster = _cluster(theme.get("macro_cluster")) if isinstance(theme, dict) else None
        amount = _provisional_amount(row)
        if cluster is None or amount is None:
            measurable = False
            continue
        exposure[cluster] = exposure.get(cluster, 0.0) + amount

    effects_by_ticker, macro_by_ticker = {}, {}
    for row in result["rows"]:
        ticker = canonical_us_ticker(row.get("ticker")) if isinstance(row, dict) else None
        theme = row.get("theme_context") if isinstance(row, dict) else None
        cluster = _cluster(theme.get("macro_cluster")) if isinstance(theme, dict) else None
        evidence = theme.get("evidence_ref") if isinstance(theme, dict) else None
        if ticker is None or ticker not in provisional_by_ticker:
            raise MacroClusterError("result/provisional ticker identity 不一致")
        if cluster is None:
            warning, frac = None, None
        elif not measurable:
            warning, frac = "elevated", None
        else:
            # §8 defines exposure_frac against the US-short bucket, not against only the currently invested
            # names (which would make a lone tiny position look 100% concentrated).  Over-bucket accounts stay
            # high without crashing protective holding output; the separate capacity stage reports the overage.
            frac = min(1.0, exposure.get(cluster, 0.0) / bucket)
            warning = "elevated" if cluster == UNKNOWN_CLUSTER else classify_macro_cluster_warning(frac)
        records = []
        if warning in {"elevated", "high"}:
            if not isinstance(evidence, dict):
                raise MacroClusterError(f"{ticker}: macro warning 缺 theme evidence_ref")
            is_build = row.get("final_action") == "建仓"
            records.append({
                "source": "macro_cluster:" + warning,
                "evidence_ref": evidence,
                "risk_tags": ["macro_cluster:" + warning],
                "trigger_conditions": [],
                "invalid_conditions": (["macro_cluster_unclassified"]
                                       if cluster == UNKNOWN_CLUSTER else []),
                "size_multiplier": HIGH_SIZE_MULTIPLIER if warning == "high" and is_build else None,
                "confidence_cap": HIGH_CONFIDENCE_CAP if warning == "high" else None,
                "action_override": None,
            })
        effects_by_ticker[ticker] = records
        macro_by_ticker[ticker] = {"macro_cluster": cluster, "macro_cluster_exposure_frac": frac,
                                   "macro_cluster_warning_level": warning}

    macro_effected = extend_result_effects(result, effects_by_ticker=effects_by_ticker, as_of=as_of)
    final = size_rows(macro_effected, sizing_context=sizing_context)
    final_rows = []
    for row in final["rows"]:
        ticker = row["ticker"]
        provisional_row = provisional_by_ticker[ticker]
        provisional_sizing = provisional_row.get("sizing")
        final_sizing = row.get("sizing")
        provisional_shares = (provisional_sizing.get("desired_model_shares")
                              if isinstance(provisional_sizing, dict) else 0) or 0
        final_shares = (final_sizing.get("desired_model_shares")
                        if isinstance(final_sizing, dict) else 0) or 0
        if not (isinstance(provisional_shares, int) and not isinstance(provisional_shares, bool)
                and isinstance(final_shares, int) and not isinstance(final_shares, bool)
                and provisional_shares >= final_shares >= 0):
            raise MacroClusterError(f"{ticker}: provisional/final share adjustment 非法")
        final_rows.append({**row, **macro_by_ticker[ticker],
                           "macro_cluster_size_adjustment": provisional_shares - final_shares})
    return {**final, "rows": final_rows, "macro_cluster_exposure_measurable": measurable}


def render_macro_cluster_banner(rows):
    """Aggregate the structured machine-row macro result; no caller-supplied free text is accepted."""
    if not isinstance(rows, list):
        raise MacroClusterError("rows 须为 list")
    clusters = {}
    for row in rows:
        if not isinstance(row, dict):
            raise MacroClusterError("macro banner row 须为 dict")
        level = row.get("macro_cluster_warning_level")
        cluster = _cluster(row.get("macro_cluster"))
        frac = row.get("macro_cluster_exposure_frac")
        if level not in WARNING_LEVELS or cluster is None:
            continue
        if level in {"elevated", "high"}:
            prior = clusters.get(cluster)
            value = None if frac is None else float(frac)
            if prior is not None and prior[:2] != (level, value):
                raise MacroClusterError("same macro cluster has conflicting warning output")
            # A high macro discount can push a provisional build below the executable minimum and turn its
            # final action into observe.  A positive size adjustment preserves that it was a build candidate;
            # do not make the banner under-count the very candidate the macro rule suppressed.
            is_build_candidate = (row.get("final_action") == "建仓"
                                  or row.get("macro_cluster_size_adjustment", 0) > 0)
            prior_count = prior[2] if prior is not None else 0
            clusters[cluster] = (level, value, prior_count + int(is_build_candidate))
    if not clusters:
        return ""
    parts = []
    for cluster, (level, frac, candidate_count) in sorted(clusters.items()):
        exposure = "unmeasurable" if frac is None else f"{frac:.1%}"
        parts.append(f"{cluster}={level}(建仓候选{candidate_count}个,暴露{exposure})")
    return "宏观集群提醒：" + "; ".join(parts) + "。"
