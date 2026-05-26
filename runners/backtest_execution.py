from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from jsonschema import Draft7Validator
except ImportError as exc:  # pragma: no cover - environment guard
    Draft7Validator = None  # type: ignore[assignment]
    JSONSCHEMA_IMPORT_ERROR = exc
else:
    JSONSCHEMA_IMPORT_ERROR = None

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.analyzer.rule6_hard_veto import RULE_VERSIONS, run_veto
from engine.analyzer.state_manager import STATE_ROOT

SCHEMA_PATH = ROOT / "schemas" / "execution_backtest_report.schema.json"
DEFAULT_INPUT_ROOT = ROOT / "result" / "a_short"
DEFAULT_OUT_DIR = ROOT / "result" / "a_short" / "backtest" / "execution"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write a Phase 5 execution-backtest skeleton report from analysis_input.json."
    )
    parser.add_argument("--as-of", required=True, help="Trade date in YYYYMMDD form.")
    parser.add_argument(
        "--input-path",
        type=Path,
        help="Path to analysis_input.json. Defaults to result/a_short/<as-of>/analysis_input.json.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="Directory for execution_report.json and CSV outputs.",
    )
    parser.add_argument("--mode", choices=["smoke", "production"], default="smoke")
    parser.add_argument("--initial-capital", type=float, default=1_000_000.0)
    parser.add_argument("--cost-pct", type=float, default=0.001)
    parser.add_argument("--max-position-pct", type=float, default=0.1)
    parser.add_argument("--max-positions", type=int, default=10)
    parser.add_argument("--time-stop-days", type=int, default=10)
    return parser.parse_args(argv)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_analysis_input(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"analysis_input must be a JSON object: {path}")
    if not isinstance(payload.get("candidates"), list):
        raise ValueError(f"analysis_input.candidates must be a list: {path}")
    return payload


def resolve_input_path(as_of: str, input_path: Path | None) -> Path:
    if input_path is not None:
        return input_path
    return DEFAULT_INPUT_ROOT / as_of / "analysis_input.json"


def validate_report(report: dict[str, Any]) -> None:
    if Draft7Validator is None:  # pragma: no cover - environment guard
        raise RuntimeError(
            "jsonschema is required to validate execution reports"
        ) from JSONSCHEMA_IMPORT_ERROR
    schema = load_json(SCHEMA_PATH)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(report), key=lambda item: list(item.path))
    if errors:
        details = "\n".join(
            f"- {'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ValueError(f"execution report schema validation failed:\n{details}")


def relative_ref(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return str(resolved)


def iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalized_l3_mode(payload: dict[str, Any]) -> str:
    mode = str(payload.get("source", {}).get("l3_mode") or "today")
    if mode not in {"pit", "today", "neutralize"}:
        raise ValueError(f"unsupported analysis_input.source.l3_mode: {mode!r}")
    return mode


def candidate_code(candidate: dict[str, Any]) -> str:
    return str(candidate.get("ts_code") or candidate.get("code") or "")


def candidate_name(candidate: dict[str, Any]) -> str:
    return str(candidate.get("name") or candidate.get("stock_name") or "")


def build_execution_assumptions(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "entry_timing": {
            "rule": "t1_open",
            "price_field": "open_qfq",
        },
        "limit_up_unbuyable": {
            "enabled": True,
            "event_code": "entry_unbuyable",
        },
        "price_adjustment": {
            "mode": "qfq_via_adj_factor",
            "source": "phase5_skeleton_contract_only",
        },
        "transaction_cost": {
            "cost_pct": args.cost_pct,
            "applies_to": "entry_and_exit",
        },
        "stop_loss": {
            "required": True,
            "missing_stop_action": "skip_trade",
            "trigger_price_field": "low_qfq",
        },
        "take_profit": {
            "enabled": False,
            "trigger_order": ["stop_loss", "time_stop"],
            "trigger_price_field": "high_qfq",
        },
        "time_stop": {
            "enabled": True,
            "days": args.time_stop_days,
            "exit_price_field": "close_qfq",
        },
        "position_sizing": {
            "method": "equal_weight",
            "max_position_pct": args.max_position_pct,
            "max_positions": args.max_positions,
            "cash_constrained": True,
        },
        "portfolio_circuit_breaker": {
            "enabled": True,
            "new_entries_blocked": True,
            "existing_positions_action": "hold_until_exit_rule",
        },
        "cooldown": {
            "enabled": True,
            "event_code": "cooldown_block",
        },
        "event_log": {
            "required": True,
            "event_codes": [
                "candidate_seen",
                "entry",
                "entry_unbuyable",
                "missing_stop",
                "stop_loss",
                "take_profit",
                "time_stop",
                "circuit_breaker",
                "cooldown_block",
                "exit",
            ],
        },
    }


def classify_skips(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        decision = run_veto(candidate)
        reason_codes = [
            str(reason.get("code"))
            for reason in decision.get("reasons", [])
            if isinstance(reason, dict) and reason.get("code")
        ]
        if bool(decision.get("vetoed")):
            reason = "analyzer_hard_veto"
        else:
            reason = "missing_stop"
        rows.append(
            {
                "ts_code": candidate_code(candidate),
                "name": candidate_name(candidate),
                "reason": reason,
                "analyzer_vetoed": bool(decision.get("vetoed")),
                "analyzer_reason_codes": ",".join(reason_codes),
            }
        )
    return rows


def event_message_for_skip(row: dict[str, Any]) -> str:
    if row["reason"] == "missing_stop":
        return "candidate skipped: no deterministic stop input wired in skeleton"
    codes = row["analyzer_reason_codes"]
    if codes:
        return f"candidate skipped by analyzer hard veto: {codes}"
    return "candidate skipped by analyzer hard veto"


def build_order_events(as_of: str, skipped_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    event_id = 1
    for row in skipped_rows:
        events.append(
            {
                "event_id": event_id,
                "as_of": as_of,
                "ts_code": row["ts_code"],
                "event_code": "candidate_seen",
                "message": "candidate loaded from analysis_input",
            }
        )
        event_id += 1
        events.append(
            {
                "event_id": event_id,
                "as_of": as_of,
                "ts_code": row["ts_code"],
                "event_code": (
                    "missing_stop" if row["reason"] == "missing_stop" else "candidate_seen"
                ),
                "message": event_message_for_skip(row),
            }
        )
        event_id += 1
    return events


def output_refs(out_dir: Path) -> dict[str, str]:
    return {
        "execution_report": relative_ref(out_dir / "execution_report.json"),
        "trades": relative_ref(out_dir / "trades.csv"),
        "daily_equity": relative_ref(out_dir / "daily_equity.csv"),
        "order_events": relative_ref(out_dir / "order_events.csv"),
        "skipped_candidates": relative_ref(out_dir / "skipped_candidates.csv"),
    }


def build_report(
    payload: dict[str, Any],
    input_path: Path,
    out_dir: Path,
    args: argparse.Namespace,
    skipped_rows: list[dict[str, Any]] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    as_of = str(payload.get("trade_date") or args.as_of)
    candidates = payload.get("candidates", [])
    if skipped_rows is None:
        skipped_rows = classify_skips(candidates)
    missing_stop_count = sum(1 for row in skipped_rows if row["reason"] == "missing_stop")
    analyzer_veto_count = sum(
        1 for row in skipped_rows if row["reason"] == "analyzer_hard_veto"
    )
    candidate_count = len(candidates)
    warnings = [
        {
            "trade_date": as_of,
            "warning_type": "no_executable_candidates",
            "severity": "warning" if candidate_count else "critical",
            "message": (
                "Phase 5 skeleton writes contract outputs only; no execution price "
                "simulator has accepted trades yet."
            ),
        }
    ]
    if analyzer_veto_count:
        warnings[0]["message"] += (
            f" Rule 6 hard veto replay skipped {analyzer_veto_count} candidate(s)."
        )

    return {
        "schema_name": "execution_backtest_report",
        "schema_version": "1.0.0",
        "generated_at": generated_at or iso_now(),
        "preset": "a_short",
        "mode": args.mode,
        "settings": {
            "mode": args.mode,
            "start_date": as_of,
            "end_date": as_of,
            "initial_capital": args.initial_capital,
            "primary_input": "analysis_input",
            "deterministic_report_required": False,
        },
        "inputs": {
            "candidate_root": relative_ref(input_path.parent),
            "analysis_inputs": [
                {
                    "as_of": as_of,
                    "path": relative_ref(input_path),
                    "schema_version": str(payload.get("schema_version") or "unknown"),
                    "candidate_count": candidate_count,
                }
            ],
            "deterministic_reports": [],
            "state_refs": [
                {"kind": "positions", "path": relative_ref(STATE_ROOT / "positions.json")},
                {"kind": "veto_log", "path": relative_ref(STATE_ROOT / "veto_log.json")},
                {
                    "kind": "circuit_breaker",
                    "path": relative_ref(STATE_ROOT / "circuit_breaker.json"),
                },
                {"kind": "execution_log", "path": relative_ref(STATE_ROOT / "execution_log.csv")},
            ],
            "price_data": {
                "path": "not_available_phase5_skeleton",
                "start_date": as_of,
                "end_date": as_of,
                "adj": "qfq_via_adj_factor",
            },
        },
        "execution_assumptions": build_execution_assumptions(args),
        "data_lineage": {
            "data_provider": "tushare",
            "api_families": {
                "candidate_generation": ["analysis_input"],
                "execution_price": ["not_implemented_phase5_skeleton"],
                "state_replay": ["state_manager_json"],
            },
            "forward_return_adjustment_mode": "qfq_via_adj_factor",
            "benchmark_sources": {
                "csi300": "not_used_phase5_skeleton",
                "csi1000": "not_used_phase5_skeleton",
            },
            "pit_limitations": [
                "Execution prices are not fetched in the Phase 5 skeleton.",
                "The runner uses analysis_input.json as the sole primary input.",
                "No Markdown report or LLM free-text output is consumed.",
            ],
            "analysis_input_schema_version": str(payload.get("schema_version") or "unknown"),
            "deterministic_report_schema_version": None,
            "analyzer_rules": [
                {"code": name, "version": version}
                for name, version in sorted(RULE_VERSIONS.items())
            ],
            "l3_mode": normalized_l3_mode(payload),
        },
        "outputs": output_refs(out_dir),
        "metrics": {
            "sample_count": candidate_count,
            "candidate_count": candidate_count,
            "trade_count": 0,
            "skipped_count": len(skipped_rows),
            "entry_unbuyable_count": 0,
            "missing_stop_count": missing_stop_count,
            "win_rate": None,
            "total_return": None,
            "annualized_return": None,
            "max_drawdown": None,
            "avg_holding_days": None,
            "ending_equity": args.initial_capital,
        },
        "date_warnings": warnings,
        "limitations": [
            "Phase 5 skeleton validates the execution report contract and writes CSV shells only.",
            "Candidates that pass analyzer replay are skipped as missing_stop until deterministic stop rules are wired.",
            "No execution price fetch, limit-up matching, order fill, portfolio accounting, or exit simulation is implemented yet.",
        ],
    }


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_outputs(
    report: dict[str, Any],
    payload: dict[str, Any],
    out_dir: Path,
    skipped_rows: list[dict[str, Any]] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    as_of = str(payload.get("trade_date") or report["settings"]["end_date"])
    if skipped_rows is None:
        skipped_rows = classify_skips(payload.get("candidates", []))
    order_events = build_order_events(as_of, skipped_rows)

    write_csv(
        out_dir / "trades.csv",
        [
            "trade_id",
            "ts_code",
            "entry_date",
            "exit_date",
            "entry_price",
            "exit_price",
            "shares",
            "pnl",
            "return_pct",
            "exit_reason",
        ],
        [],
    )
    write_csv(
        out_dir / "daily_equity.csv",
        ["trade_date", "equity", "cash", "market_value", "drawdown"],
        [
            {
                "trade_date": as_of,
                "equity": report["metrics"]["ending_equity"],
                "cash": report["metrics"]["ending_equity"],
                "market_value": 0,
                "drawdown": 0,
            }
        ],
    )
    write_csv(
        out_dir / "order_events.csv",
        ["event_id", "as_of", "ts_code", "event_code", "message"],
        order_events,
    )
    write_csv(
        out_dir / "skipped_candidates.csv",
        ["ts_code", "name", "reason", "analyzer_vetoed", "analyzer_reason_codes"],
        skipped_rows,
    )

    validate_report(report)
    with (out_dir / "execution_report.json").open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_path = resolve_input_path(args.as_of, args.input_path)
    payload = load_analysis_input(input_path)
    if str(payload.get("trade_date")) != args.as_of:
        raise ValueError(
            f"analysis_input.trade_date {payload.get('trade_date')} does not match --as-of {args.as_of}"
        )
    out_dir = args.out_dir
    skipped_rows = classify_skips(payload.get("candidates", []))
    report = build_report(payload, input_path, out_dir, args, skipped_rows=skipped_rows)
    write_outputs(report, payload, out_dir, skipped_rows=skipped_rows)
    print(f"[OK] wrote {out_dir / 'execution_report.json'}")
    print(f"[OK] wrote {out_dir / 'trades.csv'}")
    print(f"[OK] wrote {out_dir / 'daily_equity.csv'}")
    print(f"[OK] wrote {out_dir / 'order_events.csv'}")
    print(f"[OK] wrote {out_dir / 'skipped_candidates.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
