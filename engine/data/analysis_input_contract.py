from __future__ import annotations

import json
import hashlib
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from engine.a_short_industry_theme import (
    configuration_fingerprint,
    finite_industry_heat_score,
    industry_trend_from_score,
    industry_trend_policy,
)
from engine.a_short_run_revision import validate_run_revision_id
from engine.a_short_legacy_llm_tasks import TASK_TYPES
from engine.egs_industry_heat import load_governance


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


def is_official_a_short_analysis_input_path(path: str | Path) -> bool:
    """Return true for a date-root or revision-root EGS publication input."""
    try:
        relative = Path(path).resolve().relative_to((ROOT / "result" / "a_short").resolve())
    except ValueError:
        return False
    if len(relative.parts) == 2:
        return relative.parts[1] == "analysis_input.json" and bool(_DATE8_RE.fullmatch(relative.parts[0]))
    return (
        len(relative.parts) == 4
        and bool(_DATE8_RE.fullmatch(relative.parts[0]))
        and relative.parts[1] == "revisions"
        and bool(re.fullmatch(r"[0-9a-f]{32}", relative.parts[2]))
        and relative.parts[3] == "analysis_input.json"
    )


def validate_analysis_input_file(
    path: str | Path, label: str | None = None, *, official_input: bool | None = None
) -> dict[str, Any]:
    input_path = Path(path)
    with input_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    validate_analysis_input_contract(
        payload,
        label=label or f"analysis_input {input_path}",
        official_input=(
            is_official_a_short_analysis_input_path(input_path)
            if official_input is None else official_input
        ),
    )
    return payload


def validate_analysis_input_contract(
    payload: Any,
    schema_path: str | Path = ANALYSIS_INPUT_SCHEMA_PATH,
    label: str = "analysis_input",
    *,
    official_input: bool = False,
) -> None:
    validate_json_schema(payload, schema_path=schema_path, label=label)
    _validate_pit_invariants(payload, label=label, official_input=official_input)


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


def _validate_pit_invariants(payload: dict[str, Any], label: str, official_input: bool = False) -> None:
    trade_date = _parse_date8(payload.get("trade_date"), "trade_date", label)

    source = payload.get("source") or {}
    decision_as_of = payload.get("decision_as_of")
    if decision_as_of is not None and _parse_date8(decision_as_of, "decision_as_of", label) != trade_date:
        raise AnalysisInputContractError(f"{label} decision_as_of must equal trade_date")
    clocks = source.get("clocks") or {}
    if clocks:
        clock_decision = _parse_date8(clocks.get("decision_as_of"), "source.clocks.decision_as_of", label)
        clock_run = _parse_date8(clocks.get("run_date"), "source.clocks.run_date", label)
        clock_price = _parse_date8(clocks.get("price_data_through"), "source.clocks.price_data_through", label)
        if clock_decision != trade_date or clock_price > trade_date:
            raise AnalysisInputContractError(f"{label} source clock binding is inconsistent")
        if payload.get("run_date") not in (None, clock_run) or payload.get("price_data_through") not in (None, clock_price):
            raise AnalysisInputContractError(f"{label} top-level clocks do not match source.clocks")
    declared_run_date = payload.get("run_date")
    if declared_run_date in (None, "") and clocks:
        declared_run_date = clocks.get("run_date")
    run_date = (
        _parse_date8(declared_run_date, "run_date", label)
        if declared_run_date not in (None, "") else None
    )
    declared_price_data_through = (
        payload.get("price_data_through") or clocks.get("price_data_through")
    )
    if official_input and not declared_price_data_through:
        raise AnalysisInputContractError(
            f"{label} official input must declare price_data_through"
        )
    price_data_through = _parse_date8(
        declared_price_data_through or payload.get("trade_date"),
        "price_data_through", label,
    )
    if price_data_through > trade_date:
        raise AnalysisInputContractError(f"{label} price_data_through is after trade_date")
    margin_context = (payload.get("market_context") or {}).get("margin_overheat")
    predicate_facts = (
        margin_context.get("predicate_facts")
        if isinstance(margin_context, dict) else None
    )
    if predicate_facts is not None:
        # The optional comparison predicate is still a source-bound carrier.
        # Validate its existing dedicated contract here, before any weekly
        # consumer can mistake a decision-date label for the price clock.
        from engine.a_short_margin_overheat_cash_control import validate_predicate_facts

        try:
            validate_predicate_facts(predicate_facts)
        except Exception as exc:
            raise AnalysisInputContractError(
                f"{label} margin_overheat predicate_facts are invalid"
            ) from exc
        if predicate_facts.get("source_as_of") != price_data_through:
            raise AnalysisInputContractError(
                f"{label} margin_overheat predicate source_as_of must equal price_data_through"
            )
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
        if run_identity.get("run_revision_id") not in (None, ""):
            try:
                validate_run_revision_id(run_identity["run_revision_id"])
            except ValueError as exc:
                raise AnalysisInputContractError(
                    f"{label} run_revision_id is invalid"
                ) from exc
    l3_mode = source.get("l3_mode")
    l3_snapshot_date = source.get("l3_snapshot_date")
    l3_provider = source.get("l3_provider")
    l3_coverage = source.get("l3_coverage")
    schema_version = payload.get("schema_version")
    if schema_version in {"1.3.0", "1.4.0", "1.5.0"}:
        margin = (payload.get("market_context") or {}).get("margin_coverage")
        if not isinstance(margin, dict):
            raise AnalysisInputContractError(
                f"{label} margin coverage is required for schema_version {schema_version}"
            )
        reference_date = _parse_date8(margin.get("reference_date"), "margin_coverage.reference_date", label)
        if reference_date != price_data_through:
            raise AnalysisInputContractError(
                f"{label} margin coverage reference_date must equal price_data_through"
            )
        if margin.get("status") == "complete":
            effective_ref_date = _parse_date8(
                margin.get("effective_ref_date"), "margin_coverage.effective_ref_date", label
            )
            if effective_ref_date > reference_date:
                raise AnalysisInputContractError(
                    f"{label} margin coverage effective_ref_date is after reference_date"
                )
            try:
                universe_size = int(margin.get("universe_size"))
                row_count = int(margin.get("row_count"))
            except (TypeError, ValueError) as exc:
                raise AnalysisInputContractError(
                    f"{label} complete margin coverage has invalid counts"
                ) from exc
            if (margin.get("coverage_complete") is not True
                    or universe_size < 1000 or row_count < universe_size):
                raise AnalysisInputContractError(
                    f"{label} complete margin coverage is below the universe floor"
                )
        if schema_version in {"1.4.0", "1.5.0"}:
            moneyflow = (payload.get("market_context") or {}).get("moneyflow_coverage")
            if not isinstance(moneyflow, dict):
                raise AnalysisInputContractError(
                    f"{label} moneyflow coverage is required for schema_version {schema_version}"
                )
            moneyflow_reference = moneyflow.get("reference_date")
            if moneyflow_reference is not None:
                parsed_moneyflow_reference = _parse_date8(
                    moneyflow_reference, "moneyflow_coverage.reference_date", label
                )
                if parsed_moneyflow_reference != price_data_through:
                    raise AnalysisInputContractError(
                        f"{label} moneyflow coverage reference_date must equal price_data_through"
                    )
            moneyflow_status = moneyflow.get("status")
            requested_dates = moneyflow.get("requested_trade_dates")
            observed_dates = moneyflow.get("observed_trade_dates")
            if not isinstance(requested_dates, list) or not isinstance(observed_dates, list):
                raise AnalysisInputContractError(
                    f"{label} moneyflow coverage dates must be lists"
                )
            for date_index, date_value in enumerate(requested_dates):
                _parse_date8(
                    date_value,
                    f"moneyflow_coverage.requested_trade_dates[{date_index}]",
                    label,
                )
            for date_index, date_value in enumerate(observed_dates):
                _parse_date8(
                    date_value,
                    f"moneyflow_coverage.observed_trade_dates[{date_index}]",
                    label,
                )
            if len(set(requested_dates)) != len(requested_dates) or len(set(observed_dates)) != len(observed_dates):
                raise AnalysisInputContractError(
                    f"{label} moneyflow coverage dates contain duplicates"
                )
            if not set(observed_dates).issubset(set(requested_dates)):
                raise AnalysisInputContractError(
                    f"{label} moneyflow observed dates must be within requested dates"
                )
            try:
                target_total = int(moneyflow.get("target_universe_size"))
                target_complete = int(moneyflow.get("target_complete_count"))
                row_count = int(moneyflow.get("row_count"))
                universe_size = int(moneyflow.get("universe_size"))
            except (TypeError, ValueError) as exc:
                raise AnalysisInputContractError(
                    f"{label} moneyflow coverage has invalid counts"
                ) from exc
            if (
                target_total < 0
                or target_complete < 0
                or target_complete > target_total
                or row_count < 0
                or universe_size < 0
            ):
                raise AnalysisInputContractError(
                    f"{label} moneyflow coverage counts are inconsistent"
                )
            if moneyflow_status == "complete":
                if (
                    moneyflow_reference is None
                    or moneyflow.get("coverage_complete") is not True
                    or len(requested_dates) != 5
                    or len(observed_dates) != 5
                    or observed_dates != requested_dates
                    or row_count <= 0
                    or target_complete != target_total
                ):
                    raise AnalysisInputContractError(
                        f"{label} complete moneyflow coverage is inconsistent"
                    )
            elif moneyflow.get("coverage_complete"):
                raise AnalysisInputContractError(
                    f"{label} incomplete moneyflow coverage cannot claim complete"
                )
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
        if run_date is not None and snapshot_date > run_date:
            raise AnalysisInputContractError(
                f"{label} PIT validation failed: source.l3_snapshot_date "
                f"{l3_snapshot_date} is after run_date {run_date}"
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

    try:
        current_l3_contract = tuple(
            int(part) for part in str(schema_version).split(".")
        ) >= (1, 2, 0)
    except (TypeError, ValueError):
        current_l3_contract = False
    if current_l3_contract:
        if l3_mode == "today":
            if not l3_snapshot_date:
                raise AnalysisInputContractError(
                    f"{label} current live L3 requires source.l3_snapshot_date"
                )
            snapshot_date = _parse_date8(l3_snapshot_date, "source.l3_snapshot_date", label)
            if snapshot_date > trade_date:
                raise AnalysisInputContractError(
                    f"{label} current live L3 snapshot date {l3_snapshot_date} "
                    f"is after trade_date {trade_date}"
                )
            if run_date is not None and snapshot_date > run_date:
                raise AnalysisInputContractError(
                    f"{label} current live L3 snapshot date {l3_snapshot_date} "
                    f"is after run_date {run_date}"
                )
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
        if official_input and source_date is None:
            raise AnalysisInputContractError(
                f"{label} official input requires candidates[{index}].quote.source_trade_date"
            )
        if source_date is not None:
            parsed_source_date = _parse_date8(
                source_date, f"candidates[{index}].quote.source_trade_date", label
            )
            if official_input and parsed_source_date != price_data_through:
                raise AnalysisInputContractError(
                    f"{label} official input requires candidates[{index}].quote.source_trade_date "
                    f"{parsed_source_date} == price_data_through {price_data_through}"
                )
            if parsed_source_date > price_data_through:
                raise AnalysisInputContractError(
                    f"{label} PIT validation failed: candidates[{index}].quote.source_trade_date "
                    f"{parsed_source_date} is after price_data_through {price_data_through}"
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
        industry = candidate.get("industry") or {}
        industry_signal = industry.get("industry_trend_signal") or {}
        if industry_signal:
            _validate_candidate_date(
                industry_signal.get("source_as_of"),
                f"candidates[{index}].industry.industry_trend_signal.source_as_of",
                price_data_through,
                label,
            )
            if (industry_signal.get("classification") != industry_signal.get("industry_trend")
                    or industry.get("industry_trend") != industry_signal.get("classification")):
                raise AnalysisInputContractError(
                    f"{label} candidates[{index}] deterministic industry_trend_signal does not match industry_trend"
                )
            if (industry_signal.get("validation_status") == "valid"
                    and industry_signal.get("unavailable_reason") is not None):
                raise AnalysisInputContractError(
                    f"{label} candidates[{index}] valid industry_trend_signal cannot carry unavailable_reason"
                )
            if industry_signal.get("validation_status") == "valid":
                policy = industry_trend_policy(load_governance())
                thresholds = industry_signal.get("thresholds")
                if (
                    industry_signal.get("classifier_version") != policy["classifier_version"]
                    or industry_signal.get("source_id") != policy["source_id"]
                    or not isinstance(thresholds, dict)
                    or thresholds.get("headwind_max") != policy["headwind_max"]
                    or thresholds.get("tailwind_min") != policy["tailwind_min"]
                    or industry_signal.get("risk_filter_v1_prior") is not True
                    or industry_signal.get("forward_calibration_required") is not True
                    or industry_signal.get("positive_effect_enabled") is not False
                    or industry_signal.get("configuration_fingerprint")
                    != configuration_fingerprint(policy)
                ):
                    raise AnalysisInputContractError(
                        f"{label} candidates[{index}] industry_trend_signal policy or fingerprint mismatch"
                    )
                score = finite_industry_heat_score(industry_signal.get("industry_heat_score"))
                expected_classification = industry_trend_from_score(score, policy)
                if expected_classification is None:
                    raise AnalysisInputContractError(
                        f"{label} candidates[{index}] valid industry_trend_signal has invalid score"
                    )
                source_score = finite_industry_heat_score(
                    (candidate.get("scores") or {}).get("industry_heat_score")
                )
                if source_score is None or abs(score - source_score) > 1e-9:
                    raise AnalysisInputContractError(
                        f"{label} candidates[{index}] industry_trend_signal source score mismatch"
                    )
                if industry_signal.get("classification") != expected_classification:
                    raise AnalysisInputContractError(
                        f"{label} candidates[{index}] industry_trend_signal score/classification mismatch"
                    )
            if (industry_signal.get("validation_status") == "unavailable"
                    and industry_signal.get("classification") != "unknown"):
                raise AnalysisInputContractError(
                    f"{label} candidates[{index}] unavailable industry_trend_signal must classify as unknown"
                )
        _validate_legacy_task_configs(candidate, index, trade_date, label)
        taxonomy = ((candidate.get("catalyst") or {}).get("theme_taxonomy") or {})
        if taxonomy:
            if taxonomy.get("production_effect_enabled") is not False or taxonomy.get("automatic_promotion") is not False:
                raise AnalysisInputContractError(
                    f"{label} candidates[{index}] theme taxonomy must remain comparison-only with no automatic promotion"
                )
            _validate_candidate_date(
                taxonomy.get("source_as_of"),
                f"candidates[{index}].catalyst.theme_taxonomy.source_as_of",
                trade_date,
                label,
            )
            provenance = taxonomy.get("l3_provenance") or {}
            coverage = l3_coverage if isinstance(l3_coverage, dict) else {}
            expected_snapshot_date = l3_snapshot_date if l3_snapshot_date not in (None, "") else None
            expected_digest = coverage.get("catalog_digest")
            expected_digest = expected_digest if isinstance(expected_digest, str) else None
            expected_complete = coverage.get("complete") if isinstance(coverage.get("complete"), bool) else None
            expected_universe = coverage.get("scoring_universe") if isinstance(coverage.get("scoring_universe"), str) else None
            if (l3_provider == "hithink_finance" and expected_snapshot_date
                    and expected_digest and expected_complete is True
                    and expected_universe == "a_share_main_board"):
                expected_status = "verified_complete"
                expected_membership_source = "hithink_complete_concept_members"
            elif l3_provider == "legacy_tushare_snapshot" and expected_snapshot_date:
                expected_status = "legacy_snapshot"
                expected_membership_source = "legacy_snapshot_concept_members"
            else:
                expected_status = "unavailable"
                expected_membership_source = "unavailable"
            expected_provenance = {
                "provider": l3_provider if l3_provider not in (None, "") else None,
                "snapshot_date": expected_snapshot_date,
                "coverage_digest": expected_digest,
                "coverage_complete": expected_complete,
                "scoring_universe": expected_universe,
                "raw_membership_source": expected_membership_source,
                "validation_status": expected_status,
            }
            if provenance != expected_provenance:
                raise AnalysisInputContractError(
                    f"{label} candidates[{index}] theme taxonomy L3 provenance does not match source receipt"
                )
            if expected_status == "unavailable" and (
                    taxonomy.get("comparison_status") != "unknown_or_unavailable"
                    or not taxonomy.get("unavailable_reason")
            ):
                raise AnalysisInputContractError(
                    f"{label} candidates[{index}] unavailable theme taxonomy must remain unavailable"
                )
            if expected_status in {"verified_complete", "legacy_snapshot"}:
                taxonomy_source_date = _parse_date8(
                    taxonomy.get("source_as_of"),
                    f"candidates[{index}].catalyst.theme_taxonomy.source_as_of",
                    label,
                )
                if taxonomy_source_date != expected_snapshot_date:
                    raise AnalysisInputContractError(
                        f"{label} candidates[{index}] theme taxonomy source_as_of must equal L3 snapshot_date"
                    )
                if run_date is not None and taxonomy_source_date > run_date:
                    raise AnalysisInputContractError(
                        f"{label} candidates[{index}] theme taxonomy source_as_of is after run_date"
                    )
            expected_source_id = (
                f"{l3_provider}.concept_graph"
                if expected_status in {"verified_complete", "legacy_snapshot"}
                else None
            )
            for raw_index, raw_concept in enumerate(taxonomy.get("raw_concepts") or []):
                if not isinstance(raw_concept, dict):
                    raise AnalysisInputContractError(
                        f"{label} candidates[{index}] raw theme concept {raw_index} is invalid"
                    )
                if (
                    raw_concept.get("source_id") != expected_source_id
                    or raw_concept.get("source_as_of") != expected_snapshot_date
                    or raw_concept.get("source_snapshot_date") != expected_snapshot_date
                    or raw_concept.get("coverage_digest") != expected_digest
                    or raw_concept.get("membership_source") != expected_membership_source
                ):
                    raise AnalysisInputContractError(
                        f"{label} candidates[{index}] raw theme concept {raw_index} does not match L3 receipt"
                    )


def _validate_legacy_task_configs(candidate: dict[str, Any], index: int,
                                  trade_date: str, label: str) -> None:
    """Enforce the modern six-task config without rejecting historical files."""
    tasks = candidate.get("llm_tasks") or []
    modern = any(isinstance(task, dict) and "task_type" in task for task in tasks)
    if not modern:
        return
    if len(tasks) != len(TASK_TYPES):
        raise AnalysisInputContractError(
            f"{label} candidates[{index}].llm_tasks must contain exactly six legacy tasks"
        )
    ts_code = str(candidate.get("ts_code") or "")
    seen: set[str] = set()
    task_types: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            raise AnalysisInputContractError(f"{label} candidates[{index}].llm_tasks has a non-object item")
        task_type = str(task.get("task_type") or "")
        task_id = str(task.get("task_id") or "")
        if task_type not in TASK_TYPES or task.get("prompt") != task_type:
            raise AnalysisInputContractError(
                f"{label} candidates[{index}].llm_tasks has an invalid task_type/prompt pairing"
            )
        if task_id != f"{ts_code}_{task_type}" or task_id in seen:
            raise AnalysisInputContractError(
                f"{label} candidates[{index}].llm_tasks task_id is not unique and stable"
            )
        inputs = task.get("inputs") or {}
        if inputs.get("ts_code") != ts_code or inputs.get("as_of") != trade_date:
            raise AnalysisInputContractError(
                f"{label} candidates[{index}].llm_tasks task inputs are not bound to candidate/as_of"
            )
        seen.add(task_id)
        task_types.add(task_type)
    if task_types != set(TASK_TYPES):
        raise AnalysisInputContractError(
            f"{label} candidates[{index}].llm_tasks does not contain the required six task types"
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
