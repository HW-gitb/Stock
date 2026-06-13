#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-short 语义风险 advisory summary — Slice 2a(headless 结构化骨架,非生产).

在主板 Top15 观察池上产出 `a_short_semantic_risk_summary`(独立 advisory 产物,落 research lane)。
两层严格分置信:
- **official_structured(官方结构化层)= 本切片 headless 填**:复用 Slice-1 已验证的 cninfo orgId 取数,
  按披露日 **PIT**(canonical 且 ≤ as_of)过滤,标题→risk_type 映射,产出带证据的风险事件。
  status:`risk`(有 PIT 风险事件)/ `clear`(查过、无风险事件、无质量缺陷)/ `unknown`(取数失败 **或**
  有未来/不可解析/非字典/代码错配等质量缺陷——**绝不把不可信当 clear**;但 PIT 干净行里**真命中风险则
  优先报 risk**)。
- **web_llm(Sina/web LLM advisory 层)= skill 在环,本切片留 `unknown`**:headless 跑不了 web+LLM 判断,
  2b 由 skill 填 status/risk_level/action;本切片仅 best-effort 把 Sina 原始条目喂进 `sources`(不判定、
  不设 clear)。

**advisory-only 边界(硬约束)**:绝不硬否决、不进 production scoring/decision/veto、不做历史回测证据、
不写 production 路径、unknown 不伪装 clear、web/LLM 不与官方结构化混同一置信。真取数 = `--confirm-fetch-authorized`
(用户 `执行`)。纯 build/validate 核心可测;不动 egs_main / Phase5 / V14.2。Slice 2b 出 skill 契约 + 面板渲染 +
CI 守护(advisory 层已存在 ⇒ 强制 Slice 3 reconciliation;见 tests）。
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jsonschema  # noqa: E402

from engine.data.a_share_board_scope import is_a_share_main_board  # noqa: E402
from runners.a_short_semantic_risk_probe import (  # noqa: E402
    main_board_top15, fetch_cninfo, fetch_sina, _parse_disclosure_date,
    _is_canonical_date, _guard_out_path, _load_watch_pool, TOP15_CAP,
    MIN_CNINFO_ANNOUNCED_CODES,
)

# 批量 cninfo sanity:Top15 里有 PIT 公告的代码数低于此门槛 = 疑似 200+空(请求形态/软反爬),
# 此时空窗口(n_pit=0)的 clear 必须降级 unknown(fail-closed),绝不把批量空壳报成全员无风险。
# 复用探针 MIN_CNINFO_ANNOUNCED_CODES;小批量(候选数<门槛)则要求全部有公告才算健康。
MIN_BATCH_ANNOUNCED = MIN_CNINFO_ANNOUNCED_CODES

SCHEMA_NAME = "a_short_semantic_risk_summary"
SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = os.path.join(ROOT, "schemas", "a_short_semantic_risk_summary.schema.json")
PATCH_SCHEMA_NAME = "a_short_semantic_risk_web_llm_patch"
PATCH_SCHEMA_PATH = os.path.join(ROOT, "schemas", "a_short_semantic_risk_web_llm_patch.schema.json")
DEEP_RANK_MAX = 5
CNINFO_STATIC_HOST = "http://static.cninfo.com.cn/"

# 标题关键词 → (category, risk_type, severity)。首个命中的关键词决定分类(顺序=高 severity 在前=优先级)。
# severity:high(立案/处罚/ST 严重事件)/ medium(监管函件·关注·资金占用·担保 真问题)/ low(诉讼仲裁,
# 大公司常为例行)。Slice-2a 执行实测发现宽关键词假阳性(银行年报季"非经营性资金占用…专项说明"=例行合规件
# 命中 资金占用),故 Slice-2b 加负向模式 + 分级粗筛;实质精判仍交 2b skill(web_llm)。
RISK_KEYWORD_MAP = [
    ("立案调查", "立案调查", "investigation", "high"),
    ("立案", "立案调查", "investigation", "high"),
    ("行政处罚", "处罚", "penalty", "high"),
    ("处罚", "处罚", "penalty", "high"),
    ("风险警示", "风险警示", "risk_warning", "high"),
    ("问询函", "监管函件", "regulatory_inquiry", "medium"),
    ("关注函", "监管函件", "regulatory_inquiry", "medium"),
    ("监管关注", "监管关注", "regulatory_attention", "medium"),
    ("警示函", "警示函", "warning_letter", "medium"),
    ("资金占用", "资金占用", "fund_occupation", "medium"),
    ("违规担保", "违规担保", "irregular_guarantee", "medium"),
    ("诉讼", "诉讼仲裁", "litigation", "low"),
    ("仲裁", "诉讼仲裁", "litigation", "low"),
]

# 例行年报"资金占用情况"的法定披露形式(审计师/独董专项说明·专项审核报告·关联资金往来情况汇总表)。
ROUTINE_OCCUPATION_FORMS = ("专项说明", "专项审核", "汇总表")
# 明确"无占用"否定式:标题里明示不存在/未发生/无新增占用 = 真·无风险的例行件,headless 可安全抑制。
NO_OCCUPATION_NEGATIONS = ("不存在", "未发生", "未形成", "无新增", "未出现",
                           "不涉及", "无占用", "未占用", "未被占用", "未产生")


def _is_routine_occupation_report(title: str) -> bool:
    """**最窄策略**(终结 routine↔adverse 关键词 whack-a-mole;Codex 同类 5 轮后由用户授权)。
    headless **只抑制**"例行资金占用披露形式(专项说明/专项审核/汇总表)+ 标题明示无占用否定式"
    (如"…不存在非经营性资金占用…专项说明")。**其余一切**——包括未带否定式的例行专项说明/汇总表,
    以及任何明示/可疑占用——一律不抑制 → 报 risk,交 Slice-2b web/LLM skill 精判降级。
    设计后果:残余误差**只会是误报(可被 skill 降级)**,绝不会是漏报(明示风险被压成 clear);
    若漏掉某个否定式词,只会让一份无占用报告多显示为 risk,无害。headless 粗筛、skill 精判 = 设计本意。"""
    routine = ("资金占用" in title and "情况" in title
               and any(form in title for form in ROUTINE_OCCUPATION_FORMS))
    if not routine:
        return False
    return any(neg in title for neg in NO_OCCUPATION_NEGATIONS)


def _match_risk(title: str):
    """标题 → (category, risk_type, severity);无风险 → None。
    high severity 永不被抑制;medium/low 仅当命中**窄判**的例行年报资金占用专项说明时视为非风险。"""
    for kw, cat, rtype, severity in RISK_KEYWORD_MAP:
        if kw not in title:
            continue
        if severity != "high" and _is_routine_occupation_report(title):
            return None                                     # 例行年报专项说明,非真风险(窄判抑制)
        return cat, rtype, severity
    return None


# ── 官方结构化层(headless,PIT)──────────────────────────────────────────────
def build_official_structured(raw: dict, as_of: str):
    """cninfo 单代码原始结果 → official_structured + fetch_failed。
    PIT 强制(披露日 canonical 且 ≤ as_of);代码错配/未来/不可解析/非字典 = 质量缺陷。
    status:有 PIT 风险事件→risk(优先);无风险但全干净→clear;无风险但有缺陷或取数失败→unknown。"""
    as_of = str(as_of)
    if not raw.get("ok"):
        return {"status": "unknown", "events": [], "had_pit_announcements": False}, True   # 取数失败
    symbol = str(raw.get("ts_code", "")).split(".", 1)[0]
    raw_list = raw.get("announcements") or []
    n_defect = 0
    n_pit = 0                                                       # PIT-干净公告数(含非风险)
    events: list[dict] = []
    for a in raw_list:
        if not isinstance(a, dict):
            n_defect += 1
            continue
        if str(a.get("secCode", "")).strip() != symbol:
            n_defect += 1                                            # 代码错配 → 不可信,不当证据
            continue
        d = _parse_disclosure_date(a.get("announcementTime"))
        if d is None:
            n_defect += 1                                            # 不可解析披露日
            continue
        if d > as_of:
            n_defect += 1                                            # 未来日期 → PIT 泄漏,排除
            continue
        n_pit += 1
        title = str(a.get("announcementTitle", ""))
        hit = _match_risk(title)
        if hit:
            cat, rtype, severity = hit
            url = str(a.get("adjunctUrl", "") or "")
            if url and not url.startswith("http"):
                url = CNINFO_STATIC_HOST + url
            events.append({"source": "cninfo", "title": title[:200], "category": cat,
                           "disclosure_date": d, "url_or_pdf": url, "risk_type": rtype,
                           "severity": severity})
    if events:
        status = "risk"                                             # 真命中风险优先(即便另有缺陷行)
    elif n_defect > 0:
        status = "unknown"                                         # 不可信行 → 不敢报 clear
    else:
        status = "clear"                                           # 含空窗口(n_pit=0);批量空壳由 batch gate 降级
    return {"status": status, "events": events, "had_pit_announcements": n_pit > 0}, False


def _scan_tier(rank: int, official_status: str) -> str:
    if rank <= DEEP_RANK_MAX:
        return "deep"
    return "upgraded" if official_status == "risk" else "light"     # 命中升级(仅 Top6-15)


def _batch_announced(candidates: list) -> int:
    return sum(1 for c in candidates if c["official_structured"]["had_pit_announcements"])


def _batch_unhealthy(candidates: list) -> bool:
    """批量空壳判定:有 PIT 公告的代码数低于门槛 = 疑似 cninfo 200+空(请求形态/软反爬)。
    候选数 ≥ 门槛时要求 ≥ MIN_BATCH_ANNOUNCED;候选数 < 门槛时要求全部有公告。"""
    n = len(candidates)
    if n == 0:
        return False
    return _batch_announced(candidates) < min(MIN_BATCH_ANNOUNCED, n)


def _sina_sources(sina_raw) -> list[dict]:
    """best-effort:Sina 原始条目 → sources(source_type=sina);只判定不了,故不设 web_llm 状态。"""
    if not sina_raw or not sina_raw.get("ok"):
        return []
    out = []
    for it in (sina_raw.get("items") or []):
        if not isinstance(it, dict):
            continue
        title = str(it.get("title", "") or "")
        url = str(it.get("url", "") or "")
        if not title or not url:
            continue
        out.append({"title": title[:200], "url": url,
                    "published_at": (str(it.get("published_at")) if it.get("published_at") else None),
                    "fetched_at": (str(it.get("fetched_at")) if it.get("fetched_at") else None),
                    "source_type": "sina"})
    return out


def build_candidate(ts_code: str, rank: int, cninfo_raw: dict, sina_raw, as_of: str):
    official, fetch_failed = build_official_structured(cninfo_raw, as_of)
    scan_tier = _scan_tier(rank, official["status"])
    n_ev = len(official["events"])
    summary = (f"官方结构化: {official['status']}"
               + (f"({n_ev} 风险事件)" if n_ev else "")
               + "; web/LLM: 未评估(unknown,待 Slice-2b skill)")
    candidate = {
        "ts_code": ts_code, "rank": rank, "scan_tier": scan_tier,
        "official_structured": official,
        "web_llm": {"status": "unknown", "risk_level": "unknown", "action": "no_action"},
        "sources": _sina_sources(sina_raw),
        "confidence": None, "summary": summary,
        "boundary": {"advisory_only": True, "not_deterministic_veto": True},
    }
    return candidate, fetch_failed


def build_summary(universe: dict, candidate_flags: list, as_of: str, generated_at: str) -> dict:
    candidates = [c for c, _ in candidate_flags]
    checked = sum(1 for c in candidates if c["official_structured"]["status"] in ("clear", "risk"))
    unknown = sum(1 for c in candidates if c["official_structured"]["status"] == "unknown")
    failed = sum(1 for c, f in candidate_flags if f)
    return {
        "schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at, "as_of": as_of,
        "universe": {
            "requested": list(universe.get("requested", [])),
            "main_board_top15": list(universe.get("main_board_top15", [])),
            "dropped_non_main": list(universe.get("dropped_non_main", [])),
        },
        "coverage": {"checked": checked, "unknown": unknown, "failed": failed},
        "candidates": candidates,
        "boundary": {
            "production": False, "real_money": False, "hard_veto": False,
            "changes_egs_scoring": False, "changes_phase5_decision": False,
            "historical_backtest_evidence": False, "writes_production_path": False,
        },
    }


# ── 一致性硬门(advisory-only / unknown-not-clear / PIT / 主板 / scan-tier)──────
_WEB_ASSESSED_RISK = ("risk_candidate", "risk", "headwind")


def _web_llm_consistency_error(web: dict, sources: list):
    """web_llm advisory tier 跨字段不变式(summary 与 web_llm patch 共用,单一来源避免漂移)。
    返回错误字符串或 None。核心边界:**未检索/无证据 → 必须 unknown,绝不伪装 clear/tailwind**——
    任何**非 unknown**(已评估)态都必须带 sources 证据(coverage);只有 `unknown` 可空 sources。"""
    wst = web["status"]
    if wst == "unknown":
        if web["risk_level"] != "unknown":
            return "web unknown ⇒ risk_level unknown"
        if web["action"] != "no_action":
            return "web unknown ⇒ action no_action(无证据不得带 downgrade/manual_review 动作)"
        return None                                      # 未评估:unknown/unknown/no_action,可空 sources
    # 已评估态(clear_light/risk_candidate/risk/tailwind/headwind)一律须有证据
    if not sources:
        return "web 已评估态(clear_light/tailwind/risk/…)⇒ 必须有 sources 证据,否则应 unknown(不伪装 clear)"
    if wst == "clear_light" and web["risk_level"] != "none":
        return "web clear_light ⇒ risk_level none"
    if wst in _WEB_ASSESSED_RISK and web["risk_level"] not in ("low", "medium", "high"):
        return "web 风险态 ⇒ risk_level low/medium/high"
    if wst == "tailwind" and web["risk_level"] not in ("none", "low"):
        return "tailwind ⇒ risk_level none/low"
    return None


def validate_summary_consistency(summary: dict) -> None:
    if not _is_canonical_date(summary["as_of"]):
        raise ValueError("as_of 非合法 canonical 日历日期")
    as_of = summary["as_of"]
    uni = summary["universe"]
    main = uni["main_board_top15"]
    if len(main) > TOP15_CAP:
        raise ValueError("main_board_top15 超过 15")
    if any(not is_a_share_main_board(c) for c in main):
        raise ValueError("main_board_top15 含非主板代码")
    if any(is_a_share_main_board(c) for c in uni["dropped_non_main"]):
        raise ValueError("dropped_non_main 含本应保留的主板代码")
    if set(main) & set(uni["dropped_non_main"]):
        raise ValueError("main_board_top15 与 dropped_non_main 重叠")

    cands = summary["candidates"]
    if [c["ts_code"] for c in cands] != list(main):
        raise ValueError("candidates 必须与 main_board_top15 一一对应同序")
    for i, c in enumerate(cands):
        rank = c["rank"]
        if rank != i + 1:
            raise ValueError(f"{c['ts_code']}: rank 必须等于位次(1-based)")
        if not is_a_share_main_board(c["ts_code"]):
            raise ValueError(f"{c['ts_code']}: 非主板")
        if c["boundary"] != {"advisory_only": True, "not_deterministic_veto": True}:
            raise ValueError(f"{c['ts_code']}: boundary 必须 advisory_only + not_deterministic_veto")

        off = c["official_structured"]
        st = off["status"]
        # scan_tier:deep⟺rank≤5;rank≥6 → upgraded⟺official risk,else light
        if rank <= DEEP_RANK_MAX:
            if c["scan_tier"] != "deep":
                raise ValueError(f"{c['ts_code']}: rank≤5 必须 deep")
        else:
            want = "upgraded" if st == "risk" else "light"
            if c["scan_tier"] != want:
                raise ValueError(f"{c['ts_code']}: rank≥6 scan_tier 应为 {want}")
        # events ⟺ status==risk;事件须带 risk_type + PIT 披露日(canonical 且 ≤ as_of)
        if st == "risk" and len(off["events"]) < 1:
            raise ValueError(f"{c['ts_code']}: status=risk 必须有事件")
        if off["events"] and not off["had_pit_announcements"]:
            raise ValueError(f"{c['ts_code']}: 有风险事件却 had_pit_announcements=False(自相矛盾)")
        if st in ("clear", "unknown") and off["events"]:
            raise ValueError(f"{c['ts_code']}: clear/unknown 不应带风险事件")
        for ev in off["events"]:
            if not ev["risk_type"] or not ev["source"]:
                raise ValueError(f"{c['ts_code']}: 事件缺 risk_type/source")
            dd = ev["disclosure_date"]
            if not _is_canonical_date(dd) or dd > as_of:
                raise ValueError(f"{c['ts_code']}: 事件披露日非 PIT(canonical 且 ≤ as_of)")

        web_err = _web_llm_consistency_error(c["web_llm"], c["sources"])
        if web_err:
            raise ValueError(f"{c['ts_code']}: {web_err}")

    # batch-level cninfo sanity:批量空壳(有 PIT 公告代码数 < 门槛)时,任何"空窗口 clear"
    # (clear 且 had_pit_announcements=False)都非法——必须降级 unknown(fail-closed,防 200+空伪装全员无风险)。
    if _batch_unhealthy(cands):
        for c in cands:
            off = c["official_structured"]
            if off["status"] == "clear" and not off["had_pit_announcements"]:
                raise ValueError(f"{c['ts_code']}: 批量空壳(announced<门槛)下空窗口不得报 clear,应 unknown")

    cov = summary["coverage"]
    checked = sum(1 for c in cands if c["official_structured"]["status"] in ("clear", "risk"))
    unknown = sum(1 for c in cands if c["official_structured"]["status"] == "unknown")
    if cov["checked"] != checked or cov["unknown"] != unknown:
        raise ValueError("coverage checked/unknown 与 candidates 不一致")
    if cov["checked"] + cov["unknown"] != len(cands):
        raise ValueError("coverage checked+unknown 必须等于候选数")
    if cov["failed"] > cov["unknown"]:
        raise ValueError("coverage failed 不能超过 unknown")


_SEVERITY_RANK = {"high": 3, "medium": 2, "low": 1}


def _needs_manual_review(c: dict) -> bool:
    off = c["official_structured"]["status"]
    web = c["web_llm"]
    return (off in ("risk", "unknown") or web["action"] == "manual_review_required"
            or web["status"] in ("risk_candidate", "risk", "headwind"))


def _max_severity(events: list) -> str | None:
    if not events:
        return None
    return max((e["severity"] for e in events), key=lambda s: _SEVERITY_RANK.get(s, 0))


def render_semantic_risk_panel(summary: dict) -> str:
    """summary → M6.7/周报可见 markdown 块(纯函数,无 now())。明标 advisory·非确定·web/LLM 不可复现;
    只列需关注(risk/unknown/需复核)候选,clear 汇总成计数行。绝不把 advisory 混入确定性报告。"""
    cov = summary["coverage"]
    cands = summary["candidates"]
    n = len(cands)
    n_risk = sum(1 for c in cands if c["official_structured"]["status"] == "risk")
    n_unknown = sum(1 for c in cands if c["official_structured"]["status"] == "unknown")
    lines = [
        f"### A-short 语义风险 advisory(as_of {summary['as_of']})",
        "> ⚠️ **advisory·非确定·不进生产 scoring/decision/veto**;web/LLM 部分 LIVE 实时、**不可复现**;"
        "官方结构化层按披露日 PIT。仅供人工参考,非买卖信号。",
        f"覆盖:checked {cov['checked']} / unknown {cov['unknown']} / failed {cov['failed']}"
        f"(主板 Top15 共 {n});官方结构化风险候选 {n_risk};unknown {n_unknown}。",
    ]
    flagged = [c for c in cands if _needs_manual_review(c)]
    if not flagged:
        lines.append("无需关注候选(官方结构化全 clear);web/LLM 待 skill 评估。")
        return "\n".join(lines)
    lines.append("")
    lines.append("| rank | code | tier | 官方结构化 | web/LLM | 需人工复核 |")
    lines.append("|---|---|---|---|---|---|")
    for c in flagged:
        off = c["official_structured"]
        web = c["web_llm"]
        if off["status"] == "risk":
            sev = _max_severity(off["events"])
            latest = max((e["disclosure_date"] for e in off["events"]), default="-")
            rtypes = ",".join(sorted({e["risk_type"] for e in off["events"]}))
            off_cell = f"risk[{sev}] {rtypes}({len(off['events'])}事件,最新{latest})"
        else:
            off_cell = off["status"]
        web_cell = f"{web['status']}/{web['risk_level']}/{web['action']}"
        review = "是" if _needs_manual_review(c) else "否"
        lines.append(f"| {c['rank']} | {c['ts_code']} | {c['scan_tier']} | {off_cell} | "
                     f"{web_cell} | {review} |")
    lines.append("")
    lines.append("_web/LLM 全 `unknown` = 尚待 Slice-2b skill 评估(headless 仅官方结构化粗筛);"
                 "官方风险候选含宽关键词粗筛,实质性判断以 web/LLM advisory 为准。_")
    return "\n".join(lines)


def write_summary(summary: dict, out_path: str) -> None:
    _guard_out_path(out_path)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(summary, schema)
    validate_summary_consistency(summary)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


# ── Slice 2b-ii web_llm enrichment 契约(skill 产出 patch,headless 校验+合并)────
def validate_web_llm_patch(patch: dict) -> None:
    """patch schema + 跨字段不变式 + 无重复 ts_code。web_llm 不变式复用 `_web_llm_consistency_error`。"""
    with open(PATCH_SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(patch, schema)
    if not _is_canonical_date(patch["target"]["as_of"]):
        raise ValueError("patch target.as_of 非 canonical 日历日期")
    seen = set()
    for pc in patch["candidates"]:
        ts = pc["ts_code"]
        if ts in seen:
            raise ValueError(f"patch 重复 ts_code: {ts}")
        seen.add(ts)
        err = _web_llm_consistency_error(pc["web_llm"], pc["sources"])
        if err:
            raise ValueError(f"{ts}: {err}")


def apply_web_llm_patch(summary: dict, patch: dict) -> dict:
    """把 skill 的 web_llm 判断合并进 summary(纯函数,返回新 dict)。**只**写 web_llm/sources/confidence/
    summary(可选)到匹配候选;绝不碰 official_structured/boundary/rank/scan_tier/ts_code/coverage。
    patch 不能引入 universe 外的代码;合并后整体过 `validate_summary_consistency`(authoritative)。
    覆盖语义:同一候选的 web_llm/sources 被替换(非追加);未在 patch 内的候选保持原 web_llm(headless unknown)。"""
    validate_web_llm_patch(patch)
    tgt = patch["target"]
    if tgt["as_of"] != summary["as_of"]:
        raise ValueError("patch target.as_of 与 summary.as_of 不一致")
    if tgt["summary_schema_name"] != summary["schema_name"] or summary["schema_name"] != SCHEMA_NAME:
        raise ValueError("patch target.summary_schema_name 与 summary.schema_name 不一致")
    if tgt["summary_schema_version"] != summary["schema_version"]:
        raise ValueError("patch target.summary_schema_version 与 summary 不一致")
    main = set(summary["universe"]["main_board_top15"])
    by_code = {c["ts_code"]: c for c in summary["candidates"]}
    new = copy.deepcopy(summary)
    new_by_code = {c["ts_code"]: c for c in new["candidates"]}
    for pc in patch["candidates"]:
        ts = pc["ts_code"]
        if ts not in main or ts not in by_code:
            raise ValueError(f"patch 引入了 universe 外/不存在的候选: {ts}")
        c = new_by_code[ts]
        web = dict(pc["web_llm"])
        c["web_llm"] = web                               # 替换,非追加
        c["sources"] = [dict(s) for s in pc["sources"]]
        c["confidence"] = pc["confidence"]
        # summary 也是替换语义:patch 带则用;不带则按当前 official+web 态**重生**,绝不留旧 summary
        c["summary"] = pc["summary"] if "summary" in pc else (
            f"官方结构化: {c['official_structured']['status']}; "
            f"web/LLM: {web['status']}/{web['risk_level']}/{web['action']}")
        # official_structured / boundary / rank / scan_tier / ts_code 一律不动
    validate_summary_consistency(new)                    # 合并后 web 不变式 + 全局一致性硬门
    return new


def build_summary_from_fetches(watch_pool, as_of: str, cninfo_results, sina_results, generated_at: str):
    """纯编排(无 I/O):watch_pool → 主板 Top15 → 逐候选 build。cninfo_results/sina_results 为
    {ts_code: raw} 映射(注入便于测试)。sina_results 可为 None(未跑 Sina)。"""
    main_codes, dropped = main_board_top15(watch_pool)
    universe = {"requested": list(watch_pool), "main_board_top15": main_codes,
                "dropped_non_main": dropped}
    flags = []
    for rank, ts in enumerate(main_codes, start=1):
        cninfo_raw = cninfo_results.get(ts, {"ts_code": ts, "ok": False,
                                             "error_category": "not_fetched", "announcements": []})
        sina_raw = (sina_results or {}).get(ts)
        flags.append(build_candidate(ts, rank, cninfo_raw, sina_raw, as_of))
    # batch-level cninfo sanity:大面积空响应(疑似 200+空)→ 空窗口的 clear 降级 unknown(fail-closed)。
    # 单只真实无公告在健康批量里仍可 clear;批量异常时绝不把空壳报成全员无风险。
    candidates = [c for c, _ in flags]
    if _batch_unhealthy(candidates):
        for c in candidates:
            off = c["official_structured"]
            if off["status"] == "clear" and not off["had_pit_announcements"]:
                off["status"] = "unknown"
                c["summary"] += "(batch-anomaly: 大面积空响应 → 降级 unknown,疑似 cninfo 请求形态/软反爬)"
    return build_summary(universe, flags, as_of, generated_at)


def _watch_pool_from_analysis_input(ai: dict) -> list:
    """从 EGS analysis_input 抽候选 ts_code(按原顺序、去空)作 watch pool;
    runner 内部再过 `main_board_top15`。让 weekly_screening 能直接用生产 analysis_input 接入语义层。"""
    return [str(c["ts_code"]) for c in (ai.get("candidates") or [])
            if isinstance(c, dict) and c.get("ts_code")]


def main(argv=None, cninfo_fetcher=None, sina_fetcher=None):
    p = argparse.ArgumentParser(description="A-short 语义风险 advisory summary — Slice 2a headless 骨架")
    p.add_argument("--as-of", required=True, help="YYYYMMDD")
    p.add_argument("--watch-pool", help="逗号分隔 ts_code 或 @path JSON 数组(与 --analysis-input 二选一)")
    p.add_argument("--analysis-input", help="EGS analysis_input.json:从其 candidates 抽 watch pool"
                                            "(与 --watch-pool 二选一;供 weekly_screening 接入)")
    p.add_argument("--out", required=True, help="summary 落点(禁 result/a_short)")
    p.add_argument("--confirm-fetch-authorized", action="store_true",
                   help="确认用户已授权本次 cninfo(+可选 Sina)真实抓取")
    p.add_argument("--include-sina", action="store_true", help="best-effort Sina sources feeder(LIVE)")
    p.add_argument("--cninfo-lookback-days", type=int, default=90)
    args = p.parse_args(argv)

    if not args.confirm_fetch_authorized:
        raise SystemExit("[FATAL] 需 --confirm-fetch-authorized:本 runner 会真实抓取 cninfo/Sina")
    if not _is_canonical_date(args.as_of):
        raise SystemExit(f"[FATAL] --as-of {args.as_of} 不是合法日历日期")
    if bool(args.watch_pool) == bool(args.analysis_input):
        raise SystemExit("[FATAL] 须且仅须提供 --watch-pool 或 --analysis-input 之一")
    _guard_out_path(args.out)

    if args.analysis_input:
        # 消费方校验(#R-ASHORT-SEMANTIC-SUMMARY-ANALYSIS-INPUT-CONSUMER-VALIDATION-GAP):
        # 走仓库 analysis_input 契约(schema+PIT),并强制 trade_date == --as-of,**在取数/写盘前** abort,
        # 否则会把旧/未来/坏批次候选池贴上当前 as_of 标签(与 weekly pipeline 同一道门)。
        from engine.data.analysis_input_contract import validate_analysis_input_file
        ai = validate_analysis_input_file(args.analysis_input, label="semantic-risk analysis_input")
        if str(ai.get("trade_date")) != str(args.as_of):
            raise SystemExit(f"[FATAL] analysis_input.trade_date {ai.get('trade_date')} != --as-of "
                             f"{args.as_of}(批次错配/未来/陈旧,拒建语义层)")
        requested = _watch_pool_from_analysis_input(ai)
    else:
        requested = _load_watch_pool(args.watch_pool)
    main_codes, dropped = main_board_top15(requested)
    print(f"[semantic-summary] universe: requested={len(requested)} → main-board Top15={len(main_codes)} "
          f"(dropped={len(dropped)})")

    cf = cninfo_fetcher or fetch_cninfo
    cninfo_list = cf(main_codes, args.as_of, args.cninfo_lookback_days)
    cninfo_results = {r["ts_code"]: r for r in cninfo_list}
    sina_results = None
    if args.include_sina:
        sf = sina_fetcher or fetch_sina
        sina_results = {r["ts_code"]: r for r in sf(main_codes)}

    summary = build_summary_from_fetches(requested, args.as_of, cninfo_results, sina_results,
                                         datetime.now().astimezone().isoformat(timespec="seconds"))
    write_summary(summary, args.out)
    cov = summary["coverage"]
    n_risk = sum(1 for c in summary["candidates"] if c["official_structured"]["status"] == "risk")
    print(f"[semantic-summary] coverage checked={cov['checked']} unknown={cov['unknown']} "
          f"failed={cov['failed']}; official risk candidates={n_risk}")
    print(f"[semantic-summary] web/LLM 全留 unknown(待 Slice-2b skill);summary → {args.out}")


if __name__ == "__main__":
    main()
