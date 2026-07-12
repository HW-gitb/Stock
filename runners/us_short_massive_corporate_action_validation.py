"""Bounded Massive corporate-action / price capture — first validation cut, not reconciliation.

The packet at ``docs/us_short_massive_corporate_action_validation_packet_20260712.json`` freezes a
three-symbol, 12-call sample: Massive splits, dividends, adjusted daily bars, and unadjusted daily bars.
Raw wrappers stay gitignored under ``provider_samples/``; the tracked summary contains only status classes,
counts, and field names. This cut establishes source availability and response shape for a later, separately
reviewed event-to-price reconciliation. It never calculates returns, marks paper performance evaluable, selects
a provider, or authorizes DataHub, production, or ship-gate use.

Live use requires both the frozen packet and ``--confirm-user-authorization``. The API key is read only from
``MASSIVE_API_KEY`` and is never printed, logged, or placed in the tracked summary.
"""
from __future__ import annotations

import argparse
import json
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


PACKET_PATH = ROOT / "docs" / "us_short_massive_corporate_action_validation_packet_20260712.json"
PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_massive_corporate_action_validation_packet.schema.json"
SUMMARY_SCHEMA_PATH = ROOT / "schemas" / "us_short_massive_corporate_action_validation_summary.schema.json"

_FAMILIES = ("splits", "dividends", "daily_adjusted", "daily_unadjusted")
_URL_TEMPLATES = {
    "splits": "https://api.massive.com/stocks/v1/splits?ticker={ticker}&limit=1000&apiKey={key}",
    "dividends": "https://api.massive.com/stocks/v1/dividends?ticker={ticker}&limit=1000&apiKey={key}",
    "daily_adjusted": (
        "https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day/{frm}/{to}"
        "?adjusted=true&sort=asc&limit=50000&apiKey={key}"
    ),
    "daily_unadjusted": (
        "https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/day/{frm}/{to}"
        "?adjusted=false&sort=asc&limit=50000&apiKey={key}"
    ),
}


class MassiveCorporateActionValidationError(RuntimeError):
    """The bounded Massive corporate-action validation packet cannot safely run or record."""


def _schema_validator(schema_path: Path):
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:  # pragma: no cover - environment guard
        raise MassiveCorporateActionValidationError("jsonschema is required to validate the Massive packet") from exc
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MassiveCorporateActionValidationError("Massive validation schema cannot be loaded") from exc
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def _validate(value: dict[str, Any], schema_path: Path, label: str) -> None:
    errors = sorted(_schema_validator(schema_path).iter_errors(value), key=lambda error: list(error.path))
    if errors:
        path = ".".join(str(part) for part in errors[0].path) or "<root>"
        raise MassiveCorporateActionValidationError(f"{label} failed schema validation at {path}: {errors[0].message}")


def load_packet(packet_path: Path = PACKET_PATH) -> dict[str, Any]:
    try:
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MassiveCorporateActionValidationError("Massive validation packet cannot be loaded") from exc
    if not isinstance(packet, dict):
        raise MassiveCorporateActionValidationError("Massive validation packet root must be an object")
    _validate(packet, PACKET_SCHEMA_PATH, "Massive validation packet")
    symbols = [item["symbol"] for item in packet["sample"]]
    if len(set(symbols)) != len(symbols):
        raise MassiveCorporateActionValidationError("Massive validation sample symbols must be unique")
    return packet


def _repo_relative_path(value: str, *, field: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/") or ":" in value:
        raise MassiveCorporateActionValidationError(f"{field} must be a safe repo-relative path")
    path = (ROOT / value).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise MassiveCorporateActionValidationError(f"{field} escapes the repository") from exc
    return path


def _raw_root_is_gitignored(raw_root: Path) -> bool:
    try:
        sample_validation.validate_raw_root(raw_root)
        import subprocess

        result = subprocess.run(
            ["git", "check-ignore", str(raw_root)], cwd=str(ROOT), capture_output=True, text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def _url_for(family: str, symbol: str, packet: dict[str, Any], api_key: str) -> str:
    if family not in _URL_TEMPLATES:
        raise MassiveCorporateActionValidationError(f"endpoint family outside allowlist: {family!r}")
    safe_symbol = urllib.parse.quote(symbol, safe="")
    window = packet["scope"]["price_window"]
    return _URL_TEMPLATES[family].format(
        ticker=safe_symbol,
        frm=window["from"],
        to=window["to"],
        key=api_key,
    )


def _result_container(payload: Any) -> tuple[str | None, list[Any]]:
    if isinstance(payload, list):
        return "<root-list>", payload
    if isinstance(payload, dict):
        for key in ("results", "data", "historical"):
            value = payload.get(key)
            if isinstance(value, list):
                return key, value
    return None, []


def _shape_of(payload: Any) -> dict[str, Any]:
    container_key, rows = _result_container(payload)
    item_keys = sorted({str(key) for row in rows if isinstance(row, dict) for key in row})
    return {
        "payload_type": type(payload).__name__,
        "top_level_key_names": sorted(payload.keys()) if isinstance(payload, dict) else [],
        "result_container_key": container_key,
        "result_count": len(rows),
        "result_item_key_names": item_keys,
    }


def _scan_summary_safe(text: str, sensitive_values: list[str]) -> None:
    lowered = text.lower()
    for fragment in ("apikey=", "api.massive.com", "http://", "https://", '"payload"', '"raw_payload"'):
        if fragment in lowered:
            raise MassiveCorporateActionValidationError(f"tracked summary contains forbidden fragment: {fragment}")
    for value in sensitive_values:
        if value and value in text:
            raise MassiveCorporateActionValidationError("tracked summary contains an environment secret")


def _write_summary(summary: dict[str, Any], summary_path: Path, sensitive_values: list[str]) -> None:
    _validate(summary, SUMMARY_SCHEMA_PATH, "Massive validation summary")
    text = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    _scan_summary_safe(text, sensitive_values)
    sample_validation.write_json_atomic(summary, summary_path)


def run_capture(
    *,
    confirm_user_authorization: bool,
    packet_path: Path = PACKET_PATH,
    client: sample_validation.JsonHttpClient | None = None,
    sleep_func: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Capture the frozen 12-call sample. It writes raw wrappers plus a no-value tracked summary only."""
    if not confirm_user_authorization:
        raise MassiveCorporateActionValidationError("Massive capture requires explicit per-execution user authorization")
    packet = load_packet(packet_path)
    raw_root = _repo_relative_path(packet["storage"]["raw_payload_root"], field="raw_payload_root")
    summary_path = _repo_relative_path(packet["storage"]["tracked_summary_path"], field="tracked_summary_path")
    if not _raw_root_is_gitignored(raw_root):
        raise MassiveCorporateActionValidationError("Massive raw capture root is not confirmed gitignored")

    api_key = sample_validation.read_required_env("MASSIVE_API_KEY")
    client = client or sample_validation.JsonHttpClient()
    symbols = [item["symbol"] for item in packet["sample"]]
    families = packet["scope"]["endpoint_families"]
    max_calls = packet["execution"]["max_total_endpoint_calls"]
    pace_seconds = packet["execution"]["pace_seconds"]
    headers = {"User-Agent": "StockSystem/0.1 us-short-massive-corporate-action-validation"}

    records: list[sample_validation.FetchRecord] = []
    endpoint_results: list[dict[str, Any]] = []
    for symbol in symbols:
        for family in families:
            if family not in _FAMILIES:
                raise MassiveCorporateActionValidationError(f"packet endpoint family outside allowlist: {family!r}")
            sample_validation.assert_endpoint_budget_available(records, max_calls)
            if records:
                sleep_func(pace_seconds)
            record = sample_validation.fetch_and_store(
                client,
                url=_url_for(family, symbol, packet, api_key.value),
                provider_id="massive",
                endpoint_family=family,
                symbol=symbol,
                raw_root=raw_root,
                headers=headers,
            )
            records.append(record)
            endpoint_results.append(
                {
                    "symbol": symbol,
                    "endpoint_family": family,
                    "http_status": record.http_status,
                    "ok": bool(record.ok),
                    "error_type": record.error_type,
                    "response_shape": _shape_of(record.payload) if record.ok else None,
                }
            )

    summary = {
        "scope": {
            "authorization_ref": packet["authorization_ref"],
            "provider_id": "massive",
            "sample_symbols": symbols,
            "endpoint_families": families,
            "max_total_endpoint_calls": max_calls,
            "actual_total_endpoint_calls": len(records),
            "pace_seconds": pace_seconds,
            "purpose": packet["scope"]["purpose"],
        },
        "endpoint_results": endpoint_results,
        "storage": {
            "raw_payload_root": packet["storage"]["raw_payload_root"],
            "raw_payload_root_gitignored": True,
            "tracked_summary_contains_secrets": False,
            "tracked_summary_contains_request_urls": False,
            "tracked_summary_contains_raw_payload_rows": False,
            "tracked_summary_contains_price_values": False,
            "tracked_summary_contains_event_values": False,
        },
        "boundary": {
            "provider_selected": False,
            "corporate_action_reconciliation_performed": False,
            "return_calculation_performed": False,
            "paper_gate_evaluable_claimed": False,
            "ship_gate_or_production_authorized": False,
            "datahub_or_runner_consumption_authorized": False,
            "sr_provider_001_closed": False,
        },
    }
    _write_summary(summary, summary_path, [api_key.value])
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the bounded Massive corporate-action validation capture")
    parser.add_argument("--packet", type=Path, default=PACKET_PATH)
    parser.add_argument("--confirm-user-authorization", action="store_true")
    parser.add_argument("--dry-run-env", action="store_true", help="validate packet, key presence, and raw path; no network")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        packet = load_packet(args.packet)
        raw_root = _repo_relative_path(packet["storage"]["raw_payload_root"], field="raw_payload_root")
        if args.dry_run_env:
            import os

            print(f"MASSIVE_API_KEY present: {bool(os.environ.get('MASSIVE_API_KEY'))}")
            print(f"raw root gitignored: {_raw_root_is_gitignored(raw_root)}")
            print(f"planned calls: {packet['execution']['max_total_endpoint_calls']}")
            return 0
        summary = run_capture(confirm_user_authorization=args.confirm_user_authorization, packet_path=args.packet)
    except MassiveCorporateActionValidationError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(f"capture complete: {summary['scope']['actual_total_endpoint_calls']} calls")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
