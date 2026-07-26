"""Pure validator/mapper for the knife-2 provisional-theme soft boost.

The validation artifact is the only source of boost eligibility.  A ``both`` member
gets 5 points, a ``single`` member gets 2, and memberships across themes take the
maximum once per ticker.  This module never changes seats, theme momentum, lifecycle,
or any downstream safety gate.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any

from engine.us_short_eligibility_gate import canonical_us_ticker
from engine.us_short_schema_formats import FORMAT_CHECKER

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "us_short_provisional_theme_validation.schema.json"
TIER_POINTS = {"both": 5.0, "single": 2.0}
BOOST_CAP = 5.0


def _canonical_industry_code(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKC", value).strip().upper()
    return normalized if re.fullmatch(r"[0-9]{2}", normalized) else None


class ProvisionalThemeBoostError(ValueError):
    """Malformed validation artifact or boost target identity."""


_DIGEST_KEYS = ("discovery_artifact_sha256", "candidate_artifact_sha256", "classification_packet_sha256")


def validate_provisional_theme_artifact_identity(
    artifact: dict[str, Any], *, expected_decision_date: str | None = None,
    expected_input_digests: dict[str, str] | None = None,
) -> None:
    """Validate the identity fields that a consumer must not silently bypass."""
    clock = artifact.get("decision_clock")
    inputs = artifact.get("input_artifacts")
    if not isinstance(clock, dict) or not isinstance(inputs, dict):
        raise ProvisionalThemeBoostError("validation artifact identity fields are missing")
    actual_date = clock.get("expected_decision_date")
    if not isinstance(actual_date, str) or re.fullmatch(r"[0-9]{8}", actual_date) is None:
        raise ProvisionalThemeBoostError("validation artifact decision date is malformed")
    if expected_decision_date is not None and actual_date != expected_decision_date:
        raise ProvisionalThemeBoostError("validation artifact decision date does not match the consumer run")
    actual_digests: dict[str, str] = {}
    for key in _DIGEST_KEYS:
        value = inputs.get(key)
        if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None or value == "0" * 64:
            raise ProvisionalThemeBoostError(f"validation artifact digest is malformed: {key}")
        actual_digests[key] = value
    if expected_input_digests is not None:
        if type(expected_input_digests) is not dict or set(expected_input_digests) != set(_DIGEST_KEYS):
            raise ProvisionalThemeBoostError("consumer input digests must cover discovery/candidate/classification")
        if any(expected_input_digests[key] != actual_digests[key] for key in _DIGEST_KEYS):
            raise ProvisionalThemeBoostError("validation artifact input digests do not match the consumer run")


def _schema_validate(artifact: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise ProvisionalThemeBoostError("jsonschema is required for provisional theme boost") from exc
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    # The consumer gate must be at least as strict as the producer's: an unarmed validator here
    # accepted `generated_at="banana"` that knife-2 refuses (K3-R48).
    errors = sorted(
        Draft7Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(artifact),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ProvisionalThemeBoostError(f"validation artifact schema rejected: {errors[0].message}")


def _targets(target_tickers: list[str] | tuple[str, ...]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in target_tickers:
        ticker = canonical_us_ticker(raw)
        if ticker is None or ticker in seen:
            raise ProvisionalThemeBoostError(f"invalid or duplicate target ticker: {raw!r}")
        seen.add(ticker)
        out.append(ticker)
    return out


def validate_provisional_theme_boost_record(
    record: dict[str, Any], *, expected_decision_date: str | None = None,
    expected_input_digests: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Validate the bound per-ticker record carried across the score/analysis seam."""
    if type(record) is not dict:
        raise ProvisionalThemeBoostError("provisional theme boost record must be an exact dict")
    expected_keys = {
        "theme_soft_boost", "evidence_tier", "validated_theme_ids", "source_ref_ids", "observed_at",
        "validation_identity", "boost_applied",
    }
    if set(record) != expected_keys:
        raise ProvisionalThemeBoostError("provisional theme boost record keys malformed")
    points = record["theme_soft_boost"]
    if (isinstance(points, bool) or not isinstance(points, (int, float))
            or not math.isfinite(float(points)) or not 0.0 <= float(points) <= BOOST_CAP):
        raise ProvisionalThemeBoostError("provisional theme boost points malformed")
    tier = record["evidence_tier"]
    if type(record["boost_applied"]) is not bool:
        raise ProvisionalThemeBoostError("provisional theme boost applied flag malformed")
    if tier not in (None, "single", "both"):
        raise ProvisionalThemeBoostError("provisional theme boost evidence tier malformed")
    expected_points = {None: 0.0, "single": 2.0, "both": 5.0}[tier]
    if record["boost_applied"] and abs(float(points) - expected_points) > 1e-9:
        raise ProvisionalThemeBoostError("provisional theme boost tier/points mismatch")
    if not record["boost_applied"] and (float(points) != 0.0 or tier is not None):
        raise ProvisionalThemeBoostError("suppressed provisional theme boost must be zero and untiered")
    for field in ("validated_theme_ids", "source_ref_ids"):
        values = record[field]
        if (not isinstance(values, list) or any(not isinstance(value, str) for value in values)
                or len(values) != len(set(values))):
            raise ProvisionalThemeBoostError(f"provisional theme boost {field} malformed")
    observed_at = record["observed_at"]
    if observed_at is not None and not isinstance(observed_at, str):
        raise ProvisionalThemeBoostError("provisional theme boost observed_at malformed")
    if record["boost_applied"] and tier is None and (record["validated_theme_ids"] or record["source_ref_ids"] or observed_at is not None):
        raise ProvisionalThemeBoostError("zero provisional theme boost cannot carry provenance")
    identity = record["validation_identity"]
    if type(identity) is not dict or set(identity) != {"expected_decision_date", "input_digests"}:
        raise ProvisionalThemeBoostError("provisional theme boost validation identity malformed")
    actual_digests = identity["input_digests"]
    if type(actual_digests) is not dict or set(actual_digests) != set(_DIGEST_KEYS):
        raise ProvisionalThemeBoostError("provisional theme boost input digests malformed")
    validate_provisional_theme_artifact_identity(
        {"decision_clock": {"expected_decision_date": identity["expected_decision_date"]},
         "input_artifacts": actual_digests},
        expected_decision_date=expected_decision_date, expected_input_digests=expected_input_digests,
    )
    return record


def build_provisional_theme_boost_map(
    artifact: dict[str, Any], *, target_tickers: list[str] | tuple[str, ...],
    expected_decision_date: str | None = None,
    expected_input_digests: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Return one fail-closed, auditable boost record per target ticker."""
    _schema_validate(artifact)
    validate_provisional_theme_artifact_identity(
        artifact, expected_decision_date=expected_decision_date, expected_input_digests=expected_input_digests,
    )
    source_ref_types = artifact["source_ref_types"]
    if type(source_ref_types) is not dict:
        raise ProvisionalThemeBoostError("validation artifact source_ref_types is malformed")
    if any(isinstance(ref, str) and "://" in ref for ref in source_ref_types):
        raise ProvisionalThemeBoostError("validation artifact source_ref_types must use opaque source IDs, not locators")
    identity = {
        "expected_decision_date": artifact["decision_clock"]["expected_decision_date"],
        "input_digests": {key: artifact["input_artifacts"][key] for key in _DIGEST_KEYS},
    }
    targets = _targets(target_tickers)
    target_set = set(targets)
    out = {
        ticker: {
            "theme_soft_boost": 0.0, "evidence_tier": None,
            "validated_theme_ids": [], "source_ref_ids": [], "observed_at": None,
            "validation_identity": identity, "boost_applied": True,
        }
        for ticker in targets
    }
    seen_theme_ids: set[str] = set()
    for theme in artifact["themes"]:
        theme_id = theme["theme_id"]
        if theme_id in seen_theme_ids:
            raise ProvisionalThemeBoostError(f"duplicate validated theme_id: {theme_id}")
        seen_theme_ids.add(theme_id)
        theme_refs = set(theme["source_ref_ids"])
        if len(theme_refs) != len(theme["source_ref_ids"]):
            raise ProvisionalThemeBoostError(f"duplicate source_ref_id in validated theme: {theme_id}")
        expected_industry_values = [_canonical_industry_code(code) for code in theme["validation"]["industry_codes"]]
        member_industry_values = [_canonical_industry_code(member_row["industry_code"]) for member_row in theme["members"]]
        if any(code is None for code in (*expected_industry_values, *member_industry_values)):
            raise ProvisionalThemeBoostError(f"validated theme industry code is malformed: {theme_id}")
        expected_industries = sorted(set(expected_industry_values))
        member_industries = sorted(set(member_industry_values))
        if expected_industries != member_industries or len(expected_industries) < 2:
            raise ProvisionalThemeBoostError(f"validated theme industry evidence is inconsistent: {theme_id}")
        seen_member_tickers: set[str] = set()
        for member in theme["members"]:
            ticker = canonical_us_ticker(member["ticker"])
            if ticker is None or ticker not in target_set:
                continue
            if ticker in seen_member_tickers:
                raise ProvisionalThemeBoostError(f"duplicate validated member ticker in theme: {ticker}")
            seen_member_tickers.add(ticker)
            member_refs = set(member["source_ref_ids"])
            if not member_refs.issubset(theme_refs):
                raise ProvisionalThemeBoostError(f"validated member source refs are not bound to theme: {ticker}")
            tier = member["evidence_tier"]
            source_types = set(member["source_types"])
            if any(ref not in source_ref_types for ref in member_refs):
                raise ProvisionalThemeBoostError(f"validated member source type binding is missing: {ticker}")
            bound_types = {source_ref_types[ref] for ref in member_refs}
            independent_bound_types = bound_types & {"web", "x"}
            if independent_bound_types != source_types:
                raise ProvisionalThemeBoostError(
                    f"validated member source type binding mismatch for {ticker}: "
                    f"{sorted(independent_bound_types)!r} vs {sorted(source_types)!r}"
                )
            expected_tier = "both" if source_types == {"web", "x"} else "single" if len(source_types) == 1 else None
            if expected_tier != tier:
                raise ProvisionalThemeBoostError(
                    f"evidence tier/source type mismatch for {ticker}: {tier!r} vs {sorted(source_types)!r}"
                )
            points = TIER_POINTS[tier]
            current = out[ticker]
            if points > float(current["theme_soft_boost"]):
                current["theme_soft_boost"] = points
                current["evidence_tier"] = tier
            elif points == float(current["theme_soft_boost"]) and current["evidence_tier"] is None:
                current["evidence_tier"] = tier
            current["validated_theme_ids"].append(theme_id)
            current["source_ref_ids"].extend(member["source_ref_ids"])
            observed_at = theme["observed_at"]
            if current["observed_at"] is None or observed_at > current["observed_at"]:
                current["observed_at"] = observed_at
    for record in out.values():
        record["validated_theme_ids"] = sorted(set(record["validated_theme_ids"]))
        record["source_ref_ids"] = sorted(set(record["source_ref_ids"]))
        if not math.isfinite(float(record["theme_soft_boost"])) or not 0.0 <= float(record["theme_soft_boost"]) <= BOOST_CAP:
            raise ProvisionalThemeBoostError("provisional theme boost exceeded the hard cap")
        validate_provisional_theme_boost_record(record)
    return out
