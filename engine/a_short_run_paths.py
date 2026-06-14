#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A-short 单次 run 的统一产物文件夹约定(单一真相源).

用户(2026-06-11)要求把每次 run 的选股 + EGS comparison-diff 放在**一个文件夹**里方便找。
**约定:一个 run 的桶 = `<该 run 的 EGS --output-root>/<as_of>/`**(本模块的解析逻辑逐字镜像
`egs_main.export_analysis_input`:`--output-root` 绝对/项目相对皆可,缺省 = `result/a_short`)。
egs_main 把选股(analysis_input/candidates/snapshot)与 comparison-diff 都落到这一个桶;周报 M6.7 的落点**按流分**(见下两条流):分析流与选股同桶;**生产流(weekly_screening)是有意 hybrid**
——选股落 result/a_short、M6.7 advisory 落 research lane,靠 run_lineage 绑定(M6.7 非生产)。这样 comparison-diff **永远和 analysis_input 同桶**(从同一个 output_root 派生,
不硬编码),消除"选股落一处、分析落另一处"的割裂。

**两条流(显式边界,不混):**
- **生产流**(`A-EGS/egs_main.py --as-of <d>` 缺省 output-root):桶 = `result/a_short/<as_of>/`;
  `runners/forward_tracker.py` 从这里读 analysis_input。受 CLAUDE.md 保护、周报 pipeline 写盘护栏
  硬拒 `result/a_short/`——所以**生产桶 `result/a_short` 里不放 M6.7**(护栏硬拒)。**注(Slice 3b-2)**:周五 `weekly_screening.ps1` 现会跑 M6.7 advisory,但 M6.7 落 **research lane**(`research/results/a_short/<as_of>/weekly_m67.json`,IV feed 落 `research/results/a_short/iv_feed_<as_of>/`),**不进生产桶**——selection 在生产桶、advisory M6.7 在 research lane 的有意 hybrid(M6.7 非生产)。
- **分析流**(我们用:EGS `--output-root research/results/a_short` + 周报 pipeline):桶 =
  `research/results/a_short/<as_of>/`,含选股 + comparison + M6.7。该路径含 `results`(带 s),
  不触发 pipeline 的 `result/a_short` 护栏(测试钉死)。

IV feed 是**市场级、跨 run 复用**,不放进 run 桶(单独目录,用 `--iv-feed` 引用)。纯 os.path,无副作用,可单测。
"""
from __future__ import annotations

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 未来运行结果按 lane 归档的根:research/results/<lane>/(约定见 docs/a_short_run_bundle_convention)。
# 新 runner 默认往自己 lane 的目录写;us 绿地直接用;a_long 新切片配套改路径用;a_short 已用。
RESEARCH_RESULTS_REL = os.path.join("research", "results")
LANES = ("a_short", "a_long", "us_short", "us_long")
# 分析流传给 EGS `--output-root` 的相对根(我们的 run 用这个,落到 research/results/a_short/<as_of>)
ANALYSIS_OUTPUT_ROOT = os.path.join("research", "results", "a_short")


def lane_output_root(lane: str, project_root: str | None = None) -> str:
    """某 lane 的结果归档根:<root>/research/results/<lane>/。新 runner 默认往这里写,实现按 lane 归档。"""
    if lane not in LANES:
        raise ValueError(f"unknown lane {lane!r}; expected one of {LANES}")
    root = project_root if project_root is not None else PROJECT_ROOT
    return os.path.join(root, RESEARCH_RESULTS_REL, lane)
# 生产流缺省根(egs_main 默认;forward_tracker 从这里读)
PRODUCTION_OUTPUT_ROOT = os.path.join("result", "a_short")


def resolve_base_root(output_root: str | None = None, project_root: str | None = None) -> str:
    """镜像 egs_main.export_analysis_input 的 base_root 解析:output_root(绝对或项目相对)
    优先,缺省 = 生产根 result/a_short。"""
    root = project_root if project_root is not None else PROJECT_ROOT
    if output_root:
        return output_root if os.path.isabs(output_root) else os.path.join(root, output_root)
    return os.path.join(root, "result", "a_short")


def run_bundle_dir(as_of: str, output_root: str | None = None, project_root: str | None = None) -> str:
    """单次 run 的统一桶:<resolved base_root>/<as_of>/(与 EGS analysis_input 落点一致)。"""
    return os.path.join(resolve_base_root(output_root, project_root), str(as_of))


def analysis_input_path(as_of, output_root=None, project_root=None):
    return os.path.join(run_bundle_dir(as_of, output_root, project_root), "analysis_input.json")


def weight_comparison_path(as_of, output_root=None, project_root=None):
    return os.path.join(run_bundle_dir(as_of, output_root, project_root), "egs_weight_comparison.json")


def overlay_path(as_of, output_root=None, project_root=None):
    return os.path.join(run_bundle_dir(as_of, output_root, project_root), "overlay.json")


def weekly_m67_path(as_of, output_root=None, project_root=None):
    return os.path.join(run_bundle_dir(as_of, output_root, project_root), "weekly_m67.json")


def account_path(as_of, output_root=None, project_root=None):
    return os.path.join(run_bundle_dir(as_of, output_root, project_root), "account.json")
