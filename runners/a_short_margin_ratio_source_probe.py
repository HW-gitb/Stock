"""Bounded source probe: can we get a market-size denominator for the margin gate?

Queue row 19 wired a market-wide financing-overheat gate that ranks the raw
``rzye`` balance inside its own rolling three-year distribution.  The published
evidence showed that ranking is not measurable overheat: the balance drifts
upward with the market's own growth, so 53 of 53 evaluable weeks cleared p80
and 45 cleared p95.  Today's three-exchange total (~2.59e12 CNY) already
exceeds the 2015 bubble peak, not because leverage is more extreme but because
the tradeable float roughly doubled.  Ranking a non-stationary level measures
time, not temperature.

The fix is to rank a ratio -- financing balance over market float value -- which
is stationary enough for a percentile to mean something.  That needs a
denominator series, and nobody has checked whether this account can reach one.

This runner checks.  For three candidate breadth indices it reports whether
``index_dailybasic`` is reachable, which columns come back, whether
``float_mv`` is among them, what unit that column is published in, and how far
the history reaches.  It also asks ``pro.margin`` the same depth question, so
the decision to extend the numerator from three years to six is made on data
rather than on assumption.

Reaching a surface is evidence of availability only.  This probe authorizes no
wiring, computes no gate, proposes no threshold and touches no production
module.  Vendor rows stay under the gitignored ``provider_samples/`` root; the
tracked summary carries shapes, counts, public index identifiers and
market-level aggregates of the same class the row 19 artifact already
publishes -- never a per-stock row, a request URL or a credential.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from engine.a_short_tushare_client import init_tushare_pro


PROBE_DATE = "20260805"
CALL_BUDGET = 12
RAW_ROOT = Path(f"provider_samples/a_short_margin_ratio_source_probe_{PROBE_DATE}")
SUMMARY_PATH = Path(f"docs/a_short_margin_ratio_source_probe_summary_{PROBE_DATE}.json")

#: Three breadth candidates, widest first.  A percentile of a ratio is
#: invariant to a constant scale error in the denominator, so any index whose
#: float value tracks the market's growth works; what differs is how much of
#: the market each one tracks.
CANDIDATE_INDICES = (
    {"ts_code": "000985.CSI", "label": "中证全指", "breadth": "whole_a_share_market"},
    {"ts_code": "000300.SH", "label": "沪深300", "breadth": "large_cap_sse_szse"},
    {"ts_code": "000001.SH", "label": "上证综指", "breadth": "sse_only"},
)

#: Deliberately short windows.  A five-session request cannot be silently
#: truncated at a vendor row cap, so a short answer here means "no history",
#: never "the cap ate it" -- the failure mode that already bit row 22b and the
#: limit-up index probe.
PROBE_WINDOWS = (
    {"label": "recent", "start_date": "20260729", "end_date": "20260804"},
    {"label": "three_years_back", "start_date": "20230801", "end_date": "20230807"},
    {"label": "six_years_back", "start_date": "20200803", "end_date": "20200807"},
)

#: Any window returning at least this many rows is treated as possibly
#: truncated and reported as such.  The windows above are ~5 sessions, so this
#: can only fire if the vendor ignores the date range.
SUSPECT_ROW_COUNT = 300

MARGIN_EXCHANGES = ("SSE", "SZSE", "BSE")
FLOAT_MV_COLUMN = "float_mv"
TOTAL_MV_COLUMN = "total_mv"

#: A broad A-share float value is ~7e13 CNY.  The published unit decides which
#: exponent we should see, and the margin ratio below is the independent check
#: on that reading -- the 万元-vs-元 trap already cost this project one round.
_UNIT_BY_EXPONENT = {
    (12, 15): {"unit": "CNY", "scale_to_yuan": 1.0},
    (8, 11): {"unit": "10k CNY (万元)", "scale_to_yuan": 1e4},
    (4, 7): {"unit": "100m CNY (亿元)", "scale_to_yuan": 1e8},
}

#: Margin balance over market float value sits in this band in A-shares; 2015's
#: peak reached roughly 4.7%.  A reading far outside it means the unit above was
#: read wrong, which is exactly what this cross-check exists to catch.
PLAUSIBLE_RATIO_BAND = (0.005, 0.08)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str, allow_nan=False),
        encoding="utf-8",
    )


def _sanitize_nonfinite(value: Any) -> Any:
    """Map vendor NaN/Inf to null for the raw file only (see the limit-up probe)."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _sanitize_nonfinite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize_nonfinite(item) for item in value]
    return value


def _raw_json_value(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return {"kind": "dataframe",
                "rows": _sanitize_nonfinite(value.to_dict(orient="records"))}
    if isinstance(value, dict):
        return value
    return {"kind": type(value).__name__}


def _shape(value: Any) -> dict[str, Any]:
    """Columns, counts and per-column emptiness only."""
    if isinstance(value, pd.DataFrame):
        columns = [str(column) for column in value.columns]
        return {
            "kind": "dataframe",
            "row_count": int(len(value)),
            "columns": sorted(columns),
            "column_dtypes": {name: str(value[name].dtype) for name in columns},
            "all_null_columns": sorted(
                name for name in columns if bool(value[name].isna().all())
            ),
            "possibly_truncated": bool(len(value) >= SUSPECT_ROW_COUNT),
        }
    return {"kind": type(value).__name__, "row_count": 0 if value is None else 1,
            "columns": [], "column_dtypes": {}, "all_null_columns": [],
            "possibly_truncated": False}


def _error_category(exc: Exception) -> str:
    """Distinguishable failure classes; collapsing them would defeat the probe."""
    message = str(exc).casefold()
    if any(m in message for m in ("权限", "积分", "permission", "entitlement", "access denied")):
        return "permission_or_entitlement"
    if any(m in message for m in ("token", "auth", "认证", "鉴权")):
        return "authentication"
    if any(m in message for m in ("每分钟", "频率", "rate", "too many", "limit")):
        return "rate_limit"
    return "other"


def _finite(value: Any) -> bool:
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(float(value)))


def _latest_row_value(frame: Any, column: str) -> tuple[str | None, float | None]:
    """Return (trade_date, value) for the newest usable row, or (None, None)."""
    if not isinstance(frame, pd.DataFrame) or frame.empty or column not in frame.columns:
        return None, None
    if "trade_date" not in frame.columns:
        return None, None
    best_date: str | None = None
    best_value: float | None = None
    for row in frame.to_dict(orient="records"):
        trade_date = str(row.get("trade_date", "")).strip()
        value = row.get(column)
        if len(trade_date) != 8 or not trade_date.isdigit() or not _finite(value):
            continue
        if best_date is None or trade_date > best_date:
            best_date, best_value = trade_date, float(value)
    return best_date, best_value


def infer_unit(value: Any) -> dict[str, Any]:
    """Read the published unit off the magnitude, and say so explicitly.

    This is inference from order of magnitude, not a vendor documentation
    quote.  Reading the scale off the observed value is what makes the
    万元-vs-元 trap structurally impossible here: that trap is an *assumption*
    error, and nothing is assumed.

    What the ratio cross-check below can and cannot add is worth stating,
    because a check that looks stronger than it is would be worse than none.
    Each bucket converts to the same CNY value, so a denominator differing by
    exactly one unit step (1e4 / 1e8) lands in the adjacent bucket and the
    cross-check is blind to it -- correctly, since both readings are the same
    quantity.  What it does catch is a denominator that is wrong by a
    non-unit factor: an index far too narrow to stand in for market float
    value, or a magnitude matching no expected unit at all.
    """
    if not _finite(value) or float(value) <= 0:
        return {"unit": None, "scale_to_yuan": None, "exponent": None,
                "basis": "no finite positive value observed"}
    exponent = int(math.floor(math.log10(float(value))))
    for (low, high), resolved in _UNIT_BY_EXPONENT.items():
        if low <= exponent <= high:
            return dict(resolved, exponent=exponent,
                        basis="inferred from order of magnitude; confirm with the ratio cross-check")
    return {"unit": None, "scale_to_yuan": None, "exponent": exponent,
            "basis": "magnitude matches no expected unit"}


def margin_ratio_cross_check(margin_balance_yuan: Any, float_mv_raw: Any,
                             scale_to_yuan: Any) -> dict[str, Any]:
    """Recompute the financing ratio and judge whether the unit reading holds."""
    if not (_finite(margin_balance_yuan) and _finite(float_mv_raw)
            and _finite(scale_to_yuan) and float(float_mv_raw) > 0
            and float(scale_to_yuan) > 0):
        return {"ratio": None, "plausible": False,
                "reason": "missing a finite numerator, denominator or scale"}
    ratio = float(margin_balance_yuan) / (float(float_mv_raw) * float(scale_to_yuan))
    low, high = PLAUSIBLE_RATIO_BAND
    return {
        "ratio": ratio,
        "ratio_pct": ratio * 100.0,
        "plausible_band_pct": [low * 100.0, high * 100.0],
        "plausible": bool(low <= ratio <= high),
        "reason": ("financing balance over market float value lands in the band "
                   "A-shares have historically occupied"
                   if low <= ratio <= high else
                   "ratio is outside any band A-shares have occupied, so the unit "
                   "reading above is wrong or the index is far too narrow"),
    }


def run_probe(pro_client, *, raw_root: Path = RAW_ROOT) -> dict[str, Any]:
    """Answer three facts: denominator reachable, its unit, and history depth."""
    raw_root.mkdir(parents=True, exist_ok=True)
    calls: list[dict[str, Any]] = []
    used = 0

    def _call(label: str, endpoint: str, **parameters) -> Any:
        nonlocal used
        if used >= CALL_BUDGET:
            calls.append({"label": label, "endpoint": endpoint, "status": "skipped_budget"})
            return None
        used += 1
        try:
            frame = getattr(pro_client, endpoint)(**parameters)
        except Exception as exc:  # noqa: BLE001 - category is the probe's output
            calls.append({"label": label, "endpoint": endpoint, "status": "error",
                          "error_class": type(exc).__name__,
                          "error_category": _error_category(exc)})
            return None
        calls.append({"label": label, "endpoint": endpoint, "status": "ok",
                      "shape": _shape(frame)})
        _write_json(raw_root / f"{label}.json", _raw_json_value(frame))
        return frame

    index_results: dict[str, Any] = {}
    for index in CANDIDATE_INDICES:
        ts_code = index["ts_code"]
        windows: dict[str, Any] = {}
        for window in PROBE_WINDOWS:
            frame = _call(
                f"index_dailybasic_{ts_code.replace('.', '_')}_{window['label']}",
                "index_dailybasic", ts_code=ts_code,
                start_date=window["start_date"], end_date=window["end_date"],
            )
            trade_date, float_mv = _latest_row_value(frame, FLOAT_MV_COLUMN)
            shape = _shape(frame)
            windows[window["label"]] = {
                "requested": {"start_date": window["start_date"], "end_date": window["end_date"]},
                "row_count": shape["row_count"],
                "possibly_truncated": shape["possibly_truncated"],
                "has_float_mv": FLOAT_MV_COLUMN in shape["columns"],
                "has_total_mv": TOTAL_MV_COLUMN in shape["columns"],
                "latest_trade_date": trade_date,
                "latest_float_mv_raw": float_mv,
            }
        reachable_windows = [name for name, w in windows.items() if w["row_count"] > 0]
        recent = windows.get("recent") or {}
        index_results[ts_code] = {
            "label": index["label"],
            "breadth": index["breadth"],
            "reachable": bool(reachable_windows),
            "windows_with_rows": sorted(reachable_windows),
            "columns": next((c["shape"]["columns"] for c in calls
                             if c.get("status") == "ok"
                             and c["label"].startswith(f"index_dailybasic_{ts_code.replace('.', '_')}")), []),
            "float_mv_unit": infer_unit(recent.get("latest_float_mv_raw")),
            "windows": windows,
        }

    margin_recent = _call("margin_recent", "margin",
                          start_date=PROBE_WINDOWS[0]["start_date"],
                          end_date=PROBE_WINDOWS[0]["end_date"],
                          fields="trade_date,exchange_id,rzye")
    margin_six = _call("margin_six_years_back", "margin",
                       start_date=PROBE_WINDOWS[2]["start_date"],
                       end_date=PROBE_WINDOWS[2]["end_date"],
                       fields="trade_date,exchange_id,rzye")

    margin_balance = None
    margin_balance_date = None
    if isinstance(margin_recent, pd.DataFrame) and not margin_recent.empty:
        by_date: dict[str, dict[str, float]] = {}
        for row in margin_recent.to_dict(orient="records"):
            trade_date = str(row.get("trade_date", "")).strip()
            exchange = str(row.get("exchange_id", "")).strip().upper()
            value = row.get("rzye")
            if len(trade_date) == 8 and exchange in MARGIN_EXCHANGES and _finite(value):
                by_date.setdefault(trade_date, {})[exchange] = float(value)
        complete = {d: v for d, v in by_date.items() if set(v) == set(MARGIN_EXCHANGES)}
        if complete:
            margin_balance_date = max(complete)
            margin_balance = sum(complete[margin_balance_date].values())

    ranked = [
        (ts_code, result) for ts_code, result in index_results.items()
        if result["reachable"] and result["windows"]["recent"]["has_float_mv"]
    ]
    chosen_ts_code, chosen = (ranked[0] if ranked else (None, None))
    cross_check = margin_ratio_cross_check(
        margin_balance,
        (chosen or {}).get("windows", {}).get("recent", {}).get("latest_float_mv_raw"),
        ((chosen or {}).get("float_mv_unit") or {}).get("scale_to_yuan"),
    )

    margin_six_rows = _shape(margin_six)["row_count"]
    denominator_six_years = bool(
        chosen and "six_years_back" in chosen["windows_with_rows"]
    )

    if chosen is None:
        verdict = "no_reachable_float_mv_denominator"
    elif not cross_check["plausible"]:
        verdict = "denominator_reachable_but_unit_unresolved"
    elif denominator_six_years and margin_six_rows > 0:
        verdict = "denominator_and_six_year_history_available"
    else:
        verdict = "denominator_available_three_year_history_only"

    return {
        "schema_name": "a_short_margin_ratio_source_probe",
        "schema_version": "1.0.0",
        "probe_date": PROBE_DATE,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "purpose": (
            "establish whether a market float-value denominator is reachable, in "
            "which unit, and how deep both it and pro.margin go -- so row 19's "
            "quantity change and the three-vs-six-year fetch are decided on data"
        ),
        "call_budget": {"budget": CALL_BUDGET, "used": used},
        "indices": index_results,
        "recommended_denominator": chosen_ts_code,
        "recommended_denominator_breadth": (chosen or {}).get("breadth"),
        "margin_numerator": {
            "latest_complete_session": margin_balance_date,
            "three_exchange_rzye_yuan": margin_balance,
            "six_years_back_row_count": margin_six_rows,
            "six_years_back_reachable": bool(margin_six_rows > 0),
        },
        "margin_ratio_cross_check": cross_check,
        "denominator_six_years_reachable": denominator_six_years,
        "calls": calls,
        "raw_root": str(raw_root),
        "raw_root_is_gitignored": True,
        "verdict": verdict,
        "comparison_only": True,
        "production_effect_enabled": False,
        "NOT_VERIFIED": [
            "the vendor's documented unit for float_mv; this probe infers it from "
            "magnitude, which makes a 万元-vs-元 assumption error impossible but "
            "leaves the cross-check blind to a whole unit step -- it catches a "
            "denominator wrong by a non-unit factor, not by 1e4",
            "whether the ratio's percentile discriminates better than the raw "
            "level's -- that needs the full recomputation, not this probe",
            "any percentile threshold or cash factor; both remain user adjudications",
            "index rebalancing effects on the float-value series across years",
            "independent review of this probe",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-root", default=str(RAW_ROOT))
    parser.add_argument("--out", default=str(SUMMARY_PATH))
    parser.add_argument("--confirm-fetch-authorized", action="store_true", required=True)
    args = parser.parse_args(argv)

    token = os.environ.get("TUSHARE_TOKEN")
    if not token:
        raise RuntimeError("TUSHARE_TOKEN is required for the margin ratio source probe")
    summary = run_probe(init_tushare_pro(token), raw_root=Path(args.raw_root))
    _write_json(Path(args.out), summary)
    print(
        f"[margin-ratio-probe] verdict={summary['verdict']} "
        f"denominator={summary['recommended_denominator']} "
        f"ratio={summary['margin_ratio_cross_check'].get('ratio_pct')} "
        f"calls={summary['call_budget']['used']}/{summary['call_budget']['budget']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
