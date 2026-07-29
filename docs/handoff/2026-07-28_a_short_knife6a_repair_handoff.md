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

## 2026-07-28 追加：第六刀 6B Required 收口（官方输入必须自报价格钟）

承接上一节。上一节记的 Pass-with-Required，其 Required 已在同日修复并通过独立复审，本节记收口结果；缺陷正文与 closure evidence 仍只在 `docs/system_risk_register.md#R-ASHORT-KNIFE6B-OFFICIAL-CLOCK-FALLBACK-ANCHORS-TO-DECISION-DATE`，此处不复述。

### 改了什么

- `engine/data/analysis_input_contract.py`：`official_input=True` 时要求顶层或 `source.clocks` 显式声明 `price_data_through`，缺失即报 `official input must declare price_data_through`；非官方档的 `trade_date` 回落链原样保留。
- 新增 `is_official_a_short_analysis_input_path()` 于契约模块，收紧为「恰好 `result/a_short/<YYYYMMDD>/analysis_input.json` 两段路径」；`runners/a_short_weekly_pipeline.py` 里同名的本地私有谓词删除并改调它。`validate_analysis_input_file` 在未显式传 `official_input` 时自判。
- `A-EGS/egs_main.py::export_analysis_input` 在写盘前按同一路径谓词自校验，producer 不再能发布漂移的正式产物。

### 为什么改

原实现把「官方 lane」做成逐调用点 opt-in，且在输入未声明价格钟时靠回落链拿决策日顶替，于是等式锚错日子、把管线支持的 `clock_explicit=False`（从观测 bar 反推钟）模式在输入校验阶段就切掉；同时 `result/a_short/backtest/generated/**` 被误判为官方。

### 验证命令与结果

- 审查方亲跑 focused 超集 `.toolsun_unittest_with_repo_pythonpath.cmd tests.schema.test_analysis_input_contract tests.phase6.test_egs_analysis_input_contract tests.test_a_short_effect_contract tests.test_a_short_weekly_pipeline` = `552 OK / 54.1s / exit 0`；执行方已记账 `full_pack_ledger run a_short = 2072 OK / 258.2s / exit 0`（rule 4，审查方不重跑）。
- 正控 + 反控直打契约（真产物 `result/a_short/20260714/analysis_input.json`）：宽松档仍 PASS；官方档报新的 must-declare；补 `price_data_through=20260713` 后官方档 PASS；改成 `20260710` 后官方档仍拒。路径谓词逐例：官方日期目录 True、`backtest/generated` False、`snapshot.json` False、非日期目录 False、`..` 归一化后 True。旧符号 `_is_official_analysis_input_path` 全仓零残留。
- `test_a_short_effect_contract` 在超集内且绿，故本轮未动 `decision_predicate_sha256`。

### 失效的旧结论

- 上一节「官方档只在 weekly pipeline 一个消费者启用」已失效：判定下沉后 `validate_analysis_input_file` 的全部读者同门，EGS producer 亦自校验。
- 「`_is_official_analysis_input_path` 对回测子树 overclaim（当前不可达）」已失效：谓词收紧后回测子树明确非官方，并有具名测试钉住。

### 合并时的一处处置（记给下一个接手的人）

执行方本轮基线停在 `417c7fc3`（缺审查方的 `83ef31a6`/`93ec35bc`），因此重新写了一份**同 Required ID** 的 register 条目。rebase 到 master 后两份并存，已在提交前并成一份（保留审查方那份的机制/实测，折入执行方的 Required A/B 收口事实），无内容丢失。教训：执行方开工前应先把工作树 rebase 到 master，否则每轮都会在 register 制造同 ID 双写。

### 下一步注意事项

- 第六刀仍未记「完成」：还差桌面文档的「本刀合并验证」全局不变量（所有事实类日期字段 ≤ `price_data_through` 且候选侧恒等，只有 `decision_as_of` 可更晚）跑一次。
- 不改 provider live fetch、不碰真钱与 ship-gate；`result/a_short/<YYYYMMDD>/` 仍不可写。

## 2026-07-29 追加：第七刀（突破指标分歧可见性，条目 13）

本节记录第七刀。它与 6A/6B 同属桌面 `ashort_r1.md` 这一批，按 `AGENTS.md §交接记录` 的「默认追加、不轻易新建」续在本文件，本文件实际已是该批次的主 handoff。缺陷/判据正文不在此复述。

### 改了什么

- `runners/a_short_phase5_engine.py`：新增纯函数 `breakout_source_agreement(inp, ind)`，返回 `agree_true / agree_false / egs_only / pipeline_only` 四态，**只回类别、不回价格或均线**。`entry_type` 的突破分支改成 `breakout_source_agreement(...) == "agree_true"`，与门条件逐字未变。`build_m67_report` 把该枚举写进 `machine`，分歧时给 `触发条件` 追加「两套技术指标口径不一致，按保守口径处理」；`validate_m67_consistency` 强制枚举合法且与该提示一致。
- `runners/a_short_weekly_pipeline.py`：`_attach_breakout_source_disagreement_notices` 在现金/组合后处理合法重写 `触发条件` 之后把提示补回；`summarize_breakout_source_agreement(reports)` 产出本批 X/Y 与三态结论，**只读入参、不读不写任何跨周状态**；阈值常量从 `_PHASE5_POLICY` 取。
- `runners/a_short_m67_render.py`：周报 md 多一行「突破指标口径」横幅（只对候选行，持仓行已被 `cand_reports` 排除）。
- 阈值 `breakout_source_disagreement_rate_threshold_pct = 10.0` 落进两份 preset + policy schema `required` + `engine/a_short_runtime_config.py::_validate_m67`（0–100 边界）+ effect contract 的 leaf-reader 清单与 `runtime_policy_bindings`。

### 为什么改

与门是保守的，任一侧不同意只会掉回低吸/观察，**不会错误建仓**；缺的是分歧不可见——「确实没形态」和「两套数据打架」在报告里是同一句话。它同时是第 15 刀入场归因的前置。按 2026-07-28 用户裁决，只做**无状态本周自判**那一层；跨周累积 + 自动裁决属预冻结期禁建的冻结件，见桌面 `ashort_r1.md` 第 0 节。

### 验证命令与结果

- 审查方亲跑两包，覆盖全部改动符号：`tests.test_a_short_weekly_pipeline + tests.test_a_short_effect_contract + tests.test_a_short_runtime_configuration` = `531 OK / 93.4s / exit 0`；`tests.test_a_short_phase5_engine + tests.test_a_short_m67_render` = `164 OK / 1.4s / exit 0`。执行方已记账 `full_pack_ledger run a_short = 2075 OK / 276.5s / exit 0`，按 rule 4 未重跑。
- **等价性亲证（本刀最关键的一条）**：把改前的 `entry_type` 实现并排放回，对 `breakout × close(含 None) × ma10/ma5/ma20/support(含 None 与 0)` 共 432 组合逐一对比，**零差异**；另 `derived=None` 旧实现抛 `AttributeError`、新实现返回「观察」，只增稳健、不改选股。
- 植入控制：同一 1/15 分歧批次，阈值 10.0 → 「零星分歧」、5.0 → 「分歧显著」，证明结论确实读 runtime policy 而非硬编码；2/20（恰好 10.0%）→ 「分歧显著」，边界是 `>=`。marker 缺失 / 非法 / 空批一律返回 `None`、不渲染横幅（fail-closed，不伪造干净结论）。

### 失效的旧结论

桌面原稿第 7 刀第 4 点「汇总层加一个批次计数」已被 2026-07-28 用户裁决升级为「无状态三态自判 + md 横幅 + 阈值事前冻结」，桌面文档已同步改写；本实现按改写后的方案落地。

### 下一步注意事项

- 三条 Optional（渲染器↔pipeline 循环依赖、effect contract 两行哈希缩进漂移、「零星分歧」中间态无测试且 `持有` 行的提示一致性不被 validator 覆盖）见同日 `docs/SESSION_LOG.md` 顶部 entry 的 `Next`；均不阻断。
- 这盏灯**只写不读**：任何把 `breakout_source_agreement` 接进判定的改动都是口径变更，须单独立项（桌面第 7 刀第 5 点）。
- 跨周累积版在设计定稿前不做，判据见桌面第 0 节。
