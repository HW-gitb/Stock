# A-short 单次 run 产物统一文件夹约定

**日期**: 2026-06-11(2026-06-11 Codex 复审后修正:从"硬编码 research/results"改为"从 run 的 output_root 派生 + 两条流显式边界")
**动因**: 用户要求把每次 run 的选股 + 分析产物放在一个文件夹里方便找(此前 comparison-diff 落 research/results、选股落 result/a_short 或 backtest/generated,割裂)。
**单一真相源**: `engine/a_short_run_paths.py`(纯路径函数,可测)。

## 1. 约定:桶 = `<该 run 的 EGS --output-root>/<as_of>/`
`a_short_run_paths.resolve_base_root` **逐字镜像** `egs_main.export_analysis_input` 的解析:`--output-root`(绝对或项目相对)优先,缺省 = `result/a_short`。一个 run 的所有产物落到 `<base_root>/<as_of>/` **同一个桶**。comparison-diff 由 egs_main **从同一个 output_root 派生**(`weight_comparison_path(TODAY, output_root=output_root)`),所以**永远和 analysis_input 同桶**,不再割裂。

## 2. 两条流(显式边界,不混)
| 流 | EGS 调用 | 桶 | 内容 | 下游读 |
|---|---|---|---|---|
| **生产流** | `python A-EGS/egs_main.py --as-of <d>`(缺省 output-root) | `result/a_short/<as_of>/` | analysis_input / candidates / snapshot / egs_weight_comparison | `runners/forward_tracker.py` 从此读 analysis_input(`LIVE_RESULT_ROOT`);`weekly_screening.ps1` 走此流 |
| **分析流(我们用)** | `python A-EGS/egs_main.py --as-of <d> --backtest-mode --l3-mode pit --output-root research/results/a_short` | `research/results/a_short/<as_of>/` | 上述 + **weekly_m67.json**(周报 pipeline)+ account.json | 你看 M6.7 |

**为什么生产桶里不放周报 M6.7**:`result/a_short/` 受 CLAUDE.md 保护(AI 禁写)、且周报 pipeline 的写盘护栏 `_reject_production_output_path` 硬拒任何 `result/a_short/` 路径。生产流本就不跑 pipeline,故无冲突。分析流的桶是 `research/results/a_short/`(`results` 带 s,**不触发**该护栏,测试 `test_analysis_flow_bundle_is_guard_safe` 钉死)。**这是有意保留的 legacy/生产边界**——不把生产 weekly_screening.ps1 / forward_tracker 迁到 research,二者维持 result/a_short。

## 3. 分析流落到一个桶的调用(我们的流程)
设 `AS_OF=<交易日>`,`OUT=research/results/a_short/$AS_OF`:
1. `python A-EGS/egs_main.py --as-of $AS_OF --backtest-mode --l3-mode pit --output-root research/results/a_short`
   → `$OUT/{analysis_input.json, candidates.csv, snapshot.json, egs_weight_comparison.json}`(comparison 自动同桶)。
2. `python -m runners.a_short_weekly_pipeline --as-of $AS_OF --analysis-input $OUT/analysis_input.json --iv-feed research/results/a_short_iv_feed_<feed_date>/iv_feed.json --account $OUT/account.json --out $OUT/weekly_m67.json --confirm-fetch-authorized`
   → `$OUT/weekly_m67.json`。
路径函数 `run_bundle_dir / analysis_input_path / weight_comparison_path / weekly_m67_path / account_path(AS_OF, output_root="research/results/a_short")` 给出上述位置。

## 4. 边界
- IV feed 市场级跨 run 复用 → **不进 run 桶**,仍 `research/results/a_short_iv_feed_<date>/`,用 `--iv-feed` 引用。
- 本约定只规整产物落盘位置 + 让 comparison 与选股同桶,不改任何选股/打分/分析逻辑。
- 唯一代码改动:egs_main comparison-diff 路径改用 `weight_comparison_path(TODAY, output_root=output_root)`(动生产 egs_main,仅路径,无打分变更)。
- 生产流(weekly_screening.ps1 / forward_tracker / CURRENT.md 命令)**不改**——显式 legacy 边界。历史散落产物不迁移,新 run 起按约定。
