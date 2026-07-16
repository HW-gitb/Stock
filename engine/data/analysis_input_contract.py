from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
ANALYSIS_INPUT_SCHEMA_PATH = ROOT / "schemas" / "analysis_input.schema.json"
_DATE8_RE = re.compile(r"^[0-9]{8}$")


class AnalysisInputContractError(ValueError):
    """Raised when analysis_input passes JSON Schema but fails PIT invariants."""


def candidate_digest(candidates: Any) -> str:
    if not isinstance(candidates, list):
        raise AnalysisInputContractError("candidates must be a list before digesting")
    encoded = json.dumps(
        candidates, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_a_short_run_identity(trade_date: str, candidates: list[dict[str, Any]]) -> dict[str, str]:
    date_value = _parse_date8(trade_date, "trade_date", "run identity")
    digest = candidate_digest(candidates)
    return {
        "run_id": f"a-short-{date_value}-{digest[:16]}",
        "candidate_digest": digest,
        "stage_status": "egs_validated",
    }


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
    hard_sources = source.get("hard_veto_source_health")
    if hard_sources is not None:
        for name in ("suspension", "unlock", "holder_reduction"):
            item = hard_sources.get(name) or {}
            if item.get("status") == "unknown":
                raise AnalysisInputContractError(
                    f"{label} hard-veto source {name} is unknown; actionable candidates are blocked"
                )
            _validate_candidate_date(
                item.get("observed_at"), f"source.hard_veto_source_health.{name}.observed_at",
                trade_date, label,
            )
    run_identity = source.get("run_identity")
    if run_identity is not None:
        expected_digest = candidate_digest(payload.get("candidates") or [])
        if run_identity.get("candidate_digest") != expected_digest:
            raise AnalysisInputContractError(f"{label} candidate_digest does not match candidates")
        expected_run_id = f"a-short-{trade_date}-{expected_digest[:16]}"
        if run_identity.get("run_id") != expected_run_id:
            raise AnalysisInputContractError(f"{label} run_id does not match trade_date/candidate_digest")
    l3_mode = source.get("l3_mode")
    l3_snapshot_date = source.get("l3_snapshot_date")
    l3_provider = source.get("l3_provider")
    l3_coverage = source.get("l3_coverage")
    schema_version = payload.get("schema_version")
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
    if l3_coverage is not None:
        if l3_provider != "hithink_finance":
            raise AnalysisInputContractError(
                f"{label} L3 coverage requires source.l3_provider='hithink_finance'"
            )
        if l3_coverage.get("catalog_board_count") != l3_coverage.get("received_board_count"):
            raise AnalysisInputContractError(
                f"{label} L3 coverage is incomplete: catalog and received board counts differ"
            )
        if l3_coverage.get("complete") is not True:
            raise AnalysisInputContractError(f"{label} L3 coverage is not complete")
        if l3_coverage.get("scoring_universe") != "a_share_main_board":
            raise AnalysisInputContractError(f"{label} L3 coverage is not main-board scoped")
        catalog_count = l3_coverage.get("catalog_board_count")
        verified_empty_count = l3_coverage.get("verified_empty_board_count")
        scope_empty_count = l3_coverage.get("scope_filtered_empty_board_count")
        raw_pair_count = l3_coverage.get("raw_member_row_count")
        unique_pair_count = l3_coverage.get("unique_member_pair_count")
        main_board_pair_count = l3_coverage.get("main_board_member_pair_count")
        excluded_pair_count = l3_coverage.get("excluded_non_main_board_member_count")
        out_of_a_share_count = l3_coverage.get("out_of_a_share_member_count")
        suffix_pair_count = sum((l3_coverage.get("market_suffix_counts") or {}).values())
        if verified_empty_count + scope_empty_count > catalog_count:
            raise AnalysisInputContractError(f"{label} L3 empty-board counts exceed catalog size")
        if raw_pair_count < unique_pair_count:
            raise AnalysisInputContractError(f"{label} L3 raw member rows are below unique pairs")
        if main_board_pair_count + excluded_pair_count != unique_pair_count:
            raise AnalysisInputContractError(f"{label} L3 scoped member-pair counts do not reconcile")
        if out_of_a_share_count > excluded_pair_count:
            raise AnalysisInputContractError(f"{label} L3 out-of-A-share count exceeds exclusions")
        if suffix_pair_count != unique_pair_count:
            raise AnalysisInputContractError(f"{label} L3 market suffix counts do not reconcile")

    if schema_version == "1.2.0":
        if l3_mode == "today":
            if l3_provider != "hithink_finance" or l3_coverage is None:
                raise AnalysisInputContractError(
                    f"{label} current live L3 requires hithink_finance with a complete coverage receipt"
                )
            if source.get("data_provider") != "mixed":
                raise AnalysisInputContractError(
                    f"{label} current live L3 requires source.data_provider='mixed'"
                )
        elif l3_mode == "pit":
            if l3_provider not in {"hithink_finance", "legacy_tushare_snapshot"}:
                raise AnalysisInputContractError(
                    f"{label} current PIT L3 requires explicit snapshot provider provenance"
                )
            if l3_provider == "hithink_finance" and l3_coverage is None:
                raise AnalysisInputContractError(
                    f"{label} current HiThink PIT L3 requires its persisted coverage receipt"
                )
            expected_data_provider = "mixed" if l3_provider == "hithink_finance" else "tushare"
            if source.get("data_provider") != expected_data_provider:
                raise AnalysisInputContractError(
                    f"{label} PIT data_provider does not match L3 snapshot provider"
                )
        elif l3_mode == "neutralize":
            if l3_provider != "neutralized" or l3_coverage is not None:
                raise AnalysisInputContractError(
                    f"{label} neutralized L3 requires provider='neutralized' and null coverage"
                )
            if source.get("data_provider") != "tushare":
                raise AnalysisInputContractError(
                    f"{label} neutralized L3 requires source.data_provider='tushare'"
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
        quote = candidate.get("quote") or {}
        source_date = quote.get("source_trade_date")
        if source_date is not None:
            parsed_source_date = _parse_date8(
                source_date, f"candidates[{index}].quote.source_trade_date", label
            )
            if parsed_source_date > trade_date:
                raise AnalysisInputContractError(
                    f"{label} PIT validation failed: candidates[{index}].quote.source_trade_date "
                    f"{parsed_source_date} is after trade_date {trade_date}"
                )
            calendar = ((payload.get("market_context") or {}).get("trade_calendar") or {})
            recent_dates = calendar.get("recent_trade_dates")
            if recent_dates is not None and parsed_source_date not in recent_dates:
                raise AnalysisInputContractError(
                    f"{label} quote source date {parsed_source_date} is absent from official recent_trade_dates"
                )
        price_time = quote.get("price_time")
        if price_time is not None:
            try:
                price_dt = datetime.fromisoformat(str(price_time).replace("Z", "+00:00"))
                generated_dt = datetime.fromisoformat(str(payload.get("generated_at")).replace("Z", "+00:00"))
            except (TypeError, ValueError) as exc:
                raise AnalysisInputContractError(
                    f"{label} quote/generated timestamp must be valid ISO 8601"
                ) from exc
            if price_dt.tzinfo is None or generated_dt.tzinfo is None:
                raise AnalysisInputContractError(f"{label} quote/generated timestamp must include timezone")
            if price_dt > generated_dt:
                raise AnalysisInputContractError(
                    f"{label} quote price_time {price_time} is after generated_at {payload.get('generated_at')}"
                )
            if source_date is not None and price_dt.strftime("%Y%m%d") != source_date:
                raise AnalysisInputContractError(
                    f"{label} quote price_time date does not match source_trade_date {source_date}"
                )
        event_risk = candidate.get("event_risk") or {}
        for source_name in ("holder_reduction", "unlock", "suspension"):
            item = event_risk.get(source_name) or {}
            if item.get("source_status") == "unknown":
                raise AnalysisInputContractError(
                    f"{label} candidates[{index}].event_risk.{source_name} source is unknown"
                )
            _validate_candidate_date(
                item.get("observed_at"),
                f"candidates[{index}].event_risk.{source_name}.observed_at",
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
    # 严格 canonical(与 engine/weekly 的 _is_valid_date 同口径):8 位 ASCII 数字 + strptime 历法校验。
    # 仅正则会让 20260600 / 20260231 / 20260631 等非法历法日通过共享契约的 schema/PIT 字典序比较(跨消费者防线)。
    if isinstance(value, str) and _DATE8_RE.match(value):
        try:
            datetime.strptime(value, "%Y%m%d")
        except ValueError:
            pass
        else:
            return value
    raise AnalysisInputContractError(
        f"{label} PIT validation failed: {field_path} must be a canonical YYYYMMDD calendar date, got {value!r}"
    )
