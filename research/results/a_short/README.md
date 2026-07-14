# research/results/a_short/ — A-short lane 结果归档

A-short(A 股短线)的研究/运行结果。约定见 `docs/a_short_run_bundle_convention_20260611.md` + `engine/a_short_run_paths.py`。

**内容:**
- `<as_of>/`(如 `20260613/`)= 单次分析运行的 per-run bundle(analysis_input/candidates/snapshot/egs_weight_comparison/weekly_m67.json/.md),由 EGS `--output-root research/results/a_short` + 周报 pipeline 产出。
- `iv_feed_<date>/` = 市场级 50ETF IV feed(跨 run 复用,不在某次 run bundle 内)。
- `iv_feed_probe_<date>/` = IV 可行性探测产物。
- `weekly_<date>/`、`egs_weight_comparison_<date>.json` = pre-convention 的一次性产物(2026-06-11 从 research/results 顶层归入本 lane)。
- `entry_funnel_calibration_<date>/` = hash-bound、预注册的本地 funnel / IV / overlay 校准结果；seen 与 future confirmatory 分离，不是生产阈值或 ship-gate 证据。

**未来**:新的 a_short 运行自动落到这里(per-run bundle 约定)。生产选股仍在 `result/a_short/<date>`(代码引用的生产根,不在此)。
