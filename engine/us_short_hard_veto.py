# -*- coding: utf-8 -*-
"""US-short hard-veto layering classifier (§5).

Design authority: docs/us_short_system_design.md §5 (tier table + §5.1a + §5.1b + §5.3);
frozen ladder/policy in presets/us_short_hard_veto_governance_20260620.json (consumed here).

Classifies per-stock risk signals into one severity tier of the frozen ladder
(entry_hard_veto > position_hard_veto > strong_downgrade > soft_risk_tag > shadow_record, +
'none'). Severity-max across all applicable signals. Three design rules are load-bearing and
adversarially tested:

  * §5.1a reliable file-type/status/price signals (delisting / halt / bankruptcy / OTC /
    critical-data-missing) → a real hard veto (entry_hard_veto for a candidate row,
    position_hard_veto for a holding row). A SEC offering is a hard veto ONLY when it is
    recent + active + material; a stale / inactive / small shelf is NOT (→ soft_risk_tag).
  * §5.1b semantic / news signals are advisory-first: `semantic_audit_unavailable` →
    downgrade + observe, never a hard block; a high-confidence adverse read → ≥ restricted
    (strong_downgrade), not clean — still NOT a v1 hard veto.
  * §5.3 never-solo: none of {高 SI, 网络热度, 单个技术指标, 目标价低于现价, 主题拥挤, 高波动}
    ALONE may produce a hard veto — alone they reach at most soft_risk_tag.

v1 §5.2 candidate hard-vetoes (good-data-bad-reaction etc.) are forward-gated (§13 #7) and not
escalated here. The §5.1a category set is this batch-2 classifier's contract (design prose, not
a locked vocab). Pure/offline, no provider call, no A-share crossing; the veto tier lands on
final_action / risk_tags downstream (§9 action_rank, a later slice) — not enforced here.
"""

# Frozen ladder (== preset veto_tiers), severity DESCENDING.
VETO_TIERS = ("entry_hard_veto", "position_hard_veto", "strong_downgrade", "soft_risk_tag", "shadow_record")
NONE = "none"
_TIER_SEV = {NONE: 0, "shadow_record": 1, "soft_risk_tag": 2, "strong_downgrade": 3,
             "position_hard_veto": 4, "entry_hard_veto": 5}

# Frozen per-tier effect text (== preset veto_tiers[].effect; a conformance test triangulates).
TIER_EFFECT = {
    "entry_hard_veto": "禁新建/加仓",
    "position_hard_veto": "持仓强制重评/减/清（不是沉默）",
    "strong_downgrade": "降优先级/仓位/可信度",
    "soft_risk_tag": "提示/小幅扣分",
    "shadow_record": "只记录、不影响输出",
}

# §5.1a reliable file-type/status/price triggers → hard veto (auto, reliable). Input key → label.
# Anchored to the design §5.1a category set (退市/停牌/破产/OTC/严重流动性/spread/关键数据缺失); a golden
# test asserts this covers the design-required set (not a self-referential loop over this tuple).
_RELIABLE_HARD = (("delisted", "退市"), ("halted", "停牌"), ("bankruptcy", "破产"),
                  ("otc", "OTC"), ("severe_liquidity", "流动性枯竭"), ("severe_spread", "严重spread"),
                  ("critical_data_missing", "关键数据缺失"))

# §5.3 must-not-solo signals (== the 6 preset must_not_solo_veto items, English input keys):
# 单独高 SI / 单独网络热度 / 单个技术指标 / 目标价低于现价 / 主题拥挤 / 高波动. Alone → at most soft_risk_tag.
MUST_NOT_SOLO_VETO = ("high_si", "web_heat", "single_tech_indicator",
                      "target_below_price", "theme_crowded", "high_vol")

_VALID_CONTEXTS = ("candidate", "holding")

# Frozen action_table `row_source` (§11.3/§11.5) → veto row context. A holding hard-risk MUST map to
# the holding tier, not silently to candidate; a conformance test asserts this covers exactly the
# frozen row_source enum so a new row_source can't silently mis-map.
_ROW_SOURCE_TO_CONTEXT = {
    "top15_candidate": "candidate",
    "holding_in_top15": "holding",
    "holding_pass2_only": "holding",
    "holding_account_only": "holding",
}


def row_source_to_context(row_source):
    """Map a frozen action_table `row_source` value → veto row context ('candidate'/'holding').
    Raises ValueError on an unknown row_source (fail closed — never a silent candidate fallback)."""
    try:
        return _ROW_SOURCE_TO_CONTEXT[row_source]
    except KeyError:
        raise ValueError(f"unknown row_source {row_source!r}; cannot map to a hard-veto row context")


def _max_tier(a, b):
    return a if _TIER_SEV[a] >= _TIER_SEV[b] else b


def classify_hard_veto(signals, row_context="candidate"):
    """signals = structured per-stock risk fields (booleans + optional `active_offering` /
    `semantic_audit` objects); row_context ∈ {'candidate', 'holding'}. Returns
    {veto_tier, effect, reasons, row_context}. Severity-max; §5.3 solo signals never exceed
    soft_risk_tag. Pure — no data fetch, no A-share path."""
    signals = signals or {}
    if row_context not in _VALID_CONTEXTS:   # fail closed: never silently treat a bad/holding context as candidate
        raise ValueError(f"row_context must be one of {_VALID_CONTEXTS}, got {row_context!r}; "
                         "map an action_table row_source via row_source_to_context() first")
    hard = "position_hard_veto" if row_context == "holding" else "entry_hard_veto"
    tier = NONE
    reasons = []

    # §5.1a reliable file-type/status/price hard vetoes
    for key, label in _RELIABLE_HARD:
        if signals.get(key):
            tier = _max_tier(tier, hard)
            reasons.append(f"5.1a:{label}")

    # §5.1a SEC offering: hard veto ONLY if recent + active + material; stale/inactive/small → tag only
    off = signals.get("active_offering")
    if off:
        if off.get("recency") == "recent" and off.get("status") == "active" and off.get("materiality") == "material":
            tier = _max_tier(tier, hard)
            reasons.append("5.1a:SEC增发(近期+已激活+重大)")
        else:
            tier = _max_tier(tier, "soft_risk_tag")
            reasons.append("5.1a:SEC增发(陈旧/未激活/小额→仅标签)")

    # §5.1b semantic (advisory-first): unavailable → downgrade+observe, NOT hard block;
    # high-confidence adverse → ≥ restricted (strong_downgrade), not clean — still not a v1 hard veto
    sem = signals.get("semantic_audit")
    if sem:
        if not sem.get("available"):
            tier = _max_tier(tier, "soft_risk_tag")
            reasons.append("5.1b:semantic_audit_unavailable(降级+观察,不硬否决)")
        elif sem.get("adverse") and sem.get("confidence") == "high":
            tier = _max_tier(tier, "strong_downgrade")
            reasons.append("5.1b:高可信不利语义(≥restricted,不clean)")
        elif sem.get("adverse"):
            tier = _max_tier(tier, "soft_risk_tag")
            reasons.append("5.1b:不利语义(低可信→仅标签)")

    # §5.3 never-solo: each solo signal may only ADD a soft_risk_tag (severity-max keeps any
    # reliable hard veto above), so a solo signal alone can never reach a hard tier.
    for key in MUST_NOT_SOLO_VETO:
        if signals.get(key):
            tier = _max_tier(tier, "soft_risk_tag")
            reasons.append(f"5.3:{key}(单独不硬否决→仅标签)")

    return {"veto_tier": tier, "effect": TIER_EFFECT.get(tier), "reasons": reasons, "row_context": row_context}
