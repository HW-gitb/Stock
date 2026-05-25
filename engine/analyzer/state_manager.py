"""Phase 3 JSON state accessors for the A-share short-term analyzer."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
STATE_ROOT = ROOT / "state" / "a_short"
POSITIONS_PATH = STATE_ROOT / "positions.json"
VETO_LOG_PATH = STATE_ROOT / "veto_log.json"
CIRCUIT_BREAKER_PATH = STATE_ROOT / "circuit_breaker.json"
EXECUTION_LOG_PATH = STATE_ROOT / "execution_log.csv"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write JSON via temp-file + os.replace."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_json_state(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        with Path(path).open("r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return dict(default)
    if not isinstance(data, dict):
        return dict(default)
    return data


def load_positions() -> dict[str, Any]:
    return load_json_state(POSITIONS_PATH, {
        "schema_version": "1.0.0",
        "preset": "a_short",
        "updated_at": None,
        "positions": [],
    })


def load_veto_log() -> dict[str, Any]:
    return load_json_state(VETO_LOG_PATH, {
        "schema_version": "1.0.0",
        "preset": "a_short",
        "updated_at": None,
        "records": [],
    })


def load_circuit_breaker() -> dict[str, Any]:
    return load_json_state(CIRCUIT_BREAKER_PATH, {
        "schema_version": "1.0.0",
        "preset": "a_short",
        "updated_at": None,
        "active": False,
        "reason": None,
        "triggered_at": None,
        "expires_at": None,
    })


def has_position(ts_code: str) -> bool:
    positions = load_positions().get("positions", [])
    return any(str(pos.get("ts_code")) == str(ts_code) for pos in positions if isinstance(pos, dict))


def is_circuit_breaker_active(now: datetime | str | None = None) -> bool:
    state = load_circuit_breaker()
    if not bool(state.get("active", False)):
        return False
    expires_at = _parse_state_datetime(state.get("expires_at"))
    if expires_at is None:
        return True
    now_dt = _coerce_now(now)
    return now_dt < expires_at


def _coerce_now(now: datetime | str | None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, str):
        parsed = _parse_state_datetime(now)
        if parsed is None:
            raise ValueError(f"invalid now datetime: {now}")
        return parsed
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def _parse_state_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def append_veto_record(record: dict[str, Any]) -> dict[str, Any]:
    payload = load_veto_log()
    records = payload.get("records")
    if not isinstance(records, list):
        records = []
    item = dict(record)
    item.setdefault("logged_at", utc_now_iso())
    records.append(item)
    payload["records"] = records
    payload["updated_at"] = utc_now_iso()
    atomic_write_json(VETO_LOG_PATH, payload)
    return payload
