"""A-short comparison-track v2 weekly adapter.

Knife 3 owns the only weekly integration point.  It consumes a pre-existing,
private daily-cache file before M6.7 publication, then exposes only a
de-identified reminder summary to the public weekly artifact.  It never calls
a provider and it never changes production selection, sizing, or actions.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema
import pandas as pd

from engine import a_short_factor_comparison as v1
from engine.a_short_factor_comparison_v2 import (
    ComparisonV2Error,
    ROOT,
    _digest,
    _private_root,
    PUBLIC_PROGRESS_SCHEMA_PATH,
    build_v2_public_progress,
    capture_v2_week,
    settle_v2_from_daily_payload,
)
from engine.a_short_factor_comparison_v2_adjudication import adjudicate_v2_from_private_ledger
from engine.a_short_experiment_admission_registry import admission_snapshot


DAILY_CACHE_SCHEMA_PATH = ROOT / "schemas" / "a_short_factor_comparison_v2_daily_cache.schema.json"
DAILY_CACHE_NAME = "daily_cache.json"
PUBLIC_STATUS_NOT_CONFIGURED = "not_configured"
PUBLIC_STATUS_CURRENT = "evidence_current"
PUBLIC_STATUS_UNAVAILABLE = "evidence_unavailable_or_inconclusive"
CAPTURE_REPLAY_DRIFT_MESSAGE = "v2 capture replay input drifted"
CAPTURE_ERROR_CODES = frozenset({
    "bundle_binding", "price_clock", "candidate_shape", "price_nonfinite", "bar_count",
    "last_date", "last_close", "state_contract", "materialization", "write_failed", "unknown",
})


def _safe_exception_text(exc: BaseException) -> str:
    try:
        return str(exc)
    except Exception:
        return ""


def is_capture_replay_drift(exc: BaseException) -> bool:
    """Identify the immutable same-week replay branch without exposing exception text."""
    if not isinstance(exc, ValueError):
        return False
    message = _safe_exception_text(exc)
    return message == CAPTURE_REPLAY_DRIFT_MESSAGE or message.endswith(": " + CAPTURE_REPLAY_DRIFT_MESSAGE)


def capture_error_code(exc: BaseException) -> str:
    """Return a de-identified, allowlisted operator code for a failed v2 capture."""
    if is_capture_replay_drift(exc):
        return "unknown"
    if isinstance(exc, OSError):
        return "write_failed"
    message = _safe_exception_text(exc)
    markers = (
        ("published weekly bundle", "bundle_binding"),
        ("receipt", "bundle_binding"),
        ("price-freshness", "price_clock"),
        ("price_data_through", "price_clock"),
        ("invalid price_series row", "price_nonfinite"),
        ("requires ts_code and finite close", "price_nonfinite"),
        ("price_series has fewer than 20 bars", "bar_count"),
        ("last_date mismatch", "last_date"),
        ("last_close mismatch", "last_close"),
        ("candidate close is not bound", "last_close"),
        ("candidate", "candidate_shape"),
        ("partial v2", "state_contract"),
        ("private root", "state_contract"),
        ("program", "state_contract"),
        ("epoch", "state_contract"),
        ("experiment", "state_contract"),
        ("arm", "materialization"),
        ("question", "materialization"),
    )
    for marker, code in markers:
        if marker == "candidate" and not isinstance(exc, ValueError):
            continue
        if marker in message:
            return code if code in CAPTURE_ERROR_CODES else "unknown"
    return "unknown"


def _admission_binding() -> str:
    ids = ("p0_d1_entry_anchor_entry_ma_pullback", "p0_d1_entry_anchor_entry_range_pullback",
           "p0_d3_iv_policy_iv_step_down", "p0_d3_iv_policy_iv_joint_stress")
    return _digest(admission_snapshot(*ids))


def _public_admission_snapshot() -> dict:
    return admission_snapshot(
        "p0_d1_entry_anchor_entry_ma_pullback", "p0_d1_entry_anchor_entry_range_pullback",
        "p0_d3_iv_policy_iv_step_down", "p0_d3_iv_policy_iv_joint_stress",
    )


def _public_summary(status: str, reminder_count: int = 0, *, root: str | Path | None,
                    as_of: str) -> dict:
    if status == PUBLIC_STATUS_NOT_CONFIGURED:
        message = "对比轨 v2：未配置；未读取或写入对比证据，生产结论不变。"
    elif status == PUBLIC_STATUS_CURRENT:
        message = f"对比轨 v2：证据已复核，当前人工提醒 {reminder_count} 项；不自动改动生产结论。"
    elif status == PUBLIC_STATUS_UNAVAILABLE:
        message = "对比轨 v2：证据不可用或结论未定；不显示旧提醒，生产结论不变。"
    else:
        raise ComparisonV2Error("v2 public summary status is unknown")
    progress = build_v2_public_progress(root=root, as_of=as_of)
    return {
        "summary_id": "a_short_factor_comparison_v2",
        "status": status,
        "reminder_count": reminder_count,
        "admission_binding": _admission_binding(),
        "public_progress": progress,
        "message": message,
        "production_unchanged": True,
    }


def validate_v2_public_summary(summary: dict) -> None:
    """Reject a weekly surface that could relay a stale or private reminder."""
    if not isinstance(summary, dict) or set(summary) != {
            "summary_id", "status", "reminder_count", "admission_binding", "public_progress", "message",
            "production_unchanged"}:
        raise ComparisonV2Error("v2 public weekly summary shape drifted")
    status = summary.get("status")
    count = summary.get("reminder_count")
    if summary.get("summary_id") != "a_short_factor_comparison_v2" or \
            status not in {PUBLIC_STATUS_NOT_CONFIGURED, PUBLIC_STATUS_CURRENT, PUBLIC_STATUS_UNAVAILABLE} or \
            not isinstance(count, int) or isinstance(count, bool) or count < 0 or \
            summary.get("production_unchanged") is not True or summary.get("admission_binding") != _admission_binding():
        raise ComparisonV2Error("v2 public weekly summary fields are invalid")
    try:
        jsonschema.validate(summary["public_progress"], json.loads(PUBLIC_PROGRESS_SCHEMA_PATH.read_text(encoding="utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise ComparisonV2Error("v2 public progress is invalid or contains a private field") from exc
    if summary["public_progress"].get("admissions") != _public_admission_snapshot():
        raise ComparisonV2Error("v2 public progress admission binding drifted")
    if status != PUBLIC_STATUS_CURRENT and count != 0:
        raise ComparisonV2Error("unavailable v2 weekly summary must not carry a stale reminder count")
    expected_message = _public_summary(status, count, root=None,
                                       as_of=summary["public_progress"]["as_of"])["message"]
    if summary["message"] != expected_message:
        raise ComparisonV2Error("v2 public weekly summary message drifted")


def _daily_cache_path(root: Path, daily_cache_path: str | Path | None) -> Path:
    path = (root / DAILY_CACHE_NAME) if daily_cache_path is None else Path(daily_cache_path).resolve()
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise ComparisonV2Error("v2 daily cache must stay under the private v2 root") from exc
    return path.resolve()


def load_v2_daily_cache(*, root: str | Path, daily_cache_path: str | Path | None = None) -> dict:
    """Load a serialised existing cache; deliberately no provider or fallback exists."""
    private_root = _private_root(root)
    path = _daily_cache_path(private_root, daily_cache_path)
    if not path.is_file():
        raise ComparisonV2Error("v2 daily cache is unavailable")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ComparisonV2Error("v2 daily cache is unreadable") from exc
    try:
        schema = json.loads(DAILY_CACHE_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(document, schema)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise ComparisonV2Error("v2 daily cache violates its frozen contract") from exc
    return {
        "stocks": pd.DataFrame(document["stocks"]),
        "limits": pd.DataFrame(document["limits"]),
        "meta": document["meta"],
    }


def settle_and_summarize_v2_weekly(*, root: str | Path | None,
                                   daily_cache_path: str | Path | None = None, as_of: str) -> dict:
    """Settle then adjudicate before M6.7, returning only a de-identified current summary.

    An unavailable cache, corrupt private state, or any integrity failure intentionally
    produces no reminder.  Thus an old successful reminder can never be replayed into
    a fresh M6.7 report.
    """
    if root is None:
        return _public_summary(PUBLIC_STATUS_NOT_CONFIGURED, root=None, as_of=as_of)
    try:
        private_root = _private_root(root)
        if not private_root.exists():
            return _public_summary(PUBLIC_STATUS_UNAVAILABLE, root=private_root, as_of=as_of)
        payload = load_v2_daily_cache(root=private_root, daily_cache_path=daily_cache_path)
        settlement = settle_v2_from_daily_payload(root=private_root, daily_payload=payload)
        if settlement.get("status") != "settled_from_existing_cache":
            return _public_summary(PUBLIC_STATUS_UNAVAILABLE, root=private_root, as_of=as_of)
        adjudication = adjudicate_v2_from_private_ledger(root=private_root)
        if adjudication.get("status") != "adjudicated_private_v2":
            return _public_summary(PUBLIC_STATUS_UNAVAILABLE, root=private_root, as_of=as_of)
        reminder_path = private_root / "reminder.json"
        reminder = json.loads(reminder_path.read_text(encoding="utf-8"))
        if reminder != adjudication.get("reminder") or \
                reminder.get("schema_name") != "a_short_factor_comparison_v2_reminder" or \
                reminder.get("production_unchanged") is not True or \
                not isinstance(reminder.get("reminders"), list):
            return _public_summary(PUBLIC_STATUS_UNAVAILABLE, root=private_root, as_of=as_of)
        return _public_summary(PUBLIC_STATUS_CURRENT, len(reminder["reminders"]), root=private_root, as_of=as_of)
    except Exception:
        # Production seam: the comparison track must NEVER block the weekly run, so this
        # catches any Exception (not a fixed tuple) — a future latent uncaught type in
        # settle/adjudicate still degrades to "unavailable", never propagates. BaseException
        # (KeyboardInterrupt/SystemExit) is intentionally not caught.
        return _public_summary(PUBLIC_STATUS_UNAVAILABLE, root=root, as_of=as_of)


def _verify_published_weekly_bundle(*, out_path: str | Path, receipt_path: str | Path,
                                    decision_date: str, source_identity: dict) -> dict:
    output = Path(out_path)
    receipt_file = Path(receipt_path)
    markdown = output.with_suffix(".md")
    try:
        weekly = json.loads(output.read_text(encoding="utf-8"))
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ComparisonV2Error("published weekly bundle is unreadable") from exc
    lineage = weekly.get("run_lineage") if isinstance(weekly, dict) else None
    if not isinstance(lineage, dict) or str(weekly.get("as_of")) != str(decision_date) or \
            lineage.get("run_id") != source_identity.get("run_id") or \
            receipt.get("stage_status") != "complete" or \
            receipt.get("as_of") != str(decision_date) or \
            receipt.get("run_id") != lineage.get("run_id") or \
            receipt.get("candidate_digest") != lineage.get("candidate_digest") or \
            receipt.get("candidate_digest") != source_identity.get("candidate_digest") or \
            set(receipt.get("outputs") or []) != {output.name, markdown.name} or not markdown.is_file():
        raise ComparisonV2Error("published weekly bundle receipt does not match the official M6.7 artifact")
    summary = weekly.get("factor_comparison_v2")
    validate_v2_public_summary(summary)
    return weekly


def capture_v2_after_published_weekly(*, root: str | Path, decision_date: str, candidates: list[dict],
                                      source_identity: dict, out_path: str | Path, receipt_path: str | Path,
                                      forward_eligible: bool) -> dict:
    """Freeze the current week only after a matching M6.7 JSON/Markdown/receipt exists."""
    _private_root(root)
    weekly = _verify_published_weekly_bundle(out_path=out_path, receipt_path=receipt_path,
                                             decision_date=decision_date, source_identity=source_identity)
    price_freshness = (weekly.get("run_lineage") or {}).get("price_freshness")
    if not isinstance(price_freshness, dict):
        raise ComparisonV2Error("published weekly bundle lacks price_freshness lineage")
    run_date = str(price_freshness.get("run_date") or "")
    price_data_through = str(price_freshness.get("price_data_through") or "")
    if not run_date or not price_data_through:
        raise ComparisonV2Error("published weekly price_freshness lacks run_date or price_data_through")
    if forward_eligible:
        if price_freshness.get("mode") != "intraday_prior_settled":
            raise ComparisonV2Error("forward v2 capture requires the live canonical price-freshness mode")
        accepted_prior_settled = price_freshness.get("accepted_prior_settled_date")
        if price_data_through != str(decision_date) and str(accepted_prior_settled or "") != price_data_through:
            raise ComparisonV2Error("forward v2 capture price_data_through lacks the official prior-settled binding")
    sanitized = [v1._safe_candidate(candidate) for candidate in candidates]
    identity = {
        "run_id": str(source_identity["run_id"]),
        "run_date": run_date,
        "source_as_of": str(decision_date),
        "price_data_through": price_data_through,
        "candidate_digest": _digest(sanitized),
        "official_m67_digest": hashlib.sha256(Path(out_path).read_bytes()).hexdigest(),
    }
    return capture_v2_week(root=root, decision_date=decision_date, candidates=candidates,
                           run_identity=identity, forward_eligible=forward_eligible)
