"""Deterministic closure for the six legacy A-short ``llm_tasks``.

This module deliberately does not fetch data or call an LLM.  The EGS exporter
uses :func:`build_task_configs`; the weekly pipeline supplies already-fetched
facts to :func:`build_task_results`.  Keeping those responsibilities separate
prevents the legacy task layer from silently widening the provider or DeepSeek
call surface.
"""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any


TASK_TYPES = (
    "industry_trend",
    "regulatory_check",
    "policy_news",
    "earnings_bad_reaction",
    "cross_market_linkage",
    "hidden_risk",
)

_DEFERRED = {
    "policy_news": (
        "official_policy_source_not_built",
        "官方政策 API/RSS/原文列表页",
    ),
    "cross_market_linkage": (
        "linkage_registry_and_market_source_not_built",
        "SW L2→关联资产→方向映射及结构化行情",
    ),
    "hidden_risk": (
        "pledge_cb_refinancing_debt_sources_not_built",
        "质押、可转债、再融资、短债/现金字段",
    ),
}


def build_task_configs(candidate: dict[str, Any], as_of: str) -> list[dict[str, Any]]:
    """Return the one stable, idempotent six-task configuration for a candidate."""
    ts_code = str(candidate.get("ts_code") or "")
    industry = candidate.get("industry") or {}
    scores = candidate.get("scores") or {}
    name = str(candidate.get("name") or "")
    base = {
        "ts_code": ts_code,
        "name": name,
        "as_of": str(as_of),
        "sw_l2_code": industry.get("sw_l2_code"),
        "sw_l2_name": industry.get("sw_l2_name"),
        "industry_heat_score": scores.get("industry_heat_score"),
    }
    return [
        {
            "task_id": f"{ts_code}_{task_type}",
            "task_type": task_type,
            # ``prompt`` remains the backwards-compatible field consumed by
            # the old Phase 4 report builder.
            "prompt": task_type,
            "status": "pending_llm",
            "inputs": dict(base),
        }
        for task_type in TASK_TYPES
    ]


def _record(task_type: str, candidate: dict[str, Any], as_of: str, **values: Any) -> dict[str, Any]:
    ts_code = str(candidate.get("ts_code") or "")
    out = {
        "task_id": f"{ts_code}_{task_type}",
        "task_type": task_type,
        "ts_code": ts_code,
        "as_of": str(as_of),
        "executor_type": values.pop("executor_type"),
        "status": values.pop("status"),
        "coverage_status": values.pop("coverage_status"),
        "result_code": values.pop("result_code"),
        "source_id": values.pop("source_id"),
        "observed_at": values.pop("observed_at", str(as_of)),
        "references": values.pop("references", []),
        "pit_basis": values.pop("pit_basis"),
        "facts": values.pop("facts", {}),
        "missing_fields": values.pop("missing_fields", []),
        "reason": values.pop("reason", None),
        "effect": values.pop("effect", "none"),
    }
    out.update(values)
    return out


def build_industry_trend_result(candidate: dict[str, Any], as_of: str) -> dict[str, Any]:
    industry = candidate.get("industry") or {}
    signal = industry.get("industry_trend_signal") or {}
    raw_trend = industry.get("industry_trend")
    trend = raw_trend if raw_trend in {"headwind", "tailwind", "neutral", "unknown"} else "unknown"
    signal_status = str(signal.get("validation_status") or "unavailable")
    source_id = signal.get("source_id") or "A-EGS.industry_heat_score"
    facts = {
        "industry_trend": trend,
        "industry_heat_score": signal.get("industry_heat_score"),
        "sw_l2_code": signal.get("sw_l2_code") or industry.get("sw_l2_code"),
        "sw_l2_name": signal.get("sw_l2_name") or industry.get("sw_l2_name"),
        "source_as_of": signal.get("source_as_of"),
        "classifier_version": signal.get("classifier_version"),
        "thresholds": signal.get("thresholds"),
        "source_id": source_id,
        "validation_status": signal_status,
        "unavailable_reason": signal.get("unavailable_reason"),
    }
    complete = trend in {"headwind", "tailwind", "neutral"} and signal_status == "valid"
    return _record(
        "industry_trend", candidate, as_of,
        executor_type="deterministic",
        status="completed" if complete else "unknown",
        coverage_status="checked" if complete else "unknown",
        result_code=trend if complete else "unknown",
        source_id=str(source_id),
        pit_basis="trade_date_window",
        facts=facts,
        references=[{
            "source_id": source_id,
            "source_as_of": signal.get("source_as_of"),
            "classifier_version": signal.get("classifier_version"),
        }],
        missing_fields=[] if complete else ["industry_heat_score_or_source_as_of"],
        reason=("risk_filter_v1_prior" if complete else
                str(signal.get("unavailable_reason") or "industry_heat_missing_or_source_date_mismatch")),
        effect="star_down_one" if trend == "headwind" else "none",
    )


def _event_references(official_structured: Any) -> list[dict[str, Any]]:
    refs = []
    if not isinstance(official_structured, dict):
        return refs
    for event in official_structured.get("events") or []:
        if not isinstance(event, dict):
            continue
        ref = {key: event.get(key) for key in ("source", "title", "disclosure_date", "url_or_pdf")
               if event.get(key) not in (None, "")}
        if ref:
            refs.append(ref)
    return refs


def build_regulatory_result(candidate: dict[str, Any], as_of: str,
                            official_structured: dict[str, Any] | None) -> dict[str, Any]:
    target_status = "unknown"
    facts: dict[str, Any] = {"delegated_target": "machine.layer.semantic_risk.official_structured"}
    if isinstance(official_structured, dict):
        target_status = str(official_structured.get("status") or "unknown")
        facts.update({
            "delegated_target_status": target_status,
            "had_pit_announcements": official_structured.get("had_pit_announcements"),
            "event_count": len(official_structured.get("events") or []),
        })
    else:
        facts["delegated_target_status"] = "unknown"
    checked = target_status != "unknown"
    return _record(
        "regulatory_check", candidate, as_of,
        executor_type="delegated",
        status="delegated" if checked else "unknown",
        coverage_status="delegated" if checked else "unknown",
        result_code="delegated" if checked else "unknown",
        source_id="machine.layer.semantic_risk.official_structured",
        pit_basis="disclosure_date",
        facts=facts,
        references=_event_references(official_structured),
        missing_fields=[] if checked else ["delegated_target_unverified"],
        reason=("covered_by_semantic_new_chain" if checked else "delegated_target_unverified"),
        effect="none",
        delegated_target="machine.layer.semantic_risk.official_structured",
        delegated_target_status=target_status,
    )


def build_deferred_result(task_type: str, candidate: dict[str, Any], as_of: str) -> dict[str, Any]:
    reason, requirement = _DEFERRED[task_type]
    return _record(
        task_type, candidate, as_of,
        executor_type="unavailable",
        status="provider_unavailable",
        coverage_status="provider_unavailable",
        result_code="provider_unavailable",
        source_id=f"legacy_task.{task_type}",
        pit_basis="manual_review_only",
        facts={"unverified": True},
        missing_fields=["provider_not_built"],
        reason=reason,
        effect="none",
        deferred_reason=reason,
        future_source_requirement=requirement,
    )


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _date8(value: Any) -> str | None:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        return None
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError:
        return None
    return value


def _indexed_prices(rows: Any, as_of: str) -> list[dict[str, Any]]:
    indexed = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        date = _date8(str(row.get("trade_date") or ""))
        close = _finite_number(row.get("close"))
        if date and close is not None and date <= as_of:
            indexed.append({"trade_date": date, "close": close, "vol": _finite_number(row.get("vol"))})
    return sorted(indexed, key=lambda item: item["trade_date"])


def _window_return(rows: list[dict[str, Any]], announcement_date: str, n: int) -> tuple[float | None, str | None]:
    before = [row for row in rows if row["trade_date"] <= announcement_date]
    after = [row for row in rows if row["trade_date"] > announcement_date]
    if not before or len(after) < n:
        return None, None
    base = before[-1]["close"]
    if base <= 0:
        return None, None
    target = after[n - 1]
    return (target["close"] / base - 1.0), target["trade_date"]


def _post_volume_ratio(rows: list[dict[str, Any]], announcement_date: str) -> float | None:
    before = [row["vol"] for row in rows if row["trade_date"] <= announcement_date and row.get("vol") is not None]
    after = [row["vol"] for row in rows if row["trade_date"] > announcement_date and row.get("vol") is not None]
    if not before or not after:
        return None
    mean20 = sum(before[-20:]) / len(before[-20:])
    if mean20 <= 0:
        return None
    return after[0] / mean20


def build_earnings_bad_reaction_result(candidate: dict[str, Any], as_of: str,
                                       evidence: dict[str, Any] | None) -> dict[str, Any]:
    """Build a PIT-only earnings-reaction result from already-fetched evidence.

    ``evidence`` is deliberately a narrow normalized shape so tests and the
    runtime adapter share the same semantics.  It must never contain prices
    after ``as_of``; this function drops them defensively as a second guard.
    """
    evidence = evidence or {}
    if evidence.get("provider_status") == "failed":
        return _record(
            "earnings_bad_reaction", candidate, as_of,
            executor_type="deterministic", status="unknown", coverage_status="unknown",
            result_code="unknown", source_id="tushare.forecast/income/daily/index_daily",
            pit_basis="disclosure_date", facts={}, missing_fields=["provider_call_failed"],
            reason="provider_call_failed", effect="none",
        )
    announcement_date = _date8(str(evidence.get("announcement_date") or ""))
    report_period = _date8(str(evidence.get("report_period") or ""))
    financial = evidence.get("financial_outcome")
    if announcement_date is None or announcement_date > as_of or financial not in {True, False}:
        missing = []
        if announcement_date is None or announcement_date > as_of:
            missing.append("pit_announcement_date")
        if financial not in {True, False}:
            missing.append("financial_outcome")
        return _record(
            "earnings_bad_reaction", candidate, as_of,
            executor_type="deterministic", status="unknown", coverage_status="unknown",
            result_code="unknown", source_id="tushare.forecast/income/daily/index_daily",
            pit_basis="disclosure_date", facts={"announcement_date": announcement_date, "report_period": report_period},
            missing_fields=missing, reason="financial_or_announcement_missing", effect="none",
        )
    stock = _indexed_prices(evidence.get("stock_prices"), as_of)
    csi1000 = _indexed_prices(evidence.get("csi1000_prices"), as_of)
    industry = _indexed_prices(evidence.get("industry_prices"), as_of)
    stock_returns, stock_dates = {}, {}
    index_returns, industry_returns = {}, {}
    for n in (1, 3, 5):
        stock_returns[n], stock_dates[n] = _window_return(stock, announcement_date, n)
        index_returns[n], _ = _window_return(csi1000, announcement_date, n)
        industry_returns[n], _ = _window_return(industry, announcement_date, n) if industry else (None, None)
    facts = {
        "announcement_date": announcement_date,
        "report_period": report_period,
        "financial_outcome": "non_negative_or_improving" if financial else "negative_or_deteriorating",
        "post_1d_return": stock_returns[1],
        "post_3d_return": stock_returns[3],
        "post_5d_return": stock_returns[5],
        "relative_csi1000_3d": (None if stock_returns[3] is None or index_returns[3] is None
                                 else stock_returns[3] - index_returns[3]),
        "relative_sw_l2_3d": (None if stock_returns[3] is None or industry_returns[3] is None
                               else stock_returns[3] - industry_returns[3]),
        "post_1d_volume_to_prior_20d": _post_volume_ratio(stock, announcement_date),
        "completed_through": stock_dates.get(5) or stock_dates.get(3) or stock_dates.get(1),
    }
    if stock_returns[3] is None or index_returns[3] is None:
        coverage = "window_incomplete" if stock_returns[1] is not None else "unknown"
        missing = ["post_3d_stock_or_csi1000_window"]
        return _record(
            "earnings_bad_reaction", candidate, as_of,
            executor_type="deterministic", status=coverage, coverage_status=coverage,
            result_code=coverage, source_id="tushare.forecast/income/daily/index_daily",
            pit_basis="disclosure_date", facts=facts, missing_fields=missing,
            reason="post_3d_window_not_completed" if coverage == "window_incomplete" else "price_or_benchmark_missing",
            effect="none",
        )
    relative_index = facts["relative_csi1000_3d"]
    relative_industry = facts["relative_sw_l2_3d"]
    negative = bool(financial and stock_returns[3] < 0 and relative_index < 0
                    and (relative_industry is None or relative_industry < 0))
    return _record(
        "earnings_bad_reaction", candidate, as_of,
        executor_type="deterministic", status="completed", coverage_status="checked",
        result_code="negative_manual_review" if negative else "neutral",
        source_id="tushare.forecast/income/daily/index_daily",
        pit_basis="disclosure_date", facts=facts,
        missing_fields=[] if industry else ["sw_l2_benchmark_not_reused"],
        reason=("non_negative_result_with_negative_relative_3d_reaction" if negative else "conditions_not_all_met"),
        effect="manual_review" if negative else "none",
    )


def build_task_results(candidate: dict[str, Any], as_of: str, *,
                       official_structured: dict[str, Any] | None = None,
                       earnings_evidence: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return all six result records in the same order as ``build_task_configs``."""
    return [
        build_industry_trend_result(candidate, as_of),
        build_regulatory_result(candidate, as_of, official_structured),
        build_deferred_result("policy_news", candidate, as_of),
        build_earnings_bad_reaction_result(candidate, as_of, earnings_evidence),
        build_deferred_result("cross_market_linkage", candidate, as_of),
        build_deferred_result("hidden_risk", candidate, as_of),
    ]


def result_content(result: dict[str, Any]) -> str:
    """Stable, non-empty human summary used by deterministic Phase 4 sections."""
    task_type = str(result.get("task_type") or "task")
    status = str(result.get("status") or "unknown")
    code = str(result.get("result_code") or "unknown")
    reason = str(result.get("reason") or "")
    if status == "provider_unavailable":
        return f"{task_type}: 数据源未建设/未核查；effect=none。{reason}"
    if task_type == "regulatory_check" and status == "unknown":
        return "regulatory_check: 委托 CNINFO 语义目标未核查；effect=none。"
    return f"{task_type}: {code}（{status}）；effect={result.get('effect', 'none')}。{reason}"
