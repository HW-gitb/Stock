#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-short 持仓恒列入 M6.7 — Tier-2 egs_full adapter（S1）.

把本轮 EGS 官方全量评分 `result/a_short/<as_of>/[revisions/<run_revision_id>/]egs_full_<as_of>.csv`(扁平 CSV,粗筛后的全量 rank)读出,并把其中
**一行**映射成 `a_short_weekly_pipeline.normalize_candidate` 能消费的候选 dict 结构,供"过了粗筛、没进
top-N"的持仓(Tier-2)复用本轮已算好的 EGS 分/风险标志/行业/流动性。

边界与诚实原则(对应设计 §2/§18.1):
- **只读 egs_full,不改 egs_main / 选股**。
- **只映射 CSV 中真实存在、含义明确的列**;含义不明确或不在 CSV 的字段**不伪造、不 default 成"安全"**——
  让下游按"该字段缺失"处理,而不是凭空判定"无风险"。
- egs_full 列名是会随 EGS 版本漂的 CSV 契约 → `load_egs_full` 校验必需表头,缺列**显式失败**(不静默错位)。

Tier-1(持仓在 top-N)直接用 `analysis_input.candidates`,不经本 adapter;Tier-3(连 egs_full 都不在,粗筛
排除)不经本 adapter(标 EGS 未覆盖)。本 adapter 只服务 Tier-2。
"""
from __future__ import annotations

import csv
from pathlib import Path

from engine.a_short_delisting import derive_delisting_flags
from engine.a_short_run_revision import (
    official_egs_full_path,
    resolve_official_revision,
    validate_official_egs_full_binding,
)

ROOT = Path(__file__).resolve().parents[1]

# 必需表头(adapter 映射依赖的列);缺任一 → 视为 egs_full 契约漂移,显式失败而非静默错位。
EGS_FULL_REQUIRED_COLUMNS = (
    "ts_code", "name", "close", "avg_amount_5d", "avg_amount_20d",
    "esp_score", "l4_score", "final_score",
    "is_lock", "is_breakout", "vol_confirm", "has_crash_veto", "overheat_flag", "chasing_high",
    "reduce_deduct", "l1_name", "l2_name", "list_status",
)


def egs_full_path(as_of: str, root: Path | str = ROOT,
                  run_revision_id: str | None = None) -> Path:
    return official_egs_full_path(root, as_of, run_revision_id)


def load_egs_full(as_of: str, root: Path | str = ROOT,
                  run_revision_id: str | None = None, *, strict: bool = False) -> dict:
    """读官方 `egs_full_<as_of>.csv` → {ts_code: row_dict}。

    文件不存在 → 返回 {}(则所有持仓走 Tier-3 = EGS 未覆盖,这是诚实降级,不是错误)。
    文件存在但缺必需表头 → raise ValueError(egs_full 契约漂移,必须显式暴露,不可静默错位)。
    """
    selected = resolve_official_revision(root, as_of, require=False)
    official = run_revision_id is not None or selected is not None
    path = egs_full_path(as_of, root, run_revision_id)
    if not path.is_file():
        if strict or run_revision_id is not None or selected is not None:
            raise FileNotFoundError(
                f"official egs_full artifact missing for {as_of}"
                f"{f' revision={run_revision_id}' if run_revision_id else ''}: {path}"
            )
        return {}
    if official:
        validate_official_egs_full_binding(path, as_of)
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in EGS_FULL_REQUIRED_COLUMNS if c not in header]
        if missing:
            raise ValueError(f"egs_full {path} 缺必需列 {missing}(egs_full 契约漂移;Tier-2 adapter 拒绝静默错位)")
        out = {}
        for raw in reader:
            row = {(k.strip() if k else k): v for k, v in raw.items()}
            code = (row.get("ts_code") or "").strip()
            if code:
                out[code] = row
        return out


def _f(row: dict, key: str):
    """float or None(空/非数 → None,不补 0)。"""
    v = (row.get(key) or "").strip()
    if v == "":
        return None
    try:
        return float(v)
    except ValueError:
        return None


def _b(row: dict, key: str) -> bool:
    """egs_full 布尔列存为 Python `str(bool)` = 'True'/'False'(已核 20260612 真值)。"""
    return (row.get(key) or "").strip().lower() == "true"


def egs_full_row_to_candidate(row: dict, *, historical: bool = False) -> dict:
    """把一行 egs_full 映射成 normalize_candidate 能消费的候选 dict。

    只映射含义明确的列。**不映射的字段一律不写入**(下游按缺失/保守处理),不伪造"安全":
    - `derived_flags.hard_veto`/`event_risk.holder_reduction` 等无明确单列的,按下述最佳映射或留空。
    - `industry_trend`(顺/逆风)egs_full 无此判定 → 不在此给出(由调用方按 neutral 默认,非本 adapter 伪造)。
    """
    name = (row.get("name") or "").strip()
    delisting_flags = derive_delisting_flags(row, historical=historical)
    # 停牌/退市:list_status L=上市、P=暂停、D=退市;非 L 即非正常交易。
    list_status = (row.get("list_status") or "").strip().upper()
    is_suspended = list_status not in ("", "L")
    # 减持:egs_full `reduce_deduct` 非 0 视为有减持扣分信号(best-effort;无独立 active_plan 列)。
    reduce_deduct = _f(row, "reduce_deduct")
    holder_reduction_active = bool(reduce_deduct)

    return {
        "ts_code": (row.get("ts_code") or "").strip(),
        "name": name,
        "quote": {"close": _f(row, "close")},
        "scores": {"esp_score": _f(row, "esp_score"), "l4_score": _f(row, "l4_score"),
                   "final_score": _f(row, "final_score")},
        # 显式布尔风险标志:egs_full 真有 → 真实映射(非伪造;该股本轮确被评分)。
        "derived_flags": {"overheat_flag": _b(row, "overheat_flag"), "chasing_high": _b(row, "chasing_high"),
                          "is_breakout": _b(row, "is_breakout"), "vol_confirm": _b(row, "vol_confirm"),
                          "has_crash_veto": _b(row, "has_crash_veto"), "is_lock": _b(row, "is_lock")},
        "event_risk": {"holder_reduction": {"active_plan": holder_reduction_active},
                       "delisting": {"st_flag": delisting_flags["st_flag"],
                                      "delisting_warning": delisting_flags["delisting_warning"]},
                       "suspension": {"is_suspended": is_suspended}},
        "liquidity": {"avg_amount_5d": _f(row, "avg_amount_5d"), "avg_amount_20d": _f(row, "avg_amount_20d")},
        # 行业上下文(供展示;industry_trend 顺逆风 egs_full 无,不在此伪造)
        "industry_l1": (row.get("l1_name") or "").strip(),
        "industry_l2": (row.get("l2_name") or "").strip(),
    }
