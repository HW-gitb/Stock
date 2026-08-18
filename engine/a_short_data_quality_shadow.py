"""Shadow-only data-quality comparison for A-short weekly reports.

This slice deliberately observes the proposed block/degrade/warn policy without
changing Phase5 actions, shares, cash allocation, or any production threshold.
The weekly JSON/Markdown report is the formal comparison consumer.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas" / "a_short_data_quality_shadow.schema.json"
SCHEMA_NAME = "a_short_data_quality_shadow"
SCHEMA_VERSION = "1.1.0"
REQUIRED_FIELDS = (
    "quote.close",
    "technical.support",
    "technical.atr.atr_14",
)


def _field_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item).strip() for item in value if isinstance(item, str) and item.strip()})


def _finite_score(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    score = float(value)
    return score if math.isfinite(score) and 0.0 <= score <= 1.0 else None


def classify_data_quality_shadow(data_quality) -> dict:
    """Classify one candidate for observation; never mutate a production action."""
    valid = isinstance(data_quality, dict)
    payload = data_quality if valid else {}
    missing = _field_list(payload.get("missing_fields"))
    pending = _field_list(payload.get("pending_fields"))
    rule11 = _field_list(payload.get("rule11_required"))
    permanently_unavailable = _field_list(payload.get("permanently_unavailable"))
    paid_source_declined = _field_list(payload.get("paid_source_declined"))
    candidate_output_deferred = _field_list(payload.get("candidate_output_deferred"))
    score = _finite_score(payload.get("completeness_score"))
    reasons: list[str] = []
    required_missing = sorted(set(missing + pending + rule11) & set(REQUIRED_FIELDS))
    extra_missing = sorted(set(missing) - set(REQUIRED_FIELDS))
    if not valid:
        status = "block"
        reasons.append("data_quality_missing_or_invalid")
    elif required_missing:
        status = "block"
        reasons.append("required_fields_missing:" + ",".join(required_missing))
    else:
        degrade_reasons = []
        if score is None and "completeness_score" in payload:
            degrade_reasons.append("completeness_score_invalid")
        elif score is not None and score < 1.0:
            degrade_reasons.append(f"completeness_score_below_shadow_floor:{score:g}")
        if extra_missing:
            degrade_reasons.append("secondary_fields_missing:" + ",".join(extra_missing))
        if degrade_reasons:
            status = "degrade"
            reasons.extend(degrade_reasons)
        elif pending or rule11:
            status = "warn"
            reasons.append("pending_or_rule11_disclosure")
        else:
            status = "clean"
    return {
        "status": status,
        "block": status == "block",
        "degrade": status == "degrade",
        "warn": status == "warn",
        "completeness_score": score,
        "missing_fields": missing,
        "pending_fields": pending,
        "rule11_required": rule11,
        "permanently_unavailable": permanently_unavailable,
        "paid_source_declined": paid_source_declined,
        "candidate_output_deferred": candidate_output_deferred,
        "reasons": reasons or ["no_shadow_quality_issue"],
    }


def build_data_quality_shadow(normalized_list: list[dict], as_of: str) -> dict:
    rows = []
    seen_codes: set[str] = set()
    for index, candidate in enumerate(normalized_list or []):
        result = classify_data_quality_shadow(candidate.get("data_quality"))
        raw_code = str(candidate.get("ts_code") or "")
        # The shadow must not pre-empt the weekly validator's own identity
        # checks.  Give malformed/duplicate rows deterministic comparison keys
        # so a negative weekly fixture can still reach its intended validator.
        code = raw_code or f"__shadow_row_{index}"
        if code in seen_codes:
            code = f"{code}#shadow_row_{index}"
        seen_codes.add(code)
        rows.append({"ts_code": code, **result})
    counts = {status: sum(row["status"] == status for row in rows)
              for status in ("block", "degrade", "warn", "clean")}
    total = len(rows)
    if counts["block"]:
        observed = "block_observed"
    elif counts["degrade"]:
        observed = "degrade_observed"
    elif counts["warn"]:
        observed = "warn_observed"
    elif total:
        observed = "clean_observed"
    else:
        observed = "no_candidates"
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "as_of": str(as_of),
        "comparison_only": True,
        "production_effect_enabled": False,
        "policy": {
            "version": "shadow_v1",
            "required_fields": list(REQUIRED_FIELDS),
            "degrade_floor": "completeness_score < 1.0 or non-required missing_fields",
            "activation": "disabled_pending_shadow_review",
        },
        "verdict": {
            "status": "shadow_only_pending_activation",
            "observed_outcome": observed,
            "production_effect_enabled": False,
            "comparison_only": True,
        },
        "summary": {
            "total_candidates": total,
            **{f"{key}_count": value for key, value in counts.items()},
            "block_rate": round(counts["block"] / total, 6) if total else 0.0,
            "degrade_rate": round(counts["degrade"] / total, 6) if total else 0.0,
            "warn_rate": round(counts["warn"] / total, 6) if total else 0.0,
        },
        "candidates": rows,
    }


def validate_data_quality_shadow(payload: dict, *, expected_as_of: str | None = None) -> None:
    if not isinstance(payload, dict):
        raise ValueError("data-quality shadow is required and must be an object")
    jsonschema.validate(payload, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))
    if expected_as_of is not None and str(payload.get("as_of")) != str(expected_as_of):
        raise ValueError("data-quality shadow as_of is not bound to weekly as_of")
    if payload.get("comparison_only") is not True or payload.get("production_effect_enabled") is not False:
        raise ValueError("data-quality shadow must remain comparison-only and production-disabled")
    rows = payload.get("candidates") or []
    if len({row.get("ts_code") for row in rows}) != len(rows):
        raise ValueError("data-quality shadow contains duplicate candidates")
    summary = payload["summary"]
    for status in ("block", "degrade", "warn", "clean"):
        if summary[f"{status}_count"] != sum(row["status"] == status for row in rows):
            raise ValueError(f"data-quality shadow {status} count diverges")
    observed = payload["verdict"]["observed_outcome"]
    expected = ("block_observed" if summary["block_count"] else
                "degrade_observed" if summary["degrade_count"] else
                "warn_observed" if summary["warn_count"] else
                "clean_observed" if rows else "no_candidates")
    if observed != expected:
        raise ValueError("data-quality shadow verdict diverges from summary")
