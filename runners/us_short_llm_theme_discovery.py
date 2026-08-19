# -*- coding: utf-8 -*-
"""Offline US-short LLM theme-discovery producer (first knife only).

This runner consumes a caller-supplied local LLM/web/X discovery packet and freezes a
PIT-bound, source-bound provisional theme list.  It never calls a provider, assigns a
market-confirmed member, computes market validation, changes scoring/Top15/action advice,
or enables seats, theme probes, or lifecycle actions.  The output is an interface artifact
for the later soft-score knife; it is deliberately not a theme projection consumer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, time as datetime_time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import canonical_us_ticker  # noqa: E402
from engine.us_short_persisted_text_safety import SECRET_TEXT_RE, persisted_text_violation  # noqa: E402
from engine.us_short_schema_formats import FORMAT_CHECKER  # noqa: E402
from runners.us_short_discovery_publish_policy import (  # noqa: E402
    DiscoveryPublishPolicyError,
    validate_exact_decision_slot,
    write_immutable_json,
)


SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery.schema.json"
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
DEFAULT_INPUT_PATH = STATE_US_SHORT_DIR / "us_short_llm_theme_discovery_input.json"
SAFE_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{1,127}$")
KNIFE1_SOURCE_REF_KEYS = ("source_id", "source_type", "observed_at")
THEME_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
SEMANTIC_BASIS_VALUES = {
    "shared_commercial_driver",
    "category_trend_membership",
    "shared_event_bucket",
    "market_wide_move",
    "issuer_specific_collection",
    "insufficient_evidence",
}
SEMANTIC_ROLES = {
    "supplier",
    "customer",
    "beneficiary",
    "enabler",
    "competitor",
    "substitute",
    "exposed_operator",
    "other_linked_role",
}
SEMANTIC_ORIGIN_SCOPE_TYPES = {"web_chunk", "x_response"}
SEMANTIC_DISCOVERY_SCHEMA_VERSION = "2.0.0"
FORBIDDEN_OPERATIONAL_KEYS = {
    "score",
    "theme_score",
    "core_score",
    "theme_opportunity_state",
    "theme_lifecycle_state",
    "market_confirmed",
    "top15",
    "final_action",
    "recommended_action",
}


class LLMThemeDiscoveryError(ValueError):
    """A local discovery packet cannot be accepted without an operationally unsafe guess."""


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise LLMThemeDiscoveryError(f"input JSON could not be read: {path}") from exc


def default_output_path(expected_decision_date: str) -> Path:
    return STATE_US_SHORT_DIR / output_filename(expected_decision_date)


def output_filename(expected_decision_date: str) -> str:
    """Return the sole discovery-slot filename shared with every reader."""
    _parse_decision_date(expected_decision_date)
    return f"us_short_llm_theme_discovery_{expected_decision_date}.json"


def _write_json_atomic(payload: dict[str, Any], path: Path) -> bool:
    try:
        return write_immutable_json(payload, path)
    except DiscoveryPublishPolicyError as exc:
        raise LLMThemeDiscoveryError(str(exc)) from exc


def _repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _resolve_repo_path(path: Path | str, *, field: str) -> Path:
    raw = Path(path)
    resolved = raw.resolve() if raw.is_absolute() else (ROOT / raw).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except (ValueError, OverflowError) as exc:
        raise LLMThemeDiscoveryError(f"{field} must stay under the repository root") from exc
    return resolved


def _validate_input_path(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="input_path")
    if not resolved.is_file():
        raise LLMThemeDiscoveryError(f"input_path must be an existing file: {_repo_rel(resolved)}")
    return resolved


def _validate_output_path(path: Path | str, *, expected_path: Path) -> Path:
    try:
        return validate_exact_decision_slot(
            path, expected_path, root=ROOT, state_dir=STATE_US_SHORT_DIR,
        )
    except DiscoveryPublishPolicyError as exc:
        raise LLMThemeDiscoveryError(str(exc)) from exc


def _parse_rfc3339(value: Any, *, field: str) -> datetime:
    if type(value) is not str or not value:
        raise LLMThemeDiscoveryError(f"{field} must be a timezone-aware RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
        if parsed.tzinfo is None:
            raise ValueError("timezone offset is required")
        # Normalize to UTC at the boundary: a model may legitimately answer in -04:00 (the natural offset
        # for a US-equity prompt), and downstream consumers compare these instants as STRINGS.  Storing
        # mixed offsets makes lexical order disagree with chronological order.
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise LLMThemeDiscoveryError(f"{field} must be a timezone-aware RFC3339 timestamp") from exc


def _parse_decision_date(value: Any) -> datetime.date:
    if type(value) is not str or not re.fullmatch(r"[0-9]{8}", value):
        raise LLMThemeDiscoveryError("expected_decision_date must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise LLMThemeDiscoveryError("expected_decision_date must be a real calendar date") from exc


def _decision_open_et(expected_decision_date: str) -> datetime:
    return datetime.combine(
        _parse_decision_date(expected_decision_date),
        datetime_time(9, 30),
        ZoneInfo("America/New_York"),
    )


def _validate_schema(payload: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise LLMThemeDiscoveryError("jsonschema is required for discovery artifact validation") from exc
    schema = _read_json(SCHEMA_PATH)
    errors = sorted(
        Draft7Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(payload),
        key=lambda error: list(error.path),
    )
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise LLMThemeDiscoveryError(f"discovery artifact schema rejected {len(errors)} field(s): {joined}")


def _assert_safe_text(payload: dict[str, Any]) -> None:
    if persisted_text_violation(payload) is not None:
        raise LLMThemeDiscoveryError("discovery artifact contains forbidden credential-like text")


def _input_sha256(payload: dict[str, Any]) -> str:
    # Input identity is evidence identity, not provider-return ordering.  Canonicalize
    # the semantically unordered source/theme/member collections before hashing.
    stable = json.loads(json.dumps(payload, ensure_ascii=False))
    if isinstance(stable.get("source_refs"), list):
        stable["source_refs"].sort(key=lambda row: str(row.get("source_id", "")) if isinstance(row, dict) else str(row))
    if isinstance(stable.get("themes"), list):
        for theme in stable["themes"]:
            if not isinstance(theme, dict):
                continue
            if isinstance(theme.get("source_ref_ids"), list):
                theme["source_ref_ids"] = sorted(set(theme["source_ref_ids"]))
            if isinstance(theme.get("members"), list):
                for member in theme["members"]:
                    if isinstance(member, dict) and isinstance(member.get("source_ref_ids"), list):
                        member["source_ref_ids"] = sorted(set(member["source_ref_ids"]))
                theme["members"].sort(key=lambda row: str(row.get("ticker", "")) if isinstance(row, dict) else str(row))
            if isinstance(theme.get("semantic_assertions"), list):
                theme["semantic_assertions"].sort(
                    key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    if isinstance(row, dict) else str(row)
                )
        stable["themes"].sort(key=lambda row: str(row.get("theme_id", "")) if isinstance(row, dict) else str(row))
    try:
        canonical = json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise LLMThemeDiscoveryError("discovery input is not UTF-8 encodable") from exc
    return hashlib.sha256(canonical).hexdigest()


def _require_list(value: Any, *, field: str) -> list[Any]:
    if type(value) is not list:
        raise LLMThemeDiscoveryError(f"{field} must be a list")
    return value


def _reject_operational_keys(value: dict[str, Any], *, field: str) -> None:
    overlap = sorted(FORBIDDEN_OPERATIONAL_KEYS.intersection(value))
    if overlap:
        raise LLMThemeDiscoveryError(
            f"{field} contains operational fields that first-knife discovery cannot consume: {overlap}"
        )


def _source_refs(raw_refs: Any, *, cutoff: datetime) -> tuple[list[dict[str, str]], dict[str, datetime]]:
    refs = _require_list(raw_refs, field="source_refs")
    out: list[dict[str, str]] = []
    by_id: dict[str, datetime] = {}
    for index, raw in enumerate(refs):
        if type(raw) is not dict:
            raise LLMThemeDiscoveryError(f"source_refs[{index}] must be an object")
        source_id = raw.get("source_id")
        source_type = raw.get("source_type")
        if (
            type(source_id) is not str
            or SAFE_SOURCE_ID_RE.fullmatch(source_id) is None
            or SECRET_TEXT_RE.search(source_id)
        ):
            raise LLMThemeDiscoveryError(f"source_refs[{index}].source_id is invalid")
        if source_id in by_id:
            raise LLMThemeDiscoveryError(f"duplicate source_id: {source_id}")
        if source_type not in {"web", "x", "llm"}:
            raise LLMThemeDiscoveryError(f"source_refs[{index}].source_type is invalid")
        observed_at = _parse_rfc3339(raw.get("observed_at"), field=f"source_refs[{index}].observed_at")
        if observed_at >= cutoff:
            raise LLMThemeDiscoveryError(
                f"source_refs[{index}].observed_at must be before the decision open (PIT fail-closed)"
            )
        by_id[source_id] = observed_at
        canonical_ref = {
            "source_id": source_id,
            "source_type": source_type,
            "observed_at": observed_at.isoformat(),
        }
        # KNIFE1_SOURCE_REF_KEYS is the contract; this literal only carries its values.  The
        # projection below would otherwise DROP a field added here and not to the tuple, which
        # is precisely the silent drift the shared tuple exists to prevent.
        if set(canonical_ref) != set(KNIFE1_SOURCE_REF_KEYS):
            raise LLMThemeDiscoveryError(
                "Knife-1 source_ref key contract drifted from KNIFE1_SOURCE_REF_KEYS"
            )
        out.append({key: canonical_ref[key] for key in KNIFE1_SOURCE_REF_KEYS})
    out.sort(key=lambda item: item["source_id"])
    return out, by_id


def project_knife1_source_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: ref[key] for key in KNIFE1_SOURCE_REF_KEYS} for ref in sorted(refs, key=lambda ref: ref["source_id"])]


def normalize_semantic_assertions(
    raw_assertions: Any,
    *,
    theme_ref_ids: set[str],
    member_ref_ids: dict[str, set[str]],
    ref_types: dict[str, str],
    ref_times: dict[str, datetime],
    theme_observed_at: datetime,
    origin_source_type: str | None = None,
    origin_scope_type: str | None = None,
    origin_scope_index: int | None = None,
    field: str = "semantic_assertions",
) -> list[dict[str, Any]]:
    """Normalize the machine-checkable commercial-driver assertion contract.

    Provider adapters may supply the origin because they own the chunk/response boundary.  The
    frozen discovery artifact always stores it, so an assertion can never become anonymous after
    parsing or merge.
    """
    if type(raw_assertions) is not list:
        raise LLMThemeDiscoveryError(f"{field} must be a list")
    if not raw_assertions:
        return []
    allowed_keys = {
        "basis", "basis_explanation", "common_driver", "member_links",
        "origin_source_type", "origin_scope_type", "origin_scope_index",
    }
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_assertions):
        if type(raw) is not dict or not set(raw).issubset(allowed_keys):
            raise LLMThemeDiscoveryError(f"{field}[{index}] has an unexpected shape")
        basis = raw.get("basis")
        explanation = raw.get("basis_explanation")
        if basis not in SEMANTIC_BASIS_VALUES:
            raise LLMThemeDiscoveryError(f"{field}[{index}].basis is invalid")
        if type(explanation) is not str or not explanation.strip() or len(explanation) > 1000:
            raise LLMThemeDiscoveryError(f"{field}[{index}].basis_explanation is invalid")
        source_type = origin_source_type if origin_source_type is not None else raw.get("origin_source_type")
        scope_type = origin_scope_type if origin_scope_type is not None else raw.get("origin_scope_type")
        scope_index = origin_scope_index if origin_scope_index is not None else raw.get("origin_scope_index")
        if source_type not in {"web", "x"}:
            raise LLMThemeDiscoveryError(f"{field}[{index}].origin_source_type is invalid")
        if scope_type not in SEMANTIC_ORIGIN_SCOPE_TYPES:
            raise LLMThemeDiscoveryError(f"{field}[{index}].origin_scope_type is invalid")
        if (scope_type == "web_chunk" and source_type != "web") or (
            scope_type == "x_response" and source_type != "x"
        ):
            raise LLMThemeDiscoveryError(f"{field}[{index}] origin source/scope mismatch")
        if isinstance(scope_index, bool) or not isinstance(scope_index, int) or scope_index < 0:
            raise LLMThemeDiscoveryError(f"{field}[{index}].origin_scope_index is invalid")
        common = raw.get("common_driver")
        links = raw.get("member_links")
        if basis == "shared_commercial_driver":
            if type(common) is not dict or set(common) != {
                "driver_statement", "transmission_mechanism", "source_ref_ids",
            }:
                raise LLMThemeDiscoveryError(f"{field}[{index}].common_driver is invalid")
            driver_statement = common.get("driver_statement")
            mechanism = common.get("transmission_mechanism")
            if (
                type(driver_statement) is not str or not driver_statement.strip() or len(driver_statement) > 1000
                or type(mechanism) is not str or not mechanism.strip() or len(mechanism) > 1000
            ):
                raise LLMThemeDiscoveryError(f"{field}[{index}].common_driver text is invalid")
            common_refs = common.get("source_ref_ids")
            if (
                type(common_refs) is not list
                or not common_refs
                or any(type(ref_id) is not str for ref_id in common_refs)
            ):
                raise LLMThemeDiscoveryError(f"{field}[{index}].common_driver.source_ref_ids is invalid")
            normalized_common_refs = sorted(set(common_refs))
            if any(
                type(ref_id) is not str or ref_id not in theme_ref_ids
                or ref_types.get(ref_id) != source_type
                or ref_times[ref_id] > theme_observed_at
                for ref_id in normalized_common_refs
            ):
                raise LLMThemeDiscoveryError(f"{field}[{index}].common_driver source binding is invalid")
            if type(links) is not list:
                raise LLMThemeDiscoveryError(f"{field}[{index}].member_links is invalid")
            normalized_links: list[dict[str, Any]] = []
            seen_tickers: set[str] = set()
            for link_index, raw_link in enumerate(links):
                if type(raw_link) is not dict or set(raw_link) != {
                    "ticker", "role", "link_statement", "source_ref_ids",
                }:
                    raise LLMThemeDiscoveryError(f"{field}[{index}].member_links[{link_index}] is invalid")
                ticker = canonical_us_ticker(raw_link.get("ticker"))
                role = raw_link.get("role")
                statement = raw_link.get("link_statement")
                link_refs = raw_link.get("source_ref_ids")
                if ticker is None or ticker not in member_ref_ids or ticker in seen_tickers:
                    raise LLMThemeDiscoveryError(f"{field}[{index}].member_links[{link_index}].ticker is invalid")
                if role not in SEMANTIC_ROLES:
                    raise LLMThemeDiscoveryError(f"{field}[{index}].member_links[{link_index}].role is invalid")
                if type(statement) is not str or not statement.strip() or len(statement) > 1000:
                    raise LLMThemeDiscoveryError(f"{field}[{index}].member_links[{link_index}].link_statement is invalid")
                if type(link_refs) is not list or not link_refs:
                    raise LLMThemeDiscoveryError(f"{field}[{index}].member_links[{link_index}].source_ref_ids is invalid")
                if any(type(ref_id) is not str for ref_id in link_refs):
                    raise LLMThemeDiscoveryError(f"{field}[{index}].member_links[{link_index}].source_ref_ids is invalid")
                normalized_link_refs = sorted(set(link_refs))
                if any(
                    type(ref_id) is not str or ref_id not in theme_ref_ids
                    or ref_id not in member_ref_ids[ticker]
                    or ref_types.get(ref_id) != source_type
                    or ref_times[ref_id] > theme_observed_at
                    for ref_id in normalized_link_refs
                ):
                    raise LLMThemeDiscoveryError(f"{field}[{index}].member_links[{link_index}] source binding is invalid")
                seen_tickers.add(ticker)
                normalized_links.append({
                    "ticker": ticker, "role": role, "link_statement": statement.strip(),
                    "source_ref_ids": normalized_link_refs,
                })
            if len(normalized_links) < 3:
                raise LLMThemeDiscoveryError(f"{field}[{index}].member_links must contain at least 3 rows")
            normalized_common = {
                "driver_statement": driver_statement.strip(),
                "transmission_mechanism": mechanism.strip(),
                "source_ref_ids": normalized_common_refs,
            }
        else:
            if common is not None or links != []:
                raise LLMThemeDiscoveryError(f"{field}[{index}] non-shared basis must have no driver links")
            normalized_common = None
            normalized_links = []
        normalized.append({
            "basis": basis,
            "basis_explanation": explanation.strip(),
            "common_driver": normalized_common,
            "member_links": normalized_links,
            "origin_source_type": source_type,
            "origin_scope_type": scope_type,
            "origin_scope_index": scope_index,
        })
    normalized.sort(key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return normalized


def normalize_discovery_payload(
    payload: Any,
    *,
    expected_decision_date: str,
    generated_at: str,
) -> dict[str, Any]:
    """Normalize and validate a local LLM discovery response into the frozen artifact."""
    if type(payload) is not dict:
        raise LLMThemeDiscoveryError("discovery input must be an object")
    _reject_operational_keys(payload, field="discovery input")
    cutoff = _decision_open_et(expected_decision_date)
    generated = _parse_rfc3339(generated_at, field="generated_at")
    refs, ref_times = _source_refs(payload.get("source_refs"), cutoff=cutoff)
    ref_types = {ref["source_id"]: ref["source_type"] for ref in refs}
    raw_themes = _require_list(payload.get("themes"), field="themes")
    themes: list[dict[str, Any]] = []
    seen_theme_ids: set[str] = set()
    for t_index, raw_theme in enumerate(raw_themes):
        if type(raw_theme) is not dict:
            raise LLMThemeDiscoveryError(f"themes[{t_index}] must be an object")
        _reject_operational_keys(raw_theme, field=f"themes[{t_index}]")
        theme_id = raw_theme.get("theme_id")
        if type(theme_id) is not str or THEME_ID_RE.fullmatch(theme_id) is None:
            raise LLMThemeDiscoveryError(f"themes[{t_index}].theme_id is invalid")
        if theme_id in seen_theme_ids:
            raise LLMThemeDiscoveryError(f"duplicate theme_id: {theme_id}")
        seen_theme_ids.add(theme_id)
        display_name = raw_theme.get("display_name")
        summary = raw_theme.get("summary")
        if type(display_name) is not str or not display_name.strip() or len(display_name) > 120:
            raise LLMThemeDiscoveryError(f"themes[{t_index}].display_name is invalid")
        if type(summary) is not str or not summary.strip() or len(summary) > 1000:
            raise LLMThemeDiscoveryError(f"themes[{t_index}].summary is invalid")
        observed_at = _parse_rfc3339(raw_theme.get("observed_at"), field=f"themes[{t_index}].observed_at")
        if observed_at >= cutoff:
            raise LLMThemeDiscoveryError(
                f"themes[{t_index}].observed_at must be before the decision open (PIT fail-closed)"
            )
        theme_ref_ids = _require_list(raw_theme.get("source_ref_ids"), field=f"themes[{t_index}].source_ref_ids")
        if not theme_ref_ids:
            raise LLMThemeDiscoveryError(f"themes[{t_index}].source_ref_ids must not be empty")
        normalized_theme_refs: list[str] = []
        for ref_id in theme_ref_ids:
            if type(ref_id) is not str or ref_id not in ref_times:
                raise LLMThemeDiscoveryError(f"themes[{t_index}] references an unknown source_id")
            if ref_times[ref_id] > observed_at:
                raise LLMThemeDiscoveryError(f"themes[{t_index}] observed_at precedes a cited source observation")
            if ref_id not in normalized_theme_refs:
                normalized_theme_refs.append(ref_id)
        raw_members = _require_list(raw_theme.get("members"), field=f"themes[{t_index}].members")
        if not raw_members:
            raise LLMThemeDiscoveryError(f"themes[{t_index}].members must not be empty")
        members: list[dict[str, Any]] = []
        seen_tickers: set[str] = set()
        for m_index, raw_member in enumerate(raw_members):
            if type(raw_member) is not dict:
                raise LLMThemeDiscoveryError(f"themes[{t_index}].members[{m_index}] must be an object")
            _reject_operational_keys(raw_member, field=f"themes[{t_index}].members[{m_index}]")
            ticker = canonical_us_ticker(raw_member.get("ticker"))
            if ticker is None:
                raise LLMThemeDiscoveryError(f"themes[{t_index}].members[{m_index}].ticker is invalid")
            if ticker in seen_tickers:
                raise LLMThemeDiscoveryError(f"duplicate member ticker in {theme_id}: {ticker}")
            seen_tickers.add(ticker)
            member_refs = _require_list(
                raw_member.get("source_ref_ids"),
                field=f"themes[{t_index}].members[{m_index}].source_ref_ids",
            )
            if not member_refs:
                raise LLMThemeDiscoveryError(f"themes[{t_index}].members[{m_index}].source_ref_ids must not be empty")
            normalized_member_refs: list[str] = []
            for ref_id in member_refs:
                if type(ref_id) is not str or ref_id not in ref_times or ref_id not in normalized_theme_refs:
                    raise LLMThemeDiscoveryError(f"member {ticker} references an unbound source_id")
                if ref_times[ref_id] > observed_at:
                    raise LLMThemeDiscoveryError(f"member {ticker} cites a source after theme observation")
                if ref_id not in normalized_member_refs:
                    normalized_member_refs.append(ref_id)
            members.append({
                "ticker": ticker,
                "membership_status": "provisional_unvalidated",
                "source_ref_ids": sorted(normalized_member_refs),
            })
        members.sort(key=lambda item: item["ticker"])
        theme = {
            "theme_id": theme_id,
            "display_name": display_name.strip(),
            "summary": summary.strip(),
            "status": "provisional_discovered",
            "observed_at": observed_at.isoformat(),
            "source_ref_ids": sorted(normalized_theme_refs),
            "members": members,
            "cross_industry_validation_status": "not_run",
            "market_confirmation_status": "not_run",
        }
        if "semantic_assertions" in raw_theme:
            member_ref_ids = {
                member["ticker"]: set(member["source_ref_ids"]) for member in members
            }
            theme["semantic_assertions"] = normalize_semantic_assertions(
                raw_theme.get("semantic_assertions"),
                theme_ref_ids=set(normalized_theme_refs), member_ref_ids=member_ref_ids,
                ref_types=ref_types, ref_times=ref_times,
                theme_observed_at=observed_at,
            )
        themes.append(theme)
    themes.sort(key=lambda item: item["theme_id"])
    artifact = {
        "schema_name": "us_short_llm_theme_discovery",
        "schema_version": (
            SEMANTIC_DISCOVERY_SCHEMA_VERSION
            if any("semantic_assertions" in theme for theme in themes) else "1.0.0"
        ),
        "generated_at": generated.isoformat(),
        "input_sha256": _input_sha256(payload),
        "decision_clock": {
            "expected_decision_date": expected_decision_date,
            "cutoff_policy": "before_decision_open_et",
            "pit_enforced": True,
        },
        "discovery_contract": {
            "producer_kind": "llm_theme_discovery",
            "input_mode": "offline_local_input",
            "membership_status": "provisional_unvalidated",
            "market_confirmation_status": "not_run",
            "scoring_eligible": False,
            "top15_effect_enabled": False,
            "operation_advice_effect_enabled": False,
            "dynamic_seats_enabled": False,
            "theme_probe_enabled": False,
            "lifecycle_actions_enabled": False,
        },
        "source_refs": refs,
        "themes": themes,
    }
    _assert_safe_text(artifact)
    _validate_schema(artifact)
    return artifact


def run_preflight(
    *,
    input_path: Path = DEFAULT_INPUT_PATH,
    output_path: Path | None = None,
    expected_decision_date: str,
    generated_at: str,
) -> dict[str, Any]:
    input_resolved = _validate_input_path(input_path)
    output_resolved = _validate_output_path(
        output_path or default_output_path(expected_decision_date),
        expected_path=default_output_path(expected_decision_date),
    )
    payload = _read_json(input_resolved)
    artifact = normalize_discovery_payload(
        payload,
        expected_decision_date=expected_decision_date,
        generated_at=generated_at,
    )
    return {
        "schema_name": "us_short_llm_theme_discovery_preflight",
        "schema_version": "1.0.0",
        "status": "offline_preflight_passed",
        "network_access_performed": False,
        "provider_calls_performed": False,
        "scoring_or_top15_effect": False,
        "operation_advice_effect": False,
        "output_written": False,
        "output_path": _repo_rel(output_resolved),
        "theme_count": len(artifact["themes"]),
        "member_count": sum(len(theme["members"]) for theme in artifact["themes"]),
    }


def run_packet(
    *,
    input_path: Path = DEFAULT_INPUT_PATH,
    output_path: Path | None = None,
    expected_decision_date: str,
    generated_at: str,
) -> dict[str, Any]:
    input_resolved = _validate_input_path(input_path)
    output_resolved = _validate_output_path(
        output_path or default_output_path(expected_decision_date),
        expected_path=default_output_path(expected_decision_date),
    )
    payload = _read_json(input_resolved)
    artifact = normalize_discovery_payload(
        payload,
        expected_decision_date=expected_decision_date,
        generated_at=generated_at,
    )
    reused = _write_json_atomic(artifact, output_resolved)
    return {
        "schema_name": "us_short_llm_theme_discovery_execution_summary",
        "schema_version": "1.0.0",
        "status": "offline_discovery_artifact_reused" if reused else "offline_discovery_artifact_written",
        "network_access_performed": False,
        "provider_calls_performed": False,
        "scoring_or_top15_effect": False,
        "operation_advice_effect": False,
        "output_path": _repo_rel(output_resolved),
        "input_sha256": artifact["input_sha256"],
        "theme_count": len(artifact["themes"]),
        "member_count": sum(len(theme["members"]) for theme in artifact["themes"]),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate/write an offline US-short LLM theme discovery artifact.")
    parser.add_argument("--input-path", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument("--output-path", type=Path, default=None)
    parser.add_argument("--expected-decision-date", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    kwargs = {
        "input_path": args.input_path,
        "output_path": args.output_path,
        "expected_decision_date": args.expected_decision_date,
        "generated_at": args.generated_at,
    }
    result = run_preflight(**kwargs) if args.preflight_only else run_packet(**kwargs)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
