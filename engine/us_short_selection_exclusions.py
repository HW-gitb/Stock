# -*- coding: utf-8 -*-
"""Derive the batch4 §11.4 exclusion facts from actual selection decisions."""
from __future__ import annotations

import json
from pathlib import Path

from engine.us_short_hot_excluded import hot_excluded_summary

ROOT = Path(__file__).resolve().parent.parent
_GOV_PATH = ROOT / "presets" / "us_short_exclusion_summary_governance_20260620.json"
EXCLUSION_CATEGORIES = tuple(json.loads(_GOV_PATH.read_text(encoding="utf-8"))["exclusion_categories"])
_CATEGORIES = EXCLUSION_CATEGORIES
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


def validate_pass1_exclusion_summary(summary) -> dict:
    if not (isinstance(summary, dict) and set(summary) == {"total_excluded", "category_counts"}):
        raise SelectionExclusionError("pass1_exclusion_summary 形状非法")
    counts = summary["category_counts"]
    if not (isinstance(counts, dict) and set(counts) == _CATEGORY_SET):
        raise SelectionExclusionError("pass1_exclusion_summary.category_counts 类别集合非法")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts.values()):
        raise SelectionExclusionError("pass1_exclusion_summary.category_counts 须为非负整数")
    total = summary["total_excluded"]
    if isinstance(total, bool) or not isinstance(total, int) or total < 0 or total != sum(counts.values()):
        raise SelectionExclusionError("pass1_exclusion_summary total 不守恒")
    return {"total_excluded": total, "category_counts": dict(counts)}


def pass1_exclusion_summary_from_rows(rows) -> dict:
    if not isinstance(rows, list):
        raise SelectionExclusionError("Pass1 rows 须为 list")
    counts = {category: 0 for category in _CATEGORIES}
    for row in rows:
        if not (isinstance(row, dict) and isinstance(row.get("eligible"), bool)
                and isinstance(row.get("reasons"), list)):
            raise SelectionExclusionError("Pass1 row 缺少 eligible/reasons")
        if not row["eligible"]:
            counts[pass1_category(row["reasons"])] += 1
    return {"total_excluded": sum(counts.values()), "category_counts": counts}


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
    """Build the report formatter input from the selection's stage-local exclusion records."""
    if not isinstance(selection, dict):
        raise SelectionExclusionError("selection 须为 dict")
    as_of = selection.get("decision_date")
    records = selection.get("exclusion_records")
    if not (isinstance(as_of, str) and isinstance(records, list)):
        raise SelectionExclusionError("selection 须含 decision_date(str) + exclusion_records(list)")
    upstream_pass1 = selection.get("pass1_exclusion_summary")
    if upstream_pass1 is not None:
        upstream_pass1 = validate_pass1_exclusion_summary(upstream_pass1)
    local_counts = {category: 0 for category in _CATEGORIES}
    stage_counts = {stage: 0 for stage in ("pass1_eligibility", "pass2_audit_gate", "top15_selection")}
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
        if upstream_pass1 is not None and record["stage"] == "pass1_eligibility":
            raise SelectionExclusionError(
                "upstream Pass1 摘要存在时不得保留本地 pass1_eligibility 记录（禁止重复计数）"
            )
        local_counts[record["category"]] += 1
        stage_counts[record["stage"]] += 1
    if upstream_pass1 is None:
        counts = dict(local_counts)
    else:
        counts = {
            category: upstream_pass1["category_counts"][category] + local_counts[category]
            for category in _CATEGORIES
        }
        stage_counts["pass1_eligibility"] = upstream_pass1["total_excluded"]
    if sum(stage_counts.values()) != sum(counts.values()):
        raise SelectionExclusionError("exclusion summary counts do not conserve")
    recall_excluded = selection.get("recall_excluded", [])
    if not isinstance(recall_excluded, list):
        raise SelectionExclusionError("selection.recall_excluded 须为 list")
    for row in recall_excluded:
        if not (isinstance(row, dict) and set(row) == {"ticker", "reason"}
                and isinstance(row["ticker"], str) and row["ticker"]
                and row["reason"] in {"off_universe", "below_floor"}):
            raise SelectionExclusionError(f"selection recall_excluded 记录非法: {row!r}")
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
        "stage_counts": stage_counts,
        "catalyst_recall_rejected_count": len(recall_excluded),
        "hot_excluded": hot_summary,
    }
