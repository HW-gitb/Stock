#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data_canary.py — Phase 2.6 旁路数据对账 (Tushare vs akshare)

每周选股完成后跑一次，对 Tier1 候选随机抽样，对比 close/name（默认）
或 close/pe/pb/name（east-money 源）在 Tushare（egs_main.py 已落盘）
和 akshare 之间是否一致。

数据源选择（--source）：
- sina（默认）：ak.stock_zh_a_spot()，只校 close + name，但稳定（不受用户
  本地 VPN 路由策略影响；东财 push 端点反爬 + VPN 错路由都会让 em 挂）
- em：ak.stock_zh_a_spot_em()，额外校 pe/pb；需用户本地能直连东财
  （本地若挂 VPN，必须把 *.eastmoney.com 加 split-tunnel 走直连）

强约束（违反则不应合入）：
- 不进入打分、不改候选池、不改 analysis_input.json
- 不阻断选股；任何异常均只写 logs/data_canary_<as_of>.json
- 不对比"行业"字段（Tushare 用 SW 申万、akshare 默认东财/同花顺，体系不一致）

判定阈值：
- close 差异 > 0.5% → warning，> 5% → error
- pe/pb 差异 > 10% → warning；数量级 / 符号差异 → warning（仅 em 源）
- name 忽略 ST/*ST/PT 前缀差异
- 5 只抽样中 >=3 只在 akshare 找不到 → error（疑似 akshare 故障）

Usage:
    python runners/data_canary.py --as-of 20260522
    python runners/data_canary.py --as-of 20260522 --source em
    python runners/data_canary.py --candidates A-EGS/Result/egs_full_20260522.csv
"""
import argparse
import json
import os
import random
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

try:
    import akshare as ak
except ModuleNotFoundError:
    ak = None

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"

SAMPLE_SIZE = 5
CLOSE_WARN_PCT = 0.5
CLOSE_ERROR_PCT = 5.0
PE_PB_WARN_PCT = 10.0
MISSING_ERROR_COUNT = 3

ST_PREFIXES = ("*ST", "ST", "PT", "退市", "退")

AK_SOURCES = {
    "sina": {
        "fn_name": "stock_zh_a_spot",
        "fields": {"code": "代码", "name": "名称", "close": "最新价"},
        "label": "stock_zh_a_spot (新浪源, close+name only)",
        "supports_pe_pb": False,
    },
    "em": {
        "fn_name": "stock_zh_a_spot_em",
        "fields": {"code": "代码", "name": "名称", "close": "最新价",
                   "pe": "市盈率-动态", "pb": "市净率"},
        "label": "stock_zh_a_spot_em (东财源, 含 pe/pb; 受本地 VPN 路由影响)",
        "supports_pe_pb": True,
    },
}

REQUIRED_CANDIDATE_COLUMNS = ("ts_code", "name", "close")


def _normalize_name(name) -> str:
    if name is None or (isinstance(name, float) and pd.isna(name)):
        return ""
    s = str(name).strip()
    for prefix in ST_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):].strip()
            break
    return s


def _ts_code_to_akshare(ts_code: str) -> str:
    """000001.SZ -> 000001"""
    return _normalize_code(str(ts_code).split(".")[0])


def _normalize_code(c) -> str:
    """Strip non-digits and pad/validate to A-share 6-digit format.
    'sh600000' / 'SH600000' / 600000 (int) / '1' -> '600000' / '000001'.
    Codes longer than 6 digits (港股 5 位 / 美股 / 未来扩展) return "" so
    they fall through to missing_in_akshare rather than silently matching
    a wrong stock via truncation."""
    digits = "".join(ch for ch in str(c) if ch.isdigit())
    if not digits or len(digits) > 6:
        return ""
    return digits.zfill(6)


def _find_candidates(as_of: str) -> Path | None:
    """Default: prefer 实盘 egs_full, fallback 回测 candidates."""
    p1 = ROOT / "A-EGS" / "Result" / f"egs_full_{as_of}.csv"
    if p1.exists():
        return p1
    p2 = ROOT / "result" / "a_short" / "backtest" / "generated" / as_of / "candidates.csv"
    if p2.exists():
        return p2
    return None


def _write_log(payload: dict, as_of: str) -> Path:
    """Atomic write: tmp file + os.replace, so Ctrl+C / OOM mid-write
    leaves either the old file intact or the new file complete; never
    a truncated half-file."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    out = LOG_DIR / f"data_canary_{as_of}.json"
    fd, tmp_path = tempfile.mkstemp(prefix=f".data_canary_{as_of}_",
                                    suffix=".json.tmp", dir=str(LOG_DIR))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=str)
        os.replace(tmp_path, out)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return out


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _skip_payload(as_of: str, status: str, message: str, **extra) -> dict:
    payload = {
        "as_of": as_of,
        "ran_at": _now_iso(),
        "status": status,
        "summary": {"overall_status": status},
        "message": message,
    }
    payload.update(extra)
    return payload


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _pick_pe(row) -> tuple[float | None, str]:
    """Prefer pe_ttm (滚动 12 月) then pe (静态)."""
    for col in ("pe_ttm", "pe"):
        v = row.get(col)
        if v is not None and not (isinstance(v, float) and pd.isna(v)):
            try:
                return float(v), col
            except (TypeError, ValueError):
                continue
    return None, ""


def _compare_field(name: str, ts_val, ak_val, warn_pct: float,
                   error_pct: float | None = None) -> dict | None:
    """Return diff dict or None if within tolerance / not comparable."""
    if ts_val is None or ak_val is None:
        return None
    try:
        v_ts, v_ak = float(ts_val), float(ak_val)
    except (TypeError, ValueError):
        return None
    if pd.isna(v_ts) or pd.isna(v_ak):
        return None

    # Sign mismatch (pb 可能为负)
    if (v_ts > 0) != (v_ak > 0) and v_ts != 0 and v_ak != 0:
        return {"field": name, "ts": v_ts, "ak": v_ak, "severity": "warn",
                "note": "sign_mismatch"}

    # Magnitude mismatch (>=10x or <=0.1x)
    if abs(v_ts) > 1e-9 and abs(v_ak) > 1e-9:
        ratio = abs(v_ts) / abs(v_ak)
        if ratio >= 10 or ratio <= 0.1:
            return {"field": name, "ts": v_ts, "ak": v_ak, "severity": "warn",
                    "note": "magnitude_mismatch"}

    base = max(abs(v_ts), abs(v_ak))
    if base < 1e-9:
        return None
    pct = abs(v_ts - v_ak) / base * 100

    if error_pct is not None and pct > error_pct:
        return {"field": name, "ts": v_ts, "ak": v_ak, "pct": round(pct, 3),
                "severity": "error"}
    if pct > warn_pct:
        return {"field": name, "ts": v_ts, "ak": v_ak, "pct": round(pct, 3),
                "severity": "warn"}
    return None


def _compare_one(row, ak_row, fields: dict, supports_pe_pb: bool) -> dict:
    rec = {
        "ts_code": str(row["ts_code"]),
        "name_tushare": str(row.get("name", "")),
    }
    if ak_row is None:
        rec["status"] = "missing_in_akshare"
        return rec

    rec["name_akshare"] = str(ak_row[fields["name"]])

    diffs = []

    # name (忽略 ST 前缀)
    if _normalize_name(row.get("name")) != _normalize_name(ak_row[fields["name"]]):
        diffs.append({"field": "name", "ts": rec["name_tushare"],
                      "ak": rec["name_akshare"], "severity": "warn"})

    # close
    d = _compare_field("close", row.get("close"), ak_row[fields["close"]],
                       CLOSE_WARN_PCT, CLOSE_ERROR_PCT)
    if d:
        diffs.append(d)

    # pe/pb only if source carries them (em 源; sina 没有)
    if supports_pe_pb:
        pe_ts, pe_source = _pick_pe(row)
        if pe_ts is not None:
            rec["pe_tushare_source"] = pe_source
            d = _compare_field("pe", pe_ts, ak_row[fields["pe"]], PE_PB_WARN_PCT)
            if d:
                d["note"] = (d.get("note") or "") + f"|ts_uses_{pe_source}|ak_uses_dynamic"
                diffs.append(d)

        d = _compare_field("pb", row.get("pb"), ak_row[fields["pb"]], PE_PB_WARN_PCT)
        if d:
            diffs.append(d)

    rec["status"] = "diff" if diffs else "ok"
    if diffs:
        rec["diffs"] = diffs
    return rec


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2.6 旁路数据对账（Tushare vs akshare）")
    parser.add_argument("--as-of", default=datetime.now().strftime("%Y%m%d"),
                        help="As-of date YYYYMMDD (default: today)")
    parser.add_argument("--candidates", default=None,
                        help="Path to candidates CSV (default: auto-find egs_full_<as_of>.csv)")
    parser.add_argument("--sample-size", type=int, default=SAMPLE_SIZE)
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed (default: deterministic by as_of date)")
    parser.add_argument("--tier", default="Tier1",
                        help="Filter by tier before sampling (default: Tier1; '' to disable)")
    parser.add_argument("--source", choices=list(AK_SOURCES.keys()), default="sina",
                        help="akshare data source. sina (default): close+name only, stable; "
                             "em: 含 pe/pb, 但本地若挂 VPN 需将 *.eastmoney.com 加 split-tunnel")
    args = parser.parse_args()
    source_spec = AK_SOURCES[args.source]
    source_fields = source_spec["fields"]

    # Graceful skip: akshare not installed
    if ak is None:
        out = _write_log(_skip_payload(
            args.as_of,
            "skipped_akshare_not_installed",
            "akshare not installed; run `pip install akshare` to enable canary.",
        ), args.as_of)
        print(f"[SKIP] akshare not installed; wrote {out}")
        return 0

    # Find candidates
    cand_path = Path(args.candidates) if args.candidates else _find_candidates(args.as_of)
    if cand_path is None or not cand_path.exists():
        out = _write_log(_skip_payload(
            args.as_of,
            "skipped_no_candidates",
            f"No candidates file found for as_of={args.as_of}.",
        ), args.as_of)
        print(f"[SKIP] no candidates; wrote {out}")
        return 0

    try:
        df = pd.read_csv(cand_path)
    except Exception as e:
        out = _write_log(_skip_payload(
            args.as_of,
            "skipped_candidates_read_failed",
            f"{type(e).__name__}: {e}",
            candidates_source=_display_path(cand_path),
        ), args.as_of)
        print(f"[SKIP] candidates read failed; wrote {out}")
        return 0

    if df.empty:
        out = _write_log(_skip_payload(
            args.as_of,
            "skipped_empty_candidates",
            "Candidates file is empty.",
            candidates_source=_display_path(cand_path),
        ), args.as_of)
        print(f"[SKIP] empty candidates; wrote {out}")
        return 0

    required_cols = list(REQUIRED_CANDIDATE_COLUMNS)
    if args.tier:
        required_cols.append("tier")
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        out = _write_log(_skip_payload(
            args.as_of,
            "skipped_candidates_schema_mismatch",
            "Candidates file missing required columns.",
            candidates_source=_display_path(cand_path),
            missing_columns=missing_cols,
            available_columns=list(df.columns),
        ), args.as_of)
        print(f"[SKIP] candidates schema mismatch; wrote {out}")
        return 0

    # Tier filter
    if args.tier and "tier" in df.columns:
        df = df[df["tier"] == args.tier].copy()
        if df.empty:
            out = _write_log(_skip_payload(
                args.as_of,
                "skipped_no_rows_after_tier_filter",
                f"No rows after tier={args.tier} filter.",
                candidates_source=_display_path(cand_path),
                tier_filter=args.tier,
            ), args.as_of)
            print(f"[SKIP] no rows after tier={args.tier}; wrote {out}")
            return 0

    # Sample (deterministic seed = as_of date)
    try:
        seed = args.seed if args.seed is not None else int(args.as_of)
    except ValueError:
        seed = abs(hash(args.as_of)) % (2 ** 32)
    rng = random.Random(seed)
    sample_size = max(0, min(args.sample_size, len(df)))
    if sample_size == 0:
        out = _write_log(_skip_payload(
            args.as_of,
            "skipped_zero_sample_size",
            "No rows sampled because --sample-size resolved to 0.",
            candidates_source=_display_path(cand_path),
            tier_filter=args.tier or None,
            available_rows=int(len(df)),
        ), args.as_of)
        print(f"[SKIP] zero sample size; wrote {out}")
        return 0
    sample_idx = rng.sample(range(len(df)), sample_size)
    sample = df.iloc[sample_idx].reset_index(drop=True)

    # Fetch akshare spot snapshot (one shot for whole A-share)
    fn = getattr(ak, source_spec["fn_name"], None)
    if fn is None:
        out = _write_log(_skip_payload(
            args.as_of,
            "error_akshare_fn_missing",
            f"akshare has no function {source_spec['fn_name']} (akshare too old or renamed).",
            source=args.source,
            candidates_source=_display_path(cand_path),
        ), args.as_of)
        print(f"[ERROR] akshare {source_spec['fn_name']} missing; wrote {out} (not blocking)")
        return 0

    print(f"[INFO] fetching akshare {source_spec['fn_name']} via --source={args.source} "
          f"({sample_size} candidates to check)...")
    try:
        ak_spot = fn()
    except Exception as e:
        out = _write_log({
            "as_of": args.as_of,
            "ran_at": _now_iso(),
            "status": "error_akshare_fetch_failed",
            "message": f"{type(e).__name__}: {e}",
            "summary": {"overall_status": "error_akshare_fetch_failed"},
            "source": args.source,
            "candidates_source": _display_path(cand_path),
        }, args.as_of)
        print(f"[ERROR] akshare fetch failed: {e}; wrote {out} (not blocking)")
        return 0

    missing_ak_cols = [v for v in source_fields.values() if v not in ak_spot.columns]
    if missing_ak_cols:
        out = _write_log(_skip_payload(
            args.as_of,
            "error_akshare_schema_mismatch",
            f"akshare {source_spec['fn_name']} missing expected columns.",
            source=args.source,
            candidates_source=_display_path(cand_path),
            missing_columns=missing_ak_cols,
            available_columns=list(ak_spot.columns),
        ), args.as_of)
        print(f"[ERROR] akshare schema mismatch; wrote {out} (not blocking)")
        return 0

    ak_spot[source_fields["code"]] = ak_spot[source_fields["code"]].map(_normalize_code)
    ak_lookup = {row[source_fields["code"]]: row for _, row in ak_spot.iterrows()}

    comparisons = []
    missing = 0
    n_error = 0
    n_warn = 0

    for _, row in sample.iterrows():
        ak_code = _ts_code_to_akshare(row["ts_code"])
        ak_row = ak_lookup.get(ak_code)
        rec = _compare_one(row, ak_row, source_fields, source_spec["supports_pe_pb"])
        comparisons.append(rec)
        if rec["status"] == "missing_in_akshare":
            missing += 1
        for d in rec.get("diffs", []):
            if d["severity"] == "error":
                n_error += 1
            else:
                n_warn += 1

    if missing >= MISSING_ERROR_COUNT:
        overall = "error_missing"
    elif n_error > 0:
        overall = "error_drift"
    elif n_warn > 0 or missing > 0:
        overall = "warn"
    else:
        overall = "ok"

    limitations = [
        "akshare spot 是实时/最近收盘快照，非历史 PIT；若脚本晚于 as_of 超过 1-2 个交易日，close 可能已偏移。",
        "行业字段未对比（Tushare 用 SW 申万，akshare 默认东财/同花顺）。",
        "name 比较忽略 ST/*ST/PT 前缀差异。",
        "canary 仅旁路 warning，不阻断选股，不写入 analysis_input.json，不影响打分。",
    ]
    if source_spec["supports_pe_pb"]:
        limitations.insert(1, "Tushare 的 pe 优先用 pe_ttm（滚动），akshare 的 pe 是动态 PE，口径轻微差异。")
    else:
        limitations.insert(1, f"--source={args.source} 不含 pe/pb，仅校验 close + name。"
                              " 切 --source=em 启用 pe/pb 对账（需本地能直连 *.eastmoney.com）。")

    payload = {
        "as_of": args.as_of,
        "ran_at": _now_iso(),
        "status": overall,
        "candidates_source": _display_path(cand_path),
        "tier_filter": args.tier or None,
        "sample_size": sample_size,
        "sample_seed": seed,
        "source": args.source,
        "akshare_source": source_spec["label"],
        "summary": {
            "overall_status": overall,
            "missing_in_akshare": missing,
            "errors": n_error,
            "warnings": n_warn,
        },
        "thresholds": {
            "close_warn_pct": CLOSE_WARN_PCT,
            "close_error_pct": CLOSE_ERROR_PCT,
            "pe_pb_warn_pct": PE_PB_WARN_PCT if source_spec["supports_pe_pb"] else None,
            "missing_error_count": MISSING_ERROR_COUNT,
        },
        "comparisons": comparisons,
        "limitations": limitations,
    }

    out = _write_log(payload, args.as_of)
    icon = {"ok": "[OK]", "warn": "[WARN]",
            "error_drift": "[ERROR]", "error_missing": "[ERROR]"}.get(overall, "[?]")
    print(f"{icon} canary {overall}: {missing} missing, {n_error} errors, "
          f"{n_warn} warnings ({sample_size} sampled from {len(df)} {args.tier or 'all'} rows) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
