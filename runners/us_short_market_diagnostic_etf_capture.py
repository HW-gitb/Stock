"""Bounded live capture for the US-short Knife5 ETF evidence segment.

This runner is deliberately separate from the week-aligned total-return sidecar.  It captures only the
four authorized ETFs and four Massive endpoint families, keeps raw responses private, and emits a
de-identified summary plus a private normalized metadata artifact.  It never creates a diagnostic week,
calculates a return, selects a provider, writes an account, or wires production consumption.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if _PYTHON_LIBS.exists() and str(_PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(_PYTHON_LIBS))

from runners import us_egs_sample_validation as sample_validation  # noqa: E402


PACKET_PATH = ROOT / "docs" / "us_short_market_diagnostic_etf_capture_packet_20260805.json"
PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_market_diagnostic_etf_capture_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_market_diagnostic_etf_capture_summary.schema.json"

AUTHORIZATION_REF = "user_chat_20260805_knife5_live_etf_total_return_fetch"
SYMBOLS = ("SPY", "QQQ", "IWB", "VTI")
FAMILIES = ("dividends", "splits", "daily_adjusted", "daily_unadjusted")
EVENT_FAMILIES = frozenset(("dividends", "splits"))
PRICE_FAMILIES = frozenset(("daily_adjusted", "daily_unadjusted"))
ENDPOINT_PATHS = {
    "dividends": "/stocks/v1/dividends",
    "splits": "/stocks/v1/splits",
}
REQUIRED_FIELDS = {
    "dividends": ("ticker", "ex_dividend_date", "cash_amount", "split_adjusted_cash_amount"),
    "splits": ("ticker", "execution_date", "split_from", "split_to"),
    "daily_adjusted": ("c", "t"),
    "daily_unadjusted": ("c", "t"),
}


class EtfCaptureError(RuntimeError):
    """The authorized ETF capture cannot complete or record safely."""


def _schema_validator(path: Path):
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:  # pragma: no cover - environment guard
        raise EtfCaptureError("jsonschema is required for ETF capture validation") from exc
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EtfCaptureError("ETF capture schema cannot be loaded") from exc
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def _validate(value: dict[str, Any], path: Path, label: str) -> None:
    errors = sorted(_schema_validator(path).iter_errors(value), key=lambda error: list(error.path))
    if errors:
        first = errors[0]
        where = ".".join(str(part) for part in first.path) or "<root>"
        raise EtfCaptureError(f"{label} failed schema validation at {where}: {first.message}")


def load_packet(packet_path: Path = PACKET_PATH) -> dict[str, Any]:
    try:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EtfCaptureError("ETF capture packet cannot be loaded") from exc
    if not isinstance(packet, dict):
        raise EtfCaptureError("ETF capture packet must be an object")
    _validate(packet, PACKET_SCHEMA_PATH, "ETF capture packet")
    return packet


def _repo_relative_path(value: str, *, field: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/") or ":" in value:
        raise EtfCaptureError(f"{field} must be a safe repo-relative path")
    parts = Path(value).parts
    if ".." in parts:
        raise EtfCaptureError(f"{field} may not contain parent traversal")
    path = (ROOT / value).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise EtfCaptureError(f"{field} escapes the repository") from exc
    return path


def _is_gitignored_provider_path(path: Path) -> bool:
    try:
        path.resolve().relative_to((ROOT / "provider_samples").resolve())
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "--quiet", str(path)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except (OSError, ValueError):
        return False


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _write_json_once(path: Path, value: Any, label: str) -> None:
    serialized = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise EtfCaptureError(f"existing {label} is unreadable") from exc
        if existing != serialized:
            raise EtfCaptureError(f"refusing to overwrite drifted {label}")
        return
    # ``write_json_atomic`` preserves mapping insertion order.  Feed it the
    # canonical representation we compare above so the first write and every
    # retry use the same bytes, rather than making a stable page look drifted
    # because the writer and comparator disagree about key ordering.
    sample_validation.write_json_atomic(json.loads(serialized), path)


def _raw_page_path(
    raw_root: Path,
    *,
    symbol: str,
    family: str,
    page_index: int,
    attempt_index: int,
) -> Path:
    """Keep a recovery attempt from colliding with a prior persistent 429 page."""
    path = raw_root / "massive" / symbol / family / (
        f"page-{page_index:03d}-attempt-{attempt_index:03d}.json"
    )
    while path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            break
        if not isinstance(existing, dict) or existing.get("http_status") != 429:
            break
        attempt_index += 1
        path = raw_root / "massive" / symbol / family / (
            f"page-{page_index:03d}-attempt-{attempt_index:03d}.json"
        )
    return path


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _result_rows(payload: Any) -> tuple[str | None, list[Any]]:
    if isinstance(payload, list):
        return "<root-list>", payload
    if isinstance(payload, dict):
        for key in ("results", "data", "historical", "dividends", "splits"):
            rows = payload.get(key)
            if isinstance(rows, list):
                return key, rows
    return None, []


def _row_field_names(rows: list[Any]) -> list[str]:
    return sorted({str(key) for row in rows if isinstance(row, dict) for key in row})


def _date_value(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError:
        return None
    return parsed.isoformat() if parsed.isoformat() == value else None


def _row_date(row: Any, family: str) -> str | None:
    if not isinstance(row, dict):
        return None
    fields = (
        ("ex_dividend_date", "declaration_date", "pay_date") if family == "dividends"
        else ("execution_date",) if family == "splits"
        else ("session_date", "date")
    )
    for field in fields:
        parsed = _date_value(row.get(field))
        if parsed:
            return parsed
    timestamp = row.get("t", row.get("timestamp"))
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return None
    try:
        number = float(timestamp)
        if not math.isfinite(number):
            return None
        seconds = number / 1000 if abs(number) > 10_000_000_000 else number
        return dt.datetime.fromtimestamp(seconds, tz=dt.timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _source_date_range(rows: list[Any], family: str) -> tuple[str | None, str | None]:
    dates = sorted({date for row in rows if (date := _row_date(row, family)) is not None})
    return (dates[0], dates[-1]) if dates else (None, None)


def _row_matches_symbol(row: Any, symbol: str, family: str) -> bool:
    if not isinstance(row, dict):
        return False
    if family in EVENT_FAMILIES:
        return row.get("ticker", row.get("symbol")) == symbol
    row_symbol = row.get("ticker", row.get("symbol", row.get("T")))
    return row_symbol in (None, symbol)


def _safe_continuation_url(
    value: Any,
    *,
    family: str,
    symbol: str,
    packet: dict[str, Any],
    api_key: str,
) -> str:
    if not isinstance(value, str) or not value:
        raise EtfCaptureError("provider continuation is not a non-empty URL")
    parsed = urllib.parse.urlsplit(value)
    expected_host = "api.massive.com"
    if parsed.scheme != "https" or parsed.hostname != expected_host or parsed.username or parsed.password:
        raise EtfCaptureError("provider continuation is outside the authorized HTTPS Massive host")
    try:
        port = parsed.port
    except ValueError as exc:
        raise EtfCaptureError("provider continuation has an invalid port") from exc
    if port not in (None, 443):
        raise EtfCaptureError("provider continuation has an unauthorized port")
    if family in EVENT_FAMILIES:
        expected_path = ENDPOINT_PATHS[family]
    else:
        window = packet["scope"]["price_window"]
        adjusted = "true" if family == "daily_adjusted" else "false"
        expected_path = (
            f"/v2/aggs/ticker/{symbol}/range/1/day/{window['from']}/{window['to']}"
        )
        query_hint = adjusted
    if parsed.path != expected_path:
        raise EtfCaptureError("provider continuation changed the authorized endpoint path")
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    clean: list[tuple[str, str]] = []
    for key, query_value in query:
        lowered = key.lower()
        if lowered == "apikey":
            continue
        if lowered in {"ticker", "tickers"} and query_value != symbol:
            raise EtfCaptureError("provider continuation changed the authorized symbol")
        if family in PRICE_FAMILIES and lowered == "adjusted" and query_value.lower() != query_hint:
            raise EtfCaptureError("provider continuation changed adjusted price mode")
        clean.append((key, query_value))
    clean.append(("apiKey", api_key))
    return urllib.parse.urlunsplit(("https", expected_host, parsed.path, urllib.parse.urlencode(clean), ""))


def _initial_url(*, family: str, symbol: str, packet: dict[str, Any], api_key: str) -> str:
    window = packet["scope"]["price_window"]
    if family in EVENT_FAMILIES:
        params = {
            "ticker": symbol,
            "limit": "5000",
            "sort": "ex_dividend_date" if family == "dividends" else "execution_date",
            "order": "asc",
            "apiKey": api_key,
        }
        return urllib.parse.urlunsplit(
            ("https", "api.massive.com", ENDPOINT_PATHS[family], urllib.parse.urlencode(params), "")
        )
    adjusted = family == "daily_adjusted"
    path = f"/v2/aggs/ticker/{symbol}/range/1/day/{window['from']}/{window['to']}"
    params = {"adjusted": str(adjusted).lower(), "sort": "asc", "limit": "50000", "apiKey": api_key}
    return urllib.parse.urlunsplit(("https", "api.massive.com", path, urllib.parse.urlencode(params), ""))


def _capture_page(
    *,
    client: Any,
    url: str,
    raw_root: Path,
    symbol: str,
    family: str,
    page_index: int,
    attempt_index: int,
    observed_at: str,
    headers: dict[str, str],
) -> dict[str, Any]:
    payload, status, ok, error_type = client.get_json(url, headers=headers)
    # Raw pages are write-once by request identity.  The run-local observation
    # timestamp belongs in the normalized result, not this immutable wrapper:
    # otherwise an interrupted weekly retry conflicts solely because it ran at a
    # different second.
    wrapper = {
        "provider_id": "massive",
        "endpoint_family": family,
        "symbol": symbol,
        "page_index": page_index,
        "attempt_index": attempt_index,
        "http_status": status,
        "ok": ok,
        "error_type": error_type,
        "payload": payload,
    }
    path = _raw_page_path(
        raw_root,
        symbol=symbol,
        family=family,
        page_index=page_index,
        attempt_index=attempt_index,
    )
    _write_json_once(path, wrapper, f"raw page {symbol}/{family}/{page_index}/{attempt_index}")
    return {
        "payload": payload,
        "http_status": status,
        "ok": bool(ok),
        "error_type": error_type,
        "sha256": _sha256(wrapper),
    }


def _page_result(
    *,
    symbol: str,
    family: str,
    pages: list[dict[str, Any]],
    observed_at: str,
    pagination_complete: bool,
    pagination_reason: str | None,
) -> tuple[dict[str, Any], list[Any]]:
    rows: list[Any] = []
    field_names: set[str] = set()
    error_types: set[str] = set()
    unreadable_body_pages = 0
    success_pages = 0
    for page in pages:
        if page["ok"]:
            success_pages += 1
            result_key, page_rows = _result_rows(page["payload"])
            if result_key is None:
                unreadable_body_pages += 1
            rows.extend(page_rows)
            field_names.update(_row_field_names(page_rows))
        if page["error_type"]:
            error_types.add(str(page["error_type"]))
    matched = sum(1 for row in rows if _row_matches_symbol(row, symbol, family))
    required = list(REQUIRED_FIELDS[family])
    required_present = set(required).issubset(field_names)
    source_from, source_to = _source_date_range(rows, family)
    if pagination_reason == "pagination_incomplete":
        status = "pagination_incomplete"
    elif not pages or success_pages == 0:
        status = "provider_error"
    elif unreadable_body_pages:
        status = "unreadable_body"
    elif not rows:
        status = "empty"
    elif matched != len(rows):
        status = "rows_do_not_match_symbol"
    elif not required_present:
        status = "missing_required_fields"
    else:
        status = "covered"
    result = {
        "symbol": symbol,
        "endpoint_family": family,
        "pages_captured": len(pages),
        "pagination_complete": bool(pagination_complete),
        "http_success_pages": success_pages,
        "final_http_status": pages[-1]["http_status"] if pages else None,
        "error_types": sorted(error_types),
        "row_count": len(rows),
        "matched_symbol_row_count": matched,
        "field_names": sorted(field_names),
        "required_field_names": required,
        "required_fields_present": required_present,
        "source_date_from": source_from,
        "source_date_to": source_to,
        "observed_at": observed_at,
        "source_sha256": _sha256([page["sha256"] for page in pages]),
        "status": status,
    }
    return result, rows


def _daily_reconciliation(
    *,
    symbol: str,
    adjusted_result: dict[str, Any],
    adjusted_rows: list[Any],
    unadjusted_result: dict[str, Any],
    unadjusted_rows: list[Any],
    split_rows: list[Any],
    observed_at: str,
) -> dict[str, Any]:
    def session_map(rows: list[Any], family: str) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for row in rows:
            date = _row_date(row, family)
            if date is None or date in result:
                continue
            result[date] = row
        return result

    adjusted = session_map(adjusted_rows, "daily_adjusted")
    unadjusted = session_map(unadjusted_rows, "daily_unadjusted")
    overlap = set(adjusted).intersection(unadjusted)
    split_dates = {
        split_date
        for row in split_rows
        if (split_date := _row_date(row, "splits")) is not None
    }
    split_in_window = bool(
        overlap
        and any(min(overlap) <= split_date <= max(overlap) for split_date in split_dates)
    )
    numeric_pairs = 0
    numeric_mismatch = False
    if not split_in_window:
        for date in overlap:
            left = adjusted[date].get("c") if isinstance(adjusted[date], dict) else None
            right = unadjusted[date].get("c") if isinstance(unadjusted[date], dict) else None
            try:
                left_number = float(left) if not isinstance(left, bool) else float("nan")
                right_number = float(right) if not isinstance(right, bool) else float("nan")
                if math.isfinite(left_number) and math.isfinite(right_number):
                    numeric_pairs += 1
                    if not math.isclose(left_number, right_number, rel_tol=0.0, abs_tol=1e-6):
                        numeric_mismatch = True
                else:
                    numeric_mismatch = True
            except (TypeError, ValueError, OverflowError):
                numeric_mismatch = True
    both_covered = adjusted_result["status"] == "covered" and unadjusted_result["status"] == "covered"
    status = "session_coverage_match" if (
        both_covered and set(adjusted) == set(unadjusted) and not numeric_mismatch
    ) else (
        "session_coverage_mismatch" if both_covered else "not_evaluable"
    )
    return {
        "symbol": symbol,
        "status": status,
        "adjusted_session_count": len(adjusted),
        "unadjusted_session_count": len(unadjusted),
        "overlap_session_count": len(overlap),
        "numeric_pair_count": numeric_pairs,
        "adjusted_source_sha256": adjusted_result["source_sha256"],
        "unadjusted_source_sha256": unadjusted_result["source_sha256"],
        "observed_at": observed_at,
    }


def _scan_summary_safe(text: str, sensitive_values: list[str]) -> None:
    lowered = text.lower()
    for fragment in ("apikey=", "api.massive.com", "http://", "https://", '"payload"', '"raw_payload"'):
        if fragment in lowered:
            raise EtfCaptureError(f"tracked capture summary contains a forbidden fragment: {fragment}")
    for value in sensitive_values:
        if value and value in text:
            raise EtfCaptureError("tracked capture summary contains an environment secret")


def _write_summary(summary: dict[str, Any], path: Path, sensitive_values: list[str]) -> None:
    _validate(summary, SUMMARY_SCHEMA_PATH, "ETF capture summary")
    serialized = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _scan_summary_safe(serialized, sensitive_values)
    _write_json_once(path, summary, "tracked ETF capture summary")


def run_capture(
    *,
    confirm_user_authorization: bool,
    packet_path: Path = PACKET_PATH,
    client: Any | None = None,
    sleep_func: Callable[[float], None] = time.sleep,
    now_func: Callable[[], str] = _iso_now,
) -> dict[str, Any]:
    if not confirm_user_authorization:
        raise EtfCaptureError("Knife5 ETF capture requires explicit per-execution authorization")
    packet = load_packet(packet_path)
    raw_root = _repo_relative_path(packet["storage"]["raw_payload_root"], field="raw_payload_root")
    normalized_path = _repo_relative_path(packet["storage"]["normalized_capture_path"], field="normalized_capture_path")
    summary_path = _repo_relative_path(packet["storage"]["tracked_summary_path"], field="tracked_summary_path")
    if not _is_gitignored_provider_path(raw_root) or not _is_gitignored_provider_path(normalized_path.parent):
        raise EtfCaptureError("raw and normalized capture paths must be confirmed gitignored provider_samples paths")
    if raw_root.exists() or normalized_path.exists() or summary_path.exists():
        raise EtfCaptureError("capture outputs already exist; refusing to duplicate or overwrite the live capture")

    api_key = sample_validation.read_required_env("MASSIVE_API_KEY")
    client = client or sample_validation.JsonHttpClient()
    execution = packet["execution"]
    max_pages = execution["max_pages_per_symbol_family"]
    nominal_calls = execution["nominal_logical_calls"]
    max_attempts = execution["max_total_http_attempts"]
    max_retries = execution["max_retries_per_page"]
    pace_seconds = execution["pace_seconds"]
    retry_backoff = execution["retry_backoff_seconds"]
    observed_at = now_func()
    headers = {"User-Agent": "StockSystem/0.1 us-short-market-diagnostic-etf-capture"}
    physical_attempts = 0
    logical_requests = 0
    retry_count = 0
    family_results: list[dict[str, Any]] = []
    family_rows: dict[tuple[str, str], list[Any]] = {}
    records: dict[tuple[str, str], dict[str, Any]] = {}

    for symbol in SYMBOLS:
        for family in FAMILIES:
            pages: list[dict[str, Any]] = []
            next_url = _initial_url(family=family, symbol=symbol, packet=packet, api_key=api_key.value)
            pagination_complete = False
            pagination_reason: str | None = None
            for page_index in range(1, max_pages + 1):
                if not next_url:
                    pagination_complete = True
                    break
                logical_requests += 1
                if logical_requests > nominal_calls:
                    raise EtfCaptureError("logical page budget exceeded before provider request")
                attempt_index = 0
                final_page: dict[str, Any] | None = None
                while True:
                    if physical_attempts >= max_attempts:
                        pagination_reason = "pagination_incomplete"
                        next_url = None
                        break
                    if physical_attempts:
                        sleep_func(pace_seconds)
                    attempt_index += 1
                    observed_page_at = now_func()
                    page = _capture_page(
                        client=client,
                        url=next_url,
                        raw_root=raw_root,
                        symbol=symbol,
                        family=family,
                        page_index=page_index,
                        attempt_index=attempt_index,
                        observed_at=observed_page_at,
                        headers=headers,
                    )
                    physical_attempts += 1
                    # A retry is another physical attempt for the same logical page.  Keep every
                    # attempt on disk, but let the aggregate count only the final outcome once.
                    final_page = page
                    if page["ok"] or page["http_status"] != 429 or attempt_index > max_retries:
                        break
                    remaining_nominal = nominal_calls - logical_requests
                    if physical_attempts + 1 + remaining_nominal > max_attempts:
                        break
                    retry_count += 1
                    sleep_func(retry_backoff * (2 ** (attempt_index - 1)))
                if final_page is not None:
                    pages.append(final_page)
                if final_page is None:
                    pagination_reason = "pagination_incomplete"
                    break
                latest = final_page
                if not latest["ok"]:
                    pagination_complete = False
                    break
                payload = latest["payload"]
                raw_next = payload.get("next_url") if isinstance(payload, dict) else None
                if not raw_next:
                    pagination_complete = True
                    next_url = None
                    break
                if page_index == max_pages:
                    pagination_reason = "pagination_incomplete"
                    next_url = None
                    break
                try:
                    next_url = _safe_continuation_url(
                        raw_next,
                        family=family,
                        symbol=symbol,
                        packet=packet,
                        api_key=api_key.value,
                    )
                except EtfCaptureError:
                    pagination_reason = "pagination_incomplete"
                    next_url = None
                    break
            result, rows = _page_result(
                symbol=symbol,
                family=family,
                pages=pages,
                observed_at=observed_at,
                pagination_complete=pagination_complete,
                pagination_reason=pagination_reason,
            )
            family_results.append(result)
            family_rows[(symbol, family)] = rows
            records[(symbol, family)] = result

    reconciliations = []
    for symbol in SYMBOLS:
        reconciliations.append(
            _daily_reconciliation(
                symbol=symbol,
                adjusted_result=records[(symbol, "daily_adjusted")],
                adjusted_rows=family_rows[(symbol, "daily_adjusted")],
                unadjusted_result=records[(symbol, "daily_unadjusted")],
                unadjusted_rows=family_rows[(symbol, "daily_unadjusted")],
                split_rows=family_rows[(symbol, "splits")],
                observed_at=observed_at,
            )
        )

    summary = {
        "schema_name": "us_short_market_diagnostic_etf_capture_summary",
        "schema_version": "1.0.0",
        "scope": {
            "authorization_ref": AUTHORIZATION_REF,
            "capture_date": packet["capture_date"],
            "provider_id": "massive",
            "symbols": list(SYMBOLS),
            "endpoint_families": list(FAMILIES),
            "price_window": packet["scope"]["price_window"],
            "generated_at": observed_at,
            "nominal_logical_calls": nominal_calls,
            "max_total_http_attempts": max_attempts,
            "actual_logical_requests": logical_requests,
            "actual_http_attempts": physical_attempts,
            "retry_count_used": retry_count,
        },
        "family_results": family_results,
        "daily_reconciliation": reconciliations,
        "storage": {
            "raw_payload_root": packet["storage"]["raw_payload_root"],
            "normalized_capture_path": packet["storage"]["normalized_capture_path"],
            "normalized_capture_gitignored": True,
            "tracked_summary_path": packet["storage"]["tracked_summary_path"],
            "tracked_summary_contains_secrets": False,
            "tracked_summary_contains_request_urls": False,
            "tracked_summary_contains_raw_payload_rows": False,
            "tracked_summary_contains_raw_price_values": False,
            "tracked_summary_contains_raw_event_values": False,
        },
        "boundary": {
            "provider_calls_performed": True,
            "capture_segment_performed": True,
            "week_aligned_sidecar_written": False,
            "total_return_calculation_performed": False,
            "diagnostic_clock_started": False,
            "real_account_written": False,
            "selection_or_action_changed": False,
            "production_or_ship_gate_claimed": False,
            "datahub_consumed": False,
            "provider_selected": False,
            "sr_provider_001_closed": False,
        },
    }
    _write_summary(summary, normalized_path, [api_key.value])
    _write_summary(summary, summary_path, [api_key.value])
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the bounded Knife5 ETF evidence capture")
    parser.add_argument("--packet", type=Path, default=PACKET_PATH)
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--dry-run-env", action="store_true", help="validate packet, env, and private paths; no network")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        packet = load_packet(args.packet)
        raw_root = _repo_relative_path(packet["storage"]["raw_payload_root"], field="raw_payload_root")
        if args.dry_run_env:
            import os

            print(f"MASSIVE_API_KEY present: {bool(os.environ.get('MASSIVE_API_KEY'))}")
            print(f"raw root gitignored: {_is_gitignored_provider_path(raw_root)}")
            print(f"planned logical calls: {packet['execution']['nominal_logical_calls']}")
            print(f"hard HTTP-attempt cap: {packet['execution']['max_total_http_attempts']}")
            print(f"symbols: {SYMBOLS}; families: {FAMILIES}")
            return 0
        summary = run_capture(confirm_user_authorization=args.confirm_user_authorization, packet_path=args.packet)
    except EtfCaptureError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(
        f"capture complete: logical={summary['scope']['actual_logical_requests']} "
        f"http_attempts={summary['scope']['actual_http_attempts']} retries={summary['scope']['retry_count_used']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
