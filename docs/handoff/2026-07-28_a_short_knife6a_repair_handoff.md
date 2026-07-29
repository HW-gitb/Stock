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

## 2026-07-29 追加：第六刀合并验证完成

第六刀完成：本刀合并验证已在完整 synthetic 周报通过。断言 portfolio_risk.fact_as_of、候选 quote.source_trade_date、实际消耗价格序列末 bar、dragon_list/block_trade window_dates 最大值全部不晚于 price_data_through；候选 quote.source_trade_date 恒等于 price_data_through，只有 decision_as_of 可以更晚。第六刀不改 provider live fetch、真钱或 ship-gate，正式 result/a_short/<YYYYMMDD>/ 仍不可写。

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

## 2026-07-29 追加：第七刀三条 Optional 收口

### 改了什么

- `summarize_breakout_source_agreement` 与 `BREAKOUT_SOURCE_DISAGREEMENT_RATE_THRESHOLD_PCT` 从 `runners/a_short_weekly_pipeline.py` 搬进 `runners/a_short_m67_render.py`（render 自己 `load_runtime_configuration()`），渲染横幅不再反向 import pipeline；`engine/a_short_effect_contract.py::_runtime_policy_leaf_readers` 新增 render 这个 `_PHASE5_POLICY` 读点，契约的 leaf-reader 映射跟着指向 render。
- `validate_m67_consistency` 里的分歧一致性检查从 `if isinstance(rule6_gate, dict):` 块中去缩进，覆盖到 gate 缺失的报告。
- 中间态 `零星分歧` 补 1/11 用例；`schemas/a_short_m67_effect_contract.json` 两行哈希缩进归位。

### 验证命令与结果

- 审查方亲跑最小覆盖包 `.toolsun_unittest_with_repo_pythonpath.cmd tests.test_a_short_m67_render tests.test_a_short_phase5_engine tests.test_a_short_effect_contract tests.test_a_short_weekly_pipeline` = `687 OK / 46.0s / exit 0`。按用户本轮指令未起独立 agent、未跑全量（风险分级=低危：纯搬家 + 测试补齐，不新增也不改变 fail-closed 判定）。
- 零残留：`weekly_pipeline import summarize_breakout_source_agreement` 全仓 0 命中；`_PHASE5_POLICY` 在 `weekly_pipeline` 0 命中。

### 失效的旧结论

- 上一节 Optional① 的修法描述「移到 render 侧即解（循环依赖）」**不完整**：`a_short_m67_render.py:734` 本来就有一条延迟 import pipeline（自带「避免模块级循环依赖」注释），所以模块对至今仍互相依赖；本刀只拆掉了 knife 7 自己新加的那条边。剩下那条是既有的，不属本刀范围。
- 新增的 held 行 tamper 测试**不能**证明去缩进生效：实测该报告的 `rule6_gate` 就是 dict，旧代码同样会红。去缩进本身是对的（覆盖面变宽），但今天实际是防御性的——`build_holding_report` 不写该 marker，所以 gate 缺失的报告拿不到 marker、检查照样跳过。

### 下一步注意事项

一条 open Required 见 `docs/system_risk_register.md#R-ASHORT-KNIFE7-EFFECT-CONTRACT-CONSUMER-REF-NAMES-A-GONE-CONSUMER`：契约 `consumer_refs` 仍点名已搬走的 `weekly_pipeline`。`consumer_refs` 是自由散文、无任何 hash 或测试覆盖，建议一并按同类扫净并加守护。

## 2026-07-29 追加：consumer_ref 漂移按根因焊死（第七刀 P3 收口）

### 改了什么

- `engine/a_short_effect_contract.py::static_contract_error`：对每个 `must_affect_result` 的 runtime-policy binding 新增机器门——`consumer_refs` 里每一条都必须是含 `::` 的结构化定位符，且必须是该 policy path 实际算出的 leaf reader 之一的前缀，否则返回 `consumer_ref is not an actual reader: <ref>`。
- `schemas/a_short_m67_effect_contract.json`：六条 binding 的 `consumer_refs` 全部由散文（`X imports Y`）迁成 `file::symbol`；`phase5_thresholds` 指向 `runners/a_short_m67_render.py::_PHASE5_POLICY`，不再指向已搬走的 weekly_pipeline；`industry_trend_classifier` 由一句混合散文拆成三条定位符。
- `tests/test_a_short_effect_contract.py`：植入旧的（已搬走的）定位符必须转红。

### 为什么改

上一轮把 summarizer 搬进 render 后，契约的机器腿（leaf readers）跟着改了，散文腿（consumer_refs）没改，于是契约自称的消费者在 grep 下 0 命中。`consumer_refs` 此前是自由散文、不被任何 hash 或测试覆盖，每次搬家都会再漏一次——所以修法是加机器门 + 整类迁移，不是改那一行字。

### 验证命令与结果

- 审查方亲跑最小覆盖包 `.toolsun_unittest_with_repo_pythonpath.cmd tests.test_a_short_effect_contract` = `26 OK / 39.8s / exit 0`；执行方已记账 `full_pack_ledger run a_short = 2077 OK / 243.7s / exit 0`（rule 4，未重跑）。
- 审查方自写探针，把新门按三种真实漂移形态各打一遍：**不存在的文件**、**缺 `::` 的散文**、**张冠李戴的符号**——全部被拒并在错误串里点名；基线 `static_contract_error() = None`。
- 风险分级=低危（治理契约 + 一道静态断言，不碰引擎/选股/provider/PIT）；按用户指令未起独立 agent、未跑全量。

### 失效的旧结论

上一节写的修法「把 `:469` 改成 render」只是表面；实际采用的是根因修法（机器门 + 整类迁移）。另：执行方在 register 顶部新开了一节 `## 2026-07-29 closure update` 平行小节，合并时已收掉——closure 事实并进条目本身，避免 register 长出一条与条目并行的流水账（§E route-doc 单态）。

### 下一步注意事项

两条 Optional（均不阻断）：`binding["consumer_refs"]` 无 `.get` 兜底，将来某条 binding 翻成 `must_affect_result` 却忘加该键会抛 KeyError 而非返回契约错误；前缀匹配放行退化写法 `file::`（空符号，实测通过），可收紧成「`::` 后非空」。

## 2026-07-29 追加：第八刀 8A（P4a 终局差异门 + checkpoint 契约单一来源）

### 改了什么

- `engine/a_short_experiment_admission_registry.py::_p4_admission` 的 `statistical_contract` 新增 `nonoverlap_block_minimums {"12":6,"24":12,"36":12}`。
- `engine/a_short_overlay_adjudication.py` 新增 `_checkpoint_contract()`：从已封 admission 一次读出 checkpoint / difference / 非重叠块三组门，形状不合（数量、排序、键集、正整数）即抛 `OverlayAdjudicationError`。`_adjudicate` 删掉硬编码的 12/24/36/6/12 改用它，并把 **terminal difference 门提到所有终局 verdict 之前**；`build_public_summary` 的 H5/H20 状态、`_public_failed_gates` 的档位、`_summary` 的 `checkpoints`/`checkpoint_progress` 也全部由同一份契约推导。

### 为什么改

条目 5：36 周检查点此前只对晋级要求 `difference_minimums["36"]`，`do_not_promote` 与 `inconclusive_retired_for_epoch` 两条**终局**返回没有这道门 —— 政策分离证据不足时也能退役 epoch。12/24 两档都拦了所有结论，唯独 36 档只拦晋级，代码自身不自洽。

### 验证命令与结果

- 审查方亲跑 `tests.test_a_short_overlay_adjudication + tests.test_a_short_experiment_governance` = `38 OK / 4.5s / exit 0`，`tests.test_a_short_experiment_admission_registry` = `12 OK / 0.7s / exit 0`；执行方已记账 `full_pack_ledger run a_short = 2079 OK / 211.1s / exit 0`（rule 4，未重跑）。
- **审查方探针（本刀的核心不变式：改 registry 必须让结论变）**：36 周 / 18 差异 / 负面数据，基线 `do_not_promote`；`difference_minimums["36"]` 改动能翻转结论、`nonoverlap_block_minimums["24"]` 改成 999 变 `continue_accumulating` —— 两者确被读；**`nonoverlap_block_minimums["36"]` 改成 999 结论纹丝不动 —— 没被读**（见下方 Required）。
- 风险分级=comparison-only 低危：`_adjudicate` 开头 `evidence_counts_toward_clock` 早返回，预冻结期任何终局 verdict 都打不出来；这是解冻后才咬人的潜伏缺陷。按用户指令未起独立对抗 agent。

### 失效的旧结论

桌面稿把条目 5 写成「P4 对比轨可以在样本不足时提前给出淘汰结论」，读起来像现行风险；实际 `_adjudicate` 里有 `# Pre-freeze evidence is audit-only: never promote, retire or judge on it.`，今天打不出来。桌面第 8 刀已同步改写为「解冻后才咬人的潜伏缺陷」。

### 下一步注意事项

- 一条 open Required：`docs/system_risk_register.md#R-ASHORT-KNIFE8A-TERMINAL-BLOCK-MINIMUM-DECLARED-BUT-NEVER-READ`（36 周块下限声明了却无读点）。
- 一条同类 Optional（非 8A scope，留给 8B/8C/8D1）：统计阈值仍是第二份副本 —— 把 `preliminary.negative_mean_delta_pp_max` 改成 `-99.0`，36 周负面数据仍判 `do_not_promote`，因为代码里写死 `-.25`；`mean_delta_pp_min` / `block_win_rate_min` / α 同理。桌面第 8 刀「共同纪律」第 2 条要求的守护测试应覆盖到这些维度。

## 2026-07-29 追加：8A Required 收口 + P4a 阈值全部单一来源

### 改了什么

- `engine/a_short_overlay_adjudication.py`：`_adjudicate` 终局分支补上对称的块门 `if len(blocks) < terminal_blocks: return "continue_accumulating"`（上一节记的 Required）。
- 新增 `_statistical_contract()`：从同一份已封 `p4_stage3_rank_source` admission 读出 `preliminary` / `promotion` / `negative_at_36` 三段的全部数值门，并硬校验形状（有限数、正负号、`signflip_p_max <= 1`、`minimum_months` 必须是 int 而非 bool；任一不合即抛 `OverlayAdjudicationError`）。`_checkpoint_contract()` 改为接受已读契约以免重复读。
- `_adjudicate` 与 `_public_failed_gates` 里原先的 `.25 / .55 / -.25 / .025 / 2.0 / 6 / .20 / 0` 字面量全部替换为契约值 —— 上一节记的 Optional（阈值仍是第二份副本）一并闭掉。

### 验证命令与结果

- 审查方亲跑 `.toolsun_unittest_with_repo_pythonpath.cmd tests.test_a_short_overlay_adjudication` = `28 OK / 6.8s / exit 0`；执行方已记账 `full_pack_ledger run a_short = 2080 OK`（rule 4，未重跑）。
- **等价性亲证（这是本次最关键的一条）**：逐项对照 registry 值与被替换的旧字面量 —— `preliminary.mean_delta_pp_min .25`、`block_win_rate_min .55`、`negative_mean_delta_pp_max -.25`、`promotion.bootstrap_lower_pp_min .25`、`signflip_p_max .025`、`minimum_months 6`、`monthly_cluster_t_min 2.0`、`no_count_rate_pct_max 20.0 → .20`、`negative_at_36.mean_delta_pp_max -.25`、`bootstrap_upper_pp_max 0.0`，**11 项全等、零不等**；新增合取项 `promotion.mean_delta_pp_min 0.25` 不高于 preliminary 同名值，故不收紧。行为保持不变。
- **复现上一轮探针**：`nonoverlap_block_minimums["36"] = 999` 现由「纹丝不动」变为 `continue_accumulating`，Required 坐实已闭。
- **新门的反向控制**：`signflip_p_max = 0` / `negative_at_36.mean_delta_pp_max` 取正 / `minimum_months` 传 bool / `promotion` 整段删除 —— 四例全部抛 `OverlayAdjudicationError`。

### 失效的旧结论

上一节 Optional 里那条演示（“把 `preliminary.negative_mean_delta_pp_max` 改成 -99，36 周负面数据仍判 `do_not_promote`，说明阈值仍硬编码”）**不成立、已更正**：36 周终局读的是 `negative_at_36.mean_delta_pp_max`，根本不读 `preliminary` 那个键；退回 12 周档试，又被 `or not risk_ok` 那条腿盖住。Optional 的**结论**是对的（阈值确曾是第二份副本），但那条演示本身不隔离，别再引用它。

### 下一步注意事项

一条新 Optional：`docs/system_risk_register.md#R-ASHORT-P4A-NEGATIVE-BOUND-VALIDATION-IS-ASYMMETRIC`（P3）——负面终局门的两个界只校验了 `mean_delta_pp_max` 的符号，`bootstrap_upper_pp_max` 不查符号；实测设成 `99.0` 会被接受，并把 mean_delta = -0.1 的温和负面 epoch 从 `inconclusive_retired_for_epoch` 翻成 `do_not_promote`。

## 2026-07-29 追加：A-short 下一步工作单（含待用户裁决的两项治理口径）

本节是给下一位执行者（Codex）的工作单。桌面 `ashort_r1.md` 是这批刀的方案权威，但 **Codex 不读桌面**，所以凡是动手需要的内容，本节都摘全。

### 立刻可做（不依赖任何裁决，按序）

1. **修 `docs/system_risk_register.md#R-ASHORT-P4A-NEGATIVE-BOUND-VALIDATION-IS-ASYMMETRIC`（P3）**：`engine/a_short_overlay_adjudication.py::_statistical_contract()` 对 `negative_at_36["mean_delta_pp_max"]` 校验了符号（取正即抛），对同一道门的 `negative_at_36["bootstrap_upper_pp_max"]` 只查有限数、不查符号。补同侧符号约束 + 一条畸形值反向测试。实测依据：把它设成 `99.0` 验证器照收，mean_delta = −0.1 的温和负面 epoch 就从 `inconclusive_retired_for_epoch` 翻成 `do_not_promote`。
2. **跑第六刀合并门**：断言全局不变量 —— 所有「事实类日期字段」（`portfolio_risk.fact_as_of`、候选 `quote.source_trade_date`、价格序列最新 bar、龙虎榜 / 大宗 `window_dates` 最大值）**全部 ≤ `price_data_through` 且候选侧恒等于它**，只有 `decision_as_of` 可以更晚。通过后才可以记「第六刀完成」——6A、6B、6B Required 都已落地，只差这一条。

### 待用户裁决的两项治理口径（未裁决前不得开工 8B / 8C / 8D1）

**8D0′（挡着 8B 与 8C）——P3b 解锁门的语义**

- 现状：`runners/a_short_final_action_validation_runner.py:54-57` 的 `P3B_EXTERNAL_PUBLIC_SUMMARIES` 只有两条路径（P1 的 `regime_candidate_effect_summary.json`、P2 的 `target_policy_comparison_summary.json`），P5 不在里面；判定是 `external_verdicts >= 2`，今天恰好等价于「两条都必须过」。
- 待裁决：① P5 要不要计入 P3b；② `>= 2` 是「两条固定轨都要过」、「三条里任意两条」还是「三条全要」。
- 为什么必须先定：一旦 P5 进元组而 `>= 2` 不变，同一个数字就无声变成「三取二」，门槛自己放松；先修通 P3b 再决定，等于交付一道语义待定的门。

**8D0″（挡着 8D1）——P5b 的统计口径**

- ① p 值由哪个检验产生。governance 只给了 `formal_alpha_two_sided: 0.025` + `holm_bonferroni: true`，没说检验方法。P4a 的先例是块级 delta 的 sign-flip 随机化，沿用是自然选择，但要显式写进 governance 再实现。
- ② `checkpoints [12,24,36]` 与 `preliminary_*` 阈值的映射（12=初步 / 24=正式 / 36=终局？）。P4a 是这么分的，同样要显式写死。

两项裁决都写进 governance / registry，不在代码里现定；8B、8C、8D1 的验收都引用这份裁决。

### 本轮就地更正的两条 register 状态

- `R-ASHORT-KNIFE6B-OFFICIAL-CLOCK-FALLBACK-ANCHORS-TO-DECISION-DATE`：状态由 `open P2` 补正为 `closed P2`（2026-07-28 已随 `89dd5e90` 修复且复审 PASS，当时只补 closure 段、忘了翻状态）。
- `R-ASHORT-MASTER-LANE-PACK-TWO-PREEXISTING-RED`：关闭。该 finding 量在 `8a9d5d83`，现已不复现 —— 实测 `tests.test_a_short_semantic_risk_contract_docs` = `15 OK`（条目点名的目标 a），目标 b 由当前代码态账本 `a_short 2080 OK` 覆盖。留着它的害处正是它自己警告的那件事：一句陈旧的「这条 lane 本来就红」会让后面每个审查者对真回归打折。

### 第八刀的执行顺序（拍完口径后）

`8A`（已完成并合入）→ `8D0′`（裁决）→ `8B`（P2 target 裁判器 + 公开摘要四字段 + 顺带闭 `R-ASHORT-TEST-PACK-REWRITES-TRACKED-P2-PUBLIC-SUMMARY`）→ `8C`（P3 HAC + P3b 可达性 + 修 `:516` 文件名死分支）→ `8D0″`（裁决）→ `8D1`（P5b 裁判器 + 公开摘要 + 一键周跑接线）。每把子刀的不悬空判据与共同纪律见桌面 `ashort_r1.md` 第 8 刀本刀实施拆分节。

## 2026-07-29 追加：8D0′ / 8D0″ 四项治理口径已由用户裁决（可执行规格）

上一节列为「待用户裁决」的两组口径，2026-07-29 用户裁决「按建议」，全部采纳。本节是可直接施工的规格；**8B / 8C / 8D1 的开工前置就此解除**。四项一律写进 governance / registry，**代码里不得再出现第二份副本**——本批已两次栽在这条（条目 5 的硬编码检查点、8A 的统计阈值）。

### 8D0′-① P5 计入 P3b 的外部旁证

`p5_industry_weight` 加入 P3b 的外部对比轨名单。同时必须修掉那条死分支：`runners/a_short_final_action_validation_runner.py:516` 的判断键是 `industry_weight_comparison_progress_summary.json`，而 P5 实际写出的是 `industry_weight_comparison_summary.json`（`engine/a_short_industry_weight_comparison.py:35`）。这条属 8C 范围。

### 8D0′-② P3b 门槛的语义

- **新语义**：`p3b_ready` 要求「P3 自己有真裁决」**且**「至少 2 条**已实现裁判器**的外部对比轨给出有效当期裁决」。
- **名单从 registry 读**，不再是 `runners/a_short_final_action_validation_runner.py:54-57` 里那个硬编码路径元组。名单每条至少要有：轨 id、公开摘要路径、「裁判器是否已实现」的判据。
- **「已实现裁判器」直接复用现有旗标**，不要新造：`formal_adjudication_implemented`（P2 两轨，`engine/a_short_experiment_admission_registry.py:234,245`）、`formal_hac_adjudication_implemented`（P3，`:260`）、`p5b_implemented`（P5，`engine/a_short_industry_weight_comparison.py:95`）。注意 `p5b_implemented` 目前同时嵌在 governance boundary、私有记录 boundary 与私有 schema 的 `const: false` 里，8D1 计划本来就要把它摘出来只留公开 summary 层元数据——两件事一起做。
- **为什么这么定**：一条还没写裁判器的轨只是「还没资格发言」，不该拖累门槛；而以后再加第四条轨时，门槛含义不会自己从「都要过」滑成「随便两条」。
- **必须有的守护测试**：把某条轨的「已实现」旗标翻成 false → 它不再计入；名单里加一条未实现的轨 → `p3b_ready` 不变；两条已实现轨都给出有效裁决 → `p3b_ready` 为真。

### 8D0″-① P5b 的 p 值检验方法

**sign-flip 随机化，直接复用 `engine/a_short_overlay_adjudication.py::_signflip_p`**，不要新写一套统计。裁决前实测：`n <= 15` 时它是 **2ⁿ 穷举、给精确 p 值**（12 区块 = 4096 次 / 7ms），`n > 15` 才转 32768 次抽样（36 区块 355ms）；种子固定 `random.Random(1)`，同一输入连跑两次 p 值逐位相同；用局部 RNG 实例，不污染全局 `random` 状态。选它的理由：数据形状与 P4a 完全一致（区块差值）、已实现且可复现、两轨同尺度可比；t 检验在 12 区块下会被单周极值拖成「显著」。

**已知性质（写进 governance 注释即可，暂不加料）**：`n=16` 处从精确穷举切到抽样，抽样误差约 ±0.5%；仅当真实 p 落在 0.020–0.030 这条窄带（判定线 0.025）时才理论上可能影响结论。真遇到再把 trials 调高（20 万次约 2 秒），不预先加。

### 8D0″-② P5b 检查点映射

**12 周 = 初步 / 24 周 = 正式 / 36 周 = 终局**，与 P4a 同：
- 12 周：只出 `preliminary_positive` / `preliminary_negative` / 继续积累，不定案。
- 24 周：可出正式结论（需 h20 全覆盖 + bootstrap + sign-flip + 月度聚类等正式门）。
- 36 周：可出终局结论（含退役 epoch）。
**吸取 8A 的教训**：12/24/36 每档的差异下限（6/12/18）与非重叠块下限必须拦住**该档的所有终局分支**，不能只拦晋级；并且每个写进 registry 的门都必须真有读点——8A 就出过「声明了却没人读」的 Required。

### 落地顺序

先把上面四项写进 governance / registry（含守护测试），再按 `8B → 8C → 8D1` 施工。8B、8C 的验收引用 8D0′ 这两条；8D1 的验收引用 8D0″ 这两条。
