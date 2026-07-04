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


AUTHORIZATION_REF = "user_chat_20260704_us_short_live_pass2_source_packet"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_live_source_packet_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_live_source_packet_summary_20260704.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_live_source_packet_20260704")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
SOURCE_ARTIFACT_PREFIX = STATE_US_SHORT_DIR / "us_short_batch5_live_source_packet_20260704"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
DEFAULT_OUTPUT_DATA_CONTEXT_PATH = STATE_US_SHORT_DIR / "us_short_batch5_live_source_packet_20260704_data_context.json"
MAX_SYMBOLS = 3
MAX_TOTAL_ENDPOINT_CALLS = 1 + (MAX_SYMBOLS * 3)
MASSIVE_NEWS_URL = "https://api.massive.com/v2/reference/news?ticker={ticker}&limit=10&apiKey={key}"


class LiveSourcePacketError(ValueError):
    """The bounded live Pass2 source packet cannot be fetched, resolved, or consumed safely."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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
        raise LiveSourcePacketError(f"{field} must stay under the repository root") from exc
    return resolved


def _existing_file(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    if not resolved.exists() or not resolved.is_file():
        raise LiveSourcePacketError(f"{field} must be an existing file: {_display_path(resolved)}")
    return resolved


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


def _validate_state_json_path(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise LiveSourcePacketError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise LiveSourcePacketError(f"{field} must be a .json path")
    if not _git_ignored(resolved):
        raise LiveSourcePacketError(f"{field} must be gitignored")
    return resolved


def _validate_source_artifact_prefix(prefix: Path | str) -> Path:
    resolved = _resolve_repo_path(prefix, field="source_artifact_prefix")
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise LiveSourcePacketError("source_artifact_prefix must stay under state/us_short/") from exc
    return resolved


def _source_paths(prefix: Path) -> dict[str, Path]:
    return {
        "candidate_subset": prefix.with_name(prefix.name + "_candidate_subset.json"),
        "offering_audit_source": prefix.with_name(prefix.name + "_offering_audit_source.json"),
        "analyst_grade_actions": prefix.with_name(prefix.name + "_analyst_grade_actions.json"),
        "massive_news_events": prefix.with_name(prefix.name + "_massive_news_events.json"),
        "source_packet": prefix.with_name(prefix.name + "_source_packet.json"),
    }


def _validate_raw_root(raw_root: Path) -> None:
    resolved = _resolve_repo_path(raw_root, field="raw_root")
    approved = (ROOT / RAW_SAMPLE_REL_ROOT).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise LiveSourcePacketError(
            "raw_root must stay under provider_samples/us_short_batch5_live_source_packet_20260704/"
        ) from exc
    try:
        sample_validation.validate_raw_root(resolved)
    except ValueError as exc:
        raise LiveSourcePacketError(str(exc)) from exc


def _validate_summary_path(summary_path: Path) -> None:
    resolved = _resolve_repo_path(summary_path, field="summary_path")
    if resolved == SUMMARY_PATH.resolve():
        return
    try:
        resolved.relative_to((ROOT / RAW_SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise LiveSourcePacketError(
            "summary_path must be the canonical tracked summary or under this runner's provider_samples folder"
        ) from exc


def _provider_samples_gitignored() -> bool:
    gitignore = ROOT / ".gitignore"
    return gitignore.exists() and "provider_samples/" in gitignore.read_text(encoding="utf-8")


def _date8_to_ymd(value: str) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise LiveSourcePacketError("expected_decision_date must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise LiveSourcePacketError("expected_decision_date must be a real calendar date") from exc


def _valid_observed_at(value: str) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _selected_symbols(symbols: list[str] | tuple[str, ...]) -> list[str]:
    if type(symbols) not in (list, tuple) or not symbols:
        raise LiveSourcePacketError("selected_symbols must be a non-empty list/tuple")
    if len(symbols) > MAX_SYMBOLS:
        raise LiveSourcePacketError(f"selected_symbols may contain at most {MAX_SYMBOLS} tickers")
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        if type(raw) is not str:
            raise LiveSourcePacketError("selected_symbols must contain exact strings")
        ticker = canonical_us_ticker(raw)
        if ticker is None:
            raise LiveSourcePacketError("selected_symbols must be canonicalizable US tickers")
        if ticker in seen:
            raise LiveSourcePacketError(f"duplicate selected symbol: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    return out


def _candidate_subset_artifact(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
    selected_symbols: list[str],
    eligibility_governance: dict[str, Any],
) -> dict[str, Any]:
    artifact = _read_json(candidate_artifact_path)
    try:
        universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=expected_decision_date,
            governance=eligibility_governance,
        )
    except Exception as exc:
        raise LiveSourcePacketError(f"candidate artifact failed validation: {exc}") from exc
    rows_by_ticker = {row["ticker"]: row for row in artifact["rows"]}
    eligible = set(artifact["eligible_tickers"])
    missing = [ticker for ticker in selected_symbols if ticker not in rows_by_ticker]
    not_eligible = [ticker for ticker in selected_symbols if ticker not in eligible]
    if missing or not_eligible:
        raise LiveSourcePacketError(
            f"selected_symbols must exist and be Pass1-eligible (missing {missing}, not_eligible {not_eligible})"
        )
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
        universe_fetch.validate_candidate_artifact(
            subset,
            expected_decision_date=expected_decision_date,
            governance=eligibility_governance,
        )
    except Exception as exc:
        raise LiveSourcePacketError(f"candidate subset failed validation: {exc}") from exc
    return subset


def _assert_endpoint_budget(records: list[sample_validation.FetchRecord], next_call_count: int = 1) -> None:
    try:
        sample_validation.assert_endpoint_budget_available(
            records,
            MAX_TOTAL_ENDPOINT_CALLS,
            next_call_count=next_call_count,
        )
    except RuntimeError as exc:
        raise LiveSourcePacketError(str(exc)) from exc


def _fetch_live_records(
    *,
    selected_symbols: list[str],
    raw_root: Path,
    client: sample_validation.JsonHttpClient,
    fmp_env: sample_validation.EnvValue,
    sec_env: sample_validation.EnvValue,
    massive_env: sample_validation.EnvValue,
    sec_sleep_seconds: float,
) -> tuple[list[sample_validation.FetchRecord], dict[str, str]]:
    records: list[sample_validation.FetchRecord] = []
    _assert_endpoint_budget(records)
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

    fmp_headers = {"User-Agent": "StockSystem/0.1 us-short-batch5-live-source-packet"}
    sec_headers = {"User-Agent": sec_env.value, "Host": "data.sec.gov"}
    massive_headers = {"User-Agent": "StockSystem/0.1 us-short-batch5-live-source-packet"}
    for symbol in selected_symbols:
        _assert_endpoint_budget(records)
        records.append(
            sample_validation.fetch_and_store(
                client,
                url=sample_validation.fmp_url("grades", symbol, {}, fmp_env.value, endpoint_mode="stable"),
                provider_id="financial_modeling_prep",
                endpoint_family="grades",
                symbol=symbol,
                raw_root=raw_root,
                headers=fmp_headers,
            )
        )

        cik10 = cik_by_symbol.get(symbol)
        if cik10:
            _assert_endpoint_budget(records)
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

        _assert_endpoint_budget(records)
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
    return records, cik_by_symbol


def _record_map(records: list[sample_validation.FetchRecord]) -> dict[tuple[str, str, str | None], sample_validation.FetchRecord]:
    return {(record.provider_id, record.endpoint_family, record.symbol): record for record in records}


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
        raise LiveSourcePacketError(f"SEC offering source rejected: {exc}") from exc
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
        raise LiveSourcePacketError(f"Pass2 source resolver rejected live payloads: {exc}") from exc
    return {
        "offering_audit_source": offering_source,
        "analyst_grade_actions": analyst_grade_actions,
        "massive_news_events": massive_news_events,
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
) -> dict[str, Any]:
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
        "paths": {
            "candidate_artifact_path": _repo_rel(paths["candidate_subset"]),
            "eligibility_governance_path": "presets/us_short_eligibility_governance_20260624.json",
            "momentum_projection_path": _repo_rel(momentum_projection_path),
            "theme_projection_path": _repo_rel(theme_projection_path),
            "offering_audit_source_path": _repo_rel(paths["offering_audit_source"]),
            "analyst_grade_actions_path": _repo_rel(paths["analyst_grade_actions"]),
            "massive_news_events_path": _repo_rel(paths["massive_news_events"]),
            "catalyst_governance_path": "presets/us_short_catalyst_governance_20260630.json",
            "output_data_context_path": _repo_rel(output_data_context_path),
        },
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


def _payload_shape(record: sample_validation.FetchRecord) -> dict[str, Any]:
    payload = record.payload
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


def _summarize_endpoint(record: sample_validation.FetchRecord) -> dict[str, Any]:
    return {
        "provider_id": record.provider_id,
        "endpoint_family": record.endpoint_family,
        "symbol": record.symbol,
        "status": "success" if record.ok else "error",
        "http_status": record.http_status,
        "error_type": record.error_type,
        "raw_sample_ref": record.raw_sample_ref,
        "raw_sample_ref_gitignored": record.raw_sample_ref.startswith("provider_samples/"),
        "payload_shape": _payload_shape(record),
    }


def _build_summary(
    *,
    generated_at: str,
    expected_decision_date: str,
    selected_symbols: list[str],
    source_as_of: str,
    observed_at: str,
    env_summary: dict[str, Any],
    endpoint_records: list[sample_validation.FetchRecord],
    raw_root: Path,
    summary_path: Path,
    source_paths: dict[str, Path],
    source_packet_preflight: dict[str, Any] | None,
    source_packet_run: dict[str, Any] | None,
    run_data_context: bool,
) -> dict[str, Any]:
    endpoint_errors = sum(1 for record in endpoint_records if not record.ok)
    return {
        "schema_name": "us_short_batch5_live_source_packet_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_live_source_packet_summary.schema.json",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "bounded_live_pass2_resolved_source_packet",
            "status": (
                "source_packet_built_and_data_context_written"
                if source_packet_run is not None
                else "source_packet_built_preflight_only"
            ),
            "provider_calls_performed": True,
            "raw_payload_storage_performed": True,
            "resolved_source_artifacts_written": True,
            "source_packet_written": True,
            "data_context_written": source_packet_run is not None,
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
        "sample_universe": {
            "symbol_source": "caller_selected_from_validated_candidate_artifact",
            "symbols": selected_symbols,
            "max_symbols": MAX_SYMBOLS,
            "full_market_sample": False,
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "actual_total_endpoint_calls": len(endpoint_records),
            "endpoint_error_count": endpoint_errors,
            "within_budget": len(endpoint_records) <= MAX_TOTAL_ENDPOINT_CALLS,
        },
        "endpoint_results": [_summarize_endpoint(record) for record in endpoint_records],
        "storage": {
            "raw_payload_root": _repo_rel(raw_root),
            "raw_payload_root_gitignored": True,
            "tracked_summary_path": _repo_rel(summary_path),
            "tracked_summary_contains_raw_rows": False,
            "tracked_summary_contains_raw_payload": False,
            "secrets_in_summary": False,
            "request_urls_in_summary": False,
        },
        "source_artifacts": {
            "candidate_subset_path": _repo_rel(source_paths["candidate_subset"]),
            "offering_audit_source_path": _repo_rel(source_paths["offering_audit_source"]),
            "analyst_grade_actions_path": _repo_rel(source_paths["analyst_grade_actions"]),
            "massive_news_events_path": _repo_rel(source_paths["massive_news_events"]),
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
        },
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "paid_access_used": False,
            "datahub_consumed": False,
            "production_readiness_claimed": False,
            "ship_gate_evidence_claimed": False,
            "live_normalized_evidence_claimed": False,
            "broker_or_order_execution_performed": False,
            "a_share_crossing_performed": False,
        },
        "limitations": [
            "This is a bounded active-symbol Pass2 source-packet wiring run, not full-market coverage evidence.",
            "Momentum and theme projections are explicit local inputs; this runner does not fetch price history, GICS, or theme membership.",
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
        "\"payload\"",
        "\"request_url\"",
        "\"raw_payload\"",
    )
    for fragment in forbidden:
        if fragment in lower:
            raise LiveSourcePacketError(f"tracked summary contains forbidden fragment: {fragment}")
    for value in sensitive_values:
        if value and value in text:
            raise LiveSourcePacketError("tracked summary contains a sensitive environment value")


def _validate_summary_against_schema(summary: dict[str, Any]) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise LiveSourcePacketError("jsonschema is required for summary validation") from exc
    schema = _read_json(SUMMARY_SCHEMA_PATH)
    errors = sorted(Draft7Validator(schema).iter_errors(summary), key=lambda error: list(error.path))
    if errors:
        raise LiveSourcePacketError(
            "live source-packet summary failed schema validation: "
            + "; ".join(error.message for error in errors[:5])
        )


def _write_summary_validated(summary: dict[str, Any], summary_path: Path, sensitive_values: list[str]) -> None:
    _validate_summary_against_schema(summary)
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text, sensitive_values)
    _write_json_atomic(summary, summary_path)


def run_live_source_packet(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    expected_decision_date: str,
    selected_symbols: list[str],
    momentum_projection_path: Path,
    theme_projection_path: Path,
    output_data_context_path: Path = DEFAULT_OUTPUT_DATA_CONTEXT_PATH,
    source_artifact_prefix: Path = SOURCE_ARTIFACT_PREFIX,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    client: sample_validation.JsonHttpClient | None = None,
    confirm_user_authorization: bool = False,
    run_data_context: bool = False,
    generated_at: str | None = None,
    observed_at: str | None = None,
    theme_opportunity_state: str = "strong",
    sec_sleep_seconds: float = sample_validation.SEC_FAIR_ACCESS_SLEEP_SECONDS,
) -> dict[str, Any]:
    if not confirm_user_authorization:
        raise LiveSourcePacketError("live provider source-packet execution requires explicit user authorization")
    generated_at = generated_at or iso_now()
    observed_at = observed_at or generated_at
    if not _valid_observed_at(generated_at) or not _valid_observed_at(observed_at):
        raise LiveSourcePacketError("generated_at and observed_at must be timezone-aware RFC3339 instants")
    source_as_of = _date8_to_ymd(expected_decision_date)
    symbols = _selected_symbols(selected_symbols)
    if 1 + (len(symbols) * 3) > MAX_TOTAL_ENDPOINT_CALLS:
        raise LiveSourcePacketError("selected_symbols exceed the endpoint budget")
    if not _provider_samples_gitignored():
        raise LiveSourcePacketError("provider_samples/ is not confirmed in .gitignore")

    candidate_path = _existing_file(candidate_artifact_path, field="candidate_artifact_path")
    momentum_path = _existing_file(momentum_projection_path, field="momentum_projection_path")
    theme_path = _existing_file(theme_projection_path, field="theme_projection_path")
    output_path = _validate_state_json_path(output_data_context_path, field="output_data_context_path")
    prefix = _validate_source_artifact_prefix(source_artifact_prefix)
    paths = _source_paths(prefix)
    for field, path in paths.items():
        if field != "source_packet":
            _validate_state_json_path(path, field=f"source_artifact.{field}")
    _validate_state_json_path(paths["source_packet"], field="source_artifact.source_packet")
    _validate_raw_root(raw_root)
    _validate_summary_path(summary_path)

    eligibility_governance = load_eligibility_governance(ELIGIBILITY_GOVERNANCE_PATH)
    load_catalyst_governance()
    candidate_subset = _candidate_subset_artifact(
        candidate_artifact_path=candidate_path,
        expected_decision_date=expected_decision_date,
        selected_symbols=symbols,
        eligibility_governance=eligibility_governance,
    )

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
    records, _ = _fetch_live_records(
        selected_symbols=symbols,
        raw_root=raw_root,
        client=client,
        fmp_env=fmp_env,
        sec_env=sec_env,
        massive_env=massive_env,
        sec_sleep_seconds=sec_sleep_seconds,
    )
    resolved_sources = _resolved_source_artifacts(
        selected_symbols=symbols,
        source_as_of=source_as_of,
        observed_at=observed_at,
        records=records,
    )

    _write_json_atomic(candidate_subset, paths["candidate_subset"])
    _write_json_atomic(resolved_sources["offering_audit_source"], paths["offering_audit_source"])
    _write_json_atomic(resolved_sources["analyst_grade_actions"], paths["analyst_grade_actions"])
    _write_json_atomic(resolved_sources["massive_news_events"], paths["massive_news_events"])
    packet = _build_local_source_packet(
        generated_at=generated_at,
        expected_decision_date=expected_decision_date,
        theme_opportunity_state=theme_opportunity_state,
        paths=paths,
        momentum_projection_path=momentum_path,
        theme_projection_path=theme_path,
        output_data_context_path=output_path,
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
        raise LiveSourcePacketError(f"local source-packet runner rejected generated packet: {exc}") from exc

    summary = _build_summary(
        generated_at=generated_at,
        expected_decision_date=expected_decision_date,
        selected_symbols=symbols,
        source_as_of=source_as_of,
        observed_at=observed_at,
        env_summary=env_summary,
        endpoint_records=records,
        raw_root=raw_root,
        summary_path=summary_path,
        source_paths=paths,
        source_packet_preflight=packet_preflight,
        source_packet_run=packet_run,
        run_data_context=run_data_context,
    )
    _write_summary_validated(summary, summary_path, [fmp_env.value, sec_env.value, massive_env.value])
    return summary


def _parse_symbols(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a bounded US-short Batch5 live Pass2 resolved-source packet from authorized SEC/FMP/Massive "
            "inputs, then optionally run the existing local source-packet data_context assembler."
        )
    )
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--decision-date", required=True, help="Expected decision date as YYYYMMDD.")
    parser.add_argument("--symbols", default="AAPL,MSFT,JPM", help="Comma-separated <=3 active eligible tickers.")
    parser.add_argument("--momentum-projection-path", type=Path, required=True)
    parser.add_argument("--theme-projection-path", type=Path, required=True)
    parser.add_argument("--output-data-context-path", type=Path, default=DEFAULT_OUTPUT_DATA_CONTEXT_PATH)
    parser.add_argument("--source-artifact-prefix", type=Path, default=SOURCE_ARTIFACT_PREFIX)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_SAMPLE_ROOT)
    parser.add_argument("--generated-at")
    parser.add_argument("--observed-at")
    parser.add_argument("--theme-opportunity-state", default="strong")
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--run-data-context", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_live_source_packet(
        candidate_artifact_path=args.candidate_artifact_path,
        expected_decision_date=args.decision_date,
        selected_symbols=_parse_symbols(args.symbols),
        momentum_projection_path=args.momentum_projection_path,
        theme_projection_path=args.theme_projection_path,
        output_data_context_path=args.output_data_context_path,
        source_artifact_prefix=args.source_artifact_prefix,
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        confirm_user_authorization=args.confirm_user_authorization,
        run_data_context=args.run_data_context,
        generated_at=args.generated_at,
        observed_at=args.observed_at,
        theme_opportunity_state=args.theme_opportunity_state,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
