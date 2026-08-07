"""Knife 9 runner: land one week's FRED DGS3MO vintage, then shape the cash leg.

Reads ``FRED_API_KEY`` from the environment. The key is never printed, never
stored, and never allowed into an error message: a failed request from urllib
carries the URL it tried, and that URL contains the key, so every vendor failure
is reduced to its exception CLASS before it goes anywhere.

One request per week does both jobs. Asking for a real-time RANGE rather than a
single pin makes FRED return every vintage of every day in the window, which
gives two different things at once: the value as the world knew it at
``as_of_date``, and the date each value was FIRST published. The second is what
lets Knife 9 refuse a rate that was dated before the decision but not yet out
when it was made.

A missing key, a network failure or an empty window all land the same way: a
capture recording the attempt, and an ``unavailable`` cash leg for that week. The
week still happens — section 2.2 keeps its calendar slot either way.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_market_diagnostic_cash_return import (  # noqa: E402
    CAPTURE_SCHEMA_NAME,
    CAPTURE_SCHEMA_VERSION,
    FETCH_FAILED,
    FETCH_OK,
    MISSING_VALUE,
    SERIES_ID,
    VENDOR,
    CashReturnError,
    build_cash_observation,
    validate_cash_capture,
)
from engine.us_short_model_paper_portfolio import artifact_sha256  # noqa: E402
from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path  # noqa: E402
from runners.us_short_market_diagnostic_benchmark_fetch import (  # noqa: E402
    DEFAULT_INPUTS_ROOT,
    write_private_json_once,
)

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
API_KEY_ENV = "FRED_API_KEY"
CAPTURE_FILENAME = f"{SERIES_ID}.json"
OBSERVATION_FILENAME = "cash_observation.json"
# How far back the request reaches. Matches the engine's own lookback bound, so a
# rate the engine would refuse as stale is never even asked for.
LOOKBACK_DAYS = 21


class CashFetchError(Exception):
    """The week's cash input cannot be captured."""


def week_directory(decision_date: str, *, inputs_root: Path = DEFAULT_INPUTS_ROOT) -> Path:
    return Path(inputs_root).resolve() / "cash" / decision_date


def _api_key() -> str | None:
    key = os.environ.get(API_KEY_ENV)
    return key if key else None


def fetch_vintages(
    *,
    observation_start: str,
    observation_end: str,
    realtime_end: str,
    api_key: str,
    opener: Callable[[str], bytes] | None = None,
) -> list[dict[str, Any]]:
    """Every vintage of every day in the window, as FRED returns them.

    The real-time window opens at ``observation_start`` so that the first vintage
    of the oldest day requested is inside it; a clipped range would report a first
    publication later than the truth and silently reject a usable rate.
    """

    query = {
        "series_id": SERIES_ID,
        "file_type": "json",
        "api_key": api_key,
        "observation_start": observation_start,
        "observation_end": observation_end,
        "realtime_start": observation_start,
        "realtime_end": realtime_end,
    }
    url = FRED_OBSERVATIONS_URL + "?" + urllib.parse.urlencode(query)
    if opener is not None:
        payload = json.loads(opener(url).decode("utf-8"))
    else:
        with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310 - fixed host
            payload = json.loads(response.read().decode("utf-8"))
    rows = payload.get("observations")
    if not isinstance(rows, list):
        raise CashFetchError("FRED response carries no observations list")
    return rows


def _collapse(rows: list[dict[str, Any]], *, realtime_end: str) -> list[dict[str, Any]]:
    """One record per day: the value known at ``realtime_end``, and its first vintage."""

    by_day: dict[str, dict[str, Any]] = {}
    for row in rows:
        day = row.get("date")
        start = row.get("realtime_start")
        end = row.get("realtime_end")
        value = row.get("value")
        if not isinstance(day, str) or not isinstance(start, str) or not isinstance(value, str):
            raise CashFetchError("FRED observation row is missing date, realtime_start or value")
        record = by_day.setdefault(day, {"date": day, "value": None, "available_from": None})
        # The date reported beside a value has to be the date THAT value was
        # published, not the earliest date any value for the day was published.
        # Taking the minimum across every vintage paired a revised number with
        # its predecessor's publication date: FRED revised DGS3MO for 2026-06-01
        # from 4.20 to 3.00 on 06-08, and the pairing then claimed 3.00 had been
        # available since 06-02 — a rate nobody could have seen, wearing a date
        # that made it look point-in-time. Bind both to the ONE vintage that was
        # current at the real-time end being read.
        if isinstance(end, str) and start <= realtime_end <= end:
            record["value"] = value
            record["available_from"] = start if value != MISSING_VALUE else None
    collapsed = []
    for day in sorted(by_day):
        record = by_day[day]
        value = record["value"]
        if value is None or value == MISSING_VALUE:
            collapsed.append(
                {"date": day.replace("-", ""), "value": MISSING_VALUE, "available_from": None}
            )
            continue
        collapsed.append(
            {
                "date": day.replace("-", ""),
                "value": value,
                "available_from": record["available_from"],
            }
        )
    return collapsed


def capture_cash_week(
    *,
    confirm_user_authorization: bool = False,
    call_log: list[str] | None = None,
    decision_date: str,
    valuation_date: str,
    calendar_week_index: int,
    as_of_date: str | None = None,
    inputs_root: Path = DEFAULT_INPUTS_ROOT,
    opener: Callable[[str], bytes] | None = None,
    api_key: str | None = None,
    now: Callable[[], datetime] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Capture one week's vintage and write the cash observation beside it."""

    if not confirm_user_authorization:
        # The sibling live fetchers' unconditional gate. FRED is a real vendor and
        # this reaches it, so the direct and CLI paths need the same door the
        # pipeline path gets from its stage being `gated`.
        raise CashFetchError(
            "a live cash capture requires explicit user authorization "
            "(confirm_user_authorization=True)"
        )
    attempts = call_log if call_log is not None else []
    directory = week_directory(decision_date, inputs_root=inputs_root)
    try:
        reject_nonprivate_output_path(directory)
    except PrivatePathError as exc:
        raise CashFetchError(f"refusing a non-private inputs directory: {exc}") from exc

    as_of = as_of_date or datetime.now(timezone.utc).strftime("%Y%m%d")
    capture_path = directory / CAPTURE_FILENAME
    if capture_path.exists():
        capture, digest = _read_private_json(capture_path)
        validate_cash_capture(capture, as_of_date=as_of)
        reused = True
    else:
        if dry_run:
            raise CashFetchError("--dry-run cannot capture; it revalidates an already-captured week")
        # Recorded before the request so a failure cannot erase it.
        attempts.append(SERIES_ID)
        capture = _build_capture(
            valuation_date=valuation_date,
            as_of=as_of,
            opener=opener,
            api_key=api_key if api_key is not None else _api_key(),
            now=now,
        )
        digest = write_private_json_once(capture_path, capture)
        reused = False

    try:
        observation = build_cash_observation(
            capture=capture,
            capture_sha256=digest,
            valuation_date=valuation_date,
            decision_date=decision_date,
            as_of_date=as_of,
        )
    except CashReturnError as exc:
        raise CashFetchError(str(exc)) from exc

    record = {
        "calendar_week_index": calendar_week_index,
        "decision_date": decision_date,
        "valuation_date": valuation_date,
        "observation": observation,
    }
    observation_path = directory / OBSERVATION_FILENAME
    if dry_run:
        status = "dry_run"
    elif observation_path.exists():
        existing, _ = _read_private_json(observation_path)
        if existing != record:
            raise CashFetchError(
                "a different cash observation is already stored for this week; inputs are immutable"
            )
        status = "idempotent"
    else:
        write_private_json_once(observation_path, record)
        status = "captured"
    return {
        "status": status,
        "observation_path": str(observation_path),
        "reused_capture": reused,
        "cash_status": observation["status"],
        "weekly_return": observation["weekly_return"],
        "provider_calls": len(attempts),
    }


def _build_capture(
    *,
    valuation_date: str,
    as_of: str,
    opener: Callable[[str], bytes] | None,
    api_key: str | None,
    now: Callable[[], datetime] | None,
) -> dict[str, Any]:
    clock = now if now is not None else (lambda: datetime.now(timezone.utc))
    valuation = datetime.strptime(valuation_date, "%Y%m%d").date()
    start = (valuation - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end = valuation.strftime("%Y-%m-%d")
    realtime_end = datetime.strptime(as_of, "%Y%m%d").strftime("%Y-%m-%d")
    capture: dict[str, Any] = {
        "schema_name": CAPTURE_SCHEMA_NAME,
        "schema_version": CAPTURE_SCHEMA_VERSION,
        "series_id": SERIES_ID,
        "vendor": VENDOR,
        "observed_at": clock().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "vintage_realtime_date": realtime_end,
        "observation_window_start": start,
        "observation_window_end": end,
        "fetch_status": FETCH_OK,
        "error_kind": None,
        "observations": [],
    }
    if not api_key:
        # Fail closed rather than fall back to the unpinned public download: an
        # unpinned read is the revised view, and using it would quietly put
        # hindsight into a point-in-time number.
        capture["fetch_status"] = FETCH_FAILED
        capture["vintage_realtime_date"] = None
        capture["error_kind"] = "MissingApiKey"
        validate_cash_capture(capture)
        return capture
    try:
        rows = fetch_vintages(
            observation_start=start,
            observation_end=end,
            realtime_end=realtime_end,
            api_key=api_key,
            opener=opener,
        )
        capture["observations"] = _collapse(rows, realtime_end=realtime_end)
        # Validated inside the try for the same reason its benchmark sibling is:
        # a vendor that answers with rows this module refuses is a failed fetch,
        # not an exception that escapes past the honesty fields below.
        validate_cash_capture(capture, as_of_date=as_of)
    except Exception as exc:  # noqa: BLE001 - the message may contain the key
        capture["fetch_status"] = FETCH_FAILED
        capture["vintage_realtime_date"] = None
        # Class only. urllib puts the failing URL, and therefore the key, into
        # the message it raises.
        capture["error_kind"] = type(exc).__name__
        capture["observations"] = []
        validate_cash_capture(capture, as_of_date=as_of)
    return capture


def _read_private_json(path: Path) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CashFetchError(f"{path.name} is not readable canonical JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise CashFetchError(f"{path.name} is not an object")
    return payload, artifact_sha256(payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--decision-date", required=True, help="YYYYMMDD")
    parser.add_argument("--valuation-date", required=True, help="YYYYMMDD")
    parser.add_argument("--calendar-week-index", required=True, type=int)
    parser.add_argument("--as-of-date", help="YYYYMMDD; defaults to today so future vintages fail closed")
    parser.add_argument("--inputs-root", type=Path, default=DEFAULT_INPUTS_ROOT)
    parser.add_argument("--confirm-user-authorization", action="store_true",
                        help="required for a live capture; a real vendor is called")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = capture_cash_week(
            decision_date=args.decision_date,
            valuation_date=args.valuation_date,
            calendar_week_index=args.calendar_week_index,
            as_of_date=args.as_of_date,
            inputs_root=args.inputs_root,
            dry_run=args.dry_run,
            confirm_user_authorization=args.confirm_user_authorization,
        )
    except (CashFetchError, CashReturnError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(f"{result['status']}: {result['observation_path']}  cash={result['cash_status']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
