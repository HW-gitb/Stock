from __future__ import annotations

import argparse
import json
import math
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

from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance  # noqa: E402
from engine.us_short_seam_theme import DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE  # noqa: E402
from runners import us_egs_sample_validation as sample_validation  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402
from runners.us_short_batch5_momentum_price_source import PACKET_SCHEMA_PATH as PRICE_PACKET_SCHEMA_PATH  # noqa: E402


AUTHORIZATION_REF = "user_chat_20260705_us_short_theme_gics_source"
PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_theme_gics_source_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_theme_gics_source_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_theme_gics_source_summary_20260705.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_theme_gics_source_20260705")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
DEFAULT_PRICE_SOURCE_PACKET_PATH = STATE_US_SHORT_DIR / "us_short_batch5_momentum_price_source_20260705_packet.json"
DEFAULT_OUTPUT_SOURCE_PACKET_PATH = STATE_US_SHORT_DIR / "us_short_batch5_theme_gics_source_20260705_packet.json"
DEFAULT_OUTPUT_THEME_PROJECTION_PATH = STATE_US_SHORT_DIR / "us_short_batch5_theme_gics_source_20260705_theme.json"
ENDPOINT_FAMILY = "profile_or_company_metadata"
MEMBERSHIP_POOL_BASIS = "selected_symbols_only_not_full_gics_peer_pool"
MAX_SYMBOLS = 3


class ThemeGicsSourceError(ValueError):
    """The bounded theme/GICS membership source packet cannot be fetched or written safely."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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
        raise ThemeGicsSourceError(f"{field} must stay under the repository root") from exc
    return resolved


def _existing_file(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    if not resolved.exists() or not resolved.is_file():
        raise ThemeGicsSourceError(f"{field} must be an existing file: {_display_path(resolved)}")
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


def _validate_state_json_path(path: Path | str, *, field: str, must_exist: bool = False) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    try:
        resolved.parent.relative_to(STATE_US_SHORT_DIR.resolve())
    except ValueError as exc:
        raise ThemeGicsSourceError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise ThemeGicsSourceError(f"{field} must be a .json path")
    if must_exist and (not resolved.exists() or not resolved.is_file()):
        raise ThemeGicsSourceError(f"{field} must be an existing file: {_display_path(resolved)}")
    if not _git_ignored(resolved):
        raise ThemeGicsSourceError(f"{field} must be gitignored")
    return resolved


def _validate_summary_path(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="summary_path")
    if resolved.suffix != ".json":
        raise ThemeGicsSourceError("summary_path must be a .json path")
    if resolved == SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / RAW_SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise ThemeGicsSourceError(
            "summary_path must be the canonical tracked summary or under this runner's provider_samples folder"
        ) from exc
    if not _git_ignored(resolved):
        raise ThemeGicsSourceError("non-canonical summary_path must be gitignored")
    return resolved


def _validate_raw_root(raw_root: Path | str) -> Path:
    resolved = _resolve_repo_path(raw_root, field="raw_root")
    approved = (ROOT / RAW_SAMPLE_REL_ROOT).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise ThemeGicsSourceError(
            "raw_root must stay under provider_samples/us_short_batch5_theme_gics_source_20260705/"
        ) from exc
    try:
        sample_validation.validate_raw_root(resolved)
    except ValueError as exc:
        raise ThemeGicsSourceError(str(exc)) from exc
    if not _git_ignored(resolved):
        raise ThemeGicsSourceError("raw_root must be gitignored")
    return resolved


def _prepare_json_target(path: Path, *, field: str) -> None:
    if path.parent.exists() and not path.parent.is_dir():
        raise ThemeGicsSourceError(f"{field} parent must be a directory: {_display_path(path.parent)}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ThemeGicsSourceError(f"{field} parent could not be created: {_display_path(path.parent)}") from exc
    if path.exists() and path.is_dir():
        raise ThemeGicsSourceError(f"{field} must be a file path, not a directory: {_display_path(path)}")


def _write_json_atomic(payload: Any, path: Path, *, field: str) -> None:
    _prepare_json_target(path, field=field)
    tmp = path.with_name(f"{path.name}.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ThemeGicsSourceError(f"{field} could not be written atomically: {_display_path(path)}") from exc


def _valid_observed_at(value: str) -> bool:
    if not (type(value) is str and "T" in value):
        return False
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return False
    return dt.tzinfo is not None


def _date8_to_ymd(value: str, *, field: str) -> str:
    if type(value) is not str or len(value) != 8 or not value.isascii() or not value.isdigit():
        raise ThemeGicsSourceError(f"{field} must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise ThemeGicsSourceError(f"{field} must be a real calendar date") from exc


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        x = float(value)
    except (OverflowError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _validate_schema(payload: Any, schema_path: Path, *, label: str) -> None:
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:
        raise ThemeGicsSourceError("jsonschema is required for theme/GICS source validation") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise ThemeGicsSourceError(f"{label} schema rejected {len(errors)} field(s): {joined}") from errors[0]


def _selected_symbols(value: list[str] | tuple[str, ...]) -> list[str]:
    if type(value) not in (list, tuple) or not value or len(value) > MAX_SYMBOLS:
        raise ThemeGicsSourceError("selected_symbols must be a 1-3 item list/tuple")
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if type(raw) is not str:
            raise ThemeGicsSourceError("selected_symbols must contain exact strings")
        ticker = canonical_us_ticker(raw)
        if ticker is None:
            raise ThemeGicsSourceError("selected_symbols must be canonicalizable US tickers")
        if ticker in seen:
            raise ThemeGicsSourceError(f"duplicate selected symbol: {ticker}")
        seen.add(ticker)
        out.append(ticker)
    return out


def _candidate_context(
    *,
    candidate_artifact_path: Path,
    expected_decision_date: str,
    selected_symbols: list[str],
) -> dict[str, Any]:
    artifact = _read_json(candidate_artifact_path)
    governance = load_eligibility_governance(ELIGIBILITY_GOVERNANCE_PATH)
    try:
        universe_fetch.validate_candidate_artifact(
            artifact,
            expected_decision_date=expected_decision_date,
            governance=governance,
        )
    except Exception as exc:
        raise ThemeGicsSourceError(f"candidate artifact failed validation: {exc}") from exc
    rows_by_ticker = {row["ticker"]: row for row in artifact["rows"]}
    eligible = set(artifact["eligible_tickers"])
    missing = [ticker for ticker in selected_symbols if ticker not in rows_by_ticker]
    not_eligible = [ticker for ticker in selected_symbols if ticker not in eligible]
    if missing or not_eligible:
        raise ThemeGicsSourceError(
            f"selected_symbols must exist and be Pass1-eligible (missing {missing}, not_eligible {not_eligible})"
        )
    price_basis_ymd = _date8_to_ymd(artifact["price_basis_date"], field="candidate.price_basis_date")
    return {
        "expected_decision_date": artifact["decision_date"],
        "candidate_price_basis_date": artifact["price_basis_date"],
        "price_basis_date": price_basis_ymd,
        "source_as_of": price_basis_ymd,
        "row_count": len(artifact["rows"]),
        "eligible_count": len(artifact["eligible_tickers"]),
    }


def _price_packet_context(
    *,
    price_source_packet_path: Path,
    candidate_context: dict[str, Any],
    selected_symbols: list[str],
) -> dict[str, Any]:
    packet = _read_json(price_source_packet_path)
    _validate_schema(packet, PRICE_PACKET_SCHEMA_PATH, label="momentum price source packet")
    clock = packet["decision_clock"]
    if clock != {
        "expected_decision_date": candidate_context["expected_decision_date"],
        "candidate_price_basis_date": candidate_context["candidate_price_basis_date"],
        "price_basis_date": candidate_context["price_basis_date"],
        "source_as_of": candidate_context["source_as_of"],
    }:
        raise ThemeGicsSourceError("price source packet decision_clock must match candidate artifact")
    packet_symbols = _selected_symbols(packet["series_contract"]["selected_symbols"])
    missing_from_packet = [ticker for ticker in selected_symbols if ticker not in packet_symbols]
    if missing_from_packet:
        raise ThemeGicsSourceError(
            f"selected_symbols must be present in the local momentum price source packet: {missing_from_packet}"
        )
    if packet["series_contract"]["benchmark_symbols"] != ["SPY", "QQQ"]:
        raise ThemeGicsSourceError("price source packet benchmark_symbols must be SPY/QQQ")
    return {"packet_symbols": packet_symbols}


def _fetch_profile_records(
    *,
    selected_symbols: list[str],
    raw_root: Path,
    client: sample_validation.JsonHttpClient,
    fmp_env: sample_validation.EnvValue,
) -> list[sample_validation.FetchRecord]:
    records: list[sample_validation.FetchRecord] = []
    headers = {"User-Agent": "StockSystem/0.1 us-short-batch5-theme-gics-source"}
    for ticker in selected_symbols:
        try:
            sample_validation.assert_endpoint_budget_available(records, MAX_SYMBOLS)
        except RuntimeError as exc:
            raise ThemeGicsSourceError(str(exc)) from exc
        url = sample_validation.fmp_url(
            "profile",
            ticker,
            {},
            fmp_env.value,
            endpoint_mode="stable",
        )
        payload, http_status, ok, error_type = client.get_json(url, headers=headers)
        raw_path = raw_root / f"fmp_profile_{ticker}.json"
        _write_json_atomic(
            {
                "provider_id": "financial_modeling_prep",
                "endpoint_family": ENDPOINT_FAMILY,
                "symbol": ticker,
                "http_status": http_status,
                "ok": ok,
                "error_type": error_type,
                "payload": payload,
            },
            raw_path,
            field="raw_profile_sample",
        )
        records.append(
            sample_validation.FetchRecord(
                provider_id="financial_modeling_prep",
                endpoint_family=ENDPOINT_FAMILY,
                symbol=ticker,
                raw_sample_ref=_repo_rel(raw_path),
                ok=ok,
                http_status=http_status,
                error_type=error_type,
                payload=payload,
            )
        )
    return records


def _payload_shape(record: sample_validation.FetchRecord) -> dict[str, Any]:
    payload = record.payload
    if isinstance(payload, list):
        return {"kind": "list", "row_count": len(payload)}
    if isinstance(payload, dict):
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


def _profile_row(record: sample_validation.FetchRecord) -> dict[str, Any]:
    ticker = record.symbol
    if ticker is None:
        raise ThemeGicsSourceError("FMP profile record is missing symbol")
    if not record.ok:
        raise ThemeGicsSourceError(
            f"{ticker} FMP profile fetch failed: status={record.http_status} error={record.error_type}"
        )
    payload = record.payload
    if isinstance(payload, list):
        if not payload or not isinstance(payload[0], dict):
            raise ThemeGicsSourceError(f"{ticker} FMP profile payload must contain an object row")
        row = payload[0]
    elif isinstance(payload, dict):
        row = payload
    else:
        raise ThemeGicsSourceError(f"{ticker} FMP profile payload must be a list or object")
    raw_symbol = row.get("symbol")
    if raw_symbol is not None and canonical_us_ticker(raw_symbol) != ticker:
        raise ThemeGicsSourceError(f"{ticker} FMP profile symbol mismatch")
    return row


def _required_label(row: dict[str, Any], *, ticker: str, field: str) -> str:
    value = row.get(field)
    if type(value) is not str:
        raise ThemeGicsSourceError(f"{ticker} FMP profile {field} must be a string")
    out = value.strip()
    if not out:
        raise ThemeGicsSourceError(f"{ticker} FMP profile {field} is missing")
    if len(out) > 160:
        raise ThemeGicsSourceError(f"{ticker} FMP profile {field} is too long")
    if any(fragment in out.lower() for fragment in ("http://", "https://", "apikey", "token", "bearer")):
        raise ThemeGicsSourceError(f"{ticker} FMP profile {field} contains unsafe text")
    return out


def _membership_from_record(record: sample_validation.FetchRecord) -> dict[str, Any]:
    ticker = record.symbol
    if ticker is None:
        raise ThemeGicsSourceError("FMP profile record is missing symbol")
    row = _profile_row(record)
    market_cap = _finite_number(row.get("marketCap"))
    if market_cap is not None and market_cap < 0.0:
        raise ThemeGicsSourceError(f"{ticker} FMP profile marketCap must be non-negative")
    return {
        "sector": _required_label(row, ticker=ticker, field="sector"),
        "industry": _required_label(row, ticker=ticker, field="industry"),
        "market_cap": market_cap,
    }


def _neutral_theme_projection(selected_symbols: list[str]) -> dict[str, Any]:
    return {
        "theme_block_by_ticker": {},
        "neutral_fill_tickers": list(selected_symbols),
        "coverage": {
            ticker: DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE
            for ticker in selected_symbols
        },
        "target_count": len(selected_symbols),
        "scored_count": 0,
    }


def _build_packet(
    *,
    generated_at: str,
    observed_at: str,
    selected_symbols: list[str],
    candidate_context: dict[str, Any],
    records: list[sample_validation.FetchRecord],
) -> dict[str, Any]:
    by_symbol = {record.symbol: record for record in records}
    missing = [ticker for ticker in selected_symbols if ticker not in by_symbol]
    if missing:
        raise ThemeGicsSourceError(f"missing FMP profile endpoint records for {missing}")
    membership = {
        ticker: _membership_from_record(by_symbol[ticker])
        for ticker in selected_symbols
    }
    packet = {
        "schema_name": "us_short_batch5_theme_gics_source_packet",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "packet_status": "selected_symbol_gics_membership_ready_for_neutral_projection_guard",
            "network_access_performed_by_packet_producer": True,
            "provider_calls_performed_by_packet_producer": True,
            "raw_payload_refs_gitignored": True,
            "datahub_consumption_allowed": False,
            "production_storage_allowed": False,
            "ship_gate_evidence_claimed": False,
            "broker_or_order_automation_allowed": False,
            "a_share_crossing_allowed": False,
        },
        "decision_clock": {
            "expected_decision_date": candidate_context["expected_decision_date"],
            "candidate_price_basis_date": candidate_context["candidate_price_basis_date"],
            "price_basis_date": candidate_context["price_basis_date"],
            "source_as_of": candidate_context["source_as_of"],
        },
        "membership_pool": {
            "symbol_source": "caller_selected_from_validated_candidate_artifact",
            "selected_symbols": selected_symbols,
            "membership_pool_basis": MEMBERSHIP_POOL_BASIS,
            "selected_symbols_only": True,
            "full_gics_peer_pool": False,
            "full_market_sample": False,
            "max_symbols": MAX_SYMBOLS,
        },
        "gics_membership_by_ticker": membership,
        "provenance_by_ticker": {
            ticker: {
                "provider_id": "financial_modeling_prep",
                "endpoint_or_family": ENDPOINT_FAMILY,
                "source_as_of": candidate_context["source_as_of"],
                "observed_at": observed_at,
                "coverage_status": "full",
                "parser_status": "ok",
                "lineage_ref": f"financial_modeling_prep:{ENDPOINT_FAMILY}:{candidate_context['source_as_of']}#{ticker.lower()}",
                "raw_sample_ref": by_symbol[ticker].raw_sample_ref,
            }
            for ticker in selected_symbols
        },
        "projection_guard": {
            "real_gics_membership_source_consumed": True,
            "full_gics_peer_pool_consumed": False,
            "industry_heat_scoring_allowed": False,
            "theme_scoring_allowed": False,
            "neutral_projection_required": True,
        },
        "prohibited_claims": {
            "provider_selection_complete": False,
            "full_market_download_performed": False,
            "full_gics_peer_pool_consumed": False,
            "industry_heat_scored": False,
            "theme_heat_scored": False,
            "yfinance_used": False,
            "live_normalized_evidence": False,
            "ship_gate_evidence": False,
            "production_ready": False,
            "datahub_consumed": False,
        },
    }
    _validate_schema(packet, PACKET_SCHEMA_PATH, label="theme/GICS source packet")
    return packet


def _build_summary(
    *,
    generated_at: str,
    selected_symbols: list[str],
    candidate_context: dict[str, Any],
    records: list[sample_validation.FetchRecord],
    raw_root: Path,
    source_packet_path: Path,
    theme_projection_path: Path,
    summary_path: Path,
    fmp_env: sample_validation.EnvValue,
    packet: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any]:
    endpoint_errors = sum(1 for record in records if not record.ok)
    return {
        "schema_name": "us_short_batch5_theme_gics_source_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_theme_gics_source_summary.schema.json",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "bounded_theme_gics_membership_source_packet",
            "status": "theme_gics_membership_packet_written",
            "network_access_performed": True,
            "provider_calls_performed": True,
            "raw_payload_storage_performed": True,
            "source_packet_written": True,
            "theme_projection_written": True,
            "datahub_consumption_performed": False,
            "production_storage_performed": False,
            "full_market_call_performed": False,
            "yfinance_consumption_performed": False,
            "broker_or_order_execution_performed": False,
            "ship_gate_or_live_normalized_evidence_claimed": False,
            "a_share_crossing_performed": False,
        },
        "decision_clock": {
            "expected_decision_date": candidate_context["expected_decision_date"],
            "candidate_price_basis_date": candidate_context["candidate_price_basis_date"],
            "price_basis_date": candidate_context["price_basis_date"],
            "source_as_of": candidate_context["source_as_of"],
        },
        "environment": {
            "fmp_api_key_present": True,
            "fmp_api_key_source": fmp_env.source,
            "environment_values_logged": False,
            "secrets_logged": False,
        },
        "sample_universe": {
            "symbol_source": "caller_selected_from_validated_candidate_artifact",
            "symbols": selected_symbols,
            "max_symbols": MAX_SYMBOLS,
            "full_market_sample": False,
            "candidate_artifact_row_count": candidate_context["row_count"],
            "candidate_artifact_eligible_count": candidate_context["eligible_count"],
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": MAX_SYMBOLS,
            "actual_total_endpoint_calls": len(records),
            "endpoint_error_count": endpoint_errors,
            "within_budget": len(records) <= MAX_SYMBOLS,
        },
        "endpoint_results": [_summarize_endpoint(record) for record in records],
        "storage": {
            "raw_payload_root": _repo_rel(raw_root),
            "raw_payload_root_gitignored": _git_ignored(raw_root),
            "source_packet_path": _repo_rel(source_packet_path),
            "source_packet_path_gitignored": _git_ignored(source_packet_path),
            "theme_projection_path": _repo_rel(theme_projection_path),
            "theme_projection_path_gitignored": _git_ignored(theme_projection_path),
            "tracked_summary_path": _repo_rel(summary_path),
            "tracked_summary_contains_raw_payload": False,
            "tracked_summary_contains_request_urls": False,
            "tracked_summary_contains_secrets": False,
        },
        "gics_source": {
            "schema_ref": "schemas/us_short_batch5_theme_gics_source_packet.schema.json",
            "provider_ids": ["financial_modeling_prep"],
            "endpoint_family": ENDPOINT_FAMILY,
            "membership_pool_basis": packet["membership_pool"]["membership_pool_basis"],
            "selected_symbols_only": True,
            "full_gics_peer_pool": False,
            "membership_resolved_count": len(packet["gics_membership_by_ticker"]),
            "membership_missing_count": 0,
            "sector_label_values_logged_in_summary": False,
            "industry_label_values_logged_in_summary": False,
        },
        "projection_contract": {
            "target_count": projection["target_count"],
            "theme_scored_count": projection["scored_count"],
            "neutral_fill_count": len(projection["neutral_fill_tickers"]),
            "real_gics_membership_source_consumed": True,
            "full_gics_peer_pool_consumed": False,
            "industry_heat_scoring_performed": False,
            "provisional_theme_heat_scoring_performed": False,
            "neutral_disposition": DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE,
        },
        "prohibited_claims": {
            "provider_selected": False,
            "full_market_download_performed": False,
            "full_gics_peer_pool_consumed": False,
            "industry_heat_scored": False,
            "theme_heat_scored": False,
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
            "This runner only fetches selected-symbol FMP stable profile membership rows.",
            "The selected-symbol membership packet is not a full GICS peer pool and must not score industry heat.",
            "The tracked summary excludes raw payloads, request URLs, sector labels, industry labels, and secrets.",
            "This narrows theme/GICS source wiring only; provider selection, DataHub, production, and ship-gate evidence remain out of scope.",
        ],
    }


def _assert_text_safe(text: str) -> None:
    lower = text.lower()
    forbidden = (
        "apikey=",
        "financialmodelingprep.com",
        "api.massive.com",
        "data.sec.gov",
        "www.sec.gov",
        "bearer ",
        "token=",
        "key=",
        "http://",
        "https://",
        "akia",
        "@",
        "\"payload\"",
        "\"raw_payload\"",
        "\"request_url\"",
    )
    for fragment in forbidden:
        if fragment in lower:
            raise ThemeGicsSourceError(f"summary contains forbidden fragment: {fragment}")


def _write_summary_validated(summary: dict[str, Any], summary_path: Path) -> None:
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="theme/GICS source summary")
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text)
    _write_json_atomic(summary, summary_path, field="summary_path")


def _validate_theme_projection(projection: dict[str, Any], selected_symbols: list[str]) -> None:
    if set(projection) != {"theme_block_by_ticker", "neutral_fill_tickers", "coverage", "target_count", "scored_count"}:
        raise ThemeGicsSourceError("theme projection keys drifted from the theme seam contract")
    if projection["theme_block_by_ticker"] != {}:
        raise ThemeGicsSourceError("selected-only GICS membership must not emit scored theme values")
    if projection["neutral_fill_tickers"] != selected_symbols:
        raise ThemeGicsSourceError("theme projection neutral_fill_tickers must equal selected_symbols")
    if projection["target_count"] != len(selected_symbols) or projection["scored_count"] != 0:
        raise ThemeGicsSourceError("theme projection counts must reflect an all-neutral selected-symbol projection")
    expected_coverage = {
        ticker: DISPOSITION_NEUTRAL_MISSING_THEME_AND_INDUSTRY_BASE
        for ticker in selected_symbols
    }
    if projection["coverage"] != expected_coverage:
        raise ThemeGicsSourceError("theme projection coverage must use the neutral missing-theme/industry disposition")


def run_theme_gics_source(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    price_source_packet_path: Path = DEFAULT_PRICE_SOURCE_PACKET_PATH,
    expected_decision_date: str,
    selected_symbols: list[str] | tuple[str, ...],
    output_source_packet_path: Path = DEFAULT_OUTPUT_SOURCE_PACKET_PATH,
    output_theme_projection_path: Path = DEFAULT_OUTPUT_THEME_PROJECTION_PATH,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    client: sample_validation.JsonHttpClient | None = None,
    confirm_user_authorization: bool = False,
    generated_at: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    if confirm_user_authorization is not True:
        raise ThemeGicsSourceError("confirm_user_authorization is required before provider fetch")
    generated_at = generated_at or iso_now()
    observed_at = observed_at or generated_at
    if not _valid_observed_at(generated_at):
        raise ThemeGicsSourceError("generated_at must be a timezone-aware RFC3339 instant")
    if not _valid_observed_at(observed_at):
        raise ThemeGicsSourceError("observed_at must be a timezone-aware RFC3339 instant")

    selected = _selected_symbols(selected_symbols)
    candidate_path = _existing_file(candidate_artifact_path, field="candidate_artifact_path")
    price_packet_path = _validate_state_json_path(
        price_source_packet_path,
        field="price_source_packet_path",
        must_exist=True,
    )
    source_packet_path = _validate_state_json_path(
        output_source_packet_path,
        field="output_source_packet_path",
        must_exist=False,
    )
    theme_projection_path = _validate_state_json_path(
        output_theme_projection_path,
        field="output_theme_projection_path",
        must_exist=False,
    )
    summary_resolved = _validate_summary_path(summary_path)
    raw_resolved = _validate_raw_root(raw_root)
    if source_packet_path in {candidate_path, price_packet_path, theme_projection_path}:
        raise ThemeGicsSourceError("output_source_packet_path must not overwrite an input or projection file")
    if theme_projection_path in {candidate_path, price_packet_path}:
        raise ThemeGicsSourceError("output_theme_projection_path must not overwrite an input file")
    if summary_resolved in {candidate_path, price_packet_path, source_packet_path, theme_projection_path}:
        raise ThemeGicsSourceError("summary_path must not overwrite input/output state files")

    candidate = _candidate_context(
        candidate_artifact_path=candidate_path,
        expected_decision_date=expected_decision_date,
        selected_symbols=selected,
    )
    _price_packet_context(
        price_source_packet_path=price_packet_path,
        candidate_context=candidate,
        selected_symbols=selected,
    )
    fmp_env = sample_validation.read_required_env("FMP_API_KEY")
    records = _fetch_profile_records(
        selected_symbols=selected,
        raw_root=raw_resolved,
        client=client or sample_validation.JsonHttpClient(),
        fmp_env=fmp_env,
    )
    packet = _build_packet(
        generated_at=generated_at,
        observed_at=observed_at,
        selected_symbols=selected,
        candidate_context=candidate,
        records=records,
    )
    projection = _neutral_theme_projection(selected)
    summary = _build_summary(
        generated_at=generated_at,
        selected_symbols=selected,
        candidate_context=candidate,
        records=records,
        raw_root=raw_resolved,
        source_packet_path=source_packet_path,
        theme_projection_path=theme_projection_path,
        summary_path=summary_resolved,
        fmp_env=fmp_env,
        packet=packet,
        projection=projection,
    )
    _validate_theme_projection(projection, selected)
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="theme/GICS source summary")
    _write_json_atomic(packet, source_packet_path, field="output_source_packet_path")
    _write_json_atomic(projection, theme_projection_path, field="output_theme_projection_path")
    _write_summary_validated(summary, summary_resolved)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build the authorized bounded US-short Batch5 selected-symbol FMP stable profile "
            "GICS membership packet and a neutral guarded theme projection."
        )
    )
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--price-source-packet-path", type=Path, default=DEFAULT_PRICE_SOURCE_PACKET_PATH)
    parser.add_argument("--decision-date", required=True, help="Expected decision date in YYYYMMDD.")
    parser.add_argument("--symbols", required=True, help="Comma-separated selected tickers, max 3.")
    parser.add_argument("--output-source-packet-path", type=Path, default=DEFAULT_OUTPUT_SOURCE_PACKET_PATH)
    parser.add_argument("--output-theme-projection-path", type=Path, default=DEFAULT_OUTPUT_THEME_PROJECTION_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_SAMPLE_ROOT)
    parser.add_argument("--generated-at")
    parser.add_argument("--observed-at")
    parser.add_argument("--confirm-user-authorization", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    symbols = [item.strip() for item in args.symbols.split(",") if item.strip()]
    summary = run_theme_gics_source(
        candidate_artifact_path=args.candidate_artifact_path,
        price_source_packet_path=args.price_source_packet_path,
        expected_decision_date=args.decision_date,
        selected_symbols=symbols,
        output_source_packet_path=args.output_source_packet_path,
        output_theme_projection_path=args.output_theme_projection_path,
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        confirm_user_authorization=args.confirm_user_authorization,
        generated_at=args.generated_at,
        observed_at=args.observed_at,
    )
    print(
        json.dumps(
            {
                "status": summary["scope"]["status"],
                "symbols": summary["sample_universe"]["symbols"],
                "membership_resolved_count": summary["gics_source"]["membership_resolved_count"],
                "theme_scored_count": summary["projection_contract"]["theme_scored_count"],
                "summary_path": summary["storage"]["tracked_summary_path"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
