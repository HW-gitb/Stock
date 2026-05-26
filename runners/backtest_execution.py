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

try:
    import yaml
except ImportError:  # pragma: no cover - optional dependency guard
    yaml = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.analyzer.rule6_hard_veto import RULE_VERSIONS, run_veto
from engine.analyzer.state_manager import STATE_ROOT

REPORT_SCHEMA_PATH = ROOT / "schemas" / "execution_backtest_report.schema.json"
PRICE_DATA_SCHEMA_PATH = ROOT / "schemas" / "execution_price_data.schema.json"
PORTFOLIO_ALLOCATION_SCHEMA_PATH = ROOT / "schemas" / "portfolio_allocation.schema.json"
CASH_BUFFER_STATE_SCHEMA_PATH = ROOT / "schemas" / "cash_buffer_state.schema.json"
DEFAULT_INPUT_ROOT = ROOT / "result" / "a_short"
DEFAULT_OUT_DIR = ROOT / "result" / "a_short" / "backtest" / "execution"
DEFAULT_PRESET_PATH = ROOT / "presets" / "a_short.yaml"
A_SHARE_LOT_SIZE = 100
SHIP_GATE_FAILURE_MODE = "paper_or_minimal_size_or_risk_filter_only"


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
    parser.add_argument(
        "--price-data",
        type=Path,
        help="Optional path to an execution_price_data JSON file. The skeleton validates and references it, but still does not simulate fills.",
    )
    parser.add_argument(
        "--portfolio-allocation",
        type=Path,
        required=True,
        help="Path to portfolio_allocation JSON. Required so capital_context is reproducible.",
    )
    parser.add_argument(
        "--cash-buffer-state",
        type=Path,
        required=True,
        help="Path to cash_buffer_state JSON. Required so bucket capital comes from dynamic state.",
    )
    parser.add_argument(
        "--preset-path",
        type=Path,
        default=DEFAULT_PRESET_PATH,
        help="Path to preset YAML. Defaults to presets/a_short.yaml for the current Phase 5 skeleton.",
    )
    parser.add_argument(
        "--initial-capital",
        type=float,
        default=None,
        help="Optional guard: when set, must equal the selected bucket capital from cash_buffer_state.",
    )
    parser.add_argument("--cost-pct", type=float, default=0.001)
    parser.add_argument("--max-position-pct", type=float, default=0.1)
    parser.add_argument("--max-positions", type=int, default=10)
    parser.add_argument("--time-stop-days", type=int, default=10)
    return parser.parse_args(argv)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_simple_yaml_scalar(value: str) -> Any:
    text = value.strip()
    if text in {"", "null", "Null", "NULL", "~"}:
        return None
    if text in {"true", "True", "TRUE"}:
        return True
    if text in {"false", "False", "FALSE"}:
        return False
    if (text.startswith('"') and text.endswith('"')) or (
        text.startswith("'") and text.endswith("'")
    ):
        return text[1:-1]
    try:
        if any(char in text for char in ".eE"):
            return float(text)
        return int(text)
    except ValueError:
        return text


def load_simple_yaml_mapping(path: Path) -> dict[str, Any]:
    root: dict[str, Any] = {}
    current_section: dict[str, Any] | None = None
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if stripped.startswith("- "):
            continue
        if ":" not in stripped:
            raise ValueError(f"unsupported YAML line in {path}:{line_number}: {raw_line!r}")
        key, raw_value = stripped.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if indent == 0:
            if raw_value:
                root[key] = parse_simple_yaml_scalar(raw_value)
                current_section = None
            else:
                section: dict[str, Any] = {}
                root[key] = section
                current_section = section
            continue
        if current_section is None:
            raise ValueError(
                f"unsupported nested YAML line without a parent section in {path}:{line_number}"
            )
        current_section[key] = parse_simple_yaml_scalar(raw_value)
    return root


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    if yaml is not None:  # pragma: no cover - depends on optional local package
        with path.open("r", encoding="utf-8") as handle:
            payload = yaml.safe_load(handle)
    else:
        payload = load_simple_yaml_mapping(path)
    if not isinstance(payload, dict):
        raise ValueError(f"preset YAML must contain a mapping object: {path}")
    return payload


def required_string(mapping: dict[str, Any], key: str, label: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label}.{key} must be a non-empty string")
    return value


def required_float(mapping: dict[str, Any], key: str, label: str) -> float:
    value = mapping.get(key)
    if not isinstance(value, (int, float)):
        raise ValueError(f"{label}.{key} must be numeric")
    return float(value)


def load_preset_capital_profile(path: Path) -> dict[str, Any]:
    payload = load_yaml_mapping(path)
    preset = required_string(payload, "preset", "preset")
    top_market = required_string(payload, "market", "preset")
    top_horizon = required_string(payload, "horizon", "preset")
    capital = payload.get("capital")
    if not isinstance(capital, dict):
        raise ValueError(f"preset.capital must be a mapping object: {path}")

    market = required_string(capital, "market", "preset.capital")
    horizon = required_string(capital, "horizon", "preset.capital")
    bucket = required_string(capital, "bucket", "preset.capital")
    capital_basis = required_string(capital, "capital_basis", "preset.capital")
    policy_id = required_string(capital, "portfolio_allocation_policy", "preset.capital")
    if market != top_market:
        raise ValueError(f"preset.capital.market must match preset.market: {market} != {top_market}")
    if horizon != top_horizon:
        raise ValueError(
            f"preset.capital.horizon must match preset.horizon: {horizon} != {top_horizon}"
        )
    if market not in {"A", "US"}:
        raise ValueError(f"unsupported preset.capital.market: {market!r}")
    if horizon not in {"short", "long"}:
        raise ValueError(f"unsupported preset.capital.horizon: {horizon!r}")
    if bucket not in {"short", "long"}:
        raise ValueError(f"unsupported preset.capital.bucket: {bucket!r}")
    if capital_basis != "bucket_capital":
        raise ValueError(f"unsupported preset.capital.capital_basis: {capital_basis!r}")
    return {
        "preset": preset,
        "market": market,
        "horizon": horizon,
        "bucket": bucket,
        "capital_basis": capital_basis,
        "bucket_target_pct": required_float(capital, "bucket_target_pct", "preset.capital"),
        "bucket_ceiling_pct": required_float(capital, "bucket_ceiling_pct", "preset.capital"),
        "portfolio_allocation_policy": policy_id,
    }


def load_analysis_input(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"analysis_input must be a JSON object: {path}")
    if not isinstance(payload.get("candidates"), list):
        raise ValueError(f"analysis_input.candidates must be a list: {path}")
    return payload


def load_execution_price_data(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"execution_price_data must be a JSON object: {path}")
    validate_json_schema(payload, PRICE_DATA_SCHEMA_PATH, "execution_price_data")
    return payload


def load_portfolio_allocation(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"portfolio_allocation must be a JSON object: {path}")
    validate_json_schema(payload, PORTFOLIO_ALLOCATION_SCHEMA_PATH, "portfolio_allocation")
    return payload


def load_cash_buffer_state(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"cash_buffer_state must be a JSON object: {path}")
    validate_json_schema(payload, CASH_BUFFER_STATE_SCHEMA_PATH, "cash_buffer_state")
    return payload


def resolve_input_path(as_of: str, input_path: Path | None) -> Path:
    if input_path is not None:
        return input_path
    return DEFAULT_INPUT_ROOT / as_of / "analysis_input.json"


def validate_report(report: dict[str, Any]) -> None:
    validate_json_schema(report, REPORT_SCHEMA_PATH, "execution report")


def validate_json_schema(payload: dict[str, Any], schema_path: Path, label: str) -> None:
    if Draft7Validator is None:  # pragma: no cover - environment guard
        raise RuntimeError(
            f"jsonschema is required to validate {label}"
        ) from JSONSCHEMA_IMPORT_ERROR
    schema = load_json(schema_path)
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
    if errors:
        details = "\n".join(
            f"- {'/'.join(str(part) for part in error.path) or '<root>'}: {error.message}"
            for error in errors
        )
        raise ValueError(f"{label} schema validation failed:\n{details}")


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


def validate_price_data_semantics(
    price_data: dict[str, Any], analysis_input: dict[str, Any], as_of: str
) -> None:
    date_range = price_data["date_range"]
    start_date = str(date_range["start_date"])
    end_date = str(date_range["end_date"])
    if not (start_date <= as_of <= end_date):
        raise ValueError(
            "execution_price_data.date_range must cover --as-of "
            f"{as_of}: got {start_date}..{end_date}"
        )

    candidate_codes = {
        candidate_code(candidate)
        for candidate in analysis_input.get("candidates", [])
        if candidate_code(candidate)
    }
    available_symbols = {str(symbol) for symbol in price_data.get("symbols", [])}
    missing_symbols = sorted(candidate_codes - available_symbols)
    if missing_symbols:
        raise ValueError(
            "execution_price_data.symbols must include all analysis_input candidates: "
            + ", ".join(missing_symbols)
        )

    available_rows = {
        (str(row.get("ts_code")), str(row.get("trade_date")))
        for row in price_data.get("rows", [])
        if isinstance(row, dict)
    }
    missing_rows = sorted(
        code for code in candidate_codes if (code, as_of) not in available_rows
    )
    if missing_rows:
        raise ValueError(
            "execution_price_data.rows must include each analysis_input candidate "
            f"on --as-of {as_of}: " + ", ".join(missing_rows)
        )


def price_data_ref(
    price_data: dict[str, Any] | None, price_data_path: Path | None, as_of: str
) -> dict[str, str]:
    if price_data is None or price_data_path is None:
        return {
            "path": "not_available_phase5_skeleton",
            "start_date": as_of,
            "end_date": as_of,
            "adj": "qfq_via_adj_factor",
        }
    return {
        "path": relative_ref(price_data_path),
        "start_date": str(price_data["date_range"]["start_date"]),
        "end_date": str(price_data["date_range"]["end_date"]),
        "adj": str(price_data["source"]["adjustment_mode"]),
    }


def _find_one(items: list[dict[str, Any]], key: str, value: str, label: str) -> dict[str, Any]:
    matches = [item for item in items if isinstance(item, dict) and str(item.get(key)) == value]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {label} with {key}={value!r}; got {len(matches)}")
    return matches[0]


def build_capital_context(
    portfolio_allocation: dict[str, Any],
    portfolio_allocation_path: Path,
    cash_buffer_state: dict[str, Any],
    cash_buffer_state_path: Path,
    preset_profile: dict[str, Any],
) -> dict[str, Any]:
    preset = required_string(preset_profile, "preset", "preset_profile")
    market = required_string(preset_profile, "market", "preset_profile")
    bucket = required_string(preset_profile, "bucket", "preset_profile")
    horizon = required_string(preset_profile, "horizon", "preset_profile")

    policy_id = str(portfolio_allocation["policy_id"])
    if str(preset_profile["portfolio_allocation_policy"]) != policy_id:
        raise ValueError(
            "preset.capital.portfolio_allocation_policy must match "
            f"portfolio_allocation.policy_id: {preset_profile['portfolio_allocation_policy']} != {policy_id}"
        )
    state_policy_ref = cash_buffer_state["portfolio_policy_ref"]
    if str(state_policy_ref["policy_id"]) != policy_id:
        raise ValueError(
            "cash_buffer_state.portfolio_policy_ref.policy_id must match "
            f"portfolio_allocation.policy_id: {state_policy_ref['policy_id']} != {policy_id}"
        )

    market_policy = _find_one(
        portfolio_allocation["markets"], "market", market, "portfolio allocation market"
    )
    bucket_policy = _find_one(
        market_policy["buckets"], "bucket", bucket, "portfolio allocation bucket"
    )
    if bucket_policy.get("preset") != preset:
        raise ValueError(
            f"portfolio_allocation bucket {market}/{bucket} must reference preset {preset}"
        )
    if abs(float(bucket_policy["target_pct"]) - float(preset_profile["bucket_target_pct"])) > 1e-9:
        raise ValueError(
            f"portfolio_allocation bucket {market}/{bucket} target_pct must match preset capital block"
        )
    if abs(float(bucket_policy["ceiling_pct"]) - float(preset_profile["bucket_ceiling_pct"])) > 1e-9:
        raise ValueError(
            f"portfolio_allocation bucket {market}/{bucket} ceiling_pct must match preset capital block"
        )
    liquidity_policy = _find_one(
        market_policy["buckets"], "bucket", "liquidity", "portfolio liquidity bucket"
    )

    market_state = _find_one(cash_buffer_state["markets"], "market", market, "cash state market")
    bucket_state = _find_one(market_state["buckets"], "bucket", bucket, "cash state bucket")
    if bucket_state.get("preset") != preset:
        raise ValueError(f"cash_buffer_state bucket {market}/{bucket} must reference preset {preset}")

    ship_gate_policy = portfolio_allocation["ship_gate_policy"]
    return {
        "portfolio_allocation_ref": {
            "path": relative_ref(portfolio_allocation_path),
            "schema_version": str(portfolio_allocation["schema_version"]),
            "policy_id": policy_id,
        },
        "cash_buffer_state_ref": {
            "path": relative_ref(cash_buffer_state_path),
            "schema_version": str(cash_buffer_state["schema_version"]),
            "state_id": str(cash_buffer_state["state_id"]),
            "as_of": str(cash_buffer_state["as_of"]),
        },
        "preset": preset,
        "market": market,
        "horizon": horizon,
        "bucket": bucket,
        "currency": str(market_policy["currency"]),
        "capital_basis": str(preset_profile["capital_basis"]),
        "total_portfolio_capital": float(cash_buffer_state["total_portfolio_capital"]),
        "market_allocation_pct": float(market_policy["allocation_pct"]),
        "market_capital": float(market_state["capital"]["market_capital"]),
        "bucket_target_pct": float(bucket_policy["target_pct"]),
        "bucket_ceiling_pct": float(bucket_policy["ceiling_pct"]),
        "bucket_capital": float(bucket_state["capital"]),
        "liquidity_reserve_pct": float(liquidity_policy["target_pct"]),
        "liquidity_floor_policy": str(portfolio_allocation["liquidity_policy"]["floor_policy"]),
        "cross_market_cash_fungible": False,
        "manual_execution_only": bool(portfolio_allocation["execution_boundary"]["manual_order_only"]),
        "ship_gate": {
            "policy_logic": str(ship_gate_policy["logic"]),
            "monthly_alpha_t_stat_min": float(ship_gate_policy["monthly_alpha_t_stat_min"]),
            "sharpe_min": float(ship_gate_policy["sharpe_min"]),
            "max_drawdown_max": float(ship_gate_policy["max_drawdown_max"]),
            "forward_live_months_min": int(ship_gate_policy["forward_live_months_min"]),
            "failure_mode": str(ship_gate_policy["failure_mode"]),
            "status": "not_evaluated",
            "full_size_allowed": False,
            "reason": "Phase 5 skeleton has not evaluated forward-live ship-gate metrics.",
        },
    }


def validate_initial_capital_guard(args: argparse.Namespace, capital_context: dict[str, Any]) -> None:
    if args.initial_capital is None:
        return
    bucket_capital = float(capital_context["bucket_capital"])
    if abs(args.initial_capital - bucket_capital) > 0.01:
        raise ValueError(
            "--initial-capital is only a guard in v1.2.0 and must equal "
            f"capital_context.bucket_capital ({bucket_capital:.2f}); got {args.initial_capital:.2f}"
        )


def execution_price_api_families(price_data: dict[str, Any] | None) -> list[str]:
    if price_data is None:
        return ["not_implemented_phase5_skeleton"]
    return [str(item) for item in price_data["source"]["api_families"]]


def candidate_code(candidate: dict[str, Any]) -> str:
    return str(candidate.get("ts_code") or candidate.get("code") or "")


def candidate_name(candidate: dict[str, Any]) -> str:
    return str(candidate.get("name") or candidate.get("stock_name") or "")


def nested_value(payload: dict[str, Any], *path: str) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def coerce_positive_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return number


def candidate_stop_loss(candidate: dict[str, Any], entry_price: float | None = None) -> float | None:
    candidates = [
        nested_value(candidate, "execution", "stop_loss"),
        nested_value(candidate, "exit_plan", "stop_loss"),
        nested_value(candidate, "technical", "stop_loss"),
        nested_value(candidate, "technical", "support", "price"),
    ]
    for value in candidates:
        stop = coerce_positive_float(value)
        if stop is None:
            continue
        if entry_price is not None and stop >= entry_price:
            continue
        return stop
    return None


def price_rows_by_symbol(price_data: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in price_data.get("rows", []):
        if not isinstance(row, dict):
            continue
        by_symbol.setdefault(str(row.get("ts_code")), []).append(row)
    for rows in by_symbol.values():
        rows.sort(key=lambda item: str(item.get("trade_date")))
    return by_symbol


def first_price_row_after(
    rows: list[dict[str, Any]], as_of: str
) -> tuple[int, dict[str, Any]] | tuple[None, None]:
    for index, row in enumerate(rows):
        if str(row.get("trade_date")) > as_of:
            return index, row
    return None, None


def is_limit_up_unbuyable(row: dict[str, Any]) -> bool:
    entry_open = coerce_positive_float(row.get("open_qfq"))
    up_limit = coerce_positive_float(row.get("up_limit"))
    if entry_open is None or up_limit is None:
        return False
    return entry_open >= up_limit * 0.999


def calculate_shares(
    entry_price: float, cash: float, bucket_capital: float, args: argparse.Namespace
) -> int:
    per_trade_budget = min(
        cash,
        bucket_capital * args.max_position_pct,
        bucket_capital / max(args.max_positions, 1),
    )
    gross_budget = per_trade_budget / (1.0 + args.cost_pct)
    raw_shares = int(gross_budget // entry_price)
    if raw_shares < A_SHARE_LOT_SIZE:
        return 0
    return (raw_shares // A_SHARE_LOT_SIZE) * A_SHARE_LOT_SIZE


def build_execution_assumptions(
    args: argparse.Namespace, capital_context: dict[str, Any]
) -> dict[str, Any]:
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
            "source": "execution_price_data_when_provided",
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
            "capital_basis": "bucket_capital",
            "max_position_pct": args.max_position_pct,
            "bucket_ceiling_pct": capital_context["bucket_ceiling_pct"],
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
                "missing_price_data",
                "missing_stop",
                "stop_loss",
                "take_profit",
                "time_stop",
                "cash_constrained",
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
        return "candidate skipped: no deterministic stop input below entry price"
    if row["reason"] == "missing_price_data":
        return "candidate skipped: insufficient execution price data for entry or exit"
    if row["reason"] == "entry_unbuyable":
        return "candidate skipped: T+1 open is at or near up limit"
    if row["reason"] == "cash_constrained":
        return "candidate skipped: bucket cash is insufficient for one A-share lot"
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


def empty_simulation_result(
    payload: dict[str, Any],
    capital_context: dict[str, Any],
    skipped_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    as_of = str(payload.get("trade_date"))
    bucket_capital = float(capital_context["bucket_capital"])
    missing_stop_count = sum(1 for row in skipped_rows if row["reason"] == "missing_stop")
    analyzer_veto_count = sum(
        1 for row in skipped_rows if row["reason"] == "analyzer_hard_veto"
    )
    warning_message = (
        "Phase 5 skeleton writes contract outputs only; no execution price simulator "
        "has accepted trades yet."
    )
    if analyzer_veto_count:
        warning_message += f" Rule 6 hard veto replay skipped {analyzer_veto_count} candidate(s)."
    return {
        "trades": [],
        "skipped_rows": skipped_rows,
        "order_events": build_order_events(as_of, skipped_rows),
        "daily_equity": [
            {
                "trade_date": as_of,
                "equity": bucket_capital,
                "cash": bucket_capital,
                "market_value": 0.0,
                "drawdown": 0.0,
            }
        ],
        "metrics": {
            "trade_count": 0,
            "skipped_count": len(skipped_rows),
            "entry_unbuyable_count": 0,
            "missing_stop_count": missing_stop_count,
            "win_rate": None,
            "total_return": None,
            "annualized_return": None,
            "max_drawdown": None,
            "avg_holding_days": None,
            "ending_equity": bucket_capital,
        },
        "date_warnings": [
            {
                "trade_date": as_of,
                "warning_type": "no_executable_candidates",
                "severity": "warning" if payload.get("candidates") else "critical",
                "message": warning_message,
            }
        ],
        "limitations": [
            "Phase 5 skeleton validates the execution report contract and writes CSV shells only.",
            "Candidates that pass analyzer replay are skipped as missing_stop until deterministic stop rules are wired.",
            "No execution price fetch, limit-up matching, order fill, portfolio accounting, or exit simulation is implemented yet.",
        ],
    }


def add_event(
    events: list[dict[str, Any]],
    event_id: int,
    as_of: str,
    ts_code: str,
    event_code: str,
    message: str,
) -> int:
    events.append(
        {
            "event_id": event_id,
            "as_of": as_of,
            "ts_code": ts_code,
            "event_code": event_code,
            "message": message,
        }
    )
    return event_id + 1


def skip_row(
    candidate: dict[str, Any],
    reason: str,
    analyzer_vetoed: bool = False,
    analyzer_reason_codes: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "ts_code": candidate_code(candidate),
        "name": candidate_name(candidate),
        "reason": reason,
        "analyzer_vetoed": analyzer_vetoed,
        "analyzer_reason_codes": ",".join(analyzer_reason_codes or []),
    }


def simulate_execution(
    payload: dict[str, Any],
    price_data: dict[str, Any],
    args: argparse.Namespace,
    capital_context: dict[str, Any],
) -> dict[str, Any]:
    as_of = str(payload.get("trade_date") or args.as_of)
    bucket_capital = float(capital_context["bucket_capital"])
    cash = bucket_capital
    peak_equity = bucket_capital
    by_symbol = price_rows_by_symbol(price_data)
    trades: list[dict[str, Any]] = []
    skipped_rows: list[dict[str, Any]] = []
    daily_equity: list[dict[str, Any]] = [
        {
            "trade_date": as_of,
            "equity": round(bucket_capital, 6),
            "cash": round(bucket_capital, 6),
            "market_value": 0.0,
            "drawdown": 0.0,
        }
    ]
    events: list[dict[str, Any]] = []
    event_id = 1
    missing_price_data_count = 0
    entry_unbuyable_count = 0
    missing_stop_count = 0

    for candidate in payload.get("candidates", []):
        ts_code = candidate_code(candidate)
        event_id = add_event(
            events, event_id, as_of, ts_code, "candidate_seen", "candidate loaded from analysis_input"
        )
        decision = run_veto(candidate)
        reason_codes = [
            str(reason.get("code"))
            for reason in decision.get("reasons", [])
            if isinstance(reason, dict) and reason.get("code")
        ]
        if bool(decision.get("vetoed")):
            row = skip_row(candidate, "analyzer_hard_veto", True, reason_codes)
            skipped_rows.append(row)
            event_id = add_event(
                events, event_id, as_of, ts_code, "candidate_seen", event_message_for_skip(row)
            )
            continue

        rows = by_symbol.get(ts_code, [])
        entry_index, entry_row = first_price_row_after(rows, as_of)
        if entry_index is None or entry_row is None:
            missing_price_data_count += 1
            row = skip_row(candidate, "missing_price_data")
            skipped_rows.append(row)
            event_id = add_event(
                events, event_id, as_of, ts_code, "missing_price_data", event_message_for_skip(row)
            )
            continue

        entry_price = coerce_positive_float(entry_row.get("open_qfq"))
        if entry_price is None:
            missing_price_data_count += 1
            row = skip_row(candidate, "missing_price_data")
            skipped_rows.append(row)
            event_id = add_event(
                events, event_id, as_of, ts_code, "missing_price_data", event_message_for_skip(row)
            )
            continue

        if is_limit_up_unbuyable(entry_row):
            entry_unbuyable_count += 1
            row = skip_row(candidate, "entry_unbuyable")
            skipped_rows.append(row)
            event_id = add_event(
                events, event_id, as_of, ts_code, "entry_unbuyable", event_message_for_skip(row)
            )
            continue

        stop_loss = candidate_stop_loss(candidate)
        if stop_loss is None or stop_loss >= entry_price:
            missing_stop_count += 1
            row = skip_row(candidate, "missing_stop")
            skipped_rows.append(row)
            event_id = add_event(
                events, event_id, as_of, ts_code, "missing_stop", event_message_for_skip(row)
            )
            continue

        exit_index = entry_index + args.time_stop_days - 1
        if exit_index >= len(rows):
            missing_price_data_count += 1
            row = skip_row(candidate, "missing_price_data")
            skipped_rows.append(row)
            event_id = add_event(
                events, event_id, as_of, ts_code, "missing_price_data", event_message_for_skip(row)
            )
            continue

        exit_row = rows[exit_index]
        exit_row_index = exit_index
        exit_reason = "time_stop"
        exit_price = coerce_positive_float(exit_row.get("close_qfq"))
        if exit_price is None:
            missing_price_data_count += 1
            row = skip_row(candidate, "missing_price_data")
            skipped_rows.append(row)
            event_id = add_event(
                events, event_id, as_of, ts_code, "missing_price_data", event_message_for_skip(row)
            )
            continue
        for row_index in range(entry_index, exit_index + 1):
            row = rows[row_index]
            low = coerce_positive_float(row.get("low_qfq"))
            if low is not None and low <= stop_loss:
                open_price = coerce_positive_float(row.get("open_qfq"))
                exit_row = row
                exit_row_index = row_index
                exit_reason = "stop_loss"
                exit_price = (
                    open_price if open_price is not None and open_price <= stop_loss else stop_loss
                )
                break

        shares = calculate_shares(entry_price, cash, bucket_capital, args)
        if shares <= 0:
            row = skip_row(candidate, "cash_constrained")
            skipped_rows.append(row)
            event_id = add_event(
                events, event_id, as_of, ts_code, "cash_constrained", event_message_for_skip(row)
            )
            continue

        entry_date = str(entry_row["trade_date"])
        entry_gross = shares * entry_price
        entry_cost = entry_gross * args.cost_pct
        cash -= entry_gross + entry_cost
        event_id = add_event(
            events,
            event_id,
            entry_date,
            ts_code,
            "entry",
            f"entered {shares} shares at T+1 open_qfq {entry_price:.4f}",
        )

        exit_date = str(exit_row["trade_date"])
        exit_gross = shares * exit_price
        exit_cost = exit_gross * args.cost_pct
        pnl = exit_gross - exit_cost - entry_gross - entry_cost
        cash += exit_gross - exit_cost
        holding_days = exit_row_index - entry_index + 1
        trades.append(
            {
                "trade_id": len(trades) + 1,
                "ts_code": ts_code,
                "entry_date": entry_date,
                "exit_date": exit_date,
                "entry_price": round(entry_price, 6),
                "exit_price": round(exit_price, 6),
                "shares": shares,
                "pnl": round(pnl, 6),
                "return_pct": round(pnl / (entry_gross + entry_cost), 8),
                "exit_reason": exit_reason,
                "holding_days": holding_days,
            }
        )
        event_id = add_event(
            events,
            event_id,
            exit_date,
            ts_code,
            exit_reason,
            f"{exit_reason} exit at {exit_price:.4f}",
        )
        event_id = add_event(
            events,
            event_id,
            exit_date,
            ts_code,
            "exit",
            f"closed trade with net pnl {pnl:.2f}",
        )
        equity = cash
        peak_equity = max(peak_equity, equity)
        drawdown = 0.0 if peak_equity <= 0 else (equity / peak_equity) - 1.0
        daily_equity.append(
            {
                "trade_date": exit_date,
                "equity": round(equity, 6),
                "cash": round(cash, 6),
                "market_value": 0.0,
                "drawdown": round(drawdown, 8),
            }
        )

    trade_count = len(trades)
    wins = sum(1 for trade in trades if float(trade["pnl"]) > 0)
    total_pnl = sum(float(trade["pnl"]) for trade in trades)
    max_drawdown = min(float(row["drawdown"]) for row in daily_equity) if daily_equity else None
    avg_holding_days = None
    if trade_count:
        avg_holding_days = sum(int(trade["holding_days"]) for trade in trades) / trade_count
    date_warnings: list[dict[str, Any]] = []
    if trade_count == 0:
        date_warnings.append(
            {
                "trade_date": as_of,
                "warning_type": "no_executable_candidates",
                "severity": "warning" if payload.get("candidates") else "critical",
                "message": "No candidates produced executable trades after fill simulation.",
            }
        )
    if missing_price_data_count:
        date_warnings.append(
            {
                "trade_date": as_of,
                "warning_type": "missing_price_data",
                "severity": "warning",
                "message": f"{missing_price_data_count} candidate(s) lacked entry or exit price rows.",
            }
        )
    return {
        "trades": trades,
        "skipped_rows": skipped_rows,
        "order_events": events,
        "daily_equity": daily_equity,
        "metrics": {
            "trade_count": trade_count,
            "skipped_count": len(skipped_rows),
            "entry_unbuyable_count": entry_unbuyable_count,
            "missing_stop_count": missing_stop_count,
            "win_rate": (wins / trade_count) if trade_count else None,
            "total_return": (total_pnl / bucket_capital) if trade_count else None,
            "annualized_return": None,
            "max_drawdown": max_drawdown,
            "avg_holding_days": avg_holding_days,
            "ending_equity": cash,
        },
        "date_warnings": date_warnings,
        "limitations": [
            "Phase 5 minimal fill simulation uses daily OHLC only; intraday path within the day is not modeled.",
            "Stop-loss exits use the day's open_qfq when it opens below the stop; otherwise a low_qfq stop touch fills at the stop price.",
            "The first fill increment processes candidates sequentially and does not yet model concurrent open positions.",
            "Daily equity currently records starting equity and realized exit dates; open-position mark-to-market is not yet modeled.",
            "total_return is realized total_pnl divided by initial bucket_capital; no alternate ending-equity-normalized return is emitted yet.",
            "All generated actions are backtest events only; manual-order-only boundary remains in force.",
        ],
    }


def output_refs(out_dir: Path) -> dict[str, str]:
    return {
        "execution_report": relative_ref(out_dir / "execution_report.json"),
        "trades": relative_ref(out_dir / "trades.csv"),
        "daily_equity": relative_ref(out_dir / "daily_equity.csv"),
        "order_events": relative_ref(out_dir / "order_events.csv"),
        "skipped_candidates": relative_ref(out_dir / "skipped_candidates.csv"),
    }


def ship_gate_metric_result(
    value: float | None,
    threshold: float,
    passed: bool | None,
    reason: str,
) -> dict[str, Any]:
    return {
        "value": value,
        "threshold": threshold,
        "passed": passed,
        "reason": reason,
    }


def build_ship_gate_evaluation(
    report_metrics: dict[str, Any], capital_context: dict[str, Any]
) -> dict[str, Any]:
    policy = capital_context["ship_gate"]
    trade_count = int(report_metrics.get("trade_count") or 0)
    max_drawdown = report_metrics.get("max_drawdown")
    max_drawdown_value = (
        float(max_drawdown) if isinstance(max_drawdown, (int, float)) else None
    )
    max_drawdown_threshold = float(policy["max_drawdown_max"])
    max_drawdown_passed = None
    max_drawdown_reason = "requires simulated equity drawdown; no executable equity path was available"
    if trade_count == 0:
        max_drawdown_value = None
        max_drawdown_reason = "no executed trades to evaluate drawdown signal"
    elif max_drawdown_value is not None:
        max_drawdown_passed = abs(max_drawdown_value) <= max_drawdown_threshold
        max_drawdown_reason = "uses realized daily_equity drawdown from this execution run"

    metric_results = {
        "monthly_alpha_t_stat": ship_gate_metric_result(
            None,
            float(policy["monthly_alpha_t_stat_min"]),
            None,
            "requires a multi-period benchmark-excess return series; this single execution report does not compute it",
        ),
        "sharpe": ship_gate_metric_result(
            None,
            float(policy["sharpe_min"]),
            None,
            "requires a multi-period return series; this single execution report does not compute it",
        ),
        "max_drawdown": ship_gate_metric_result(
            max_drawdown_value,
            max_drawdown_threshold,
            max_drawdown_passed,
            max_drawdown_reason,
        ),
        "forward_live_months": ship_gate_metric_result(
            0.0,
            float(policy["forward_live_months_min"]),
            False,
            "backtest reports carry no forward-live observation months",
        ),
    }
    passed_values = [result["passed"] for result in metric_results.values()]
    if any(value is None for value in passed_values):
        status = "not_evaluable"
    elif all(bool(value) for value in passed_values):
        status = "pass"
    else:
        status = "fail"

    return {
        "policy_logic": str(policy["policy_logic"]),
        "status": status,
        "full_size_allowed": status == "pass",
        "failure_mode": str(policy.get("failure_mode") or SHIP_GATE_FAILURE_MODE),
        "manual_execution_only": bool(capital_context["manual_execution_only"]),
        "metric_results": metric_results,
        "limitations": [
            "monthly_alpha_t_stat and sharpe need multi-period benchmark-aware aggregation outside a single execution report.",
            "forward_live_months is always 0 for a backtest report; Phase 6 forward tracking must supply live evidence.",
            "full_size_allowed only turns true when every AND-gate metric is evaluable and passes under the manual-order boundary.",
        ],
    }


def build_report(
    payload: dict[str, Any],
    input_path: Path,
    out_dir: Path,
    args: argparse.Namespace,
    capital_context: dict[str, Any],
    skipped_rows: list[dict[str, Any]] | None = None,
    price_data: dict[str, Any] | None = None,
    price_data_path: Path | None = None,
    simulation: dict[str, Any] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    as_of = str(payload.get("trade_date") or args.as_of)
    candidates = payload.get("candidates", [])
    if skipped_rows is None:
        skipped_rows = classify_skips(candidates)
    if simulation is None:
        simulation = empty_simulation_result(payload, capital_context, skipped_rows)
    candidate_count = len(candidates)
    sim_metrics = dict(simulation["metrics"])
    report_metrics = {
        "sample_count": candidate_count,
        "candidate_count": candidate_count,
        **sim_metrics,
    }

    return {
        "schema_name": "execution_backtest_report",
        "schema_version": "1.2.0",
        "generated_at": generated_at or iso_now(),
        "preset": str(capital_context["preset"]),
        "mode": args.mode,
        "settings": {
            "mode": args.mode,
            "start_date": as_of,
            "end_date": as_of,
            "initial_capital": capital_context["bucket_capital"],
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
            "price_data": price_data_ref(price_data, price_data_path, as_of),
        },
        "capital_context": capital_context,
        "execution_assumptions": build_execution_assumptions(args, capital_context),
        "data_lineage": {
            "data_provider": "tushare",
            "api_families": {
                "candidate_generation": ["analysis_input"],
                "execution_price": execution_price_api_families(price_data),
                "state_replay": ["state_manager_json"],
            },
            "forward_return_adjustment_mode": "qfq_via_adj_factor",
            "benchmark_sources": {
                "csi300": "not_used_phase5_skeleton",
                "csi1000": "not_used_phase5_skeleton",
            },
            "pit_limitations": [
                (
                    "Execution price data is used by the Phase 5 minimal daily-OHLC fill simulator."
                    if price_data is not None
                    else "Execution prices are not fetched in the Phase 5 skeleton."
                ),
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
        "metrics": report_metrics,
        "ship_gate_evaluation": build_ship_gate_evaluation(report_metrics, capital_context),
        "date_warnings": simulation["date_warnings"],
        "limitations": simulation["limitations"],
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
    simulation: dict[str, Any] | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    as_of = str(payload.get("trade_date") or report["settings"]["end_date"])
    if skipped_rows is None:
        skipped_rows = classify_skips(payload.get("candidates", []))
    if simulation is None:
        simulation = empty_simulation_result(payload, report["capital_context"], skipped_rows)

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
            "holding_days",
        ],
        simulation["trades"],
    )
    write_csv(
        out_dir / "daily_equity.csv",
        ["trade_date", "equity", "cash", "market_value", "drawdown"],
        simulation["daily_equity"],
    )
    write_csv(
        out_dir / "order_events.csv",
        ["event_id", "as_of", "ts_code", "event_code", "message"],
        simulation["order_events"],
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
    price_data = None
    price_data_path = None
    if args.price_data is not None:
        price_data_path = args.price_data
        price_data = load_execution_price_data(price_data_path)
        validate_price_data_semantics(price_data, payload, args.as_of)
    portfolio_allocation = load_portfolio_allocation(args.portfolio_allocation)
    cash_buffer_state = load_cash_buffer_state(args.cash_buffer_state)
    preset_profile = load_preset_capital_profile(args.preset_path)
    capital_context = build_capital_context(
        portfolio_allocation,
        args.portfolio_allocation,
        cash_buffer_state,
        args.cash_buffer_state,
        preset_profile,
    )
    validate_initial_capital_guard(args, capital_context)
    out_dir = args.out_dir
    if price_data is None:
        skipped_rows = classify_skips(payload.get("candidates", []))
        simulation = empty_simulation_result(payload, capital_context, skipped_rows)
    else:
        simulation = simulate_execution(payload, price_data, args, capital_context)
        skipped_rows = simulation["skipped_rows"]
    report = build_report(
        payload,
        input_path,
        out_dir,
        args,
        capital_context,
        skipped_rows=skipped_rows,
        price_data=price_data,
        price_data_path=price_data_path,
        simulation=simulation,
    )
    write_outputs(report, payload, out_dir, skipped_rows=skipped_rows, simulation=simulation)
    print(f"[OK] wrote {out_dir / 'execution_report.json'}")
    print(f"[OK] wrote {out_dir / 'trades.csv'}")
    print(f"[OK] wrote {out_dir / 'daily_equity.csv'}")
    print(f"[OK] wrote {out_dir / 'order_events.csv'}")
    print(f"[OK] wrote {out_dir / 'skipped_candidates.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
