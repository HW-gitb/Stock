from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if PYTHON_LIBS.exists() and str(PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(PYTHON_LIBS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance  # noqa: E402
from runners import us_egs_sample_validation as sample_validation  # noqa: E402
from runners import us_short_universe_fetch as universe_fetch  # noqa: E402
from runners.us_short_batch5_momentum_price_source import PACKET_SCHEMA_PATH  # noqa: E402


AUTHORIZATION_REF = "user_chat_20260705_us_short_momentum_price_source_packet"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_batch5_momentum_price_source_packet_summary.schema.json"
SUMMARY_PATH = ROOT / "docs" / "us_short_batch5_momentum_price_source_packet_summary_20260705.json"
RAW_SAMPLE_REL_ROOT = Path("provider_samples/us_short_batch5_momentum_price_source_packet_20260705")
RAW_SAMPLE_ROOT = ROOT / RAW_SAMPLE_REL_ROOT / "raw"
STATE_US_SHORT_DIR = ROOT / "state" / "us_short"
ELIGIBILITY_GOVERNANCE_PATH = ROOT / "presets" / "us_short_eligibility_governance_20260624.json"
DEFAULT_CANDIDATE_ARTIFACT_PATH = STATE_US_SHORT_DIR / "candidate_universe_20260706.json"
DEFAULT_OUTPUT_SOURCE_PACKET_PATH = STATE_US_SHORT_DIR / "us_short_batch5_momentum_price_source_20260705_packet.json"

BENCHMARK_SYMBOLS = ("SPY", "QQQ")
MAX_SYMBOLS = 3
MAX_TOTAL_ENDPOINT_CALLS = MAX_SYMBOLS + len(BENCHMARK_SYMBOLS)
MIN_POINTS_PER_SERIES = 64
LOOKBACK_CALENDAR_DAYS = 140
MASSIVE_SLEEP_SECONDS = 13.0
MASSIVE_DAILY_AGGS_URL = (
    "https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day/{frm}/{to}"
    "?adjusted=true&sort=asc&limit=300&apiKey={key}"
)
ENDPOINT_FAMILY = "ticker_daily_aggregates_adjusted"


class MomentumPriceSourcePacketError(ValueError):
    """The bounded live momentum price-history source packet cannot be fetched or written safely."""


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
        raise MomentumPriceSourcePacketError(f"{field} must stay under the repository root") from exc
    return resolved


def _existing_file(path: Path | str, *, field: str) -> Path:
    resolved = _resolve_repo_path(path, field=field)
    if not resolved.exists() or not resolved.is_file():
        raise MomentumPriceSourcePacketError(f"{field} must be an existing file: {_display_path(resolved)}")
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
        raise MomentumPriceSourcePacketError(f"{field} must stay under state/us_short/") from exc
    if resolved.suffix != ".json":
        raise MomentumPriceSourcePacketError(f"{field} must be a .json path")
    if must_exist and (not resolved.exists() or not resolved.is_file()):
        raise MomentumPriceSourcePacketError(f"{field} must be an existing file: {_display_path(resolved)}")
    if not _git_ignored(resolved):
        raise MomentumPriceSourcePacketError(f"{field} must be gitignored")
    return resolved


def _validate_summary_path(path: Path | str) -> Path:
    resolved = _resolve_repo_path(path, field="summary_path")
    if resolved.suffix != ".json":
        raise MomentumPriceSourcePacketError("summary_path must be a .json path")
    if resolved == SUMMARY_PATH.resolve():
        return resolved
    try:
        resolved.relative_to((ROOT / RAW_SAMPLE_REL_ROOT).resolve())
    except ValueError as exc:
        raise MomentumPriceSourcePacketError(
            "summary_path must be the canonical tracked summary or under this runner's provider_samples folder"
        ) from exc
    if not _git_ignored(resolved):
        raise MomentumPriceSourcePacketError("non-canonical summary_path must be gitignored")
    return resolved


def _validate_raw_root(raw_root: Path | str) -> Path:
    resolved = _resolve_repo_path(raw_root, field="raw_root")
    approved = (ROOT / RAW_SAMPLE_REL_ROOT).resolve()
    try:
        resolved.relative_to(approved)
    except ValueError as exc:
        raise MomentumPriceSourcePacketError(
            "raw_root must stay under provider_samples/us_short_batch5_momentum_price_source_packet_20260705/"
        ) from exc
    try:
        sample_validation.validate_raw_root(resolved)
    except ValueError as exc:
        raise MomentumPriceSourcePacketError(str(exc)) from exc
    if not _git_ignored(resolved):
        raise MomentumPriceSourcePacketError("raw_root must be gitignored")
    return resolved


def _prepare_json_target(path: Path, *, field: str) -> None:
    if path.parent.exists() and not path.parent.is_dir():
        raise MomentumPriceSourcePacketError(f"{field} parent must be a directory: {_display_path(path.parent)}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MomentumPriceSourcePacketError(f"{field} parent could not be created: {_display_path(path.parent)}") from exc
    if path.exists() and path.is_dir():
        raise MomentumPriceSourcePacketError(f"{field} must be a file path, not a directory: {_display_path(path)}")


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
        raise MomentumPriceSourcePacketError(f"{field} could not be written atomically: {_display_path(path)}") from exc


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
        raise MomentumPriceSourcePacketError(f"{field} must be ASCII YYYYMMDD")
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError as exc:
        raise MomentumPriceSourcePacketError(f"{field} must be a real calendar date") from exc


def _ymd(value: str, *, field: str):
    if type(value) is not str or len(value) != 10:
        raise MomentumPriceSourcePacketError(f"{field} must be YYYY-MM-DD")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise MomentumPriceSourcePacketError(f"{field} must be a real calendar date") from exc


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
        raise MomentumPriceSourcePacketError("jsonschema is required for price-source packet validation") from exc
    schema = _read_json(schema_path)
    errors = sorted(Draft7Validator(schema).iter_errors(payload), key=lambda error: list(error.path))
    if errors:
        joined = "; ".join(error.message for error in errors[:5])
        raise MomentumPriceSourcePacketError(f"{label} schema rejected {len(errors)} field(s): {joined}") from errors[0]


def _selected_symbols(value: list[str] | tuple[str, ...]) -> list[str]:
    if type(value) not in (list, tuple) or not value or len(value) > MAX_SYMBOLS:
        raise MomentumPriceSourcePacketError("selected_symbols must be a 1-3 item list/tuple")
    out: list[str] = []
    seen: set[str] = set()
    for raw in value:
        if type(raw) is not str:
            raise MomentumPriceSourcePacketError("selected_symbols must contain exact strings")
        ticker = canonical_us_ticker(raw)
        if ticker is None:
            raise MomentumPriceSourcePacketError("selected_symbols must be canonicalizable US tickers")
        if ticker in BENCHMARK_SYMBOLS:
            raise MomentumPriceSourcePacketError("selected_symbols may not include benchmark symbols SPY/QQQ")
        if ticker in seen:
            raise MomentumPriceSourcePacketError(f"duplicate selected symbol: {ticker}")
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
        raise MomentumPriceSourcePacketError(f"candidate artifact failed validation: {exc}") from exc
    rows_by_ticker = {row["ticker"]: row for row in artifact["rows"]}
    eligible = set(artifact["eligible_tickers"])
    missing = [ticker for ticker in selected_symbols if ticker not in rows_by_ticker]
    not_eligible = [ticker for ticker in selected_symbols if ticker not in eligible]
    if missing or not_eligible:
        raise MomentumPriceSourcePacketError(
            f"selected_symbols must exist and be Pass1-eligible (missing {missing}, not_eligible {not_eligible})"
        )
    compact_price_basis = artifact["price_basis_date"]
    price_basis_ymd = _date8_to_ymd(compact_price_basis, field="candidate.price_basis_date")
    return {
        "expected_decision_date": artifact["decision_date"],
        "candidate_price_basis_date": compact_price_basis,
        "price_basis_date": price_basis_ymd,
        "source_as_of": price_basis_ymd,
        "row_count": len(artifact["rows"]),
        "eligible_count": len(artifact["eligible_tickers"]),
    }


def _massive_url(*, ticker: str, source_as_of: str, lookback_calendar_days: int, api_key: str) -> str:
    to_date = _ymd(source_as_of, field="source_as_of")
    frm = (to_date - timedelta(days=lookback_calendar_days)).isoformat()
    safe_ticker = urllib.parse.quote(ticker, safe="")
    return MASSIVE_DAILY_AGGS_URL.format(ticker=safe_ticker, frm=frm, to=source_as_of, key=api_key)


def _fetch_records(
    *,
    required_symbols: list[str],
    source_as_of: str,
    raw_root: Path,
    client: sample_validation.JsonHttpClient,
    massive_env: sample_validation.EnvValue,
    lookback_calendar_days: int,
    massive_sleep_seconds: float,
) -> list[sample_validation.FetchRecord]:
    records: list[sample_validation.FetchRecord] = []
    headers = {"User-Agent": "StockSystem/0.1 us-short-batch5-momentum-price-source-packet"}
    for idx, ticker in enumerate(required_symbols):
        if idx > 0 and massive_sleep_seconds > 0:
            time.sleep(massive_sleep_seconds)
        try:
            sample_validation.assert_endpoint_budget_available(records, MAX_TOTAL_ENDPOINT_CALLS)
        except RuntimeError as exc:
            raise MomentumPriceSourcePacketError(str(exc)) from exc
        records.append(
            sample_validation.fetch_and_store(
                client,
                url=_massive_url(
                    ticker=ticker,
                    source_as_of=source_as_of,
                    lookback_calendar_days=lookback_calendar_days,
                    api_key=massive_env.value,
                ),
                provider_id="massive",
                endpoint_family=ENDPOINT_FAMILY,
                symbol=ticker,
                raw_root=raw_root,
                headers=headers,
            )
        )
    return records


def _point_from_raw(*, ticker: str, raw: dict[str, Any], source_as_of: str) -> dict[str, Any]:
    timestamp = _finite_number(raw.get("t"))
    close = _finite_number(raw.get("c"))
    raw_volume = raw.get("v")
    volume = _finite_number(raw_volume) if raw_volume is not None else None
    if timestamp is None:
        raise MomentumPriceSourcePacketError(f"{ticker} Massive aggregate row is missing finite timestamp")
    if close is None or close <= 0.0:
        raise MomentumPriceSourcePacketError(f"{ticker} Massive aggregate row close must be finite and positive")
    if raw_volume is not None and volume is None:
        raise MomentumPriceSourcePacketError(f"{ticker} Massive aggregate row volume must be finite when present")
    if volume is not None and volume < 0.0:
        raise MomentumPriceSourcePacketError(f"{ticker} Massive aggregate row volume must be non-negative")
    try:
        date_value = datetime.fromtimestamp(timestamp / 1000.0, timezone.utc).date()
    except (OverflowError, OSError, ValueError) as exc:
        raise MomentumPriceSourcePacketError(f"{ticker} Massive aggregate row timestamp is out of range") from exc
    if date_value > _ymd(source_as_of, field="source_as_of"):
        raise MomentumPriceSourcePacketError(f"{ticker} Massive aggregate row is after source_as_of")
    point = {"date": date_value.isoformat(), "close": close}
    if volume is not None:
        point["volume"] = volume
    return point


def _series_from_record(
    *,
    ticker: str,
    record: sample_validation.FetchRecord,
    source_as_of: str,
    min_points_per_series: int,
) -> dict[str, Any]:
    if not record.ok:
        raise MomentumPriceSourcePacketError(
            f"{ticker} Massive daily aggregates fetch failed: status={record.http_status} error={record.error_type}"
        )
    payload = record.payload
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise MomentumPriceSourcePacketError(f"{ticker} Massive daily aggregates payload must contain results[]")
    points_by_date: dict[str, dict[str, Any]] = {}
    for raw in payload["results"]:
        if not isinstance(raw, dict):
            raise MomentumPriceSourcePacketError(f"{ticker} Massive aggregate row must be an object")
        point = _point_from_raw(ticker=ticker, raw=raw, source_as_of=source_as_of)
        if point["date"] in points_by_date:
            raise MomentumPriceSourcePacketError(f"{ticker} Massive aggregate rows contain duplicate date")
        points_by_date[point["date"]] = point
    points = [points_by_date[date] for date in sorted(points_by_date)]
    if len(points) < min_points_per_series:
        raise MomentumPriceSourcePacketError(
            f"{ticker} Massive daily aggregates returned fewer than {min_points_per_series} usable bars"
        )
    if points[-1]["date"] != source_as_of:
        raise MomentumPriceSourcePacketError(f"{ticker} latest Massive bar must equal source_as_of")
    return {
        "as_of": source_as_of,
        "session": "RTH",
        "adjustment_mode": "split_div_adjusted",
        "points": points,
    }


def _record_by_symbol(records: list[sample_validation.FetchRecord]) -> dict[str, sample_validation.FetchRecord]:
    out: dict[str, sample_validation.FetchRecord] = {}
    for record in records:
        if record.symbol is None:
            continue
        if record.symbol in out:
            raise MomentumPriceSourcePacketError(f"duplicate endpoint record for {record.symbol}")
        out[record.symbol] = record
    return out


def _build_packet(
    *,
    generated_at: str,
    observed_at: str,
    selected_symbols: list[str],
    candidate_context: dict[str, Any],
    records: list[sample_validation.FetchRecord],
    min_points_per_series: int,
) -> dict[str, Any]:
    required_symbols = selected_symbols + list(BENCHMARK_SYMBOLS)
    by_symbol = _record_by_symbol(records)
    missing = [symbol for symbol in required_symbols if symbol not in by_symbol]
    if missing:
        raise MomentumPriceSourcePacketError(f"missing Massive endpoint records for {missing}")
    series_by_ticker = {
        symbol: _series_from_record(
            ticker=symbol,
            record=by_symbol[symbol],
            source_as_of=candidate_context["source_as_of"],
            min_points_per_series=min_points_per_series,
        )
        for symbol in required_symbols
    }
    provenance_by_ticker = {
        symbol: {
            "provider_id": "massive",
            "endpoint_or_family": ENDPOINT_FAMILY,
            "source_as_of": candidate_context["source_as_of"],
            "observed_at": observed_at,
            "coverage_status": "full",
            "parser_status": "ok",
            "lineage_ref": f"massive:{ENDPOINT_FAMILY}:{candidate_context['source_as_of']}#{symbol.lower()}",
        }
        for symbol in required_symbols
    }
    packet = {
        "schema_name": "us_short_batch5_momentum_price_source_packet",
        "schema_version": "1.0.0",
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "lane": "us_short",
            "batch": "batch5_provider_live",
            "packet_status": "price_history_source_packet_ready_for_local_momentum_projection",
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
        "series_contract": {
            "symbol_source": "caller_selected_from_validated_candidate_artifact",
            "selected_symbols": selected_symbols,
            "benchmark_symbols": list(BENCHMARK_SYMBOLS),
            "session": "RTH",
            "adjustment_mode": "split_div_adjusted",
            "min_points_per_series": min_points_per_series,
            "full_market_sample": False,
        },
        "series_by_ticker": series_by_ticker,
        "provenance_by_ticker": provenance_by_ticker,
        "preflight_gates": {
            "local_files_only": True,
            "candidate_artifact_must_match_price_basis": True,
            "selected_symbols_must_be_pass1_eligible": True,
            "benchmarks_required": True,
            "output_must_be_gitignored": True,
            "no_provider_fetch_by_runner": True,
            "no_datahub_or_production": True,
        },
        "prohibited_claims": {
            "provider_selection_complete": False,
            "full_market_download_performed": False,
            "yfinance_used": False,
            "live_normalized_evidence": False,
            "ship_gate_evidence": False,
            "production_ready": False,
            "datahub_consumed": False,
        },
    }
    _validate_schema(packet, PACKET_SCHEMA_PATH, label="momentum price source packet")
    return packet


def _payload_shape(record: sample_validation.FetchRecord) -> dict[str, Any]:
    payload = record.payload
    if isinstance(payload, dict):
        rows = payload.get("results")
        return {
            "kind": "object_results" if isinstance(rows, list) else "object",
            "row_count": len(rows) if isinstance(rows, list) else None,
        }
    if isinstance(payload, list):
        return {"kind": "list", "row_count": len(payload)}
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
    selected_symbols: list[str],
    candidate_context: dict[str, Any],
    records: list[sample_validation.FetchRecord],
    raw_root: Path,
    source_packet_path: Path,
    summary_path: Path,
    massive_env: sample_validation.EnvValue,
    packet: dict[str, Any],
    min_points_per_series: int,
    lookback_calendar_days: int,
) -> dict[str, Any]:
    endpoint_errors = sum(1 for record in records if not record.ok)
    bar_counts_by_ticker = {
        ticker: len(series["points"])
        for ticker, series in packet["series_by_ticker"].items()
    }
    latest_bar_by_ticker = {
        ticker: series["points"][-1]["date"]
        for ticker, series in packet["series_by_ticker"].items()
    }
    earliest_bar_by_ticker = {
        ticker: series["points"][0]["date"]
        for ticker, series in packet["series_by_ticker"].items()
    }
    return {
        "schema_name": "us_short_batch5_momentum_price_source_packet_summary",
        "schema_version": "1.0.0",
        "schema_ref": "schemas/us_short_batch5_momentum_price_source_packet_summary.schema.json",
        "authorization_ref": AUTHORIZATION_REF,
        "generated_at": generated_at,
        "scope": {
            "market": "US",
            "route": "US-short",
            "batch": "batch5",
            "purpose": "bounded_momentum_price_history_source_packet",
            "status": "price_history_source_packet_written",
            "network_access_performed": True,
            "provider_calls_performed": True,
            "raw_payload_storage_performed": True,
            "source_packet_written": True,
            "momentum_projection_written_by_this_runner": False,
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
            "massive_api_key_present": True,
            "massive_api_key_source": massive_env.source,
            "environment_values_logged": False,
            "secrets_logged": False,
        },
        "sample_universe": {
            "symbol_source": "caller_selected_from_validated_candidate_artifact",
            "symbols": selected_symbols,
            "max_symbols": MAX_SYMBOLS,
            "benchmark_symbols": list(BENCHMARK_SYMBOLS),
            "full_market_sample": False,
            "candidate_artifact_row_count": candidate_context["row_count"],
            "candidate_artifact_eligible_count": candidate_context["eligible_count"],
        },
        "endpoint_call_budget": {
            "max_total_endpoint_calls": MAX_TOTAL_ENDPOINT_CALLS,
            "actual_total_endpoint_calls": len(records),
            "endpoint_error_count": endpoint_errors,
            "within_budget": len(records) <= MAX_TOTAL_ENDPOINT_CALLS,
        },
        "endpoint_results": [_summarize_endpoint(record) for record in records],
        "storage": {
            "raw_payload_root": _repo_rel(raw_root),
            "raw_payload_root_gitignored": True,
            "source_packet_path": _repo_rel(source_packet_path),
            "source_packet_path_gitignored": _git_ignored(source_packet_path),
            "tracked_summary_path": _repo_rel(summary_path),
            "tracked_summary_contains_price_rows": False,
            "tracked_summary_contains_raw_payload": False,
            "tracked_summary_contains_request_urls": False,
            "tracked_summary_contains_secrets": False,
        },
        "price_packet": {
            "schema_ref": "schemas/us_short_batch5_momentum_price_source_packet.schema.json",
            "provider_ids": ["massive"],
            "endpoint_family": ENDPOINT_FAMILY,
            "series_count": len(packet["series_by_ticker"]),
            "selected_series_count": len(selected_symbols),
            "benchmark_symbols": list(BENCHMARK_SYMBOLS),
            "session": "RTH",
            "adjustment_mode": "split_div_adjusted",
            "min_points_per_series": min_points_per_series,
            "lookback_calendar_days": lookback_calendar_days,
            "bar_counts_by_ticker": bar_counts_by_ticker,
            "earliest_bar_by_ticker": earliest_bar_by_ticker,
            "latest_bar_by_ticker": latest_bar_by_ticker,
            "corporate_action_reconciliation_performed": False,
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
            "This is a bounded per-ticker price-history packet for <=3 selected symbols plus SPY/QQQ, not a full-market fetch.",
            "Raw provider payloads stay under gitignored provider_samples; tracked summary excludes request URLs, raw rows, and secrets.",
            "The packet is shaped for the existing local momentum projection runner; this runner does not write the projection.",
            "Corporate-action reconciliation, broader provider health/fallback, theme/GICS, DataHub, production, and ship-gate evidence remain out of scope.",
        ],
    }


def _assert_text_safe(text: str, sensitive_values: list[str]) -> None:
    lower = text.lower()
    forbidden = (
        "apikey=",
        "api.massive.com",
        "financialmodelingprep.com",
        "data.sec.gov",
        "www.sec.gov",
        "bearer ",
        "token=",
        "http://",
        "https://",
        "akia",
        "\"payload\"",
        "\"raw_payload\"",
        "\"request_url\"",
        "\"points\"",
        "\"results\"",
    )
    for fragment in forbidden:
        if fragment in lower:
            raise MomentumPriceSourcePacketError(f"summary contains forbidden fragment: {fragment}")
    for value in sensitive_values:
        if value and value in text:
            raise MomentumPriceSourcePacketError("summary contains a sensitive environment value")


def _write_summary_validated(summary: dict[str, Any], summary_path: Path, sensitive_values: list[str]) -> None:
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="momentum price source packet summary")
    text = json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    _assert_text_safe(text, sensitive_values)
    _write_json_atomic(summary, summary_path, field="summary_path")


def run_price_source_packet(
    *,
    candidate_artifact_path: Path = DEFAULT_CANDIDATE_ARTIFACT_PATH,
    expected_decision_date: str,
    selected_symbols: list[str],
    output_source_packet_path: Path = DEFAULT_OUTPUT_SOURCE_PACKET_PATH,
    summary_path: Path = SUMMARY_PATH,
    raw_root: Path = RAW_SAMPLE_ROOT,
    client: sample_validation.JsonHttpClient | None = None,
    confirm_user_authorization: bool = False,
    generated_at: str | None = None,
    observed_at: str | None = None,
    min_points_per_series: int = MIN_POINTS_PER_SERIES,
    lookback_calendar_days: int = LOOKBACK_CALENDAR_DAYS,
    massive_sleep_seconds: float = MASSIVE_SLEEP_SECONDS,
) -> dict[str, Any]:
    if not confirm_user_authorization:
        raise MomentumPriceSourcePacketError("live price-source packet execution requires explicit user authorization")
    generated_at = generated_at or iso_now()
    observed_at = observed_at or generated_at
    if not _valid_observed_at(generated_at) or not _valid_observed_at(observed_at):
        raise MomentumPriceSourcePacketError("generated_at and observed_at must be timezone-aware RFC3339 instants")
    if min_points_per_series < MIN_POINTS_PER_SERIES:
        raise MomentumPriceSourcePacketError(f"min_points_per_series must be >= {MIN_POINTS_PER_SERIES}")
    if lookback_calendar_days < 90:
        raise MomentumPriceSourcePacketError("lookback_calendar_days must be at least 90")
    if massive_sleep_seconds < 0:
        raise MomentumPriceSourcePacketError("massive_sleep_seconds must be non-negative")

    _date8_to_ymd(expected_decision_date, field="expected_decision_date")
    symbols = _selected_symbols(selected_symbols)
    candidate_path = _existing_file(candidate_artifact_path, field="candidate_artifact_path")
    output_path = _validate_state_json_path(output_source_packet_path, field="output_source_packet_path")
    summary_resolved = _validate_summary_path(summary_path)
    raw_resolved = _validate_raw_root(raw_root)
    candidate_ctx = _candidate_context(
        candidate_artifact_path=candidate_path,
        expected_decision_date=expected_decision_date,
        selected_symbols=symbols,
    )
    massive_env = sample_validation.read_required_env("MASSIVE_API_KEY")

    _prepare_json_target(output_path, field="output_source_packet_path")
    _prepare_json_target(summary_resolved, field="summary_path")

    client = client or sample_validation.JsonHttpClient()
    required_symbols = symbols + list(BENCHMARK_SYMBOLS)
    records = _fetch_records(
        required_symbols=required_symbols,
        source_as_of=candidate_ctx["source_as_of"],
        raw_root=raw_resolved,
        client=client,
        massive_env=massive_env,
        lookback_calendar_days=lookback_calendar_days,
        massive_sleep_seconds=massive_sleep_seconds,
    )
    packet = _build_packet(
        generated_at=generated_at,
        observed_at=observed_at,
        selected_symbols=symbols,
        candidate_context=candidate_ctx,
        records=records,
        min_points_per_series=min_points_per_series,
    )
    summary = _build_summary(
        generated_at=generated_at,
        selected_symbols=symbols,
        candidate_context=candidate_ctx,
        records=records,
        raw_root=raw_resolved,
        source_packet_path=output_path,
        summary_path=summary_resolved,
        massive_env=massive_env,
        packet=packet,
        min_points_per_series=min_points_per_series,
        lookback_calendar_days=lookback_calendar_days,
    )
    _validate_schema(summary, SUMMARY_SCHEMA_PATH, label="momentum price source packet summary")
    _assert_text_safe(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", [massive_env.value])
    _write_json_atomic(packet, output_path, field="output_source_packet_path")
    _write_summary_validated(summary, summary_resolved, [massive_env.value])
    return summary


def _parse_symbols(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build an authorized bounded US-short Batch5 momentum price-history source packet from Massive "
            "per-ticker daily aggregates. This runner writes raw payloads only under provider_samples and never "
            "uses DataHub, production storage, yfinance, broker/order automation, or A-share paths."
        )
    )
    parser.add_argument("--candidate-artifact-path", type=Path, default=DEFAULT_CANDIDATE_ARTIFACT_PATH)
    parser.add_argument("--decision-date", required=True, help="Expected decision date as YYYYMMDD.")
    parser.add_argument("--symbols", default="AAPL,MSFT,JPM", help="Comma-separated <=3 active eligible tickers.")
    parser.add_argument("--output-source-packet-path", type=Path, default=DEFAULT_OUTPUT_SOURCE_PACKET_PATH)
    parser.add_argument("--summary-path", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--raw-root", type=Path, default=RAW_SAMPLE_ROOT)
    parser.add_argument("--generated-at")
    parser.add_argument("--observed-at")
    parser.add_argument("--min-points-per-series", type=int, default=MIN_POINTS_PER_SERIES)
    parser.add_argument("--lookback-calendar-days", type=int, default=LOOKBACK_CALENDAR_DAYS)
    parser.add_argument("--massive-sleep-seconds", type=float, default=MASSIVE_SLEEP_SECONDS)
    parser.add_argument("--confirm-user-authorization", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_price_source_packet(
        candidate_artifact_path=args.candidate_artifact_path,
        expected_decision_date=args.decision_date,
        selected_symbols=_parse_symbols(args.symbols),
        output_source_packet_path=args.output_source_packet_path,
        summary_path=args.summary_path,
        raw_root=args.raw_root,
        confirm_user_authorization=args.confirm_user_authorization,
        generated_at=args.generated_at,
        observed_at=args.observed_at,
        min_points_per_series=args.min_points_per_series,
        lookback_calendar_days=args.lookback_calendar_days,
        massive_sleep_seconds=args.massive_sleep_seconds,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
