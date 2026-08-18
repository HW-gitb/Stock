"""A-short hard admission gate for corrected Tushare 扣非 TTM profit."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path

import jsonschema
import pandas as pd

from engine.a_short_regime_classifier import FORWARD_RETURN_BASIS
from engine.a_short_regime_comparison import backfill_forward_return_values


LOSS_MAKING_REASON = "loss_making_ttm_profit_dedt_non_positive"
UNAVAILABLE_REASON = "ttm_profit_dedt_unavailable"
ADMISSION_REASONS = frozenset({LOSS_MAKING_REASON, UNAVAILABLE_REASON})
TRACKER_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "a_short_loss_making_exclusion_tracker.schema.json"
_DATE8_RE = re.compile(r"^[0-9]{8}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{32}$")
_HORIZONS = ("h1", "h3", "h5", "h10")
_SOURCE_FIELDS = (
    "as_of", "run_revision_id", "official_rank_reconciliation", "ts_code",
    "ttm_profit_dedt", "final_score", "pre_admission_rank", "exclusion_reason",
)


def _finite_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _ranked(scored_df: pd.DataFrame) -> pd.DataFrame:
    required = {"ts_code", "final_score", "l4_score", "pct_20d_n"}
    missing = sorted(required - set(scored_df.columns))
    if missing:
        raise ValueError(f"loss-making admission missing ranking columns: {missing}")
    return scored_df.sort_values(
        ["final_score", "l4_score", "pct_20d_n"],
        ascending=[False, False, False],
    )


def apply_loss_making_admission(scored_df: pd.DataFrame):
    """Partition a complete L5 frame without changing scores or survivor order."""
    if not isinstance(scored_df, pd.DataFrame) or "ts_code" not in scored_df.columns:
        raise ValueError("loss-making admission requires a dataframe with ts_code")
    if scored_df["ts_code"].duplicated().any():
        raise ValueError("loss-making admission received duplicate ts_code")

    ranked = _ranked(scored_df)
    pre_rank = {
        str(code): rank for rank, code in enumerate(ranked["ts_code"].astype(str), start=1)
    }
    profits = scored_df.get(
        "ttm_profit_dedt",
        pd.Series([None] * len(scored_df), index=scored_df.index),
    )
    numeric = profits.map(_finite_number)
    admitted_mask = numeric.notna() & (numeric > 0)
    reasons = {}
    audit = []
    for index, row in ranked.iterrows():
        code = str(row["ts_code"])
        value = numeric.loc[index]
        reason = None if pd.notna(value) and value > 0 else (
            LOSS_MAKING_REASON if pd.notna(value) else UNAVAILABLE_REASON
        )
        if reason is not None:
            reasons[code] = reason
        audit.append({
            "ts_code": code,
            "ttm_profit_dedt": None if pd.isna(value) else float(value),
            "final_score": _finite_number(row.get("final_score")),
            "pre_admission_rank": pre_rank[code],
            "reason": reason,
        })
    admitted = scored_df.loc[admitted_mask].copy()
    return admitted, reasons, pd.DataFrame(
        audit,
        columns=["ts_code", "ttm_profit_dedt", "final_score", "pre_admission_rank", "reason"],
    )


def _validate_identity(as_of: str, run_revision_id: str) -> tuple[str, str]:
    as_of = str(as_of or "")
    run_revision_id = str(run_revision_id or "")
    if not _DATE8_RE.fullmatch(as_of):
        raise ValueError("loss-making tracker as_of must be YYYYMMDD")
    if not _REVISION_RE.fullmatch(run_revision_id):
        raise ValueError("loss-making tracker run_revision_id must be 32 lowercase hex characters")
    return as_of, run_revision_id


def _tracker_payload(records=None) -> dict:
    return {
        "schema_name": "a_short_loss_making_exclusion_tracker",
        "schema_version": "1.0.0",
        "forward_return_basis": json.loads(json.dumps(FORWARD_RETURN_BASIS)),
        "records": list(records or []),
    }


def validate_loss_making_exclusion_tracker(payload: dict) -> bool:
    jsonschema.validate(payload, json.loads(TRACKER_SCHEMA_PATH.read_text(encoding="utf-8")))
    seen = set()
    for record in payload["records"]:
        key = (record["as_of"], record["run_revision_id"], record["ts_code"])
        if key in seen:
            raise ValueError(f"loss-making tracker duplicate key {key}")
        seen.add(key)
        expected_pending = [
            horizon for horizon in _HORIZONS
            if record["forward_returns"].get(horizon) is None
        ]
        if record["forward_returns_pending"] != expected_pending:
            raise ValueError("loss-making tracker pending horizons do not match returns")
        if record["backfill_complete"] != (not expected_pending):
            raise ValueError("loss-making tracker backfill_complete does not match returns")
        if _finite_number(record["final_score"]) is None:
            raise ValueError("loss-making tracker final_score must be finite")
        ttm = _finite_number(record["ttm_profit_dedt"])
        if record["ttm_profit_dedt"] is not None and ttm is None:
            raise ValueError("loss-making tracker ttm_profit_dedt must be finite or null")
        if record["exclusion_reason"] == LOSS_MAKING_REASON and (ttm is None or ttm > 0):
            raise ValueError("loss-making tracker loss reason must have finite non-positive ttm_profit_dedt")
        if record["exclusion_reason"] == UNAVAILABLE_REASON and ttm is not None:
            raise ValueError("loss-making tracker unavailable reason must have null ttm_profit_dedt")
    return True


def _official_rank_reference(rank_csv_path: str | Path, as_of: str, run_revision_id: str,
                             project_root: str | Path | None = None) -> str:
    as_of, run_revision_id = _validate_identity(as_of, run_revision_id)
    rank_path = Path(rank_csv_path).resolve()
    marker_path = rank_path.parent / "official_publish.json"
    if not rank_path.is_file() or not marker_path.is_file():
        raise ValueError("loss-making tracker requires the official rank CSV and official_publish marker")
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("loss-making tracker official_publish marker is unreadable") from exc
    ref = (marker.get("files") or {}).get("rank_universe_reconciliation") or {}
    digest = hashlib.sha256(rank_path.read_bytes()).hexdigest()
    if (marker.get("schema_name") != "a_short_egs_official_publish"
            or marker.get("stage_status") != "complete"
            or str(marker.get("decision_as_of") or marker.get("trade_date")) != as_of
            or marker.get("run_revision_id") != run_revision_id
            or ref.get("path") != rank_path.name
            or ref.get("sha256") != digest):
        raise ValueError("loss-making tracker official rank CSV is not bound by the official publish marker")
    base = Path(project_root).resolve() if project_root is not None else Path(__file__).resolve().parents[1]
    try:
        relative = rank_path.relative_to(base).as_posix()
    except ValueError as exc:
        raise ValueError("loss-making tracker rank CSV is outside the project root") from exc
    expected = f"result/a_short/{as_of}/revisions/{run_revision_id}/rank_universe_reconciliation.csv"
    if relative != expected:
        raise ValueError("loss-making tracker rank CSV is not the requested official revision path")
    return relative


def _new_tracker_record(row: dict, *, as_of: str, run_revision_id: str,
                        official_reference: str) -> dict:
    code = str(row.get("ts_code") or "").strip()
    reason = str(row.get("reason") or "").strip()
    if not code or reason not in ADMISSION_REASONS:
        raise ValueError("loss-making tracker rank row has invalid code or admission reason")
    ttm = _finite_number(row.get("ttm_profit_dedt"))
    if reason == LOSS_MAKING_REASON and (ttm is None or ttm > 0):
        raise ValueError(f"loss-making tracker ttm/reason mismatch for {code}")
    if reason == UNAVAILABLE_REASON and ttm is not None:
        raise ValueError(f"loss-making tracker unavailable/reason mismatch for {code}")
    score = _finite_number(row.get("final_score"))
    if score is None:
        raise ValueError(f"loss-making tracker final_score unavailable for {code}")
    rank_value = _finite_number(row.get("pre_admission_rank"))
    if rank_value is None or not rank_value.is_integer() or rank_value < 1:
        raise ValueError(f"loss-making tracker pre_admission_rank invalid for {code}")
    rank = int(rank_value)
    return {
        "as_of": as_of,
        "run_revision_id": run_revision_id,
        "official_rank_reconciliation": official_reference,
        "ts_code": code,
        "ttm_profit_dedt": ttm,
        "final_score": score,
        "pre_admission_rank": rank,
        "exclusion_reason": reason,
        "forward_returns": {horizon: None for horizon in _HORIZONS},
        "forward_returns_pending": list(_HORIZONS),
        "backfill_complete": False,
    }


def _backfill_tracker_record(record: dict, csi1000, as_of_now: str) -> dict:
    updated = dict(record)
    values = backfill_forward_return_values(
        updated["forward_returns"], updated["as_of"], csi1000, as_of_now
    )
    updated["forward_returns"] = values
    updated["forward_returns_pending"] = [horizon for horizon in _HORIZONS if values[horizon] is None]
    updated["backfill_complete"] = not updated["forward_returns_pending"]
    return updated


def _load_tracker(path: Path) -> tuple[dict, bytes | None]:
    if not path.exists():
        return _tracker_payload(), None
    raw = path.read_bytes()
    payload = json.loads(raw.decode("utf-8"))
    validate_loss_making_exclusion_tracker(payload)
    return payload, raw


def merge_loss_making_exclusion_tracker(path: str | Path, records: list[dict]) -> dict:
    path = Path(path)
    payload, previous_bytes = _load_tracker(path)
    by_key = {
        (item["as_of"], item["run_revision_id"], item["ts_code"]): item
        for item in payload["records"]
    }
    for record in records:
        key = (record["as_of"], record["run_revision_id"], record["ts_code"])
        old = by_key.get(key)
        if old is not None:
            if any(old[field] != record[field] for field in _SOURCE_FIELDS):
                raise ValueError(f"loss-making tracker source conflict for key {key}")
            if old == record:
                continue
        by_key[key] = dict(record)
    merged = _tracker_payload(sorted(by_key.values(), key=lambda item: (
        item["as_of"], item["run_revision_id"], item["pre_admission_rank"], item["ts_code"]
    )))
    validate_loss_making_exclusion_tracker(merged)
    encoded = (json.dumps(merged, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if previous_bytes is not None and encoded == previous_bytes:
        return payload
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return merged


def update_loss_making_exclusion_tracker(path: str | Path, *, official_rank_csv_path: str | Path,
                                          as_of: str, run_revision_id: str, csi1000,
                                          as_of_now: str, project_root: str | Path | None = None) -> dict:
    as_of, run_revision_id = _validate_identity(as_of, run_revision_id)
    official_reference = _official_rank_reference(
        official_rank_csv_path, as_of, run_revision_id, project_root=project_root
    )
    if csi1000 is None or getattr(csi1000, "empty", True):
        raise ValueError("loss-making tracker CSI1000 data is unavailable; tracker not updated")
    if not _DATE8_RE.fullmatch(str(as_of_now or "")):
        raise ValueError("loss-making tracker as_of_now must be YYYYMMDD")
    try:
        rank_rows = pd.read_csv(official_rank_csv_path, dtype=str).to_dict("records")
    except (OSError, UnicodeDecodeError, pd.errors.ParserError) as exc:
        raise ValueError("loss-making tracker official rank CSV is unreadable") from exc
    required = {"ts_code", "decision_as_of", "run_revision_id", "terminal_stage", "reason",
                "ttm_profit_dedt", "final_score", "pre_admission_rank"}
    if not required.issubset(rank_rows[0].keys() if rank_rows else required):
        raise ValueError("loss-making tracker rank CSV is missing admission audit columns")
    incoming = []
    for row in rank_rows:
        if str(row.get("terminal_stage") or "") != "loss_making_admission":
            continue
        if str(row.get("decision_as_of") or "") != as_of or str(row.get("run_revision_id") or "") != run_revision_id:
            raise ValueError("loss-making tracker rank CSV identity does not match requested revision")
        reason = str(row.get("reason") or "").strip()
        if reason == "ranked":
            continue
        if not reason:
            raise ValueError("loss-making tracker admission row has no terminal reason")
        if reason not in ADMISSION_REASONS:
            raise ValueError(f"loss-making tracker rank CSV has unknown admission reason {reason!r}")
        incoming.append(_new_tracker_record(
            row, as_of=as_of, run_revision_id=run_revision_id,
            official_reference=official_reference,
        ))
    tracker_path = Path(path)
    current, _previous = _load_tracker(tracker_path)
    refreshed = [_backfill_tracker_record(record, csi1000, str(as_of_now)) for record in current["records"]]
    refreshed.extend(_backfill_tracker_record(record, csi1000, str(as_of_now)) for record in incoming)
    return merge_loss_making_exclusion_tracker(tracker_path, refreshed)
