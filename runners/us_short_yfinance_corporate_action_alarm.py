"""Default-dry-run, one-ticker yfinance daily split/dividend smoke alarm."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path
from engine.us_short_security_identity import SecurityIdentityError, validate_security_identity
from engine.us_short_yfinance_corporate_action_alarm import (
    YFinanceCorporateActionAlarmError,
    evaluate_yfinance_daily_alarm,
)


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/us_short_yfinance_corporate_action_alarm.schema.json"
DEFAULT_OUTPUT = (ROOT / "state/us_short/lifecycle/yfinance_corporate_action_alarm.json").resolve()


class YFinanceCorporateActionFetchError(ValueError):
    """The authorization, provider, normalized row, private path, or schema failed."""


def _read_identity(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return validate_security_identity(value)
    except (OSError, UnicodeError, json.JSONDecodeError, SecurityIdentityError) as exc:
        raise YFinanceCorporateActionFetchError("identity is not readable valid security-identity JSON") from exc


def _expected_date(value: str) -> datetime:
    if type(value) is not str:
        raise YFinanceCorporateActionFetchError("expected_price_date must be YYYY-MM-DD")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError as exc:
        raise YFinanceCorporateActionFetchError("expected_price_date must be a real YYYY-MM-DD") from exc
    if parsed.strftime("%Y-%m-%d") != value:
        raise YFinanceCorporateActionFetchError("expected_price_date must be canonical YYYY-MM-DD")
    return parsed


def _observed_at(value: str | None) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if type(value) is not str:
        raise YFinanceCorporateActionFetchError("observed_at must be an aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise YFinanceCorporateActionFetchError("observed_at must be an aware ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise YFinanceCorporateActionFetchError("observed_at must be timezone-aware")
    return value


def _row_date(index: Any) -> str | None:
    try:
        if hasattr(index, "date"):
            return index.date().strftime("%Y-%m-%d")
        text = str(index)
    except Exception:
        return None
    candidate = text[:10]
    try:
        datetime.strptime(candidate, "%Y-%m-%d")
    except ValueError:
        return None
    return candidate


def _history_observation(module: Any, identity: dict[str, Any], expected: datetime, observed_at: str) -> dict[str, Any]:
    ticker_name = identity["current_ticker"]
    network_access_performed = False
    try:
        network_access_performed = True
        ticker = module.Ticker(ticker_name)
        history = ticker.history(
            start=expected.strftime("%Y-%m-%d"),
            end=(expected + timedelta(days=1)).strftime("%Y-%m-%d"),
            auto_adjust=False,
            actions=True,
            repair=False,
        )
        rows: list[tuple[str, Any]] = []
        if history is not None and not bool(getattr(history, "empty", False)):
            for index, row in history.iterrows():
                row_date = _row_date(index)
                if row_date is not None:
                    rows.append((row_date, row))
        if not rows:
            raise LookupError("no rows")
        wanted = expected.strftime("%Y-%m-%d")
        row_date, row = next((item for item in rows if item[0] == wanted), rows[-1])
        returned_ticker = getattr(ticker, "ticker", None)
        return {
            "source_ticker": ticker_name,
            "returned_ticker": returned_ticker if type(returned_ticker) is str else None,
            "expected_price_date": wanted,
            "observed_at": observed_at,
            "fetch_status": "ok",
            "price_date": row_date,
            "close": row.get("Close"),
            "stock_splits": row.get("Stock Splits", 0.0),
            "dividends": row.get("Dividends", 0.0),
            "network_access_performed": network_access_performed,
        }
    except Exception:
        return {
            "source_ticker": ticker_name,
            "returned_ticker": None,
            "expected_price_date": expected.strftime("%Y-%m-%d"),
            "observed_at": observed_at,
            "fetch_status": "error",
            "price_date": None,
            "close": None,
            "stock_splits": None,
            "dividends": None,
            "network_access_performed": network_access_performed,
        }


def _validate_result(result: dict[str, Any]) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    if list(Draft7Validator(schema).iter_errors(result)):
        raise YFinanceCorporateActionFetchError("alarm output failed its schema")


def _write_json_atomic(value: dict[str, Any], path: Path) -> None:
    try:
        reject_nonprivate_output_path(path)
    except PrivatePathError as exc:
        raise YFinanceCorporateActionFetchError("output path is not provably private") from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def run_yfinance_alarm(
    *,
    identity_path: Path,
    output_path: Path,
    expected_price_date: str,
    confirm_user_authorization: bool,
    observed_at: str | None = None,
    importer=importlib.import_module,
) -> dict[str, Any]:
    output_path = Path(output_path).resolve()
    try:
        reject_nonprivate_output_path(output_path)
    except PrivatePathError as exc:
        raise YFinanceCorporateActionFetchError("output path is not provably private") from exc
    expected = _expected_date(expected_price_date)
    if confirm_user_authorization is not True:
        raise YFinanceCorporateActionFetchError("yfinance fetch requires explicit per-execution user authorization")
    identity = _read_identity(Path(identity_path))
    observed = _observed_at(observed_at)
    try:
        module = importer("yfinance")
    except Exception:
        module = None
    observation = (_history_observation(module, identity, expected, observed)
                   if module is not None else {
                       "source_ticker": identity["current_ticker"], "returned_ticker": None,
                       "expected_price_date": expected.strftime("%Y-%m-%d"),
                       "observed_at": observed, "fetch_status": "error", "price_date": None,
                       "close": None, "stock_splits": None, "dividends": None,
                       "network_access_performed": False,
                   })
    try:
        result = evaluate_yfinance_daily_alarm(identity, observation)
    except YFinanceCorporateActionAlarmError:
        # yfinance is low-trust/non-critical. A malformed provider row is the same safe outcome as a down
        # source for this alarm: freeze only this ticker, expose no raw exception, and never abort a future loop.
        result = evaluate_yfinance_daily_alarm(identity, {
            "source_ticker": identity["current_ticker"], "returned_ticker": None,
            "expected_price_date": expected.strftime("%Y-%m-%d"),
            "observed_at": observation["observed_at"], "fetch_status": "error", "price_date": None,
            "close": None, "stock_splits": None, "dividends": None,
            "network_access_performed": observation["network_access_performed"],
        })
    _validate_result(result)
    _write_json_atomic(result, output_path)
    return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one low-trust yfinance split/dividend daily smoke alarm. Default dry-run.")
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--expected-price-date", required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--observed-at")
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.run:
        print(json.dumps({"status": "dry_run", "provider_calls": 0, "source_trust": "low_trust_advisory",
                          "selection_use_allowed": False}, indent=2))
        return 0
    try:
        result = run_yfinance_alarm(
            identity_path=args.identity,
            output_path=args.out,
            expected_price_date=args.expected_price_date,
            observed_at=args.observed_at,
            confirm_user_authorization=args.confirm_user_authorization,
        )
    except YFinanceCorporateActionFetchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({"alarm_status": result["alarm_status"], "output": str(Path(args.out).resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
