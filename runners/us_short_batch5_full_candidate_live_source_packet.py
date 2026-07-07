from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
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
from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance  # noqa: E402
from engine.us_short_pass2_funnel import Pass2FunnelError, select_pass2_targets  # noqa: E402
from engine.us_short_fmp_analyst_grades import FmpGradesError, resolve_analyst_grade_actions  # noqa: E402
from engine.us_short_massive_news import MassiveNewsError, resolve_news_events  # noqa: E402
from engine.us_short_sec_offering_audit import (  # noqa: E402
    OfferingAuditError,
    build_offering_audit_from_sec_submissions,
)
from runners import us_egs_sample_validation as sample_validation  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402
from runners.us_short_batch5_data_context_source_packet import (  # noqa: E402
    SourcePacketError,
    run_packet as run_local_source_packet,
    run_preflight as run_local_source_packet_preflight,
)


AUTHORIZATION_REF = "user_chat_20260706_us_short_full_candidate_live_source_packet"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_candidate_live_source_packet_summary.schema.json"
PREFLIGHT_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_full_candidate_pass2_preflight_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_full_candidate_live_source_packet_summary_20260706.json"
PREFLIGHT_SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_full_candidate_pass2_preflight_summary_20260706.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_full_candidate_live_source_packet_20260706")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
SOURCE_ARTIFACT_PREFIX = STATE_US_SHORT_DIR / "us_short_batch5_full_candidate_live_source_packet_20260706"
DEFAULT_OUTPUT_DATA_CONTEXT_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_candidate_live_source_packet_20260706_data_context.json"
)
DEFAULT_CONTEXT_COMPONENTS_OUTPUT_PATH = (
    STATE_US_SHORT_DIR / "us_short_batch5_full_candidate_live_source_packet_20260706_context_components.json"
)
MASSIVE_NEWS_URL = "https://api.massive.com/v2/reference/news?ticker={ticker}&limit=10&apiKey={key}"
FMP_FREE_DAILY_GRADE_CALL_CAP = 250   # mirror the preflight; the funnel target + within-cap invariant is RE-DERIVED here at the live boundary, not trusted from the preflight
# Mirror the preflight `_forecast_calls`: each Pass2 target costs 5 endpoint calls (3 source-packet: grades +
# submissions + reference-news; 2 corporate-action: splits + dividends) plus 1 shared SEC ticker->CIK mapping.
# The live-spend budget is RE-ANCHORED to the runner-RE-DERIVED target count (not the preflight-attested
# forecast/momentum_top_k), so a forged preflight cannot widen K/target_count without the operator independently
# authorizing the matching budget. Cross-checked against the preflight formula by test.
_SEC_TICKER_MAPPING_CALLS = 1
_PASS2_ENDPOINT_CALLS_PER_TARGET = 5


class FullCandidateLiveSourcePacketError(ValueError):
    """The full-candidate live Pass2 source packet cannot be fetched or assembled safely."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FullCandidateLiveSourcePacketError(f"failed to read JSON from {path}: {exc}") from exc


def _write_json_atomic(payload: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    tmp.replace(path)


def _repo_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _display_path(path: Path) -> str:
    try:
        return _repo_rel(path)
    except ValueError:
        return str(path)


def _resolve_repo_path(path: Path | str, *, field: str) -> Path:
    raw = Path(path)
    resolved = raw.resolve() if raw.is_absolute() else (ROOT / raw).resolve()
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError(f"{field} must stay under the repository root") from exc
    return resolved


def _git_ignored(path: Path) -> bool:
    rel = _repo_rel(path)
    result = subprocess.run(
        ["git", "-c", "core.excludesFile=", "check-ignore", "-q", "--", rel],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _existing_file(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    if not resolved.exists() or not resolved.is_file():
        raise FullCandidateLiveSourcePacketError(f"{field} must be an existing file: {_display_path(resolved)}")
    return resolved


def _existing_state_json(path: Path | str, *, field: str) -> Path:
    resolved = _existing_file(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise FullCandidateLiveSourcePacketError(f"{field} must be a .json file")
    if not _git_ignored(resolved):
        raise FullCandidateLiveSourcePacketError(f"{field} must be gitignored")
    return resolved


def _validate_state_json_path(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise FullCandidateLiveSourcePacketError(f"{field} must be a .json path")
    if not _git_ignored(resolved):
        raise FullCandidateLiveSourcePacketError(f"{field} must be gitignored")
    return resolved


def _validate_source_artifact_prefix(prefix: Path | str) -> Path:
    resolved = _resolve_repo_path(prefix, field="source_artifact_prefix")
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError("source_artifact_prefix must stay under state/us_short/") from exc
    return resolved


def _source_paths(prefix: Path) -> dict[str, Path]:
    return {
        "candidate_subset": prefix.with_name(prefix.name + "_candidate_subset.json"),
        "offering_audit_source": prefix.with_name(prefix.name + "_offering_audit_source.json"),
        "analyst_grade_actions": prefix.with_name(prefix.name + "_analyst_grade_actions.json"),
        "massive_news_events": prefix.with_name(prefix.name + "_massive_news_events.json"),
        "corporate_action_capture": prefix.with_name(prefix.name + "_corporate_action_capture.json"),
        "momentum_projection": prefix.with_name(prefix.name + "_momentum_projection.json"),
        "theme_projection": prefix.with_name(prefix.name + "_theme_projection.json"),
        "source_packet": prefix.with_name(prefix.name + "_source_packet.json"),
    }


def _validate_raw_root(raw_root: Path | str) -> Path:
    resolved = _resolve_repo_path(raw_root, field="raw_root")
    approved = (ROOT / RAW_SAMPLE_REL_ROOT).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError(
            "raw_root must stay under provider_samples/us_short_batch5_full_candidate_live_source_packet_20260706/"
        ) from exc
    try:
        sample_validation.validate_raw_root(resolved)
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError(str(exc)) from exc
    return resolved


def _validate_summary_path(summary_path: Path | str) -> Path:
    resolved = _resolve_repo_path(summary_path, field="summary_path")
    if resolved.suffix != ".json":
        raise FullCandidateLiveSourcePacketError("summary_path must be a .json file")
    if resolved == SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / RAW_SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError(
            "summary_path must be the canonical tracked summary or under this runner's provider_samples folder"
        ) from exc
    if not _git_ignored(resolved):
        raise FullCandidateLiveSourcePacketError("non-canonical summary_path must be gitignored")
    return resolved


def _validate_preflight_path(preflight_summary_path: Path | str) -> Path:
    resolved = _existing_file(preflight_summary_path, field="preflight_summary_path")
    if resolved == PREFLIGHT_SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / "provider_samples/us_short_batch5_full_candidate_pass2_preflight_20260706").resolve())
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError(
            "preflight_summary_path must be the canonical tracked summary or under its provider_samples folder"
        ) from exc
    if not _git_ignored(resolved):
        raise FullCandidateLiveSourcePacketError("non-canonical preflight_summary_path must be gitignored")
    return resolved


def _provider_samples_gitignored() -> bool:
    gitignore = ROOT / ".gitignore"
    return gitignore.exists() and "provider_samples/" in gitignore.read_text(encoding="utf-8")


def _date8_to_ymd(value: Any) -> str:
    if not (type(value) is str and len(value) == 8 and value.isascii() and value.isdigit()):
        raise FullCandidateLiveSourcePacketError("expected_decision_date must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise FullCandidateLiveSourcePacketError("expected_decision_date must be a real calendar date") from exc


def _valid_observed_at(value: str) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _validate_json_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise FullCandidateLiveSourcePacketError(f"jsonschema is required for {label} validation") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise FullCandidateLiveSourcePacketError(f"{label} failed schema validation: {joined}")


def _load_ready_preflight(preflight_summary_path: Path, expected_total_call_budget: int) -> dict[str, Any]:
    if type(expected_total_call_budget) is not int or expected_total_call_budget <= 0:
        raise FullCandidateLiveSourcePacketError("expected_total_call_budget must be a positive integer")
    preflight = _read_json(preflight_summary_path)
    _validate_json_schema(preflight, PREFLIGHT_SCHEMA_PATH, label="full-candidate preflight summary")
    status = ((preflight.get("scope") or {}).get("status"))
    gate = preflight.get("execution_gate") or {}
    local = preflight.get("local_input_coverage") or {}
    forecast = ((preflight.get("endpoint_call_forecast") or {}).get("total_calls_for_pass2_target_cut"))
    targets = preflight.get("pass2_target_universe") or {}
    if status != "ready_for_reviewed_live_execution" or gate.get("ready_to_run_full_candidate_live_packet") is not True:
        raise FullCandidateLiveSourcePacketError("preflight summary is not ready for reviewed live execution")
    if local.get("all_required_local_inputs_cover_candidates") is not True:
        raise FullCandidateLiveSourcePacketError("preflight local inputs are not fully covered")
    if targets.get("target_count") <= 0 or targets.get("fmp_grade_calls_within_free_daily_cap") is not True:
        raise FullCandidateLiveSourcePacketError("preflight Pass2 target universe is not free-budget ready")
    if forecast != expected_total_call_budget:
        raise FullCandidateLiveSourcePacketError(
            f"expected call budget must match preflight forecast: {expected_total_call_budget} != {forecast}"
        )
    return preflight


def _candidate_subset_artifact(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
    selected_symbols: list[str],
) -> dict[str, Any]:
    artifact = _read_json(candidate_artifact_path)
    try:
        artifact = universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=expected_decision_date,
            governance=eligibility_governance,
        )
    except Exception as exc:
        raise FullCandidateLiveSourcePacketError(f"candidate artifact failed validation: {exc}") from exc
    rows_by_ticker = {row["ticker"]: row for row in artifact["rows"]}
    eligible = list(artifact["eligible_tickers"])
    eligible_set = set(eligible)
    if type(selected_symbols) is not list or not selected_symbols:
        raise FullCandidateLiveSourcePacketError("selected_symbols must be a non-empty exact list")
    seen: set[str] = set()
    for symbol in selected_symbols:
        if type(symbol) is not str or symbol in seen:
            raise FullCandidateLiveSourcePacketError("selected_symbols must contain unique exact ticker strings")
        if symbol not in eligible_set or symbol not in rows_by_ticker:
            raise FullCandidateLiveSourcePacketError("selected_symbols must stay inside the reviewed eligible candidate set")
        seen.add(symbol)
    rows = [rows_by_ticker[ticker] for ticker in selected_symbols]
    adv_window = artifact["adv_window"]
    subset = universe_fetch.build_candidate_artifact(
        rows=rows,
        decision_date=artifact["decision_date"],
        price_basis_date=artifact["price_basis_date"],
        used_date=artifact["used_date"],
        observed_window_dates=adv_window["observed_window_dates"],
        generated_at=artifact["generated_at"],
        calendar_verification_status=artifact["calendar_verification_status"],
        window_days=adv_window["trading_days"],
        min_days=adv_window["min_days_required"],
    )
    try:
        return universe_fetch.validate_candidate_artifact(
            subset,
            expected_decision_date=expected_decision_date,
            governance=eligibility_governance,
        )
    except Exception as exc:
        raise FullCandidateLiveSourcePacketError(f"candidate subset failed validation: {exc}") from exc


def _assert_endpoint_budget(records: list[sample_validation.FetchRecord], max_total_endpoint_calls: int) -> None:
    try:
        sample_validation.assert_endpoint_budget_available(records, max_total_endpoint_calls)
    except RuntimeError as exc:
        raise FullCandidateLiveSourcePacketError(str(exc)) from exc


def _fmp_stable_url(path_template: str, symbol: str, api_key: str) -> str:
    return sample_validation.fmp_url(path_template, symbol, {}, api_key, endpoint_mode="stable")


def _fetch_live_records(
    *,
    selected_symbols: list[str],
    raw_root: Path,
    client: sample_validation.JsonHttpClient,
    fmp_env: sample_validation.EnvValue,
    sec_env: sample_validation.EnvValue,
    massive_env: sample_validation.EnvValue,
    sec_sleep_seconds: float,
    max_total_endpoint_calls: int,
) -> tuple[list[sample_validation.FetchRecord], dict[str, str]]:
    records: list[sample_validation.FetchRecord] = []
    _assert_endpoint_budget(records, max_total_endpoint_calls)
    mapping = sample_validation.fetch_and_store(
        client,
        url=sample_validation.sec_url("company_tickers_mapping"),
        provider_id="sec_edgar",
        endpoint_family="company_tickers_mapping",
        symbol=None,
        raw_root=raw_root,
        headers={"User-Agent": sec_env.value, "Host": "www.sec.gov"},
    )
    records.append(mapping)
    cik_by_symbol = sample_validation.parse_sec_cik_map(mapping.payload, selected_symbols)

    fmp_headers = {"User-Agent": "StockSystem/0.1 us-short-batch5-full-candidate-live-source-packet"}
    sec_headers = {"User-Agent": sec_env.value, "Host": "data.sec.gov"}
    massive_headers = {"User-Agent": "StockSystem/0.1 us-short-batch5-full-candidate-live-source-packet"}
    for symbol in selected_symbols:
        _assert_endpoint_budget(records, max_total_endpoint_calls)
        records.append(
            sample_validation.fetch_and_store(
                client,
                url=_fmp_stable_url("grades", symbol, fmp_env.value),
                provider_id="financial_modeling_prep",
                endpoint_family="grades",
                symbol=symbol,
                raw_root=raw_root,
                headers=fmp_headers,
            )
        )

        cik10 = cik_by_symbol.get(symbol)
        if cik10:
            _assert_endpoint_budget(records, max_total_endpoint_calls)
            time.sleep(sec_sleep_seconds)
            records.append(
                sample_validation.fetch_and_store(
                    client,
                    url=sample_validation.sec_url("submissions", cik10),
                    provider_id="sec_edgar",
                    endpoint_family="submissions",
                    symbol=symbol,
                    raw_root=raw_root,
                    headers=sec_headers,
                )
            )

        _assert_endpoint_budget(records, max_total_endpoint_calls)
        records.append(
            sample_validation.fetch_and_store(
                client,
                url=MASSIVE_NEWS_URL.format(ticker=symbol, key=massive_env.value),
                provider_id="massive",
                endpoint_family="reference_news",
                symbol=symbol,
                raw_root=raw_root,
                headers=massive_headers,
            )
        )

        _assert_endpoint_budget(records, max_total_endpoint_calls)
        records.append(
            sample_validation.fetch_and_store(
                client,
                url=_fmp_stable_url("splits", symbol, fmp_env.value),
                provider_id="financial_modeling_prep",
                endpoint_family="stock_splits",
                symbol=symbol,
                raw_root=raw_root,
                headers=fmp_headers,
            )
        )

        _assert_endpoint_budget(records, max_total_endpoint_calls)
        records.append(
            sample_validation.fetch_and_store(
                client,
                url=_fmp_stable_url("dividends", symbol, fmp_env.value),
                provider_id="financial_modeling_prep",
                endpoint_family="dividends",
                symbol=symbol,
                raw_root=raw_root,
                headers=fmp_headers,
            )
        )
    return records, cik_by_symbol


def _record_map(records: list[sample_validation.FetchRecord]) -> dict[tuple[str, str, str | None], sample_validation.FetchRecord]:
    return {(record.provider_id, record.endpoint_family, record.symbol): record for record in records}


def _target_scoped_projection(
    *,
    projection_path: Path,
    value_key: str,
    selected_symbols: list[str],
) -> dict[str, Any]:
    raw = _read_json(projection_path)
    if type(raw) is not dict:
        raise FullCandidateLiveSourcePacketError(f"{value_key} projection must be an exact dict")
    values = raw.get(value_key)
    neutral = raw.get("neutral_fill_tickers")
    coverage = raw.get("coverage")
    if type(values) is not dict or type(neutral) is not list or type(coverage) is not dict:
        raise FullCandidateLiveSourcePacketError(f"{value_key} projection has an invalid shape")
    if not all(type(key) is str for key in values) or not all(type(key) is str for key in coverage):
        raise FullCandidateLiveSourcePacketError(f"{value_key} projection keys must be exact strings")
    if not all(type(ticker) is str for ticker in neutral):
        raise FullCandidateLiveSourcePacketError(f"{value_key} neutral_fill_tickers must contain exact strings")
    neutral_set = set(neutral)
    scoped_values: dict[str, Any] = {}
    scoped_neutral: list[str] = []
    scoped_coverage: dict[str, Any] = {}
    seen: set[str] = set()
    for symbol in selected_symbols:
        if symbol in seen:
            raise FullCandidateLiveSourcePacketError("selected_symbols contains a duplicate")
        seen.add(symbol)
        if symbol not in coverage:
            raise FullCandidateLiveSourcePacketError(f"{value_key} coverage is missing a selected target")
        if symbol in values:
            scoped_values[symbol] = values[symbol]
        elif symbol in neutral_set:
            scoped_neutral.append(symbol)
        else:
            raise FullCandidateLiveSourcePacketError(f"{value_key} projection partition misses a selected target")
        scoped_coverage[symbol] = coverage[symbol]
    return {
        value_key: scoped_values,
        "neutral_fill_tickers": scoped_neutral,
        "coverage": scoped_coverage,
        "target_count": len(selected_symbols),
        "scored_count": len(scoped_values),
    }


def _empty_provenance(
    *,
    provider_id: str,
    endpoint_or_filing_type: str,
    source_as_of: str,
    observed_at: str,
    coverage_status: str,
    parser_status: str,
    lineage_id: str,
) -> dict[str, Any]:
    return {
        "provider_id": provider_id,
        "endpoint_or_filing_type": endpoint_or_filing_type,
        "source_as_of": source_as_of,
        "observed_at": observed_at,
        "coverage_status": coverage_status,
        "parser_status": parser_status,
        "lineage_ref": f"{provider_id}:{endpoint_or_filing_type}:{source_as_of}#{lineage_id}",
    }


def _payload_list_status(record: sample_validation.FetchRecord | None) -> tuple[list[Any], str, str]:
    if record is None or not record.ok:
        return [], "missing", "failed"
    if isinstance(record.payload, list):
        return record.payload, "full", "ok"
    return [], "partial", "failed"


def _massive_news_payload_status(record: sample_validation.FetchRecord | None) -> tuple[list[Any], str, str]:
    if record is None or not record.ok:
        return [], "missing", "failed"
    if isinstance(record.payload, dict) and isinstance(record.payload.get("results"), list):
        return record.payload["results"], "full", "ok"
    if isinstance(record.payload, list):
        return record.payload, "full", "ok"
    return [], "partial", "failed"


def _resolved_source_artifacts(
    *,
    selected_symbols: list[str],
    source_as_of: str,
    observed_at: str,
    records: list[sample_validation.FetchRecord],
) -> dict[str, Any]:
    by_key = _record_map(records)
    submissions_by_ticker: dict[str, Any] = {}
    missing_sec: list[str] = []
    for symbol in selected_symbols:
        rec = by_key.get(("sec_edgar", "submissions", symbol))
        if rec is not None and rec.ok and isinstance(rec.payload, dict):
            submissions_by_ticker[symbol] = rec.payload
        else:
            missing_sec.append(symbol)
    try:
        offering_source = build_offering_audit_from_sec_submissions(
            as_of=source_as_of,
            observed_at=observed_at,
            submissions_by_ticker=submissions_by_ticker,
        )
    except OfferingAuditError as exc:
        raise FullCandidateLiveSourcePacketError(f"SEC offering source rejected: {exc}") from exc
    for symbol in missing_sec:
        offering_source["excluded"][symbol] = {"active_offering": "coverage=missing/parser=failed"}

    grades_by_ticker: dict[str, Any] = {}
    news_by_ticker: dict[str, Any] = {}
    for symbol in selected_symbols:
        grade_records, grade_coverage, grade_parser = _payload_list_status(
            by_key.get(("financial_modeling_prep", "grades", symbol))
        )
        grades_by_ticker[symbol] = {
            "records": grade_records,
            "provenance": _empty_provenance(
                provider_id="fmp",
                endpoint_or_filing_type="grades",
                source_as_of=source_as_of,
                observed_at=observed_at,
                coverage_status=grade_coverage,
                parser_status=grade_parser,
                lineage_id=f"{symbol.lower()}grades",
            ),
        }

        news_records, news_coverage, news_parser = _massive_news_payload_status(
            by_key.get(("massive", "reference_news", symbol))
        )
        news_by_ticker[symbol] = {
            "records": news_records,
            "provenance": _empty_provenance(
                provider_id="massive",
                endpoint_or_filing_type="reference_news",
                source_as_of=source_as_of,
                observed_at=observed_at,
                coverage_status=news_coverage,
                parser_status=news_parser,
                lineage_id=f"{symbol.lower()}news",
            ),
        }

    try:
        analyst_grade_actions = resolve_analyst_grade_actions(
            as_of=source_as_of,
            grades_by_ticker=grades_by_ticker,
        )
        massive_news_events = resolve_news_events(
            as_of=source_as_of,
            news_by_ticker=news_by_ticker,
        )
    except (FmpGradesError, MassiveNewsError) as exc:
        raise FullCandidateLiveSourcePacketError(f"Pass2 source resolver rejected live payloads: {exc}") from exc
    return {
        "offering_audit_source": offering_source,
        "analyst_grade_actions": analyst_grade_actions,
        "massive_news_events": massive_news_events,
    }


def _payload_shape_from_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, list):
        return {"kind": "list", "row_count": len(payload)}
    if isinstance(payload, dict):
        results = payload.get("results")
        if isinstance(results, list):
            return {"kind": "object_results", "row_count": len(results)}
        recent = ((payload.get("filings") or {}).get("recent") or {})
        if isinstance(recent, dict) and isinstance(recent.get("form"), list):
            return {"kind": "sec_submissions", "row_count": len(recent["form"])}
        return {"kind": "object", "row_count": None}
    if payload is None:
        return {"kind": "null", "row_count": None}
    return {"kind": "scalar", "row_count": None}


def _payload_shape(record: sample_validation.FetchRecord) -> dict[str, Any]:
    return _payload_shape_from_payload(record.payload)


def _summarize_endpoint(record: sample_validation.FetchRecord) -> dict[str, Any]:
    return {
        "provider_id": record.provider_id,
        "endpoint_family": record.endpoint_family,
        "symbol": record.symbol,
        "status": "success" if record.ok else "error",
        "http_status": record.http_status,
        "error_type": record.error_type,
        "raw_sample_ref": record.raw_sample_ref,
        "raw_sample_ref_gitignored": record.raw_sample_ref.startswith(str(RAW_SAMPLE_REL_ROOT).replace("\\", "/")),
        "payload_shape": _payload_shape(record),
    }


def _event_count(record: sample_validation.FetchRecord | None) -> int:
    if record is None or not record.ok:
        return 0
    shape = _payload_shape(record)
    return int(shape["row_count"] or 0)


def _build_corporate_action_capture(
    *,
    generated_at: str,
    expected_decision_date: str,
    source_as_of: str,
    observed_at: str,
    selected_symbols: list[str],
    records: list[sample_validation.FetchRecord],
) -> dict[str, Any]:
    by_key = _record_map(records)
    by_ticker: dict[str, Any] = {}
    split_calls = 0
    dividend_calls = 0
    split_events = 0
    dividend_events = 0
    for symbol in selected_symbols:
        split_rec = by_key.get(("financial_modeling_prep", "stock_splits", symbol))
        dividend_rec = by_key.get(("financial_modeling_prep", "dividends", symbol))
        split_count = _event_count(split_rec)
        dividend_count = _event_count(dividend_rec)
        split_calls += 1 if split_rec is not None else 0
        dividend_calls += 1 if dividend_rec is not None else 0
        split_events += split_count
        dividend_events += dividend_count
        by_ticker[symbol] = {
            "split_endpoint": _summarize_endpoint(split_rec) if split_rec is not None else None,
            "dividend_endpoint": _summarize_endpoint(dividend_rec) if dividend_rec is not None else None,
            "split_event_count": split_count,
            "dividend_event_count": dividend_count,
        }
    return {
        "schema_name": "us_short_batch5_corporate_action_live_capture",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "decision_clock": {
            "expected_decision_date": expected_decision_date,
            "source_as_of": source_as_of,
            "observed_at": observed_at,
        },
        "scope": {
            "provider_calls_performed": True,
            "raw_payload_storage_performed": True,
            "corporate_action_reconciliation_performed": False,
            "return_calculation_performed": False,
            "paper_gate_confirmation_claimed": False,
            "ship_gate_or_production_authorized": False,
        },
        "aggregate_counts": {
            "ticker_count": len(selected_symbols),
            "split_endpoint_call_count": split_calls,
            "dividend_endpoint_call_count": dividend_calls,
            "split_event_count": split_events,
            "dividend_event_count": dividend_events,
        },
        "by_ticker": by_ticker,
        "limitations": [
            "This artifact captures split/dividend endpoint response shapes and raw refs only.",
            "It does not reconcile corporate actions to prices, calculate returns, or confirm paper-performance evaluability.",
        ],
    }


def _build_local_source_packet(
    *,
    generated_at: str,
    expected_decision_date: str,
    theme_opportunity_state: str,
    paths: dict[str, Path],
    momentum_projection_path: Path,
    theme_projection_path: Path,
    output_data_context_path: Path,
    context_components_output_path: Path | None,
) -> dict[str, Any]:
    packet_paths: dict[str, Any] = {
        "candidate_artifact_path": _repo_rel(paths["candidate_subset"]),
        "eligibility_governance_path": "presets/us_short_eligibility_governance_20260624.json",
        "momentum_projection_path": _repo_rel(momentum_projection_path),
        "theme_projection_path": _repo_rel(theme_projection_path),
        "offering_audit_source_path": _repo_rel(paths["offering_audit_source"]),
        "analyst_grade_actions_path": _repo_rel(paths["analyst_grade_actions"]),
        "massive_news_events_path": _repo_rel(paths["massive_news_events"]),
        "catalyst_governance_path": "presets/us_short_catalyst_governance_20260630.json",
        "output_data_context_path": _repo_rel(output_data_context_path),
    }
    if context_components_output_path is not None:
        packet_paths["output_context_components_path"] = _repo_rel(context_components_output_path)
    return {
        "schema_name": "us_short_batch5_data_context_source_packet",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "packet_status": "resolved_pass2_source_packet_ready_for_local_assembly",
            "network_access_performed": False,
            "provider_calls_performed": False,
            "raw_payload_capture_performed": False,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "expected_decision_date": expected_decision_date,
            "theme_opportunity_state": theme_opportunity_state,
        },
        "paths": packet_paths,
        "optional_inputs": {
            "holdings": [],
            "catalyst_recall_feed": None,
        },
        "preflight_gates": {
            "local_files_only": True,
            "source_artifacts_must_exist": True,
            "output_must_be_gitignored": True,
            "no_provider_fetch": True,
            "no_datahub_or_production": True,
        },
        "prohibited_claims": {
            "provider_selection_complete": False,
            "live_normalized_evidence": False,
            "ship_gate_evidence": False,
            "production_ready": False,
            "datahub_consumed": False,
        },
    }


def _endpoint_count(records: list[sample_validation.FetchRecord], provider: str, family: str) -> int:
    return sum(1 for record in records if record.provider_id == provider and record.endpoint_family == family)


def _build_summary(
    *,
    generated_at: str,
    expected_decision_date: str,
    source_as_of: str,
    observed_at: str,
    env_summary: dict[str, Any],
    preflight_summary_path: Path,
    expected_total_call_budget: int,
    preflight_total_call_forecast: int,
    candidate_artifact_path: Path,
    candidate_artifact: dict[str, Any],
    pass2_target_universe: dict[str, Any],
    endpoint_records: list[sample_validation.FetchRecord],
    cik_by_symbol: dict[str, str],
    raw_root: Path,
    summary_path: Path,
    source_paths: dict[str, Path],
    source_packet_preflight: dict[str, Any] | None,
    source_packet_run: dict[str, Any] | None,
    run_data_context: bool,
    context_components_output_path: Path | None,
) -> dict[str, Any]:
    endpoint_errors = sum(1 for record in endpoint_records if not record.ok)
    eligible = list(candidate_artifact["eligible_tickers"])
    return {
        "schema_name": "us_short_batch5_full_candidate_live_source_packet_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_full_candidate_live_source_packet_summary.schema.json",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "full_candidate_live_pass2_resolved_source_packet",
            "status": (
                "source_packet_built_and_data_context_written"
                if source_packet_run is not None
                else "source_packet_built_preflight_only"
            ),
            "network_access_performed": True,
            "provider_calls_performed": True,
            "raw_payload_storage_performed": True,
            "resolved_source_artifacts_written": True,
            "corporate_action_capture_written": True,
            "source_packet_written": True,
            "data_context_written": source_packet_run is not None,
            "context_components_written": (
                source_packet_run is not None
                and source_packet_run["scope"]["context_components_written"] is True
            ),
            "corporate_action_reconciliation_performed": False,
            "return_calculation_performed": False,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "full_market_call_performed": False,
            "yfinance_consumption_performed": False,
            "broker_or_order_execution_performed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False,
            "a_share_crossing_performed": False,
        },
        "decision_clock": {
            "expected_decision_date": expected_decision_date,
            "source_as_of": source_as_of,
            "observed_at": observed_at,
        },
        "environment": env_summary,
        "preflight_gate": {
            "preflight_summary_path": _repo_rel(preflight_summary_path),
            "preflight_status": "ready_for_reviewed_live_execution",
            "local_inputs_ready": True,
            "expected_total_call_budget": expected_total_call_budget,
            "preflight_total_call_forecast": preflight_total_call_forecast,
            "call_budget_matches_preflight": expected_total_call_budget == preflight_total_call_forecast,
        },
        "candidate_universe": {
            "candidate_artifact_path": _repo_rel(candidate_artifact_path),
            "candidate_artifact_path_gitignored": _git_ignored(candidate_artifact_path),
            "row_count": len(candidate_artifact["rows"]),
            "eligible_count": len(eligible),
            "eligible_symbol_sample": eligible[:10],
            "symbol_scope": "pass2_target_universe",
            "source_full_candidate_eligible_count": pass2_target_universe["eligible_count"],
            "full_market_sample": False,
        },
        "pass2_target_universe": {
            "selection_mode": pass2_target_universe["selection_mode"],
            "momentum_top_k": pass2_target_universe["momentum_top_k"],
            "target_count": pass2_target_universe["target_count"],
            "target_symbols": list(pass2_target_universe["target_symbols"]),
            "target_symbol_sample": list(pass2_target_universe["target_symbol_sample"]),
            "fmp_grade_call_cap": pass2_target_universe["fmp_grade_call_cap"],
            "fmp_grade_calls_within_free_daily_cap": pass2_target_universe["fmp_grade_calls_within_free_daily_cap"],
            "neutral_fill_tickers_excluded_from_expensive_pass2": (
                pass2_target_universe["neutral_fill_tickers_excluded_from_expensive_pass2"]
            ),
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": expected_total_call_budget,
            "actual_total_endpoint_calls": len(endpoint_records),
            "sec_ticker_reference_calls": _endpoint_count(endpoint_records, "sec_edgar", "company_tickers_mapping"),
            "fmp_grades_calls": _endpoint_count(endpoint_records, "financial_modeling_prep", "grades"),
            "sec_submissions_calls": _endpoint_count(endpoint_records, "sec_edgar", "submissions"),
            "massive_reference_news_calls": _endpoint_count(endpoint_records, "massive", "reference_news"),
            "fmp_stock_split_calls": _endpoint_count(endpoint_records, "financial_modeling_prep", "stock_splits"),
            "fmp_dividend_calls": _endpoint_count(endpoint_records, "financial_modeling_prep", "dividends"),
            "endpoint_error_count": endpoint_errors,
            "sec_cik_missing_count": len([symbol for symbol in eligible if symbol not in cik_by_symbol]),
            "retry_count_allowed": 0,
            "retry_count_used": 0,
            "within_budget": len(endpoint_records) <= expected_total_call_budget,
        },
        "endpoint_results": [_summarize_endpoint(record) for record in endpoint_records],
        "storage": {
            "raw_payload_root": _repo_rel(raw_root),
            "raw_payload_root_gitignored": True,
            "tracked_summary_path": _repo_rel(summary_path),
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_raw_payload": False,
            "tracked_summary_contains_request_urls": False,
            "tracked_summary_contains_secrets": False,
        },
        "source_artifacts": {
            "candidate_subset_path": _repo_rel(source_paths["candidate_subset"]),
            "offering_audit_source_path": _repo_rel(source_paths["offering_audit_source"]),
            "analyst_grade_actions_path": _repo_rel(source_paths["analyst_grade_actions"]),
            "massive_news_events_path": _repo_rel(source_paths["massive_news_events"]),
            "corporate_action_capture_path": _repo_rel(source_paths["corporate_action_capture"]),
            "momentum_projection_path": _repo_rel(source_paths["momentum_projection"]),
            "theme_projection_path": _repo_rel(source_paths["theme_projection"]),
            "artifacts_gitignored": all(_git_ignored(source_paths[key]) for key in source_paths if key != "source_packet"),
        },
        "source_packet": {
            "path": _repo_rel(source_paths["source_packet"]),
            "preflight_status": (
                source_packet_preflight["scope"]["preflight_status"]
                if source_packet_preflight is not None
                else "not_run"
            ),
            "run_data_context_requested": run_data_context,
            "data_context_output_path": (
                source_packet_run["data_context"]["output_path"]
                if source_packet_run is not None
                else None
            ),
            "context_components_output_path": (
                _repo_rel(context_components_output_path) if context_components_output_path is not None else None
            ),
        },
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "paid_access_used": False,
            "datahub_consumed": False,
            "production_readiness_claimed": False,
            "corporate_action_reconciliation_claimed": False,
            "return_calculation_performed": False,
            "ship_gate_evidence_claimed": False,
            "live_normalized_evidence_claimed": False,
            "broker_or_order_execution_performed": False,
            "a_share_crossing_performed": False,
        },
        "limitations": [
            "This source-packet run is narrowed to the reviewed Pass2 target universe, not full-market coverage evidence and not the full Pass1-eligible set.",
            "Split/dividend endpoints are captured as raw provider evidence only; this runner does not reconcile corporate actions or calculate returns.",
            "Raw payloads stay under gitignored provider_samples; tracked summary excludes request URLs, raw rows, and secrets.",
            "No provider selection, DataHub, production storage, broker/order execution, live-normalized, or ship-gate evidence is claimed.",
        ],
    }


def _assert_text_safe(text: str, sensitive_values: list[str]) -> None:
    lower = text.lower()
    forbidden = (
        "apikey=",
        "financialmodelingprep.com",
        "api.massive.com",
        "data.sec.gov",
        "www.sec.gov",
        "http://",
        "https://",
        "\"payload\"",
        "\"request_url\"",
        "\"raw_payload\"",
    )
    for fragment in forbidden:
        if fragment in lower:
            raise FullCandidateLiveSourcePacketError(f"tracked summary contains forbidden fragment: {fragment}")
    for value in sensitive_values:
        if value and value in text:
            raise FullCandidateLiveSourcePacketError("tracked summary contains a sensitive environment value")


def _validate_summary_against_schema(summary: dict[str, Any]) -> None:
    _validate_json_schema(summary, SUMMARY_SCHEMA_PATH, label="full-candidate live source-packet summary")
    gate = summary["preflight_gate"]
    budget = summary["endpoint_call_budget"]
    if gate["expected_total_call_budget"] != gate["preflight_total_call_forecast"]:
        raise FullCandidateLiveSourcePacketError("summary call budget does not match preflight forecast")
    if budget["max_total_endpoint_calls"] != gate["expected_total_call_budget"]:
        raise FullCandidateLiveSourcePacketError("summary max call budget does not match the expected budget")
    actual_family_calls = (
        budget["sec_ticker_reference_calls"]
        + budget["fmp_grades_calls"]
        + budget["sec_submissions_calls"]
        + budget["massive_reference_news_calls"]
        + budget["fmp_stock_split_calls"]
        + budget["fmp_dividend_calls"]
    )
    if actual_family_calls != budget["actual_total_endpoint_calls"]:
        raise FullCandidateLiveSourcePacketError("summary endpoint family counts do not equal actual calls")
    if budget["actual_total_endpoint_calls"] != len(summary["endpoint_results"]):
        raise FullCandidateLiveSourcePacketError("summary endpoint_results length does not equal actual calls")


def _write_summary_validated(summary: dict[str, Any], summary_path: Path, sensitive_values: list[str]) -> None:
    _validate_summary_against_schema(summary)
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text, sensitive_values)
    _write_json_atomic(summary, summary_path)


def _canonical_forced_holdings(
    forced_holding_tickers: list[str] | tuple[str, ...] | None,
    *,
    eligible: set[str],
) -> set[str]:
    """Canonicalize the caller-supplied forced-holding tickers exactly as the preflight `_canonical_list_keys` does
    (the repo single US-ticker identity policy) and require each to be in the reviewed Pass1-eligible set, so the
    live target re-derivation matches the preflight rule `target = momentum-scored∩eligible ∪ forced-holdings`."""
    if forced_holding_tickers is None:
        return set()
    if type(forced_holding_tickers) not in (list, tuple):
        raise FullCandidateLiveSourcePacketError("forced_holding_tickers must be an exact list/tuple or None")
    out: set[str] = set()
    for raw in forced_holding_tickers:
        if type(raw) is not str:
            raise FullCandidateLiveSourcePacketError("forced_holding_tickers must contain exact ticker strings")
        canon = canonical_us_ticker(raw)
        if canon is None:
            raise FullCandidateLiveSourcePacketError("forced_holding_tickers contains a non-canonicalizable ticker")
        if canon not in eligible:
            raise FullCandidateLiveSourcePacketError("forced_holding_tickers must be in the Pass1-eligible candidate set")
        out.add(canon)
    return out


def _rederive_and_verify_pass2_targets(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
    eligibility_governance: dict[str, Any],
    momentum_projection_path: Path,
    forced_holding_tickers: list[str] | tuple[str, ...] | None,
    reviewed_target_symbols: list[str],
    preflight_within_cap: Any,
    momentum_top_k: int,
) -> dict[str, Any]:
    """Independently RE-DERIVE the Step 1 funnel Pass2 target from the momentum projection + candidate artifact
    (mirrors the preflight `_pass2_target_universe` via the SAME `select_pass2_targets`: top-K by momentum score
    plus forced holdings, with the SAME K read from the reviewed preflight), and
    REJECT any preflight whose `target_symbols` / within-cap disagree — so the expensive live boundary does NOT
    trust the preflight's self-attestation. Closes R-USSHORT-BATCH5-LIVE-RUNNER-TRUSTS-PREFLIGHT-FUNNEL-NOT-
    REDERIVED (a forged preflight can otherwise inject a neutral-fill target or re-expand to the full 2404/12021).
    Returns the runner-verified target universe for the summary, so its const-true within-cap / neutral-excluded
    attestations are COMPUTED here (only reachable on the truly-true path), not copied from the preflight."""
    artifact = _read_json(candidate_artifact_path)
    try:
        artifact = universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=expected_decision_date,
            governance=eligibility_governance,
        )
    except Exception as exc:
        raise FullCandidateLiveSourcePacketError(f"candidate artifact failed validation: {exc}") from exc
    eligible = set(artifact["eligible_tickers"])
    raw = _read_json(momentum_projection_path)
    if type(raw) is not dict or type(raw.get("momentum_by_ticker")) is not dict:
        raise FullCandidateLiveSourcePacketError("momentum projection has an invalid shape for target re-derivation")
    forced = _canonical_forced_holdings(forced_holding_tickers, eligible=eligible)
    # SINGLE-SOURCE funnel selection: the SAME select_pass2_targets the preflight used (top-K by momentum score +
    # forced holdings), with the SAME K read from the reviewed preflight, so the runner re-derivation is provably
    # identical to the preflight target. A hand-authored non-canonical-keyed projection fails closed HERE (before
    # any fetch) as a funnel mismatch rather than fetching and then failing downstream.
    try:
        expected_list = select_pass2_targets(
            momentum_scores=raw["momentum_by_ticker"],
            eligible=eligible,
            forced_holdings=forced,
            top_k=momentum_top_k,
        )
    except Pass2FunnelError as exc:
        raise FullCandidateLiveSourcePacketError(f"re-derived Pass2 funnel target is invalid: {exc}") from exc
    expected = set(expected_list)
    if type(reviewed_target_symbols) is not list or set(reviewed_target_symbols) != expected:
        raise FullCandidateLiveSourcePacketError(
            "preflight target_symbols do not match the re-derived momentum top-K plus forced-holdings funnel"
        )
    within_cap = len(expected) <= FMP_FREE_DAILY_GRADE_CALL_CAP
    if not within_cap or preflight_within_cap is not True:
        raise FullCandidateLiveSourcePacketError(
            "re-derived Pass2 target exceeds the FMP free daily grade-call cap or disagrees with the preflight within-cap flag"
        )
    targets = expected_list  # already sorted by select_pass2_targets
    return {
        "selection_mode": "momentum_scored_candidates_plus_forced_holdings",
        "eligible_count": len(artifact["eligible_tickers"]),
        "momentum_top_k": momentum_top_k,
        "target_count": len(targets),
        "target_symbols": targets,
        "target_symbol_sample": targets[:10],
        "fmp_grade_call_cap": FMP_FREE_DAILY_GRADE_CALL_CAP,
        "fmp_grade_calls_within_free_daily_cap": within_cap,
        "neutral_fill_tickers_excluded_from_expensive_pass2": True,
    }


def run_full_candidate_live_source_packet(
    *,
    preflight_summary_path: Path = PREFLIGHT_SUMMARY_PATH,
    expected_total_call_budget: int,
    output_data_context_path: Path = DEFAULT_OUTPUT_DATA_CONTEXT_PATH,
    context_components_output_path: Path | None = DEFAULT_CONTEXT_COMPONENTS_OUTPUT_PATH,
    source_artifact_prefix: Path = SOURCE_ARTIFACT_PREFIX,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    client: sample_validation.JsonHttpClient | None = None,
    confirm_user_authorization: bool = False,
    run_data_context: bool = False,
    generated_at: str | None = None,
    observed_at: str | None = None,
    theme_opportunity_state: str = "strong",
    forced_holding_tickers: list[str] | tuple[str, ...] | None = None,
    sec_sleep_seconds: float = sample_validation.SEC_FAIR_ACCESS_SLEEP_SECONDS,
) -> dict[str, Any]:
    if not confirm_user_authorization:
        raise FullCandidateLiveSourcePacketError("full-candidate live provider execution requires explicit user authorization")
    generated_at = generated_at or iso_now()
    observed_at = observed_at or generated_at
    if not _valid_observed_at(generated_at) or not _valid_observed_at(observed_at):
        raise FullCandidateLiveSourcePacketError("generated_at and observed_at must be timezone-aware RFC3339 instants")
    preflight_path = _validate_preflight_path(preflight_summary_path)
    preflight = _load_ready_preflight(preflight_path, expected_total_call_budget)
    expected_decision_date = preflight["decision_clock"]["expected_decision_date"]
    source_as_of = _date8_to_ymd(expected_decision_date)

    if not _provider_samples_gitignored():
        raise FullCandidateLiveSourcePacketError("provider_samples/ is not confirmed in .gitignore")
    candidate_path = _existing_state_json(
        preflight["candidate_universe"]["candidate_artifact_path"],
        field="preflight.candidate_artifact_path",
    )
    preflight_targets = preflight["pass2_target_universe"]
    reviewed_target_symbols = list(preflight_targets["target_symbols"])
    momentum_path = _existing_state_json(
        preflight["local_input_coverage"]["momentum_projection"]["path"],
        field="preflight.momentum_projection.path",
    )
    theme_path = _existing_state_json(
        preflight["local_input_coverage"]["theme_projection"]["path"],
        field="preflight.theme_projection.path",
    )
    output_path = _validate_state_json_path(output_data_context_path, field="output_data_context_path")
    components_path = (
        _validate_state_json_path(context_components_output_path, field="context_components_output_path")
        if context_components_output_path is not None
        else None
    )
    prefix = _validate_source_artifact_prefix(source_artifact_prefix)
    paths = _source_paths(prefix)
    for field, path in paths.items():
        _validate_state_json_path(path, field=f"source_artifact.{field}")
    raw_root_resolved = _validate_raw_root(raw_root)
    summary_resolved = _validate_summary_path(summary_path)

    eligibility_governance = load_eligibility_governance(ELIGIBILITY_GOVERNANCE_PATH)
    load_catalyst_governance()
    verified_targets = _rederive_and_verify_pass2_targets(
        candidate_artifact_path=candidate_path,
        expected_decision_date=expected_decision_date,
        eligibility_governance=eligibility_governance,
        momentum_projection_path=momentum_path,
        forced_holding_tickers=forced_holding_tickers,
        reviewed_target_symbols=reviewed_target_symbols,
        preflight_within_cap=preflight_targets.get("fmp_grade_calls_within_free_daily_cap"),
        momentum_top_k=preflight_targets.get("momentum_top_k"),
    )
    # Re-anchor the live-spend budget to the RUNNER-re-derived target count (not the preflight-attested
    # forecast/momentum_top_k): the operator's authorized call budget must equal the forecast recomputed from the
    # re-derived Pass2 target count, so a forged preflight that widens momentum_top_k / target_count is rejected
    # BEFORE any provider call unless the operator independently authorized the matching wider budget. Closes the
    # circular-K seam where the re-derivation otherwise consumes K from the very summary it distrusts.
    rederived_call_forecast = _SEC_TICKER_MAPPING_CALLS + verified_targets["target_count"] * _PASS2_ENDPOINT_CALLS_PER_TARGET
    if rederived_call_forecast != expected_total_call_budget:
        raise FullCandidateLiveSourcePacketError(
            "expected call budget must match the forecast recomputed from the re-derived Pass2 target count: "
            f"{expected_total_call_budget} != {rederived_call_forecast}"
        )
    candidate_subset = _candidate_subset_artifact(
        candidate_artifact_path=candidate_path,
        expected_decision_date=expected_decision_date,
        eligibility_governance=eligibility_governance,
        selected_symbols=reviewed_target_symbols,
    )
    selected_symbols = list(candidate_subset["eligible_tickers"])
    if selected_symbols != reviewed_target_symbols:
        raise FullCandidateLiveSourcePacketError("candidate target symbols drifted from the reviewed preflight")

    fmp_env = sample_validation.read_required_env("FMP_API_KEY")
    sec_env = sample_validation.read_required_env("SEC_USER_AGENT")
    massive_env = sample_validation.read_required_env("MASSIVE_API_KEY")
    env_summary = {
        "fmp_api_key_present": True,
        "fmp_api_key_source": fmp_env.source,
        "sec_user_agent_present": True,
        "sec_user_agent_source": sec_env.source,
        "massive_api_key_present": True,
        "massive_api_key_source": massive_env.source,
        "environment_values_logged": False,
        "secrets_logged": False,
    }

    client = client or sample_validation.JsonHttpClient()
    records, cik_by_symbol = _fetch_live_records(
        selected_symbols=selected_symbols,
        raw_root=raw_root_resolved,
        client=client,
        fmp_env=fmp_env,
        sec_env=sec_env,
        massive_env=massive_env,
        sec_sleep_seconds=sec_sleep_seconds,
        max_total_endpoint_calls=expected_total_call_budget,
    )
    resolved_sources = _resolved_source_artifacts(
        selected_symbols=selected_symbols,
        source_as_of=source_as_of,
        observed_at=observed_at,
        records=records,
    )
    corporate_action_capture = _build_corporate_action_capture(
        generated_at=generated_at,
        expected_decision_date=expected_decision_date,
        source_as_of=source_as_of,
        observed_at=observed_at,
        selected_symbols=selected_symbols,
        records=records,
    )
    target_momentum_projection = _target_scoped_projection(
        projection_path=momentum_path,
        value_key="momentum_by_ticker",
        selected_symbols=selected_symbols,
    )
    target_theme_projection = _target_scoped_projection(
        projection_path=theme_path,
        value_key="theme_block_by_ticker",
        selected_symbols=selected_symbols,
    )

    _write_json_atomic(candidate_subset, paths["candidate_subset"])
    _write_json_atomic(resolved_sources["offering_audit_source"], paths["offering_audit_source"])
    _write_json_atomic(resolved_sources["analyst_grade_actions"], paths["analyst_grade_actions"])
    _write_json_atomic(resolved_sources["massive_news_events"], paths["massive_news_events"])
    _write_json_atomic(corporate_action_capture, paths["corporate_action_capture"])
    _write_json_atomic(target_momentum_projection, paths["momentum_projection"])
    _write_json_atomic(target_theme_projection, paths["theme_projection"])
    packet = _build_local_source_packet(
        generated_at=generated_at,
        expected_decision_date=expected_decision_date,
        theme_opportunity_state=theme_opportunity_state,
        paths=paths,
        momentum_projection_path=paths["momentum_projection"],
        theme_projection_path=paths["theme_projection"],
        output_data_context_path=output_path,
        context_components_output_path=components_path,
    )
    _write_json_atomic(packet, paths["source_packet"])

    try:
        packet_preflight = run_local_source_packet_preflight(paths["source_packet"], generated_at=generated_at)
        packet_run = (
            run_local_source_packet(paths["source_packet"], generated_at=generated_at)
            if run_data_context
            else None
        )
    except SourcePacketError as exc:
        raise FullCandidateLiveSourcePacketError(f"local source-packet runner rejected generated packet: {exc}") from exc

    summary = _build_summary(
        generated_at=generated_at,
        expected_decision_date=expected_decision_date,
        source_as_of=source_as_of,
        observed_at=observed_at,
        env_summary=env_summary,
        preflight_summary_path=preflight_path,
        expected_total_call_budget=expected_total_call_budget,
        preflight_total_call_forecast=preflight["endpoint_call_forecast"]["total_calls_for_pass2_target_cut"],
        candidate_artifact_path=candidate_path,
        candidate_artifact=candidate_subset,
        pass2_target_universe=verified_targets,
        endpoint_records=records,
        cik_by_symbol=cik_by_symbol,
        raw_root=raw_root_resolved,
        summary_path=summary_resolved,
        source_paths=paths,
        source_packet_preflight=packet_preflight,
        source_packet_run=packet_run,
        run_data_context=run_data_context,
        context_components_output_path=components_path,
    )
    _write_summary_validated(summary, summary_resolved, [fmp_env.value, sec_env.value, massive_env.value])
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the US-short Batch5 full-candidate live Pass2 resolved-source packet from reviewed "
            "preflight inputs, including split/dividend endpoint capture. This does not reconcile "
            "corporate actions, calculate returns, use DataHub, or claim production/ship-gate evidence."
        )
    )
    parser.add_argument("--preflight-summary-path", type=Path, default=PREFLIGHT_SUMMARY_PATH)
    parser.add_argument("--expected-total-call-budget", type=int, required=True)
    parser.add_argument("--output-data-context-path", type=Path, default=DEFAULT_OUTPUT_DATA_CONTEXT_PATH)
    parser.add_argument("--context-components-out", type=Path, default=DEFAULT_CONTEXT_COMPONENTS_OUTPUT_PATH)
    parser.add_argument("--source-artifact-prefix", type=Path, default=SOURCE_ARTIFACT_PREFIX)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_SAMPLE_ROOT)
    parser.add_argument("--generated-at")
    parser.add_argument("--observed-at")
    parser.add_argument("--theme-opportunity-state", default="strong")
    parser.add_argument("--forced-holding-ticker", action="append", default=[])
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--run-data-context", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        summary = run_full_candidate_live_source_packet(
            preflight_summary_path=args.preflight_summary_path,
            expected_total_call_budget=args.expected_total_call_budget,
            output_data_context_path=args.output_data_context_path,
            context_components_output_path=args.context_components_out,
            source_artifact_prefix=args.source_artifact_prefix,
            summary_path=args.summary_path,
            raw_root=args.raw_root,
            confirm_user_authorization=args.confirm_user_authorization,
            run_data_context=args.run_data_context,
            generated_at=args.generated_at,
            observed_at=args.observed_at,
            theme_opportunity_state=args.theme_opportunity_state,
            forced_holding_tickers=args.forced_holding_ticker,
        )
    except FullCandidateLiveSourcePacketError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "status": summary["scope"]["status"],
                "eligible_count": summary["candidate_universe"]["eligible_count"],
                "actual_total_endpoint_calls": summary["endpoint_call_budget"]["actual_total_endpoint_calls"],
                "endpoint_error_count": summary["endpoint_call_budget"]["endpoint_error_count"],
                "summary_path": summary["storage"]["tracked_summary_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
