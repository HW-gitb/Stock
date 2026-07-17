"""Strict local runtime configuration for the A-short screening and M6.7 paths.

Business thresholds live in reviewed JSON policy files.  Python deliberately
keeps only the calculation code and this closed-world validator: a missing,
unknown, malformed, or unsafe policy value is a startup error, never an
implicit fallback to a Python literal.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRESET_RELATIVE_PATH = "presets/a_short.yaml"
_REGIMES = ("进攻期", "震荡期", "防御期", "收缩期")
_SCREENING_KEYS = (
    "min_avg_amount", "unlock_ratio", "top_n", "watch_n", "final_n",
    "suspend_lookback", "suspend_daily_min_coverage", "daily_stats_min_rows",
    "momentum_std_threshold", "overheat_5d",
    "overheat_20d", "esp_raw_cap",
)
_PHASE5_KEYS = (
    "atr_mult", "rr_floor", "single_cap_pct", "iv_halve_pct", "iv_nobuild_pct",
    "iv_hv_ratio_hi", "iv_hv_ratio_lo", "min_avg_amount_5d", "lowxi_band",
    "support_lookback", "resistance_lookback",
    "sr_spike_atr", "breakout_rr_bonus", "min_shares", "min_amount", "impact_cost_frac",
)
_PORTFOLIO_KEYS = (
    "same_sw_l2_threshold_pct", "northbound_threshold_pct", "margin_threshold_pct",
    "large_index_threshold_pct", "small_float_mv_threshold_pct", "small_float_mv_rmb",
    "high_risk_holding_cap_multiplier",
)
_WEEKLY_WINDOW_KEYS = (
    "min_price_observations", "ex_div_window_days", "forward_event_window_days",
    "dragon_list_lookback_trading_days", "block_trade_lookback_trading_days",
)

class RuntimeConfigError(ValueError):
    """Raised before any provider call when a runtime policy cannot be trusted."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: object) -> str:
    return _sha256_bytes(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8"))


def _read_flat_preset_section(path: Path, section_name: str) -> dict[str, str]:
    """Read one flat routing section without adding a YAML runtime dependency."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeConfigError(f"cannot read A-short preset {path}: {exc}") from exc
    section: dict[str, str] = {}
    found = False
    for line_number, raw in enumerate(lines, 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if re.fullmatch(rf"{re.escape(section_name)}\s*:\s*(?:#.*)?", raw):
            if found:
                raise RuntimeConfigError(f"preset repeats routing section {section_name}")
            found = True
            continue
        if not found:
            continue
        if raw[0] not in " \t":
            break
        if not raw.startswith("  ") or raw.startswith("    "):
            raise RuntimeConfigError(
                f"preset {section_name} must be a flat two-space mapping at {path}:{line_number}"
            )
        stripped = raw.strip()
        if ":" not in stripped:
            raise RuntimeConfigError(f"invalid preset route line {path}:{line_number}")
        key, value = (part.strip() for part in stripped.split(":", 1))
        if not key or not value or key in section:
            raise RuntimeConfigError(f"invalid/duplicate preset route key {path}:{line_number}")
        section[key] = value.strip("\"'")
    if not found:
        raise RuntimeConfigError(f"preset missing routing section {section_name}")
    return section


def _repo_path(root: Path, value: str, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeConfigError(f"{label} must be a non-empty repo-relative path")
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeConfigError(f"{label} escapes repository root: {value!r}") from exc
    return path


def _exact_mapping(value: object, keys: tuple[str, ...], label: str) -> dict:
    if not isinstance(value, dict):
        raise RuntimeConfigError(f"{label} must be an object")
    actual = set(value)
    expected = set(keys)
    if actual != expected:
        missing, extra = sorted(expected - actual), sorted(actual - expected)
        raise RuntimeConfigError(f"{label} keys invalid: missing={missing}, extra={extra}")
    return value


def _number(value: object, label: str, *, minimum: float | None = None,
            maximum: float | None = None, integer: bool = False) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeConfigError(f"{label} must be a {'integer' if integer else 'number'}")
    value = float(value)
    if not math.isfinite(value):
        raise RuntimeConfigError(f"{label} must be finite")
    if integer and not value.is_integer():
        raise RuntimeConfigError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise RuntimeConfigError(f"{label} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise RuntimeConfigError(f"{label} must be <= {maximum}")
    return int(value) if integer else value


def _load_json_policy(path: Path, expected_schema: str, expected_version: str) -> tuple[dict, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise RuntimeConfigError(f"cannot read runtime policy {path}: {exc}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeConfigError(f"runtime policy is not valid UTF-8 JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeConfigError(f"runtime policy root must be an object: {path}")
    if payload.get("schema_name") != expected_schema or payload.get("schema_version") != expected_version:
        raise RuntimeConfigError(f"runtime policy schema/version mismatch: {path}")
    if payload.get("runtime_authority") is not True:
        raise RuntimeConfigError(f"runtime policy must explicitly declare runtime_authority=true: {path}")
    if not isinstance(payload.get("policy_id"), str) or not payload["policy_id"].strip():
        raise RuntimeConfigError(f"runtime policy policy_id missing: {path}")
    return payload, _sha256_bytes(raw)


def _validate_screening(payload: dict) -> dict:
    _exact_mapping(payload, ("schema_name", "schema_version", "policy_id", "runtime_authority", "thresholds"),
                   "screening policy")
    raw = _exact_mapping(payload["thresholds"], _SCREENING_KEYS, "screening.thresholds")
    out = {
        "min_avg_amount": _number(raw["min_avg_amount"], "screening.min_avg_amount", minimum=0.0),
        "unlock_ratio": _number(raw["unlock_ratio"], "screening.unlock_ratio", minimum=0.0, maximum=100.0),
        "top_n": _number(raw["top_n"], "screening.top_n", minimum=1, integer=True),
        "watch_n": _number(raw["watch_n"], "screening.watch_n", minimum=1, integer=True),
        "final_n": _number(raw["final_n"], "screening.final_n", minimum=1, integer=True),
        "suspend_lookback": _number(raw["suspend_lookback"], "screening.suspend_lookback", minimum=1, integer=True),
        "suspend_daily_min_coverage": _number(raw["suspend_daily_min_coverage"], "screening.suspend_daily_min_coverage", minimum=0.0, maximum=1.0),
        "daily_stats_min_rows": _number(raw["daily_stats_min_rows"], "screening.daily_stats_min_rows", minimum=1, integer=True),
        "momentum_std_threshold": _number(raw["momentum_std_threshold"], "screening.momentum_std_threshold", minimum=0.0),
        "overheat_5d": _number(raw["overheat_5d"], "screening.overheat_5d", minimum=0.0),
        "overheat_20d": _number(raw["overheat_20d"], "screening.overheat_20d", minimum=0.0),
        "esp_raw_cap": _number(raw["esp_raw_cap"], "screening.esp_raw_cap", minimum=0.0),
    }
    if not out["final_n"] <= out["watch_n"] <= out["top_n"]:
        raise RuntimeConfigError("screening requires final_n <= watch_n <= top_n")
    return out


def _regime_map(value: object, label: str, *, minimum: float, maximum: float | None = None) -> dict[str, float]:
    raw = _exact_mapping(value, _REGIMES, label)
    return {name: float(_number(raw[name], f"{label}.{name}", minimum=minimum, maximum=maximum))
            for name in _REGIMES}


def _validate_m67(payload: dict) -> dict:
    _exact_mapping(payload, ("schema_name", "schema_version", "policy_id", "runtime_authority",
                             "phase5", "portfolio_risk", "weekly_windows"), "M6.7 policy")
    phase = _exact_mapping(payload["phase5"], _PHASE5_KEYS, "m67.phase5")
    out_phase = {
        "atr_mult": _regime_map(phase["atr_mult"], "m67.phase5.atr_mult", minimum=0.0),
        "rr_floor": _regime_map(phase["rr_floor"], "m67.phase5.rr_floor", minimum=0.0),
        "single_cap_pct": _regime_map(phase["single_cap_pct"], "m67.phase5.single_cap_pct", minimum=0.0, maximum=1.0),
        "iv_halve_pct": _number(phase["iv_halve_pct"], "m67.phase5.iv_halve_pct", minimum=0.0, maximum=100.0),
        "iv_nobuild_pct": _number(phase["iv_nobuild_pct"], "m67.phase5.iv_nobuild_pct", minimum=0.0, maximum=100.0),
        "iv_hv_ratio_hi": _number(phase["iv_hv_ratio_hi"], "m67.phase5.iv_hv_ratio_hi", minimum=0.0),
        "iv_hv_ratio_lo": _number(phase["iv_hv_ratio_lo"], "m67.phase5.iv_hv_ratio_lo", minimum=0.0),
        "min_avg_amount_5d": _number(phase["min_avg_amount_5d"], "m67.phase5.min_avg_amount_5d", minimum=0.0),
        "lowxi_band": _number(phase["lowxi_band"], "m67.phase5.lowxi_band", minimum=0.0, maximum=1.0),
        "support_lookback": _number(phase["support_lookback"], "m67.phase5.support_lookback", minimum=2, integer=True),
        "resistance_lookback": _number(phase["resistance_lookback"], "m67.phase5.resistance_lookback", minimum=2, integer=True),
        "sr_spike_atr": _number(phase["sr_spike_atr"], "m67.phase5.sr_spike_atr", minimum=0.0),
        "breakout_rr_bonus": _number(phase["breakout_rr_bonus"], "m67.phase5.breakout_rr_bonus", minimum=0.0),
        "min_shares": _number(phase["min_shares"], "m67.phase5.min_shares", minimum=1, integer=True),
        "min_amount": _number(phase["min_amount"], "m67.phase5.min_amount", minimum=0.0),
        "impact_cost_frac": _number(phase["impact_cost_frac"], "m67.phase5.impact_cost_frac", minimum=0.0, maximum=1.0),
    }
    if out_phase["iv_halve_pct"] >= out_phase["iv_nobuild_pct"]:
        raise RuntimeConfigError("m67.phase5 requires iv_halve_pct < iv_nobuild_pct")
    if out_phase["iv_hv_ratio_lo"] > out_phase["iv_hv_ratio_hi"]:
        raise RuntimeConfigError("m67.phase5 requires iv_hv_ratio_lo <= iv_hv_ratio_hi")
    portfolio = _exact_mapping(payload["portfolio_risk"], _PORTFOLIO_KEYS, "m67.portfolio_risk")
    out_portfolio = {
        key: _number(portfolio[key], f"m67.portfolio_risk.{key}", minimum=0.0,
                     maximum=100.0 if key.endswith("_pct") else None)
        for key in _PORTFOLIO_KEYS
    }
    out_portfolio["small_float_mv_rmb"] = _number(portfolio["small_float_mv_rmb"], "m67.portfolio_risk.small_float_mv_rmb", minimum=0.0)
    out_portfolio["high_risk_holding_cap_multiplier"] = _number(
        portfolio["high_risk_holding_cap_multiplier"],
        "m67.portfolio_risk.high_risk_holding_cap_multiplier", minimum=0.0, maximum=1.0)
    windows = _exact_mapping(payload["weekly_windows"], _WEEKLY_WINDOW_KEYS, "m67.weekly_windows")
    out_windows = {key: _number(windows[key], f"m67.weekly_windows.{key}", minimum=1, integer=True)
                   for key in _WEEKLY_WINDOW_KEYS}
    return {"phase5": out_phase, "portfolio_risk": out_portfolio,
            "weekly_windows": out_windows}


def _route(root: Path, section_name: str, expected_schema_ref: str) -> tuple[Path, dict]:
    preset = root / PRESET_RELATIVE_PATH
    route = _read_flat_preset_section(preset, section_name)
    _exact_mapping(route, ("schema_ref", "artifact_ref", "status"), f"preset.{section_name}")
    if route["schema_ref"] != expected_schema_ref:
        raise RuntimeConfigError(f"preset.{section_name}.schema_ref is not the reviewed schema")
    if route["status"] != "runtime_json_authority":
        raise RuntimeConfigError(f"preset.{section_name} is not an active runtime JSON authority")
    return _repo_path(root, route["artifact_ref"], f"preset.{section_name}.artifact_ref"), route


def load_runtime_configuration(*, root: Path | str | None = None) -> dict:
    """Load the two reviewed policies. ``root`` exists only for hermetic tests."""
    root_path = Path(root).resolve() if root is not None else ROOT
    screening_path, _ = _route(root_path, "screening_threshold_governance",
                                "schemas/a_short_screening_threshold_governance.schema.json")
    m67_path, _ = _route(root_path, "m67_runtime_policy",
                          "schemas/a_short_m67_runtime_policy.schema.json")
    screening_payload, screening_sha = _load_json_policy(
        screening_path, "a_short_screening_runtime_policy", "2.0.0")
    m67_payload, m67_sha = _load_json_policy(m67_path, "a_short_m67_runtime_policy", "1.0.0")
    policies = [
        {"policy_id": screening_payload["policy_id"], "schema_name": screening_payload["schema_name"],
         "schema_version": screening_payload["schema_version"],
         "path": screening_path.relative_to(root_path).as_posix(), "sha256": screening_sha},
        {"policy_id": m67_payload["policy_id"], "schema_name": m67_payload["schema_name"],
         "schema_version": m67_payload["schema_version"],
         "path": m67_path.relative_to(root_path).as_posix(), "sha256": m67_sha},
    ]
    return {
        "screening": _validate_screening(screening_payload),
        "m67": _validate_m67(m67_payload),
        "lineage": {
            "schema_name": "a_short_runtime_configuration",
            "schema_version": "1.0.0",
            "configuration_fingerprint": _canonical_sha256(policies),
            "policies": policies,
        },
    }


def runtime_configuration_lineage(configuration: dict | None = None) -> dict:
    configuration = configuration if configuration is not None else load_runtime_configuration()
    lineage = configuration.get("lineage") if isinstance(configuration, dict) else None
    if not isinstance(lineage, dict):
        raise RuntimeConfigError("runtime configuration lineage missing")
    return copy.deepcopy(lineage)


def validate_runtime_configuration_lineage(lineage: object) -> None:
    if not isinstance(lineage, dict):
        raise RuntimeConfigError("runtime configuration lineage must be an object")
    expected = runtime_configuration_lineage()
    if lineage != expected:
        raise RuntimeConfigError("runtime configuration lineage does not match the active reviewed JSON policies")
