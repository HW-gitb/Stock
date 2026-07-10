from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_catalyst import load_catalyst_governance  # noqa: E402
from engine.us_short_eligibility_gate import load_eligibility_governance  # noqa: E402
from runners.us_short_batch5_data_context import (  # noqa: E402
    assemble_data_context_from_resolved_pass2_sources,
    assemble_official_context_components_from_resolved_pass2_sources,
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
)
OPTIONAL_SOURCE_PATH_FIELDS = ("overextension_projection_path", "yfinance_grade_actions_path")
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


class SourcePacketError(ValueError):
    """The local US-short Batch5 source packet cannot be consumed safely."""


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
    return packet, paths


def _source_json(path: Path, *, field: str) -> Any:
    try:
        return _read_json(path)
    except Exception as exc:
        raise SourcePacketError(f"paths.{field} could not be read as JSON: {_display_path(path)}") from exc


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
        "schema_version": "1.0.0",
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
) -> dict[str, Any]:
    packet, paths = _load_and_validate_packet(packet_path)
    if context_components_output_path is not None:
        paths["output_context_components_path"] = _validate_output_path(
            context_components_output_path,
            field="output_context_components_path",
        )
    try:
        eligibility_governance = load_eligibility_governance(paths["eligibility_governance_path"])
        catalyst_governance = load_catalyst_governance(paths["catalyst_governance_path"])
        source_payloads = {
            field: _source_json(paths[field], field=field)
            for field in (
                "candidate_artifact_path",
                "momentum_projection_path",
                "theme_projection_path",
                "offering_audit_source_path",
                "analyst_grade_actions_path",
                "massive_news_events_path",
            )
        }
        if "overextension_projection_path" in paths:
            source_payloads["overextension_projection_path"] = _source_json(
                paths["overextension_projection_path"], field="overextension_projection_path"
            )
        if "yfinance_grade_actions_path" in paths:
            source_payloads["yfinance_grade_actions_path"] = _source_json(
                paths["yfinance_grade_actions_path"], field="yfinance_grade_actions_path"
            )
        analyst_grade_actions = source_payloads.get(
            "yfinance_grade_actions_path",
            source_payloads["analyst_grade_actions_path"],
        )
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
            "holdings": packet["optional_inputs"]["holdings"],
            "catalyst_recall_feed": packet["optional_inputs"]["catalyst_recall_feed"],
        }
        if "overextension_projection_path" in source_payloads:
            projection = source_payloads["overextension_projection_path"]
            if type(projection) is not dict or type(projection.get("overextension_by_ticker")) is not dict:
                raise SourcePacketError(
                    "paths.overextension_projection_path must contain an overextension_by_ticker object"
                )
            common_kwargs["overextension_by_ticker"] = projection["overextension_by_ticker"]
        context_components = None
        if "output_context_components_path" in paths:
            context_components = assemble_official_context_components_from_resolved_pass2_sources(
                **common_kwargs,
                source_ref_paths={
                    field: _repo_rel(paths[field])
                    for field in (*SOURCE_PATH_FIELDS, *OPTIONAL_SOURCE_PATH_FIELDS)
                    if field in paths
                },
            )
            data_context = context_components["data_context"]
        else:
            data_context = assemble_data_context_from_resolved_pass2_sources(
                **common_kwargs,
            )
    except SourcePacketError:
        raise
    except Exception as exc:
        raise SourcePacketError(f"source packet data_context assembly rejected: {exc}") from exc

    output_path = paths["output_data_context_path"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data_context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    context_components_output_path = paths.get("output_context_components_path")
    if context_components_output_path is not None and context_components is not None:
        context_components_output_path.parent.mkdir(parents=True, exist_ok=True)
        context_components_output_path.write_text(
            json.dumps(context_components, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return {
        "schema_name": "us_short_batch5_data_context_source_packet_run_result",
        "schema_version": "1.0.0",
        "generated_at": generated_at or iso_now(),
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
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
