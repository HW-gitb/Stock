"""A-short industry-trend and governed theme-taxonomy helpers.

This module is deliberately pure: it reads only explicit JSON configuration and
in-memory L3 structures.  It neither fetches provider data nor turns concept
membership into a production signal.  The weekly pipeline may consume the
industry-trend signal as the single authorized -1 star risk; every theme
classification remains comparison-only until a separately reviewed promotion.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY_PATH = ROOT / "presets" / "a_short_theme_taxonomy.json"
ROLE_VALUES = {"core", "key_supplier", "adjacent", "weak_link", "unknown"}


def configuration_fingerprint(value: Any) -> str:
    """Stable SHA-256 for a governed runtime/configuration object."""
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def finite_industry_heat_score(value: Any) -> float | None:
    """Return a finite numeric heat score; booleans are not numeric evidence."""
    if isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return score if math.isfinite(score) else None


def industry_trend_policy(governance: dict) -> dict:
    """Return the governed deterministic ``industry_trend`` classifier policy."""
    block = (governance or {}).get("industry_trend_classifier")
    required = {
        "classifier_version", "source_id", "headwind_max", "tailwind_min",
        "risk_filter_v1_prior", "forward_calibration_required",
        "positive_effect_enabled", "semantic_boundary",
    }
    if not isinstance(block, dict) or required - set(block):
        raise ValueError("industry heat governance missing industry_trend_classifier")
    if not (0.0 <= float(block["headwind_max"]) < float(block["tailwind_min"]) <= 100.0):
        raise ValueError("industry trend classifier thresholds are not ordered")
    if block["positive_effect_enabled"] is not False:
        raise ValueError("industry trend v1 must prohibit a positive M6.7 effect")
    return dict(block)


def industry_trend_from_score(score: Any, policy: dict) -> str | None:
    """Return the governed label for a valid 0--100 industry heat score."""
    value = finite_industry_heat_score(score)
    if value is None or not 0.0 <= value <= 100.0:
        return None
    if value <= float(policy["headwind_max"]):
        return "headwind"
    if value >= float(policy["tailwind_min"]):
        return "tailwind"
    return "neutral"


def classify_industry_trend(*, score: Any, sw_l2_code: Any, sw_l2_name: Any,
                            source_as_of: Any, expected_as_of: Any,
                            governance: dict) -> dict:
    """Classify existing EGS heat into the deterministic M6.7 industry signal.

    This is d15e's source-bound ``industry_trend`` method: it consumes no new
    data and never reuses the LLM's fundamental/policy judgement.  Missing,
    stale or invalid evidence is explicit ``unknown``, never silent neutral.
    """
    policy = industry_trend_policy(governance)
    value = finite_industry_heat_score(score)
    source = None if source_as_of in (None, "") else str(source_as_of)
    expected = None if expected_as_of in (None, "") else str(expected_as_of)
    code = None if sw_l2_code in (None, "") else str(sw_l2_code)
    name = None if sw_l2_name in (None, "") else str(sw_l2_name)
    reason = None
    if not (isinstance(expected, str) and len(expected) == 8 and expected.isascii() and expected.isdigit()):
        reason = "expected_as_of_invalid"
    elif not code or not name or name == "未知":
        reason = "sw_l2_unavailable"
    elif source != expected:
        reason = "source_as_of_mismatch"
    elif industry_trend_from_score(value, policy) is None:
        reason = "industry_heat_score_invalid"
    if reason is not None:
        trend = "unknown"
    else:
        trend = industry_trend_from_score(value, policy)
    return {
        "classification": trend,
        "industry_trend": trend,
        "industry_heat_score": value if reason is None else None,
        "sw_l2_code": code,
        "sw_l2_name": name,
        "source_as_of": source,
        "classifier_version": str(policy["classifier_version"]),
        "thresholds": {
            "headwind_max": float(policy["headwind_max"]),
            "tailwind_min": float(policy["tailwind_min"]),
        },
        "source_id": str(policy["source_id"]),
        "risk_filter_v1_prior": bool(policy["risk_filter_v1_prior"]),
        "forward_calibration_required": bool(policy["forward_calibration_required"]),
        "positive_effect_enabled": bool(policy["positive_effect_enabled"]),
        "configuration_fingerprint": configuration_fingerprint(policy),
        "validation_status": "valid" if reason is None else "unavailable",
        "unavailable_reason": reason,
    }


def _normalise(value: Any) -> str:
    return "".join(str(value or "").strip().lower().split())


def _date8(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 8 and value.isascii() and value.isdigit()


def load_theme_taxonomy(path: str | Path = TAXONOMY_PATH) -> dict:
    with Path(path).open("r", encoding="utf-8") as handle:
        taxonomy = json.load(handle)
    validate_theme_taxonomy(taxonomy)
    return taxonomy


def validate_theme_taxonomy(taxonomy: dict) -> None:
    """Small runtime guard that complements the JSON-schema contract."""
    if not isinstance(taxonomy, dict):
        raise ValueError("theme taxonomy must be an object")
    if taxonomy.get("schema_name") != "a_short_theme_taxonomy":
        raise ValueError("theme taxonomy schema_name mismatch")
    if taxonomy.get("schema_version") != "1.2.0":
        raise ValueError("theme taxonomy schema_version mismatch")
    raw_source = taxonomy.get("raw_concept_source")
    if not isinstance(raw_source, dict) or raw_source.get("provider") != "runtime_bound_l3":
        raise ValueError("theme taxonomy must bind raw concepts to the runtime L3 receipt")
    if raw_source.get("runtime_receipt_required") is not True:
        raise ValueError("theme taxonomy must require an L3 runtime receipt")
    if raw_source.get("live_coverage_receipt_required") is not True:
        raise ValueError("theme taxonomy must require a complete live L3 coverage receipt")
    if raw_source.get("legacy_snapshot_allowed_for_comparison") is not True:
        raise ValueError("theme taxonomy must explicitly constrain legacy snapshots to comparison use")
    themes = taxonomy.get("canonical_themes")
    if not isinstance(themes, list) or not themes:
        raise ValueError("theme taxonomy needs canonical_themes")
    seen = set()
    for theme in themes:
        theme_id = str((theme or {}).get("theme_id") or "").strip()
        if not theme_id or theme_id in seen:
            raise ValueError("theme taxonomy IDs must be non-empty and unique")
        seen.add(theme_id)
        if theme.get("status") not in {"comparison_only", "approved", "retired"}:
            raise ValueError(f"theme {theme_id} has invalid status")
        if theme.get("production_effect_enabled") is not False:
            raise ValueError(f"theme {theme_id} must start production_effect_enabled=false")
        calibration = theme.get("forward_calibration") or {}
        if calibration.get("automatic_promotion") is not False:
            raise ValueError(f"theme {theme_id} must prohibit automatic promotion")


def _l3_provenance(*, l3_provider: Any, l3_snapshot_date: Any,
                   l3_coverage: Any) -> dict:
    """Reduce the upstream L3 receipt to the fields taxonomy consumers need.

    The taxonomy consumes the complete concept graph supplied by the screening
    run; it must not relabel that graph as a permanent Tushare source.  The
    provider and coverage receipt travel with every classification so the
    forward comparison track can distinguish a complete current graph from a
    legacy PIT snapshot or unavailable comparison evidence.
    """
    provider = str(l3_provider).strip() if l3_provider not in (None, "") else None
    snapshot_date = str(l3_snapshot_date) if _date8(l3_snapshot_date) else None
    coverage = dict(l3_coverage) if isinstance(l3_coverage, dict) else {}
    digest = coverage.get("catalog_digest")
    digest = str(digest) if isinstance(digest, str) and len(digest) == 64 else None
    complete = coverage.get("complete") if isinstance(coverage.get("complete"), bool) else None
    universe = coverage.get("scoring_universe")
    universe = str(universe) if isinstance(universe, str) and universe else None
    if (provider == "hithink_finance" and snapshot_date and complete is True
            and universe == "a_share_main_board" and digest):
        status = "verified_complete"
        membership_source = "hithink_complete_concept_members"
    elif provider == "legacy_tushare_snapshot" and snapshot_date:
        status = "legacy_snapshot"
        membership_source = "legacy_snapshot_concept_members"
    else:
        status = "unavailable"
        membership_source = "unavailable"
    return {
        "provider": provider,
        "snapshot_date": snapshot_date,
        "coverage_digest": digest,
        "coverage_complete": complete,
        "scoring_universe": universe,
        "raw_membership_source": membership_source,
        "validation_status": status,
    }


def unavailable_theme_taxonomy(as_of: str, reason: str, taxonomy: dict | None = None,
                               *, l3_provider: Any = None, l3_snapshot_date: Any = None,
                               l3_coverage: Any = None) -> dict:
    """An explicit comparison-unavailable value for old/no-L3 artifacts."""
    taxonomy = taxonomy or load_theme_taxonomy()
    return {
        "taxonomy_schema_name": taxonomy["schema_name"],
        "taxonomy_schema_version": taxonomy["schema_version"],
        "taxonomy_configuration_fingerprint": configuration_fingerprint(taxonomy),
        "source_as_of": str(as_of),
        "l3_provenance": _l3_provenance(
            l3_provider=l3_provider,
            l3_snapshot_date=l3_snapshot_date,
            l3_coverage=l3_coverage,
        ),
        "raw_concepts": [],
        "canonical_themes": [],
        "primary_canonical_theme_id": None,
        "production_effect_enabled": False,
        "automatic_promotion": False,
        "comparison_status": "unknown_or_unavailable",
        "unavailable_reason": str(reason),
    }


def complete_stock_concepts(stock_concepts: dict | None, concept_members: dict | None) -> dict[str, list[str]]:
    """Return all known raw concepts per stock, including inverse-membership extras.

    Older L3 snapshots may retain only the first five provider concepts per
    stock.  ``concept_members`` is the market-wide inverse source, so using its
    union here prevents governed classification from silently dropping the
    sixth-and-later concepts while preserving the provider's original ordering
    where it exists.
    """
    out: dict[str, list[str]] = {}
    for code, ids in (stock_concepts or {}).items():
        out[str(code)] = [str(item) for item in (ids or []) if str(item).strip()]
    for concept_id, codes in (concept_members or {}).items():
        for code in codes or []:
            bucket = out.setdefault(str(code), [])
            if str(concept_id) not in bucket:
                bucket.append(str(concept_id))
    return out


def _concept_names(concepts_df: Any) -> dict[str, str]:
    if not isinstance(concepts_df, pd.DataFrame) or concepts_df.empty:
        return {}
    id_col = next((name for name in ("code", "concept_id", "id", "ts_code") if name in concepts_df.columns), None)
    name_col = next((name for name in ("name", "concept_name", "src_name") if name in concepts_df.columns), None)
    if not id_col or not name_col:
        return {}
    return {
        str(row[id_col]): str(row[name_col])
        for _, row in concepts_df[[id_col, name_col]].dropna().iterrows()
        if str(row[id_col]).strip() and str(row[name_col]).strip()
    }


def _validated_role_evidence(records: Any, code: str, as_of: str,
                             run_date: Any = None) -> tuple[str, str, list[dict], str | None]:
    """Accept only structured, clocked evidence; never infer a role from prose."""
    if not records:
        return "unknown", "unknown", [], "structured_business_evidence_unavailable"
    decision_date = str(as_of)
    if not _date8(decision_date):
        return "unknown", "unknown", [], "structured_business_evidence_invalid_or_unavailable"
    evidence_cutoff = decision_date
    if run_date not in (None, ""):
        run_date = str(run_date)
        if not _date8(run_date):
            return "unknown", "unknown", [], "structured_business_evidence_invalid_or_unavailable"
        evidence_cutoff = min(decision_date, run_date)
    valid = []
    for item in records:
        if not isinstance(item, dict) or str(item.get("ts_code")) != str(code):
            continue
        required = {"role", "source_id", "observed_at", "checked_at", "finding_id"}
        if required - set(item) or item.get("role") not in ROLE_VALUES - {"unknown"}:
            continue
        if not _date8(item["observed_at"]) or not _date8(item["checked_at"]):
            continue
        if item["observed_at"] > evidence_cutoff or item["checked_at"] > evidence_cutoff:
            continue
        valid.append({key: item[key] for key in ("role", "source_id", "observed_at", "checked_at", "finding_id")})
    if not valid:
        return "unknown", "unknown", [], "structured_business_evidence_invalid_or_unavailable"
    # The provider/adapter must explicitly nominate the role.  Multiple valid
    # findings use the strongest explicitly evidenced role, never a keyword guess.
    order = {"core": 4, "key_supplier": 3, "adjacent": 2, "weak_link": 1}
    role = max((item["role"] for item in valid), key=lambda value: order[value])
    confidence = "high" if len(valid) > 1 else "medium"
    return role, confidence, valid, None


def _matches(raw: dict, values: list[str]) -> bool:
    norm_values = {_normalise(value) for value in values if _normalise(value)}
    return str(raw["concept_id"]) in values or _normalise(raw["concept_name"]) in norm_values


def classify_theme_taxonomy(*, ts_code: str, stock_concepts: dict | None,
                            concept_members: dict | None, concepts_df: Any,
                            as_of: str, taxonomy: dict | None = None,
                            business_evidence: list[dict] | None = None,
                            l3_provider: Any = None, l3_snapshot_date: Any = None,
                            l3_coverage: Any = None, run_date: Any = None) -> dict:
    """Classify raw provider concepts into zero or more governed canonical themes."""
    taxonomy = taxonomy or load_theme_taxonomy()
    validate_theme_taxonomy(taxonomy)
    provenance = _l3_provenance(
        l3_provider=l3_provider,
        l3_snapshot_date=l3_snapshot_date,
        l3_coverage=l3_coverage,
    )
    if provenance["validation_status"] == "unavailable":
        return unavailable_theme_taxonomy(
            as_of,
            "l3_provenance_unavailable",
            taxonomy,
            l3_provider=l3_provider,
            l3_snapshot_date=l3_snapshot_date,
            l3_coverage=l3_coverage,
        )
    names = _concept_names(concepts_df)
    full = complete_stock_concepts(stock_concepts, concept_members)
    raw = [
        {
            "concept_id": concept_id,
            "concept_name": names.get(concept_id, concept_id),
            "source_id": f"{provenance['provider']}.concept_graph",
            "source_as_of": provenance["snapshot_date"],
            "source_snapshot_date": provenance["snapshot_date"],
            "coverage_digest": provenance["coverage_digest"],
            "membership_source": provenance["raw_membership_source"],
        }
        for concept_id in full.get(str(ts_code), [])
    ]
    themes = []
    for theme in taxonomy["canonical_themes"]:
        excluded_ids = set(theme.get("excluded_raw_concept_ids") or [])
        excluded_names = {_normalise(item) for item in (theme.get("excluded_raw_concept_names") or [])}
        included_ids = list(theme.get("included_raw_concept_ids") or [])
        included_names = list(theme.get("included_raw_concept_names") or [])
        matched = [
            item for item in raw
            if item["concept_id"] not in excluded_ids
            and _normalise(item["concept_name"]) not in excluded_names
            and _matches(item, included_ids + included_names)
        ]
        if not matched:
            continue
        subthemes = []
        for subtheme in theme.get("subthemes") or []:
            sub_matched = [
                item for item in matched
                if _matches(item, list(subtheme.get("included_raw_concept_ids") or [])
                            + list(subtheme.get("included_raw_concept_names") or []))
            ]
            if sub_matched:
                subthemes.append({"subtheme_id": subtheme["subtheme_id"], "name": subtheme["name"],
                                  "matched_raw_concept_ids": [item["concept_id"] for item in sub_matched]})
        role, confidence, evidence, unavailable = _validated_role_evidence(
            business_evidence, str(ts_code), as_of, run_date=run_date,
        )
        themes.append({
            "theme_id": theme["theme_id"],
            "name_cn": theme["name_cn"],
            "name_en": theme["name_en"],
            "status": theme["status"],
            "matched_raw_concepts": matched,
            "matched_subthemes": subthemes,
            "role": role,
            "role_confidence": confidence,
            "classification_basis": ("registry_membership_and_structured_business_evidence"
                                     if evidence else "registry_membership_proxy_only"),
            "business_evidence": evidence,
            "coverage_status": "checked" if evidence else "unknown_or_unavailable",
            "unknown_reason": unavailable,
            "production_effect_enabled": False,
            "automatic_promotion": False,
        })
    primary = themes[0]["theme_id"] if themes else None
    return {
        "taxonomy_schema_name": taxonomy["schema_name"],
        "taxonomy_schema_version": taxonomy["schema_version"],
        "taxonomy_configuration_fingerprint": configuration_fingerprint(taxonomy),
        # The taxonomy is a non-price source.  Its source clock is the actual
        # L3 receipt date, not the decision/cohort label supplied by the caller.
        "source_as_of": provenance["snapshot_date"],
        "l3_provenance": provenance,
        "raw_concepts": raw,
        "canonical_themes": themes,
        "primary_canonical_theme_id": primary,
        "production_effect_enabled": False,
        "automatic_promotion": False,
    }


def taxonomy_by_code(pool_df: pd.DataFrame, *, stock_concepts: dict | None,
                     concept_members: dict | None, concepts_df: Any, as_of: str,
                     taxonomy: dict | None = None,
                     business_evidence_by_code: dict[str, list[dict]] | None = None,
                     l3_provider: Any = None, l3_snapshot_date: Any = None,
                     l3_coverage: Any = None, run_date: Any = None) -> dict[str, dict]:
    taxonomy = taxonomy or load_theme_taxonomy()
    return {
        str(code): classify_theme_taxonomy(
            ts_code=str(code), stock_concepts=stock_concepts, concept_members=concept_members,
            concepts_df=concepts_df, as_of=as_of, taxonomy=taxonomy,
            business_evidence=(business_evidence_by_code or {}).get(str(code)),
            l3_provider=l3_provider,
            l3_snapshot_date=l3_snapshot_date,
            l3_coverage=l3_coverage,
            run_date=run_date,
        )
        for code in pool_df.get("ts_code", pd.Series(dtype=str)).astype(str).tolist()
    }

