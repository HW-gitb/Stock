#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-short 手工账户表 → 原子 account bundle 转换器。

五张必需 CSV（account / positions / trades / manual_controls / portfolio_rule12）一次读取，
输出一个由 digest 绑定的 account + lineage JSON。``account.as_of`` 保留真实账户事实日，
``decision_as_of`` 单独记录周报决策日；Rule12 缺失或空白一律拒跑。转换器只做确定性的
状态校验/推进，不接券商、不抓行情、不自动下单。完整列映射见
``docs/a_short_account_state_manual_tables_4_3.md``。

用法：
    python runners/a_short_account_state_from_manual_tables.py \
        --input-dir state/a_short/account_state_csv --as-of 20260615 \
        --out state/a_short/account_bundle.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.data.a_share_board_scope import is_a_share_main_board  # noqa: E402

ACCOUNT_SCHEMA_NAME = "a_short_account_state"
ACCOUNT_SCHEMA_VERSION = "1.1.0"
LINEAGE_SCHEMA_NAME = "a_short_account_state_lineage"
LINEAGE_SCHEMA_VERSION = "1.0.0"
ACCOUNT_BUNDLE_SCHEMA_NAME = "a_short_account_bundle"
ACCOUNT_BUNDLE_SCHEMA_VERSION = "1.0.0"
ACCOUNT_BUNDLE_SCHEMA_PATH = ROOT / "schemas" / "a_short_account_bundle.schema.json"

# Rule12 is a highest-priority portfolio fact.  Missing/blank must not silently become inactive.
REQUIRED_TABLES = ("account", "positions", "trades", "manual_controls", "portfolio_rule12")
OPTIONAL_TABLES = ()

EXPECTED_COLUMNS = {
    "account": ("as_of", "available_cash", "total_equity", "current_gross_exposure",
                "manual_order_only", "broker_connection_allowed"),
    "positions": ("ts_code", "name", "shares", "avg_cost", "entry_date", "stop_loss",
                  "take_profit_1", "take_profit_2", "last_exit_date", "last_exit_reason", "manual_notes"),
    "trades": ("trade_date", "ts_code", "name", "side", "shares", "price", "reason", "order_manual", "notes"),
    "manual_controls": ("ts_code", "new_catalyst_confirmed", "m4_recheck_passed",
                        "max_reentry_position_pct", "override_status", "override_reason"),
    "portfolio_rule12": ("status", "reason", "triggered_at", "cooldown_until",
                         "recovery_position_multiplier", "consecutive_stop_losses_window",
                         "drawdown_pct", "iv_change_abs_1d_pctpt"),
}
REQUIRED_COLUMNS = {
    "account": ("as_of", "available_cash", "manual_order_only", "broker_connection_allowed"),
    "positions": ("ts_code", "name", "shares", "avg_cost", "entry_date"),
    "trades": ("trade_date", "ts_code", "name", "side", "shares", "price", "reason", "order_manual"),
    "manual_controls": ("ts_code",),
    "portfolio_rule12": ("status",),
}

# v14.2 spec defaults (single-source override-able via presets/a_short.yaml::position_management).
#   Rule13 = 24h cooldown (v14.2 §Rule13「止损后重建仓：24h冷静期」) → +1 calendar day in the date-only model.
#     Safety does NOT rest on the period length: an expired Rule13 cooldown advances to pending_recheck,
#     which STILL blocks re-entry until the manual new_catalyst + M4 recheck are both true.
#   Rule13 re-entry position cap = 50% (v14.2 §Rule13「仓位≤原50%」).
#   Rule12 recovery first-position multiplier = 50% (v14.2 §Rule12「48h冷静期，恢复后首笔仓位≤正常50%」).
DEFAULT_CONFIG = {
    "rule13_cooldown_calendar_days": 1,
    "rule13_default_max_reentry_position_pct": 0.5,
    "rule12_default_recovery_position_multiplier": 0.5,
}

VALID_RULE12_STATUSES = ("inactive", "active_cooldown", "recovery_1")
VALID_TRADE_SIDES = ("BUY", "SELL")


class ConvertError(SystemExit):
    """FATAL conversion error (fail-fast, never silently degrade risk state)."""

    def __init__(self, msg: str):
        super().__init__(f"[FATAL] {msg}")


# ── 显式 parsing（挡 Excel 静默强转 / 脏输入；CSV 也走同样的严格 parse）────────────────
def _parse_date(raw, field: str) -> str:
    s = ("" if raw is None else str(raw)).strip()
    # reject coerced floats ("20260601.0"), excel date objects, short/long, non-digit
    if not re.fullmatch(r"\d{8}", s):
        raise ConvertError(f"{field}={raw!r} 不是 8 位 YYYYMMDD 文本（疑被 Excel 转成数字/日期/丢前导零）")
    try:
        datetime.strptime(s, "%Y%m%d")
    except ValueError:
        raise ConvertError(f"{field}={raw!r} 不是合法日历日期")
    return s


def _parse_optional_date(raw, field: str):
    s = ("" if raw is None else str(raw)).strip()
    return None if s == "" else _parse_date(s, field)


def _parse_bool(raw, field: str) -> bool:
    s = ("" if raw is None else str(raw)).strip().lower()
    if s == "true":
        return True
    if s == "false":
        return False
    raise ConvertError(f"{field}={raw!r} 必须是 TRUE/FALSE（不接受 1/0/是/否/真/假，避免 Excel 强转歧义）")


def _parse_float(raw, field: str, *, positive=False, allow_zero=True, max_value=None):
    s = ("" if raw is None else str(raw)).strip()
    if s == "":
        raise ConvertError(f"{field} 缺失（必填数值）")
    try:
        v = float(s)
    except ValueError:
        raise ConvertError(f"{field}={raw!r} 不是合法数值")
    if not math.isfinite(v):
        raise ConvertError(f"{field}={raw!r} 非有限值（NaN/Inf 不接受）")
    if positive and v <= 0:
        raise ConvertError(f"{field}={raw!r} 必须 > 0")
    if not allow_zero and v == 0:
        raise ConvertError(f"{field}={raw!r} 不能为 0")
    if max_value is not None and v > max_value:
        raise ConvertError(f"{field}={raw!r} 超出上限 {max_value}")
    return v


def _parse_optional_float(raw, field: str, **kwargs):
    s = ("" if raw is None else str(raw)).strip()
    return None if s == "" else _parse_float(s, field, **kwargs)


def _parse_int_shares(raw, field: str) -> int:
    s = ("" if raw is None else str(raw)).strip()
    if not re.fullmatch(r"\d+", s):
        raise ConvertError(f"{field}={raw!r} 必须是正整数股数（不接受小数/科学计数，避免 Excel 把整数转成 float）")
    v = int(s)
    if v <= 0:
        raise ConvertError(f"{field}={raw!r} 必须 > 0")
    return v


def _parse_ts_code(raw, field: str) -> str:
    s = ("" if raw is None else str(raw)).strip().upper()
    if not re.fullmatch(r"\d{6}\.(SH|SZ)", s):
        raise ConvertError(f"{field}={raw!r} 不是合法 A 股代码（须 NNNNNN.SH/.SZ，含前导零）")
    if not is_a_share_main_board(s):
        raise ConvertError(f"{field}={s} 非 A 股主板（A-short 设计上只操作主板；非主板/B 股持仓请在本工具外管理）")
    return s


def _opt_str(raw):
    s = ("" if raw is None else str(raw)).strip()
    return None if s == "" else s


def _add_calendar_days(yyyymmdd: str, n: int) -> str:
    return (datetime.strptime(yyyymmdd, "%Y%m%d") + timedelta(days=n)).strftime("%Y%m%d")


# ── 核心纯函数：tables(dict[str, list[dict]]) + decision_as_of + config → (account_state, lineage)──
def build_account_state(tables: dict, decision_as_of: str, config: dict | None = None) -> tuple:
    """Build the schema-valid account_state dict + lineage dict from already-parsed table rows.

    `tables` maps table name → list of raw-string row dicts (csv.DictReader output). Pure & deterministic:
    same tables + decision_as_of + config → identical output (rows sorted by ts_code; no wall-clock).
    Raises ConvertError (FATAL) on any malformed / out-of-contract input.
    """
    cfg = dict(DEFAULT_CONFIG)
    if config:
        cfg.update(config)
    _validate_config(cfg)
    decision_as_of = _parse_date(decision_as_of, "--as-of")

    facts_as_of, account_fields = _build_account_fields(tables["account"], decision_as_of)
    facts_staleness = "current" if facts_as_of == decision_as_of else "stale_warning"

    positions, held = _build_positions(tables["positions"], decision_as_of)
    rule12, rule12_lineage = _build_rule12(tables.get("portfolio_rule12") or [], decision_as_of, cfg)
    manual = _index_manual_controls(tables["manual_controls"])
    rule13, rule13_lineage = _build_rule13(tables["trades"], held, manual, decision_as_of, cfg)
    consistency_warnings = reconcile_trades_positions(tables["trades"], positions)   # 4.3-D advisory

    account_state = {
        "schema_name": ACCOUNT_SCHEMA_NAME,
        "schema_version": ACCOUNT_SCHEMA_VERSION,
        "as_of": decision_as_of,
        "available_cash": account_fields["available_cash"],
        "total_equity": account_fields["total_equity"],
        "current_gross_exposure": account_fields["current_gross_exposure"],
        "positions": positions,
        "rule12": rule12,
        "rule13_cooldowns": rule13,
        "manual_order_only": True,
        "broker_connection_allowed": False,
    }
    lineage = {
        "schema_name": LINEAGE_SCHEMA_NAME,
        "schema_version": LINEAGE_SCHEMA_VERSION,
        "generated_at": None,
        "decision_as_of": decision_as_of,
        "facts_as_of": facts_as_of,
        "facts_staleness": facts_staleness,
        "config": dict(cfg),
        "source_tables": [],   # filled by main() (needs file paths/hashes); pure build leaves empty
        "rule12": rule12_lineage,
        "rule13_cooldowns": rule13_lineage,
        "consistency_warnings": consistency_warnings,
    }
    return account_state, lineage


def _canonical_json_sha256(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _bundle_digest(account: dict, lineage: dict) -> str:
    return _canonical_json_sha256({"account": account, "lineage": lineage})


def build_account_bundle(tables: dict, decision_as_of: str, config: dict | None = None,
                         source_tables: list | None = None, generated_at: str | None = None) -> dict:
    """Build one atomically publishable account+lineage snapshot.

    ``account.as_of`` remains the true manual-facts date.  ``decision_as_of`` is kept only at the
    bundle/lineage level, so a Friday snapshot used for a Monday-before-open decision cannot be
    relabelled as Monday facts.  The digest binds account and lineage in the same JSON object.
    """
    account, lineage = build_account_state(tables, decision_as_of, config)
    facts_as_of = lineage["facts_as_of"]
    account["as_of"] = facts_as_of
    lineage["source_tables"] = list(source_tables or [])
    lineage["generated_at"] = generated_at
    digest = _bundle_digest(account, lineage)
    bundle = {
        "schema_name": ACCOUNT_BUNDLE_SCHEMA_NAME,
        "schema_version": ACCOUNT_BUNDLE_SCHEMA_VERSION,
        "decision_as_of": str(decision_as_of),
        "facts_as_of": facts_as_of,
        "snapshot_id": f"a-short-account-{facts_as_of}-{digest[:16]}",
        "snapshot_digest": digest,
        "account": account,
        "lineage": lineage,
    }
    validate_account_bundle(bundle, str(decision_as_of))
    return bundle


def validate_account_bundle(bundle: dict, decision_as_of: str) -> dict:
    """Validate schema, date identity and account/lineage digest binding."""
    import jsonschema
    if not isinstance(bundle, dict):
        raise ConvertError("account bundle 须为 JSON object")
    try:
        schema = json.loads(ACCOUNT_BUNDLE_SCHEMA_PATH.read_text(encoding="utf-8"))
        jsonschema.validate(bundle, schema)
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise ConvertError(f"account bundle schema invalid: {exc}") from exc
    if bundle.get("decision_as_of") != str(decision_as_of):
        raise ConvertError(
            f"account bundle decision_as_of {bundle.get('decision_as_of')} != 本次 {decision_as_of}")
    account, lineage = bundle["account"], bundle["lineage"]
    total_equity = account.get("total_equity")
    gross_exposure = account.get("current_gross_exposure")
    if (isinstance(total_equity, bool) or not isinstance(total_equity, (int, float)) or total_equity <= 0 or
            isinstance(gross_exposure, bool) or not isinstance(gross_exposure, (int, float)) or gross_exposure < 0):
        raise ConvertError("account bundle 必须提供有效 total_equity/current_gross_exposure，供 bucket 敞口门使用")
    facts = bundle["facts_as_of"]
    if account.get("as_of") != facts or lineage.get("facts_as_of") != facts:
        raise ConvertError("account bundle facts_as_of / account.as_of / lineage.facts_as_of 不一致")
    if lineage.get("decision_as_of") != str(decision_as_of):
        raise ConvertError("account bundle lineage.decision_as_of 与本次决策日不一致")
    expected = _bundle_digest(account, lineage)
    if bundle.get("snapshot_digest") != expected:
        raise ConvertError("account bundle snapshot_digest 与 account+lineage 内容不一致（疑似错配/篡改）")
    expected_id = f"a-short-account-{facts}-{expected[:16]}"
    if bundle.get("snapshot_id") != expected_id:
        raise ConvertError("account bundle snapshot_id 与 facts_as_of/digest 不一致")
    from runners.a_short_weekly_pipeline import validate_account_state
    validate_account_state(account, facts)
    try:
        lineage_schema = json.loads((ROOT / "schemas" / "a_short_account_state_lineage.schema.json").read_text(encoding="utf-8"))
        jsonschema.validate(lineage, lineage_schema)
    except (OSError, json.JSONDecodeError, jsonschema.ValidationError) as exc:
        raise ConvertError(f"account bundle lineage schema invalid: {exc}") from exc
    return bundle


def _validate_config(cfg: dict) -> None:
    days = cfg.get("rule13_cooldown_calendar_days")
    if not isinstance(days, int) or isinstance(days, bool) or days < 0:
        raise ConvertError(f"config.rule13_cooldown_calendar_days={days!r} 须为 >=0 整数")
    for key in ("rule13_default_max_reentry_position_pct", "rule12_default_recovery_position_multiplier"):
        v = cfg.get(key)
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not (0 < v <= 1):
            raise ConvertError(f"config.{key}={v!r} 须在 (0, 1]")


def _build_account_fields(rows: list, decision_as_of: str) -> tuple:
    if len(rows) != 1:
        raise ConvertError(f"account 表须恰好 1 行（组合账户级状态唯一），实际 {len(rows)} 行")
    a = rows[0]
    facts_as_of = _parse_date(a.get("as_of"), "account.as_of")
    if facts_as_of > decision_as_of:
        raise ConvertError(f"account.as_of {facts_as_of} > --as-of {decision_as_of}（用了未来事实，拒跑）")
    if not _parse_bool(a.get("manual_order_only"), "account.manual_order_only"):
        raise ConvertError("account.manual_order_only 必须为 TRUE")
    if _parse_bool(a.get("broker_connection_allowed"), "account.broker_connection_allowed"):
        raise ConvertError("account.broker_connection_allowed 必须为 FALSE")
    available_cash = _parse_float(a.get("available_cash"), "account.available_cash")
    if available_cash < 0:
        raise ConvertError("account.available_cash 必须 >= 0；0 现金允许继续管理已有持仓，但禁止新建仓")
    return facts_as_of, {
        "available_cash": available_cash,
        "total_equity": _parse_optional_float(a.get("total_equity"), "account.total_equity", positive=True),
        "current_gross_exposure": _parse_optional_float(
            a.get("current_gross_exposure"), "account.current_gross_exposure"),
    }


def _build_positions(rows: list, decision_as_of: str) -> tuple:
    positions = []
    seen = set()
    for i, r in enumerate(rows):
        ts = _parse_ts_code(r.get("ts_code"), f"positions[{i}].ts_code")
        if ts in seen:
            raise ConvertError(f"positions 含重复 ts_code {ts}")
        seen.add(ts)
        name = _opt_str(r.get("name"))
        if not name:
            raise ConvertError(f"positions[{i}].name 必填")
        entry_date = _parse_date(r.get("entry_date"), f"positions[{i}].entry_date")
        if entry_date > decision_as_of:
            raise ConvertError(f"positions[{i}].entry_date {entry_date} > --as-of {decision_as_of}（未来建仓）")
        last_exit = _parse_optional_date(r.get("last_exit_date"), f"positions[{i}].last_exit_date")
        if last_exit is not None and last_exit > decision_as_of:
            raise ConvertError(f"positions[{i}].last_exit_date {last_exit} > --as-of {decision_as_of}")
        positions.append({
            "ts_code": ts,
            "name": name,
            "shares": _parse_int_shares(r.get("shares"), f"positions[{i}].shares"),
            "avg_cost": _parse_float(r.get("avg_cost"), f"positions[{i}].avg_cost", positive=True),
            "entry_date": entry_date,
            "stop_loss": _parse_optional_float(r.get("stop_loss"), f"positions[{i}].stop_loss", positive=True),
            "take_profit_1": _parse_optional_float(r.get("take_profit_1"), f"positions[{i}].take_profit_1", positive=True),
            "take_profit_2": _parse_optional_float(r.get("take_profit_2"), f"positions[{i}].take_profit_2", positive=True),
            "last_exit_date": last_exit,
            "last_exit_reason": _opt_str(r.get("last_exit_reason")),
        })
    positions.sort(key=lambda p: p["ts_code"])
    return positions, seen


def _build_rule12(rows: list, decision_as_of: str, cfg: dict) -> tuple:
    if len(rows) > 1:
        raise ConvertError(f"portfolio_rule12 表至多 1 行（组合级状态唯一），实际 {len(rows)} 行")
    if not rows or _opt_str(rows[0].get("status")) is None:
        raise ConvertError("portfolio_rule12 表/状态缺失；无法证明组合熔断未触发，拒绝默认 inactive")
    r = rows[0]
    status = _opt_str(r.get("status"))
    if status not in VALID_RULE12_STATUSES:
        raise ConvertError(f"portfolio_rule12.status={status!r} 须为 {VALID_RULE12_STATUSES} 之一")
    triggered_at = _parse_optional_date(r.get("triggered_at"), "portfolio_rule12.triggered_at")
    if triggered_at is not None and triggered_at > decision_as_of:
        raise ConvertError(f"portfolio_rule12.triggered_at {triggered_at} > --as-of {decision_as_of}")
    cooldown_until = _parse_optional_date(r.get("cooldown_until"), "portfolio_rule12.cooldown_until")
    mult = _parse_optional_float(r.get("recovery_position_multiplier"),
                                 "portfolio_rule12.recovery_position_multiplier", positive=True, max_value=1.0)
    progressed = None

    if status == "active_cooldown":
        if cooldown_until is None:
            raise ConvertError("portfolio_rule12 active_cooldown 必须填 cooldown_until")
        if cooldown_until < decision_as_of:
            # 过期：自动推进到 recovery_1（更严格侧）；绝不自动到 inactive
            progressed = {"from_status": "active_cooldown", "to_status": "recovery_1"}
            status = "recovery_1"
    if status == "recovery_1" and mult is None:
        mult = cfg["rule12_default_recovery_position_multiplier"]

    rule12 = {
        "status": status,
        "reason": _opt_str(r.get("reason")),
        "triggered_at": triggered_at,
        "cooldown_until": cooldown_until,
        "recovery_position_multiplier": mult if status == "recovery_1" else None,
        "consecutive_stop_losses_window": _parse_optional_int_nonneg(
            r.get("consecutive_stop_losses_window"), "portfolio_rule12.consecutive_stop_losses_window"),
        "drawdown_pct": _parse_optional_float(r.get("drawdown_pct"), "portfolio_rule12.drawdown_pct"),
        "iv_change_abs_1d_pctpt": _parse_optional_float(
            r.get("iv_change_abs_1d_pctpt"), "portfolio_rule12.iv_change_abs_1d_pctpt"),
    }
    return rule12, {"source": "excel_portfolio_rule12", "progressed": progressed}


def _parse_optional_int_nonneg(raw, field: str):
    s = ("" if raw is None else str(raw)).strip()
    if s == "":
        return None
    if not re.fullmatch(r"\d+", s):
        raise ConvertError(f"{field}={raw!r} 须为非负整数")
    return int(s)


def _index_manual_controls(rows: list) -> dict:
    out = {}
    for i, r in enumerate(rows):
        ts = _parse_ts_code(r.get("ts_code"), f"manual_controls[{i}].ts_code")
        if ts in out:
            raise ConvertError(f"manual_controls 含重复 ts_code {ts}")
        override = _opt_str(r.get("override_status"))
        if override is not None and override != "manual_block":
            # 安全后门防护：manual_allow 等放行不允许（只许更严格方向）
            raise ConvertError(
                f"manual_controls[{i}].override_status={override!r} 不允许；只支持 manual_block 或留空"
                "（解除阻断只能走正规的 new_catalyst_confirmed + m4_recheck_passed 事实，不能用单元格放行）")
        out[ts] = {
            "new_catalyst_confirmed": _parse_bool(r.get("new_catalyst_confirmed") or "false",
                                                  f"manual_controls[{i}].new_catalyst_confirmed"),
            "m4_recheck_passed": _parse_bool(r.get("m4_recheck_passed") or "false",
                                             f"manual_controls[{i}].m4_recheck_passed"),
            "max_reentry_position_pct": _parse_optional_float(
                r.get("max_reentry_position_pct"), f"manual_controls[{i}].max_reentry_position_pct",
                positive=True, max_value=1.0),
            "manual_block": override == "manual_block",
        }
    return out


def _build_rule13(trades: list, held: set, manual: dict, decision_as_of: str, cfg: dict) -> tuple:
    # 最近一笔 SELL 决定当前出场态：取每只票 max(trade_date) 的 SELL；该日若有 stop_loss → 触发冷静期。
    latest_sell = {}   # ts_code -> (trade_date, has_stop_loss_at_that_date)
    for i, r in enumerate(trades):
        ts = _parse_ts_code(r.get("ts_code"), f"trades[{i}].ts_code")
        if not _opt_str(r.get("name")):
            raise ConvertError(f"trades[{i}].name 必填")
        side = (_opt_str(r.get("side")) or "").upper()
        if side not in VALID_TRADE_SIDES:
            raise ConvertError(f"trades[{i}].side={r.get('side')!r} 须为 BUY/SELL")
        trade_date = _parse_date(r.get("trade_date"), f"trades[{i}].trade_date")
        if trade_date > decision_as_of:
            raise ConvertError(f"trades[{i}].trade_date {trade_date} > --as-of {decision_as_of}（未来成交）")
        _parse_int_shares(r.get("shares"), f"trades[{i}].shares")
        _parse_float(r.get("price"), f"trades[{i}].price", positive=True)
        reason = _opt_str(r.get("reason"))
        if not reason:
            raise ConvertError(f"trades[{i}].reason 必填（entry/stop_loss/take_profit/manual_exit 等）")
        if not _parse_bool(r.get("order_manual"), f"trades[{i}].order_manual"):
            raise ConvertError(f"trades[{i}].order_manual 必须为 TRUE（系统只记录手工成交）")
        if side != "SELL":
            continue
        prev = latest_sell.get(ts)
        is_stop = reason == "stop_loss"
        if prev is None or trade_date > prev[0]:
            latest_sell[ts] = (trade_date, is_stop)
        elif trade_date == prev[0]:
            latest_sell[ts] = (trade_date, prev[1] or is_stop)  # 同日多笔 SELL：任一止损 → 视为止损（保守）

    rule13 = []
    lineage = []
    for ts in sorted(latest_sell):
        trade_date, is_stop = latest_sell[ts]
        if not is_stop or ts in held:
            continue   # 最近出场非止损，或已重新持有（持仓管理，引擎走 not_applicable）→ 不生成冷静期
        mc = manual.get(ts, {})
        new_cat = bool(mc.get("new_catalyst_confirmed"))
        m4 = bool(mc.get("m4_recheck_passed"))
        max_reentry = mc.get("max_reentry_position_pct")
        if max_reentry is None:
            max_reentry = cfg["rule13_default_max_reentry_position_pct"]
        cooldown_until = _add_calendar_days(trade_date, cfg["rule13_cooldown_calendar_days"])
        base_status = "active_cooldown"
        if decision_as_of <= cooldown_until:
            status = "active_cooldown"
        elif not (new_cat and m4):
            status = "pending_recheck"
        else:
            status = "cleared_for_reentry"
        manual_block = bool(mc.get("manual_block"))
        if manual_block and status == "cleared_for_reentry":
            status = "pending_recheck"   # 用户强制阻断：只许更严格，永不放行到可再入
        progressed = None if status == base_status else {"from_status": base_status, "to_status": status}
        rule13.append({
            "ts_code": ts,
            "status": status,
            "exit_date": trade_date,
            "exit_reason": "stop_loss",
            "cooldown_until": cooldown_until,
            "requires_new_catalyst": True,
            "new_catalyst_confirmed": new_cat,
            "requires_m4_recheck": True,
            "m4_recheck_passed": m4,
            "max_reentry_position_pct": float(max_reentry),
            "notes": None,
        })
        lineage.append({
            "ts_code": ts,
            "source": "excel_trades_with_manual_controls" if ts in manual else "excel_trades",
            "progressed": progressed,
            "exit_date": trade_date,
            "cooldown_until": cooldown_until,
            "manual_block_applied": manual_block,
        })

    # manual_block 只能挂在「有止损冷静期、当前空仓」的票上（更严格方向）；其余位置 account_state schema 无字段可表达 → FATAL
    cooldown_codes = {r["ts_code"] for r in rule13}
    for ts, mc in manual.items():
        if mc.get("manual_block") and ts not in cooldown_codes:
            if ts in held:
                raise ConvertError(
                    f"manual_controls {ts} 标了 manual_block，但你当前持有它；manual_block 用于阻止止损后"
                    "空仓再入，不适用于持仓（持仓由 positions 走持仓管理）")
            raise ConvertError(
                f"manual_controls {ts} 标了 manual_block，但该票没有止损冷静期、也未持有；通用「阻断任意"
                "空仓股」在 account_state schema 无字段可表达（S3a v1.1.0 仅放开 stop 可选，不含此），本切片不支持")
    return rule13, lineage


# ── 4.3-D 可选一致性检查：trades 净额 vs positions(advisory·WARN-only·绝不覆盖 positions)──────
def reconcile_trades_positions(trades: list, positions: list) -> list:
    """对账提醒:把 trades 按 ts_code 净额(BUY +、SELL −)与 positions.shares 对一下,差异 → WARN。
    **只提醒、不改任何东西**(positions 仍是权威,绝不用 trades 覆盖);best-effort——差异可能因历史成交
    不全 / 分红拆股 / 费用,属人工核对提示、非必然错误。trades 已在 `_build_rule13` 校验过(此处仅净额)。
    返回 [{ts_code, kind, message}, ...](无问题则空)。"""
    pos_by = {p["ts_code"]: p for p in positions}
    net = {}
    for r in trades:
        ts = _parse_ts_code(r.get("ts_code"), "trades.ts_code")
        side = (_opt_str(r.get("side")) or "").upper()
        shares = _parse_int_shares(r.get("shares"), "trades.shares")
        net[ts] = net.get(ts, 0) + (shares if side == "BUY" else -shares)
    warnings = []
    for ts in sorted(net):
        n = net[ts]
        pos = pos_by.get(ts)
        if pos is None:
            if n > 0:   # 净买入却没登记持仓(净卖出/=0 不在持仓 = 正常出场/Rule13,不提醒)
                warnings.append({"ts_code": ts, "kind": "net_buy_not_in_positions",
                                 "message": f"trades 净买入 {n} 股,但 positions 未登记 {ts}(可能漏登持仓,请核对)"})
        elif n != pos["shares"]:   # 仅对「有近期成交」的持仓做精确核对(无成交的旧持仓不在 net 里、不提醒)
            warnings.append({"ts_code": ts, "kind": "shares_mismatch",
                             "message": (f"{ts}:positions {pos['shares']} 股 vs trades 净额 {n} 股"
                                         f"(差 {pos['shares'] - n};可能因历史成交不全/分红拆股/费用,请核对,非必然错误)")})
    return warnings


# ── 薄 main：读 CSV → build → 既有 validator 兜底 → 原子写 json + lineage ──────────────
def _read_csv_table(path: Path, name: str) -> list:
    with open(path, encoding="utf-8-sig", newline="") as f:   # utf-8-sig：容忍用户用 Excel 存出的 BOM
        reader = csv.DictReader(f)
        header = [h.strip() for h in (reader.fieldnames or [])]
        missing = [c for c in REQUIRED_COLUMNS[name] if c not in header]
        if missing:
            raise ConvertError(f"{name}.csv 缺必需列：{missing}（表头={header}）")
        rows = []
        for raw in reader:
            rows.append({(k.strip() if k else k): v for k, v in raw.items()})
        return rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    os.replace(tmp, path)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="A-short 手工表格 → 原子 account bundle 转换器")
    p.add_argument("--input-dir", required=True,
                   help="含 account/positions/trades/manual_controls/portfolio_rule12.csv 五张必需表的目录")
    p.add_argument("--as-of", required=True, help="决策日 YYYYMMDD（= bundle.decision_as_of = 周报 --as-of）")
    p.add_argument("--out", required=True, help="输出原子 account bundle JSON 路径（内含 account + lineage）")
    p.add_argument("--lineage-out", help=argparse.SUPPRESS)
    p.add_argument("--allow-nonprivate-account-out", action="store_true",
                   help="显式允许把 account_state/lineage 写到仓库内非 gitignored 路径（默认拒，防账户隐私被提交泄漏）")
    args = p.parse_args(argv)
    if args.lineage_out:
        raise ConvertError("--lineage-out 已停用：account 与 lineage 必须作为同一个 bundle 原子发布")

    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        raise ConvertError(f"--input-dir 不存在或非目录：{input_dir}")

    tables = {}
    source_tables = []
    for name in REQUIRED_TABLES + OPTIONAL_TABLES:
        path = input_dir / f"{name}.csv"
        if not path.is_file():
            if name in REQUIRED_TABLES:
                raise ConvertError(f"缺必需表 {name}.csv（{path}）")
            tables[name] = []
            continue
        rows = _read_csv_table(path, name)
        tables[name] = rows
        source_tables.append({"name": name, "path": str(path).replace("\\", "/"),
                              "sha256": _sha256(path), "row_count": len(rows)})

    bundle = build_account_bundle(
        tables, args.as_of, _load_preset_config(), source_tables=source_tables,
        generated_at=datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))
    account_state, lineage = bundle["account"], bundle["lineage"]

    out_path = Path(args.out)
    # 隐私护栏(P0 修复):bundle 含真实 cash/positions/cost/stop/cooldown → 拒落仓库内 git 未忽略路径
    # (fail-fast,早于任何写盘);复用 weekly 同守门(git check-ignore 真值)。默认私密目录 = gitignored state/a_short/。
    from runners.a_short_weekly_pipeline import _reject_nonprivate_account_output_path
    _reject_nonprivate_account_output_path(str(out_path), True, args.allow_nonprivate_account_out)
    _write_json_atomic(out_path, bundle)

    _print_plain_summary(account_state, lineage)
    print(f"[OK] account bundle → {out_path} ({bundle['snapshot_id']})")
    return 0


def _load_preset_config() -> dict:
    """Read position_management overrides from presets/a_short.yaml (single source); fall back to defaults.

    Minimal YAML read (no PyYAML dependency): only the flat position_management block keys we need.
    """
    preset = ROOT / "presets" / "a_short.yaml"
    cfg = dict(DEFAULT_CONFIG)
    if not preset.is_file():
        return cfg
    in_block = False
    for line in preset.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\S", line):
            in_block = line.strip().startswith("position_management:")
            continue
        if not in_block:
            continue
        m = re.match(r"^\s+([a-z0-9_]+):\s*([0-9.]+)\s*(?:#.*)?$", line)
        if m and m.group(1) in DEFAULT_CONFIG:
            key, val = m.group(1), m.group(2)
            cfg[key] = int(val) if key == "rule13_cooldown_calendar_days" else float(val)
    return cfg


def _print_plain_summary(account_state: dict, lineage: dict) -> None:
    """大白话解释：这次表格里哪些事实导致了什么状态（满足 4.3 §11 大白话要求）。"""
    print(f"[4.3] 决策日 {account_state['as_of']}；事实截止 {lineage['facts_as_of']}"
          f"（{lineage['facts_staleness']}）。持仓 {len(account_state['positions'])} 只，"
          f"Rule12={account_state['rule12']['status']}，Rule13 冷静 {len(account_state['rule13_cooldowns'])} 只。")
    if lineage["facts_staleness"] == "stale_warning":
        print(f"[WARN] 事实截止日 {lineage['facts_as_of']} 早于决策日 {account_state['as_of']}："
              "可能漏了之后的成交/持仓变化，请确认表格已更新。")
    if lineage["rule12"]["progressed"]:
        pr = lineage["rule12"]["progressed"]
        print(f"  · Rule12 冷静期已过期，自动推进 {pr['from_status']}→{pr['to_status']}"
              f"（恢复首仓上限×{account_state['rule12']['recovery_position_multiplier']}）。")
    for cd, ln in zip(account_state["rule13_cooldowns"], lineage["rule13_cooldowns"]):
        src = "你 trades 表的止损卖出" if ln["source"] == "excel_trades" else "trades 止损 + manual_controls 复核"
        note = ""
        if ln["progressed"]:
            note = f"，已自动推进 {ln['progressed']['from_status']}→{ln['progressed']['to_status']}"
        if ln["manual_block_applied"]:
            note += "，并按你的 manual_block 强制保持阻断"
        print(f"  · {cd['ts_code']} 冷静期来自{src}：{cd['status']}（止损 {cd['exit_date']}，"
              f"冷静到 {cd['cooldown_until']}{note}）。")
    for w in (lineage.get("consistency_warnings") or []):     # 4.3-D 对账提醒(advisory,不改任何结论)
        print(f"[核对] {w['message']}")


if __name__ == "__main__":
    raise SystemExit(main())
