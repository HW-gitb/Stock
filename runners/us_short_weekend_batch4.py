# -*- coding: utf-8 -*-
"""Supported offline CLI for the US-short batch4 weekend pipeline.

Loads a closed-world local context packet and reviewed calendar/governance artifacts, optionally bootstraps the
private lifecycle register, then delegates to ``run_weekend_pipeline``. No provider, network, broker, or order path.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.us_short_canonical_asof import OutOfWindowError, resolve_canonical_asof
from engine.us_short_cli_redaction import closed_world_counts, safe_schema_location
from engine.us_short_eligibility_gate import canonical_us_ticker, load_eligibility_governance
from engine.us_short_market_calendar import sessions_for_window, validate_market_calendar
from engine.us_short_private_paths import PrivatePathError, reject_nonprivate_output_path
from engine.us_short_run_origin import (
    RunOriginError,
    is_capstone_research_live_capability,
    require_research_live_provider_health,
)
from runners.us_short_account_state_from_manual_tables import ConvertError, validate_account_state

_CALIBRATION_PATH = ROOT / "presets" / "us_short_lifecycle_calibration_governance_20260620.json"
_PACKET_SCHEMA_PATH = ROOT / "schemas" / "us_short_weekend_batch4_context_packet.schema.json"

_PACKET_KEYS = frozenset({
    "data_context", "eligibility_governance_path", "per_ticker_analysis", "run_provenance",
    "provider_health", "calendar_path", "account_state_path", "market_axis_regimes", "prior_regime",
    "prior_upgrade_count", "sizing_per_ticker", "basket_context", "cost_inputs", "report_context",
    "lifecycle_register_path", "lifecycle_readiness_out_path", "runs_private_root", "weekly_private_root",
})


class Batch4RunnerError(ValueError):
    """The local runner packet, clock, or required private state is invalid."""


def _read_json(path: Path, label: str):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        raise Batch4RunnerError(f"{label} 无法读取为 UTF-8 JSON")


def _resolve_path(value, *, base: Path, label: str, allow_none=False):
    if allow_none and value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise Batch4RunnerError(f"{label} 须为非空路径字符串")
    path = Path(value)
    return path if path.is_absolute() else (base / path).resolve()


def _initial_lifecycle_register(as_of: str) -> dict:
    calibration = _read_json(_CALIBRATION_PATH, "lifecycle calibration")
    items = calibration.get("calibration_items")
    if not isinstance(items, list):
        raise Batch4RunnerError("lifecycle calibration 缺 calibration_items")
    return {
        "schema_name": "us_short_lifecycle_register", "schema_version": "1.0.0", "as_of": as_of,
        "items": [{"number": row["number"], "title": row["title"], "forward_observations": {},
                   "secondary_condition_met": False, "upgrade_margin_frozen": False, "due": False}
                  for row in items],
    }


def _bootstrap_lifecycle(path: Path, *, decision_date: str) -> bool:
    """Create the private zero-observation register once; an existing artifact is never overwritten."""
    if path.exists():
        return False
    from engine.us_short_lifecycle_store import write_lifecycle_register
    write_lifecycle_register(_initial_lifecycle_register(decision_date), path)
    return True


def _validate_packet_schema(packet: dict) -> None:
    """Structural schema validation BEFORE orchestration (the closed-world top-level key check above is the
    first-line error; this validates the nested batch2/3 shape against the routed schema-first contract so a
    hand-authored / builder-produced packet is caught here, not deep inside the orchestrator). The deep
    SEMANTIC gates (PIT 对账 / price-clock / seam coverage / health / run-mode) stay in the orchestrator."""
    import jsonschema  # run_packet already imported + hard-required jsonschema before calling this
    schema = json.loads(_PACKET_SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        jsonschema.validate(packet, schema)
    except jsonschema.ValidationError as exc:
        location = safe_schema_location(exc.absolute_path, allowed_roots=_PACKET_KEYS)
        raise Batch4RunnerError(f"context packet 不符合 schema (at {location})")


def _load_packet(packet_path) -> tuple[dict, Path]:
    path = Path(packet_path).resolve()
    packet = _read_json(path, "batch4 context packet")
    if not isinstance(packet, dict) or set(packet) != _PACKET_KEYS:
        shape = closed_world_counts(packet, expected_keys=_PACKET_KEYS)
        raise Batch4RunnerError(f"context packet 顶层须为 18-key closed-world object ({shape})")
    _validate_packet_schema(packet)
    return packet, path.parent


def _assemble_context(packet: dict, base: Path) -> tuple[dict, dict]:
    gov_path = _resolve_path(packet["eligibility_governance_path"], base=base,
                             label="eligibility_governance_path")
    calendar_path = _resolve_path(packet["calendar_path"], base=base, label="calendar_path")
    account_path = _resolve_path(packet["account_state_path"], base=base, label="account_state_path")
    try:
        reject_nonprivate_output_path(account_path)
    except PrivatePathError as exc:
        raise Batch4RunnerError("account_state_path 必须为可证明私密的路径") from exc
    account = _read_json(account_path, "US-short account state")
    try:
        validate_account_state(account, account.get("as_of") if isinstance(account, dict) else None)
    except (ConvertError, KeyError, TypeError):
        # redacted: validate_account_state messages echo account equity/cash/ticker values
        raise Batch4RunnerError("account_state 非法（详见你的私密 account artifact）")
    if not isinstance(packet["sizing_per_ticker"], dict):
        raise Batch4RunnerError("sizing_per_ticker 须为 dict")
    data_context = packet["data_context"]
    if not (isinstance(data_context, dict) and isinstance(data_context.get("holdings"), list)):
        raise Batch4RunnerError("data_context.holdings 须为 list")
    account_tickers = {p["ticker"] for p in account["positions"]}
    # TRUE 1:1: canonical holding tickers must be UNIQUE (dup rows must not pass set equality) AND equal
    # the account ticker set. Redacted: counts only, never the tickers (§11/§18 no-secret contract).
    canon_holdings = []
    for h in data_context["holdings"]:
        c = canonical_us_ticker(h.get("ticker")) if isinstance(h, dict) else None
        if c is None:
            raise Batch4RunnerError("data_context.holdings 行须为 {object, 合法 ticker}")
        canon_holdings.append(c)
    if len(set(canon_holdings)) != len(canon_holdings):
        raise Batch4RunnerError(
            f"data_context.holdings 含 {len(canon_holdings) - len(set(canon_holdings))} 个重复 canonical ticker（须 1:1 唯一）")
    if set(canon_holdings) != account_tickers:
        raise Batch4RunnerError(
            f"data_context.holdings 与 account_state.positions 不 1:1 对应（holdings {len(set(canon_holdings))} / positions {len(account_tickers)}）")
    pc = {
        "data_context": packet["data_context"],
        "eligibility_governance": load_eligibility_governance(gov_path),
        "per_ticker_analysis": packet["per_ticker_analysis"],
        "run_provenance": packet["run_provenance"],
        "provider_health": packet["provider_health"],
        "calendar": _read_json(calendar_path, "market calendar"),
        "market_axis_regimes": packet["market_axis_regimes"],
        "prior_regime": packet["prior_regime"],
        "prior_upgrade_count": packet["prior_upgrade_count"],
        "sizing_context": {"short_bucket_dollars": account["us_short_bucket_capital"],
                           "per_ticker": packet["sizing_per_ticker"]},
        "basket_context": packet["basket_context"],
        "cost_inputs": packet["cost_inputs"],
        "available_cash": account["us_short_available_cash"],
        "account_state": account,
        "report_context": packet["report_context"],
        "lifecycle_register_path": _resolve_path(packet["lifecycle_register_path"], base=base,
                                                   label="lifecycle_register_path"),
        "lifecycle_readiness_out_path": _resolve_path(packet["lifecycle_readiness_out_path"], base=base,
                                                        label="lifecycle_readiness_out_path", allow_none=True),
        "runs_private_root": _resolve_path(packet["runs_private_root"], base=base, label="runs_private_root"),
        "weekly_private_root": _resolve_path(packet["weekly_private_root"], base=base,
                                               label="weekly_private_root"),
    }
    return pc, account


def _decision_date_for_bootstrap(now_et: datetime, calendar: dict):
    validated = validate_market_calendar(calendar)
    sessions = sessions_for_window(now_et.strftime("%Y%m%d"), calendar=validated)
    try:
        return resolve_canonical_asof(now_et, sessions)["decision_date"]
    except OutOfWindowError:
        return None


def _summary(result: dict, *, dry_run: bool) -> dict:
    summary = {
        "emitted": bool(result.get("emitted")), "out_of_window": bool(result.get("out_of_window")),
        "no_emit_reason": result.get("no_emit_reason"), "decision_date": result.get("decision_date"),
        "run_date": result.get("run_date"), "row_count": len(result.get("machine_record", {}).get("rows", [])),
        "dry_run": dry_run,
    }
    if result.get("emitted") and not dry_run:
        summary["output_paths"] = {key: str(value) for key, value in result["written"].items()}
    return summary


def run_packet(packet_path, *, now_et: datetime, run_mode="offline_test", _research_live_capability=None,
               bootstrap_lifecycle=False, dry_run=False) -> dict:
    if not isinstance(now_et, datetime) or now_et.tzinfo is not None:
        raise Batch4RunnerError("now_et 须为无时区 datetime，按 America/New_York 本地墙钟解释")
    # Provider-backed modes are CAPSTONE-INTERNAL: a generic batch4 caller must not stamp a
    # context packet with the "真实 provider 数据" research banner. It is minted only when the caller holds the
    # source-bound capstone execution receipt (not a caller-settable flag), which the e2e bridge forwards only after
    # checking the consumed source path/digest. A direct batch4 caller selecting either mode without it fails closed.
    if run_mode in ("research_live", "mixed_source") and not is_capstone_research_live_capability(_research_live_capability):
        raise Batch4RunnerError(
            "provider-backed run_mode 为 capstone 内部 run_origin（须持 source-bound capstone execution receipt，经 e2e 桥转发）；batch4 通用调用方"
            "不可直接选择")
    try:
        import jsonschema  # noqa: F401 - required by the official lifecycle/machine/report validators
    except ImportError as exc:
        raise Batch4RunnerError("jsonschema 未安装；batch4 官方 validator 无法运行，拒绝降级执行") from exc
    from engine.us_short_weekend_orchestrator import run_weekend_pipeline
    packet, base = _load_packet(packet_path)
    pc, account = _assemble_context(packet, base)
    if run_mode in ("research_live", "mixed_source"):
        try:
            require_research_live_provider_health(_research_live_capability, pc["provider_health"])
        except RunOriginError as exc:
            raise Batch4RunnerError(
                "provider-backed provider health does not match the receipt-bound provider outcome"
            ) from exc

    if run_mode in ("offline_test", "research_live", "mixed_source"):
        decision_date = _decision_date_for_bootstrap(now_et, pc["calendar"])
        if decision_date is not None:
            try:
                validate_account_state(account, decision_date)
            except ConvertError:
                # redacted: ConvertError echoes account as_of/equity/cash values
                raise Batch4RunnerError("account_state 与本次 decision_date 不一致（详见你的私密 account artifact）")
        register_path = Path(pc["lifecycle_register_path"])
        if decision_date is not None and not register_path.exists():
            if not bootstrap_lifecycle:
                raise Batch4RunnerError(
                    "lifecycle register 缺失；首次离线运行请显式加 --bootstrap-lifecycle")
            _bootstrap_lifecycle(register_path, decision_date=decision_date)

    if dry_run:
        with tempfile.TemporaryDirectory(prefix="us_short_batch4_dry_") as tmp:
            dry_pc = {**pc, "runs_private_root": Path(tmp) / "runs_private",
                      "weekly_private_root": Path(tmp) / "weekly_private",
                      "lifecycle_readiness_out_path": None}
            return _summary(run_weekend_pipeline(now_et, dry_pc, run_mode=run_mode,
                                                 research_live_capability=_research_live_capability), dry_run=True)
    return _summary(run_weekend_pipeline(now_et, pc, run_mode=run_mode,
                                         research_live_capability=_research_live_capability), dry_run=False)


def _parse_now_et(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise argparse.ArgumentTypeError("须为 ET 墙钟 YYYY-MM-DDTHH:MM:SS") from exc
    return parsed


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Run the offline US-short batch4 weekend pipeline")
    parser.add_argument("--context", required=True, type=Path, help="local closed-world context packet JSON")
    parser.add_argument("--now-et", required=True, type=_parse_now_et, help="ET wall clock YYYY-MM-DDTHH:MM:SS")
    # Provider-backed modes are capstone-INTERNAL, not operator-selectable here; a generic batch4 caller only gets
    # offline_test/live.
    parser.add_argument("--run-mode", choices=("offline_test", "live"), default="offline_test")
    parser.add_argument("--bootstrap-lifecycle", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        summary = run_packet(args.context, now_et=args.now_et, run_mode=args.run_mode,
                             bootstrap_lifecycle=args.bootstrap_lifecycle, dry_run=args.dry_run)
    except Batch4RunnerError as exc:
        print(f"US-short batch4 runner failed: {exc}", file=sys.stderr)   # already redacted at the raise site
        return 2
    except Exception as exc:
        # redacted: a propagated engine error (orchestrator/analysis/private-path) message can echo
        # tickers/scores/account values; surface only the error CLASS, never str(exc)
        print(f"US-short batch4 runner failed: {type(exc).__name__}（已脱敏）", file=sys.stderr)
        return 2
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
