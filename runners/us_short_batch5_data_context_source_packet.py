from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_catalyst import load_catalyst_governance  # noqa: E402
from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance  # noqa: E402
from engine.us_short_massive_news_catalyst import validate_resolved_news_events  # noqa: E402
from engine.us_short_projection_binding import validate_projection_binding  # noqa: E402
from engine.us_short_result_source_linkage import (  # noqa: E402
    ResultSourceLinkageError,
    build_result_source_facts,
)
from engine.us_short_soft_boost_consumption import (  # noqa: E402
    build_consumption_receipt,
    build_shadow_receipt,
    degrade_soft_boost_consumption,
    resolve_soft_boost_consumption,
    write_consumption_receipt,
    write_evidence_bundle,
)
from engine.us_short_seam_momentum import (  # noqa: E402
    COVERAGE_DISPOSITIONS as MOMENTUM_COVERAGE_DISPOSITIONS,
    DISPOSITION_SCORED as MOMENTUM_SCORED_DISPOSITION,
)
from engine.us_short_seam_theme import (  # noqa: E402
    COVERAGE_DISPOSITIONS as THEME_COVERAGE_DISPOSITIONS,
    DISPOSITION_SCORED_INDUSTRY_BASE,
    DISPOSITION_SCORED_THEME_BASE,
)
from engine.us_short_sec_offering_audit import resolve_offering_audit  # noqa: E402
from runners.us_short_batch5_data_context import (  # noqa: E402
    assemble_data_context_from_resolved_pass2_sources,
    assemble_official_context_components_from_resolved_pass2_sources,
    official_top15_tickers,
    validate_overextension_projection,
)


SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_data_context_source_packet.schema.json"
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
DEFAULT_PACKET_PATH = STATE_US_SHORT_DIR / "us_short_batch5_live_source_packet_20260704_source_packet.json"
PROVIDER_SAMPLES_DIR = ROOT / "provider_samples"
SOURCE_PATH_FIELDS = (
    "candidate_artifact_path",
    "eligibility_governance_path",
    "momentum_projection_path",
    "theme_projection_path",
    "offering_audit_source_path",
    "analyst_grade_actions_path",
    "massive_news_events_path",
    "catalyst_governance_path",
    "theme_selection_contract_path",
)
OPTIONAL_SOURCE_PATH_FIELDS = (
    "overextension_projection_path",
    "overextension_candidate_artifact_path",
    "ohlcv_series_packet_path",
)
SOFT_BOOST_INPUT_PATH_FIELDS = (
    "provisional_theme_stage_receipt_path",
    "provisional_theme_validation_path",
    "original_candidate_artifact_path",
    "classification_packet_path",
)
SOFT_BOOST_OUTPUT_PATH_FIELDS = (
    "soft_boost_consumption_receipt_path",
    "soft_boost_shadow_receipt_path",
    "soft_boost_comparison_ledger_path",
)
SOFT_BOOST_STATE_DIR_PATH_FIELD = "soft_boost_state_dir_path"
PROVIDER_ENVELOPE_DIGEST_PATH_FIELDS = (
    "offering_audit_source_path",
    "analyst_grade_actions_path",
    "massive_news_events_path",
    "theme_selection_contract_path",
)
_SHA256_HEX_LENGTH = 64
_PROVIDER_ENVELOPE_RESULT_KEYS = frozenset({"signals", "records", "provenance", "checked", "excluded"})
_SEC_OFFERING_RESULT_KEYS = frozenset({"signals", "provenance", "checked", "excluded"})
_SOURCE_PROVENANCE_FIELDS = frozenset({
    "provider_id",
    "endpoint_or_filing_type",
    "source_as_of",
    "observed_at",
    "coverage_status",
    "parser_status",
    "lineage_ref",
})
_SOURCE_PROVENANCE_COUNT_FIELDS = frozenset({
    "total_record_count",
    "out_of_window_count",
    "future_excluded_count",
})
_ANALYST_RECORD_KEYS = frozenset({
    "date",
    "grading_company",
    "new_grade",
    "previous_grade",
    "action",
    "direction",
})
_ANALYST_SUMMARY_KEYS = frozenset({
    "upgrades",
    "downgrades",
    "neutrals",
    "net",
    "distinct_firms",
    "distinct_downgrading_firms",
    "window_days",
})
SCOPE_FALSE_FIELDS = (
    "network_access_performed",
    "provider_calls_performed",
    "raw_payload_capture_performed",
    "datahub_consumption_allowed",
    "production_storage_allowed",
    "ship_gate_evidence_claimed",
    "broker_or_order_automation_allowed",
    "a_share_crossing_allowed",
)
PREFLIGHT_TRUE_FIELDS = (
    "local_files_only",
    "source_artifacts_must_exist",
    "output_must_be_gitignored",
    "no_provider_fetch",
    "no_datahub_or_production",
)
PROHIBITED_FALSE_FIELDS = (
    "provider_selection_complete",
    "live_normalized_evidence",
    "ship_gate_evidence",
    "production_ready",
    "datahub_consumed",
)
_CONTEXT_COMPONENT_LEGACY_KEYS = frozenset({"data_context", "per_ticker_analysis", "run_provenance"})
CONTEXT_COMPONENT_SHAPES = MappingProxyType({
    "legacy": _CONTEXT_COMPONENT_LEGACY_KEYS,
    "a1": _CONTEXT_COMPONENT_LEGACY_KEYS | frozenset({"score_composition", "overextension_by_ticker"}),
    "cut4": _CONTEXT_COMPONENT_LEGACY_KEYS
    | frozenset({"score_composition", "overextension_by_ticker", "result_linkage_sources"}),
})
CURRENT_CONTEXT_COMPONENT_SHAPE = "cut4"
_CONTEXT_COMPONENT_MAPPING_FIELDS = frozenset({
    "data_context",
    "score_composition",
    "per_ticker_analysis",
    "run_provenance",
    "result_linkage_sources",
})


class SourcePacketError(ValueError):
    """The local US-short Batch5 source packet cannot be consumed safely."""


def validate_context_components_shape(value: Any, *, allowed_shapes: tuple[str, ...]) -> str:
    """Return the exact accepted carrier shape; reject missing, extra, or mistyped components."""
    unknown_shapes = set(allowed_shapes) - set(CONTEXT_COMPONENT_SHAPES)
    if not allowed_shapes or unknown_shapes:
        raise SourcePacketError(f"context_components allowed_shapes are invalid: {sorted(unknown_shapes)}")
    if not isinstance(value, Mapping):
        raise SourcePacketError("context_components must be a mapping")

    actual_keys = frozenset(value)
    for shape in allowed_shapes:
        expected_keys = CONTEXT_COMPONENT_SHAPES[shape]
        if actual_keys != expected_keys:
            continue
        invalid_value_types = sorted(
            key
            for key in expected_keys
            if (
                key in _CONTEXT_COMPONENT_MAPPING_FIELDS and not isinstance(value[key], Mapping)
            )
            or (
                key == "overextension_by_ticker"
                and value[key] is not None
                and not isinstance(value[key], Mapping)
            )
        )
        if invalid_value_types:
            raise SourcePacketError(
                f"context_components {shape} has invalid_value_types={invalid_value_types}"
            )
        return shape

    closest_shape = min(
        allowed_shapes,
        key=lambda shape: (
            len(actual_keys ^ CONTEXT_COMPONENT_SHAPES[shape]),
            -len(CONTEXT_COMPONENT_SHAPES[shape]),
            shape,
        ),
    )
    expected_keys = CONTEXT_COMPONENT_SHAPES[closest_shape]
    missing_keys = sorted(expected_keys - actual_keys)
    unexpected_keys = sorted(actual_keys - expected_keys)
    raise SourcePacketError(
        "context_components closed-world shape rejected: "
        f"missing_keys={missing_keys} unexpected_keys={unexpected_keys}"
    )


def validate_current_context_components(value: Any) -> str:
    """Accept only the final six-key Cut4 carrier used by current producer and shadow paths."""
    return validate_context_components_shape(
        value,
        allowed_shapes=(CURRENT_CONTEXT_COMPONENT_SHAPE,),
    )


@dataclass(frozen=True)
class ProjectionBindingExpectations:
    producer_id: str
    momentum_source_roles: tuple[str, ...]
    theme_source_roles: tuple[str, ...]
    momentum_allowed_dispositions: tuple[str, ...]
    momentum_scored_dispositions: tuple[str, ...]
    theme_allowed_dispositions: tuple[str, ...]
    theme_scored_dispositions: tuple[str, ...]


FULL_CANDIDATE_LIVE_PROJECTION_BINDING = ProjectionBindingExpectations(
    producer_id="us_short_batch5_full_candidate_live_source_packet",
    momentum_source_roles=("parent_momentum_projection",),
    theme_source_roles=("parent_theme_projection",),
    momentum_allowed_dispositions=tuple(sorted(MOMENTUM_COVERAGE_DISPOSITIONS)),
    momentum_scored_dispositions=(MOMENTUM_SCORED_DISPOSITION,),
    theme_allowed_dispositions=tuple(sorted(THEME_COVERAGE_DISPOSITIONS)),
    theme_scored_dispositions=(DISPOSITION_SCORED_THEME_BASE, DISPOSITION_SCORED_INDUSTRY_BASE),
)

PROJECTION_INPUTS_BINDING = ProjectionBindingExpectations(
    producer_id="us_short_batch5_full_candidate_projection_inputs",
    momentum_source_roles=("candidate_artifact", "source_momentum_projection"),
    theme_source_roles=("candidate_artifact", "source_theme_projection"),
    momentum_allowed_dispositions=tuple(sorted(MOMENTUM_COVERAGE_DISPOSITIONS)),
    momentum_scored_dispositions=(MOMENTUM_SCORED_DISPOSITION,),
    theme_allowed_dispositions=tuple(sorted(THEME_COVERAGE_DISPOSITIONS)),
    theme_scored_dispositions=(DISPOSITION_SCORED_THEME_BASE, DISPOSITION_SCORED_INDUSTRY_BASE),
)


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _resolve_invocation_path(path: Path | str) -> Path:
    raw = Path(path)
    resolved = raw.resolve() if raw.is_absolute() else (ROOT / raw).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise SourcePacketError("packet_path must stay under the repository root") from exc
    if not resolved.exists():
        raise SourcePacketError(f"packet_path does not exist: {_display_path(resolved)}")
    return resolved


def _validate_source_packet_path(packet_path: Path) -> None:
    if not packet_path.is_file():
        raise SourcePacketError(f"packet_path must be a file: {_display_path(packet_path)}")
    try:
        packet_path.resolve().parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise SourcePacketError("packet_path must stay under state/us_short/") from exc
    if packet_path.suffix != ".json":
        raise SourcePacketError("packet_path must be a .json file")
    if not _git_ignored(packet_path):
        raise SourcePacketError("packet_path must be gitignored")


def _display_path(path: Path) -> str:
    try:
        return _repo_rel(path)
    except ValueError:
        return str(path)


def _validate_repo_relative_text(value: Any, *, field: str) -> Path:
    if type(value) is not str or not value.strip():
        raise SourcePacketError(f"paths.{field} must be a non-empty repo-relative path")
    rel = Path(value)
    if rel.is_absolute() or rel.anchor or any(part == ".." for part in rel.parts):
        raise SourcePacketError(f"paths.{field} must be repo-relative and non-traversing")
    resolved = (ROOT / rel).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise SourcePacketError(f"paths.{field} escaped the repository root") from exc
    return resolved


def _existing_repo_path(value: Any, *, field: str) -> Path:
    path = _validate_repo_relative_text(value, field=field)
    if not path.exists():
        raise SourcePacketError(f"paths.{field} does not exist: {_display_path(path)}")
    if not path.is_file():
        raise SourcePacketError(f"paths.{field} must be a file: {_display_path(path)}")
    try:
        path.resolve().relative_to(PROVIDER_SAMPLES_DIR.resolve())
    except ValueError:
        pass
    else:
        raise SourcePacketError(f"paths.{field} must point at a resolved source artifact, not provider_samples/")
    return path


def _git_ignored(path: Path) -> bool:
    rel = _repo_rel(path)
    result = subprocess.run(
        ["git", "check-ignore", "-q", "--", rel],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _validate_output_path(value: Any, *, field: str) -> Path:
    path = _validate_repo_relative_text(value, field=field)
    try:
        path.resolve().parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise SourcePacketError(f"paths.{field} must stay under state/us_short/") from exc
    if path.suffix != ".json":
        raise SourcePacketError(f"paths.{field} must be a .json file")
    if not _git_ignored(path):
        raise SourcePacketError(f"paths.{field} must be gitignored")
    return path


def _validate_soft_boost_state_dir(value: Any) -> Path:
    path = _validate_repo_relative_text(value, field=SOFT_BOOST_STATE_DIR_PATH_FIELD)
    if not path.exists() or not path.is_dir():
        raise SourcePacketError("paths.soft_boost_state_dir_path must be an existing directory")
    return path


def _validate_soft_boost_output_path(
    value: Any, *, field: str, state_dir: Path,
) -> Path:
    path = _validate_repo_relative_text(value, field=field)
    try:
        path.resolve().parent.relative_to(state_dir.resolve())
    except ValueError as exc:
        raise SourcePacketError(f"paths.{field} must stay under the K4b state root") from exc
    if path.suffix != ".json":
        raise SourcePacketError(f"paths.{field} must be a .json file")
    if not _git_ignored(path):
        raise SourcePacketError(f"paths.{field} must be gitignored")
    return path


def _soft_boost_common_input_sha256(
    packet: dict[str, Any], paths: dict[str, Path],
) -> str:
    input_path_sha256 = {
        field: hashlib.sha256(paths[field].read_bytes()).hexdigest()
        for field in (
            *SOURCE_PATH_FIELDS,
            *OPTIONAL_SOURCE_PATH_FIELDS,
            *SOFT_BOOST_INPUT_PATH_FIELDS,
        )
        if field in paths
    }
    payload = {
        "decision_clock": packet["decision_clock"],
        "input_path_sha256": input_path_sha256,
        "soft_boost_state_dir": _repo_rel(paths[SOFT_BOOST_STATE_DIR_PATH_FIELD]),
        "holdings": packet["optional_inputs"]["holdings"],
        "catalyst_recall_feed": packet["optional_inputs"]["catalyst_recall_feed"],
        "preflight_gates": packet["preflight_gates"],
        "prohibited_claims": packet["prohibited_claims"],
    }
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _validate_schema(packet: Any) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise SourcePacketError("jsonschema is required for source-packet validation") from exc
    schema = _read_json(SCHEMA_PATH)
    errors = sorted(Draft7Validator(schema).iter_errors(packet), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise SourcePacketError(f"source packet schema rejected {len(errors)} field(s): {joined}")


def _validate_yyyymmdd(value: Any, *, field: str) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise SourcePacketError(f"{field} must be ASCII YYYYMMDD")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise SourcePacketError(f"{field} must be a real calendar date") from exc
    return value


def _validated_provider_envelope_digests(packet: dict[str, Any], paths: dict[str, Path]) -> dict[str, str]:
    """Require the provider envelopes selected by this packet to be content-bound before consumption."""
    digests = packet.get("source_artifact_sha256")
    if type(digests) is not dict:
        raise SourcePacketError("source_artifact_sha256 must be an exact dict")
    expected_fields = set(PROVIDER_ENVELOPE_DIGEST_PATH_FIELDS)
    if "ohlcv_series_packet_path" in paths:
        expected_fields.add("ohlcv_series_packet_path")
    if set(digests) != expected_fields:
        raise SourcePacketError(
            "source_artifact_sha256 must exactly cover the provider envelope paths selected by this packet"
        )
    out: dict[str, str] = {}
    for field in expected_fields:
        digest = digests[field]
        if not (
            type(digest) is str
            and len(digest) == _SHA256_HEX_LENGTH
            and digest.isascii()
            and all(character in "0123456789abcdef" for character in digest)
        ):
            raise SourcePacketError(f"source_artifact_sha256.{field} must be lowercase SHA-256 hex")
        try:
            actual = hashlib.sha256(paths[field].read_bytes()).hexdigest()
        except OSError as exc:
            raise SourcePacketError(f"source_artifact_sha256.{field} source artifact could not be read") from exc
        if actual != digest:
            raise SourcePacketError(f"source_artifact_sha256.{field} does not bind the current source artifact")
        out[field] = digest
    return out


def _load_and_validate_packet(packet_path: Path | str) -> tuple[dict[str, Any], dict[str, Path]]:
    resolved_packet_path = _resolve_invocation_path(packet_path)
    _validate_source_packet_path(resolved_packet_path)
    try:
        packet = _read_json(resolved_packet_path)
    except Exception as exc:
        raise SourcePacketError(f"source packet JSON could not be read: {_display_path(resolved_packet_path)}") from exc
    _validate_schema(packet)
    if type(packet) is not dict:
        raise SourcePacketError("source packet root must be an object")
    if packet.get("active_analyst_source") not in {"yfinance", "fmp"}:
        raise SourcePacketError("active_analyst_source must be exactly yfinance or fmp")

    scope = packet["scope"]
    for field in SCOPE_FALSE_FIELDS:
        if scope.get(field) is not False:
            raise SourcePacketError(f"scope.{field} must be false")
    gates = packet["preflight_gates"]
    for field in PREFLIGHT_TRUE_FIELDS:
        if gates.get(field) is not True:
            raise SourcePacketError(f"preflight_gates.{field} must be true")
    prohibited = packet["prohibited_claims"]
    for field in PROHIBITED_FALSE_FIELDS:
        if prohibited.get(field) is not False:
            raise SourcePacketError(f"prohibited_claims.{field} must be false")
    _validate_yyyymmdd(packet["decision_clock"]["expected_decision_date"], field="decision_clock.expected_decision_date")

    paths = {
        field: _existing_repo_path(packet["paths"][field], field=field)
        for field in SOURCE_PATH_FIELDS
    }
    for field in OPTIONAL_SOURCE_PATH_FIELDS:
        if field in packet["paths"]:
            paths[field] = _existing_repo_path(packet["paths"][field], field=field)
    soft_enabled = packet["optional_inputs"].get("theme_soft_boost_enabled", False)
    if type(soft_enabled) is not bool:
        raise SourcePacketError("optional_inputs.theme_soft_boost_enabled must be exact bool")
    all_soft_path_fields = (
        *SOFT_BOOST_INPUT_PATH_FIELDS,
        *SOFT_BOOST_OUTPUT_PATH_FIELDS,
        SOFT_BOOST_STATE_DIR_PATH_FIELD,
    )
    soft_present = {
        field for field in all_soft_path_fields
        if field in packet["paths"]
    }
    if soft_enabled and soft_present != set(all_soft_path_fields):
        raise SourcePacketError("enabled K4b source packet must carry every soft-boost path")
    if not soft_enabled and soft_present:
        raise SourcePacketError("disabled K4b source packet must not carry soft-boost paths")
    if not soft_enabled and "soft_discovery_stage_result" in packet["optional_inputs"]:
        raise SourcePacketError("disabled K4b source packet must not carry a stage result")
    if soft_enabled:
        if "output_context_components_path" not in packet["paths"]:
            raise SourcePacketError("enabled K4b source packet requires output_context_components_path")
        if type(packet["optional_inputs"].get("soft_discovery_stage_result")) is not dict:
            raise SourcePacketError("enabled K4b source packet requires this run's stage result")
        soft_state_dir = _validate_soft_boost_state_dir(
            packet["paths"][SOFT_BOOST_STATE_DIR_PATH_FIELD]
        )
        paths[SOFT_BOOST_STATE_DIR_PATH_FIELD] = soft_state_dir
        for field in SOFT_BOOST_INPUT_PATH_FIELDS:
            paths[field] = _validate_repo_relative_text(packet["paths"][field], field=field)
        for field in SOFT_BOOST_OUTPUT_PATH_FIELDS:
            paths[field] = _validate_soft_boost_output_path(
                packet["paths"][field], field=field, state_dir=soft_state_dir,
            )
    paths["output_data_context_path"] = _validate_output_path(
        packet["paths"]["output_data_context_path"],
        field="output_data_context_path",
    )
    if "output_context_components_path" in packet["paths"]:
        paths["output_context_components_path"] = _validate_output_path(
            packet["paths"]["output_context_components_path"],
            field="output_context_components_path",
        )
    paths["packet_path"] = resolved_packet_path
    _validated_provider_envelope_digests(packet, paths)
    return packet, paths


def _source_json(path: Path, *, field: str, expected_sha256: str | None = None) -> Any:
    try:
        raw = path.read_bytes()
        if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise SourcePacketError(f"source_artifact_sha256.{field} changed before consumption")
        return json.loads(raw.decode("utf-8"))
    except SourcePacketError:
        raise
    except Exception as exc:
        raise SourcePacketError(f"paths.{field} could not be read as JSON: {_display_path(path)}") from exc


def _canonical_provider_envelope_map(value: Any, *, name: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise SourcePacketError(f"provider envelope {name} must be an exact dict")
    out: dict[str, Any] = {}
    for raw_ticker, row in value.items():
        if type(raw_ticker) is not str:
            raise SourcePacketError(f"provider envelope {name} ticker must be exact str")
        ticker = canonical_us_ticker(raw_ticker)
        if ticker is None or ticker != raw_ticker:
            raise SourcePacketError(f"provider envelope {name} ticker must be canonical US identity")
        if ticker in out:
            raise SourcePacketError(f"provider envelope {name} contains duplicate canonical ticker")
        out[ticker] = row
    return out


def _provider_envelope_as_of(expected_decision_date: str) -> str:
    return datetime.strptime(expected_decision_date, "%Y%m%d").date().isoformat()


def _validated_source_provenance(
    value: Any,
    *,
    ticker: str,
    as_of: str,
    provider_id: str,
    endpoint: str,
) -> tuple[dict[str, Any], dict[str, int]]:
    if type(value) is not dict or set(value) != (_SOURCE_PROVENANCE_FIELDS | _SOURCE_PROVENANCE_COUNT_FIELDS):
        raise SourcePacketError(f"provider envelope provenance[{ticker}] keys drifted")
    if (
        type(value["provider_id"]) is not str
        or type(value["endpoint_or_filing_type"]) is not str
        or type(value["coverage_status"]) is not str
        or type(value["parser_status"]) is not str
        or value["provider_id"] != provider_id
        or value["endpoint_or_filing_type"] != endpoint
        or value["coverage_status"] != "full"
        or value["parser_status"] != "ok"
    ):
        raise SourcePacketError(f"provider envelope provenance[{ticker}] provider/endpoint drifted")
    source_as_of = value["source_as_of"]
    try:
        source_date = datetime.strptime(source_as_of, "%Y-%m-%d").date()
        decision_date = datetime.strptime(as_of, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise SourcePacketError(f"provider envelope provenance[{ticker}] source_as_of is not a real date") from exc
    if source_date > decision_date:
        raise SourcePacketError(f"provider envelope provenance[{ticker}] source_as_of is look-ahead")
    observed_at = value["observed_at"]
    if type(observed_at) is not str or "T" not in observed_at:
        raise SourcePacketError(f"provider envelope provenance[{ticker}] observed_at must be timezone-aware")
    try:
        observed = datetime.fromisoformat(observed_at[:-1] + "+00:00" if observed_at.endswith("Z") else observed_at)
    except ValueError as exc:
        raise SourcePacketError(f"provider envelope provenance[{ticker}] observed_at is malformed") from exc
    if observed.tzinfo is None:
        raise SourcePacketError(f"provider envelope provenance[{ticker}] observed_at must be timezone-aware")
    try:
        from zoneinfo import ZoneInfo

        observed_et = observed.astimezone(ZoneInfo("America/New_York"))
    except Exception as exc:
        raise SourcePacketError(f"provider envelope provenance[{ticker}] observed_at cannot bind the decision clock") from exc
    if observed_et.date() > source_date or observed_et >= datetime(
        source_date.year, source_date.month, source_date.day, 9, 30, tzinfo=observed_et.tzinfo
    ):
        raise SourcePacketError(f"provider envelope provenance[{ticker}] observed_at violates PIT cutoff")
    lineage_ref = value["lineage_ref"]
    prefix, separator, record_id = lineage_ref.rpartition("#") if type(lineage_ref) is str else ("", "", "")
    if (
        type(lineage_ref) is not str
        or not lineage_ref.isascii()
        or separator != "#"
        or prefix != f"{provider_id}:{endpoint}:{source_as_of}"
        or not record_id
        or any(character.isspace() for character in record_id)
        or ":" in record_id
        or "#" in record_id
    ):
        raise SourcePacketError(f"provider envelope provenance[{ticker}] lineage_ref drifted")
    counts: dict[str, int] = {}
    for field in _SOURCE_PROVENANCE_COUNT_FIELDS:
        count = value[field]
        if type(count) is not int or count < 0:
            raise SourcePacketError(f"provider envelope provenance[{ticker}].{field} must be non-negative int")
        counts[field] = count
    return ({field: value[field] for field in _SOURCE_PROVENANCE_FIELDS}, counts)


def _validate_resolved_analyst_grade_envelope(
    result: Any,
    *,
    as_of: str,
    provider_id: str,
    endpoint: str,
    direction_map: dict[str, str],
) -> None:
    if type(result) is not dict or set(result) != _PROVIDER_ENVELOPE_RESULT_KEYS:
        raise SourcePacketError("provider envelope analyst-grade result keys drifted")
    signals = _canonical_provider_envelope_map(result["signals"], name="analyst.signals")
    records = _canonical_provider_envelope_map(result["records"], name="analyst.records")
    provenance = _canonical_provider_envelope_map(result["provenance"], name="analyst.provenance")
    checked = _canonical_provider_envelope_map(result["checked"], name="analyst.checked")
    excluded = _canonical_provider_envelope_map(result["excluded"], name="analyst.excluded")
    identities = (set(signals), set(checked), set(excluded))
    if any(left & right for index, left in enumerate(identities) for right in identities[index + 1:]):
        raise SourcePacketError("provider envelope analyst-grade dispositions overlap")
    if set(records) != set(signals) or set(provenance) != (set(signals) | set(checked)):
        raise SourcePacketError("provider envelope analyst-grade records/provenance identities drifted")
    for ticker, row in signals.items():
        if type(row) is not dict or set(row) != {"analyst_actions_recent"}:
            raise SourcePacketError(f"provider envelope analyst signal[{ticker}] keys drifted")
        summary = row["analyst_actions_recent"]
        if type(summary) is not dict or set(summary) != _ANALYST_SUMMARY_KEYS:
            raise SourcePacketError(f"provider envelope analyst summary[{ticker}] keys drifted")
        if any(type(summary[field]) is not int for field in _ANALYST_SUMMARY_KEYS):
            raise SourcePacketError(f"provider envelope analyst summary[{ticker}] values must be exact int")
        normalized_records = records[ticker]
        if type(normalized_records) is not list:
            raise SourcePacketError(f"provider envelope analyst records[{ticker}] must be a list")
        source_provenance, counts = _validated_source_provenance(
            provenance[ticker], ticker=ticker, as_of=as_of, provider_id=provider_id, endpoint=endpoint
        )
        from zoneinfo import ZoneInfo

        observed_date = datetime.fromisoformat(source_provenance["observed_at"].replace("Z", "+00:00")).astimezone(
            ZoneInfo("America/New_York")
        ).date()
        seen: set[tuple[str, str, str, str, str]] = set()
        actions = {"up": 0, "down": 0, "neutral": 0}
        firms: set[str] = set()
        downgrading_firms: set[str] = set()
        for record in normalized_records:
            if type(record) is not dict or set(record) != _ANALYST_RECORD_KEYS:
                raise SourcePacketError(f"provider envelope analyst record[{ticker}] keys drifted")
            date = record["date"]
            try:
                record_date = datetime.strptime(date, "%Y-%m-%d").date()
            except (TypeError, ValueError) as exc:
                raise SourcePacketError(f"provider envelope analyst record[{ticker}] date is malformed") from exc
            if record_date > observed_date:
                raise SourcePacketError(f"provider envelope analyst record[{ticker}] is look-ahead")
            if (datetime.strptime(as_of, "%Y-%m-%d").date() - record_date).days > 90:
                raise SourcePacketError(f"provider envelope analyst record[{ticker}] is out of the source window")
            for field in ("grading_company", "new_grade", "action"):
                if type(record[field]) is not str or not record[field].strip():
                    raise SourcePacketError(f"provider envelope analyst record[{ticker}].{field} is malformed")
            if type(record["previous_grade"]) is not str or type(record["direction"]) is not str:
                raise SourcePacketError(f"provider envelope analyst record[{ticker}] grade/direction types drifted")
            expected_direction = direction_map.get(record["action"], "neutral")
            if record["direction"] != expected_direction:
                raise SourcePacketError(f"provider envelope analyst record[{ticker}] direction drifted")
            normalized_firm = " ".join(record["grading_company"].split()).casefold()
            identity = (date, normalized_firm, record["action"], record["new_grade"], record["previous_grade"])
            if identity in seen:
                raise SourcePacketError(f"provider envelope analyst record[{ticker}] duplicates source identity")
            seen.add(identity)
            actions[record["direction"]] += 1
            firms.add(normalized_firm)
            if record["direction"] == "down":
                downgrading_firms.add(normalized_firm)
        if normalized_records != sorted(
            normalized_records, key=lambda record: (record["date"], " ".join(record["grading_company"].split()).casefold())
        ):
            raise SourcePacketError(f"provider envelope analyst records[{ticker}] are not canonical order")
        expected_summary = {
            "upgrades": actions["up"],
            "downgrades": actions["down"],
            "neutrals": actions["neutral"],
            "net": actions["up"] - actions["down"],
            "distinct_firms": len(firms),
            "distinct_downgrading_firms": len(downgrading_firms),
            "window_days": 90,
        }
        if summary != expected_summary:
            raise SourcePacketError(f"provider envelope analyst summary[{ticker}] is not bound to records")
        if counts["total_record_count"] != len(normalized_records) + counts["out_of_window_count"] + counts["future_excluded_count"]:
            raise SourcePacketError(f"provider envelope analyst provenance[{ticker}] counts drifted")
    for ticker, row in checked.items():
        source_provenance, counts = _validated_source_provenance(
            provenance[ticker], ticker=ticker, as_of=as_of, provider_id=provider_id, endpoint=endpoint
        )
        del source_provenance
        if (
            type(row) is not dict
            or set(row) != ({"disposition", "coverage_status", "parser_status"} | _SOURCE_PROVENANCE_COUNT_FIELDS)
            or row["disposition"] != "checked_no_recent_activity"
            or row["coverage_status"] != "full"
            or row["parser_status"] != "ok"
            or any(row[field] != counts[field] for field in _SOURCE_PROVENANCE_COUNT_FIELDS)
            or counts["total_record_count"] != counts["out_of_window_count"] + counts["future_excluded_count"]
        ):
            raise SourcePacketError(f"provider envelope analyst checked[{ticker}] is not source-bound")
    if any(type(reason) is not str for reason in excluded.values()):
        raise SourcePacketError("provider envelope analyst excluded dispositions must be exact str")


def _resolve_active_analyst_source(
    source_payloads: dict[str, Any], *, as_of: str, active_analyst_source: str,
) -> tuple[dict[str, Any], str]:
    """Validate and select the one analyst envelope consumed by all local consumers."""
    if active_analyst_source not in {"yfinance", "fmp"}:
        raise SourcePacketError("active_analyst_source must be exactly yfinance or fmp")
    path_field = "analyst_grade_actions_path"
    provider_id, endpoint, direction_map = (
        ("yfinance", "upgrades_downgrades", {"up": "up", "down": "down"})
        if active_analyst_source == "yfinance"
        else ("fmp", "grades", {"upgrade": "up", "downgrade": "down"})
    )
    _validate_resolved_analyst_grade_envelope(
        source_payloads[path_field],
        as_of=as_of,
        provider_id=provider_id,
        endpoint=endpoint,
        direction_map=direction_map,
    )
    return source_payloads[path_field], provider_id


def _validate_resolved_offering_envelope(result: Any, *, as_of: str) -> None:
    if type(result) is not dict or set(result) != _SEC_OFFERING_RESULT_KEYS:
        raise SourcePacketError("provider envelope SEC offering result keys drifted")
    signals = _canonical_provider_envelope_map(result["signals"], name="offering.signals")
    provenance = _canonical_provider_envelope_map(result["provenance"], name="offering.provenance")
    checked = _canonical_provider_envelope_map(result["checked"], name="offering.checked")
    excluded = _canonical_provider_envelope_map(result["excluded"], name="offering.excluded")
    identities = (set(signals), set(checked), set(excluded))
    if any(left & right for index, left in enumerate(identities) for right in identities[index + 1:]):
        raise SourcePacketError("provider envelope SEC offering dispositions overlap")
    if set(provenance) != (set(signals) | set(checked)):
        raise SourcePacketError("provider envelope SEC offering provenance identities drifted")
    reconstructed: dict[str, dict[str, Any]] = {}
    for ticker in (*signals, *checked):
        row = provenance[ticker]
        if type(row) is not dict or set(row) != {"active_offering"} or type(row["active_offering"]) is not dict:
            raise SourcePacketError(f"provider envelope SEC offering provenance[{ticker}] keys drifted")
        source_row = row["active_offering"]
        if set(source_row) != (_SOURCE_PROVENANCE_FIELDS | {"contributing_filings"}):
            raise SourcePacketError(f"provider envelope SEC offering provenance[{ticker}] source fields drifted")
        if source_row["provider_id"] != "sec_edgar" or source_row["endpoint_or_filing_type"] != "submissions":
            raise SourcePacketError(f"provider envelope SEC offering provenance[{ticker}] provider/endpoint drifted")
        reconstructed[ticker] = {
            "filings": source_row["contributing_filings"],
            "provenance": {field: source_row[field] for field in _SOURCE_PROVENANCE_FIELDS},
        }
    for ticker, row in excluded.items():
        if type(row) is not dict or set(row) != {"active_offering"} or type(row["active_offering"]) is not str:
            raise SourcePacketError(f"provider envelope SEC offering excluded[{ticker}] is malformed")
    try:
        replayed = resolve_offering_audit(as_of=as_of, filings_by_ticker=reconstructed)
    except Exception as exc:
        raise SourcePacketError(f"provider envelope SEC offering cannot replay its source facts: {exc}") from exc
    for field in ("signals", "provenance", "checked"):
        if replayed[field] != result[field]:
            raise SourcePacketError(f"provider envelope SEC offering {field} is not bound to provenance/filings")


def source_packet_input_manifest(packet_path: Path | str) -> tuple[tuple[str, str, str], ...]:
    """Return the exact source files consumed by a packet, with absolute paths and content digests."""
    _, paths = _load_and_validate_packet(packet_path)
    rows = []
    for field in (*SOURCE_PATH_FIELDS, *OPTIONAL_SOURCE_PATH_FIELDS):
        if field not in paths:
            continue
        path = paths[field].resolve()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append((field, str(path), digest))
    return tuple(rows)


def run_preflight(
    packet_path: Path | str = DEFAULT_PACKET_PATH,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    packet, paths = _load_and_validate_packet(packet_path)
    return {
        "schema_name": "us_short_batch5_data_context_source_packet_preflight_result",
        "schema_version": "1.1.0",
        "generated_at": generated_at or iso_now(),
        "packet_ref": _repo_rel(paths["packet_path"]),
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "preflight_status": "offline_preflight_passed",
            "network_access_required": False,
            "provider_calls_performed": False,
            "raw_payloads_read": False,
            "data_context_written": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "preflight_checks": {
            "packet_contract_validated": True,
            "source_paths_exist": True,
            "output_path_gitignored": True,
            "no_provider_fetch": packet["preflight_gates"]["no_provider_fetch"],
            "no_datahub_or_production": packet["preflight_gates"]["no_datahub_or_production"],
        },
        "paths": {
            "output_data_context_path": _repo_rel(paths["output_data_context_path"]),
            "source_artifact_count": sum(field in paths for field in (*SOURCE_PATH_FIELDS, *OPTIONAL_SOURCE_PATH_FIELDS)),
        },
    }


def run_packet(
    packet_path: Path | str = DEFAULT_PACKET_PATH,
    *,
    generated_at: str | None = None,
    context_components_output_path: Path | str | None = None,
    projection_binding_expectations: ProjectionBindingExpectations = FULL_CANDIDATE_LIVE_PROJECTION_BINDING,
    decision_lock: Any = None,
) -> dict[str, Any]:
    packet, paths = _load_and_validate_packet(packet_path)
    provider_envelope_digests = _validated_provider_envelope_digests(packet, paths)
    if context_components_output_path is not None:
        paths["output_context_components_path"] = _validate_output_path(
            context_components_output_path,
            field="output_context_components_path",
        )
    try:
        eligibility_governance = load_eligibility_governance(paths["eligibility_governance_path"])
        catalyst_governance = load_catalyst_governance(paths["catalyst_governance_path"])
        source_payloads = {
                field: _source_json(
                    paths[field],
                    field=field,
                    expected_sha256=provider_envelope_digests.get(field),
                )
            for field in (
                "candidate_artifact_path",
                "momentum_projection_path",
                "theme_projection_path",
                "offering_audit_source_path",
                "analyst_grade_actions_path",
                "massive_news_events_path",
                "theme_selection_contract_path",
            )
        }
        has_overextension_projection = "overextension_projection_path" in paths
        has_overextension_candidate = "overextension_candidate_artifact_path" in paths
        if has_overextension_projection != has_overextension_candidate:
            raise SourcePacketError(
                "overextension projection and its full eligible-universe candidate artifact must be paired"
            )
        if has_overextension_projection:
            source_payloads["overextension_projection_path"] = _source_json(
                paths["overextension_projection_path"], field="overextension_projection_path"
            )
            source_payloads["overextension_candidate_artifact_path"] = _source_json(
                paths["overextension_candidate_artifact_path"],
                field="overextension_candidate_artifact_path",
            )
        if "ohlcv_series_packet_path" in paths:
            source_payloads["ohlcv_series_packet_path"] = _source_json(
                paths["ohlcv_series_packet_path"], field="ohlcv_series_packet_path",
                expected_sha256=provider_envelope_digests["ohlcv_series_packet_path"],
            )
        provider_envelope_as_of = _provider_envelope_as_of(packet["decision_clock"]["expected_decision_date"])
        _validate_resolved_offering_envelope(
            source_payloads["offering_audit_source_path"], as_of=provider_envelope_as_of
        )
        active_analyst_payload, active_analyst_provider = _resolve_active_analyst_source(
            source_payloads,
            as_of=provider_envelope_as_of,
            active_analyst_source=packet["active_analyst_source"],
        )
        try:
            validate_resolved_news_events(
                news_events=source_payloads["massive_news_events_path"],
                as_of=packet["decision_clock"]["expected_decision_date"],
            )
        except Exception as exc:
            raise SourcePacketError(f"provider envelope Massive news rejected: {exc}") from exc
        active_source_payloads = dict(source_payloads)
        analyst_grade_actions = active_analyst_payload
        candidate = source_payloads["candidate_artifact_path"]
        try:
            validate_projection_binding(
                source_payloads["momentum_projection_path"],
                component="momentum",
                expected_decision_date=packet["decision_clock"]["expected_decision_date"],
                candidate_price_basis_date=candidate["price_basis_date"],
                source_as_of=candidate["used_date"],
                target_tickers=None,
                expected_producer_id=projection_binding_expectations.producer_id,
                expected_source_roles=projection_binding_expectations.momentum_source_roles,
                allowed_dispositions=set(projection_binding_expectations.momentum_allowed_dispositions),
                scored_dispositions=set(projection_binding_expectations.momentum_scored_dispositions),
            )
            validate_projection_binding(
                source_payloads["theme_projection_path"],
                component="theme",
                expected_decision_date=packet["decision_clock"]["expected_decision_date"],
                candidate_price_basis_date=candidate["price_basis_date"],
                source_as_of=candidate["used_date"],
                target_tickers=None,
                expected_producer_id=projection_binding_expectations.producer_id,
                expected_source_roles=projection_binding_expectations.theme_source_roles,
                allowed_dispositions=set(projection_binding_expectations.theme_allowed_dispositions),
                scored_dispositions=set(projection_binding_expectations.theme_scored_dispositions),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SourcePacketError(f"score projection source binding rejected: {exc}") from exc
        common_kwargs = {
            "candidate_artifact": source_payloads["candidate_artifact_path"],
            "expected_decision_date": packet["decision_clock"]["expected_decision_date"],
            "eligibility_governance": eligibility_governance,
            "momentum_projection": source_payloads["momentum_projection_path"],
            "theme_projection": source_payloads["theme_projection_path"],
            "offering_audit_source": source_payloads["offering_audit_source_path"],
            "analyst_grade_actions": analyst_grade_actions,
            "massive_news_events": source_payloads["massive_news_events_path"],
            "catalyst_governance": catalyst_governance,
            "theme_opportunity_state": packet["decision_clock"]["theme_opportunity_state"],
            "theme_selection_contract": source_payloads["theme_selection_contract_path"],
            "holdings": packet["optional_inputs"]["holdings"],
            "catalyst_recall_feed": packet["optional_inputs"]["catalyst_recall_feed"],
        }
        soft_requested = packet["optional_inputs"].get("theme_soft_boost_enabled", False)
        if soft_requested:
            try:
                soft_resolution = resolve_soft_boost_consumption(
                    expected_decision_date=packet["decision_clock"]["expected_decision_date"],
                    theme_soft_boost_enabled=True,
                    current_stage_result=packet["optional_inputs"]["soft_discovery_stage_result"],
                    stage_receipt_path=paths["provisional_theme_stage_receipt_path"],
                    validation_artifact_path=paths["provisional_theme_validation_path"],
                    candidate_artifact_path=paths["original_candidate_artifact_path"],
                    classification_packet_path=paths["classification_packet_path"],
                    state_dir=paths[SOFT_BOOST_STATE_DIR_PATH_FIELD],
                )
            except Exception:
                soft_resolution = degrade_soft_boost_consumption(
                    decision_date=packet["decision_clock"]["expected_decision_date"],
                )
        else:
            soft_resolution = None
        overextension_generated_at = None
        if "overextension_projection_path" in source_payloads:
            projection = source_payloads["overextension_projection_path"]
            validated_overextension = validate_overextension_projection(
                projection,
                candidate_artifact=source_payloads["overextension_candidate_artifact_path"],
                expected_decision_date=packet["decision_clock"]["expected_decision_date"],
                eligibility_governance=eligibility_governance,
            )
            common_kwargs["overextension_by_ticker"] = validated_overextension["overextension_by_ticker"]
            overextension_generated_at = validated_overextension["generated_at"]
        context_components = None
        soft_evidence_bundle_written = False
        soft_consumption_receipt_written = False
        if "output_context_components_path" in paths:
            component_kwargs = {
                **common_kwargs,
                "overextension_generated_at": overextension_generated_at,
                "source_ref_paths": {
                    field: _repo_rel(paths[field])
                    for field in (*SOURCE_PATH_FIELDS, *OPTIONAL_SOURCE_PATH_FIELDS)
                    if field in paths and field != "ohlcv_series_packet_path"
                },
            }
            # OFF is the mandatory baseline. Any failure in the optional ON/evidence
            # lifecycle below must return to these exact bytes, never abort Pass2.
            off_components = assemble_official_context_components_from_resolved_pass2_sources(
                **component_kwargs,
                theme_soft_boost_enabled=False,
            )
            context_components = off_components
            data_context = off_components["data_context"]
            if soft_resolution is not None:
                try:
                    on_components = (
                        assemble_official_context_components_from_resolved_pass2_sources(
                            **component_kwargs,
                            provisional_theme_validation=soft_resolution["validation_payload"],
                            theme_soft_boost_enabled=True,
                            provisional_theme_input_digests=soft_resolution["input_digests"],
                        )
                        if soft_resolution["effective_enabled"]
                        else off_components
                    )
                    on_selection = {
                        ticker: row["core_score"]
                        for ticker, row in on_components["data_context"][
                            "selection_inputs"
                        ]["per_ticker"].items()
                    }
                    off_selection = {
                        ticker: row["core_score"]
                        for ticker, row in off_components["data_context"][
                            "selection_inputs"
                        ]["per_ticker"].items()
                    }
                    if soft_resolution["effective_enabled"]:
                        boost_records = {
                            ticker: dict(
                                on_components["score_composition"]["analysis_by_ticker"][
                                    ticker
                                ]["provisional_theme_boost"]
                            )
                            for ticker in on_selection
                        }
                    else:
                        boost_records = {
                            ticker: {"theme_soft_boost": 0.0, "evidence_tier": None}
                            for ticker in on_selection
                        }
                    on_top15 = official_top15_tickers(
                        on_components["data_context"]["selection_inputs"],
                        decision_date=packet["decision_clock"]["expected_decision_date"],
                    )
                    off_top15 = official_top15_tickers(
                        off_components["data_context"]["selection_inputs"],
                        decision_date=packet["decision_clock"]["expected_decision_date"],
                    )
                    receipt = build_consumption_receipt(
                        resolved=soft_resolution,
                        generated_at=generated_at or iso_now(),
                        on_selection=on_selection,
                        off_selection=off_selection,
                        boost_records=boost_records,
                        on_top15=on_top15,
                        off_top15=off_top15,
                    )
                    if soft_resolution["effective_enabled"]:
                        common_input_sha256 = _soft_boost_common_input_sha256(packet, paths)
                        shadow = build_shadow_receipt(
                            resolved=soft_resolution,
                            generated_at=generated_at or iso_now(),
                            on_top15=on_top15,
                            off_top15=off_top15,
                            common_input_sha256=common_input_sha256,
                        )
                        write_evidence_bundle(
                            consumption_receipt=receipt,
                            consumption_path=paths["soft_boost_consumption_receipt_path"],
                            shadow_receipt=shadow,
                            shadow_path=paths["soft_boost_shadow_receipt_path"],
                            ledger_path=paths["soft_boost_comparison_ledger_path"],
                            state_dir=paths[SOFT_BOOST_STATE_DIR_PATH_FIELD],
                            decision_lock=decision_lock,
                        )
                        soft_evidence_bundle_written = True
                        soft_consumption_receipt_written = True
                        context_components = on_components
                        data_context = on_components["data_context"]
                    else:
                        try:
                            write_consumption_receipt(
                                receipt,
                                paths["soft_boost_consumption_receipt_path"],
                                state_dir=paths[SOFT_BOOST_STATE_DIR_PATH_FIELD],
                            )
                            soft_consumption_receipt_written = True
                        except Exception:
                            pass
                except Exception:
                    context_components = off_components
                    data_context = off_components["data_context"]
                    soft_resolution = degrade_soft_boost_consumption(
                        decision_date=packet["decision_clock"]["expected_decision_date"],
                    )
                    try:
                        zero_selection = {
                            ticker: row["core_score"]
                            for ticker, row in off_components["data_context"]["selection_inputs"]["per_ticker"].items()
                        }
                        zero_receipt = build_consumption_receipt(
                            resolved=soft_resolution,
                            generated_at=generated_at or iso_now(),
                            on_selection=zero_selection,
                            off_selection=zero_selection,
                            boost_records={
                                ticker: {"theme_soft_boost": 0.0, "evidence_tier": None}
                                for ticker in zero_selection
                            },
                            on_top15=official_top15_tickers(
                                off_components["data_context"]["selection_inputs"],
                                decision_date=packet["decision_clock"]["expected_decision_date"],
                            ),
                            off_top15=official_top15_tickers(
                                off_components["data_context"]["selection_inputs"],
                                decision_date=packet["decision_clock"]["expected_decision_date"],
                            ),
                        )
                        try:
                            write_consumption_receipt(
                                zero_receipt,
                                paths["soft_boost_consumption_receipt_path"],
                                state_dir=paths[SOFT_BOOST_STATE_DIR_PATH_FIELD],
                            )
                            soft_consumption_receipt_written = True
                        except Exception:
                            # A lifecycle failure is the result of this run, not a
                            # retry of a typed-zero receipt.  Keep the failure visible
                            # when the immutable zero slot belongs to an earlier run.
                            pass
                    except Exception:
                        pass
            # Cut4: one source-bound per-ticker record owns coverage, the catalyst availability annotation,
            # price input, and the output-visible quality/execution tags. The existing score and price engines
            # still do their own work; this only binds their permitted inputs to the local source packet.
            source_digests = {
                field: hashlib.sha256(path.read_bytes()).hexdigest()
                for field, path in paths.items()
                if field in (*SOURCE_PATH_FIELDS, *OPTIONAL_SOURCE_PATH_FIELDS)
            }
            try:
                source_facts = build_result_source_facts(
                    context_components=context_components,
                    source_payloads=active_source_payloads,
                    source_digests=source_digests,
                    ohlcv_packet=source_payloads.get("ohlcv_series_packet_path"),
                )
            except ResultSourceLinkageError as exc:
                raise SourcePacketError(f"Cut4 result-source linkage rejected: {exc}") from exc
            if set(source_facts) != set(context_components["per_ticker_analysis"]):
                raise SourcePacketError("Cut4 source facts do not exactly cover official analysis rows")
            context_components["per_ticker_analysis"] = {
                ticker: {**row, "source_result_facts": source_facts[ticker]}
                for ticker, row in context_components["per_ticker_analysis"].items()
            }
            context_components["result_linkage_sources"] = source_facts
            data_context = context_components["data_context"]
        else:
            data_context = assemble_data_context_from_resolved_pass2_sources(
                **common_kwargs,
                theme_soft_boost_enabled=False,
            )
    except SourcePacketError:
        raise
    except Exception as exc:
        raise SourcePacketError(f"source packet data_context assembly rejected: {exc}") from exc

    context_components_output_path = paths.get("output_context_components_path")
    if context_components_output_path is not None and context_components is not None:
        validate_current_context_components(context_components)
    output_path = paths["output_data_context_path"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data_context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if context_components_output_path is not None and context_components is not None:
        context_components_output_path.parent.mkdir(parents=True, exist_ok=True)
        context_components_output_path.write_text(
            json.dumps(context_components, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    result = {
        "schema_name": "us_short_batch5_data_context_source_packet_run_result",
        "schema_version": "1.0.0",
        "generated_at": generated_at or iso_now(),
        "active_analyst_source": packet["active_analyst_source"],
        "packet_ref": _repo_rel(paths["packet_path"]),
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "assembly_status": "data_context_assembled_from_resolved_sources",
            "network_access_required": False,
            "provider_calls_performed": False,
            "raw_payloads_read": False,
            "data_context_written": True,
            "context_components_written": context_components_output_path is not None,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "data_context": {
            "output_path": _repo_rel(output_path),
            "universe_count": len(data_context["universe"]),
            "selection_input_count": len(data_context["selection_inputs"]["per_ticker"]),
        },
        "context_components": {
            "output_path": _repo_rel(context_components_output_path) if context_components_output_path is not None else None,
            "per_ticker_analysis_count": (
                len(context_components["per_ticker_analysis"]) if context_components is not None else 0
            ),
            "result_linkage_source_count": (
                len(context_components["result_linkage_sources"]) if context_components is not None else 0
            ),
            "run_provenance_family_count": (
                len(context_components["run_provenance"]["families"]) if context_components is not None else 0
            ),
        },
        "source_artifacts": {
            "local_source_artifacts_read": sum(
                field in paths for field in (*SOURCE_PATH_FIELDS, *OPTIONAL_SOURCE_PATH_FIELDS)
            ),
            "source_artifacts_gitignored_required_for_raw_payloads": True,
        },
        "prohibited_claims": packet["prohibited_claims"],
    }
    if packet["optional_inputs"].get("theme_soft_boost_enabled", False):
        result["soft_boost"] = {
            "requested_enabled": True,
            "status": soft_resolution["status"],
            "reason_code": soft_resolution["reason_code"],
            "effective_enabled": soft_resolution["effective_enabled"],
            "evidence_bundle_written": soft_evidence_bundle_written,
            "consumption_receipt_path": (
                _repo_rel(paths["soft_boost_consumption_receipt_path"])
                if soft_consumption_receipt_written else None
            ),
            "shadow_receipt_path": (
                _repo_rel(paths["soft_boost_shadow_receipt_path"])
                if soft_evidence_bundle_written else None
            ),
            "comparison_ledger_path": (
                _repo_rel(paths["soft_boost_comparison_ledger_path"])
                if soft_evidence_bundle_written else None
            ),
            "provider_calls_performed": False,
        }
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Offline US-short Batch5 source-packet runner for assembling a Batch4 data_context. "
            "Consumes local resolved-source artifacts only; it never fetches providers, writes raw payloads, "
            "uses DataHub, or claims production/ship-gate evidence."
        )
    )
    parser.add_argument("--packet-path", type=Path, default=DEFAULT_PACKET_PATH)
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--generated-at", help="Optional deterministic timestamp for tests.")
    parser.add_argument(
        "--context-components-out",
        help="Optional repo-relative state/us_short/*.json path for official data_context/per_ticker/run_provenance.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.preflight_only:
        result = run_preflight(args.packet_path, generated_at=args.generated_at)
    else:
        result = run_packet(
            args.packet_path,
            generated_at=args.generated_at,
            context_components_output_path=args.context_components_out,
            projection_binding_expectations=PROJECTION_INPUTS_BINDING,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
