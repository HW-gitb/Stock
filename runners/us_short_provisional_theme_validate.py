# -*- coding: utf-8 -*-
"""Offline validator for the US-short provisional cross-industry discovery lane.

This is knife 2 only: it consumes the knife-1 discovery artifact, a same-decision-date
Pass1 universe artifact, and a same-decision-date SEC-SIC classification packet.  It
never calls a provider and emits an inert validation artifact; scoring, Top15, operation
advice, seats, theme_probe, and lifecycle actions remain disabled by schema constants.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
import re
from datetime import date, datetime, time as datetime_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance  # noqa: E402
from engine.us_short_persisted_text_safety import persisted_text_violation  # noqa: E402
from engine.us_short_schema_formats import FORMAT_CHECKER  # noqa: E402
from runners.us_short_discovery_publish_policy import (  # noqa: E402
    DiscoveryPublishPolicyError,
    _serialized_sha256,
    validate_exact_decision_slot,
    write_immutable_json,
)
from runners import us_short_llm_theme_discovery as discovery_writer  # noqa: E402
from runners import us_short_universe_fetch  # noqa: E402

SCHEMA_PATH = ROOT / "schemas" / "us_short_provisional_theme_validation.schema.json"
DISCOVERY_SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery.schema.json"
CLASSIFICATION_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_universe_sector_classification_packet.schema.json"
GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
CONFORMANCE_GUARDS = ("_guard_discovery_digest",)
STATE_DIR = ROOT / "state" / "us_short"
DEFAULT_CLASSIFICATION_PATH = STATE_DIR / "us_short_full_universe_sector_classification_packet.json"
NEW_YORK = ZoneInfo("America/New_York")
MIN_THEME_MEMBERS = 3
MAX_THEMES = 8


class ProvisionalThemeValidationError(ValueError):
    """An input artifact cannot be consumed without guessing."""


def _read_json(path: Path) -> tuple[Any, str]:
    try:
        raw = path.read_bytes()
        return json.loads(raw.decode("utf-8")), hashlib.sha256(raw).hexdigest()
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ProvisionalThemeValidationError(f"cannot read JSON artifact: {path}") from exc


def _write_atomic(payload: dict[str, Any], path: Path) -> bool:
    """Publish through the lane's single write door; a frozen peer must still satisfy this schema."""
    try:
        return write_immutable_json(
            payload, path,
            verify=lambda existing: _schema_validate(existing, SCHEMA_PATH, "existing validation receipt"),
        )
    except DiscoveryPublishPolicyError as exc:
        raise ProvisionalThemeValidationError(str(exc)) from exc
    except (ValueError, OverflowError) as exc:
        raise ProvisionalThemeValidationError(f"cannot atomically write output: {path}") from exc


def _repo_path(value: Path | str, *, field: str) -> Path:
    raw = Path(value)
    resolved = (raw if raw.is_absolute() else ROOT / raw).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ProvisionalThemeValidationError(f"{field} must stay under repository root") from exc
    return resolved


def _input_path(value: Path | str, *, field: str) -> Path:
    path = _repo_path(value, field=field)
    if not path.is_file():
        raise ProvisionalThemeValidationError(f"{field} must be an existing file")
    return path


def _output_path(value: Path | str, *, expected_path: Path) -> Path:
    try:
        return validate_exact_decision_slot(value, expected_path, root=ROOT, state_dir=STATE_DIR)
    except DiscoveryPublishPolicyError as exc:
        raise ProvisionalThemeValidationError(str(exc)) from exc


def _schema_validate(payload: Any, schema_path: Path, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise ProvisionalThemeValidationError("jsonschema is required; refusing schema bypass") from exc
    schema, _ = _read_json(schema_path)
    errors = sorted(
        Draft7Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(payload),
        key=lambda error: list(error.path),
    )
    if errors:
        raise ProvisionalThemeValidationError(f"{label} schema rejected {len(errors)} field(s): {errors[0].message}")


def _parse_instant(value: Any, field: str) -> datetime:
    if type(value) is not str:
        raise ProvisionalThemeValidationError(f"{field} must be timezone-aware RFC3339")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ProvisionalThemeValidationError(f"{field} must be timezone-aware RFC3339") from exc
    if parsed.tzinfo is None:
        raise ProvisionalThemeValidationError(f"{field} must be timezone-aware RFC3339")
    return parsed


def _open_et(decision_date: str) -> datetime:
    try:
        opened = datetime.combine(datetime.strptime(decision_date, "%Y%m%d").date(), datetime_time(9, 30), NEW_YORK)
    except ValueError as exc:
        raise ProvisionalThemeValidationError("expected_decision_date must be YYYYMMDD") from exc
    return opened


def default_output_path(expected_decision_date: str) -> Path:
    """Return this validator's only immutable slot for one decision date."""
    _open_et(expected_decision_date)
    return STATE_DIR / f"us_short_provisional_theme_validation_{expected_decision_date}.json"


def default_discovery_path(expected_decision_date: str) -> Path:
    """Use knife-1's own date-keyed writer helper; never invent a reader slot."""
    return discovery_writer.default_output_path(expected_decision_date)


def default_candidate_path(expected_decision_date: str) -> Path:
    """Use the candidate writer's canonical decision-date-bound output slot."""
    return us_short_universe_fetch.default_candidate_path(expected_decision_date)


def _canonical_map(values: dict[str, Any], *, field: str, allowed: set[str] | None = None) -> dict[str, Any]:
    if type(values) is not dict:
        raise ProvisionalThemeValidationError(f"{field} must be an object")
    out: dict[str, Any] = {}
    for raw_key, value in values.items():
        ticker = canonical_us_ticker(raw_key)
        if ticker is None:
            raise ProvisionalThemeValidationError(f"{field} has a non-canonical US ticker")
        if ticker in out:
            raise ProvisionalThemeValidationError(f"{field} has duplicate canonical ticker: {ticker}")
        if allowed is not None and ticker not in allowed:
            raise ProvisionalThemeValidationError(f"{field} has a ticker outside the eligible universe: {ticker}")
        out[ticker] = value
    return out


def _validate_discovery_bindings(discovery: dict[str, Any], expected_date: str) -> None:
    cutoff = _open_et(expected_date)
    refs = discovery["source_refs"]
    ref_times: dict[str, datetime] = {}
    ref_types: dict[str, str] = {}
    for ref in refs:
        source_id = ref["source_id"]
        if source_id in ref_times:
            raise ProvisionalThemeValidationError(f"discovery source_refs contains duplicate source_id: {source_id}")
        ref_times[source_id] = _parse_instant(ref["observed_at"], f"source_refs[{source_id}].observed_at")
        ref_types[source_id] = ref["source_type"]
        if ref_times[source_id] >= cutoff:
            raise ProvisionalThemeValidationError(f"source {source_id} is not before the decision open")
    seen_themes: set[str] = set()
    for theme in discovery["themes"]:
        theme_id = theme["theme_id"]
        if theme_id in seen_themes:
            raise ProvisionalThemeValidationError(f"discovery contains duplicate theme_id: {theme_id}")
        seen_themes.add(theme_id)
        theme_time = _parse_instant(theme["observed_at"], f"themes[{theme_id}].observed_at")
        if theme_time >= cutoff:
            raise ProvisionalThemeValidationError(f"theme {theme_id} is not before the decision open")
        theme_refs = set(theme["source_ref_ids"])
        if len(theme_refs) != len(theme["source_ref_ids"]):
            raise ProvisionalThemeValidationError(f"theme {theme_id} contains duplicate source_ref_id")
        if not theme_refs or not theme_refs.issubset(ref_times):
            raise ProvisionalThemeValidationError(f"theme {theme_id} has an unbound source_ref_id")
        if any(ref_times[ref_id] > theme_time for ref_id in theme_refs):
            raise ProvisionalThemeValidationError(f"theme {theme_id} cites a source after theme observation")
        # Member-level identity/source-quality defects are intentionally handled by
        # validate_provisional_themes so one bad member cannot kill an otherwise usable theme.


def _load_inputs(
    discovery_path: Path, candidate_path: Path, classification_path: Path, expected_date: str
) -> dict[str, Any]:
    discovery, discovery_hash = _read_json(discovery_path)
    try:
        canonical_discovery_hash = _serialized_sha256(discovery)
    except DiscoveryPublishPolicyError as exc:
        raise ProvisionalThemeValidationError(
            "discovery artifact cannot be serialized safely"
        ) from exc
    inputs = load_inputs_from_discovery(
        discovery=discovery,
        discovery_sha256=canonical_discovery_hash,
        candidate_path=candidate_path,
        classification_path=classification_path,
        expected_date=expected_date,
    )
    inputs["hashes"]["discovery"] = discovery_hash
    return inputs


def _guard_discovery_digest(discovery: dict[str, Any], discovery_sha256: Any) -> None:
    if (
        type(discovery_sha256) is not str
        or re.fullmatch(r"[0-9a-f]{64}", discovery_sha256) is None
        or discovery_sha256 != _serialized_sha256(discovery)
    ):
        raise ProvisionalThemeValidationError("discovery artifact digest is invalid or does not bind its payload")


def load_inputs_from_discovery(
    *,
    discovery: dict[str, Any],
    discovery_sha256: str,
    candidate_path: Path,
    classification_path: Path,
    expected_date: str,
) -> dict[str, Any]:
    """Validate Knife1 in memory with the same Knife2 gates used by the file runner."""
    _schema_validate(discovery, DISCOVERY_SCHEMA_PATH, "discovery artifact")
    if discovery["decision_clock"]["expected_decision_date"] != expected_date:
        raise ProvisionalThemeValidationError("discovery decision date does not match expected_decision_date")
    _validate_discovery_bindings(discovery, expected_date)
    _guard_discovery_digest(discovery, discovery_sha256)

    candidate, candidate_hash = _read_json(candidate_path)
    try:
        candidate = us_short_universe_fetch.validate_candidate_artifact(
            candidate, expected_decision_date=expected_date,
            governance=load_eligibility_governance(GOVERNANCE_PATH),
        )
    except Exception as exc:
        raise ProvisionalThemeValidationError(f"candidate artifact failed its canonical validator: {exc}") from exc

    classification, classification_hash = _read_json(classification_path)
    _schema_validate(classification, CLASSIFICATION_SCHEMA_PATH, "classification packet")
    clock = classification["decision_clock"]
    if clock["expected_decision_date"] != expected_date:
        raise ProvisionalThemeValidationError("classification decision date does not match expected_decision_date")
    if clock["candidate_price_basis_date"] != candidate["price_basis_date"]:
        raise ProvisionalThemeValidationError("classification candidate_price_basis_date does not match candidate")
    if clock["price_basis_date"] != candidate["used_date"]:
        raise ProvisionalThemeValidationError("classification price_basis_date does not match candidate used_date")
    if clock["source_as_of"] != classification["classification_contract"]["as_of"]:
        raise ProvisionalThemeValidationError("classification source_as_of does not match its contract")
    source_as_of = date.fromisoformat(clock["source_as_of"])
    if source_as_of > datetime.strptime(expected_date, "%Y%m%d").date():
        raise ProvisionalThemeValidationError("classification source_as_of is after the decision date")
    if _parse_instant(
        classification["provenance"]["observed_at"], "classification.provenance.observed_at"
    ) >= _open_et(expected_date):
        raise ProvisionalThemeValidationError("classification observed_at is not before the decision open")

    eligible = set(candidate["eligible_tickers"])
    candidate_tickers = {
        canonical_us_ticker(row["ticker"])
        for row in candidate["rows"]
        if canonical_us_ticker(row["ticker"]) is not None
    }
    candidate_reasons = {
        canonical_us_ticker(row["ticker"]): list(row["reasons"])
        for row in candidate["rows"]
        if canonical_us_ticker(row["ticker"]) is not None
    }
    sectors = _canonical_map(
        classification["sector_by_ticker"], field="classification.sector_by_ticker", allowed=eligible
    )
    return {
        "discovery": discovery, "candidate": candidate, "classification": classification,
        "hashes": {
            "discovery": discovery_sha256,
            "candidate": candidate_hash,
            "classification": classification_hash,
        },
        "eligible": eligible, "universe": candidate_tickers,
        "candidate_reasons": candidate_reasons, "sectors": sectors,
    }


def validate_provisional_themes(
    discovery: dict[str, Any], *, eligible_tickers: set[str], sectors_by_ticker: dict[str, str],
    candidate_tickers: set[str] | None = None,
    candidate_reasons_by_ticker: dict[str, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply the knife-2 member/theme gates without scoring or downstream effects."""
    if candidate_tickers is None:
        candidate_tickers = set(eligible_tickers)
    if candidate_reasons_by_ticker is None:
        candidate_reasons_by_ticker = {}
    source_types = {ref["source_id"]: ref["source_type"] for ref in discovery["source_refs"]}
    accepted: list[dict[str, Any]] = []
    drops: list[dict[str, Any]] = []
    def canonical_industry_code(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = unicodedata.normalize("NFKC", value).strip().upper()
        return normalized if re.fullmatch(r"[0-9]{2}", normalized) else None

    for raw_theme in discovery["themes"]:
        theme_id = raw_theme["theme_id"]
        members: list[dict[str, Any]] = []
        seen_tickers: set[str] = set()
        for raw_member in raw_theme["members"]:
            ticker = canonical_us_ticker(raw_member["ticker"])
            raw_refs = set(raw_member["source_ref_ids"])
            theme_refs = set(raw_theme["source_ref_ids"])
            refs = [ref for ref in raw_member["source_ref_ids"] if ref in theme_refs]
            types = {source_types.get(ref) for ref in refs}
            reason = None
            if ticker is None:
                reason = "invalid_canonical_us_ticker"
            elif ticker in seen_tickers:
                reason = "duplicate_member_ticker"
            elif not raw_refs or not raw_refs.issubset(theme_refs):
                reason = "unbound_member_source_ref"
            elif ticker not in candidate_tickers:
                reason = "not_in_same_date_candidate_universe"
            elif ticker not in eligible_tickers:
                reason = "in_same_date_candidate_but_pass1_ineligible"
            elif not ({"web", "x"} & types):
                reason = "missing_independent_web_x_evidence"
            elif ticker not in sectors_by_ticker or canonical_industry_code(sectors_by_ticker[ticker]) is None:
                reason = "missing_sec_sic_classification"
            if reason:
                drop = {
                    "stage": "member", "theme_id": theme_id,
                    "ticker": ticker or str(raw_member["ticker"]), "reason": reason,
                    "source_ref_ids": sorted(raw_refs),
                }
                if reason == "in_same_date_candidate_but_pass1_ineligible":
                    drop["candidate_reasons"] = list(candidate_reasons_by_ticker.get(ticker, []))
                drops.append(drop)
                continue
            seen_tickers.add(ticker)
            evidence_tier = "both" if {"web", "x"}.issubset(types) else "single"
            members.append({
                "ticker": ticker, "membership_status": "provisional_validated",
                "source_ref_ids": sorted(set(refs)),
                "source_types": sorted({kind for kind in types if kind in {"web", "x"}}),
                "evidence_tier": evidence_tier,
                "industry_code": canonical_industry_code(sectors_by_ticker[ticker]),
                "industry_source": "sec_sic_major_group",
            })
        members.sort(key=lambda row: row["ticker"])
        semantic_assertions = raw_theme.get("semantic_assertions")
        early_negative_assertion_indexes: set[int] = set()
        if isinstance(semantic_assertions, list):
            for assertion_index, assertion in enumerate(semantic_assertions):
                if not isinstance(assertion, dict):
                    continue
                basis = assertion.get("basis")
                if basis is not None and basis != "shared_commercial_driver":
                    early_negative_assertion_indexes.add(assertion_index)
                    drops.append({
                        "stage": "theme", "theme_id": theme_id,
                        "reason": "semantic_basis_not_shared_commercial_driver",
                        "detail": f"assertion[{assertion_index}]:{basis}",
                    })
            if early_negative_assertion_indexes and not any(
                isinstance(assertion, dict)
                and assertion.get("basis") == "shared_commercial_driver"
                for assertion in semantic_assertions
            ):
                continue
        # Positive assertions keep the production structural gates first. An explicit negative
        # basis was recorded above before those gates, without changing multi-assertion behavior.
        structural_industry_codes = sorted({row["industry_code"] for row in members})
        if len(members) < MIN_THEME_MEMBERS:
            drops.append({"stage": "theme", "theme_id": theme_id, "reason": "fewer_than_3_qualified_members"})
            continue
        if len(structural_industry_codes) < 2:
            drops.append({"stage": "theme", "theme_id": theme_id, "reason": "fewer_than_2_sec_sic_industries"})
            continue
        semantic_validation: dict[str, Any] | None = None
        if "semantic_assertions" in raw_theme:
            if type(raw_theme.get("semantic_assertions")) is not list:
                drops.append({
                    "stage": "theme", "theme_id": theme_id,
                    "reason": "semantic_assertion_malformed_or_unbound",
                    "detail": "semantic_assertions",
                })
                continue
            raw_member_ref_ids = {
                canonical_us_ticker(raw_member.get("ticker")): set(raw_member.get("source_ref_ids", []))
                for raw_member in raw_theme["members"]
                if isinstance(raw_member, dict)
                and canonical_us_ticker(raw_member.get("ticker")) is not None
                and isinstance(raw_member.get("source_ref_ids"), list)
            }
            qualified_by_ticker = {member["ticker"]: member for member in members}
            theme_ref_ids = set(raw_theme["source_ref_ids"])
            passing_assertions: list[dict[str, Any]] = []
            for assertion_index, assertion in enumerate(raw_theme.get("semantic_assertions", [])):
                detail = f"assertion[{assertion_index}]"
                if type(assertion) is not dict:
                    drops.append({"stage": "theme", "theme_id": theme_id, "reason": "semantic_assertion_malformed_or_unbound", "detail": detail})
                    continue
                basis = assertion.get("basis")
                if assertion_index in early_negative_assertion_indexes:
                    continue
                if basis != "shared_commercial_driver":
                    drops.append({"stage": "theme", "theme_id": theme_id, "reason": "semantic_basis_not_shared_commercial_driver", "detail": f"{detail}:{basis}"})
                    continue
                origin_source_type = assertion.get("origin_source_type")
                origin_scope_type = assertion.get("origin_scope_type")
                origin_scope_index = assertion.get("origin_scope_index")
                common = assertion.get("common_driver")
                links = assertion.get("member_links")
                if (
                    origin_source_type not in {"web", "x"}
                    or (origin_source_type == "web" and origin_scope_type != "web_chunk")
                    or (origin_source_type == "x" and origin_scope_type != "x_response")
                    or isinstance(origin_scope_index, bool)
                    or not isinstance(origin_scope_index, int)
                    or origin_scope_index < 0
                    or type(common) is not dict
                    or not isinstance(links, list)
                ):
                    drops.append({"stage": "theme", "theme_id": theme_id, "reason": "semantic_assertion_malformed_or_unbound", "detail": detail})
                    continue
                common_refs = common.get("source_ref_ids")
                if (
                    not isinstance(common_refs, list)
                    or not common_refs
                    or any(
                        ref not in theme_ref_ids or source_types.get(ref) != origin_source_type
                        for ref in common_refs
                    )
                ):
                    drops.append({"stage": "theme", "theme_id": theme_id, "reason": "semantic_assertion_malformed_or_unbound", "detail": f"{detail}:common_refs"})
                    continue
                linked_tickers: list[str] = []
                linked_source_ref_ids: set[str] = set(common_refs)
                malformed = False
                for link in links:
                    if type(link) is not dict:
                        malformed = True
                        break
                    ticker = canonical_us_ticker(link.get("ticker"))
                    link_refs = link.get("source_ref_ids")
                    if (
                        ticker is None or ticker in linked_tickers
                        or ticker not in raw_member_ref_ids
                        or not isinstance(link_refs, list) or not link_refs
                        or any(
                            ref not in theme_ref_ids
                            or ref not in raw_member_ref_ids[ticker]
                            or source_types.get(ref) != origin_source_type
                            for ref in link_refs
                        )
                    ):
                        malformed = True
                        break
                    linked_tickers.append(ticker)
                    linked_source_ref_ids.update(link_refs)
                if malformed:
                    drops.append({"stage": "theme", "theme_id": theme_id, "reason": "semantic_assertion_malformed_or_unbound", "detail": detail})
                    continue
                qualified_linked = sorted(set(linked_tickers) & set(qualified_by_ticker))
                if len(qualified_linked) < MIN_THEME_MEMBERS:
                    drops.append({"stage": "theme", "theme_id": theme_id, "reason": "fewer_than_3_semantically_linked_qualified_members", "detail": detail})
                    continue
                linked_industries = sorted({qualified_by_ticker[ticker]["industry_code"] for ticker in qualified_linked})
                if len(linked_industries) < 2:
                    drops.append({"stage": "theme", "theme_id": theme_id, "reason": "fewer_than_2_semantically_linked_sec_sic_industries", "detail": detail})
                    continue
                passing_assertions.append({
                    "assertion": assertion,
                    "linked_tickers": qualified_linked,
                    "origin_source_type": origin_source_type,
                    "origin_scope_type": origin_scope_type,
                    "origin_scope_index": origin_scope_index,
                    "source_ref_ids": sorted(linked_source_ref_ids),
                })
            if not passing_assertions:
                continue
            final_tickers = sorted({
                ticker for row in passing_assertions for ticker in row["linked_tickers"]
            })
            for member in list(members):
                if member["ticker"] not in final_tickers:
                    drops.append({
                        "stage": "member", "theme_id": theme_id, "ticker": member["ticker"],
                        "reason": "member_not_linked_to_passing_common_driver",
                        "source_ref_ids": list(member["source_ref_ids"]),
                    })
            members = [member for member in members if member["ticker"] in final_tickers]
            for member in members:
                semantic_types = sorted({
                    row["origin_source_type"]
                    for row in passing_assertions
                    if member["ticker"] in row["linked_tickers"]
                })
                member["source_types"] = semantic_types
                member["evidence_tier"] = "both" if set(semantic_types) == {"web", "x"} else "single"
            semantic_industry_codes = sorted({member["industry_code"] for member in members})
            if len(members) < MIN_THEME_MEMBERS:
                drops.append({"stage": "theme", "theme_id": theme_id, "reason": "fewer_than_3_semantically_linked_qualified_members"})
                continue
            if len(semantic_industry_codes) < 2:
                drops.append({"stage": "theme", "theme_id": theme_id, "reason": "fewer_than_2_semantically_linked_sec_sic_industries"})
                continue
            semantic_validation = {
                "status": "validated_shared_commercial_driver",
                "anchor_origin": {
                    "origin_source_type": passing_assertions[0]["origin_source_type"],
                    "origin_scope_type": passing_assertions[0]["origin_scope_type"],
                    "origin_scope_index": passing_assertions[0]["origin_scope_index"],
                },
                "passing_origins": [
                    {
                        "origin_source_type": row["origin_source_type"],
                        "origin_scope_type": row["origin_scope_type"],
                        "origin_scope_index": row["origin_scope_index"],
                        "linked_tickers": row["linked_tickers"],
                    }
                    for row in passing_assertions
                ],
                "semantically_linked_qualified_member_count": len(members),
                "semantically_linked_sec_sic_industry_count": len(semantic_industry_codes),
                "passing_source_ref_ids": sorted({
                    ref_id for row in passing_assertions for ref_id in row["source_ref_ids"]
                }),
                "final_member_tickers": [member["ticker"] for member in members],
            }
        industry_codes = sorted({row["industry_code"] for row in members})
        if len(members) < MIN_THEME_MEMBERS:
            drops.append({"stage": "theme", "theme_id": theme_id, "reason": "fewer_than_3_qualified_members"})
            continue
        if len(industry_codes) < 2:
            drops.append({"stage": "theme", "theme_id": theme_id, "reason": "fewer_than_2_sec_sic_industries"})
            continue
        source_counts = {
            kind: sum(
                kind in (set(member["source_types"]) if semantic_validation is not None else {source_types.get(ref) for ref in member["source_ref_ids"]})
                for member in members
            )
            for kind in ("web", "x")
        }
        source_counts["both"] = sum(member["evidence_tier"] == "both" for member in members)
        accepted_theme = {
            "theme_id": theme_id, "display_name": raw_theme["display_name"], "summary": raw_theme["summary"],
            "status": "provisional_validated", "observed_at": raw_theme["observed_at"],
            "source_ref_ids": sorted(raw_theme["source_ref_ids"]), "members": members,
            "cross_industry_validation_status": "validated_by_sec_sic_major_group",
            "market_confirmation_status": "not_run",
            "validation": {
                "selection_rank": 0, "qualified_member_count": len(members),
                "industry_count": len(industry_codes), "industry_codes": industry_codes,
                "source_type_counts": source_counts,
            },
        }
        if semantic_validation is not None:
            accepted_theme["semantic_validation"] = semantic_validation
        accepted.append(accepted_theme)
    for theme in accepted:
        # Ranking evidence is the union actually retained by validated members.  The theme-level
        # list remains full provenance, so a redundant lane ref pruned from every member cannot
        # re-enter selection through this tie-break.
        member_ref_ids = {
            ref
            for member in theme["members"]
            for ref in member["source_ref_ids"]
        }
        theme["validation"]["distinct_web_x_source_ref_count"] = sum(
            source_types[ref] in {"web", "x"} for ref in member_ref_ids
        )
    # Deterministic, model-confidence-free top-8: more qualified members, then more distinct independent refs,
    # then newest PIT observation, then stable theme id. This is selection bookkeeping, not a score.
    accepted.sort(key=lambda theme: (
        -theme["validation"]["source_type_counts"].get("both", 0),
        -(
            theme["semantic_validation"]["semantically_linked_qualified_member_count"]
            if "semantic_validation" in theme else theme["validation"]["qualified_member_count"]
        ),
        -(
            theme["semantic_validation"]["semantically_linked_sec_sic_industry_count"]
            if "semantic_validation" in theme else theme["validation"]["industry_count"]
        ),
        -theme["validation"]["distinct_web_x_source_ref_count"],
        -_parse_instant(theme["observed_at"], f"themes[{theme['theme_id']}].observed_at").timestamp(),
        theme["theme_id"],
    ))
    for rank, theme in enumerate(accepted, start=1):
        theme["validation"]["selection_rank"] = rank
    for theme in accepted[MAX_THEMES:]:
        drops.append({"stage": "truncation", "theme_id": theme["theme_id"], "reason": "outside_deterministic_top_8"})
    return accepted[:MAX_THEMES], drops


def build_artifact(inputs: dict[str, Any], *, generated_at: str) -> dict[str, Any]:
    generated = _parse_instant(generated_at, "generated_at")
    themes, drops = validate_provisional_themes(
        inputs["discovery"], eligible_tickers=inputs["eligible"],
        candidate_tickers=inputs.get("universe", inputs["eligible"]),
        candidate_reasons_by_ticker=inputs.get("candidate_reasons", {}),
        sectors_by_ticker=inputs["sectors"],
    )
    semantic_mode = any("semantic_assertions" in theme for theme in inputs["discovery"]["themes"])
    payload = {
        "schema_name": "us_short_provisional_theme_validation",
        "schema_version": "1.2.0" if semantic_mode else "1.1.0",
        "generated_at": generated.isoformat(),
        "decision_clock": {
            "expected_decision_date": inputs["candidate"]["decision_date"],
            "candidate_price_basis_date": inputs["candidate"]["price_basis_date"],
            "universe_used_date": inputs["candidate"]["used_date"],
            "classification_source_as_of": inputs["classification"]["decision_clock"]["source_as_of"],
            "cutoff_policy": "before_decision_open_et", "pit_enforced": True,
        },
        "validation_contract": {
            "producer_kind": "provisional_theme_validate", "input_mode": "offline_local_artifacts",
            "membership_status": "provisional_validated", "market_confirmation_status": "not_run",
            "scoring_eligible": False, "top15_effect_enabled": False,
            "operation_advice_effect_enabled": False, "dynamic_seats_enabled": False,
            "theme_probe_enabled": False, "lifecycle_actions_enabled": False,
        },
        "input_artifacts": {
            "discovery_artifact_sha256": inputs["hashes"]["discovery"],
            "candidate_artifact_sha256": inputs["hashes"]["candidate"],
            "classification_packet_sha256": inputs["hashes"]["classification"],
            "eligible_ticker_count": len(inputs["eligible"]), "classification_ticker_count": len(inputs["sectors"]),
        },
        "source_ref_types": {
            ref["source_id"]: ref["source_type"] for ref in inputs["discovery"]["source_refs"]
        },
        "themes": themes, "drop_ledger": drops,
        "summary": {
            "discovered_theme_count": len(inputs["discovery"]["themes"]), "validated_theme_count": len(themes),
            "validated_member_count": sum(len(theme["members"]) for theme in themes),
            "rejected_theme_count": sum(1 for row in drops if row["stage"] == "theme"),
            "dropped_member_count": sum(1 for row in drops if row["stage"] == "member"),
            "truncated_theme_count": sum(1 for row in drops if row["stage"] == "truncation"),
        },
    }
    if persisted_text_violation(payload) is not None:
        raise ProvisionalThemeValidationError("validation artifact contains forbidden credential-like text")
    _schema_validate(payload, SCHEMA_PATH, "validation artifact")
    return payload


def run_preflight(
    *, discovery_path: Path | None = None,
    candidate_path: Path | None = None,
    classification_path: Path = DEFAULT_CLASSIFICATION_PATH,
    output_path: Path | None = None,
    expected_decision_date: str,
    generated_at: str,
) -> dict[str, Any]:
    paths = [
        _input_path(discovery_path or default_discovery_path(expected_decision_date), field="discovery_path"),
        _input_path(candidate_path or default_candidate_path(expected_decision_date), field="candidate_path"),
        _input_path(classification_path, field="classification_path"),
    ]
    expected_output = default_output_path(expected_decision_date)
    output = _output_path(output_path or expected_output, expected_path=expected_output)
    artifact = build_artifact(_load_inputs(*paths, expected_decision_date), generated_at=generated_at)
    return {
        "schema_name": "us_short_provisional_theme_validation_preflight", "schema_version": "1.0.0",
        "status": "offline_preflight_passed", "network_access_performed": False,
        "provider_calls_performed": False, "scoring_or_top15_effect": False,
        "operation_advice_effect": False, "output_written": False,
        "output_path": output.resolve().relative_to(ROOT.resolve()).as_posix(),
        "validated_theme_count": len(artifact["themes"]),
        "validated_member_count": artifact["summary"]["validated_member_count"],
    }


def run_packet(
    *, discovery_path: Path | None = None,
    candidate_path: Path | None = None,
    classification_path: Path = DEFAULT_CLASSIFICATION_PATH,
    output_path: Path | None = None,
    expected_decision_date: str,
    generated_at: str,
) -> dict[str, Any]:
    paths = [
        _input_path(discovery_path or default_discovery_path(expected_decision_date), field="discovery_path"),
        _input_path(candidate_path or default_candidate_path(expected_decision_date), field="candidate_path"),
        _input_path(classification_path, field="classification_path"),
    ]
    expected_output = default_output_path(expected_decision_date)
    output = _output_path(output_path or expected_output, expected_path=expected_output)
    artifact = build_artifact(_load_inputs(*paths, expected_decision_date), generated_at=generated_at)
    reused = _write_atomic(artifact, output)
    return {
        "schema_name": "us_short_provisional_theme_validation_execution_summary", "schema_version": "1.0.0",
        "status": "offline_validation_artifact_reused" if reused else "offline_validation_artifact_written",
        "network_access_performed": False,
        "provider_calls_performed": False, "scoring_or_top15_effect": False,
        "operation_advice_effect": False,
        "output_path": output.resolve().relative_to(ROOT.resolve()).as_posix(),
        "validated_theme_count": len(artifact["themes"]),
        "validated_member_count": artifact["summary"]["validated_member_count"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate an offline US-short provisional theme artifact.")
    parser.add_argument("--discovery-path", type=Path)
    parser.add_argument("--candidate-path", type=Path)
    parser.add_argument("--classification-path", type=Path, default=DEFAULT_CLASSIFICATION_PATH)
    parser.add_argument("--output-path", type=Path)
    parser.add_argument("--expected-decision-date", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    kwargs = {
        "discovery_path": args.discovery_path, "candidate_path": args.candidate_path,
        "classification_path": args.classification_path, "output_path": args.output_path,
        "expected_decision_date": args.expected_decision_date, "generated_at": args.generated_at,
    }
    result = run_preflight(**kwargs) if args.preflight_only else run_packet(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
