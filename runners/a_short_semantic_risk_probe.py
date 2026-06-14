#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-short 语义风险层 provider 可行性探针(Slice 1, probe-first, 不改生产).

正式 Slice-2 语义风险层(官方结构化 cninfo PIT 层 + Sina/web LLM advisory 层)要建在
**未治理** 的数据源上(无 token、有频率限制、字段/分类/反爬形态未证明)。本探针在投全量前
独立验证 provider 机制:字段是否齐、披露日能否解析(可 PIT 过滤)、返回的证券代码是否对得上
查询代码、覆盖率、失败形态——**只表征 provider 可行性,绝不据此对股票下任何风控结论**。

设计要点(对齐 `docs/a_short_semantic_risk_top15_enrichment_design_20260612.md` §3/§8 Slice 1):
- 覆盖对象 = EGS 周频候选 **观察池 Top15**,全程主板(复用 `is_a_share_main_board`,排创业板/科创板/
  北交所/B 股/畸形码)。
- **cninfo(官方结构化层)= 本探针的 gating 项**:headless POST `hisAnnouncement/query`,`stock` 参数
  须为 "代码,orgId"(orgId 从 cninfo 证券清单 JSON 解析;**首版 `执行` 发现仅"代码,sh/sz"会 200+空**,
  故改 orgId),按披露日可 PIT。`feasible`(总)== `cninfo.feasible`。
- **Sina/web(advisory 层)= LIVE-only**:headless 探针只做 best-effort 原始可达性检查
  (`--include-sina` opt-in),`pit_capable=false`,**绝不**作历史回测证据;完整 web+LLM 判断不在本探针
  (web 产出路径见契约 `docs/a_short_semantic_risk_contract.md` §web_llm 产出路径)。
- **失败 → `unknown`,绝不伪装 `clear`**:某代码 provider 调用失败 → 该代码 status=`unknown`;
  调用成功但窗口内无公告 → `clear_light`(真·查过、无事)。两者语义严格区分。
- 与 IV probe 的差别:IV probe 在 provider 异常时**中止不写**(否则"无访问"会被误读成"无期权")。
  本探针**逐代码失败是要采集的信号**(反爬/字段漂移/网络),计入失败形态、写进 summary;
  `feasible=false`(provider 不可行)是**诚实的负向探针结论**,不会被误读成"股票无风险"。
- **真取数 = 用户授权 `执行`**(`--confirm-fetch-authorized`)。不硬否决、不改 EGS scoring、
  不改 Phase5 decision、不做历史回测证据、不写 production 路径(`result/a_short` 被拒)。

纯函数 `assess_cninfo_feasibility` / `assess_sina_feasibility` / `validate_probe_summary_consistency`
(合成 fixture 可测);真实 HTTP 调用在 `fetch_*` / `main` 薄层。不动 production / egs_main / V14.2。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import jsonschema

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from engine.data.a_share_board_scope import is_a_share_main_board  # noqa: E402

SCHEMA_NAME = "a_short_semantic_risk_probe_summary"
SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = os.path.join(ROOT, "schemas", "a_short_semantic_risk_probe_summary.schema.json")

TOP15_CAP = 15
MIN_CNINFO_OK_CODES = 10
MIN_CNINFO_OK_RATIO = 0.6
MIN_CNINFO_ANNOUNCED_CODES = 3
MIN_SINA_OK_CODES = 8
MIN_SINA_OK_RATIO = 0.5
MIN_SINA_ITEM_CODES = 3

REQUIRED_CNINFO_FIELDS = ["announcementTitle", "adjunctUrl", "announcementTime", "secCode"]
# 用于验证"公告标题关键词能否映射监管风险"(探针只标 risk_candidate,**绝不据此否决**)。
REGULATOR_KEYWORDS = ["问询函", "立案调查", "监管关注", "警示函", "处罚", "诉讼", "仲裁",
                      "资金占用", "违规担保", "风险警示"]
SINA_ITEM_FIELDS = ["title", "url"]

CNINFO_QUERY_URL = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
# cninfo hisAnnouncement/query 的 `stock` 参数需 "代码,orgId";orgId 从 cninfo 的证券清单 JSON 解析。
# 端点/字段未治理 → 设默认 + 允许环境变量覆盖(逗号分隔多个 URL);best-effort,失败如实记。
CNINFO_ORGID_URLS = tuple(
    u.strip() for u in os.environ.get(
        "CNINFO_ORGID_URLS",
        "http://www.cninfo.com.cn/new/data/sse_stock.json,"
        "http://www.cninfo.com.cn/new/data/szse_stock.json",
    ).split(",") if u.strip()
)
# Sina 端点形态未证明 → 设默认 + 允许环境变量覆盖;best-effort,完整验证不在本探针(见契约 §web_llm 产出路径)。
SINA_NEWS_URL_TEMPLATE = os.environ.get(
    "SINA_NEWS_URL_TEMPLATE",
    "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=1686&num=10&k={symbol}",
)


# ── 日期工具 ──────────────────────────────────────────────────────────────────
def _is_canonical_date(value) -> bool:
    """严格 canonical YYYYMMDD:8 个 ASCII 数字 + strptime 合法 + strftime round-trip。"""
    s = str(value)
    if len(s) != 8 or not all(c in "0123456789" for c in s):
        return False
    try:
        dt = datetime.strptime(s, "%Y%m%d")
    except ValueError:
        return False
    return dt.strftime("%Y%m%d") == s


def _epoch_ms_to_date(ms) -> str | None:
    """epoch 毫秒 → Asia/Shanghai 日期 YYYYMMDD(cninfo announcementTime 为 ms)。"""
    try:
        v = int(ms)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    try:
        dt = datetime.fromtimestamp(v / 1000, tz=timezone(timedelta(hours=8)))
    except (OverflowError, OSError, ValueError):
        return None
    return dt.strftime("%Y%m%d")


def _parse_disclosure_date(value) -> str | None:
    """把 cninfo 披露时间字段解析成 canonical YYYYMMDD;无法解析 → None(字段漂移信号)。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return _epoch_ms_to_date(value)
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit() and len(s) >= 11:                  # epoch 毫秒(~13 位),区别于 8 位日期
        return _epoch_ms_to_date(s)
    if _is_canonical_date(s):
        return s
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    return None


# ── universe(主板 Top15 过滤)─────────────────────────────────────────────────
def main_board_top15(watch_pool, cap: int = TOP15_CAP):
    """把候选观察池过滤为主板 + 去重 + 截断 Top{cap}。返回 (main_board, dropped_non_main)。"""
    seen: set[str] = set()
    main: list[str] = []
    dropped: list[str] = []
    for code in (watch_pool or []):
        c = str(code).strip().upper()
        if not c or c in seen:
            continue
        seen.add(c)
        if is_a_share_main_board(c):
            if len(main) < cap:
                main.append(c)
        else:
            dropped.append(c)
    return main, dropped


# ── cninfo 逐代码分类 + 聚合(纯函数)──────────────────────────────────────────
def _ann_has_required_fields(ann: dict) -> bool:
    for f in REQUIRED_CNINFO_FIELDS:
        v = ann.get(f)
        if v is None or (isinstance(v, str) and not v.strip()):
            return False
    return True


def classify_cninfo_code(raw: dict, as_of: str) -> dict:
    """单代码 cninfo 原始结果 → 分类。**PIT 强制**:只有披露日 canonical 且 ≤ as_of 的公告才计入
    `n_announcements`/字段·映射判定/risk_candidate;未来日期行单列 `n_future_dated`,绝不助证据。
    失败 → status `unknown`(绝不 `clear`)。纯函数自行 PIT 把关,不信赖 fetcher 的取数窗口。

    每代码字段(`n_returned` 在 isinstance 过滤前对**原始返回行**计数,三类缺陷精确划分):
    - `n_returned`      = provider 返回的公告总行数(含非字典/不可解析/未来,**原始**计数)。
    - `n_announcements` = PIT 有效公告数(字典 + canonical 且 ≤ as_of)——"有公告"(announced)= 此 > 0。
    - `n_future_dated`  = 字典但披露日 > as_of 的行数(PIT 泄漏信号)。
    - `n_unparseable_dates` = 字典但披露日不可解析的行数(字段/日期形态不可靠信号)。
    - `n_bad_shape`     = 非字典的行数(provider 形态异常信号)。
      四者精确划分:`n_announcements + n_future_dated + n_unparseable_dates + n_bad_shape == n_returned`。
    - `dates_pit_ok`    = 返回行**全部**为字典 + canonical + ≤ as_of(无未来/不可解析/坏形态);n_returned=0 → None。
    - `required_fields_ok`/`code_mapping_ok` = 在 PIT 公告上判定;无 PIT 公告 → None。
    三类缺陷各有 provider 级聚合门(`n_future_dated_codes`/`n_unparseable_date_codes`/`n_bad_shape_codes` 全 0),
    任一非 0 → not feasible(坏行绝不能被报成 clean,也绝不能与 feasible=True 并存)。
    """
    as_of = str(as_of)
    ts_code = str(raw.get("ts_code", ""))
    symbol = ts_code.split(".", 1)[0]
    if not raw.get("ok"):
        return {"ts_code": ts_code, "ok": False,
                "error_category": raw.get("error_category") or "other",
                "n_returned": 0, "n_announcements": 0, "n_future_dated": 0,
                "n_unparseable_dates": 0, "n_bad_shape": 0,
                "required_fields_ok": None, "dates_pit_ok": None,
                "code_mapping_ok": None, "status": "unknown"}
    raw_list = raw.get("announcements") or []
    n_returned = len(raw_list)                          # 原始计数,先于 isinstance 过滤
    if n_returned == 0:
        return {"ts_code": ts_code, "ok": True, "error_category": None,
                "n_returned": 0, "n_announcements": 0, "n_future_dated": 0,
                "n_unparseable_dates": 0, "n_bad_shape": 0,
                "required_fields_ok": None, "dates_pit_ok": None,
                "code_mapping_ok": None, "status": "clear_light"}
    pit_anns: list[dict] = []
    n_future_dated = 0
    n_unparseable_dates = 0
    n_bad_shape = 0
    for a in raw_list:
        if not isinstance(a, dict):
            n_bad_shape += 1                            # 非字典行:形态异常,不静默丢弃
            continue
        d = _parse_disclosure_date(a.get("announcementTime"))
        if d is None:
            n_unparseable_dates += 1                    # 不可解析:形态不可靠,排除出证据
        elif d <= as_of:
            pit_anns.append(a)
        else:
            n_future_dated += 1                        # 未来日期:PIT 泄漏,排除出证据
    n_pit = len(pit_anns)
    dates_pit_ok = (n_pit == n_returned)               # 全部返回行都是字典 + canonical + ≤ as_of
    if n_pit > 0:
        required_fields_ok = all(_ann_has_required_fields(a) for a in pit_anns)
        code_mapping_ok = all(str(a.get("secCode", "")).strip() == symbol for a in pit_anns)
        risk_hit = any(kw in str(a.get("announcementTitle", ""))
                       for a in pit_anns for kw in REGULATOR_KEYWORDS)
    else:
        required_fields_ok = None
        code_mapping_ok = None
        risk_hit = False
    # status:`clear_light`/`risk_candidate` 只在**真正干净**时给(无 future/unparseable/非字典缺陷,
    # 且 PIT 行字段+映射有效);任何 provider 质量缺陷 → `unknown`(绝不伪装 clear)。此处 n_returned>0
    # (空窗口已提前 return clear_light)。
    quality_ok = (n_future_dated == 0 and n_unparseable_dates == 0 and n_bad_shape == 0
                  and n_pit > 0 and bool(required_fields_ok) and bool(code_mapping_ok))
    if not quality_ok:
        status = "unknown"
    elif risk_hit:
        status = "risk_candidate"
    else:
        status = "clear_light"
    return {"ts_code": ts_code, "ok": True, "error_category": None,
            "n_returned": n_returned, "n_announcements": n_pit, "n_future_dated": n_future_dated,
            "n_unparseable_dates": n_unparseable_dates, "n_bad_shape": n_bad_shape,
            "required_fields_ok": (None if required_fields_ok is None else bool(required_fields_ok)),
            "dates_pit_ok": bool(dates_pit_ok),
            "code_mapping_ok": (None if code_mapping_ok is None else bool(code_mapping_ok)),
            "status": status}


def _tally_failures(classified: list[dict]) -> dict:
    cats: dict[str, int] = {}
    for c in classified:
        if not c["ok"]:
            cat = c.get("error_category") or "other"
            cats[cat] = cats.get(cat, 0) + 1
    return cats


def assess_cninfo_feasibility(per_code_raw: list[dict], as_of: str) -> dict:
    """聚合 cninfo provider 可行性。feasible 须有真实成功证据(够的代码 + 够的有公告代码 +
    字段/披露日/代码映射在有公告代码上全 OK);任何门不达标 → not feasible + reason。"""
    as_of = str(as_of)
    as_of_is_valid_date = _is_canonical_date(as_of)
    classified = [classify_cninfo_code(r, as_of) for r in (per_code_raw or [])]
    n_requested = len(classified)
    n_ok = sum(1 for c in classified if c["ok"])
    n_failed = n_requested - n_ok
    announced = [c for c in classified if c["ok"] and c["n_announcements"] > 0]
    n_announced = len(announced)
    n_future_dated_codes = sum(1 for c in classified if c["n_future_dated"] > 0)
    n_unparseable_date_codes = sum(1 for c in classified if c["n_unparseable_dates"] > 0)
    n_bad_shape_codes = sum(1 for c in classified if c["n_bad_shape"] > 0)
    n_required_fields_ok = sum(1 for c in announced if c["required_fields_ok"] is True)
    n_dates_pit_ok = sum(1 for c in announced if c["dates_pit_ok"] is True)
    n_code_mapping_ok = sum(1 for c in announced if c["code_mapping_ok"] is True)
    n_risk_candidate = sum(1 for c in classified if c["status"] == "risk_candidate")
    ok_ratio = round(n_ok / n_requested, 6) if n_requested else 0.0

    reasons: list[str] = []
    if not as_of_is_valid_date:
        reasons.append(f"as_of {as_of} 不是合法日历日期")
    if n_ok < MIN_CNINFO_OK_CODES:
        reasons.append(f"成功响应代码数 {n_ok} < {MIN_CNINFO_OK_CODES}(provider 不够可达)")
    if ok_ratio < MIN_CNINFO_OK_RATIO:
        reasons.append(f"成功率 {ok_ratio:.2f} < {MIN_CNINFO_OK_RATIO}(疑似反爬/封锁)")
    if n_announced < MIN_CNINFO_ANNOUNCED_CODES:
        reasons.append(f"有 PIT 公告代码数 {n_announced} < {MIN_CNINFO_ANNOUNCED_CODES}(无法验证字段/日期/映射形态)")
    if n_future_dated_codes:
        reasons.append(f"{n_future_dated_codes} 个代码返回未来日期公告(>as_of)→ PIT 不可信(future 行已排除出证据)")
    if n_unparseable_date_codes:
        reasons.append(f"{n_unparseable_date_codes} 个代码返回不可解析披露日 → 字段/日期形态不可靠")
    if n_bad_shape_codes:
        reasons.append(f"{n_bad_shape_codes} 个代码返回非字典公告行 → provider 形态异常")
    if n_announced and n_required_fields_ok < n_announced:
        reasons.append(f"字段齐全代码 {n_required_fields_ok}/{n_announced}(字段漂移)")
    if n_announced and n_dates_pit_ok < n_announced:
        reasons.append(f"披露日 PIT 干净代码 {n_dates_pit_ok}/{n_announced}(含未来日期/不可解析)")
    if n_announced and n_code_mapping_ok < n_announced:
        reasons.append(f"代码映射正确代码 {n_code_mapping_ok}/{n_announced}(secCode 对不上,会误挂风险)")

    feasible = (
        as_of_is_valid_date
        and n_ok >= MIN_CNINFO_OK_CODES
        and ok_ratio >= MIN_CNINFO_OK_RATIO
        and n_announced >= MIN_CNINFO_ANNOUNCED_CODES
        and n_future_dated_codes == 0
        and n_unparseable_date_codes == 0
        and n_bad_shape_codes == 0
        and n_required_fields_ok == n_announced
        and n_dates_pit_ok == n_announced
        and n_code_mapping_ok == n_announced
    )
    return {
        "as_of_is_valid_date": bool(as_of_is_valid_date),
        "n_requested": n_requested, "n_ok": n_ok, "n_failed": n_failed,
        "n_announced": n_announced, "n_future_dated_codes": n_future_dated_codes,
        "n_unparseable_date_codes": n_unparseable_date_codes, "n_bad_shape_codes": n_bad_shape_codes,
        "n_required_fields_ok": n_required_fields_ok,
        "n_dates_pit_ok": n_dates_pit_ok, "n_code_mapping_ok": n_code_mapping_ok,
        "n_risk_candidate": n_risk_candidate, "ok_ratio": ok_ratio,
        "failure_categories": _tally_failures(classified),
        "per_code": classified, "feasible": bool(feasible), "reasons": reasons,
    }


# ── Sina 逐代码分类 + 聚合(纯函数,LIVE-only)─────────────────────────────────
def classify_sina_code(raw: dict) -> dict:
    """单代码 Sina 原始结果 → 分类。失败 → `unknown`;成功无条目 → `clear_light`;有条目 → `items_found`。"""
    ts_code = str(raw.get("ts_code", ""))
    if not raw.get("ok"):
        return {"ts_code": ts_code, "ok": False,
                "error_category": raw.get("error_category") or "other",
                "n_items": 0, "fields_ok": None, "status": "unknown"}
    items = [it for it in (raw.get("items") or []) if isinstance(it, dict)]
    n = len(items)
    if n == 0:
        return {"ts_code": ts_code, "ok": True, "error_category": None,
                "n_items": 0, "fields_ok": None, "status": "clear_light"}
    fields_ok = all(all(it.get(f) not in (None, "") for f in SINA_ITEM_FIELDS) for it in items)
    return {"ts_code": ts_code, "ok": True, "error_category": None,
            "n_items": n, "fields_ok": bool(fields_ok), "status": "items_found"}


def assess_sina_feasibility(per_code_raw: list[dict], as_of: str) -> dict:
    """聚合 Sina(LIVE-only advisory)原始可达性。pit_capable 恒 false。"""
    as_of = str(as_of)
    as_of_is_valid_date = _is_canonical_date(as_of)
    classified = [classify_sina_code(r) for r in (per_code_raw or [])]
    n_requested = len(classified)
    n_ok = sum(1 for c in classified if c["ok"])
    n_failed = n_requested - n_ok
    with_items = [c for c in classified if c["ok"] and c["n_items"] > 0]
    n_with_items = len(with_items)
    n_fields_ok = sum(1 for c in with_items if c["fields_ok"] is True)
    ok_ratio = round(n_ok / n_requested, 6) if n_requested else 0.0

    reasons: list[str] = []
    if not as_of_is_valid_date:
        reasons.append(f"as_of {as_of} 不是合法日历日期")
    if n_requested == 0:
        reasons.append("Sina 探针未运行(best-effort,--include-sina opt-in;web+LLM advisory 不在本探针,见契约 §web_llm 产出路径)")
    else:
        if n_ok < MIN_SINA_OK_CODES:
            reasons.append(f"成功响应代码数 {n_ok} < {MIN_SINA_OK_CODES}")
        if ok_ratio < MIN_SINA_OK_RATIO:
            reasons.append(f"成功率 {ok_ratio:.2f} < {MIN_SINA_OK_RATIO}")
        if n_with_items < MIN_SINA_ITEM_CODES:
            reasons.append(f"有条目代码数 {n_with_items} < {MIN_SINA_ITEM_CODES}")
        if n_with_items and n_fields_ok < n_with_items:
            reasons.append(f"字段齐全代码 {n_fields_ok}/{n_with_items}")

    feasible = (
        as_of_is_valid_date
        and n_requested > 0
        and n_ok >= MIN_SINA_OK_CODES
        and ok_ratio >= MIN_SINA_OK_RATIO
        and n_with_items >= MIN_SINA_ITEM_CODES
        and n_fields_ok == n_with_items
    )
    return {
        "as_of_is_valid_date": bool(as_of_is_valid_date), "pit_capable": False,
        "n_requested": n_requested, "n_ok": n_ok, "n_failed": n_failed,
        "n_with_items": n_with_items, "n_fields_ok": n_fields_ok, "ok_ratio": ok_ratio,
        "failure_categories": _tally_failures(classified),
        "per_code": classified, "feasible": bool(feasible), "reasons": reasons,
    }


# ── summary 组装 + 一致性硬门 ─────────────────────────────────────────────────
def build_probe_summary(universe: dict, cninfo: dict, sina: dict,
                        as_of: str, generated_at: str) -> dict:
    return {
        "schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at, "as_of": as_of,
        "universe": {
            "requested": list(universe.get("requested", [])),
            "main_board_top15": list(universe.get("main_board_top15", [])),
            "dropped_non_main": list(universe.get("dropped_non_main", [])),
        },
        "thresholds": {
            "min_cninfo_ok_codes": MIN_CNINFO_OK_CODES,
            "min_cninfo_ok_ratio": MIN_CNINFO_OK_RATIO,
            "min_cninfo_announced_codes": MIN_CNINFO_ANNOUNCED_CODES,
            "required_cninfo_fields": list(REQUIRED_CNINFO_FIELDS),
            "regulator_keywords": list(REGULATOR_KEYWORDS),
            "min_sina_ok_codes": MIN_SINA_OK_CODES,
            "min_sina_ok_ratio": MIN_SINA_OK_RATIO,
            "min_sina_item_codes": MIN_SINA_ITEM_CODES,
        },
        "cninfo": cninfo,
        "sina": sina,
        "feasible": bool(cninfo["feasible"]),       # 总可行性 = 结构化层(gating)
        "boundary": {
            "production": False, "real_money": False, "hard_veto": False,
            "changes_egs_scoring": False, "changes_phase5_decision": False,
            "historical_backtest_evidence": False, "writes_production_path": False,
        },
    }


def _check_provider_counts(a: dict, *, is_cninfo: bool) -> None:
    if a["n_ok"] + a["n_failed"] != a["n_requested"]:
        raise ValueError("n_ok + n_failed != n_requested")
    if a["n_requested"]:
        expect = round(a["n_ok"] / a["n_requested"], 6)
        if abs(a["ok_ratio"] - expect) > 1e-6:
            raise ValueError("ok_ratio 与 n_ok/n_requested 不一致")
    elif a["ok_ratio"] != 0.0:
        raise ValueError("n_requested=0 时 ok_ratio 必须为 0")
    # 逐代码状态不变式:传输失败 ⇒ unknown(绝不伪装 clear/risk/items);反向 ⇒ 非 unknown 状态必须 ok。
    # cninfo 允许 ok=True 但 status=unknown(provider 质量缺陷,见下 is_cninfo 块);sina 无质量缺陷态,
    # ok 调用必为 clear_light/items_found。
    for c in a["per_code"]:
        if not c["ok"] and c["status"] != "unknown":
            raise ValueError(f"{c['ts_code']}: 传输失败必须为 unknown,不得伪装 clear/risk/items")
        if not is_cninfo and c["ok"] and c["status"] == "unknown":
            raise ValueError(f"{c['ts_code']}: sina 成功调用不应为 unknown")
    sum_failed = sum(1 for c in a["per_code"] if not c["ok"])
    if sum_failed != a["n_failed"]:
        raise ValueError("per_code 失败数与 n_failed 不一致")
    sum_failcat = sum(a["failure_categories"].values())
    if sum_failcat != a["n_failed"]:
        raise ValueError("failure_categories 总数与 n_failed 不一致")
    if is_cninfo:
        announced = [c for c in a["per_code"] if c["ok"] and c["n_announcements"] > 0]
        if len(announced) != a["n_announced"]:
            raise ValueError("n_announced 与 per_code 不一致")
        for cnt, key in (("n_future_dated", "n_future_dated_codes"),
                         ("n_unparseable_dates", "n_unparseable_date_codes"),
                         ("n_bad_shape", "n_bad_shape_codes")):
            if sum(1 for c in a["per_code"] if c[cnt] > 0) != a[key]:
                raise ValueError(f"{key} 与 per_code 不一致")
        for c in a["per_code"]:
            has_pit = c["ok"] and c["n_announcements"] > 0
            if (c["required_fields_ok"] is not None) != has_pit:
                raise ValueError(f"{c['ts_code']}: 字段/映射判定应仅当有 PIT 公告时存在")
            if (c["code_mapping_ok"] is not None) != has_pit:
                raise ValueError(f"{c['ts_code']}: 字段/映射判定应仅当有 PIT 公告时存在")
            has_returned = c["ok"] and c["n_returned"] > 0
            if (c["dates_pit_ok"] is not None) != has_returned:
                raise ValueError(f"{c['ts_code']}: dates_pit_ok 应仅当有返回公告时存在")
            # 精确划分:PIT + future + unparseable + bad_shape == n_returned
            if c["n_announcements"] + c["n_future_dated"] + c["n_unparseable_dates"] \
                    + c["n_bad_shape"] != c["n_returned"]:
                raise ValueError(f"{c['ts_code']}: 公告分类计数和 != n_returned")
            clean = (c["n_future_dated"] == 0 and c["n_unparseable_dates"] == 0
                     and c["n_bad_shape"] == 0)
            if c["ok"] and c["n_returned"] > 0 and c["dates_pit_ok"] != clean:
                raise ValueError(f"{c['ts_code']}: dates_pit_ok 必须等于'返回行全干净'")
            # status 质量不变式:clear_light/risk_candidate 只许 真正干净 的 ok 代码
            # (无 future/unparseable/非字典缺陷,且 PIT 行字段+映射有效);否则必须 unknown。
            if c["status"] in ("clear_light", "risk_candidate"):
                if not c["ok"]:
                    raise ValueError(f"{c['ts_code']}: clear/risk 必须 ok")
                if not clean:
                    raise ValueError(f"{c['ts_code']}: 有质量缺陷的代码不得报 clear/risk(应 unknown)")
                if c["n_announcements"] > 0 and not (c["required_fields_ok"] and c["code_mapping_ok"]):
                    raise ValueError(f"{c['ts_code']}: clear/risk 要求 PIT 行字段+映射有效")
            if c["status"] == "risk_candidate" and c["n_announcements"] == 0:
                raise ValueError(f"{c['ts_code']}: risk_candidate 需有 PIT 公告")
        if a["n_required_fields_ok"] > a["n_announced"] or a["n_dates_pit_ok"] > a["n_announced"] \
                or a["n_code_mapping_ok"] > a["n_announced"]:
            raise ValueError("字段/日期/映射 OK 数不能超过 n_announced")
    else:
        if a["pit_capable"] is not False:
            raise ValueError("Sina pit_capable 必须为 False(LIVE-only,不可作 PIT/回测证据)")
        with_items = [c for c in a["per_code"] if c["ok"] and c["n_items"] > 0]
        if len(with_items) != a["n_with_items"]:
            raise ValueError("n_with_items 与 per_code 不一致")
        if a["n_fields_ok"] > a["n_with_items"]:
            raise ValueError("n_fields_ok 不能超过 n_with_items")


def validate_probe_summary_consistency(summary: dict) -> None:
    """顶层/子层不矛盾 + 逐代码失败→unknown 不变式 + universe 主板 + feasible⇒门全过(防手搓虚报)。"""
    if bool(summary["feasible"]) != bool(summary["cninfo"]["feasible"]):
        raise ValueError("顶层 feasible 必须等于 cninfo.feasible")
    if not _is_canonical_date(summary["as_of"]):
        raise ValueError("as_of 非合法 canonical 日历日期")

    uni = summary["universe"]
    main = uni["main_board_top15"]
    if len(main) > TOP15_CAP:
        raise ValueError("main_board_top15 超过 15")
    if any(not is_a_share_main_board(c) for c in main):
        raise ValueError("main_board_top15 含非主板代码")
    if any(is_a_share_main_board(c) for c in uni["dropped_non_main"]):
        raise ValueError("dropped_non_main 含本应保留的主板代码")
    if set(main) & set(uni["dropped_non_main"]):
        raise ValueError("main_board_top15 与 dropped_non_main 不应重叠")

    cninfo = summary["cninfo"]
    sina = summary["sina"]
    if cninfo["as_of_is_valid_date"] != _is_canonical_date(summary["as_of"]):
        raise ValueError("cninfo.as_of_is_valid_date 与 as_of 不一致")
    if sina["as_of_is_valid_date"] != _is_canonical_date(summary["as_of"]):
        raise ValueError("sina.as_of_is_valid_date 与 as_of 不一致")
    _check_provider_counts(cninfo, is_cninfo=True)
    _check_provider_counts(sina, is_cninfo=False)

    # cninfo 是 gating 提供方:probe 的 universe 与 cninfo 探测代码集必须一致(否则 feasible 无意义)
    if cninfo["n_requested"] != len(main):
        raise ValueError("cninfo.n_requested 必须等于 main_board_top15 数(探测对象=主板 Top15)")

    if summary["feasible"]:
        if cninfo["reasons"]:
            raise ValueError("feasible=true 却携带 cninfo blocking reasons")
        gates = [
            cninfo["as_of_is_valid_date"],
            cninfo["n_ok"] >= MIN_CNINFO_OK_CODES,
            cninfo["ok_ratio"] >= MIN_CNINFO_OK_RATIO,
            cninfo["n_announced"] >= MIN_CNINFO_ANNOUNCED_CODES,
            cninfo["n_future_dated_codes"] == 0,
            cninfo["n_unparseable_date_codes"] == 0,
            cninfo["n_bad_shape_codes"] == 0,
            cninfo["n_required_fields_ok"] == cninfo["n_announced"],
            cninfo["n_dates_pit_ok"] == cninfo["n_announced"],
            cninfo["n_code_mapping_ok"] == cninfo["n_announced"],
        ]
        if not all(gates):
            raise ValueError("feasible=true 但 cninfo 有门未达标")


# ── 写盘(schema + consistency + production-path guard + 原子写)────────────────
def _guard_out_path(out_path: str) -> None:
    norm = os.path.normpath(os.path.abspath(out_path)).replace("\\", "/").lower()
    if "/result/a_short/" in norm or norm.endswith("/result/a_short"):
        raise ValueError("拒绝写入 result/a_short(生产路径);probe 产物须落 research lane")


def write_probe_summary(summary: dict, out_path: str) -> None:
    _guard_out_path(out_path)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(summary, schema)
    validate_probe_summary_consistency(summary)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


# ── 取数薄层(执行期,sanitized 错误)──────────────────────────────────────────
def _categorize_error(exc) -> str:
    """粗分类(sanitized:只给类别,不外泄 url/raw 行)。"""
    msg = str(exc).lower()
    if any(k in msg for k in ("forbidden", "403", "captcha", "blocked", "反爬", "拒绝")):
        return "anti_scrape"
    if any(k in msg for k in ("timeout", "connection", "network", "ssl", "max retries", "超时")):
        return "network"
    if any(k in msg for k in ("json", "decode", "expecting value", "解析")):
        return "parse_or_field_drift"
    return "other"


def _cninfo_payload(symbol: str, org_id: str, market: str, start: str, end: str) -> dict:
    return {
        "stock": f"{symbol},{org_id}", "tabName": "fulltext", "pageSize": 30, "pageNum": 1,
        "column": "szse" if market == "sz" else "sse", "category": "", "plate": market,
        "seDate": f"{start[:4]}-{start[4:6]}-{start[6:]} ~ {end[:4]}-{end[4:6]}-{end[6:]}",
        "searchkey": "", "secid": "", "sortName": "", "sortType": "", "isHLtitle": True,
    }


def fetch_cninfo_orgid_map(session=None, urls=None) -> tuple[dict, bool]:
    """从 cninfo 证券清单 JSON 解析 {6位代码: orgId}。返回 (map, fetched_ok)。
    任一 URL 成功解析即 fetched_ok=True;全失败 → ({}, False)(供上层把全部代码记 orgid_map_failed,
    区别于 fetched_ok=True 但某代码缺 orgId 的 no_orgid)。形态未治理 → 防御式解析,异常吞掉转下一个 URL。"""
    import requests
    sess = session or requests
    mapping: dict[str, str] = {}
    fetched_ok = False
    for url in (urls or CNINFO_ORGID_URLS):
        try:
            resp = sess.get(url, headers=_CNINFO_HEADERS, timeout=15)
            if resp.status_code != 200:
                continue
            rows = resp.json().get("stockList") or []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                code = str(row.get("code", "")).strip()
                org = str(row.get("orgId", "")).strip()
                if code and org:
                    mapping[code] = org
            fetched_ok = True
        except Exception:  # noqa: BLE001 (orgId 清单端点未治理;失败转下一个 URL,最终由 fetched_ok 反映)
            continue
    return mapping, fetched_ok


_CNINFO_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "http://www.cninfo.com.cn/new/disclosure/stock",
}


def fetch_cninfo(codes, as_of: str, lookback_days: int = 90, session=None,
                 request_delay: float = 0.3) -> list[dict]:
    """执行期:先解析 orgId 清单,再逐主板代码 POST cninfo hisAnnouncement/query(`stock`="代码,orgId";
    窗口 [as_of-lookback, as_of],PIT)。返回逐代码原始结果(ok/error_category/announcements)。
    失败语义分层:orgId 清单整体取不到 → 全部 `orgid_map_failed`;清单取到但某代码缺 orgId → 该代码
    `no_orgid`;HTTP 403/429 → `anti_scrape`;其余异常 → 分类。逐代码失败是要采集的探针信号。
    `request_delay` 在每次 POST 后小睡(默认 0.3s)以缓解 cninfo 对快速顺序请求的软反爬(返 200+空)。"""
    import time

    import requests
    sess = session or requests
    start = (datetime.strptime(as_of, "%Y%m%d") - timedelta(days=lookback_days)).strftime("%Y%m%d")
    orgid_map, map_ok = fetch_cninfo_orgid_map(sess)
    results: list[dict] = []
    for ts_code in codes:
        symbol = str(ts_code).split(".", 1)[0]
        if not map_ok:
            results.append({"ts_code": ts_code, "ok": False,
                            "error_category": "orgid_map_failed", "announcements": []})
            continue
        org_id = orgid_map.get(symbol)
        if not org_id:
            results.append({"ts_code": ts_code, "ok": False,
                            "error_category": "no_orgid", "announcements": []})
            continue
        market = "sz" if str(ts_code).upper().endswith(".SZ") else "sh"
        try:
            resp = sess.post(CNINFO_QUERY_URL,
                             data=_cninfo_payload(symbol, org_id, market, start, as_of),
                             headers=_CNINFO_HEADERS, timeout=10)
            if resp.status_code != 200:
                cat = "anti_scrape" if resp.status_code in (403, 429) else "network"
                results.append({"ts_code": ts_code, "ok": False, "error_category": cat,
                                "announcements": []})
            else:
                anns = resp.json().get("announcements") or []
                results.append({"ts_code": ts_code, "ok": True, "error_category": None,
                                "announcements": anns})
        except Exception as exc:  # noqa: BLE001 (逐代码失败是要采集的探针信号)
            results.append({"ts_code": ts_code, "ok": False,
                            "error_category": _categorize_error(exc), "announcements": []})
        if request_delay:
            time.sleep(request_delay)
    return results


def _sina_market_symbol(ts_code) -> str:
    """ts_code → Sina 风格 market 前缀代码(sh600519 / sz000001)。"""
    code = str(ts_code)
    sym = code.split(".", 1)[0]
    pref = "sz" if code.upper().endswith(".SZ") else "sh"
    return f"{pref}{sym}"


def _normalize_sina_item(it) -> dict | None:
    """把 Sina 新闻条目(键名不一)归一为 {title,url,published_at};缺 title/url → None。
    形态未治理 → 多键名 fallback;真实端点/键名留 `执行` 实测(完整 web 判断不在本探针,见契约 §web_llm 产出路径)。"""
    if not isinstance(it, dict):
        return None
    title = next((str(it[k]) for k in ("title", "stitle", "t", "wapsummary") if it.get(k)), "")
    url = next((str(it[k]) for k in ("url", "surl", "u", "link") if it.get(k)), "")
    published = next((str(it[k]) for k in ("ctime", "intime", "mtime", "datetime", "pub_date")
                      if it.get(k)), None)
    if not title or not url:
        return None
    return {"title": title, "url": url, "published_at": published}


def fetch_sina(codes, session=None) -> list[dict]:
    """执行期(best-effort,LIVE-only):逐代码 GET Sina 新闻条目,market 前缀代码 + 防御式键名归一。
    端点/键名未治理 → 形态实测留 `执行`;完整 web+LLM 判断不在本探针(见契约 §web_llm 产出路径),本函数只喂原始 sources。"""
    import requests
    sess = session or requests
    results: list[dict] = []
    for ts_code in codes:
        url = SINA_NEWS_URL_TEMPLATE.format(symbol=_sina_market_symbol(ts_code))
        try:
            resp = sess.get(url, timeout=10)
            if resp.status_code != 200:
                cat = "anti_scrape" if resp.status_code in (403, 429) else "network"
                results.append({"ts_code": ts_code, "ok": False, "error_category": cat, "items": []})
                continue
            data = resp.json()
            raw = (data.get("result", {}).get("data") if isinstance(data, dict) else None) \
                or (data.get("list") if isinstance(data, dict) else None) \
                or (data.get("data") if isinstance(data, dict) else None) or []
            items = [n for n in (_normalize_sina_item(x) for x in raw if isinstance(raw, list)) if n]
            results.append({"ts_code": ts_code, "ok": True, "error_category": None, "items": items})
        except Exception as exc:  # noqa: BLE001
            results.append({"ts_code": ts_code, "ok": False,
                            "error_category": _categorize_error(exc), "items": []})
    return results


def _load_watch_pool(spec: str) -> list[str]:
    """`@path.json`(JSON list)或逗号分隔代码串。"""
    if spec.startswith("@"):
        with open(spec[1:], "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise SystemExit("[FATAL] --watch-pool 文件须是 JSON 数组")
        return [str(x) for x in data]
    return [c for c in (s.strip() for s in spec.split(",")) if c]


def main(argv=None, cninfo_fetcher=None, sina_fetcher=None):
    p = argparse.ArgumentParser(description="A-short 语义风险层 provider 可行性探针(Slice 1, probe-first)")
    p.add_argument("--as-of", required=True, help="YYYYMMDD")
    p.add_argument("--watch-pool", required=True,
                   help="主板 Top15 候选:逗号分隔 ts_code,或 @path 指向 JSON 数组")
    p.add_argument("--out", required=True, help="probe summary 落点(禁 result/a_short)")
    p.add_argument("--confirm-fetch-authorized", action="store_true",
                   help="确认用户已授权本次 cninfo(+可选 Sina)真实 HTTP 探测调用")
    p.add_argument("--include-sina", action="store_true",
                   help="best-effort Sina 原始可达性探测(LIVE-only,默认关闭)")
    p.add_argument("--cninfo-lookback-days", type=int, default=90)
    args = p.parse_args(argv)

    if not args.confirm_fetch_authorized:
        raise SystemExit("[FATAL] 需 --confirm-fetch-authorized:本 probe 会真实抓取 cninfo/Sina,须用户授权")
    if not _is_canonical_date(args.as_of):
        raise SystemExit(f"[FATAL] --as-of {args.as_of} 不是合法日历日期")
    _guard_out_path(args.out)              # 取数前先挡掉生产路径,别白抓

    requested = _load_watch_pool(args.watch_pool)
    main_codes, dropped = main_board_top15(requested)
    print(f"[probe] universe: requested={len(requested)} → main-board Top15={len(main_codes)} "
          f"(dropped non-main={len(dropped)})")
    if not main_codes:
        print("[probe] WARNING: 观察池无主板代码,写 not-feasible summary")

    cf = cninfo_fetcher or fetch_cninfo
    cninfo_raw = cf(main_codes, args.as_of, args.cninfo_lookback_days)
    cninfo = assess_cninfo_feasibility(cninfo_raw, args.as_of)

    if args.include_sina:
        sf = sina_fetcher or fetch_sina
        sina_raw = sf(main_codes)
    else:
        sina_raw = []
    sina = assess_sina_feasibility(sina_raw, args.as_of)

    universe = {"requested": requested, "main_board_top15": main_codes, "dropped_non_main": dropped}
    summary = build_probe_summary(universe, cninfo, sina, args.as_of,
                                  datetime.now().astimezone().isoformat(timespec="seconds"))
    write_probe_summary(summary, args.out)
    print(f"[probe] cninfo: ok={cninfo['n_ok']}/{cninfo['n_requested']} announced={cninfo['n_announced']} "
          f"risk_candidate={cninfo['n_risk_candidate']} feasible={cninfo['feasible']} "
          f"failures={cninfo['failure_categories']}")
    print(f"[probe] cninfo reasons={cninfo['reasons']}")
    print(f"[probe] sina(best-effort,LIVE-only): ok={sina['n_ok']}/{sina['n_requested']} "
          f"items={sina['n_with_items']} feasible={sina['feasible']}")
    print(f"[probe] overall feasible(=cninfo)={summary['feasible']} → summary {args.out}")


if __name__ == "__main__":
    main()
