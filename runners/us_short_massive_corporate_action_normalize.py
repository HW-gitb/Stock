"""Normalize the frozen Massive corporate-action capture into private source-bound packets.

This is an offline-only adapter. It validates the exact 3-symbol x 4-family wrapper
matrix captured by ``us_short_massive_corporate_action_validation.py`` and writes
normalized values only under the Git-ignored ``provider_samples/`` tree. It makes no
network request and does not perform reconciliation, calculate returns, or authorize
paper evaluation, provider selection, production, DataHub, or a ship gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, time, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
_PYTHON_LIBS = ROOT / ".tools" / "python_libs"
if _PYTHON_LIBS.exists() and str(_PYTHON_LIBS) not in sys.path:
    sys.path.insert(0, str(_PYTHON_LIBS))

from runners import us_egs_sample_validation as sample_validation  # noqa: E402
from runners import us_short_massive_corporate_action_validation as capture  # noqa: E402


CAPTURE_PACKET_PATH = ROOT / "docs" / "us_short_massive_corporate_action_validation_packet_20260712.json"
SCHEMA_PATH = ROOT / "schemas" / "us_short_massive_corporate_action_normalized_packet.schema.json"
PROVIDER_SAMPLES_ROOT = ROOT / "provider_samples"
_FAMILIES = ("splits", "dividends", "daily_adjusted", "daily_unadjusted")
_EVENT_FAMILIES = ("splits", "dividends")
_SESSION_TIMEZONE = ZoneInfo("America/New_York")


class MassiveCorporateActionNormalizeError(RuntimeError):
    """The frozen Massive wrappers cannot safely be normalized into private packets."""


def _schema_validator():
    try:
        from jsonschema import Draft7Validator
    except ImportError as exc:  # pragma: no cover - environment guard
        raise MassiveCorporateActionNormalizeError("jsonschema is required to validate normalized packets") from exc
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MassiveCorporateActionNormalizeError("normalized-packet schema cannot be loaded") from exc
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def _validate_packet(packet: dict[str, Any]) -> None:
    errors = sorted(_schema_validator().iter_errors(packet), key=lambda error: list(error.path))
    if errors:
        path = ".".join(str(part) for part in errors[0].path) or "<root>"
        raise MassiveCorporateActionNormalizeError(f"normalized packet failed schema validation at {path}")


def _repo_path(value: str, *, field: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/") or ":" in value:
        raise MassiveCorporateActionNormalizeError(f"{field} must be a safe repo-relative path")
    path = (ROOT / value).resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise MassiveCorporateActionNormalizeError(f"{field} escapes the repository") from exc
    return path


def _is_gitignored_provider_samples_path(path: Path) -> bool:
    try:
        path.resolve().relative_to(PROVIDER_SAMPLES_ROOT.resolve())
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


def _load_capture_binding(packet_path: Path) -> tuple[dict[str, Any], list[str], str]:
    packet = capture.load_packet(packet_path)
    families = packet["scope"]["endpoint_families"]
    symbols = [item["symbol"] for item in packet["sample"]]
    if families != list(_FAMILIES) or len(symbols) != 3 or len(set(symbols)) != 3:
        raise MassiveCorporateActionNormalizeError("capture packet does not describe the frozen wrapper matrix")
    try:
        packet_digest = hashlib.sha256(packet_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise MassiveCorporateActionNormalizeError("capture packet cannot be read for source binding") from exc
    return packet, symbols, packet_digest


def _read_wrapper(raw_root: Path, symbol: str, family: str) -> tuple[dict[str, Any], str]:
    path = raw_root / "massive" / symbol / f"{family}.json"
    try:
        content = path.read_bytes()
        wrapper = json.loads(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MassiveCorporateActionNormalizeError("frozen raw wrapper is missing or unreadable") from exc
    required_keys = {"provider_id", "endpoint_family", "symbol", "http_status", "ok", "error_type", "payload"}
    if not isinstance(wrapper, dict) or set(wrapper) != required_keys:
        raise MassiveCorporateActionNormalizeError("frozen raw wrapper has an unexpected envelope")
    if (
        wrapper["provider_id"] != "massive"
        or wrapper["endpoint_family"] != family
        or wrapper["symbol"] != symbol
        or wrapper["http_status"] != 200
        or wrapper["ok"] is not True
        or wrapper["error_type"] is not None
        or not isinstance(wrapper["payload"], dict)
    ):
        raise MassiveCorporateActionNormalizeError("frozen raw wrapper identity or success state is invalid")
    payload = wrapper["payload"]
    if payload.get("status") != "OK" or not isinstance(payload.get("results"), list):
        raise MassiveCorporateActionNormalizeError("frozen raw wrapper payload shape is invalid")
    return payload, hashlib.sha256(content).hexdigest()


def _date(value: Any) -> str:
    if not isinstance(value, str):
        raise MassiveCorporateActionNormalizeError("corporate-action date is invalid")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise MassiveCorporateActionNormalizeError("corporate-action date is invalid") from exc
    if parsed.isoformat() != value:
        raise MassiveCorporateActionNormalizeError("corporate-action date is invalid")
    return value


def _positive_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MassiveCorporateActionNormalizeError(f"{label} must be a finite positive number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized <= 0:
        raise MassiveCorporateActionNormalizeError(f"{label} must be a finite positive number")
    return normalized


def _required_event_id(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (str, int)) or (isinstance(value, str) and not value):
        raise MassiveCorporateActionNormalizeError("corporate-action event identity is invalid")


def _normalize_events(symbol: str, family: str, payload: dict[str, Any], source_digest: str) -> list[dict[str, Any]]:
    if family not in _EVENT_FAMILIES:
        raise MassiveCorporateActionNormalizeError("event family outside frozen matrix")
    rows: list[tuple[str, int, dict[str, Any]]] = []
    date_field = "execution_date" if family == "splits" else "ex_dividend_date"
    for index, row in enumerate(payload["results"]):
        if not isinstance(row, dict) or row.get("ticker") != symbol:
            raise MassiveCorporateActionNormalizeError("corporate-action row identity is invalid")
        _required_event_id(row.get("id"))
        event_date = _date(row.get(date_field))
        rows.append((event_date, index, row))

    normalized: list[dict[str, Any]] = []
    event_type = "split" if family == "splits" else "dividend"
    for ordinal, (event_date, _, row) in enumerate(sorted(rows, key=lambda item: (item[0], item[1])), start=1):
        event = {
            "event_id": f"{symbol}-{event_type}-{event_date.replace('-', '')}-{source_digest[:12]}-{ordinal:04d}",
            "event_type": event_type,
            "event_date": event_date,
            "source_family": family,
            "source_ref_sha256": source_digest,
        }
        if family == "splits":
            event["split_from"] = _positive_number(row.get("split_from"), label="split_from")
            event["split_to"] = _positive_number(row.get("split_to"), label="split_to")
        normalized.append(event)
    return normalized


def _session_date(timestamp_ms: Any) -> str:
    if isinstance(timestamp_ms, bool) or not isinstance(timestamp_ms, int):
        raise MassiveCorporateActionNormalizeError("daily timestamp must be an integer millisecond value")
    try:
        local = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).astimezone(_SESSION_TIMEZONE)
    except (OverflowError, OSError, ValueError) as exc:
        raise MassiveCorporateActionNormalizeError("daily timestamp is outside the supported session range") from exc
    if local.timetz().replace(tzinfo=None) != time(0, 0):
        raise MassiveCorporateActionNormalizeError("daily timestamp is not New York midnight")
    return local.date().isoformat()


def _normalize_prices(symbol: str, family: str, payload: dict[str, Any], source_digest: str) -> list[dict[str, Any]]:
    adjusted = family == "daily_adjusted"
    if family not in ("daily_adjusted", "daily_unadjusted"):
        raise MassiveCorporateActionNormalizeError("price family outside frozen matrix")
    if payload.get("ticker") != symbol or payload.get("adjusted") is not adjusted:
        raise MassiveCorporateActionNormalizeError("daily payload identity or adjustment mode is invalid")
    rows: list[dict[str, Any]] = []
    sessions: set[str] = set()
    for row in payload["results"]:
        if not isinstance(row, dict):
            raise MassiveCorporateActionNormalizeError("daily row shape is invalid")
        session_date = _session_date(row.get("t"))
        if session_date in sessions:
            raise MassiveCorporateActionNormalizeError("daily payload repeats a New York session date")
        sessions.add(session_date)
        rows.append(
            {
                "symbol": symbol,
                "session_date": session_date,
                "adjustment_mode": "adjusted" if adjusted else "unadjusted",
                "source_family": family,
                "source_ref_sha256": source_digest,
                "close": _positive_number(row.get("c"), label="daily close"),
            }
        )
    return sorted(rows, key=lambda row: row["session_date"])


def _write_packet(output_path: Path, packet: dict[str, Any]) -> None:
    sample_validation.write_json_atomic(packet, output_path)


def normalize_capture(
    *,
    confirm_user_authorization: bool,
    packet_path: Path = CAPTURE_PACKET_PATH,
    raw_root: Path | None = None,
    output_root: Path | None = None,
) -> dict[str, int]:
    """Normalize all frozen wrappers after explicit authorization, without any provider call."""
    if not confirm_user_authorization:
        raise MassiveCorporateActionNormalizeError("normalization requires explicit per-execution user authorization")
    capture_packet, symbols, capture_digest = _load_capture_binding(packet_path)
    raw_root = raw_root or _repo_path(capture_packet["storage"]["raw_payload_root"], field="raw_payload_root")
    output_root = output_root or raw_root.parent / "normalized"
    raw_root = raw_root.resolve()
    output_root = output_root.resolve()
    if not _is_gitignored_provider_samples_path(raw_root) or not _is_gitignored_provider_samples_path(output_root):
        raise MassiveCorporateActionNormalizeError("raw and normalized roots must be confirmed Git-ignored provider_samples paths")
    if output_root.exists():
        raise MassiveCorporateActionNormalizeError("normalized output root already exists; refusing to overwrite private packets")

    packets: list[tuple[Path, dict[str, Any]]] = []
    wrapper_count = 0
    for symbol in symbols:
        payloads: dict[str, dict[str, Any]] = {}
        digests: dict[str, str] = {}
        for family in _FAMILIES:
            payload, digest = _read_wrapper(raw_root, symbol, family)
            payloads[family] = payload
            digests[family] = digest
            wrapper_count += 1
        events = _normalize_events(symbol, "splits", payloads["splits"], digests["splits"])
        events.extend(_normalize_events(symbol, "dividends", payloads["dividends"], digests["dividends"]))
        prices = _normalize_prices(symbol, "daily_adjusted", payloads["daily_adjusted"], digests["daily_adjusted"])
        prices.extend(_normalize_prices(symbol, "daily_unadjusted", payloads["daily_unadjusted"], digests["daily_unadjusted"]))
        packet = {
            "schema_name": "us_short_massive_corporate_action_normalized_packet",
            "schema_version": "1.0.0",
            "capture_binding": {
                "capture_packet_schema_name": "us_short_massive_corporate_action_validation_packet",
                "capture_packet_sha256": capture_digest,
                "provider_id": "massive",
                "session_timezone": "America/New_York",
                "day_timestamp_semantics": "new_york_midnight_timestamp",
                "raw_wrapper_sha256": digests,
            },
            "symbol": symbol,
            "normalized_events": events,
            "normalized_price_rows": prices,
            "boundary": {
                "provider_call_performed_during_normalization": False,
                "raw_payload_read_and_normalized": True,
                "corporate_action_reconciliation_performed": False,
                "return_calculation_performed": False,
                "paper_gate_evaluable_claimed": False,
                "ship_gate_or_production_authorized": False,
            },
        }
        _validate_packet(packet)
        packets.append((output_root / f"{symbol}.json", packet))

    output_root.mkdir(parents=True)
    for output_path, packet in packets:
        _write_packet(output_path, packet)
    return {"normalized_packet_count": len(packets), "raw_wrapper_count": wrapper_count}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize the frozen Massive corporate-action wrappers offline")
    parser.add_argument("--confirm-user-authorization", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = normalize_capture(confirm_user_authorization=args.confirm_user_authorization)
    except MassiveCorporateActionNormalizeError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(f"normalized packets: {result['normalized_packet_count']}; raw wrappers: {result['raw_wrapper_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
