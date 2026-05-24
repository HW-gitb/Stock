# Phase 2 Data Lineage Handoff

Date: 2026-05-24

## What Changed

Closed the Phase 2.6 lineage tail by adding a formal `data_lineage` object to `backtest_report.json`. Report schema bumped to `rank_backtest_report` v1.10.0.

Files changed:

- `schemas/rank_backtest_report.schema.json` (v1.9.0 → v1.10.0; `data_lineage` added to `required` + `properties`)
- `runners/backtest_rank.py` (writes `data_lineage` block; schema_version constant bumped)
- `result/a_short/backtest/backtest_report.json` (regenerated via `--stats-only`)
- `docs/CURRENT.md` (Phase 2.6 status flipped to 完成；§6 next-step list rewritten around Phase 3)
- `AGENTS.md` (handoff chain link)

## Why

Phase 2.6 design doc and AGENTS guardrail were already in place, but report lineage was only partially recorded — provider, API surface, benchmark identifiers, and PIT limitations were scattered across `settings`, `forward_daily`, and the free-text `limitations` array, or absent entirely. The 24p v7.10 review explicitly flagged this as the Phase 2.6 闭环 gap.

A future reader (LLM teammate, audit, or a Phase 7 DataHub refactor) now has one canonical place to identify what fed every number in the report.

## The data_lineage Object

```json
"data_lineage": {
  "data_provider": "tushare",
  "api_families": {
    "candidate_generation": [
      "daily", "daily_basic", "moneyflow", "fina_indicator",
      "stk_limit", "stock_basic", "trade_cal",
      "index_member_all", "index_member", "index_classify",
      "adj_factor", "concept", "concept_detail"
    ],
    "forward_evaluation": [
      "daily", "adj_factor", "stk_limit", "index_daily", "trade_cal"
    ]
  },
  "forward_return_adjustment_mode": "qfq_via_adj_factor",
  "benchmark_sources": {
    "csi300": "tushare:index_daily/000300.SH",
    "csi1000": "tushare:index_daily/000852.SH",
    "eligible": "internal:generated/_intermediate/egs_full_YYYYMMDD.csv Tier1+Tier2 equal-weight"
  },
  "pit_limitations": [
    "Tushare financials are filtered by ann_date<=as_of but returned values reflect latest revisions, not as-originally-disclosed (Tushare API limitation, not fixable here).",
    "L3 concept catalysts have no native as-of parameter; PIT support is via locally accumulated state/l3_snapshots/ snapshots (only effective once coverage is meaningful).",
    "SW industry membership applies in_date/out_date PIT filtering (B3a fix).",
    "Stock universe includes delisted stocks per as_of (B2 fix)."
  ]
}
```

Notes:

- `forward_return_adjustment_mode` is read from `forward_daily.adj` when available; otherwise defaults to `qfq_via_adj_factor`. Schema enum currently `qfq_via_adj_factor | none` matches `forward_daily.adj`.
- `pit_limitations` is a centralized, structured subset; the dynamic `l3_mode`-dependent note still lives in the top-level `limitations` array (it varies per run).
- This is additive metadata only. No production screening, candidate scoring, sample selection, or stats computation changed.

## Validation Commands

Syntax check:

```powershell
python -c "from pathlib import Path; [compile(Path(f).read_text(encoding='utf-8'), f, 'exec') for f in ['runners/backtest_rank.py']]; print('syntax ok')"
```

Result: `syntax ok`.

Schema meta-validation:

```powershell
python -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/rank_backtest_report.schema.json',encoding='utf-8')); Draft7Validator.check_schema(s); print('schema meta-validation ok')"
```

Result: `schema meta-validation ok`.

Stats-only regeneration:

```powershell
python runners/backtest_rank.py --mode production --stats-only --windows 5,10,20 --split-date 20250101
```

Result: success, exit code 0.

Independent report-against-schema validation:

```powershell
python -c "import json; from jsonschema import Draft7Validator; s=json.load(open('schemas/rank_backtest_report.schema.json',encoding='utf-8')); r=json.load(open('result/a_short/backtest/backtest_report.json',encoding='utf-8')); errs=list(Draft7Validator(s).iter_errors(r)); print(f'errors: {len(errs)}'); print('schema_version:', r['schema_version'])"
```

Result: `errors: 0`, `schema_version: 1.10.0`.

## Invalidated Old Conclusions

- `rank_backtest_report` v1.9.0 outputs remain readable but no longer match the current contract (missing `data_lineage`).
- `CURRENT.md` claim that Phase 2.6 was "待启动" is invalid; Phase 2.6 is now complete.
- `CURRENT.md` schema-version references to `1.8.0` are invalid; current is `1.10.0`.

No strategy conclusion changes. Phase 2 strategy boundary unchanged: engineering signoff yes, strategy signoff no, Tier1-only is the primary subset.

## Next Notes

- Future schema changes that introduce a new data source (e.g., 美股扩展时引入 polygon/alpaca) must extend `data_provider` enum and add to `api_families`. Treat any new external API endpoint as a `data_lineage` change requiring schema version bump.
- Phase 3 analyzer/state work should be the next handoff. The Phase 2.6 work is now considered fully closed.

---

## 2026-05-24 追加：data canary 旁路对账脚本

新建 `runners/data_canary.py`：每周选股后跑一次，对 Tier1 候选随机抽 5 只，对比 close/pe/pb/name 在 Tushare（egs_main.py 落盘）和 akshare（实时快照）是否一致。属于 Phase 2.6 lineage 收尾的最后一块拼图——data_lineage 元数据说"我们用了什么源"，canary 验证"这个源没有静默漂移"。

### 改动文件

- 新增 `runners/data_canary.py`（~230 行）
- 修改 `.gitignore` 加 `logs/`（canary 输出目录）
- 修改 AGENTS.md 文件参考
- 修改 CURRENT.md §2/§7

### 设计约束（违反则不应合入）

- **不进入打分**：不写 `analysis_input.json`、不动 candidates.csv、不改 EGS Tier 划分
- **不阻断选股**：任何异常（akshare 未装 / 抓取失败 / 候选缺失）都只写 `logs/data_canary_<as_of>.json` 并 exit 0
- **不对比行业**：Tushare 用 SW 申万，akshare 默认东财/同花顺，体系不一致硬比会大量误报
- **阈值收紧**：close 差异 > 0.5% warning / > 5% error；pe/pb 差异 > 10% 才 warning；name 忽略 ST/*ST/PT 前缀

### 三个 graceful 分支

| 分支 | 触发 | 验证状态 |
|---|---|---|
| `skipped_akshare_not_installed` | akshare 未装 | 已沙箱验证 |
| `skipped_no_candidates` | 找不到 egs_full_<as_of>.csv 也找不到 backtest candidates | 路径分支已加 |
| `error_akshare_fetch_failed` | akshare API 异常（限速 / 网络 / 接口变更） | 已沙箱验证（沙箱无法连东财，正好验证不阻断逻辑） |
| `ok / warn / error_drift / error_missing` | 真实对账 | **需用户本地（非沙箱）跑一次验证** |

### 使用

```powershell
# 默认：auto-find A-EGS/Result/egs_full_<today>.csv，过滤 Tier1，随机抽 5 只
python runners/data_canary.py

# 指定 as-of
python runners/data_canary.py --as-of 20260522

# 手工指定候选源
python runners/data_canary.py --candidates A-EGS/Result/egs_full_20260522.csv
```

输出：`logs/data_canary_<as_of>.json`。结构含 `summary.overall_status`（ok/warn/error_drift/error_missing）、`comparisons` 数组（每只票的 diff）、`thresholds`、`limitations`。

### 失效旧结论

无。canary 是旁路新增工具，不改任何已有结论或数据流。

### 验证命令

```powershell
python -c "from pathlib import Path; compile(Path('runners/data_canary.py').read_text(encoding='utf-8'), 'runners/data_canary.py', 'exec'); print('syntax ok')"
python runners/data_canary.py --as-of 20260522 --help
python runners/data_canary.py --as-of 20260522   # 沙箱无网会落 error_akshare_fetch_failed，符合预期
```

### 下一步

1. 用户本地（非沙箱）跑一次 `python runners/data_canary.py --as-of 20260522` 验证真实对账分支；如果 5 只里 close 差异都 < 0.5% 且 name 一致 → 收尾完成
2. 周五选股流程末尾加一行 canary 调用（手工 / 脚本 / scheduler 都可，不强制）
3. 第一次跑出 warning 时复查阈值是否合适，再决定是否调整

