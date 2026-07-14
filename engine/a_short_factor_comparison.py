"""A-short D1/D3 single-factor comparison track (comparison-only).

This module freezes a weekly baseline and four one-factor heads under the private
``state/a_short/factor_comparison_private`` root.  It never changes EGS, M6.7,
portfolio sizing, or any production policy.  A week becomes evidence only after
its frozen T+1 forward outcome settles from an already available price cache.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import random
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GOVERNANCE_PATH = ROOT / "presets" / "a_short_factor_comparison_governance_20260714.json"
GOVERNANCE_SCHEMA_PATH = ROOT / "schemas" / "a_short_factor_comparison_governance.schema.json"
WEEKLY_SCHEMA_PATH = ROOT / "schemas" / "a_short_factor_comparison_weekly.schema.json"
DEFAULT_PRIVATE_ROOT = ROOT / "state" / "a_short" / "factor_comparison_private"

SCHEMA_NAME = "a_short_factor_comparison_weekly"
SCHEMA_VERSION = "1.0.0"
BASELINE_ID = "v14_2_frozen"
FACTOR_IDS = ("entry_ma_pullback", "entry_range_pullback", "iv_step_down", "iv_joint_stress")
HORIZONS = (5, 10, 20)
TERMINAL_ENTRY_STATUSES = {"ok", "unfilled_entry_range", "unfilled_limit_up"}


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _finite(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _date(value) -> str:
    text = str(value)
    if len(text) != 8 or not text.isascii() or not text.isdigit():
        raise ValueError(f"comparison decision_date must be canonical YYYYMMDD, got {value!r}")
    datetime.strptime(text, "%Y%m%d")
    return text


def _private_root(root: str | Path) -> Path:
    path = Path(root).resolve()
    parts = [part.lower() for part in path.parts]
    joined = "/".join(parts)
    if "/result/a_short" in joined or "/research/results/a_short" in joined:
        raise ValueError(f"comparison output must not use a production/research result root: {path}")
    expected = ["state", "a_short", "factor_comparison_private"]
    if parts[-3:] != expected:
        raise ValueError("comparison output must end in state/a_short/factor_comparison_private")
    return path


def _atomic_write(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_governance(path: str | Path = GOVERNANCE_PATH) -> dict:
    governance = _load_json(Path(path))
    validate_governance(governance)
    return governance


def validate_governance(governance: dict) -> None:
    import jsonschema

    schema = _load_json(GOVERNANCE_SCHEMA_PATH)
    jsonschema.validate(governance, schema)
    ids = [row["factor_id"] for row in governance["factor_registry"]]
    if tuple(ids) != FACTOR_IDS or len(set(ids)) != len(ids):
        raise ValueError("factor registry must contain the four frozen D1/D3 factor ids once each")
    if governance["selection"]["slots"] < 1:
        raise ValueError("comparison selection slots must be positive")
    if governance["outcome_basis"]["horizons_trading_days"] != list(HORIZONS):
        raise ValueError("comparison outcome horizons drifted")


def _safe_candidate(candidate: dict) -> dict:
    """Keep the exact decision inputs needed by D1/D3; omit account/semantic private material."""
    series = []
    for row in candidate.get("price_series") or []:
        if not isinstance(row, dict) or not all(_finite(row.get(k)) for k in ("high", "low", "close")):
            raise ValueError(f"candidate {candidate.get('ts_code')}: invalid price_series row")
        clean = {"high": float(row["high"]), "low": float(row["low"]), "close": float(row["close"])}
        if row.get("trade_date") is not None:
            clean["trade_date"] = _date(row["trade_date"])
        series.append(clean)
    code = str(candidate.get("ts_code") or "")
    if not code or not _finite(candidate.get("close")):
        raise ValueError("comparison candidate requires ts_code and finite close")
    if len(series) < 20:
        raise ValueError(f"candidate {code}: price_series has fewer than 20 bars")
    keep = ("name", "esp_score", "l4_score", "egs_score", "overlay", "industry_trend", "derived",
            "event", "liquidity", "iv", "market_regime", "regime_fallback", "stateful_risk")
    out = {key: copy.deepcopy(candidate.get(key)) for key in keep}
    out.update({"ts_code": code, "close": float(candidate["close"]), "price_series": series})
    return out


def _factor_map(governance: dict) -> dict:
    return {row["factor_id"]: row for row in governance["factor_registry"]}


def unavailable_realized_regime(governance: dict, reason: str) -> dict:
    """Fail closed for the experimental context without blocking the official weekly run."""
    params = governance["realized_regime"]
    return {
        "status": "unavailable",
        "label": "unavailable",
        "reason": str(reason),
        "index_ts_code": params["index_ts_code"],
        "source_as_of": None,
        "trend_20d_pct": None,
        "realized_vol_annualized_pct": None,
        "source_digest": None,
    }


def build_realized_regime(index_rows: list[dict], *, decision_date: str, governance: dict) -> dict:
    """Freeze a comparison-only CSI300 trend/realized-volatility label from PIT rows.

    This context never changes the production regime.  It is deliberately unavailable rather
    than guessed when its market slice is incomplete or stale.
    """
    params = governance["realized_regime"]
    decision_date = _date(decision_date)
    by_date = {}
    for row in index_rows:
        if not isinstance(row, dict):
            raise ValueError("realized-regime index rows must be objects")
        trade_date = _date(row.get("trade_date"))
        close = row.get("close")
        if not _finite(close) or float(close) <= 0:
            raise ValueError("realized-regime index rows require positive finite close")
        if trade_date > decision_date:
            raise ValueError("realized-regime index row is after decision_date")
        if trade_date in by_date and by_date[trade_date] != float(close):
            raise ValueError("realized-regime index rows have conflicting duplicate trade_date")
        by_date[trade_date] = float(close)
    rows = [{"trade_date": date, "close": by_date[date]} for date in sorted(by_date)]
    if len(rows) < int(params["min_history_bars"]):
        return unavailable_realized_regime(governance, "insufficient_index_history")
    latest = rows[-1]["trade_date"]
    age = (datetime.strptime(decision_date, "%Y%m%d") -
           datetime.strptime(latest, "%Y%m%d")).days
    if age < 0 or age > int(params["max_staleness_calendar_days"]):
        return unavailable_realized_regime(governance, "index_history_stale")
    window = rows[-int(params["min_history_bars"]):]
    closes = [row["close"] for row in window]
    trend = (closes[-1] / closes[0] - 1.0) * 100.0
    daily = [math.log(closes[i] / closes[i - 1]) for i in range(1, len(closes))]
    if len(daily) < 2:
        return unavailable_realized_regime(governance, "insufficient_index_returns")
    mean_daily = sum(daily) / len(daily)
    variance = sum((value - mean_daily) ** 2 for value in daily) / (len(daily) - 1)
    realized_vol = math.sqrt(variance) * math.sqrt(252.0) * 100.0
    trend_label = ("trend_up" if trend >= float(params["trend_up_min_pct"]) else
                   "trend_down" if trend <= float(params["trend_down_max_pct"]) else "trend_flat")
    vol_label = "vol_high" if realized_vol >= float(params["high_realized_vol_annualized_pct"]) else "vol_low"
    return {
        "status": "available",
        "label": f"{trend_label}_{vol_label}",
        "reason": "csi300_20d_realized_context",
        "index_ts_code": params["index_ts_code"],
        "source_as_of": latest,
        "trend_20d_pct": round(trend, 8),
        "realized_vol_annualized_pct": round(realized_vol, 8),
        "source_digest": _digest(window),
    }


def _validate_realized_regime(context: dict, governance: dict, decision_date: str) -> dict:
    if not isinstance(context, dict):
        raise ValueError("comparison realized regime must be an object")
    required = {"status", "label", "reason", "index_ts_code", "source_as_of", "trend_20d_pct",
                "realized_vol_annualized_pct", "source_digest"}
    if set(context) != required:
        raise ValueError("comparison realized regime keys drifted")
    if context["index_ts_code"] != governance["realized_regime"]["index_ts_code"]:
        raise ValueError("comparison realized regime index drifted")
    if context["status"] == "unavailable":
        if context["label"] != "unavailable":
            raise ValueError("unavailable comparison regime must use unavailable label")
        if any(context[key] is not None for key in ("source_as_of", "trend_20d_pct",
                                                     "realized_vol_annualized_pct", "source_digest")):
            raise ValueError("unavailable comparison regime must not carry a partial market state")
        return copy.deepcopy(context)
    if context["status"] != "available":
        raise ValueError("comparison realized regime status is invalid")
    if context["label"] not in {
        "trend_up_vol_low", "trend_up_vol_high", "trend_flat_vol_low", "trend_flat_vol_high",
        "trend_down_vol_low", "trend_down_vol_high",
    }:
        raise ValueError("comparison realized regime label is invalid")
    source_as_of = _date(context["source_as_of"])
    if source_as_of > decision_date:
        raise ValueError("comparison realized regime source is after decision_date")
    age = (datetime.strptime(decision_date, "%Y%m%d") - datetime.strptime(source_as_of, "%Y%m%d")).days
    if age > int(governance["realized_regime"]["max_staleness_calendar_days"]):
        raise ValueError("comparison realized regime source is stale")
    if not (_finite(context["trend_20d_pct"]) and _finite(context["realized_vol_annualized_pct"])):
        raise ValueError("available comparison realized regime requires finite metrics")
    digest = str(context["source_digest"] or "")
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("available comparison realized regime requires source digest")
    return copy.deepcopy(context)


def _is_existing_holding(candidate: dict) -> bool:
    return ((candidate.get("stateful_risk") or {}).get("position_state") == "held")


def _entry_for_factor(candidate: dict, indicators: dict, factor_id: str, factor: dict) -> tuple[str, str]:
    from runners.a_short_phase5_engine import entry_type

    baseline_type, baseline_reason = entry_type(candidate, indicators)
    if factor_id not in ("entry_ma_pullback", "entry_range_pullback"):
        return baseline_type, baseline_reason
    if baseline_type == "突破":
        return baseline_type, "frozen_breakout_rule"
    close = candidate["close"]
    ma5, ma10, ma20 = indicators.get("ma5"), indicators.get("ma10"), indicators.get("ma20")
    if all(_finite(value) for value in (ma5, ma10, ma20)) and close < ma5 and close < ma10 and close < ma20:
        return "观察", "downtrend_guard"
    params = factor["parameters"]
    if factor_id == "entry_ma_pullback":
        if not all(_finite(value) and float(value) > 0 for value in (ma10, ma20)):
            return "观察", "ma_anchor_missing"
        if bool(params["require_ma10_ge_ma20"]) and ma10 < ma20:
            return "观察", "ma_trend_guard"
        if close < ma20 * float(params["ma20_nonbreak_ratio"]):
            return "观察", "ma20_nonbreak_guard"
        band = float(params["ma_anchor_band_pct"])
        if any(abs(close - anchor) / anchor <= band for anchor in (ma10, ma20)):
            return "低吸", "ma_pullback"
        return "观察", "outside_ma_anchor_band"
    low, high = indicators.get("recent_low_20"), indicators.get("recent_high_20")
    if not all(_finite(value) for value in (low, high, ma20)) or high <= low:
        return "观察", "range_anchor_missing"
    if close < ma20 * float(params["ma20_nonbreak_ratio"]):
        return "观察", "ma20_nonbreak_guard"
    fraction = (close - low) / (high - low)
    if fraction <= float(params["lower_range_fraction"]):
        return "低吸", "range_pullback"
    return "观察", "outside_lower_range"


def _iv_policy(candidate: dict, factor_id: str, factor: dict, realized_regime: dict) -> dict:
    """Return only the D3 override.  A contraction hard gate is never relaxed."""
    iv = ((candidate.get("iv") or {}).get("iv_percentile_252d"))
    regime = str(candidate.get("market_regime") or "")
    if not _finite(iv):
        return {"relax_iv_hard": False, "extra_halve": True, "size_multiplier": 1.0,
                "reason": "iv_missing_conservative"}
    iv = float(iv)
    if factor_id not in ("iv_step_down", "iv_joint_stress"):
        return {"relax_iv_hard": False, "extra_halve": 80.0 < iv <= 90.0, "size_multiplier": 1.0,
                "reason": "baseline_iv_rule"}
    parameters = factor["parameters"]
    if factor_id == "iv_step_down":
        threshold = float(parameters["further_reduce_above_percentile"])
        if iv > threshold and regime != "收缩期":
            return {"relax_iv_hard": True, "extra_halve": True,
                    "size_multiplier": float(parameters["further_reduce_size_multiplier"]),
                    "reason": "iv_step_down_above_90"}
        return {"relax_iv_hard": False, "extra_halve": iv > float(parameters["halve_above_percentile"]),
                "size_multiplier": 1.0, "reason": "iv_step_down_baseline_gate"}
    ratio = None
    iv_value = (candidate.get("iv") or {}).get("iv_value")
    hv_value = (candidate.get("iv") or {}).get("hv_value")
    if _finite(iv_value) and _finite(hv_value) and float(hv_value) > 0:
        ratio = float(iv_value) / float(hv_value)
    if realized_regime["status"] != "available":
        return {"relax_iv_hard": False, "extra_halve": iv > float(parameters["halve_above_percentile"]),
                "size_multiplier": 1.0, "reason": "iv_joint_context_unavailable", "iv_hv_ratio": ratio}
    stress = (ratio is not None and ratio >= float(parameters["iv_hv_ratio_stress_min"])) or \
        realized_regime["label"] in set(parameters["comparison_regime_stress_labels"])
    if iv > float(parameters["iv_percentile_threshold"]) and not stress and regime != "收缩期":
        return {"relax_iv_hard": True, "extra_halve": True,
                "size_multiplier": float(parameters["non_stress_size_multiplier"]),
                "reason": "iv_joint_nonstress", "iv_hv_ratio": ratio}
    return {"relax_iv_hard": False, "extra_halve": 80.0 < iv <= 90.0,
            "size_multiplier": 1.0, "reason": "iv_joint_stress_or_baseline", "iv_hv_ratio": ratio}


def _hard_reasons(families: dict, relax_iv_hard: bool) -> list[str]:
    hard = []
    for family, detail in families.items():
        if detail.get("action") != "hard_veto":
            continue
        for reason in (detail.get("reasons") or []):
            reason = str(reason)
            # D3 may compare a lower IV>90 threshold only.  It must never
            # relax the independent contraction no-new-entry hard gate.
            if family == "market_regime" and relax_iv_hard and "IV分位" in reason and "不可建仓" in reason:
                continue
            hard.append(reason)
    return hard


def _candidate_decision(candidate: dict, factor_id: str, factor: dict | None, governance: dict,
                        realized_regime: dict) -> dict:
    from runners.a_short_phase5_engine import classify_risk_families, compute_indicators, exit_and_size

    if _is_existing_holding(candidate):
        return {"ts_code": candidate["ts_code"], "status": "out_of_scope_existing_holding", "selected": False,
                "score": candidate.get("egs_score"), "reason": "comparison_new_entries_only", "plan": None}
    indicators = compute_indicators(candidate["price_series"])
    families = classify_risk_families(candidate, indicators)
    iv = _iv_policy(candidate, factor_id, factor or {"parameters": {} }, realized_regime)
    hard = _hard_reasons(families, bool(iv["relax_iv_hard"]))
    if hard:
        return {"ts_code": candidate["ts_code"], "status": "hard_veto", "selected": False,
                "score": candidate.get("egs_score"), "reason": "|".join(hard), "plan": None}
    entry_type, entry_reason = _entry_for_factor(candidate, indicators, factor_id, factor or {"parameters": {}})
    if entry_type == "观察":
        return {"ts_code": candidate["ts_code"], "status": "observe", "selected": False,
                "score": candidate.get("egs_score"), "reason": entry_reason, "plan": None}
    virtual = copy.deepcopy(candidate)
    cash = float(governance["selection"]["virtual_account_available_cash"])
    virtual["account"] = {"available_cash": cash, "bucket_capital": cash, "new_exposure_capacity": cash}
    plan, rejected = exit_and_size(virtual, indicators, str(candidate.get("market_regime") or "震荡期"), entry_type,
                                   extra_halve=bool(iv["extra_halve"]), halve_reason=str(iv["reason"]),
                                   size_multiplier=float(iv["size_multiplier"]),
                                   size_multiplier_reason=str(iv["reason"]))
    if plan is None:
        return {"ts_code": candidate["ts_code"], "status": "observe", "selected": False,
                "score": candidate.get("egs_score"), "reason": str(rejected), "plan": None}
    return {"ts_code": candidate["ts_code"], "status": "eligible", "selected": False,
            "score": candidate.get("egs_score"), "reason": entry_reason, "plan": plan,
            "iv_policy": iv}


def _score_key(decision: dict) -> tuple:
    score = decision.get("score")
    return (-(float(score) if _finite(score) else float("-inf")), str(decision["ts_code"]))


def _policy_result(candidates: list[dict], factor_id: str, factor: dict | None, governance: dict,
                   decision_date: str, forward_eligible: bool, universe_digest: str,
                   realized_regime: dict) -> dict:
    decisions = [_candidate_decision(candidate, factor_id, factor, governance, realized_regime)
                 for candidate in candidates]
    eligible = sorted((row for row in decisions if row["status"] == "eligible"), key=_score_key)
    chosen = eligible[:int(governance["selection"]["slots"])]
    chosen_codes = {row["ts_code"] for row in chosen}
    for row in decisions:
        row["selected"] = row["ts_code"] in chosen_codes
    selected = [row["ts_code"] for row in chosen]
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "decision_date": decision_date,
        "policy_id": BASELINE_ID if factor_id == "baseline" else factor_id,
        "baseline_policy_id": BASELINE_ID,
        "factor_id": factor_id,
        "forward_eligible": bool(forward_eligible),
        "candidate_universe_digest": universe_digest,
        "selection": {
            "slots": int(governance["selection"]["slots"]),
            "eligible_symbols": [row["ts_code"] for row in eligible],
            "selected_symbols": selected,
            "decisions": decisions,
        },
        "outcome": {
            "status": "pending_forward" if forward_eligible else "historical_not_counted",
            "basis": copy.deepcopy(governance["outcome_basis"]),
            "horizons": {f"h{h}": {"status": "pending"} for h in HORIZONS},
            "selected_positions": [],
        },
        "boundary": copy.deepcopy(governance["boundary"]),
    }


def validate_weekly_record(record: dict) -> None:
    import jsonschema

    jsonschema.validate(record, _load_json(WEEKLY_SCHEMA_PATH))
    if len(record["selection"]["selected_symbols"]) > record["selection"]["slots"]:
        raise ValueError("selection exceeds frozen slots")
    if not set(record["selection"]["selected_symbols"]).issubset(set(record["selection"]["eligible_symbols"])):
        raise ValueError("selected symbols must be eligible")
    if any(record["boundary"].values()):
        raise ValueError("comparison record boundary drifted into production")


def capture_week(*, root: str | Path, decision_date: str, candidates: list[dict], run_identity: dict,
                 forward_eligible: bool, governance: dict | None = None,
                 realized_regime: dict | None = None) -> dict:
    """Freeze baseline plus each D1/D3 head.  Same-day replay is idempotent only for identical inputs."""
    root = _private_root(root)
    decision_date = _date(decision_date)
    governance = governance or load_governance()
    validate_governance(governance)
    realized_regime = _validate_realized_regime(
        realized_regime if realized_regime is not None else unavailable_realized_regime(governance, "not_supplied"),
        governance, decision_date,
    )
    sanitized = [_safe_candidate(candidate) for candidate in candidates]
    codes = [candidate["ts_code"] for candidate in sanitized]
    if len(codes) != len(set(codes)):
        raise ValueError("comparison candidate universe has duplicate ts_code")
    if not sanitized:
        raise ValueError("comparison candidate universe is empty")
    regimes = {str(candidate.get("market_regime") or "") for candidate in sanitized}
    if len(regimes) != 1:
        raise ValueError("comparison candidates must share one effective market regime")
    universe_digest = _digest(sanitized)
    governance_digest = _digest(governance)
    day = root / decision_date
    manifest = {
        "schema_name": "a_short_factor_comparison_manifest",
        "schema_version": "1.0.0",
        "decision_date": decision_date,
        "lane": "a_short",
        "forward_eligible": bool(forward_eligible),
        "run_identity": {"run_id": str(run_identity.get("run_id") or ""),
                         "candidate_digest": str(run_identity.get("candidate_digest") or "")},
        "candidate_universe_digest": universe_digest,
        "governance_digest": governance_digest,
        "production_effective_regime": next(iter(regimes)),
        "comparison_realized_regime": realized_regime,
        "baseline_policy_id": BASELINE_ID,
        "factor_ids": list(FACTOR_IDS),
        "boundary": copy.deepcopy(governance["boundary"]),
    }
    manifest_path = day / "manifest.json"
    if manifest_path.exists():
        existing = _load_json(manifest_path)
        if existing != manifest:
            raise ValueError(f"{decision_date}: existing comparison snapshot has different frozen input")
        return {"status": "already_captured", "day": str(day), "manifest": existing}
    if day.exists() and any(day.iterdir()):
        raise ValueError(f"{decision_date}: partial comparison directory exists without manifest")
    baseline = _policy_result(sanitized, "baseline", None, governance, decision_date, forward_eligible,
                              universe_digest, realized_regime)
    factors = {factor_id: _policy_result(sanitized, factor_id, _factor_map(governance)[factor_id], governance,
                                         decision_date, forward_eligible, universe_digest, realized_regime)
               for factor_id in FACTOR_IDS}
    for record in [baseline, *factors.values()]:
        validate_weekly_record(record)
    summary = {
        "schema_name": "a_short_factor_comparison_weekly_summary",
        "schema_version": "1.0.0",
        "decision_date": decision_date,
        "forward_eligible": bool(forward_eligible),
        "comparison_realized_regime": realized_regime,
        "baseline_selected_symbols": baseline["selection"]["selected_symbols"],
        "factor_summaries": {
            factor_id: {
                "selected_symbols": record["selection"]["selected_symbols"],
                "selection_diverged": record["selection"]["selected_symbols"] != baseline["selection"]["selected_symbols"],
                "outcome_status": record["outcome"]["status"],
            }
            for factor_id, record in factors.items()
        },
        "boundary": copy.deepcopy(governance["boundary"]),
    }
    _atomic_write(manifest_path, manifest)
    _atomic_write(day / "baseline_result.json", baseline)
    for factor_id, record in factors.items():
        _atomic_write(day / f"factor_{factor_id}.json", record)
    _atomic_write(day / "weekly_summary.json", summary)
    return {"status": "captured", "day": str(day), "manifest": manifest, "summary": summary}


def _price_lookup(daily_payload: dict):
    import pandas as pd

    stocks = daily_payload.get("stocks")
    if not isinstance(stocks, pd.DataFrame) or stocks.empty:
        return [], {}
    required = {"ts_code", "trade_date", "open", "close", "adj_factor"}
    if not required.issubset(stocks.columns):
        raise ValueError(f"forward price cache missing columns {sorted(required - set(stocks.columns))}")
    rows = stocks.copy()
    rows["trade_date"] = rows["trade_date"].astype(str)
    dates = sorted(set(rows["trade_date"].tolist()))
    lookup = {}
    for row in rows[["ts_code", "trade_date", "open", "close", "adj_factor"]].itertuples(index=False):
        lookup[(str(row.ts_code), str(row.trade_date))] = (row.open, row.close, row.adj_factor)
    return dates, lookup


def _settle_record(record: dict, daily_payload: dict) -> dict:
    """Settle one frozen selection using the shared T+1/qfq/cost convention, never a fresh fetch."""
    from runners.backtest_rank import attach_forward_returns
    import pandas as pd

    record = copy.deepcopy(record)
    dates, lookup = _price_lookup(daily_payload)
    date_pos = {date: idx for idx, date in enumerate(dates)}
    as_of = record["decision_date"]
    slots = record["selection"]["slots"]
    chosen = [row for row in record["selection"]["decisions"] if row.get("selected")]
    if as_of not in date_pos:
        return record
    samples = pd.DataFrame([{"trade_date": as_of, "ts_code": row["ts_code"], "name": row["ts_code"],
                             "board": "main", "close": None} for row in chosen])
    attached = attach_forward_returns(samples, list(HORIZONS), daily_payload) if not samples.empty else samples
    by_code = {str(row["ts_code"]): row for _, row in attached.iterrows()} if not attached.empty else {}
    positions = []
    horizon_values = {h: [] for h in HORIZONS}
    horizon_pending = {h: False for h in HORIZONS}
    for decision in chosen:
        code = decision["ts_code"]
        row = by_code.get(code)
        position = {"ts_code": code, "entry_status": "pending", "horizons": {}}
        for h in HORIZONS:
            key = f"ret_{h}d_status"
            status = str(row.get(key)) if row is not None else "pending_no_price_cache"
            result = {"status": status, "net_return_pct": None}
            if status == "ok":
                entry_date = str(row.get("entry_date"))
                base = lookup.get((code, as_of))
                entry = lookup.get((code, entry_date))
                plan = decision.get("plan") or {}
                entry_model = None
                if base and entry and _finite(base[1]) and float(base[1]) > 0 and _finite(entry[0]):
                    entry_model = float(plan.get("entry", 0.0)) * float(entry[0]) / float(base[1])
                if not _finite(entry_model) or entry_model < float(plan.get("entry_low", math.inf)) or \
                        entry_model > float(plan.get("entry_high", -math.inf)):
                    status = "unfilled_entry_range"
                    result = {"status": status, "net_return_pct": 0.0, "entry_model_price": entry_model}
                else:
                    result = {"status": "ok", "net_return_pct": float(row[f"ret_{h}d_t1_net"]),
                              "entry_model_price": entry_model, "entry_date": entry_date,
                              "exit_date": str(row.get(f"ret_{h}d_exit_date"))}
            elif status == "pending_no_entry_limit_up":
                status = "unfilled_limit_up"
                result = {"status": status, "net_return_pct": 0.0}
            position["horizons"][f"h{h}"] = result
            if status in TERMINAL_ENTRY_STATUSES:
                horizon_values[h].append(float(result["net_return_pct"]))
            else:
                horizon_pending[h] = True
        values = [position["horizons"][f"h{h}"]["status"] for h in HORIZONS]
        position["entry_status"] = "settled" if all(value in TERMINAL_ENTRY_STATUSES for value in values) else "pending"
        positions.append(position)
    horizons = {}
    for h in HORIZONS:
        key = f"h{h}"
        mature_without_selection = not chosen and date_pos[as_of] + h < len(dates)
        settled = (not horizon_pending[h] and len(horizon_values[h]) == len(chosen)) or mature_without_selection
        if not settled:
            horizons[key] = {"status": "pending"}
            continue
        values = horizon_values[h]
        net = (sum(values) / slots) if values else 0.0
        filled = [value for value in values if value != 0.0]
        horizons[key] = {
            "status": "settled",
            "evaluation_exit_date": dates[date_pos[as_of] + h],
            "net_return_pct": net,
            "win_rate": (sum(1 for value in filled if value > 0) / len(filled)) if filled else 0.0,
            "bad_name_rate": (sum(1 for value in filled if value <= -5.0) / len(filled)) if filled else 0.0,
            "cash_drag_pct": (slots - len(filled)) / slots * 100.0,
        }
    record["outcome"]["selected_positions"] = positions
    record["outcome"]["horizons"] = horizons
    record["outcome"]["status"] = "settled_h10" if horizons["h10"]["status"] == "settled" else "pending_forward"
    return record


def _maximum_drawdown(values: list[float]) -> float:
    nav, peak, maximum = 1.0, 1.0, 0.0
    for value in values:
        nav *= 1.0 + float(value) / 100.0
        peak = max(peak, nav)
        maximum = max(maximum, (peak - nav) / peak * 100.0)
    return maximum


def _binomial_tail(wins: int, n: int) -> float:
    if n <= 0:
        return 1.0
    return sum(math.comb(n, k) for k in range(wins, n + 1)) / (2 ** n)


def _sign_flip_two_sided_pvalue(values: list[float], draws: int) -> float | None:
    """Deterministic paired sign-flip test on the mean difference, exact through 16 blocks."""
    if not values:
        return None
    observed = abs(sum(values) / len(values))
    if not observed:
        return 1.0
    n = len(values)
    if n <= 16:
        total = 1 << n
        extreme = 0
        for mask in range(total):
            signed = sum(value if (mask >> index) & 1 else -value for index, value in enumerate(values)) / n
            extreme += abs(signed) >= observed - 1e-12
        return extreme / total
    seed = int(_digest({"kind": "sign_flip", "values": values, "draws": draws})[:16], 16)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(int(draws)):
        signed = sum(value if rng.getrandbits(1) else -value for value in values) / n
        extreme += abs(signed) >= observed - 1e-12
    return (extreme + 1) / (int(draws) + 1)


def _bootstrap_mean_ci(values: list[float], draws: int, confidence: float) -> tuple[float | None, float | None]:
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    seed = int(_digest({"kind": "bootstrap", "values": values, "draws": draws, "confidence": confidence})[:16], 16)
    rng = random.Random(seed)
    n = len(values)
    samples = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(int(draws)))
    tail = (1.0 - float(confidence)) / 2.0
    lower = samples[max(0, min(len(samples) - 1, math.floor(tail * len(samples))))]
    upper = samples[max(0, min(len(samples) - 1, math.ceil((1.0 - tail) * len(samples)) - 1))]
    return lower, upper


def _holm_bonferroni(pvalues: dict[str, float | None]) -> dict[str, float | None]:
    """Family-wise adjustment across all frozen heads, including heads without a usable test yet."""
    active = sorted((1.0 if value is None else float(value), factor_id) for factor_id, value in pvalues.items())
    out = {factor_id: None for factor_id in pvalues}
    running = 0.0
    total = len(active)
    for index, (pvalue, factor_id) in enumerate(active):
        adjusted = min(1.0, pvalue * (total - index))
        running = max(running, adjusted)
        if pvalues[factor_id] is not None:
            out[factor_id] = running
    return out


def _nonoverlap_blocks(rows: list[dict]) -> list[dict]:
    """Greedily retain h10 effects whose decision date starts after the prior h10 exit."""
    selected, previous_exit = [], None
    for row in sorted(rows, key=lambda item: item["decision_date"]):
        exit_date = row.get("evaluation_exit_date")
        if not exit_date:
            continue
        if previous_exit is None or row["decision_date"] > previous_exit:
            selected.append(row)
            previous_exit = exit_date
    return selected


def _power_required_blocks(values: list[float], effect_pct: float, alpha: float, target: float,
                           family_size: int) -> int | None:
    if len(values) < 2 or not effect_pct:
        return None
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    if variance <= 0:
        return 1
    from statistics import NormalDist
    normal = NormalDist()
    per_head_alpha = float(alpha) / max(1, int(family_size))
    z_alpha = normal.inv_cdf(1.0 - per_head_alpha / 2.0)
    z_power = normal.inv_cdf(float(target))
    return int(math.ceil(((z_alpha + z_power) * math.sqrt(variance) / abs(float(effect_pct))) ** 2))


def _user_decisions(root: Path) -> dict:
    path = root / "cumulative" / "user_decisions.json"
    if not path.exists():
        return {}
    payload = _load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("user_decisions.json must be an object keyed by factor_id")
    return payload


def _evaluate(root: Path, governance: dict) -> tuple[dict, dict]:
    effects = {factor_id: [] for factor_id in FACTOR_IDS}
    observed = {factor_id: 0 for factor_id in FACTOR_IDS}
    for day in sorted(path for path in root.iterdir() if path.is_dir() and path.name.isdigit()):
        base_path = day / "baseline_result.json"
        manifest_path = day / "manifest.json"
        if not base_path.exists() or not manifest_path.exists():
            continue
        manifest, baseline = _load_json(manifest_path), _load_json(base_path)
        if not manifest.get("forward_eligible") or baseline["outcome"]["horizons"]["h10"]["status"] != "settled":
            continue
        base_selected = baseline["selection"]["selected_symbols"]
        base_h = baseline["outcome"]["horizons"]["h10"]
        realized = manifest.get("comparison_realized_regime") or {}
        realized_label = realized.get("label") if realized.get("status") == "available" else None
        for factor_id in FACTOR_IDS:
            factor_path = day / f"factor_{factor_id}.json"
            if not factor_path.exists():
                continue
            factor = _load_json(factor_path)
            factor_h = factor["outcome"]["horizons"]["h10"]
            if factor_h["status"] != "settled":
                continue
            observed[factor_id] += 1
            if factor["selection"]["selected_symbols"] == base_selected:
                continue
            effects[factor_id].append({
                "decision_date": day.name,
                "comparison_realized_regime": realized_label,
                "evaluation_exit_date": max(str(base_h.get("evaluation_exit_date") or ""),
                                            str(factor_h.get("evaluation_exit_date") or "")) or None,
                "paired_net_excess_pct": float(factor_h["net_return_pct"]) - float(base_h["net_return_pct"]),
                "factor_net_return_pct": float(factor_h["net_return_pct"]),
                "baseline_net_return_pct": float(base_h["net_return_pct"]),
                "factor_bad_name_rate": float(factor_h["bad_name_rate"]),
                "baseline_bad_name_rate": float(base_h["bad_name_rate"]),
            })
    rule = governance["decision_rule"]
    metrics = {}
    raw_pvalues = {}
    for factor_id, rows in effects.items():
        blocks = _nonoverlap_blocks(rows)
        block_diffs = [row["paired_net_excess_pct"] for row in blocks]
        pvalue = _sign_flip_two_sided_pvalue(block_diffs, int(rule["permutation_draws"]))
        raw_pvalues[factor_id] = pvalue
        ci_low, ci_high = _bootstrap_mean_ci(block_diffs, int(rule["bootstrap_draws"]),
                                              float(rule["confidence_level"]))
        block_mean = sum(block_diffs) / len(block_diffs) if block_diffs else None
        metrics[factor_id] = {
            "rows": rows,
            "blocks": blocks,
            "block_diffs": block_diffs,
            "pvalue": pvalue,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "block_mean": block_mean,
        }
    adjusted_pvalues = _holm_bonferroni(raw_pvalues)
    verdicts = {}
    for factor_id, item in metrics.items():
        rows = item["rows"]
        n = len(rows)
        diffs = [row["paired_net_excess_pct"] for row in rows]
        wins = sum(value > 0 for value in diffs)
        losses = sum(value < 0 for value in diffs)
        mean = sum(diffs) / n if n else None
        win_rate = wins / n if n else None
        regimes = sorted({str(row["comparison_realized_regime"]) for row in rows
                          if row.get("comparison_realized_regime")})
        blocks = item["blocks"]
        block_diffs = item["block_diffs"]
        block_n = len(block_diffs)
        block_wins = sum(value > 0 for value in block_diffs)
        block_win_rate = block_wins / block_n if block_n else None
        power_required = _power_required_blocks(
            block_diffs, float(rule["adopt_min_mean_paired_net_excess_pct"]),
            float(rule["adjusted_pvalue_max"]), float(rule["power_target"]), len(FACTOR_IDS))
        factor_mdd = _maximum_drawdown([row["factor_net_return_pct"] for row in rows]) if rows else None
        baseline_mdd = _maximum_drawdown([row["baseline_net_return_pct"] for row in rows]) if rows else None
        factor_bad = sum(row["factor_bad_name_rate"] for row in rows) / n if n else None
        baseline_bad = sum(row["baseline_bad_name_rate"] for row in rows) / n if n else None
        reliable_advantage = (block_n >= int(rule["min_nonoverlap_blocks_adopt"]) and
                              item["block_mean"] >= float(rule["adopt_min_mean_paired_net_excess_pct"]) and
                              block_win_rate >= float(rule["adopt_min_win_rate"]) and
                              item["ci_low"] is not None and item["ci_low"] > 0.0 and
                              adjusted_pvalues[factor_id] is not None and
                              adjusted_pvalues[factor_id] <= float(rule["adjusted_pvalue_max"]))
        reliable_harm = (block_n >= int(rule["min_nonoverlap_blocks_adopt"]) and
                         item["block_mean"] <= -float(rule["adopt_min_mean_paired_net_excess_pct"]) and
                         block_win_rate is not None and (1.0 - block_win_rate) >= float(rule["adopt_min_win_rate"]) and
                         item["ci_high"] is not None and item["ci_high"] < 0.0 and
                         adjusted_pvalues[factor_id] is not None and
                         adjusted_pvalues[factor_id] <= float(rule["adjusted_pvalue_max"]))
        if n < int(rule["min_effective_weeks_provisional"]):
            status = "accumulating"
        elif n < int(rule["min_effective_weeks_adopt"]):
            status = "provisional_review_due"
        elif block_n < int(rule["min_nonoverlap_blocks_adopt"]):
            status = "inconclusive" if n >= int(rule["retire_after_effective_weeks"]) else "provisional_review_due"
        else:
            adopt = (reliable_advantage and
                     len(regimes) >= int(rule["min_comparison_regimes_adopt"]) and
                     factor_mdd <= baseline_mdd + float(rule["max_drawdown_worsening_pct"]) and
                     factor_bad <= baseline_bad + float(rule["max_bad_name_rate_worsening_pct"]))
            if adopt:
                status = "recommend_adopt_change"
            elif reliable_harm and n >= int(rule["retire_after_effective_weeks"]):
                status = "recommend_retire_head"
            elif reliable_harm:
                status = "recommend_keep_baseline"
            else:
                status = "inconclusive"
        verdicts[factor_id] = {
            "factor_id": factor_id,
            "status": status,
            "effective_difference_weeks": n,
            "settled_observation_weeks": observed[factor_id],
            "selection_divergence_frequency": n / observed[factor_id] if observed[factor_id] else None,
            "comparison_realized_regimes": regimes,
            "mean_paired_net_excess_pct": mean,
            "paired_week_win_rate": win_rate,
            "nonoverlap_blocks": block_n,
            "nonoverlap_mean_paired_net_excess_pct": item["block_mean"],
            "nonoverlap_block_win_rate": block_win_rate,
            "paired_bootstrap_ci": {"confidence_level": rule["confidence_level"],
                                    "lower_pct": item["ci_low"], "upper_pct": item["ci_high"]},
            "paired_sign_flip_two_sided_pvalue": item["pvalue"],
            "holm_bonferroni_adjusted_pvalue": adjusted_pvalues[factor_id],
            "sign_test_one_sided_pvalue": _binomial_tail(wins, n),
            "first_half_nonoverlap_mean_pct": (sum(block_diffs[:block_n // 2]) / (block_n // 2)
                                                if block_n >= 2 else None),
            "second_half_nonoverlap_mean_pct": (sum(block_diffs[block_n // 2:]) / (block_n - block_n // 2)
                                                 if block_n >= 2 else None),
            "power_estimated_required_blocks": power_required,
            "power_status": ("not_estimable" if power_required is None else
                             "adequately_powered_for_threshold" if block_n >= power_required else
                             "underpowered_for_threshold"),
            "factor_max_drawdown_pct": factor_mdd,
            "baseline_max_drawdown_pct": baseline_mdd,
            "factor_bad_name_rate": factor_bad,
            "baseline_bad_name_rate": baseline_bad,
            "automatic_production_switch": False,
        }
    decisions = _user_decisions(root)
    reminders = []
    recommendation_statuses = {"recommend_adopt_change", "recommend_keep_baseline", "recommend_retire_head"}
    for factor_id, verdict in verdicts.items():
        if verdict["status"] in recommendation_statuses and not decisions.get(factor_id):
            reminders.append({"factor_id": factor_id, "status": verdict["status"],
                              "message": "User decision required; production remains unchanged."})
    return ({"schema_name": "a_short_factor_comparison_verdicts", "schema_version": "1.0.0",
             "lane": "a_short", "verdicts": verdicts,
             "boundary": copy.deepcopy(governance["boundary"])},
            {"schema_name": "a_short_factor_comparison_reminder", "schema_version": "1.0.0",
             "lane": "a_short", "reminders": reminders,
             "production_unchanged": True})


def settle_from_daily_payload(*, root: str | Path, daily_payload: dict, governance: dict | None = None) -> dict:
    root = _private_root(root)
    governance = governance or load_governance()
    updated = []
    if not root.exists():
        return {"status": "no_comparison_root", "updated_dates": []}
    for day in sorted(path for path in root.iterdir() if path.is_dir() and path.name.isdigit()):
        baseline_path = day / "baseline_result.json"
        manifest_path = day / "manifest.json"
        if not baseline_path.exists() or not manifest_path.exists():
            continue
        baseline = _settle_record(_load_json(baseline_path), daily_payload)
        validate_weekly_record(baseline)
        _atomic_write(baseline_path, baseline)
        factor_records = {}
        for factor_id in FACTOR_IDS:
            path = day / f"factor_{factor_id}.json"
            if not path.exists():
                raise ValueError(f"{day.name}: missing factor file {factor_id}")
            record = _settle_record(_load_json(path), daily_payload)
            validate_weekly_record(record)
            _atomic_write(path, record)
            factor_records[factor_id] = record
        summary = _load_json(day / "weekly_summary.json")
        summary["baseline_selected_symbols"] = baseline["selection"]["selected_symbols"]
        for factor_id, record in factor_records.items():
            base_h, factor_h = baseline["outcome"]["horizons"]["h10"], record["outcome"]["horizons"]["h10"]
            pair = None
            if base_h["status"] == "settled" and factor_h["status"] == "settled":
                pair = float(factor_h["net_return_pct"]) - float(base_h["net_return_pct"])
            summary["factor_summaries"][factor_id].update({
                "outcome_status": record["outcome"]["status"],
                "paired_net_excess_h10_pct": pair,
            })
        _atomic_write(day / "weekly_summary.json", summary)
        updated.append(day.name)
    verdicts, reminder = _evaluate(root, governance)
    _atomic_write(root / "cumulative" / "factor_verdicts.json", verdicts)
    _atomic_write(root / "cumulative" / "reminder.json", reminder)
    return {"status": "settled_from_cache", "updated_dates": updated, "verdicts": verdicts, "reminder": reminder}
