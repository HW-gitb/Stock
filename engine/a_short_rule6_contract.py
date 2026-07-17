"""Canonical Rule6 check inventory and fail-closed completion gate."""

from __future__ import annotations


RULE6_CHECKS = (
    ("rule6_holder_reduction", "pre_veto"),
    ("rule6_crash_veto", "pre_veto"),
    ("rule6_holder_below_5pct", "pre_veto"),
    ("rule6_50etf_iv", "pre_veto"),
    ("rule6_cash_debt_double_high", "pre_veto"),
    ("rule6_regulatory_48h", "pre_veto"),
    ("rule6_good_data_bad_reaction", "post_veto"),
    ("rule6_volume_stall", "post_veto"),
    ("rule6_margin_extreme_accumulation", "post_veto"),
    ("rule6_block_trade_discount", "post_veto"),
    ("rule6_northbound_selloff", "post_veto"),
    ("rule6_short_selling_surge", "post_veto"),
    ("rule6_ar_growth_gt_revenue_growth", "post_veto"),
)

_EXPECTED_GROUPS = dict(RULE6_CHECKS)
RULE6_D_TIER_REASONS = {
    "rule6_northbound_selloff": (
        "仅人工核查：逐股北向持仓日度数据已不可得，市场级北向流仅作环境参考"
    ),
    "rule6_good_data_bad_reaction": (
        "仅人工核查：免费数据无卖方一致预期及次日盘中反应，不能自动判定"
    ),
    "rule6_regulatory_48h": (
        "仅人工核查：监管/媒体事件保留 cninfo 语义层 advisory，不作自动硬否决"
    ),
}
# Conditionally-inapplicable computable checks.  These two Rule6 items are only
# meaningful for margin-eligible (两融标的) stocks.  When the producer has
# POSITIVELY established (from a fetched margin universe) that a stock is not a
# margin target, the rule genuinely does not apply and is `not_applicable` with
# the frozen reason below -- which counts as clear.  A missing margin universe
# (fetch failure) must NOT reach this state; it stays `unknown` upstream.
RULE6_CONDITIONAL_NA_REASONS = {
    "rule6_margin_extreme_accumulation": "非两融标的：无融资融券余额记录，融资异常累积规则不适用",
    "rule6_short_selling_surge": "非两融标的：无融资融券余额记录，融券异常激增规则不适用",
}
_CLEAR_STATUSES = {"pass", "not_applicable"}


def validate_rule6_check_contract(checks: list[dict]) -> None:
    """Ensure producer output has the complete, stable Rule6 check inventory."""
    if not isinstance(checks, list):
        raise ValueError("Rule6 checks must be a list")

    seen: set[str] = set()
    for check in checks:
        if not isinstance(check, dict):
            raise ValueError("Rule6 check must be an object")
        check_id = check.get("id")
        if not isinstance(check_id, str) or check_id not in _EXPECTED_GROUPS:
            raise ValueError(f"unexpected Rule6 check id: {check_id!r}")
        if check_id in seen:
            raise ValueError(f"duplicate Rule6 check id: {check_id}")
        if check.get("group") != _EXPECTED_GROUPS[check_id]:
            raise ValueError(f"Rule6 check group mismatch: {check_id}")
        if check_id in RULE6_D_TIER_REASONS:
            if check.get("status") != "not_applicable":
                raise ValueError(f"Rule6 D-tier must be not_applicable: {check_id}")
            if check.get("notes") != RULE6_D_TIER_REASONS[check_id]:
                raise ValueError(f"Rule6 D-tier reason mismatch: {check_id}")
        elif check_id in RULE6_CONDITIONAL_NA_REASONS and check.get("status") == "not_applicable":
            if check.get("notes") != RULE6_CONDITIONAL_NA_REASONS[check_id]:
                raise ValueError(f"Rule6 conditional not_applicable reason mismatch: {check_id}")
        elif check.get("status") == "not_applicable":
            raise ValueError(f"Rule6 computable check cannot be not_applicable: {check_id}")
        elif check.get("status") not in {"pass", "fail", "unknown"}:
            raise ValueError(f"Rule6 computable check must be pass, fail, or unknown: {check_id}")
        seen.add(check_id)

    missing = set(_EXPECTED_GROUPS) - seen
    if missing:
        raise ValueError(f"missing Rule6 checks: {','.join(sorted(missing))}")


def assess_rule6_checks(checks: object) -> dict:
    """Classify Rule6 for an M6.7 decision without treating pending as clear.

    ``hard_veto`` wins when any known check failed.  All unresolved, malformed,
    absent, duplicate, or inventory-drift cases require manual review and may
    not produce a new-position recommendation.
    """
    manual_review_ids: list[str] = []
    hard_veto_ids: list[str] = []
    records: dict[str, dict] = {}
    not_applicable_checks: list[dict[str, str]] = []
    conditional_na_checks: list[dict[str, str]] = []

    if not isinstance(checks, list):
        manual_review_ids.append("rule6_checks_missing")
        checks = []

    for item in checks:
        if not isinstance(item, dict):
            manual_review_ids.append("rule6_check_malformed")
            continue
        check_id = item.get("id")
        if not isinstance(check_id, str) or check_id not in _EXPECTED_GROUPS:
            manual_review_ids.append(f"unexpected:{check_id!r}")
            continue
        if check_id in records:
            manual_review_ids.append(f"duplicate:{check_id}")
            continue
        records[check_id] = item

    for check_id, expected_group in RULE6_CHECKS:
        item = records.get(check_id)
        if item is None:
            manual_review_ids.append(f"missing:{check_id}")
            continue
        if item.get("group") != expected_group:
            manual_review_ids.append(f"group_mismatch:{check_id}")
            continue
        status = item.get("status")
        d_tier_reason = RULE6_D_TIER_REASONS.get(check_id)
        if d_tier_reason is not None:
            if status != "not_applicable" or item.get("notes") != d_tier_reason:
                manual_review_ids.append(f"d_tier_disposition:{check_id}")
            else:
                not_applicable_checks.append({"id": check_id, "reason": d_tier_reason})
            continue
        conditional_na_reason = RULE6_CONDITIONAL_NA_REASONS.get(check_id)
        if conditional_na_reason is not None and status == "not_applicable":
            if item.get("notes") == conditional_na_reason:
                conditional_na_checks.append({"id": check_id, "reason": conditional_na_reason})
            else:
                manual_review_ids.append(f"conditional_na_disposition:{check_id}")
            continue
        if status == "not_applicable":
            manual_review_ids.append(f"not_applicable_not_allowed:{check_id}")
            continue
        if status == "fail":
            hard_veto_ids.append(check_id)
        elif status not in _CLEAR_STATUSES:
            manual_review_ids.append(check_id)

    manual_review_ids = list(dict.fromkeys(manual_review_ids))
    hard_veto_ids = list(dict.fromkeys(hard_veto_ids))
    disposition = "hard_veto" if hard_veto_ids else (
        "manual_review" if manual_review_ids else "clear")
    return {
        "disposition": disposition,
        "hard_veto_check_ids": hard_veto_ids,
        "manual_review_check_ids": manual_review_ids,
        "not_applicable_checks": not_applicable_checks,
        "conditional_na_checks": conditional_na_checks,
    }


def render_rule6_d_tier_banner(gate: dict) -> str:
    """Return the persistent user-facing D-tier manual-review banner."""
    checks = gate.get("not_applicable_checks") if isinstance(gate, dict) else None
    if not isinstance(checks, list) or len(checks) != len(RULE6_D_TIER_REASONS):
        return "仅人工核查：Rule6 D-tier 处置不完整，当前不可建仓"
    by_id = {item.get("id"): item.get("reason") for item in checks if isinstance(item, dict)}
    if by_id != RULE6_D_TIER_REASONS:
        return "仅人工核查：Rule6 D-tier 处置不完整，当前不可建仓"
    return "仅人工核查（不参与自动否决）：" + "；".join(
        f"{check_id}（{reason}）" for check_id, reason in RULE6_D_TIER_REASONS.items()
    )
