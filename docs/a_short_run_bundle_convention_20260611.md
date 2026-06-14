# A-short 单次 run 产物统一文件夹约定

**日期**: 2026-06-11(2026-06-11 Codex 复审后修正:从"硬编码 research/results"改为"从 run 的 output_root 派生 + 两条流显式边界")
**动因**: 用户要求把每次 run 的选股 + EGS comparison-diff 放在一个文件夹里方便找(此前 comparison-diff 落 research/results、选股落 result/a_short 或 backtest/generated,割裂)。
**单一真相源**: `engine/a_short_run_paths.py`(纯路径函数,可测)。

## 1. 约定:桶 = `<该 run 的 EGS --output-root>/<as_of>/`
`a_short_run_paths.resolve_base_root` **逐字镜像** `egs_main.export_analysis_input` 的解析:`--output-root`(绝对或项目相对)优先,缺省 = `result/a_short`。一个 run 的**选股 + EGS comparison-diff** 落到 `<base_root>/<as_of>/` **同一个桶**(周报 M6.7 落点**按流分**:分析流与选股同桶;**生产流是有意 hybrid**——选股 result/a_short、M6.7 advisory research lane,run_lineage 绑定,见 §2 / §4 Slice 3b-2 条)。comparison-diff 由 egs_main **从同一个 output_root 派生**(`weight_comparison_path(TODAY, output_root=output_root)`),所以**永远和 analysis_input 同桶**,不再割裂。

## 2. 两条流(显式边界,不混)
| 流 | EGS 调用 | 桶 | 内容 | 下游读 |
|---|---|---|---|---|
| **生产流** | `python A-EGS/egs_main.py --as-of <d>`(缺省 output-root) | `result/a_short/<as_of>/` | analysis_input / candidates / snapshot / egs_weight_comparison | `runners/forward_tracker.py` 从此读 analysis_input(`LIVE_RESULT_ROOT`);`weekly_screening.ps1` 跑此流的 egs_main 选股(并自 Slice 3b-2 另跑 M6.7 advisory → research lane,见 §为什么) |
| **分析流(我们用)** | `python A-EGS/egs_main.py --as-of <d> --backtest-mode --l3-mode pit --output-root research/results/a_short` | `research/results/a_short/<as_of>/` | 上述 + **weekly_m67.json**(周报 pipeline)+ account.json | 你看 M6.7 |

**为什么生产桶里不放周报 M6.7**:`result/a_short/` 受 CLAUDE.md 保护(AI 禁写)、且周报 pipeline 的写盘护栏 `_reject_production_output_path` 硬拒任何 `result/a_short/` 路径。周五 `weekly_screening.ps1` 自 Slice 3b-2 跑 M6.7 advisory,但 M6.7 写 research lane(护栏硬拒 `result/a_short/`),生产桶仍不含 M6.7,故无冲突。分析流的桶是 `research/results/a_short/`(`results` 带 s,**不触发**该护栏,测试 `test_analysis_flow_bundle_is_guard_safe` 钉死)。**这是有意保留的 legacy/生产边界**——不把生产 weekly_screening.ps1 / forward_tracker 迁到 research,二者维持 result/a_short。

## 3. 分析流落到一个桶的调用(我们的流程)
设 `AS_OF=<交易日>`,`OUT=research/results/a_short/$AS_OF`:
1. `python A-EGS/egs_main.py --as-of $AS_OF --backtest-mode --l3-mode pit --output-root research/results/a_short`
   → `$OUT/{analysis_input.json, candidates.csv, snapshot.json, egs_weight_comparison.json}`(comparison 自动同桶)。
2. `python -m runners.a_short_weekly_pipeline --as-of $AS_OF --analysis-input $OUT/analysis_input.json --iv-feed research/results/a_short/iv_feed_<feed_date>/iv_feed.json --account $OUT/account.json --out $OUT/weekly_m67.json --confirm-fetch-authorized`
   → `$OUT/weekly_m67.json`。
路径函数 `run_bundle_dir / analysis_input_path / weight_comparison_path / weekly_m67_path / account_path(AS_OF, output_root="research/results/a_short")` 给出上述位置。

## 4. 边界
- IV feed 市场级跨 run 复用 → **不进 run 桶**(不是某次 `<as_of>/` 桶),归入 a_short lane 的 `research/results/a_short/iv_feed_<date>/`(2026-06-11 从 research/results 顶层归档至此),用 `--iv-feed` 引用。
- 本约定只规整产物落盘位置 + 让 comparison 与选股同桶,不改任何选股/打分/分析逻辑。
- 唯一代码改动:egs_main comparison-diff 路径改用 `weight_comparison_path(TODAY, output_root=output_root)`(动生产 egs_main,仅路径,无打分变更)。
- **Slice 3b-2**:`weekly_screening.ps1` 增跑 M6.7 advisory —— egs_main 选股仍落 `result/a_short/<as_of>/`;M6.7 落 `research/results/a_short/<as_of>/weekly_m67.json`(消费同 as_of 选股的 `analysis_input.json` + 市场 IV feed `research/results/a_short/iv_feed_<as_of>/iv_feed.json` + 可选 `-Account` available_cash;weekly_m67.json 的 `run_lineage` 字段记 analysis_input / selection_bucket / iv_feed / account_status / sizing_mode,机器可读绑定 selection↔M6.7;无账户时 sizing_mode=`observation_only_no_account` 且 .md 带 no-sizing banner,schema `a_short_weekly_report.schema.json` 校验)。**有意 hybrid**:selection 生产桶、advisory M6.7 research lane(M6.7 非生产、护栏硬拒 result/a_short)。`forward_tracker` / CURRENT.md 命令不改;历史散落产物不迁移。

## 5. lane 归档约定(2026-06-11)— 未来运行结果按 lane 落
**约定:每条 lane 的研究/运行结果落 `research/results/<lane>/`**(`lane ∈ {a_short, a_long, us_short, us_long}`;`engine/a_short_run_paths.lane_output_root(lane)`)。
- **a_short**:已用(本约定 §1-§4;run bundle = `research/results/a_short/<as_of>/`,IV feed = `research/results/a_short/iv_feed_<date>/`)。2026-06-11 把 pre-convention 的 `a_short_iv_feed_*`/`a_short_iv_feed_probe_*`/`a_short_weekly_20260609`/`egs_weight_comparison_20260609.json` 从 research/results 顶层归入 `research/results/a_short/`。
- **us_short / us_long**:绿地(无历史、无耦合)。建美股 runner 时从第一天直接写本 lane。
- **a_long**:**增量迁移**。现存 a_long 产物**留在 research/results 顶层不动**(整条 a_long 链 + ~20 测试 + prereg 按硬编码路径互读/读 fixture/作 provenance,物理搬迁会断,需单独审查迁移);**新的 a_long 切片**建时把输出 + 读上游路径一起指到 `research/results/a_long/`(配套改 + 测试)。各 lane 文件夹 README 记录此边界。
- **不动 `result/`**:它是代码引用的生产/回测数据根(forward_tracker / backtest / reaudit / egs_main 生产 output-root),与本 lane 归档无关。
