#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-short 赛道热度 overlay §6 升级-复审 readiness + 跨LLM 提醒(comparison-track,非生产).

**目的(用户 2026-06-17 硬要求):** overlay 是 comparison-only,要攒够 forward 观测(governance
`promotion_rule.min_forward_observations`,当前 12)才到 §6 升级/退役复审点。本 harness 把这个
"到点提醒"做成**确定性、数据驱动**的——扫所有 forward overlay.json、数 forward 观测、≥阈值即置
`promotion_review_due`,并由 `weekly_screening.ps1` 的 overlay Stage 每次实盘自动打醒目横幅。
**不依赖某个 LLM 记得读 register**——不管用哪个 AI 跑系统,实盘运行的横幅 + eval summary artifact
都会提醒。register track ② 同步成"数据驱动 + 运行时横幅"。

**边界 / 现在不做的:** 本 harness **不**自动升级,也**不**算 §6 的赛道-vs-baseline 跑赢指标
(monthly clustered-t / drawdown / win-rate / bad-ticket / false-negative)。原因:governance 的
`promotion_rule` 还**没冻** top-K / 持有窗 / 稳定胜出 margin(`stable_win_margin_pending`:首次复审前才冻)。
按纪律不现编未冻参数、也没 12 周数据可验证。深度指标计算 = 临近复审、冻完参数后的独立小切片(见 register
`R-ASHORT-OVERLAY-EVAL-METRICS-FOLLOWUP`)。本切片只做诚实的 readiness 检测 + 提醒 + forward 观测清单。
零取数、不碰生产 final_score/tier/admission。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import jsonschema  # noqa: E402

from engine.a_short_run_paths import run_bundle_dir, PRODUCTION_OUTPUT_ROOT  # noqa: E402
from runners.a_short_theme_overlay_comparison import (  # noqa: E402
    validate_overlay_summary_consistency, SCHEMA_NAME as OVERLAY_SCHEMA_NAME)

SCHEMA_NAME = "a_short_overlay_eval_summary"
SCHEMA_VERSION = "1.0.0"
SCHEMA_PATH = os.path.join(ROOT, "schemas", "a_short_overlay_eval_summary.schema.json")
OVERLAY_SCHEMA_PATH = os.path.join(ROOT, "schemas", "a_short_theme_overlay_comparison.schema.json")
GOV_PATH = os.path.join(ROOT, "presets", "a_short_theme_overlay_governance_20260610.json")
FORWARD = "forward"   # 只有 concept_membership=='forward'(决策当日 live 成员)的 obs 计入升级时钟

DECISION_ACCUMULATING = "accumulating"                     # 还没到 min_forward_observations
DECISION_DUE_MARGIN_PENDING = "review_due_margin_pending"  # 到点但 governance 稳定胜出 margin 还没冻
DECISION_DUE_READY = "review_due_ready"                    # 到点且 margin 已冻 → 可算指标 + 决定
DECISION_STATUSES = (DECISION_ACCUMULATING, DECISION_DUE_MARGIN_PENDING, DECISION_DUE_READY)


def _is_yyyymmdd(s) -> bool:
    try:
        datetime.strptime(str(s), "%Y%m%d")
        return True
    except (ValueError, TypeError):
        return False


def _load_governance(path: str = GOV_PATH) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def margin_frozen(promotion_rule: dict) -> bool:
    """稳定胜出 margin 是否已冻:promotion_rule 里有数值 `stable_win_margin` 才算冻。
    当前 governance 只有占位字符串 `stable_win_margin_pending` → 未冻 → 即便到 12 obs 也不授权升级。"""
    return isinstance(promotion_rule.get("stable_win_margin"), (int, float))


def discover_forward_overlays(results_root: str | None = None, project_root: str | None = None) -> list:
    """扫 `<results_root>/<as_of>/overlay.json`,只收 **schema 合法 + track=comparison + concept_membership=='forward'**
    的观测(forward = live 决策当日成员,无 look-ahead,唯一计入升级时钟的)。malformed/不可读/非 forward → 跳过
    (fail-closed:绝不把坏 artifact 计入证据)。返回按 as_of 升序、as_of 去重的 obs 列表。"""
    base = results_root if results_root is not None else os.path.join(
        project_root if project_root is not None else ROOT, *PRODUCTION_OUTPUT_ROOT.split(os.sep))
    if not os.path.isdir(base):
        return []
    with open(OVERLAY_SCHEMA_PATH, "r", encoding="utf-8") as f:
        overlay_schema = json.load(f)
    by_as_of: dict[str, dict] = {}
    for name in sorted(os.listdir(base)):
        if not _is_yyyymmdd(name):
            continue
        path = os.path.join(base, name, "overlay.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                ov = json.load(f)
            if ov.get("schema_name") != OVERLAY_SCHEMA_NAME:
                continue
            jsonschema.validate(ov, overlay_schema)
            validate_overlay_summary_consistency(ov)
        except Exception:
            continue                                          # 坏/不可解析 overlay 不计入(fail-closed)
        if (ov.get("pit_source") or {}).get("concept_membership") != FORWARD:
            continue                                          # 只计 forward(pit 回放/unavailable 不进升级时钟)
        as_of = str(ov.get("as_of"))
        if not _is_yyyymmdd(as_of) or as_of != name:
            continue   # 桶目录名必须 == artifact as_of:错位/陈旧 artifact(name != as_of)fail-closed 不计入,防错位推进升级时钟
        by_as_of[as_of] = {                                   # as_of 去重:同日多次写以最后读到的为准
            "as_of": as_of,
            "generated_at": str(ov.get("generated_at") or ""),
            "candidate_count": int(ov.get("candidate_count") or 0),
        }
    return [by_as_of[k] for k in sorted(by_as_of)]


def promotion_readiness(n_forward_obs: int, min_obs: int, is_margin_frozen: bool) -> dict:
    """纯判定:数 obs vs 阈值 + margin 是否已冻 → decision_status。"""
    review_due = n_forward_obs >= min_obs
    if not review_due:
        status = DECISION_ACCUMULATING
    elif not is_margin_frozen:
        status = DECISION_DUE_MARGIN_PENDING
    else:
        status = DECISION_DUE_READY
    return {"promotion_review_due": review_due, "decision_status": status}


def build_eval_summary(forward_obs: list, as_of: str, generated_at: str, gov: dict) -> dict:
    pr = gov["promotion_rule"]
    min_obs = int(pr["min_forward_observations"])
    is_frozen = margin_frozen(pr)
    n = len(forward_obs)
    readiness = promotion_readiness(n, min_obs, is_frozen)
    return {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "as_of": str(as_of),
        "track": "comparison_non_production",
        "min_forward_observations": min_obs,
        "n_forward_observations": n,
        "promotion_review_due": readiness["promotion_review_due"],
        "stable_win_margin_frozen": is_frozen,
        "decision_status": readiness["decision_status"],
        "benchmarks_required": list(pr.get("benchmarks_required") or []),
        "metrics_required": list(pr.get("metrics_required") or []),
        "forward_observations": list(forward_obs),
        "boundary": {"production": False, "is_promotion_decision": False, "satisfies_ship_gate": False},
    }


def validate_eval_summary_consistency(summary: dict) -> None:
    """§ 不变量:计数自洽、due 与阈值一致、status 与(due,margin)一致、obs 升序唯一合法、boundary 全 false。"""
    if not _is_yyyymmdd(summary["as_of"]):
        raise ValueError(f"as_of {summary['as_of']} 非合法日历日期")
    obs = summary["forward_observations"]
    if summary["n_forward_observations"] != len(obs):
        raise ValueError("n_forward_observations 与 forward_observations 长度不一致")
    prev = None
    for o in obs:
        if not _is_yyyymmdd(o["as_of"]):
            raise ValueError(f"forward obs as_of 非法: {o['as_of']}")
        if prev is not None and o["as_of"] <= prev:
            raise ValueError("forward_observations as_of 非严格升序/有重复")
        prev = o["as_of"]
    due = summary["n_forward_observations"] >= summary["min_forward_observations"]
    if due != summary["promotion_review_due"]:
        raise ValueError("promotion_review_due 与 n>=min 不一致")
    st, frozen = summary["decision_status"], summary["stable_win_margin_frozen"]
    if st not in DECISION_STATUSES:
        raise ValueError(f"decision_status 非法 {st!r}")
    exp = (DECISION_ACCUMULATING if not due
           else (DECISION_DUE_READY if frozen else DECISION_DUE_MARGIN_PENDING))
    if st != exp:
        raise ValueError(f"decision_status {st!r} 与 (due={due}, margin_frozen={frozen}) 不一致(应 {exp!r})")
    if any(summary["boundary"].values()):
        raise ValueError("boundary 必须全 false(非生产/非升级决定/非 ship-gate)")


def assert_non_production_out(out_path: str) -> None:
    """eval summary 是 comparison-only 非生产 → **绝不写进生产桶 `result/a_short`**(防 lineage 污染:
    生产桶受 CLAUDE.md 保护、周报护栏硬拒)。任何路径含连续段 `result`/`a_short`(不管在哪个根下,含 tmp)
    即拒,写盘前 fail-closed。sanctioned 的 `research/results/a_short/...`(段是 results 非 result)放行。"""
    parts = [p.lower() for p in os.path.normpath(os.path.abspath(out_path)).split(os.sep)]
    for i in range(len(parts) - 1):
        if parts[i] == "result" and parts[i + 1] == "a_short":
            raise ValueError(f"拒绝把非生产 overlay eval summary 写入生产桶 result/a_short:{out_path}")


def write_eval_summary(summary: dict, out_path: str) -> None:
    assert_non_production_out(out_path)                        # 写盘前先挡生产桶(非生产产物不得污染 result/a_short)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    jsonschema.validate(summary, schema)
    validate_eval_summary_consistency(summary)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    tmp = str(out_path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    os.replace(tmp, out_path)


def readiness_banner(summary: dict) -> str:
    """运行时给用户/任何 AI 看的提醒文本。到点 -> 醒目;未到 -> 一行进度。**必须 GBK-safe**(无 emoji / 非 GBK
    符号):Windows 控制台 stdout 常是 gbk,若横幅含 ⚠️ 等字符,会在"恰好该提醒(到点)"时 UnicodeEncodeError
    崩掉、连提醒都打不出——正好打败本切片目的。故只用 ASCII 符号 + 中文。"""
    n, m = summary["n_forward_observations"], summary["min_forward_observations"]
    if not summary["promotion_review_due"]:
        return f"[overlay] forward 观测 {n}/{m} -- 未到 S6 升级复审点,继续 comparison 累积(非生产)。"
    head = ("\n" + "=" * 78 + "\n"
            f"!!! [overlay] S6 升级复审到期:forward 观测 {n} >= {m}(governance 阈值)。\n")
    if summary["decision_status"] == DECISION_DUE_MARGIN_PENDING:
        body = ("    下一步(需用户决定,任何 AI 都应在此提醒):\n"
                "      1) 先在 presets/a_short_theme_overlay_governance_20260610.json 冻 stable_win_margin\n"
                "         (当前 stable_win_margin_pending、未冻 -> 暂不授权升级);\n"
                "      2) 起草 S6 指标切片(R-ASHORT-OVERLAY-EVAL-METRICS-FOLLOWUP):算 overlay vs baseline 的\n"
                "         monthly clustered-t / drawdown / win-rate / bad-ticket / false-negative(CSI1000 & CSI300);\n"
                "      3) 据指标 + margin 决定:升 production 排序 / 退役。full-size 另走 12 月 ship gate。\n")
    else:
        body = ("    margin 已冻 -> 起草/运行 S6 指标切片算 overlay vs baseline 跑赢度,据此决定升级/退役。\n")
    return head + body + ("    (comparison-only,绝不自动切生产;详见 register comparison-only tracks 索引 track 2。)\n"
                          + "=" * 78)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="A-short overlay §6 readiness + promotion-review 提醒(非生产)")
    p.add_argument("--results-root", default=None,
                   help="扫 overlay.json 的根(缺省 = 生产桶 result/a_short)")
    p.add_argument("--as-of", default=None, help="summary 的 as_of(缺省 = 最新 forward obs 的 as_of,无则今天)")
    p.add_argument("--out", default=os.path.join(ROOT, "research", "results", "a_short", "overlay_eval_summary.json"),
                   help="eval summary 落点(research lane,非生产)")
    p.add_argument("--check-readiness", action="store_true",
                   help="只打 readiness 横幅、不写 summary(供 weekly_screening.ps1 每周快查)")
    args = p.parse_args(argv)

    gov = _load_governance()
    forward_obs = discover_forward_overlays(args.results_root)
    as_of = args.as_of or (forward_obs[-1]["as_of"] if forward_obs else datetime.now().strftime("%Y%m%d"))
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    summary = build_eval_summary(forward_obs, as_of, generated_at, gov)
    print(readiness_banner(summary))
    if not args.check_readiness:
        write_eval_summary(summary, args.out)
        print(f"[overlay] eval summary -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
