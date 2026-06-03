from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
JOB_SPEC_SCHEMA_PATH = ROOT / "schemas" / "datahub_job_spec.schema.json"
RESOURCE_BUDGET_SCHEMA_PATH = ROOT / "schemas" / "datahub_local_resource_budget.schema.json"
RESOURCE_BUDGET_CONTRACT_PATH = ROOT / "docs" / "datahub_local_resource_budget_contract_20260602.json"


class DataHubJobSpecContractError(ValueError):
    """Raised when a DataHub job spec fails adjunct local-resource invariants."""


def validate_datahub_job_spec_file(
    path: str | Path,
    *,
    resource_budget_path: str | Path = RESOURCE_BUDGET_CONTRACT_PATH,
    label: str | None = None,
) -> dict[str, Any]:
    spec_path = Path(path)
    with spec_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    validate_datahub_job_spec_contract(
        payload,
        resource_budget_path=resource_budget_path,
        label=label or f"datahub_job_spec {spec_path}",
    )
    return payload


def validate_datahub_job_spec_contract(
    payload: Any,
    *,
    resource_budget_path: str | Path = RESOURCE_BUDGET_CONTRACT_PATH,
    label: str = "datahub_job_spec",
) -> None:
    validate_json_schema(payload, JOB_SPEC_SCHEMA_PATH, label)
    resource_budget = _load_and_validate_resource_budget(resource_budget_path)
    _validate_profile_contract(payload, resource_budget, label)
    _validate_partition_contract(payload, label)
    _validate_executable_review_gates(payload, label)
    _validate_no_scope_creep(payload, label)


def validate_json_schema(payload: Any, schema_path: str | Path, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "jsonschema is required to validate DataHub job specs. "
            "Install with: python -m pip install -r requirements.txt"
        ) from exc

    with Path(schema_path).open("r", encoding="utf-8") as f:
        schema = json.load(f)

    Draft7Validator.check_schema(schema)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = "$" + "".join(f"[{repr(p)}]" for p in first.path)
        raise DataHubJobSpecContractError(f"{label} schema validation failed at {path}: {first.message}")


def _load_and_validate_resource_budget(resource_budget_path: str | Path) -> dict[str, Any]:
    path = Path(resource_budget_path)
    with path.open("r", encoding="utf-8") as f:
        resource_budget = json.load(f)
    validate_json_schema(resource_budget, RESOURCE_BUDGET_SCHEMA_PATH, f"resource budget {path}")
    return resource_budget


def _validate_profile_contract(payload: dict[str, Any], resource_budget: dict[str, Any], label: str) -> None:
    profile = payload["budget_profile"]
    profile_id = profile["profile_id"]
    budget_profiles = {item["profile_id"]: item for item in resource_budget["budget_profiles"]}
    if profile_id not in budget_profiles:
        raise DataHubJobSpecContractError(
            f"{label} budget validation failed: profile_id {profile_id!r} is not in resource budget contract"
        )

    budget_profile = budget_profiles[profile_id]
    for field in [
        "requires_explicit_user_approval",
        "authorizes_provider_calls",
        "authorizes_datahub_implementation",
    ]:
        if profile[field] != budget_profile[field]:
            raise DataHubJobSpecContractError(
                f"{label} budget validation failed: budget_profile.{field}={profile[field]!r} "
                f"does not match resource budget {budget_profile[field]!r}"
            )

    if profile_id == "local_interactive_default" and not budget_profile["default_allowed"]:
        raise DataHubJobSpecContractError(
            f"{label} budget validation failed: local_interactive_default must remain default-allowed"
        )

    if profile_id == "reviewed_heavy_run_optional":
        if budget_profile["default_allowed"]:
            raise DataHubJobSpecContractError(
                f"{label} budget validation failed: reviewed_heavy_run_optional cannot be default-allowed"
            )
        if not profile["explicit_user_approval_recorded"] or not profile["approval_ref"]:
            raise DataHubJobSpecContractError(
                f"{label} budget validation failed: heavy profile requires explicit approval_ref"
            )
        if not _has_gate(payload, "heavy_run_approval"):
            raise DataHubJobSpecContractError(
                f"{label} budget validation failed: heavy profile requires a heavy_run_approval gate"
            )


def _validate_partition_contract(payload: dict[str, Any], label: str) -> None:
    partition = payload["partition_scope"]
    market = partition["market"]
    lane = partition["lane"]
    if market == "A" and not lane.startswith("a_"):
        raise DataHubJobSpecContractError(
            f"{label} partition validation failed: A market cannot use lane {lane!r}"
        )
    if market == "US" and not lane.startswith("us_"):
        raise DataHubJobSpecContractError(
            f"{label} partition validation failed: US market cannot use lane {lane!r}"
        )

    window = partition["date_window"]
    as_of = partition["as_of_date"]
    start = _parse_date8(window["start_date"], "date_window.start_date", label)
    end = _parse_date8(window["end_date"], "date_window.end_date", label)
    as_of_date = _parse_date8(as_of, "as_of_date", label)
    if end < start:
        raise DataHubJobSpecContractError(
            f"{label} partition validation failed: date_window.end_date is before start_date"
        )
    if not (start <= as_of_date <= end):
        raise DataHubJobSpecContractError(
            f"{label} partition validation failed: as_of_date must be inside date_window"
        )

    actual_days = (end - start).days + 1
    declared_max = window["max_calendar_days"]
    if actual_days > declared_max:
        raise DataHubJobSpecContractError(
            f"{label} partition validation failed: date_window spans {actual_days} days "
            f"but max_calendar_days is {declared_max}"
        )
    if window["window_role"] == "single_as_of" and (
        window["start_date"] != as_of or window["end_date"] != as_of or declared_max != 1
    ):
        raise DataHubJobSpecContractError(
            f"{label} partition validation failed: single_as_of must use start=end=as_of and max_calendar_days=1"
        )


def _validate_executable_review_gates(payload: dict[str, Any], label: str) -> None:
    identity = payload["job_identity"]
    status = identity["job_spec_status"]
    review_status = identity["review_status"]
    if status in {"reviewed_plan_not_executed", "reviewed_executable_plan"} and review_status != "reviewed":
        raise DataHubJobSpecContractError(
            f"{label} review validation failed: reviewed job specs must have review_status='reviewed'"
        )
    if status == "reviewed_executable_plan":
        blocking = [gate["gate_id"] for gate in payload["approval_gates"] if gate["blocks_execution"]]
        if blocking:
            raise DataHubJobSpecContractError(
                f"{label} review validation failed: executable job has blocking gates {blocking!r}"
            )


def _validate_no_scope_creep(payload: dict[str, Any], label: str) -> None:
    scope = payload["scope"]
    prohibited = payload["prohibited_actions"]
    execution = payload["execution_policy"]
    budget_profile = payload["budget_profile"]
    forbidden_scope = [
        "data_fetch_allowed",
        "provider_call_allowed",
        "provider_selection_allowed",
        "new_token_or_paid_access_allowed",
        "datahub_table_implementation_allowed",
        "runner_change_allowed",
        "phase7c_implementation_authorized_by_this_artifact",
        "broker_or_order_automation_allowed",
        "ship_gate_claim_allowed",
        "production_ready_claim_allowed",
    ]
    for field in forbidden_scope:
        if scope[field]:
            raise DataHubJobSpecContractError(f"{label} scope validation failed: scope.{field} must be false")

    for field, value in prohibited.items():
        if value:
            raise DataHubJobSpecContractError(
                f"{label} scope validation failed: prohibited_actions.{field} must be false"
            )

    for field in [
        "full_market_refresh_allowed",
        "all_markets_all_lanes_allowed",
        "provider_calls_allowed",
        "raw_payload_write_allowed",
        "production_runner_consumption_allowed",
    ]:
        if execution[field]:
            raise DataHubJobSpecContractError(
                f"{label} scope validation failed: execution_policy.{field} must be false"
            )

    for field in [
        "authorizes_provider_calls",
        "authorizes_datahub_implementation",
        "authorizes_runner_change",
    ]:
        if budget_profile[field]:
            raise DataHubJobSpecContractError(
                f"{label} scope validation failed: budget_profile.{field} must be false"
            )


def _has_gate(payload: dict[str, Any], gate_id: str) -> bool:
    return any(gate.get("gate_id") == gate_id for gate in payload["approval_gates"])


def _parse_date8(value: Any, field_path: str, label: str):
    if not isinstance(value, str):
        raise DataHubJobSpecContractError(
            f"{label} partition validation failed: {field_path} must be YYYYMMDD, got {value!r}"
        )
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise DataHubJobSpecContractError(
            f"{label} partition validation failed: {field_path} must be YYYYMMDD, got {value!r}"
        ) from exc
