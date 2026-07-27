"""US-short §4c receipt-bound soft-discovery weekly banner.

This adapter is deliberately read-only: it consumes the immutable K4a stage receipt,
K4b consumption receipt and (when present) the same-week comparison ledger.  It has
no scoring, selection, provider, network, or operation-advice authority.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
_SCHEMA = ROOT / "schemas" / "us_short_soft_discovery_weekly_record.schema.json"
_STAGE_SCHEMA = ROOT / "schemas" / "us_short_provisional_theme_stage_receipt.schema.json"
_CONSUMPTION_SCHEMA = ROOT / "schemas" / "us_short_soft_boost_consumption_receipt.schema.json"
_LEDGER_SCHEMA = ROOT / "schemas" / "us_short_soft_boost_comparison_ledger.schema.json"
_PAIRWISE_LEDGER_SCHEMA = ROOT / "schemas" / "us_short_soft_boost_pairwise_ledger.schema.json"
_SHADOW_SCHEMA = ROOT / "schemas" / "us_short_soft_boost_shadow_receipt.schema.json"
_ADJUDICATION_SCHEMA = ROOT / "schemas" / "us_short_soft_boost_adjudication_receipt.schema.json"
_VALIDATION_SCHEMA = ROOT / "schemas" / "us_short_provisional_theme_validation.schema.json"
_REMINDER = "paid_member_source_then_source_bound_member_confirmation_and_independent_market_verification_then_forward_shadow_then_reconsider_unlock_cap_switch"
_REMINDER_TEXT = "治理提醒：付费成员源后，先做源绑定成员确认和独立市场验证，再做 forward shadow，才可重议解锁/上限/切换"


class SoftDiscoveryWeeklyReportError(ValueError):
    pass


def _load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate(value: Any, schema: Path) -> None:
    jsonschema.validate(value, _load_schema(schema))


def _artifact(path: Path | None, digest: str | None = None) -> dict[str, str | None]:
    if path is None:
        return {"path": None, "sha256": digest}
    try:
        rel = path.resolve().relative_to(ROOT.resolve()).as_posix()
    except (OSError, ValueError):
        return {"path": None, "sha256": None}
    return {"path": rel, "sha256": digest}


def _read(path: Path, schema: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    _validate(value, schema)
    return value, hashlib.sha256(raw).hexdigest()


def _read_comparison_ledger(path: Path) -> tuple[dict[str, Any], str, bool]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise SoftDiscoveryWeeklyReportError("comparison ledger must be an object")
    pairwise = value.get("schema_name") == "us_short_soft_boost_pairwise_ledger"
    _validate(value, _PAIRWISE_LEDGER_SCHEMA if pairwise else _LEDGER_SCHEMA)
    return value, hashlib.sha256(raw).hexdigest(), pairwise


def _bound_path(binding: dict[str, Any], *, root: Path) -> Path | None:
    value = binding.get("path") if isinstance(binding, dict) else None
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise SoftDiscoveryWeeklyReportError("receipt binding path is invalid")
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise SoftDiscoveryWeeklyReportError("receipt binding escapes repository") from exc
    return path


def _empty_consumed() -> dict[str, Any]:
    return {"labels": [], "tickers": [], "boosts": [], "top15_entered": [], "top15_exited": [],
            "operation_advice_effect_claimed": False}


def invalid_evidence_record(*, decision_date: str, stage_receipt_path: Path | None = None,
                            consumption_receipt_path: Path | None = None,
                            shadow_receipt_path: Path | None = None,
                            comparison_ledger_path: Path | None = None,
                            adjudication_receipt_path: Path | None = None,
                            reason_code: str = "K4C_RECEIPT_REJECTED") -> dict[str, Any]:
    """The sole fail-closed report record for an unreadable optional evidence branch."""
    record = {"schema_name": "us_short_soft_discovery_weekly_record", "schema_version": "1.0.0",
              "decision_date": decision_date, "state": "invalid_evidence", "reason_code": reason_code,
              "bindings": {"stage_receipt": _artifact(stage_receipt_path),
                           "consumption_receipt": _artifact(consumption_receipt_path),
                           "shadow_receipt": _artifact(shadow_receipt_path),
                           "comparison_ledger": _artifact(comparison_ledger_path),
                           "adjudication_receipt": _artifact(adjudication_receipt_path)},
              "consumed": _empty_consumed(),
              "comparison": {"status": "comparison_unavailable", "captured_week_count": 0,
                             "matured_week_count": 0, "eligible_divergence_week_count": 0,
                             "formal_thresholds": [24, 36], "formal_look": None,
                             "recommendation": "comparison_unavailable", "user_decision_required": False,
                             "automatic_replacement_allowed": False}, "governance_reminder": _REMINDER}
    _validate(record, _SCHEMA)
    return record


def _comparison(ledger_path: Path | None, shadow_path: Path | None, adjudication_path: Path | None,
                *, decision_date: str, stage_sha: str | None, consumption_sha: str | None,
                root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    unavailable = {"status": "comparison_unavailable", "captured_week_count": 0,
                   "matured_week_count": 0, "eligible_divergence_week_count": 0,
                   "formal_thresholds": [24, 36], "formal_look": None,
                   "recommendation": "comparison_unavailable", "user_decision_required": False,
                   "automatic_replacement_allowed": False}
    if ledger_path is None or shadow_path is None:
        return unavailable, _artifact(None), _artifact(None), _artifact(None)
    try:
        ledger, sha, pairwise = _read_comparison_ledger(ledger_path)
        shadow, shadow_sha = _read(shadow_path, _SHADOW_SCHEMA)
        if pairwise:
            bound = (ledger["latest_decision_date"] == decision_date
                     and ledger["latest_shadow_receipt_sha256"] == shadow_sha
                     and ledger["latest_consumption_receipt_sha256"] == consumption_sha)
        else:
            bound = (ledger["records"][0] == shadow and shadow["decision_date"] == decision_date
                     and shadow["stage_receipt_sha256"] == stage_sha)
        if not bound:
            raise SoftDiscoveryWeeklyReportError("comparison ledger binding mismatch")
        base = {"status": "continue_accumulation", "captured_week_count": ledger["captured_week_count"],
                "matured_week_count": ledger["matured_week_count"],
                "eligible_divergence_week_count": ledger["eligible_divergence_week_count"],
                "formal_thresholds": [24, 36], "formal_look": None, "recommendation": "continue_accumulating",
                "user_decision_required": False, "automatic_replacement_allowed": False}
        if adjudication_path is None:
            return base, _artifact(ledger_path, sha), _artifact(shadow_path, shadow_sha), _artifact(None)
        adjudication, adj_sha = _read(adjudication_path, _ADJUDICATION_SCHEMA)
        if (adjudication["decision_date"] != decision_date or adjudication["comparison_ledger_sha256"] != sha
                or adjudication["epoch_id"] != shadow["epoch_id"]):
            raise SoftDiscoveryWeeklyReportError("adjudication receipt binding mismatch")
        expected_look = 36 if ledger["eligible_divergence_week_count"] >= 36 else (
            24 if ledger["eligible_divergence_week_count"] >= 24 else None)
        if adjudication["formal_look"] != expected_look:
            raise SoftDiscoveryWeeklyReportError("adjudication receipt is ahead of eligible comparison evidence")
        if not pairwise or adjudication["comparison_statistical_plan_sha256"] != ledger["comparison_statistical_plan_sha256"] \
                or adjudication["comparison_counts"] != {key: ledger[key] for key in (
                    "captured_week_count", "matured_week_count", "eligible_divergence_week_count", "non_overlap_h10_block_count")}:
            raise SoftDiscoveryWeeklyReportError("adjudication receipt is not source-bound to a pairwise ledger")
        expected_evidence = {
            "continue_on": {"on_gate_passed": True, "off_gate_passed": False, "inconclusive": False},
            "recommend_switch_off": {"on_gate_passed": False, "off_gate_passed": True, "inconclusive": False},
            "insufficient_evidence": {"on_gate_passed": False, "off_gate_passed": False, "inconclusive": True},
        }
        if adjudication["formal_evidence"] != expected_evidence.get(adjudication["recommendation"]):
            raise SoftDiscoveryWeeklyReportError("adjudication recommendation and formal evidence disagree")
        if adjudication["user_decision"] not in {"none", "accept", "reject", "defer"}:
            raise SoftDiscoveryWeeklyReportError("adjudication user decision is invalid")
        return {"status": "formal_adjudicated", "captured_week_count": ledger["captured_week_count"],
                "matured_week_count": ledger["matured_week_count"],
                "eligible_divergence_week_count": ledger["eligible_divergence_week_count"],
                "formal_thresholds": [24, 36], "formal_look": adjudication["formal_look"],
                "recommendation": adjudication["recommendation"], "user_decision_required": True,
                "automatic_replacement_allowed": False}, _artifact(ledger_path, sha), _artifact(shadow_path, shadow_sha), _artifact(adjudication_path, adj_sha)
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError, jsonschema.ValidationError,
            SoftDiscoveryWeeklyReportError):
        return unavailable, _artifact(ledger_path), _artifact(shadow_path), _artifact(adjudication_path)


def build_weekly_record(*, decision_date: str, stage_receipt_path: Path | None,
                        consumption_receipt_path: Path | None, comparison_ledger_path: Path | None = None,
                        shadow_receipt_path: Path | None = None, adjudication_receipt_path: Path | None = None,
                        root: Path = ROOT) -> dict[str, Any]:
    """Derive the §4c record.  A supplied unreadable/inconsistent receipt is *invalid_evidence*, never empty."""
    if not isinstance(decision_date, str) or len(decision_date) != 8 or not decision_date.isascii() or not decision_date.isdigit():
        raise SoftDiscoveryWeeklyReportError("decision_date must be YYYYMMDD")
    if consumption_receipt_path is None:
        record = {"schema_name": "us_short_soft_discovery_weekly_record", "schema_version": "1.0.0",
                  "decision_date": decision_date, "state": "disabled", "reason_code": "SOFT_BOOST_DISABLED",
                  "bindings": {"stage_receipt": _artifact(None), "consumption_receipt": _artifact(None),
                               "shadow_receipt": _artifact(None), "comparison_ledger": _artifact(None),
                               "adjudication_receipt": _artifact(None)}, "consumed": _empty_consumed(),
                  "comparison": {"status": "comparison_unavailable", "captured_week_count": 0,
                                 "matured_week_count": 0, "eligible_divergence_week_count": 0,
                                 "formal_thresholds": [24, 36], "formal_look": None,
                                 "recommendation": "comparison_unavailable", "user_decision_required": False,
                                 "automatic_replacement_allowed": False}, "governance_reminder": _REMINDER}
        _validate(record, _SCHEMA)
        return record
    consumption_path = Path(consumption_receipt_path)
    stage_path = Path(stage_receipt_path) if stage_receipt_path is not None else None
    ledger_path = Path(comparison_ledger_path) if comparison_ledger_path is not None else None
    shadow_path = Path(shadow_receipt_path) if shadow_receipt_path is not None else None
    adjudication_path = Path(adjudication_receipt_path) if adjudication_receipt_path is not None else None
    try:
        consumption, consumption_sha = _read(consumption_path, _CONSUMPTION_SCHEMA)
        if consumption["decision_date"] != decision_date:
            raise SoftDiscoveryWeeklyReportError("consumption decision date mismatch")
        bound_stage = _bound_path(consumption["bindings"]["stage_receipt"], root=root)
        if bound_stage is not None:
            if stage_path is None or bound_stage != stage_path.resolve():
                raise SoftDiscoveryWeeklyReportError("stage path is not the consumption-bound receipt")
            stage, stage_sha = _read(bound_stage, _STAGE_SCHEMA)
            if (stage_sha != consumption["bindings"]["stage_receipt"]["sha256"]
                    or stage["decision_date"] != decision_date):
                raise SoftDiscoveryWeeklyReportError("stage receipt digest or date mismatch")
        else:
            stage, stage_sha = None, None
        status_map = {"consumed_valid_nonempty": "valid_nonempty", "zero_valid_empty": "valid_empty",
                      "zero_upstream_unavailable": "upstream_unavailable", "zero_invalid_evidence": "invalid_evidence",
                      "zero_disabled": "disabled"}
        state = status_map[consumption["status"]]
        expected_stage = {"valid_nonempty": "valid_nonempty", "valid_empty": "valid_empty",
                          "upstream_unavailable": "upstream_unavailable", "invalid_evidence": "invalid_evidence",
                          "disabled": "disabled"}[state]
        if stage is not None and stage["status"] != expected_stage:
            raise SoftDiscoveryWeeklyReportError("stage and consumption state disagree")
        consumed = _empty_consumed()
        if state == "valid_nonempty":
            validation_path = _bound_path(consumption["bindings"]["validation_artifact"], root=root)
            if validation_path is None:
                raise SoftDiscoveryWeeklyReportError("valid consumption lacks validation binding")
            validation, validation_sha = _read(validation_path, _VALIDATION_SCHEMA)
            if validation_sha != consumption["bindings"]["validation_artifact"]["sha256"]:
                raise SoftDiscoveryWeeklyReportError("validation digest mismatch")
            boosts = [{"ticker": row["ticker"], "actual_boost": float(row["actual_boost"])} for row in consumption["per_ticker"] if row["actual_boost"] > 0]
            tickers = [row["ticker"] for row in boosts]
            labels = sorted({theme["display_name"] for theme in validation["themes"]
                             if any(member["ticker"] in tickers for member in theme["members"])})
            if not boosts or not labels:
                raise SoftDiscoveryWeeklyReportError("valid nonempty receipt has no consumed validated theme")
            consumed = {"labels": labels, "tickers": tickers, "boosts": boosts,
                        "top15_entered": consumption["top15_impact"]["entered"],
                        "top15_exited": consumption["top15_impact"]["exited"],
                        "operation_advice_effect_claimed": False}
        comparison, ledger_artifact, shadow_artifact, adjudication_artifact = _comparison(
            ledger_path, shadow_path, adjudication_path, decision_date=decision_date, stage_sha=stage_sha,
            consumption_sha=consumption_sha, root=root)
        record = {"schema_name": "us_short_soft_discovery_weekly_record", "schema_version": "1.0.0",
                  "decision_date": decision_date, "state": state,
                  "reason_code": consumption["reason_code"],
                  "bindings": {"stage_receipt": _artifact(stage_path, stage_sha),
                               "consumption_receipt": _artifact(consumption_path, consumption_sha),
                               "shadow_receipt": shadow_artifact, "comparison_ledger": ledger_artifact,
                               "adjudication_receipt": adjudication_artifact}, "consumed": consumed,
                  "comparison": comparison, "governance_reminder": _REMINDER}
    except (OSError, UnicodeDecodeError, ValueError, KeyError, TypeError, jsonschema.ValidationError,
            SoftDiscoveryWeeklyReportError):
        record = invalid_evidence_record(
            decision_date=decision_date, stage_receipt_path=stage_path, consumption_receipt_path=consumption_path,
            shadow_receipt_path=shadow_path, comparison_ledger_path=ledger_path,
            adjudication_receipt_path=adjudication_path)
    _validate(record, _SCHEMA)
    return record


def render_weekly_banner(record: dict[str, Any]) -> str | None:
    _validate(record, _SCHEMA)
    state = record["state"]
    if state == "disabled":
        return None
    comparison = record["comparison"]
    progress = ("对比进度：已捕获=%d / 已成熟=%d / 有效分歧=%d / 正式门槛=%s；%s；需用户决定=%s；不会自动替换" % (
        comparison["captured_week_count"], comparison["matured_week_count"],
        comparison["eligible_divergence_week_count"], "/".join(str(x) for x in comparison["formal_thresholds"]),
        comparison["recommendation"], "是" if comparison["user_decision_required"] else "否"))
    if state == "valid_nonempty":
        boosts = ", ".join(f"{row['ticker']} +{int(row['actual_boost'])}分" for row in record["consumed"]["boosts"])
        return "未确认软发现 · ≤5 分；暂定主题=%s；已消费=%s；不改变操作建议；%s；%s" % (
            ", ".join(record["consumed"]["labels"]), boosts, progress, _REMINDER_TEXT)
    if state == "valid_empty":
        return "软发现已运行 · 本周无合格主题 · 0 分；%s；%s" % (progress, _REMINDER_TEXT)
    if state == "upstream_unavailable":
        return "软发现不可用/未完成 · 本周未消费 · 0 分；%s；%s" % (progress, _REMINDER_TEXT)
    return "软发现证据无效 · 已拒绝消费 · 0 分；错误码=%s；%s；%s" % (
        record["reason_code"], progress, _REMINDER_TEXT)
