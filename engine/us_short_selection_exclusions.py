# -*- coding: utf-8 -*-
"""Derive the batch4 §11.4 exclusion facts from actual selection decisions."""
from __future__ import annotations

import json
from pathlib import Path

from engine.us_short_hot_excluded import hot_excluded_summary

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


def _hot_audit_gate(record):
    """Fixed §11.4 mapping. Pass2 is the hard-veto gate and is never hot-excluded."""
    if record["stage"] != "pass1_eligibility":
        return None
    if record["category"] == "流动性":
        return "liquidity"
    if record["category"] == "数据unknown":
        return "data"
    if record["category"] == "停牌退市破产":
        return "safety"
    if record["category"] == "价格市值":
        return "safety"
    return None


def build_hot_excluded_audit(exclusion_records, *, heat_audit, as_of, source_digest):
    """Join actual exclusions to the same theme contract digest; never changes admission."""
    if not (isinstance(exclusion_records, list) and isinstance(as_of, str)
            and isinstance(source_digest, str) and len(source_digest) == 64):
        raise SelectionExclusionError("hot-excluded join identity 非法")
    heat_by_ticker = {}
    threshold = None
    if heat_audit is not None:
        if not (isinstance(heat_audit, dict) and set(heat_audit) == {"heat_threshold", "per_ticker"}
                and isinstance(heat_audit["per_ticker"], dict)):
            raise SelectionExclusionError("theme heat audit 形状非法")
        threshold = heat_audit["heat_threshold"]
        heat_by_ticker = heat_audit["per_ticker"]
    rows, unevaluable = [], 0
    for record in exclusion_records:
        gate = _hot_audit_gate(record)
        if gate is None:
            continue
        ticker = record.get("ticker")
        heat = heat_by_ticker.get(ticker) if isinstance(ticker, str) else None
        if heat is None:
            unevaluable += 1
            continue
        rows.append({"ticker": ticker, "theme_heat_score": heat,
                     "dropped_at_gate": gate, "is_holding": False})
    return {"as_of": as_of, "source_digest": source_digest, "heat_threshold": threshold,
            "rows": rows, "unevaluable_count": unevaluable}


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
    hot_audit = selection.get("hot_excluded_audit")
    expected_digest = selection.get("theme_contract_digest")
    if not (isinstance(hot_audit, dict)
            and set(hot_audit) == {"as_of", "source_digest", "heat_threshold", "rows", "unevaluable_count"}
            and hot_audit["as_of"] == as_of and isinstance(hot_audit["source_digest"], str)
            and isinstance(expected_digest, str) and hot_audit["source_digest"] == expected_digest
            and len(expected_digest) == 64
            and all(ch in "0123456789abcdef" for ch in expected_digest)
            and isinstance(hot_audit["rows"], list)
            and isinstance(hot_audit["unevaluable_count"], int)
            and not isinstance(hot_audit["unevaluable_count"], bool)
            and hot_audit["unevaluable_count"] >= 0):
        raise SelectionExclusionError("selection.hot_excluded_audit 缺失或未绑定同 run")
    if hot_audit["heat_threshold"] is None:
        hot_summary = {"public_heat_count": 0, "holdings": []}
    else:
        hot_summary = hot_excluded_summary(
            hot_audit["rows"], heat_threshold=hot_audit["heat_threshold"])
    hot_summary["unevaluable_count"] = hot_audit["unevaluable_count"]
    return {
        "as_of": as_of,
        "categories": {category: {"public_count": count, "holdings": []}
                       for category, count in counts.items()},
        "hot_excluded": hot_summary,
    }
