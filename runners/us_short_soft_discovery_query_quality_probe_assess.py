"""Offline assessor for the separately authorized US-short query-quality probe.

This runner never calls a provider.  It consumes the frozen probe packet plus
the exact Web/X discovery, receipt, and plan-level budget slots registered by
that packet, computes the preregistered query-quality metrics, and writes one
immutable counts/digests/timestamps-only assessment.  It has no scoring, confirmation,
seat, lifecycle, operation-advice, or forward-clock effect.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_schema_formats import FORMAT_CHECKER  # noqa: E402
from engine import us_short_soft_discovery_query_quality_probe_paths as probe_paths  # noqa: E402
from engine import us_short_llm_theme_discovery_plan_budget as plan_budget  # noqa: E402
from runners import us_short_llm_theme_discovery_fetch_web as web  # noqa: E402
from runners import us_short_llm_theme_discovery_fetch_x as xfetch  # noqa: E402
from runners.us_short_discovery_publish_policy import (  # noqa: E402
    DiscoveryPublishPolicyError,
    write_immutable_json,
)


DEFAULT_PACKET_PATH = ROOT / "docs" / "us_short_soft_discovery_query_quality_probe_packet_20260730.json"
PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_soft_discovery_query_quality_probe_packet.schema.json"
PLAN_BUDGET_SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery_plan_budget.schema.json"
ASSESSMENT_SCHEMA_PATH = ROOT / "schemas" / "us_short_soft_discovery_query_quality_probe_assessment.schema.json"
DISCOVERY_SCHEMA_PATH = ROOT / "schemas" / "us_short_llm_theme_discovery.schema.json"


class QueryQualityProbeAssessmentError(ValueError):
    """The frozen query-quality probe cannot be assessed safely."""


@dataclass(frozen=True)
class _JsonSnapshot:
    path: Path
    raw_bytes: bytes
    payload: dict[str, Any]
    sha256: str


def _read_json_snapshot(path: Path, *, label: str) -> _JsonSnapshot:
    try:
        raw_bytes = path.read_bytes()
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise QueryQualityProbeAssessmentError(f"{label} is unreadable JSON: {path.name}") from exc
    if not isinstance(payload, dict):
        raise QueryQualityProbeAssessmentError(f"{label} must be a JSON object")
    return _JsonSnapshot(
        path=path,
        raw_bytes=raw_bytes,
        payload=payload,
        sha256=_sha256_bytes(raw_bytes),
    )


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    return _read_json_snapshot(path, label=label).payload


def _validate_schema(payload: dict[str, Any], schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
        schema = _read_json(schema_path, label=f"{label} schema")
    except ImportError as exc:  # pragma: no cover - the pinned project Python carries jsonschema.
        raise QueryQualityProbeAssessmentError("jsonschema is required") from exc
    errors = sorted(
        Draft7Validator(schema, format_checker=FORMAT_CHECKER).iter_errors(payload),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        first = errors[0]
        path = ".".join(str(part) for part in first.absolute_path) or "<root>"
        raise QueryQualityProbeAssessmentError(f"{label} schema violation at {path}: {first.message}")


def _canonical_bytes(payload: Any) -> bytes:
    try:
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError) as exc:
        raise QueryQualityProbeAssessmentError("assessment input is not canonically serializable") from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _parse_instant(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise QueryQualityProbeAssessmentError(
            f"{label} must be a timezone-aware RFC3339 instant"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QueryQualityProbeAssessmentError(
            f"{label} must be a timezone-aware RFC3339 instant"
        )
    return parsed


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _decision_cutoff(expected_decision_date: str) -> datetime:
    try:
        decision = datetime.strptime(expected_decision_date, "%Y%m%d")
    except (TypeError, ValueError) as exc:
        raise QueryQualityProbeAssessmentError(
            "expected_decision_date must be canonical YYYYMMDD"
        ) from exc
    return decision.replace(
        hour=9,
        minute=30,
        tzinfo=ZoneInfo("America/New_York"),
    )


def _causal_order_and_floor(
    *,
    packet: dict[str, Any],
    web_discovery: dict[str, Any],
    web_receipt: dict[str, Any],
    x_discovery: dict[str, Any],
    x_receipt: dict[str, Any],
    ledgers: dict[str, dict[str, Any]],
    lane_inconclusive_reasons: dict[str, list[str]],
) -> dict[str, Any]:
    decision_date = packet["probe_boundary"]["expected_decision_date"]
    cutoff = _decision_cutoff(decision_date)
    raw_components: list[tuple[str, Any]] = [
        ("packet.generated_at", packet["generated_at"]),
        ("web_discovery.generated_at", web_discovery["generated_at"]),
        ("web_receipt.generated_at", web_receipt["generated_at"]),
        ("x_discovery.generated_at", x_discovery["generated_at"]),
        ("x_receipt.generated_at", x_receipt["generated_at"]),
    ]
    packet_generated = _parse_instant(packet["generated_at"], label="packet.generated_at")
    ledger_instants: dict[str, tuple[datetime, datetime]] = {}
    for key, ledger in ledgers.items():
        first = _parse_instant(
            ledger["first_reserved_at"], label=f"{key}_ledger.first_reserved_at"
        )
        last = _parse_instant(
            ledger["last_reserved_at"], label=f"{key}_ledger.last_reserved_at"
        )
        if packet_generated > first:
            raise QueryQualityProbeAssessmentError(
                f"packet generated_at cannot be later than {key} first_reserved_at"
            )
        if first > last:
            raise QueryQualityProbeAssessmentError(
                f"{key} first_reserved_at cannot follow last_reserved_at"
            )
        ledger_instants[key] = (first, last)

    ledger_keys_by_lane = {
        "web": ("web",),
        "x": ("xai",),
    }
    for lane, discovery, receipt in (
        ("web", web_discovery, web_receipt),
        ("x", x_discovery, x_receipt),
    ):
        lane_fetches: list[tuple[str, datetime]] = []
        discovery_generated = _parse_instant(
            discovery["generated_at"], label=f"{lane}_discovery.generated_at"
        )
        receipt_generated = _parse_instant(
            receipt["generated_at"], label=f"{lane}_receipt.generated_at"
        )
        if discovery_generated > receipt_generated:
            raise QueryQualityProbeAssessmentError(
                f"{lane} discovery generated_at cannot be later than its receipt"
            )
        discovery_sources = {
            row["source_id"]: row for row in discovery["source_refs"]
        }
        receipt_sources = {
            row["source_id"]: (index, row)
            for index, row in enumerate(receipt["source_refs"])
        }
        for index, row in enumerate(discovery["source_refs"]):
            source_id = row["source_id"]
            receipt_index, receipt_row = receipt_sources[source_id]
            discovery_observed = _parse_instant(
                row["observed_at"],
                label=f"{lane}_discovery.source_refs[{index}].observed_at",
            )
            receipt_observed = _parse_instant(
                receipt_row["observed_at"],
                label=f"{lane}_receipt.source_refs[{receipt_index}].observed_at",
            )
            fetched = _parse_instant(
                receipt_row["fetched_at"],
                label=f"{lane}_receipt.source_refs[{receipt_index}].fetched_at",
            )
            if discovery_observed != receipt_observed:
                raise QueryQualityProbeAssessmentError(
                    f"{lane} discovery/receipt source observed_at mismatch"
                )
            if receipt_observed > fetched:
                raise QueryQualityProbeAssessmentError(
                    f"{lane} source observed_at cannot be later than fetched_at"
                )
            if fetched > discovery_generated:
                raise QueryQualityProbeAssessmentError(
                    f"{lane} source fetched_at cannot be later than discovery generated_at"
                )
            if fetched > receipt_generated:
                raise QueryQualityProbeAssessmentError(
                    f"{lane} source fetched_at cannot be later than receipt generated_at"
                )
            raw_components.extend((
                (
                    f"{lane}_discovery.source_refs[{index}].observed_at",
                    row["observed_at"],
                ),
                (
                    f"{lane}_receipt.source_refs[{receipt_index}].observed_at",
                    receipt_row["observed_at"],
                ),
            ))
            lane_fetches.append((
                f"{lane}_receipt.source_refs[{receipt_index}].fetched_at",
                fetched,
            ))
        for index, theme in enumerate(discovery["themes"]):
            observed = _parse_instant(
                theme["observed_at"],
                label=f"{lane}_discovery.themes[{index}].observed_at",
            )
            bound_source_fetched = [
                _parse_instant(
                    receipt_sources[source_id][1]["fetched_at"],
                    label=f"{lane} bound source {source_id} fetched_at",
                )
                for source_id in theme["source_ref_ids"]
            ]
            if bound_source_fetched and observed < max(bound_source_fetched):
                raise QueryQualityProbeAssessmentError(
                    f"{lane} theme observed_at cannot be earlier than its bound source fetches"
                )
            if observed > discovery_generated:
                raise QueryQualityProbeAssessmentError(
                    f"{lane} theme observed_at cannot be later than discovery generated_at"
                )
            raw_components.append((
                f"{lane}_discovery.themes[{index}].observed_at",
                theme["observed_at"],
            ))
        raw_components.extend(
            (f"{lane}_receipt.source_refs[{index}].fetched_at", row["fetched_at"])
            for index, row in enumerate(receipt["source_refs"])
        )
        for index, row in enumerate(receipt.get("provider_response_refs", [])):
            fetched = _parse_instant(
                row["fetched_at"],
                label=f"{lane}_receipt.provider_response_refs[{index}].fetched_at",
            )
            if fetched > receipt_generated:
                raise QueryQualityProbeAssessmentError(
                    f"{lane} provider response fetched_at cannot be later than receipt generated_at"
                )
            lane_fetches.append((
                f"{lane}_receipt.provider_response_refs[{index}].fetched_at",
                fetched,
            ))
            raw_components.append((
                f"{lane}_receipt.provider_response_refs[{index}].fetched_at",
                row["fetched_at"],
            ))
        if lane_fetches:
            execution_bound_label, execution_bound = min(
                lane_fetches, key=lambda row: row[1]
            )
        else:
            if not lane_inconclusive_reasons.get(lane):
                raise QueryQualityProbeAssessmentError(
                    f"{lane} causal order has no immutable provider/source evidence "
                    "and is not preregistered inconclusive"
                )
            execution_bound_label = f"{lane}_receipt.generated_at"
            execution_bound = receipt_generated
        for key in ledger_keys_by_lane[lane]:
            _, last = ledger_instants[key]
            if last <= execution_bound:
                continue
            raise QueryQualityProbeAssessmentError(
                f"{key} last_reserved_at cannot be later than {execution_bound_label}"
            )
    raw_components.extend(
        (f"{key}_ledger.{field}", ledger[field])
        for key, ledger in ledgers.items()
        for field in ("first_reserved_at", "last_reserved_at")
    )
    components = [
        {
            "component": label,
            "instant": _utc_text(_parse_instant(value, label=label)),
        }
        for label, value in raw_components
    ]
    for row in components:
        if _parse_instant(row["instant"], label=row["component"]) >= cutoff:
            raise QueryQualityProbeAssessmentError(
                f"{row['component']} must be strictly earlier than the decision cutoff"
            )
    floor = max(
        _parse_instant(row["instant"], label=row["component"])
        for row in components
    )
    return {"instant": _utc_text(floor), "components": components}


def _validate_assessment(payload: dict[str, Any], *, label: str) -> None:
    _validate_schema(payload, ASSESSMENT_SCHEMA_PATH, label=label)
    floor = payload["causal_floor"]
    component_names = [row["component"] for row in floor["components"]]
    if len(component_names) != len(set(component_names)):
        raise QueryQualityProbeAssessmentError(f"{label} has duplicate causal-floor components")
    component_floor = max(
        _parse_instant(row["instant"], label=f"{label} causal component {row['component']}")
        for row in floor["components"]
    )
    declared_floor = _parse_instant(floor["instant"], label=f"{label} causal_floor.instant")
    if declared_floor != component_floor:
        raise QueryQualityProbeAssessmentError(
            f"{label} causal_floor.instant does not equal its latest component"
        )
    generated = _parse_instant(payload["generated_at"], label=f"{label} generated_at")
    if generated < declared_floor:
        raise QueryQualityProbeAssessmentError(
            f"{label} generated_at cannot be earlier than its causal evidence floor"
        )


def _assert_snapshots_unchanged(snapshots: dict[str, _JsonSnapshot]) -> None:
    root = ROOT.absolute()
    for label, snapshot in snapshots.items():
        if (
            snapshot.path.absolute() != snapshot.path
            or not snapshot.path.is_relative_to(root)
            or _path_chain_has_symlink(snapshot.path, root)
            or not snapshot.path.is_file()
        ):
            raise QueryQualityProbeAssessmentError(
                f"{label} exact path changed after its validated read"
            )
        try:
            current = snapshot.path.read_bytes()
        except OSError as exc:
            raise QueryQualityProbeAssessmentError(
                f"{label} changed after its validated read"
            ) from exc
        if current != snapshot.raw_bytes or _sha256_bytes(current) != snapshot.sha256:
            raise QueryQualityProbeAssessmentError(
                f"{label} changed after its validated read"
            )


def _repo_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError as exc:
        raise QueryQualityProbeAssessmentError("probe input path must stay under the repository root") from exc


def _path_chain_has_symlink(path: Path, root: Path) -> bool:
    if path == root:
        return path.is_symlink()
    return path.is_symlink() or _path_chain_has_symlink(path.parent, root)


def _exact_input_path(candidate: Path, expected: Path, *, field: str) -> Path:
    root = ROOT.absolute()
    expected_absolute = expected.absolute()
    if candidate.is_absolute():
        if ".." in candidate.parts or "." in candidate.parts:
            raise QueryQualityProbeAssessmentError(
                f"{field} does not match the runner's exact decision slot"
            )
        candidate_absolute = candidate
    else:
        try:
            expected_relative = expected_absolute.relative_to(root)
        except ValueError as exc:
            raise QueryQualityProbeAssessmentError(
                f"{field} expected slot escapes the repository root"
            ) from exc
        if candidate.as_posix() != expected_relative.as_posix():
            raise QueryQualityProbeAssessmentError(
                f"{field} does not match the runner's exact decision slot"
            )
        candidate_absolute = root / candidate
    if (
        candidate_absolute != expected_absolute
        or not candidate_absolute.is_relative_to(root)
    ):
        raise QueryQualityProbeAssessmentError(
            f"{field} does not match the runner's exact decision slot"
        )
    if _path_chain_has_symlink(candidate_absolute, root):
        raise QueryQualityProbeAssessmentError(f"{field} must not be a symlink")
    if not candidate_absolute.is_file():
        raise QueryQualityProbeAssessmentError(f"{field} is missing: {candidate}")
    return candidate_absolute


def _exact_existing_path(raw: Any, expected: Path, *, field: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise QueryQualityProbeAssessmentError(f"{field} must be a repository-relative path")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise QueryQualityProbeAssessmentError(f"{field} must be a repository-relative path")
    return _exact_input_path(candidate, expected, field=field)


def _expected_slot_map(decision_date: str) -> dict[str, Any]:
    state_dir = ROOT / "state" / "us_short"
    return {
        "expected_decision_date": decision_date,
        "decision_outputs": {
            "web_discovery": _repo_relative(web.default_discovery_path(decision_date)),
            "web_receipt": _repo_relative(web.default_receipt_path(decision_date)),
            "x_discovery": _repo_relative(xfetch.default_discovery_path(decision_date)),
            "x_receipt": _repo_relative(xfetch.default_receipt_path(decision_date)),
        },
        "budget_ledgers": {
            "web": _repo_relative(
                plan_budget.default_plan_budget_path("web", decision_date, state_dir=state_dir)
            ),
            "xai": _repo_relative(
                plan_budget.default_plan_budget_path("xai", decision_date, state_dir=state_dir)
            ),
        },
        "raw_roots": {
            "web": _repo_relative(web.DEFAULT_RAW_ROOT),
            "x": _repo_relative(xfetch.DEFAULT_RAW_ROOT),
        },
        "assessment_path": _repo_relative(probe_paths.default_assessment_path(decision_date)),
        "output_or_receipt_overrides_allowed": False,
        "raw_root_overrides_allowed": False,
        "unregistered_slots_allowed": False,
    }


def _validate_packet(
    packet_path: Path,
) -> tuple[dict[str, Any], Path, str, list[str], _JsonSnapshot]:
    packet_path = _exact_input_path(
        packet_path,
        DEFAULT_PACKET_PATH,
        field="packet path",
    )
    snapshot = _read_json_snapshot(packet_path, label="query-quality probe packet")
    packet = snapshot.payload
    _validate_schema(packet, PACKET_SCHEMA_PATH, label="query-quality probe packet")
    decision_date = packet["probe_boundary"]["expected_decision_date"]
    if packet["execution_slot_map"] != _expected_slot_map(decision_date):
        raise QueryQualityProbeAssessmentError("packet execution_slot_map no longer matches real runner defaults")
    queries = [row["text"] for row in packet["query_templates"]]
    if len(queries) != packet["probe_boundary"]["query_count_per_lane"]:
        raise QueryQualityProbeAssessmentError("packet query count is inconsistent")
    return packet, packet_path, decision_date, queries, snapshot


def _validate_discovery_and_receipt(
    *, lane: str, discovery: dict[str, Any], receipt: dict[str, Any],
    decision_date: str, queries: list[str],
) -> list[str]:
    _validate_schema(discovery, DISCOVERY_SCHEMA_PATH, label=f"{lane} discovery")
    receipt_schema = web.SCHEMA_PATH if lane == "web" else xfetch.SCHEMA_PATH
    _validate_schema(receipt, receipt_schema, label=f"{lane} receipt")
    if discovery["decision_clock"]["expected_decision_date"] != decision_date:
        raise QueryQualityProbeAssessmentError(f"{lane} discovery decision date mismatch")
    if receipt["decision_clock"]["expected_decision_date"] != decision_date:
        raise QueryQualityProbeAssessmentError(f"{lane} receipt decision date mismatch")
    if receipt["queries"] != queries:
        raise QueryQualityProbeAssessmentError(f"{lane} receipt query bytes/order mismatch")
    if receipt["discovery_artifact_sha256"] != web._discovery_evidence_hash(discovery):
        raise QueryQualityProbeAssessmentError(f"{lane} receipt does not bind the discovery artifact")
    discovery_source_ids = [row["source_id"] for row in discovery["source_refs"]]
    receipt_source_ids = [row["source_id"] for row in receipt["source_refs"]]
    if len(set(discovery_source_ids)) != len(discovery_source_ids):
        raise QueryQualityProbeAssessmentError(f"{lane} discovery has duplicate source ids")
    if len(set(receipt_source_ids)) != len(receipt_source_ids):
        raise QueryQualityProbeAssessmentError(f"{lane} receipt has duplicate source ids")
    if set(discovery_source_ids) != set(receipt_source_ids):
        raise QueryQualityProbeAssessmentError(f"{lane} discovery/receipt source ids do not match")
    known_sources = set(discovery_source_ids)
    for theme in discovery["themes"]:
        if not set(theme["source_ref_ids"]).issubset(known_sources):
            raise QueryQualityProbeAssessmentError(f"{lane} theme contains an unbound source id")
        for member in theme["members"]:
            if not set(member["source_ref_ids"]).issubset(known_sources):
                raise QueryQualityProbeAssessmentError(f"{lane} member contains an unbound source id")
    summary = receipt["summary"]
    expected_summary = {
        "query_count": len(queries),
        "accepted_source_count": len(receipt_source_ids),
        "validated_theme_count": len(discovery["themes"]),
        "validated_member_count": sum(len(theme["members"]) for theme in discovery["themes"]),
    }
    for key, expected_value in expected_summary.items():
        if summary[key] != expected_value:
            raise QueryQualityProbeAssessmentError(f"{lane} receipt summary mismatch at {key}")
    if summary["dropped_result_count"] != len(receipt["drop_ledger"]):
        raise QueryQualityProbeAssessmentError(
            f"{lane} receipt summary mismatch at dropped_result_count"
        )

    contract = receipt["fetch_contract"]
    reasons: list[str] = []
    if contract["execution_mode"] != "live_authorized":
        reasons.append("execution_mode_not_live_authorized")
    if not contract["network_access_performed"] or not contract["provider_calls_performed"]:
        reasons.append("provider_calls_not_proven")
    transport_counts = contract["transport_response_counts"]
    source_raw_failure_reasons = (
        web.SOURCE_RAW_PUBLISH_FAILURE_REASONS
        if lane == "web"
        else xfetch.SOURCE_RAW_PUBLISH_FAILURE_REASONS
    )
    for row in receipt["drop_ledger"]:
        reason = row.get("reason")
        if (
            row.get("stage") == "search_result"
            and reason in source_raw_failure_reasons
        ):
            reasons.append(f"{lane}_source_raw_publish_failure:{reason}")
    if lane == "x":
        try:
            xfetch._validate_builder_receipt_evidence(
                receipt,
                completed_response_count=transport_counts["xai"],
            )
        except xfetch.XThemeDiscoveryError as exc:
            raise QueryQualityProbeAssessmentError(
                f"x receipt provider response evidence is incomplete: {exc}"
            ) from exc
        for row in receipt["drop_ledger"]:
            reason = row.get("reason")
            if reason in xfetch.PROVIDER_RESPONSE_DROP_REASONS:
                reasons.append(f"x_provider_response_failure:{reason}")
    else:
        regroup_counts = contract.get("regroup_chunk_counts")
        if (
            type(regroup_counts) is not dict
            or set(regroup_counts)
            != {"attempted", "successful", "failed", "failed_indexes"}
            or any(type(regroup_counts[key]) is not int or regroup_counts[key] < 0
                   for key in ("attempted", "successful", "failed"))
            or type(regroup_counts["failed_indexes"]) is not list
            or any(
                type(index) is not int or index < 0
                for index in regroup_counts["failed_indexes"]
            )
            or len(regroup_counts["failed_indexes"])
            != len(set(regroup_counts["failed_indexes"]))
            or regroup_counts["attempted"]
            != regroup_counts["successful"] + regroup_counts["failed"]
            or len(regroup_counts["failed_indexes"]) != regroup_counts["failed"]
            or any(
                index >= regroup_counts["attempted"]
                for index in regroup_counts["failed_indexes"]
            )
        ):
            raise QueryQualityProbeAssessmentError(
                "web receipt regroup chunk counts are missing or inconsistent"
            )
        deepseek_completed = transport_counts["deepseek"]
        if not (
            regroup_counts["successful"]
            <= deepseek_completed
            <= regroup_counts["attempted"]
        ):
            raise QueryQualityProbeAssessmentError(
                "web receipt regroup counts do not bind completed DeepSeek responses"
            )
        failed_indexes: list[int] = []
        provider_item_failed_indexes: list[int] = []
        for row in receipt["drop_ledger"]:
            reason = row.get("reason")
            if reason not in {
                "regroup_chunk_dropped",
                "provider_item_exception_dropped",
            }:
                continue
            try:
                index = (
                    web._regroup_chunk_drop_index(row)
                    if reason == "regroup_chunk_dropped"
                    else web._provider_item_chunk_drop_index(row)
                )
            except (KeyError, TypeError, web.WebThemeDiscoveryError):
                raise QueryQualityProbeAssessmentError(
                    "web receipt has malformed regroup chunk drop index"
                ) from None
            if index is None:
                if reason == "provider_item_exception_dropped":
                    continue
                raise QueryQualityProbeAssessmentError(
                    "web receipt has malformed regroup chunk drop index"
                )
            if reason == "regroup_chunk_dropped":
                failed_indexes.append(index)
            else:
                provider_item_failed_indexes.append(index)
        if sorted(provider_item_failed_indexes) != sorted(failed_indexes):
            raise QueryQualityProbeAssessmentError(
                "web receipt regroup chunk drops lack paired provider-item evidence"
            )
        if (
            len(failed_indexes) != len(set(failed_indexes))
            or sorted(failed_indexes) != sorted(regroup_counts["failed_indexes"])
        ):
            raise QueryQualityProbeAssessmentError(
                "web receipt regroup chunk drops do not match audited counts"
            )
        if regroup_counts["failed"]:
            reasons.append("web_regroup_failed")
        if any(
            row.get("stage") == "search_result"
            and row.get("reason") in web.INCONCLUSIVE_SEARCH_RESULT_REASONS
            for row in receipt["drop_ledger"]
        ):
            reasons.append("web_provider_or_transport_failed")
    transport_call_count = sum(transport_counts.values())
    has_immutable_execution_ref = bool(
        receipt["source_refs"] or receipt.get("provider_response_refs", [])
    )
    if (
        not has_immutable_execution_ref
        and (
            contract["network_call_count"] != transport_call_count
            or contract["provider_call_count"] != transport_call_count
        )
    ):
        raise QueryQualityProbeAssessmentError(
            f"{lane} zero-ref execution accounting is incomplete"
        )
    if contract["network_call_count"] != transport_call_count:
        reasons.append("network_call_count_not_bound_to_transport")
    if contract["provider_call_count"] != transport_call_count:
        reasons.append("provider_call_count_not_bound_to_transport")
    if not has_immutable_execution_ref:
        reasons.append(f"{lane}_immutable_execution_evidence_missing")
    model = contract["regroup_model"] if lane == "web" else contract["grok_model"]
    model_was_called = (
        transport_counts["deepseek"] > 0 if lane == "web" else transport_counts["xai"] > 0
    )
    if model_was_called and not model["served_model"]:
        reasons.append("served_model_identity_missing")
    return reasons


def _validate_budget_ledger(
    ledger: dict[str, Any], *, provider: str, decision_date: str,
    queries: list[str], expected_call_count: int,
) -> int:
    label = f"{provider} plan budget ledger"
    _validate_schema(ledger, PLAN_BUDGET_SCHEMA_PATH, label=label)
    required_identity = {
        "lane": "us_short",
        "provider": provider,
        "decision_date": decision_date,
        "planned_provider_call_count": expected_call_count,
    }
    for key, expected in required_identity.items():
        if ledger.get(key) != expected:
            raise QueryQualityProbeAssessmentError(f"{label} mismatch at {key}")
    envelope = ledger.get("provider_envelope")
    if (
        not isinstance(envelope, dict)
        or envelope.get("provider") != provider
        or envelope.get("max_dispatch_count") != expected_call_count
    ):
        raise QueryQualityProbeAssessmentError(f"{label} provider envelope is not exact")

    attempt_count = ledger.get("reservation_attempt_count")
    if (
        isinstance(attempt_count, bool)
        or not isinstance(attempt_count, int)
        or attempt_count < 1
    ):
        raise QueryQualityProbeAssessmentError(
            f"{label} mismatch at reservation_attempt_count"
        )

    reservations = ledger.get("query_reservations")
    if not isinstance(reservations, list):
        raise QueryQualityProbeAssessmentError(f"{label} query scope is not exact")
    reservation_keys = [
        (row.get("query_sha256"), row.get("stage"), row.get("vendor"))
        for row in reservations if isinstance(row, dict)
    ]
    if len(reservation_keys) != len(reservations) or len(set(reservation_keys)) != len(reservation_keys):
        raise QueryQualityProbeAssessmentError(f"{label} query scope is not exact")
    expected_stage1_vendor = "tavily" if provider == "web" else "xai"
    expected_stage1 = {
        (_sha256_bytes(query.encode("utf-8")), "stage1", expected_stage1_vendor)
        for query in queries
    }
    actual_stage1 = set(reservation_keys) & {
        (key[0], key[1], key[2]) for key in reservation_keys
        if key[1] == "stage1" and key[2] == expected_stage1_vendor
    }
    if actual_stage1 != expected_stage1:
        raise QueryQualityProbeAssessmentError(f"{label} query scope is not exact")
    for row in reservations:
        if (
            row.get("query_count") != 1
            or row.get("planned_provider_call_count") != 1
            or row.get("attempt_count", 0) < 1
            or row.get("last_status") not in {"in_flight", "complete", "failure", "unknown"}
        ):
            raise QueryQualityProbeAssessmentError(f"{label} query scope is not exact")

    counts = ledger.get("dispatch_counts", {})
    if (
        counts.get("dispatch_count")
        != counts.get("stage1_dispatch_count", 0)
        + counts.get("stage2_dispatch_count", 0)
        + counts.get("retry_dispatch_count", 0)
    ):
        raise QueryQualityProbeAssessmentError(f"{label} dispatch counts are inconsistent")
    instants: dict[str, datetime] = {}
    for field in ("first_reserved_at", "last_reserved_at"):
        try:
            instants[field] = _parse_instant(
                ledger[field], label=f"{label} {field}"
            )
        except KeyError as exc:
            raise QueryQualityProbeAssessmentError(
                f"{label} has bad {field}"
            ) from exc
    if instants["first_reserved_at"] > instants["last_reserved_at"]:
        raise QueryQualityProbeAssessmentError(
            f"{label} first_reserved_at cannot follow last_reserved_at"
        )
    return attempt_count


def _lane_metrics(
    discovery: dict[str, Any], receipt: dict[str, Any], thresholds: dict[str, Any],
) -> dict[str, Any]:
    tickers = {
        member["ticker"]
        for theme in discovery["themes"]
        for member in theme["members"]
    }
    accepted_source_ids = {row["source_id"] for row in receipt["source_refs"]}
    used_source_ids = {
        source_id
        for theme in discovery["themes"]
        for member in theme["members"]
        for source_id in member["source_ref_ids"]
        if source_id in accepted_source_ids
    }
    accepted_count = len(accepted_source_ids)
    ratio = len(used_source_ids) / accepted_count if accepted_count else 0.0
    metrics = {
        "validated_theme_count": len(discovery["themes"]),
        "source_bound_member_count": len(tickers),
        "accepted_source_count": accepted_count,
        "member_bound_source_count": len(used_source_ids),
        "member_bound_source_ratio": ratio,
    }
    failures = []
    if metrics["validated_theme_count"] < thresholds["minimum_validated_theme_count"]:
        failures.append("validated_theme_count_below_threshold")
    if metrics["source_bound_member_count"] < thresholds["minimum_source_bound_member_count"]:
        failures.append("source_bound_member_count_below_threshold")
    if ratio < thresholds["minimum_member_bound_source_ratio"]:
        failures.append("member_bound_source_ratio_below_threshold")
    return {**metrics, "quality_thresholds_met": not failures, "quality_failure_reasons": failures}


def _build_assessment_with_snapshots(
    *, packet_path: Path = DEFAULT_PACKET_PATH, assessment_path: Path | None = None,
    generated_at: str,
) -> tuple[dict[str, Any], Path, dict[str, _JsonSnapshot]]:
    """Preflight every exact input and build a schema-valid assessment without writing it."""
    packet, validated_packet_path, decision_date, queries, packet_snapshot = _validate_packet(
        Path(packet_path)
    )
    # Load-bearing C2 gate: resolve the only tracked target before reading inputs or staging bytes.
    try:
        output = probe_paths.validate_assessment_path(
            assessment_path or probe_paths.default_assessment_path(decision_date),
            decision_date,
        )
    except probe_paths.QueryQualityProbePathError as exc:
        raise QueryQualityProbeAssessmentError(str(exc)) from exc
    slots = packet["execution_slot_map"]
    expected = _expected_slot_map(decision_date)
    paths = {
        key: _exact_existing_path(slots["decision_outputs"][key], ROOT / expected["decision_outputs"][key], field=key)
        for key in ("web_discovery", "web_receipt", "x_discovery", "x_receipt")
    }
    ledger_paths = {
        key: _exact_existing_path(slots["budget_ledgers"][key], ROOT / expected["budget_ledgers"][key], field=key)
        for key in ("web", "xai")
    }
    input_snapshots = {
        "web_discovery": _read_json_snapshot(paths["web_discovery"], label="web discovery"),
        "web_receipt": _read_json_snapshot(paths["web_receipt"], label="web receipt"),
        "x_discovery": _read_json_snapshot(paths["x_discovery"], label="x discovery"),
        "x_receipt": _read_json_snapshot(paths["x_receipt"], label="x receipt"),
    }
    web_discovery = input_snapshots["web_discovery"].payload
    web_receipt = input_snapshots["web_receipt"].payload
    x_discovery = input_snapshots["x_discovery"].payload
    x_receipt = input_snapshots["x_receipt"].payload
    lane_inconclusive_reasons = {
        "web": _validate_discovery_and_receipt(
            lane="web", discovery=web_discovery, receipt=web_receipt,
            decision_date=decision_date, queries=queries,
        ),
        "x": _validate_discovery_and_receipt(
            lane="x", discovery=x_discovery, receipt=x_receipt,
            decision_date=decision_date, queries=queries,
        ),
    }
    inconclusive = (
        lane_inconclusive_reasons["web"] + lane_inconclusive_reasons["x"]
    )
    expected_calls = {
        "web": (
            packet["provider_budget"]["tavily"]["current_ledger_reservation_units"]
            + packet["provider_budget"]["deepseek"]["current_ledger_reservation_units"]
        ),
        "xai": packet["provider_budget"]["xai"]["current_ledger_reservation_units"],
    }
    ledger_snapshots = {
        key: _read_json_snapshot(
            path,
            label=f"{key} plan budget ledger",
        )
        for key, path in ledger_paths.items()
    }
    input_snapshots.update(ledger_snapshots)
    ledgers = {key: snapshot.payload for key, snapshot in ledger_snapshots.items()}
    budget_reservation_attempt_counts: dict[str, int] = {}
    for key, ledger in ledgers.items():
        attempt_count = _validate_budget_ledger(
            ledger,
            provider=key, decision_date=decision_date, queries=queries,
            expected_call_count=expected_calls[key],
        )
        budget_reservation_attempt_counts[key] = attempt_count
        if attempt_count > 1:
            retry_reason = "actual_call_count_or_scope_cannot_be_proven"
            inconclusive.append(retry_reason)
            lane_inconclusive_reasons["web" if key == "web" else "x"].append(retry_reason)

    actual_counts = {
        "tavily": web_receipt["fetch_contract"]["transport_response_counts"]["tavily"],
        "deepseek": web_receipt["fetch_contract"]["transport_response_counts"]["deepseek"],
        "xai": x_receipt["fetch_contract"]["transport_response_counts"]["xai"],
    }
    provider_caps = {
        "tavily": packet["provider_budget"]["tavily"]["max_actual_calls"],
        "deepseek": packet["provider_budget"]["deepseek"]["structural_max_actual_calls"],
        "xai": packet["provider_budget"]["xai"]["max_actual_calls"],
    }
    if actual_counts["tavily"] != packet["provider_budget"]["tavily"]["planned_calls"]:
        inconclusive.append("tavily_query_call_count_not_proven")
    if actual_counts["xai"] != packet["provider_budget"]["xai"]["planned_calls"]:
        inconclusive.append("xai_query_call_count_not_proven")
    if any(actual_counts[name] > provider_caps[name] for name in actual_counts):
        inconclusive.append("actual_provider_call_cap_exceeded")
    if sum(actual_counts.values()) > packet["provider_budget"]["max_actual_provider_calls"]:
        inconclusive.append("total_actual_provider_call_cap_exceeded")
    thresholds = packet["preregistered_evaluation"]["per_lane_quality_thresholds"]
    lanes = {
        "web": _lane_metrics(web_discovery, web_receipt, thresholds),
        "x": _lane_metrics(x_discovery, x_receipt, thresholds),
    }
    distinct_theme_ids = len({
        theme["theme_id"]
        for discovery in (web_discovery, x_discovery)
        for theme in discovery["themes"]
    })
    if inconclusive:
        verdict = packet["preregistered_evaluation"]["inconclusive_verdict"]
    elif all(row["quality_thresholds_met"] for row in lanes.values()):
        verdict = packet["preregistered_evaluation"]["pass_verdict"]
    else:
        verdict = packet["preregistered_evaluation"]["quality_fail_verdict"]

    causal_floor = _causal_order_and_floor(
        packet=packet,
        web_discovery=web_discovery,
        web_receipt=web_receipt,
        x_discovery=x_discovery,
        x_receipt=x_receipt,
        ledgers=ledgers,
        lane_inconclusive_reasons=lane_inconclusive_reasons,
    )
    parsed_generated = _parse_instant(generated_at, label="generated_at")
    parsed_floor = _parse_instant(causal_floor["instant"], label="causal_floor.instant")
    if parsed_generated < parsed_floor:
        raise QueryQualityProbeAssessmentError(
            "generated_at cannot be earlier than the causal evidence floor"
        )
    assessment = {
        "schema_name": "us_short_soft_discovery_query_quality_probe_assessment",
        "schema_version": "1.4.0",
        "schema_ref": "schemas/us_short_soft_discovery_query_quality_probe_assessment.schema.json",
        "generated_at": parsed_generated.isoformat(),
        "causal_floor": causal_floor,
        "probe_identity": {
            "expected_decision_date": decision_date,
            "policy_version": packet["policy_draft"]["policy_version"],
            "packet_ref": _repo_relative(validated_packet_path),
            "packet_sha256": packet_snapshot.sha256,
            "query_scope_sha256": _sha256_bytes(_canonical_bytes(queries)),
        },
        "input_bindings": {
            key: {
                "path": _repo_relative(snapshot.path),
                "sha256": snapshot.sha256,
            }
            for key, snapshot in input_snapshots.items()
        },
        "execution_evidence": {
            "actual_provider_call_counts": actual_counts,
            "actual_provider_call_count": sum(actual_counts.values()),
            "budget_reservation_attempt_counts": budget_reservation_attempt_counts,
            "web_regroup_chunk_counts":
                dict(web_receipt["fetch_contract"]["regroup_chunk_counts"]),
            "all_exact_slots_bound": True,
            "all_budget_scopes_bound": True,
            "inconclusive_reasons": sorted(set(inconclusive)),
        },
        "lane_assessments": lanes,
        "combined_diagnostic": {
            "distinct_candidate_theme_ids": distinct_theme_ids,
            "distinct_candidate_theme_ids_diagnostic_target":
                packet["preregistered_evaluation"]["combined_quality_thresholds"][
                    "distinct_candidate_theme_ids_diagnostic_target"
                ],
            "breadth_diagnostic_is_pass_gate": False,
        },
        "verdict": verdict,
        "prohibited_effects": dict(packet["prohibited_effects"]),
    }
    _validate_assessment(assessment, label="query-quality probe assessment")
    all_snapshots = {"packet": packet_snapshot, **input_snapshots}
    _assert_snapshots_unchanged(all_snapshots)
    return assessment, output, all_snapshots


def build_assessment(
    *, packet_path: Path = DEFAULT_PACKET_PATH, assessment_path: Path | None = None,
    generated_at: str,
) -> tuple[dict[str, Any], Path]:
    assessment, output, _ = _build_assessment_with_snapshots(
        packet_path=packet_path,
        assessment_path=assessment_path,
        generated_at=generated_at,
    )
    return assessment, output


def run_assessment(
    *, packet_path: Path = DEFAULT_PACKET_PATH, assessment_path: Path | None = None,
    generated_at: str, preflight_only: bool = False,
) -> dict[str, Any]:
    assessment, output, snapshots = _build_assessment_with_snapshots(
        packet_path=packet_path, assessment_path=assessment_path, generated_at=generated_at,
    )
    if not preflight_only:
        # C2 must stay immediately load-bearing at the tracked write boundary.
        try:
            output = probe_paths.validate_assessment_path(
                output, assessment["probe_identity"]["expected_decision_date"],
            )
        except probe_paths.QueryQualityProbePathError as exc:
            raise QueryQualityProbeAssessmentError(str(exc)) from exc
        _assert_snapshots_unchanged(snapshots)
        try:
            write_immutable_json(
                assessment,
                output,
                verify=lambda payload: _validate_assessment(
                    payload, label="frozen query-quality probe assessment",
                ),
            )
        except DiscoveryPublishPolicyError as exc:
            raise QueryQualityProbeAssessmentError(str(exc)) from exc
    return {
        "status": "preflight_passed_no_write" if preflight_only else "assessment_written_or_reused",
        "assessment_path": _repo_relative(output),
        "verdict": assessment["verdict"],
        "provider_calls_performed_by_assessor": False,
        "network_access_performed_by_assessor": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preflight or generate the offline US-short query-quality probe assessment."
    )
    parser.add_argument("--packet-path", type=Path, default=DEFAULT_PACKET_PATH)
    parser.add_argument("--assessment-output", type=Path, default=None)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    summary = run_assessment(
        packet_path=args.packet_path,
        assessment_path=args.assessment_output,
        generated_at=args.generated_at,
        preflight_only=args.preflight_only,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
