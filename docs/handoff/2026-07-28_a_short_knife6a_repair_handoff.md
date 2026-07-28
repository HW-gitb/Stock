# A-short 第六刀 6A 修复交接（组合事实时钟与北向因子退役）

## 范围与结论

本轮响应 Claude Code 对 `R-ASHORT-KNIFE6A-NORTHBOUND-RETIREMENT-CRASHES-EGS-AND-LEAVES-PARTIAL-RESIDUE` 的 FAIL。审查判断成立：原修复虽已把组合事实改为价格时钟，但北向因子只删除了部分受控阈值，EGS 仍会在每个候选上读取不存在的 `northbound_threshold_pct` 并崩溃。

已完成 A–G、Required I1/H1 与一条 Optional（均待 Claude Code 独立审查）：

- 完整退役北向组合因子：EGS factor row、analysis-input enum、portfolio facts、runtime policy/schema、provider `hk_hold` 调用、来源标签、效应契约及测试夹具均同步删除；历史 D-tier probe 仍只作为历史证据保留。
- 组合事实时钟必须等于 `price_data_through`。在价格 bar 最终确定后才生成龙虎榜/大宗共用交易日窗口，避免盘中 decision date 混入价格事实窗口。
- provider 输出 `ok`、`not_published`、`unavailable` 三态，并写入周报 `portfolio_risk.fact_fetch`。异常或显式 `unavailable` 都转换为 fail-closed facts，已有持仓会进入 `manual_review_required`；空表不伪造零值，也不覆盖有效输入事实。
- effect contract 现在不仅比较哈希，也逐项比较 `runtime_policy_paths` 和 `runtime_policy_leaf_readers` 正文；植入一个 inventory 外 governed leaf 会报错。
- I1：`fact_fetch` 对已发布 weekly schema 保持可选，未改写 `research/results/a_short/20260727/weekly_m67.json`；新 builder 仍以 `_validate_portfolio_risk` 强制该字段的状态和价格时钟。
- H1：静态 AST 守卫扫描 `A-EGS/`、`engine/`、`runners/` 中 `_RUNTIME_CONFIGURATION` 及其 alias 的所有字面量下标读点，并逐段核对 runtime preset；删除真实的 `margin_threshold_pct` 必须转红。
- Optional：对 `runtime_policy_leaf_readers` 补独立正文篡改反向测试，不再只由 paths 测试间接覆盖。
- 执行流程：唯一权威 `docs/pre_codex_self_review_checklist.md` 新增 repair-closeout matrix；SESSION_LOG 的 post-adoption 守卫要求每个未来 `修复` entry 留 `matrix=`、`register=`、`handoff=`、`focused=`、`full-lane=` 闭环字段。

## 验证

- 6A 原有 5 项验收通过：不同 decision/price clock 的 facts 与龙虎榜窗口同为 `20260608`；三态可见；两类 unavailable 均 fail-closed；契约正文反向守卫可触发。
- I1 回归同时证明历史产物 schema-valid、新 builder 缺 `fact_fetch` 必红；H1 真实 preset-delete 植入必红；Optional 的 leaf-reader-only 植入必红；流程闭环 guard 的缺字段植入必红。
- `validate_static_contract()` 通过；官方 ledger `a_short = 2070 OK / 228.3s`；`tests/phase6/test_egs*.py` 仍是既有 `1 fail / 9 errors` 基线；`git diff --check` clean（仅 CRLF warning）。
- `tests/phase6/test_egs*.py` 回到既有 `1 fail / 9 errors` 基线；本刀引入的 8 个 `northbound_threshold_pct` KeyError 已消失。

## 未完成与下一步

风险条目仍为 open P1，不能提交，直到 Claude Code 独立审查 PASS。I1/H1/Optional 已实现；下一步是按清单只跑一次官方 `a_short` full lane，并保留 `tests/phase6/test_egs*.py` 的既有 `1 fail / 9 errors` 基线。不改 6B、provider live fetch、生产交易或 ship-gate。

## 失效的旧结论

“6A 仅需时钟接线和删 policy 键即可收口”已失效。删除 governed leaf 必须沿符号轴和语义轴清扫所有生产/契约消费者，并以反向守卫阻止契约正文残留。
