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

## 2026-07-28 追加：第六刀 6B（候选价格单一权威 + 官方档输入时钟加严）

本节记录 6B 的落地与独立审查结论。6B 与 6A 同属第六刀，按 `AGENTS.md §交接记录` 追加在此，不新建文件。

### 改了什么

- `runners/a_short_weekly_pipeline.py::normalize_candidate` 的 `close` 由 EGS 快照 `quote.close` 改取 `price_series[-1]["close"]`，与该候选 `ma5/ma10/ma20/support/atr` 所用的同一根已结算 bar 同源；EGS 快照价降级为纯 lineage，不再是第二价格权威。
- `engine/data/analysis_input_contract.py` 新增 `official_input: bool = False` 关键字（贯穿 `validate_analysis_input_file` / `validate_analysis_input_contract` / `_validate_pit_invariants`）。为真时官方输入的每个候选必须存在 `quote.source_trade_date` 且恒等 `price_data_through`；为假时保持既有的「只拒更新、允许更旧」上界校验，research / hermetic fixtures 不受影响。
- 新增共享谓词 `runners/a_short_weekly_pipeline.py::_is_official_analysis_input_path`，把原先在 `main()` 里重复两遍的 `result/a_short` 路径判定收成一处，并由它同时驱动新的严格档与既有的官方门（损坏即 FATAL、必须有 `run_identity`）。
- `schemas/a_short_m67_effect_contract.json` 的 `decision_predicate_sha256` 中 `runners/a_short_weekly_pipeline.py` 一项随谓词变化更新（该值是谓词哈希，不是文件字节哈希）。

### 为什么改

条目 14：候选行用 EGS 快照价、技术指标用 pipeline 自抓序列，两侧口径不对称；契约只校验 `source_trade_date <= price_data_through`，允许更旧。在 `intraday_prior_settled` 模式下候选价与指标可能不属于同一日，低吸/突破判断会失真。修法双腿：契约加严负责快失败，价格取序列负责即使契约放行也不会用错价。

### 验证命令与结果

- 审查方亲跑 focused 超集 `.toolsun_unittest_with_repo_pythonpath.cmd tests.schema.test_analysis_input_contract tests.test_a_short_effect_contract tests.test_a_short_weekly_pipeline` = `538 OK / 46.8s / exit 0`，与执行方计数一致；按 `AGENTS` rule 4 未重跑执行方已记账的 `full_pack_ledger run a_short = 2072 OK / 205.8s / exit 0`。
- 真数据探针：用真校验器对主树 13 个官方 `analysis_input` 与 27 个 `result/a_short/backtest/generated/*` 产物逐个跑 `official_input=False/True` 对照。仅 `20260727` 两档皆过；6 个批次由 lenient-PASS 翻成 official-REJECT；回测子树 27/27 会被判官方，但因缺 `run_identity` 早被既有官方门 FATAL，故不可达。
- 桌面验收 ③（`close` 与 `ma5/ma10/ma20/support/atr` 恒同源同日）由构造成立：`_candidate_price_clock` 与 `:4374` 的 `observed candidate price clock != price_data_through` FATAL 已把序列末根钉在 `price_data_through`。`close=None` 的反方向不可达：`cands = eligible_cands` 之前已做 `_candidate_price_exclusion` 与 `len(series) < MIN_PRICE_OBS` 整批 FATAL；持仓腿 `:511` 同门。
- 官方腿真接线：`runners/weekly_screening.ps1:428` 传的正是 `result/a_short/<AsOf>/analysis_input.json`。
- 文档治理三包 `72 OK`。

### 审查结论（含同日更正）

首轮判 PASS 并已提交 `417c7fc3`（fast-forward 进 master）。独立对抗 agent 在结论发出后返回，坐实一条被判轻的缺陷，同日更正为 **Pass-with-Required**（`83ef31a6`）：官方档等式在输入未声明价格钟时，靠 `_parse_date8` 回落链拿 `trade_date` 顶替价格钟，于是拿候选 bar 日去比决策日，把管线自身支持的 `clock_explicit=False`（从观测 bar 反推钟）模式在 `:4097` 静默切掉。代码不回滚（纯 fail-shut，不产生错误选股），缺陷转 open Required。完整机制、实测、两条腿修法与四条 closure tests 见 `docs/system_risk_register.md#R-ASHORT-KNIFE6B-OFFICIAL-CLOCK-FALLBACK-ANCHORS-TO-DECISION-DATE`（单一来源，本文件不复述）。

### 失效的旧结论

- 「6B 的实测前置已由 20260727 单批次满足」失效：实测口径应写成「相等只自 producer 开始写 `price_data_through` 之后成立」，13 个官方产物里仅该批次是当代格式。
- 审查方首轮把上述缺陷记为 Optional「记录口径偏窄、当代 producer 恒写故不可达」的定性作废——不可达的只是「当代产物」这一半，被切掉的是管线的反推钟模式。
- 本轮执行方 SESSION_LOG 的 `handoff=updated` 与仓库状态不符：`417c7fc3` 未触及 `docs/handoff/`，本节即补记。

### 下一步注意事项

- 第六刀**未闭**：合并门要求 6A、6B 测试全过且 6B 的加严形态有实测依据在案，现有一条 open Required 悬着。修完该 Required 并复审通过后，再跑桌面文档的「本刀合并验证」全局不变量（所有事实类日期字段 ≤ `price_data_through` 且候选侧恒等），才可记「第六刀完成」。
- 不改 provider live fetch、不碰真钱与 ship-gate；`result/a_short/<YYYYMMDD>/` 仍不可写。
