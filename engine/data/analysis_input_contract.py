from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_INPUT_SCHEMA_PATH = ROOT / "schemas" / "analysis_input.schema.json"
_DATE8_RE = re.compile(r"^[0-9]{8}$")


class AnalysisInputContractError(ValueError):
    """Raised when analysis_input passes JSON Schema but fails PIT invariants."""


def validate_analysis_input_file(path: str | Path, label: str | None = None) -> dict[str, Any]:
    input_path = Path(path)
    with input_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    validate_analysis_input_contract(payload, label=label or f"analysis_input {input_path}")
    return payload


def validate_analysis_input_contract(
    payload: Any,
    schema_path: str | Path = ANALYSIS_INPUT_SCHEMA_PATH,
    label: str = "analysis_input",
) -> None:
    validate_json_schema(payload, schema_path=schema_path, label=label)
    _validate_pit_invariants(payload, label=label)


def validate_json_schema(
    payload: Any,
    schema_path: str | Path = ANALYSIS_INPUT_SCHEMA_PATH,
    label: str = "analysis_input",
) -> None:
    try:
        from jsonschema import Draft7Validator
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "jsonschema is required to validate analysis_input contracts. "
            "Install with: python -m pip install -r requirements.txt"
        ) from exc

    with Path(schema_path).open("r", encoding="utf-8") as f:
        schema = json.load(f)

    Draft7Validator.check_schema(schema)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = "$" + "".join(f"[{repr(p)}]" for p in first.path)
        raise ValueError(f"{label} schema validation failed at {path}: {first.message}")


def _validate_pit_invariants(payload: dict[str, Any], label: str) -> None:
    trade_date = _parse_date8(payload.get("trade_date"), "trade_date", label)

    source = payload.get("source") or {}
    l3_mode = source.get("l3_mode")
    l3_snapshot_date = source.get("l3_snapshot_date")
    if l3_mode == "pit":
        if not l3_snapshot_date:
            raise AnalysisInputContractError(
                f"{label} PIT validation failed: source.l3_snapshot_date is required "
                "when source.l3_mode='pit'"
            )
        snapshot_date = _parse_date8(l3_snapshot_date, "source.l3_snapshot_date", label)
        if snapshot_date > trade_date:
            raise AnalysisInputContractError(
                f"{label} PIT validation failed: source.l3_snapshot_date "
                f"{l3_snapshot_date} is after trade_date {trade_date}"
            )

    for index, candidate in enumerate(payload.get("candidates") or []):
        if not isinstance(candidate, dict):
            continue
        expectation = ((candidate.get("fundamental") or {}).get("expectation") or {})
        _validate_candidate_date(
            expectation.get("earnings_report_date"),
            f"candidates[{index}].fundamental.expectation.earnings_report_date",
            trade_date,
            label,
        )


def _validate_candidate_date(value: Any, field_path: str, trade_date: str, label: str) -> None:
    if value in (None, ""):
        return
    date_value = _parse_date8(value, field_path, label)
    if date_value > trade_date:
        raise AnalysisInputContractError(
            f"{label} PIT validation failed: {field_path} {date_value} "
            f"is after trade_date {trade_date}"
        )


def _parse_date8(value: Any, field_path: str, label: str) -> str:
    if not isinstance(value, str) or not _DATE8_RE.match(value):
        raise AnalysisInputContractError(
            f"{label} PIT validation failed: {field_path} must be YYYYMMDD, got {value!r}"
        )
    return value
