# -*- coding: utf-8 -*-
"""Derive the batch4 §11.4 exclusion facts from actual selection decisions."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_GOV_PATH = ROOT / "presets" / "us_short_exclusion_summary_governance_20260620.json"
_CATEGORIES = tuple(json.loads(_GOV_PATH.read_text(encoding="utf-8"))["exclusion_categories"])
_CATEGORY_SET = frozenset(_CATEGORIES)


class SelectionExclusionError(ValueError):
    """Selection reject evidence is malformed or outside the frozen category vocabulary."""


def pass1_category(reasons) -> str:
    """Map one failed Pass1 verdict to one frozen primary category."""
    rs = tuple(reasons) if isinstance(reasons, list) else ()
    if any(r in {"exchange_not_whitelisted", "status_delisted", "status_halted",
                 "status_bankruptcy", "status_otc"} for r in rs):
        return "停牌退市破产"
    if "adv_usd_below_floor" in rs:
        return "流动性"
    if any(r in {"price_below_floor", "market_cap_usd_below_floor"} for r in rs):
        return "价格市值"
    return "数据unknown"


def pass2_category(reasons) -> str:
    """Map one Pass2 hard-veto verdict to one frozen primary category."""
    rs = tuple(reasons) if isinstance(reasons, list) else ()
    if any("SEC增发" in r for r in rs):
        return "增发SEC"
    if any(any(label in r for label in ("退市", "停牌", "破产", "OTC")) for r in rs):
        return "停牌退市破产"
    if any(any(label in r for label in ("流动性", "spread")) for r in rs):
        return "流动性"
    return "数据unknown"


def build_selection_exclusion_data(selection: dict) -> dict:
    """Build the report formatter input from ``run_selection.exclusion_records`` only."""
    if not isinstance(selection, dict):
        raise SelectionExclusionError("selection 须为 dict")
    as_of = selection.get("decision_date")
    records = selection.get("exclusion_records")
    if not (isinstance(as_of, str) and isinstance(records, list)):
        raise SelectionExclusionError("selection 须含 decision_date(str) + exclusion_records(list)")
    counts = {category: 0 for category in _CATEGORIES}
    for record in records:
        if not (isinstance(record, dict)
                and set(record) == {"stage", "ticker", "category", "reasons"}
                and record["stage"] in {"pass1_eligibility", "pass2_audit_gate", "top15_selection"}
                and (record["ticker"] is None or isinstance(record["ticker"], str))
                and record["category"] in _CATEGORY_SET
                and isinstance(record["reasons"], list)
                and record["reasons"]
                and all(isinstance(reason, str) and reason for reason in record["reasons"])):
            raise SelectionExclusionError(f"selection exclusion record 非法: {record!r}")
        counts[record["category"]] += 1
    return {
        "as_of": as_of,
        "categories": {category: {"public_count": count, "holdings": []}
                       for category, count in counts.items()},
        "hot_excluded": {"public_heat_count": 0, "holdings": []},
    }
