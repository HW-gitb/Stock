"""Gated weekly Massive fetch for the Knife 5 ETF total-return sidecar.

This runner is called only by the existing diagnostic fetch stage.  It has no
standalone authorization CLI: the capstone's per-execution gate is the one
authorization for benchmark prices, cash, and this sidecar together.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
from collections.abc import Mapping
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_market_diagnostic import BENCHMARKS
from engine.us_short_market_diagnostic_etf_sidecar import (
    FAMILIES,
    EtfSidecarProducerError,
    build_etf_total_return_sidecar_week,
    sidecar_evaluable_symbols,
)
from engine.us_short_market_diagnostic_local_adapter import validate_local_price_packet
from engine.us_short_market_diagnostic_total_return import (
    TotalReturnSidecarError,
    validate_etf_total_return_sidecar,
)
from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path
from engine.us_short_model_paper_portfolio import canonical_json_bytes
from runners import us_short_market_diagnostic_etf_capture as capture
from runners import us_egs_sample_validation as sample_validation
from runners import us_short_universe_fetch as universe_fetch
from runners.us_short_market_diagnostic_benchmark_fetch import DEFAULT_INPUTS_ROOT


SIDECAR_DIRECTORY = "etf_total_return_sidecar"
SIDECAR_FILENAME = "total_return_sidecar.json"
BASELINE_LOGICAL_CALLS = len(BENCHMARKS) * len(FAMILIES)
MAX_PAGES_PER_SYMBOL_FAMILY = 2
MAX_LOGICAL_REQUESTS = BASELINE_LOGICAL_CALLS * MAX_PAGES_PER_SYMBOL_FAMILY
MAX_TOTAL_HTTP_ATTEMPTS = 40
MAX_RETRIES_PER_PAGE = universe_fetch.MASSIVE_RATE_LIMIT_MAX_RETRIES
MASSIVE_429_RETRY_WAIT_SECONDS = universe_fetch.MASSIVE_RATE_LIMIT_RETRY_SECONDS
MISSING_PROVIDER_KEY = "provider_key_missing"


class EtfSidecarFetchError(RuntimeError):
    """The weekly sidecar fetch cannot proceed without violating a hard boundary."""


def sidecar_week_directory(
    decision_date: str, *, inputs_root: Path = DEFAULT_INPUTS_ROOT
) -> Path:
    return Path(inputs_root).resolve() / SIDECAR_DIRECTORY / decision_date


def sidecar_path(
    decision_date: str, *, inputs_root: Path = DEFAULT_INPUTS_ROOT
) -> Path:
    return sidecar_week_directory(decision_date, inputs_root=inputs_root) / SIDECAR_FILENAME


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _calendar_day(value: str, field: str):
    if not isinstance(value, str):
        raise EtfSidecarFetchError(f"{field} must be YYYYMMDD or YYYY-MM-DD")
    normalized = value.replace("-", "") if len(value) == 10 else value
    if len(normalized) != 8 or not normalized.isascii() or not normalized.isdigit():
        raise EtfSidecarFetchError(f"{field} must be YYYYMMDD or YYYY-MM-DD")
    try:
        return datetime.strptime(normalized, "%Y%m%d").date()
    except ValueError as exc:
        raise EtfSidecarFetchError(f"{field} is not a real date") from exc


def _observed_day(value: str):
    if not isinstance(value, str) or not value:
        raise EtfSidecarFetchError("sidecar observed_at must be an ISO timestamp")
    normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise EtfSidecarFetchError("sidecar observed_at must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise EtfSidecarFetchError("sidecar observed_at must include a timezone")
    return parsed.astimezone(timezone.utc).date()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EtfSidecarFetchError(f"{label} cannot be read") from exc
    if not isinstance(value, dict):
        raise EtfSidecarFetchError(f"{label} is not an object")
    return value


def _write_json_once(path: Path, value: Mapping[str, Any]) -> None:
    payload = canonical_json_bytes(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        try:
            existing = path.read_bytes()
        except OSError as read_exc:
            raise EtfSidecarFetchError("existing sidecar is unreadable") from read_exc
        if existing != payload:
            raise EtfSidecarFetchError("refusing to overwrite a different sidecar") from exc
        return
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)

def _safe_sidecar_text(text: str, sensitive_values: list[str]) -> None:
    lowered = text.lower()
    for fragment in ("apikey=", "api.massive.com", "http://", "https://", '"payload"'):
        if fragment in lowered:
            raise EtfSidecarFetchError("sidecar contains a forbidden provider fragment")
    if any(value and value in text for value in sensitive_values):
        raise EtfSidecarFetchError("sidecar contains an environment secret")


def _provider_samples_root(decision_date: str) -> Path:
    return ROOT / "provider_samples" / f"us_short_market_diagnostic_etf_sidecar_{decision_date}" / "raw"


def _synthetic_capture(
    *,
    symbol: str,
    family: str,
    decision_date: str,
    observed_at: str,
    error_type: str,
) -> dict[str, Any]:
    # Missing-key and pre-response failures have no provider row to persist.  A
    # deterministic failure digest still lets the sidecar bind the attempted
    # family without writing a fabricated provider payload.
    source_sha = capture._sha256({
        "kind": "us_short_etf_sidecar_failure",
        "symbol": symbol,
        "family": family,
        "decision_date": decision_date,
        "error_type": error_type,
    })
    return {
        "symbol": symbol,
        "endpoint_family": family,
        "pages_captured": 0,
        "pagination_complete": False,
        "http_success_pages": 0,
        "final_http_status": None,
        "error_types": [error_type],
        "row_count": 0,
        "matched_symbol_row_count": 0,
        "field_names": [],
        "required_field_names": list(capture.REQUIRED_FIELDS[family]),
        "required_fields_present": False,
        "source_date_from": None,
        "source_date_to": None,
        "observed_at": observed_at,
        "source_sha256": source_sha,
        "status": "provider_error",
        "rows": [],
    }


def _consume_physical_attempt(
    counters: dict[str, int], *, reserved_required_attempts: int,
) -> bool:
    """Consume one attempt while preserving one initial attempt per remaining logical slot."""
    if counters["physical"] + 1 + reserved_required_attempts > MAX_TOTAL_HTTP_ATTEMPTS:
        return False
    counters["physical"] += 1
    return True


def _price_window(price_intervals: dict[str, dict[str, str | None]], fallback: str) -> dict[str, str]:
    dates = [
        value
        for interval in price_intervals.values()
        for value in (interval.get("prior_price_date"), interval.get("price_date"))
        if isinstance(value, str)
    ]
    if not dates:
        fallback_iso = f"{fallback[:4]}-{fallback[4:6]}-{fallback[6:]}"
        return {"from": fallback_iso, "to": fallback_iso}
    first = min(dates)
    last = max(dates)
    return {
        "from": f"{first[:4]}-{first[4:6]}-{first[6:]}",
        "to": f"{last[:4]}-{last[4:6]}-{last[6:]}",
    }


def _capture_family(
    *,
    symbol: str,
    family: str,
    packet: dict[str, Any],
    raw_root: Path,
    client: Any,
    api_key: str,
    observed_at: str,
    decision_date: str,
    counters: dict[str, int],
    call_log: list[str],
    sleep_func: Callable[[float], None],
) -> tuple[dict[str, Any], bool]:
    pages: list[dict[str, Any]] = []
    next_url = capture._initial_url(
        family=family, symbol=symbol, packet=packet, api_key=api_key
    )
    pagination_complete = False
    pagination_reason: str | None = None

    for page_index in range(1, MAX_PAGES_PER_SYMBOL_FAMILY + 1):
        if not next_url:
            pagination_complete = True
            break
        if counters["logical"] >= MAX_LOGICAL_REQUESTS:
            raise EtfSidecarFetchError("weekly ETF sidecar logical call budget exceeded before request")
        if not _consume_physical_attempt(
            counters,
            reserved_required_attempts=MAX_LOGICAL_REQUESTS - counters["logical"] - 1,
        ):
            pagination_reason = "pagination_incomplete"
            break
        counters["logical"] += 1
        attempt_index = 0
        final_page: dict[str, Any] | None = None
        while True:
            attempt_index += 1
            call_log.append(f"etf_sidecar:{symbol}:{family}:{page_index}:{attempt_index}")
            try:
                final_page = capture._capture_page(
                    client=client,
                    url=next_url,
                    raw_root=raw_root,
                    symbol=symbol,
                    family=family,
                    page_index=page_index,
                    attempt_index=attempt_index,
                    observed_at=observed_at,
                    headers={"User-Agent": "StockSystem/0.1 us-short-market-diagnostic-etf-sidecar"},
                )
            except capture.EtfCaptureError:
                # A write-once raw conflict may follow an interrupted attempt.
                # Do not overwrite its private evidence; mark only this family
                # unavailable and let the other ETFs plus the cash leg proceed.
                return _synthetic_capture(
                    symbol=symbol,
                    family=family,
                    decision_date=decision_date,
                    observed_at=observed_at,
                    error_type="raw_conflict",
                ), False
            except Exception as exc:  # provider/client failure; retain class only
                return _synthetic_capture(
                    symbol=symbol,
                    family=family,
                    decision_date=decision_date,
                    observed_at=observed_at,
                    error_type=type(exc).__name__,
                ), False
            if final_page["ok"] or final_page["http_status"] != 429 or attempt_index > MAX_RETRIES_PER_PAGE:
                break
            if not _consume_physical_attempt(
                counters,
                reserved_required_attempts=MAX_LOGICAL_REQUESTS - counters["logical"],
            ):
                pagination_reason = "pagination_incomplete"
                break
            counters["retry"] += 1
            sleep_func(MASSIVE_429_RETRY_WAIT_SECONDS)
        if final_page is not None:
            pages.append(final_page)
        if final_page is None:
            break
        if not final_page["ok"]:
            break
        payload = final_page["payload"]
        raw_next = payload.get("next_url") if isinstance(payload, dict) else None
        if not raw_next:
            pagination_complete = True
            next_url = None
            break
        if page_index == MAX_PAGES_PER_SYMBOL_FAMILY:
            pagination_reason = "pagination_incomplete"
            next_url = None
            break
        try:
            next_url = capture._safe_continuation_url(
                raw_next,
                family=family,
                symbol=symbol,
                packet=packet,
                api_key=api_key,
            )
        except capture.EtfCaptureError:
            pagination_reason = "pagination_incomplete"
            next_url = None
            break

    result, rows = capture._page_result(
        symbol=symbol,
        family=family,
        pages=pages,
        observed_at=observed_at,
        pagination_complete=pagination_complete,
        pagination_reason=pagination_reason,
    )
    result["rows"] = rows
    massive_429_exhausted = bool(
        final_page is not None
        and not final_page["ok"]
        and final_page["http_status"] == 429
    )
    if massive_429_exhausted:
        result["error_types"] = sorted(
            set(result.get("error_types", [])) | {"massive_429_exhausted"}
        )
    return result, massive_429_exhausted


def capture_sidecar_week(
    *,
    confirm_user_authorization: bool,
    benchmark_packet: dict[str, Any],
    decision_date: str,
    as_of_date: str | None = None,
    inputs_root: Path = DEFAULT_INPUTS_ROOT,
    client: Any | None = None,
    api_key: str | None = None,
    now: Callable[[], str] | None = None,
    call_log: list[str] | None = None,
    sleep_func: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Capture and write one immutable sidecar after the existing gate passes."""

    if confirm_user_authorization is not True:
        raise EtfSidecarFetchError("the weekly ETF sidecar requires the existing capstone authorization")
    try:
        packet = validate_local_price_packet(benchmark_packet, as_of_date=as_of_date)
    except Exception as exc:
        raise EtfSidecarFetchError("benchmark price packet cannot bind the ETF sidecar") from exc
    week = packet["weeks"][0]
    price_intervals = {
        symbol: {
            "prior_price_date": week["benchmarks"][symbol]["prior_price_date"],
            "price_date": week["benchmarks"][symbol]["price_date"],
        }
        for symbol in BENCHMARKS
    }
    directory = sidecar_week_directory(decision_date, inputs_root=inputs_root)
    try:
        reject_nonprivate_output_path(directory)
    except PrivatePathError as exc:
        raise EtfSidecarFetchError("refusing a non-private ETF sidecar directory") from exc
    raw_root = _provider_samples_root(decision_date)
    if not capture._is_gitignored_provider_path(raw_root):
        raise EtfSidecarFetchError("ETF sidecar raw root is not provably gitignored")
    output_path = directory / SIDECAR_FILENAME
    observed_at = (now or _iso_now)()
    if as_of_date is not None and _observed_day(observed_at) > _calendar_day(
        as_of_date, "as_of_date"
    ):
        # Reject a historical replay before spending its ETF-call budget.  Do
        # not backdate observed_at: that would fabricate PIT evidence.
        raise EtfSidecarFetchError("sidecar observed_at is after the requested as_of_date")
    local_log = call_log if call_log is not None else []
    if output_path.exists():
        existing = _read_json(output_path, "ETF sidecar")
        try:
            validate_etf_total_return_sidecar(
                existing,
                expected_price_intervals={
                    (week["calendar_week_index"], symbol): (
                        price_intervals[symbol]["prior_price_date"],
                        price_intervals[symbol]["price_date"],
                    )
                    for symbol in BENCHMARKS
                },
                as_of_date=as_of_date,
            )
        except TotalReturnSidecarError as exc:
            raise EtfSidecarFetchError("existing ETF sidecar fails its source/date binding") from exc
        return {
            "status": "idempotent",
            "sidecar_path": str(output_path),
            "evaluable_symbols": sidecar_evaluable_symbols(existing),
            "provider_calls": 0,
            "logical_requests": 0,
            "http_attempts": 0,
            "retry_count_allowed": MAX_RETRIES_PER_PAGE,
            "retry_count_used": 0,
            "massive_429_retry_wait_seconds": MASSIVE_429_RETRY_WAIT_SECONDS,
        }

    counters = {"logical": 0, "physical": 0, "retry": 0}
    sleeper = sleep_func or time.sleep
    captures: dict[str, dict[str, dict[str, Any]]] = {}
    persistent_429_families = 0
    if api_key is None:
        try:
            api_key = sample_validation.read_required_env("MASSIVE_API_KEY").value
        except Exception:
            api_key = ""
    if not api_key:
        for symbol in BENCHMARKS:
            captures[symbol] = {
                family: _synthetic_capture(
                    symbol=symbol,
                    family=family,
                    decision_date=decision_date,
                    observed_at=observed_at,
                    error_type=MISSING_PROVIDER_KEY,
                )
                for family in FAMILIES
            }
    else:
        provider = client or sample_validation.JsonHttpClient()
        request_packet = {
            "scope": {"price_window": _price_window(price_intervals, decision_date)},
        }
        for symbol in BENCHMARKS:
            captures[symbol] = {}
            for family in FAMILIES:
                captures[symbol][family], exhausted_429 = _capture_family(
                    symbol=symbol,
                    family=family,
                    packet=request_packet,
                    raw_root=raw_root,
                    client=provider,
                    api_key=api_key,
                    observed_at=observed_at,
                    decision_date=decision_date,
                    counters=counters,
                    call_log=local_log,
                    sleep_func=sleeper,
                )
                persistent_429_families += int(exhausted_429)

    if (
        persistent_429_families == BASELINE_LOGICAL_CALLS
        and all(
            captures[symbol][family].get("http_success_pages", 0) == 0
            for symbol in BENCHMARKS
            for family in FAMILIES
        )
    ):
        return {
            "status": "incomplete_no_count",
            "sidecar_path": None,
            "evaluable_symbols": [],
            "provider_calls": counters["physical"],
            "logical_requests": counters["logical"],
            "http_attempts": counters["physical"],
            "retry_count_allowed": MAX_RETRIES_PER_PAGE,
            "retry_count_used": counters["retry"],
            "massive_429_retry_wait_seconds": MASSIVE_429_RETRY_WAIT_SECONDS,
        }

    try:
        sidecar = build_etf_total_return_sidecar_week(
            captures=captures,
            price_intervals=price_intervals,
            calendar_week_index=week["calendar_week_index"],
            valuation_date=week["valuation_date"],
            diagnostic_epoch=packet["diagnostic_epoch"],
            observed_at=observed_at,
        )
        validate_etf_total_return_sidecar(
            sidecar,
            expected_price_intervals={
                (week["calendar_week_index"], symbol): (
                    price_intervals[symbol]["prior_price_date"],
                    price_intervals[symbol]["price_date"],
                )
                for symbol in BENCHMARKS
            },
            as_of_date=as_of_date,
        )
    except (EtfSidecarProducerError, TotalReturnSidecarError) as exc:
        raise EtfSidecarFetchError("ETF sidecar producer failed its local validation") from exc
    serialized = canonical_json_bytes(sidecar).decode("utf-8")
    _safe_sidecar_text(serialized, [api_key])
    _write_json_once(output_path, sidecar)
    return {
        "status": "captured",
        "sidecar_path": str(output_path),
        "evaluable_symbols": sidecar_evaluable_symbols(sidecar),
        "provider_calls": counters["physical"],
        "logical_requests": counters["logical"],
        "http_attempts": counters["physical"],
        "retry_count_allowed": MAX_RETRIES_PER_PAGE,
        "retry_count_used": counters["retry"],
        "massive_429_retry_wait_seconds": MASSIVE_429_RETRY_WAIT_SECONDS,
    }


__all__ = [
    "BASELINE_LOGICAL_CALLS",
    "EtfSidecarFetchError",
    "MAX_LOGICAL_REQUESTS",
    "MAX_TOTAL_HTTP_ATTEMPTS",
    "MAX_RETRIES_PER_PAGE",
    "MASSIVE_429_RETRY_WAIT_SECONDS",
    "SIDECAR_FILENAME",
    "capture_sidecar_week",
    "sidecar_path",
    "sidecar_week_directory",
]
