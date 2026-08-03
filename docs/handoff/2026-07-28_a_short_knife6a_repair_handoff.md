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
**吸取 8A 的教训**：12/24/36 每档的差异下限（6/12/18，唯一来源是 preset 的 `clock_contract`）必须拦住**该档的所有终局分支**，不能只拦晋级；每个写进 registry 的门都必须真有读点——8A 就出过「声明了却没人读」的 Required。**注意（2026-07-29 更正）**：P5b **没有** `nonoverlap_block_minimums`，preset 与 admission 里都不存在（那是 P4a 独有的）。8D1 开工时必须显式决定 P5b 要不要非重叠块门：要，就先在 preset 补齐这组数再实现；不要，就只按差异下限设门，别照抄 P4a。

### 落地顺序

先把上面四项写进 governance / registry（含守护测试），再按 `8B → 8C → 8D1` 施工。8B、8C 的验收引用 8D0′ 这两条；8D1 的验收引用 8D0″ 这两条。

## 2026-07-29 追加：负面界符号约束收口 + 第六刀合并门的独立复核

### 改了什么

- `engine/a_short_overlay_adjudication.py::_statistical_contract()` 增加一条 `negative_at_36["bootstrap_upper_pp_max"] > 0` 即抛，补上与 sibling `mean_delta_pp_max` 对称的符号校验。
- 第六刀合并门以断言形式钉进既有端到端测试 `tests/test_a_short_weekly_pipeline.py::MainWiringTests::test_portfolio_facts_follow_the_price_clock_and_share_dragon_window`：该测试跑一次完整 `main(...)` 周报，临时包住 `normalize_candidate` 抓每个候选的 `(quote.source_trade_date, 消耗序列末 bar)`，然后断言四类日期字段全部 ≤ `price_data_through`，且候选侧 `source_trade_date` 恒等于它。

### 验证命令与结果

- 审查方亲跑 `.toolsun_unittest_with_repo_pythonpath.cmd tests.test_a_short_overlay_adjudication tests.test_a_short_weekly_pipeline` = `525 OK / 35.2s / exit 0`；执行方已记账 `full_pack_ledger run a_short = 2080 OK`（rule 4，未重跑）。
- **边界逐点量清**（新约束写 `> 0` 而不是 `>= 0` 是对的）：`bootstrap_upper_pp_max = 99.0` → 抛（复现审查方原探针，上轮此值是被接受的）；已封值 `0.0` → **仍接受**，不误伤；`0.001` 这种轻微正值 → 即拒，门是紧的；`-1.0` 这种更严的值 → 接受。它与 sibling `mean_delta_pp_max`（已封值 -0.25、要求严格 `< 0`）的宽严差异来自各自的已封值，不是遗留的不对称。
- **植入控制（证明合并门不是空转）**：把决策日 `20260609` 塞进龙虎榜窗口后，该 wiring 测试由绿转红。候选腿的 `== price_data_through` 同样非空转 —— 该场景下 `price_data_through = 20260608` 与 as_of `20260609` 本就不同，所以这条等式排除的正是「把决策日当价格日」这个错误。

### 第六刀状态

**第六刀完成**：6A（组合事实时钟 + 北向因子退役）、6B（候选价格单一权威 + 官方档时钟加严）、6B Required（官方输入必须自报价格钟）、本刀合并门，四段齐。桌面 `ashort_r1.md` 第 6 刀的最终合并门条件至此满足。

### 下一步注意事项

一条流程 Optional（非代码）：执行方**第三次**只补 closure 段落、不翻 `状态 / 严重度` 行，留下 `open` 的陈旧状态由审查方收口时翻正（本轮是 `R-ASHORT-P4A-NEGATIVE-BOUND-VALIDATION-IS-ASYMMETRIC`，前两轮是 6B 官方时钟条目与 master-lane 两红条目）。建议把「写 closure 段落必须同时翻状态行」做成 doc-governance 守卫，否则每轮都要人工兜。

## 2026-07-29 追加：8D0′ 四项落 governance + 8B 完成 P2

### 改了什么

- **8D0′**：`engine/a_short_experiment_admission_registry.py` 新增 `p3b_external_comparison_tracks()` —— P3b 的外部轨名单 + 每条的「裁判器是否已实现」判据下沉到这里（P1 常量、P2 读 `formal_adjudication_implemented`、P5 读 `p5b_implemented`）；`runners/a_short_final_action_validation_runner.py` 删掉硬编码的 `P3B_EXTERNAL_PUBLIC_SUMMARIES` 元组、改遍历该名单并跳过未实现裁判器的轨，`_p3b_ready()` 独立成函数；`:516` 的文件名死分支改为真实产物名 `industry_weight_comparison_summary.json`。P2 的 `formal_adjudication_implemented` 翻 True。
- **8D0″**：P5 三个 admission 的 statistical 里加 `p5b_adjudication_governance`（`p_value_method` 指向 `_signflip_p`、检查点阶段映射、终局分支必须卡最小值的断言）。
- **8B**：新模块 `engine/a_short_target_policy_adjudication.py`（83 行，纯函数、阈值全从已封 admission 读、不进指纹）；P2 公开摘要 schema 补齐 `verdict` / `progress` / `fingerprint` / `source_hash` 四个 **required** 字段 + `target_exit_adjudication` / `breakout_entry_reports` / `breakout_entry_verdict`；breakout 轨只出四类报告 + `not_adjudicated` 占位，不现编阈值。公开发布路径改为 `--target-policy-public-summary` / `--target-policy-public-markdown` 两个显式参数，**both-or-neither**，省略即不写公开文件；`weekly_screening.ps1` 官方跑才传这两个路径。

### 验证命令与结果

- 审查方亲跑覆盖全部改动符号的超集（`target_policy_adjudication` + `p3b_governance` + `final_action_validation` + `target_policy_comparison` + `experiment_admission_registry` + `effect_contract` + `weekly_pipeline`）= `581 OK / 60.5s / exit 0`。
- **全量由审查方按 rule 4 接管**：本刀改了生产顶层 runner + `weekly_screening.ps1` + 三个 schema，触发 rule 3(a)。执行方跑过全量，但用的是裸 `-m unittest discover`（`2088 OK / 196.6s`），**没走 `full_pack_ledger run`**，所以 `check a_short` 查不到该代码态的绿、pre-commit 钩子也告警。审查方用账本原子命令重跑并记账 = `2088 OK / 189.5s / exit 0`，计数与裸跑一致，`check` 现为 `CACHED GREEN`。裸跑结果按 rule 4 不构成记账证据——rule 3 触发时请直接用账本命令。
- **tracked 产物卫生亲证**：跑完这 581 个测试后 `git status research/` 为空 —— 即 register `R-ASHORT-TEST-PACK-REWRITES-TRACKED-P2-PUBLIC-SUMMARY` 的闭合判据（「跑完 A-short 包后 git status 不得出现 tracked 公开摘要的改动」）在我的运行下成立。
- **不悬空链路已核**：P2 裁判器 verdict → 公开摘要 `verdict` 字段（schema required，enum 含 `not_adjudicated`）→ `_valid_external_public_verdicts()` → P3b 解锁判定。这条链是 8B 的「影响对比项未来裁决」判据。

### 下一步注意事项

一条 open Required：`docs/system_risk_register.md#R-ASHORT-P5B-GOVERNANCE-NUMBERS-DUPLICATED-ACROSS-PRESET-AND-ADMISSION` —— `p5b_adjudication_governance` 把 preset `clock_contract` 已冻的 `checkpoints` 与 `difference_minimums` 又抄了一份（形状还不同：list vs dict），无任何绑定；且它断言「终局分支必须同时卡非重叠块下限」，而 P5b 的 `nonoverlap_block_minimums` 在 preset 与 admission 里都不存在。修完再进 8C。

## 2026-07-29 追加：P5b 治理数字重复已按单一来源收口

### 改了什么

`engine/a_short_experiment_admission_registry.py::_p5_admissions` 里的 `p5b_adjudication_governance` 缩到只剩本次用户裁决**新增**的两项：`p_value_method`（指向 `_signflip_p`）与 `checkpoint_stages`（12=preliminary / 24=formal / 36=terminal）。`difference_minimums`、裸 `checkpoints` 列表、以及 `terminal_branches_require_difference_and_nonoverlap_minimums` 断言全部删除——数值门只留在 preset 的 `clock_contract`。

### 验证命令与结果

- 审查方亲跑 `tests.test_a_short_experiment_admission_registry + tests.test_a_short_p3b_governance + tests.test_a_short_target_policy_adjudication` = `21 OK / 0.7s / exit 0`。本刀改三个 P5 已封 admission 的身份（rule 3b），调账本全量得 `CACHED GREEN a_short = 2089 OK` —— 执行方已在同一代码态记账，账本判本次运行冗余并跳过。
- **单一来源亲证**：`p5b_adjudication_governance` 现仅两键；`clock.checkpoints [12,24,36]` 与 `clock.difference_minimums [6,12,18]` 与 preset 逐项相等；全 admissions 里 `nonoverlap_block_minimums` 仅剩 P4a 自己那 1 处，P5 侧零残留。
- 新测试的绑定方式是对的：把 `checkpoint_stages` 的键集绑到 `definition["clock"]["checkpoints"]`，再 patch `registry._load` 把 preset 的 `difference_minimums` 改成 `[7,12,18]`、断言 admission 的 `clock` 跟着变 —— 改 preset 不改代码就能让结果变，正是本批反复要求的那条不变式。

### 下一步注意事项（转 8D1）

「终局分支必须卡最小值」这条要求现在**只以本 handoff 的散文形式存在**，没有机器可读载体；而且 **P5b 至今没有任何 `nonoverlap_block_minimums` 来源**。执行方选择删断言而不是编数字，这个取舍是对的（不记录一条没有出处的要求），但 8D1 开工时必须显式决定 P5b 要不要非重叠块门 —— 要就先在 preset 补齐，不要就只按差异下限设门，别照抄 P4a。

## 2026-07-29 追加：8C 完成 P3 HAC 裁判 + 打通 P3b 可达性

### 改了什么

- 新模块 `engine/a_short_final_action_adjudication.py`：Newey-West HAC t（Bartlett 权 `1 - k/(L+1)`，`maxlags` 与 `t_min` 全从已封 `p3_managed_exit_vs_hold` admission 读并硬校验形状），五道门（mean / median / favorable_ratio / hac_t / drawdown）全过才给 `preliminary_edge_positive`。
- `engine/a_short_experiment_admission_registry.py`：`formal_hac_adjudication_implemented` 由 `False` 翻 `True`（P3 admission 身份随之变化，预冻结期无代价）。
- `runners/a_short_final_action_validation_runner.py`：`public_verdict` 不再是硬编码常量，改由 `adjudicate_full_edge(edges, evidence_counts=...)` 产出并进 `adjudication` 节；新增 `_outcome_drawdowns` / `_close_drawdown_pct` 供 drawdown 门用。
- `engine/a_short_regime_action_comparison.py`：P1 公开摘要补上 `source_hash` —— 这是 P3b 四字段里 P1 缺的最后一块。
- P3 / P1 两份摘要 schema 同步。

### 验证命令与结果

- 审查方亲跑 `tests.test_a_short_final_action_validation + regime_comparison_runner + weekly_sidecar_health + effect_contract + experiment_admission_registry` = `110 OK / 44.2s / exit 0`；账本对本代码态已有 `CACHED GREEN a_short = 2090 OK`（rule 4，未重跑）。
- **HAC 实现按公式核对无误**：`γ₀ + 2·Σ(1 - k/(L+1))·γ_k`，`lag = min(maxlags, n-1)`，`t = mean / sqrt(LRV/n)`，教科书 Newey-West。
- **对照组证明门在工作**：同均值但有波动的 26 周序列得 `hac_t = 50.494`、verdict `edge_not_proven`（均值差一点没到 0.30）。

### 下一步注意事项

一条 open Required：`docs/system_risk_register.md#R-ASHORT-P3-HAC-ZERO-VARIANCE-FAILS-OPEN-AND-EMITS-INFINITY`（P2）。`_hac_t` 在长期方差 `<= 0` 时返回 `±inf`，两条腿：① `hac_t` 门对 `inf` 恒真 → 恒定周效应（上游写占位常量的典型 signature）会被判成 `preliminary_edge_positive`，**方向是 fail-open**；② 该 `inf` 进 `adjudication.progress.hac_t`，而 `progress` schema 无约束、写盘没有 `allow_nan=False`，公开 JSON 里会出现裸 `Infinity` 字面量。修法：退化时返回 `None`（门已有 `is not None` 判据，改完即 fail-closed），并给 writer 加 `allow_nan=False`。

## 2026-07-29 追加：第八刀收尾工单（Codex 执行；用户 2026-07-29 派工）

第八刀六个子刀（8A / 8D0′ / 8B / 8C / 8D0″ / 8D1）已全部实现、审查并合入 master（`40b3b7d7`），全量 `a_short = 2114 OK` 记账。**但第八刀尚未完成**：桌面方案的「本刀合并验证」第 ④ 条在真实产物上不成立，且六步验证从未作为一次完整 pass 跑过。本节是收尾工单，做完第八刀才算收口。

### 改什么（四条 Required，按此顺序做）

1. **`R-ASHORT-KNIFE8-P2-PUBLIC-SUMMARY-PREDATES-ITS-8B-CONTRACT`（P2）** —— 让 P2 自己的一键 sidecar 从私有账本正常跑一次，重写 tracked 的 `research/results/a_short/target_policy_comparison_summary.json` 与配对 md。**不得手工回填任何字段**（同类已栽两次：P1 的 `source_hash`、P5 的 md 镜像）。并补一条把 tracked 产物钉成「与 writer 输出逐字段相等」的回归，照抄 P1/P5 已有那两条的做法。
2. **`R-ASHORT-P5B-NONOVERLAP-BLOCK-GATE-DECISION`（P2，用户已裁决方案 A）** —— preset `clock_contract` 补 `nonoverlap_block_minimums {"12": 6, "24": 12, "36": 12}`（沿用 P4a 已封数值，不新增待批参数），`adjudicate_question` 读它并**拦住该检查点的所有终局结论**（正面许可与负面淘汰都拦，不能只拦晋级 —— 8A 的直接教训）；块数不足时给 `continue_accumulating` + 一个能与「差异周不足」区分开的 reason。
3. **`R-ASHORT-P5B-AGGREGATE-VERDICT-DEPENDS-ON-QUESTION-ORDER`（P3，用户授权按审查方推荐）** —— 顶层 verdict 改由**已冻结的优先级表**取最保守者（`manual_rollback_review_only` > `do_not_promote` > `retain_balanced_only` > `next_reviewed_candidate_only`），优先级表进 governance/admission、不写死在代码里；**不新增 enum 值**。
4. **`R-ASHORT-KNIFE8-SIX-STEP-MERGE-VERIFICATION-NOT-RUN-AS-ONE-PASS`（P3）** —— 前三条落完后，在同一代码态**一次性**跑完方案的六步合并验证，逐条给命令 + 本次实测输出写进该 register 条目。不许写「已验」「同前」。

### 顺带修的 Optional（三条，`R-ASHORT-WEEKLY-PIPELINE-JSON-WRITERS-OUTSIDE-THE-NONFINITE-GUARD` 名下；合理就一并修，不做要写明原因）

- (a) 写盘口发现器的文件范围只有 `engine/a_short_*.py` + `runners/a_short_*.py` 两个 glob，**A-short 家族里不叫这个名字的模块在范围外** —— `engine/egs_industry_heat.py:377::write_weight_comparison` 与 `runners/materialize_a_short_variant_tracking.py:79` 都在写 JSON 且无 `allow_nan=False`（未证实是 A-short 生产活路径）。建议把范围从「文件名 glob」换成「按内容找写盘口」，或显式把 A-short 家族模块列进范围。
- (b) 判据只认 `ast.FunctionDef`，`async def` 写盘口整类看不见。
- (c) 子串匹配会把未来名字含 `write` 的非写盘口函数（`_rewrite_for_digest` / `_write_lock` 之类）误判为需登记 —— 方向是 fail-closed 的噪音，今天仓内零命中，改不改都可以，但要在 entry 里写下处置。

### 边界（这一轮不许顺手做的事）

- **不解冻任何证据轨**：四条对比轨必须仍是 `pre_freeze_audit_only`，`evidence_counts_toward_clock` 不许动。
- 不碰 `active_profile` / EGS / M6.7 / 选股 / 仓位 / 账户 / provider / 生产配置。
- 不开第九刀（EGS 短历史动量与空候选池健壮性，条目 18、19）——收尾做完再开。
- 阈值只许从 governance/preset/admission 读；代码里不得出现第二份副本。

### 验证要求

- 触发 `AGENTS` rule 3（改了 preset / admission / 裁判器 / 公开产物），故必须走 `.tools\full_pack_ledger.py run a_short ... -- discover -s tests -p "test_a_short*.py"` 一次终态绿并记账。
- 交接 entry 必须带 `Pre-Codex self-review` 行，五个字段（`matrix=` / `register=` / `handoff=` / `focused=` / `full-lane=`）写实 —— 上一轮就是漏了这一行导致 doc-governance 与 pre-commit 钩子双红、全量 FAIL。
- 每条 Required 的 closure tests 见 `docs/system_risk_register.md` 对应条目，本节不复述。

### 下一步注意事项

第八刀的收口条件 = 上面四条 Required 全闭 + 三条 Optional 有处置记录 + 六步合并验证留下一次性证据 + 全量绿记账。全部满足后第八刀才可宣布完成，之后才进第九刀。

## 2026-07-29 追加：第八刀收尾第一轮独立审查 = FAIL（Claude Code；79eb 工作树，未提交）

**审了什么**：79eb 工作树相对 `36f1aa1a` 的 13 个改动文件（P5b 裁判器 + P5 比较器 + governance preset + program schema + P2 sidecar runner + 两份 tracked 公开产物 + 四个测试文件 + register/SESSION_LOG）。

**成立的部分（不必返工）**：

- P5b 非重叠块门：`clock_contract.nonoverlap_block_minimums {"12":6,"24":12,"36":12}` 为唯一数值源，`adjudicate_question` 在差异周门之后、任何正面许可与负面淘汰之前读取当前检查点的块门，不足统一给 `continue_accumulating / insufficient_nonoverlap_blocks`，与 `insufficient_policy_separation` 可区分；`load_governance` 对该 dict 有漂移守护；36 周正负两分支的回归都在。
- 顶层 verdict：`_aggregate_terminal_verdict` 从 `risk_and_statistics_contract.aggregate_verdict_priority` 取 rank，未知终局 verdict 缺 priority 时 fail-closed；正序与反序都得 `do_not_promote`；未新增 enum。
- P5 公开产物：`remaining_nonoverlap_blocks` 逐问补齐、`admission_binding` 随 preset 变更重算，全程零证据形态诚实（各项 0），由 writer 产出。
- P2 sidecar 的两处放松**保留**：`_validate_ledger` 的 `enforcement_enabled` 门修的是真实潜伏缺陷（admission 一变整份账本不可读），`frozen_enforced` 反向控制已在；`_assert_public_summary_as_of_monotonic` 对 pre-8B legacy 形状的一次性放行也保留，半成品仍 fail-closed 的反向控制已在。

**为什么 FAIL**：新增的 `_summary_epoch` legacy 回退把**上一个契约指纹下**采集的那 1 周当成当前进度写进 tracked 公开摘要。实测：账本两条 epoch 指纹 `786b1033…` / `d4f93db8…`，当前预冻结常量指纹 `83855504…` / `420b8276…`，`_active_epoch(create=False)` 为 None；换回 `_active_epoch` 得 `forward_weeks=0`，带回退得 1，产物写的是 1。桌面方案已明确记过「预冻结切换后 `forward_weeks 0` 才是诚实值、一次性代价已记录」，本改动等于在没有新裁决的情况下推翻它。

**失效的旧结论（我自己给错的，必须作废）**：审查方在派工后的问答里说过「预冻结指纹是常量 ⇒ 那 1 周仍在当前 epoch，会被错误覆盖成 0」，据此给了「必须保住 forward_weeks=1」的条件。**该条件作废**——那两条 epoch 建立于预冻结切换之前，今天诚实的值就是 0。执行方是照这条错误条件施工的，返工责任在审查方。

**验证命令与结果**：`full_pack_ledger run a_short` → `CACHED GREEN a_short = 2120 OK`（同一精确代码态，审查方亲跑）；审查方自写反向控制见上；`git status --short --untracked-files=all` 实测 13 个改动（register 里写的 11 个不实）。

**给 Codex 的命令（下一轮）**：修复 `docs/system_risk_register.md#R-ASHORT-KNIFE8-P2-PUBLIC-SUMMARY-RESURRECTS-A-CROSS-EPOCH-LEGACY-RECORD` 的三条 Required repair，然后按 reopen 的 `#R-ASHORT-KNIFE8-SIX-STEP-MERGE-VERIFICATION-NOT-RUN-AS-ONE-PASS` 逐条重跑六步（每步给本次命令 + 本次实际输出，不许写「已验」「同前」「由全量覆盖」），并在 `#R-ASHORT-WEEKLY-PIPELINE-JSON-WRITERS-OUTSIDE-THE-NONFINITE-GUARD` 名下补齐工单三条 Optional 的「已修 / 不修 + 理由」。

**下一步注意事项**：重生产物仍只用 `settle --as-of 20260727`（无 `--daily-cache`、无 `refresh`、不前推日期），跑完仍要核主树与 79eb 的私有账本逐字节相同；不解冻任何轨；第八刀收口后才进第九刀。

## 2026-07-29 追加：第八刀收尾第二轮独立审查 = PASS（Claude Code；已提交并合入 master）

**改了什么**：跨 epoch 回填整条拆除 —— `_summary_epoch` 删除、`_summary_from_ledger` 恢复只读 `_active_epoch`；tracked 的 P2 公开 JSON 与配对 MD 由同一次 `settle --as-of 20260727` 重生（`forward_weeks` 两轨与 formal 全为 0）；钉住旧回退的那条测试换成 `test_cross_fingerprint_legacy_epoch_never_enters_public_progress`（pre-freeze 与 frozen 两种模式都断言 0）。工单三条 Optional 一并处置：`engine/egs_industry_heat.py::write_weight_comparison` 与 `runners/materialize_a_short_variant_tracking.py::write_payload` 补 `allow_nan=False` 并入注册表、发现器范围显式纳入这两个模块；AST 同时枚举 `AsyncFunctionDef`；`"write" in name` 子串判据换成明确的 file-sink + 本地 helper 词表并配误报负控。

**为什么**：上一轮 FAIL 的唯一 Required 就是「别把上一个契约指纹下的证据当当前进度」；Optional 三条是工单里点名要么修要么写理由的。

**验证命令与结果（审查方亲跑）**：`full_pack_ledger run a_short` → `CACHED GREEN a_short = 2122 OK`（同一精确代码态）；door 守卫 `tests.test_doc_governance_guard + tests.test_route_doc_ledger_status_consistency` 亲跑通过。自写探针：`hasattr(runner,'_summary_epoch') = False`；tracked JSON == writer 输出（逐字段相等）、MD == `_render_summary_markdown(writer 输出)`、`validate_public_summary` 通过、`forward_weeks=0`；`_is_current_external_public_summary(Path, payload) = True`、`_valid_external_public_verdicts() = 0`（预冻结期 `not_adjudicated`，符合预期）。放松类反向控制：把窄化后的 `_is_file_write_call` 换回旧子串匹配重跑发现器 —— 新旧都是 34 个写盘口、`LOST=[]`、无未登记项，证明这次窄化今天零覆盖损失。

**失效的旧结论**：上一轮 FAIL 里「tracked P2 两轨 `forward_weeks=1`」及其「legacy epoch 可作公开诊断来源」的说法已作废，register 对应条目已加更正行；今天权威值是 0。

**残留风险（Optional，未阻断）**：窄化后的写盘口词表是白名单，未来若新增一个名字不在词表内的本地 JSON 写盘 helper（例如 `_write_payload` / `_save_json`），发现器会看不见它 —— 旧的 `"write" in name` 子串判据本来能兜住一部分这类名字。建议后续给该判据补一个「`write` 作为词首/词尾」的兜底，或加一条植入新 helper 名必须被发现的守护测试。今天零命中损失，故不阻断本刀。

**下一步注意事项**：第八刀至此收口（四条 Required 全闭 + 三条 Optional 有处置 + 六步逐条留证 + 全量绿记账）；可进第九刀（EGS 短历史动量与空候选池健壮性，条目 18、19）。仍不解冻任何证据轨。

## 2026-07-30 追加：第九刀实现交接（Codex；待 Claude Code 独立审查）

### 实现范围

- 条目 18：`A-EGS/egs_main.py` 的 5/20/60 日收益改为各自要求 N+1 根有效收盘并使用第 N 根锚点；L0 区分 provider/source 缺口与已知短历史，后者按 20 日窗口 fail closed 排除；`runners/a_short_crash_veto_tracker.py` 的 20 日口径同步。
- 下游风险语义：动量窗口不足时 `chasing_high` / `overheat_flag` 保持 nullable，正式 Tier 与 `runners/backtest_rank.py` 的重排/variant 消费者均把 unknown 当作保守降级或排除条件，并记录 `momentum_history_unknown`。
- `schemas/data_health.schema.json` 升至 1.7.0，新增 `short_history_candidate_count`；短历史可见为 warning，不与 source coverage failure 混同。
- 条目 19：L1→L5 均支持阶段列/dtype 完整的结构化空表；L3 空表在 provider/snapshot 前短路。合法零候选只在 reconciliation pass、accounting balanced、source coverage 无失败时形成 `empty_candidate_pool` warning和 `overall_status=warn`；否则保持 error。
- 正式与 weekly 消费：空池写 `analysis_input.candidates=[]`；weekly 不请求候选价格/语义 provider，仍写 schema-valid 的零 reports JSON、配对 Markdown 和 receipt。未更改账户持仓链语义。

### 验证证据

- 固定解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，Python 3.13.8。
- 受影响调用者/消费者超集：`Ran 627 tests ... OK`；新增 review1 回测消费者负控：`Ran 21 tests ... OK`；effect-contract + industry：`Ran 55 tests ... OK`。
- 最终自审另补“非空 full + 空 watch/final 不得伪装合法空池”的反向控制，连 effect contract 为 `39 OK`；合法空池现在还必须满足 `full_universe == 0`。
- `data_health` Draft7 schema check、五个改动 Python 面的 `py_compile`、`git diff --check` 均通过；route-doc + doc-governance：`Ran 55 tests ... OK`。
- 自审修正后的最终 `.tools/full_pack_ledger.py run a_short ... -- discover -s tests -p 'test_a_short*.py'`：`Ran 2125 tests in 172.049s — OK (skipped=3)`；ledger 终态 `PASS / exit=0 / tests=2125 / elapsed=173.4s`。修正前一次 full pack 不作为最终代码态证据。
- full pack 后 `git status --short --untracked-files=all` 无 tracked 正式公开产物漂移；仅本刀代码、schema、测试和交接文档为修改态。

### 审查边界与下一步

- 权威细节：`docs/system_risk_register.md#R-ASHORT-KNIFE9-SHORT-HISTORY-AND-EMPTY-POOL`；桌面 `ashort_r1.md` 只作路线图背景。
- 未解冻任何 evidence lane，未改 active profile、账户、provider 授权或其他三套系统；Codex 未 commit、push、merge。
- 下一步：Claude Code 独立审查本刀；只有审查 PASS 后才由 Claude Code 提交。

## 2026-07-30 追加：第九刀第一轮独立审查 = FAIL（Claude Code；79eb 工作树，未提交）

**审了什么**：79eb 相对 `06fe9443` 的 17 个改动文件（`A-EGS/egs_main.py` +287、`engine/egs_industry_heat.py`、`runners/a_short_crash_veto_tracker.py`、`runners/backtest_rank.py`、effect contract 与 data_health schema、7 个测试文件）。分级：生产选股入口 + fail-closed 门改动 → 走满标准，起 1 个 §6a 独立对抗 agent（read-only、禁网禁改）。

**成立的部分（不必返工）**：

- 窗口重定义：`_trailing_return_pct` 要求 N+1 根收盘、锚点在 `iloc[N]`，与桌面方案条目 18 第 1 点**原文一致**（不是越界改因子定义）。审查方自写边界探针：6/8/20 根 → 20d/60d 为 NaN；21 根恰好可算且与手算逐位一致（**不过度排除**）；61 根三窗口齐全；非正锚点 → NaN。
- L0：删掉「pct_20d 全 NaN 就跳过过滤」的应急分支、改为 NaN 一律排除；缺 stats 符号仍 `RuntimeError` fail loud，两类没混为一谈。
- `_short_history_candidate_count` 只数主板、1–60 根，0 根不误计为短历史。
- 消费者同步：`crash_veto_tracker` 的本地 20 日重算与 egs_main 同口径；`backtest_rank` / `egs_industry_heat` 的 `chasing_high` / `overheat_flag` 由 `fillna(False)` 改 `fillna(True)`（保守侧），`has_l4_overheat` 保留 False-fill 是对的（非动量派生）。
- data_health 1.6.0→1.7.0：仓内 0 份 1.6.0 产物，不存在历史产物被新 `const` 打死的问题（区别于 8D1 那次同类）。
- effect contract 双哈希由仓内校验器机器核对（非手抄），随全量绿。
- agent 的四个 HELD：空表端到端穿完 L1→L5 与整条发布链且产物 schema 有效、CSV 带表头；空表不触任何 provider / snapshot / cninfo；unknown 动量被三条独立机制挡在 Tier1 之外且 `downgrade_reasons` 只写 `momentum_history_unknown`（不伪称真追高/过热）。

**为什么 FAIL（三条 P2，正文只在 register）**：`#R-ASHORT-KNIFE9-EMPTY-POOL-LAUNDERS-A-PRE-L0-FAILURE`（`legal_empty_pool` 不要求有票进过 L0，L0 之前的批量失败被洗成 warn，warning 文案还与自身指标矛盾）、`#R-ASHORT-KNIFE9-L3-EMPTY-SHORTCIRCUIT-SILENCES-ITS-DATA-GUARDS`（空表 return 在 L3 自己两道 `SystemExit` 数据门之上；次生发现一条被 `schema_version == "1.2.0"` 围栏关死的 L3 provider/mode 交叉校验，现行发布是 1.3.0）、`#R-ASHORT-KNIFE9-WEEKLY-NULLABLE-MOMENTUM-READ-FAIL-OPEN`（`weekly_pipeline:603` 用 `bool()` 把本刀新发的 `null` 读成 False，与同一 dict 往下 6 行的退市字段口径相反）。三条的承重前提审查方逐条自核过源码，未采信转述。

**验证命令与结果**：`full_pack_ledger run a_short` → `CACHED GREEN a_short = 2125 OK`（同一精确代码态，rule 4 亲跑）；六个改动的 phase6 EGS 模块（`test_egs_main_board_and_holder_pit` / `..._daily_stats_guard` / `..._qfq_price_basis` / `..._suspend_guard` / `test_egs_rank_universe_reconciliation` / `..._sw_industry_and_watch_pool_health`）= `58 OK`（rule 1 亲跑）；door 守卫 `55 OK`；`git diff --check` 干净；`research/` 与 `result/` 无产物漂移。

**失效的旧结论**：agent 报告里「非空回归逐列取值完全一致、`egs_full` CSV 逐字节相同」只在**固定 stats 输入之下游**成立 —— 窗口重定义按方案就是要把三个窗口各挪一个交易日，非空票的 `pct_5d/20d/60d` 必然变化并流入动量排名与行业热度。这是方案授权的口径变更，但不得用「取值不变」描述（已更正入 register）。

**给 Codex 的命令（下一轮）**：修复 `docs/system_risk_register.md` 里 `#R-ASHORT-KNIFE9-EMPTY-POOL-LAUNDERS-A-PRE-L0-FAILURE`、`#R-ASHORT-KNIFE9-L3-EMPTY-SHORTCIRCUIT-SILENCES-ITS-DATA-GUARDS`、`#R-ASHORT-KNIFE9-WEEKLY-NULLABLE-MOMENTUM-READ-FAIL-OPEN` 三条的 Required repair 与 closure tests；`#R-ASHORT-KNIFE9-OPTIONAL-BATCH` 六条逐条写「已修 / 不修 + 理由」（(a)(e) 建议修，(d) 只报不动）。

**下一步注意事项**：修 `legal_empty_pool` 时不要把本刀要支持的合法形态（有票进 L0、全被记账门排除）一起打回 error —— closure test (2) 就是这条反向控制。L3 空表 return 下移后要确认空表仍不触 provider（agent 已 HELD 的那条不能回归）。仍不解冻任何证据轨、不碰 `active_profile` / M6.7 / 生产配置。

## 2026-07-30 追加：第五刀冻结包运行时承重修复（Codex；待 Claude Code 独立审查）

### 修复范围

- 桌面 `ashort_hang.md` 指出的悬空成立：冻结包原来在正式 `engine/` / `runners/` 中零消费者，schema 测试只借 P4a mode 当总开关。
- 现由七轨共用 `engine/a_short_evidence_epoch_mode.py::enforcement_enabled(track)` 每次消费 packet：预冻结校验 schema / inventory / self-hash / 诚实边界；任一轨单独冻结时校验全部八项 LF-canonical hash，漂移即 fail-closed。
- freeze schema const-pin 八项身份与顺序，并以 schema / runtime / packet 三角测试防两套清单漂移；README 增加薄路由。

### 验证与反向控制

- 七轨逐一单独冻结均触发共享 full-hash 门；任一轨下植入一个错误 contract hash 均被拒。删项、重复、换名、换路、调序以及 pre-freeze 不诚实声明也全部转红。
- 最终固定 Python 七轨消费者超集 `346 OK`；exact-final-code full A-short ledger `2175 OK (skipped=3)`，fingerprint `ade9bfc50cc8`；`py_compile` / `git diff --check` 通过。
- 开发期两次红灯及归因完整记录在 `docs/system_risk_register.md#R-ASHORT-FIFTH-KNIFE-FREEZE-PACKET-RUNTIME-ORPHAN`。

### 边界与下一步

- 当前八项仍有六项 pre-freeze 漂移，七轨 registry 仍全部 `pre_freeze_audit_only`；本轮没有重封、没有解冻、没有启动时钟，也没有改 EGS / M6.7 / active profile / provider / 账户。
- 下一步仅是 Claude Code 独立审查本修复；PASS 后由 Claude Code 按项目流程提交，不 push。

## 2026-07-30 追加：第五刀 frozen 切换事务旁路修复（Codex；待 Claude Code 独立复审）

### 修复范围

- 复审确认首次 start、显式 reset 与 active-written/registry-not-written 恢复会先写耐久状态、后由消费端 full-hash 门发现漂移，形成 frozen 半开状态。
- `engine/a_short_evidence_epoch_mode.py::validate_frozen_transition(track)` 现提供不依赖 registry 当前极性的八契约 full-hash transition guard。
- `runners/a_short_theme_forward_comparison.py::_start_or_reset_epoch()` 的普通 start/reset 在首个 admission 写入前调用该门；恢复分支在 registry mutation/write 前调用。失败不写 admission、archive、active epoch 或 registry。

### 验证与反向控制

- 单项错误 hash 分别攻击 start/reset/带真实 admission 的 active-written 恢复，三条均 fail-closed，临时树逐文件字节不变。
- 完整临时重封 packet 下三条合法路径完成；植入计数证明每条路径恰好一次 guard 且先于首个 write。
- AST writer inventory 枚举所有 registry JSON writer，未来新增写 owner 或移走两处 prewrite guard 会转红。
- 固定 Python：theme transaction `16 OK`；epoch consumer focused superset `255 OK`；`py_compile` 通过；exact-code-state full A-short ledger fingerprint `88933539453c`，`2178 OK (skipped=3)`，ledger PASS。

### 边界与下一步

- 当前生产 freeze packet 仍有六项 hash 漂移，七轨仍全为 `pre_freeze_audit_only`；未重封、未解冻、未启动时钟，未改 EGS / M6.7 / active profile / provider / 账户。
- Claude Code 需独立复审 `R-ASHORT-FIFTH-KNIFE-FROZEN-TRANSITION-BYPASS`；PASS 后由 Claude Code 提交，不 push。

## 2026-07-30 追加：第五刀 packet/epoch source binding 修复（Codex；运行验证 NOT_VERIFIED）

### 修复范围

- `validate_frozen_transition()` 返回稳定 freeze packet identity；七轨所有 real fingerprint（含 P0 四腿、P2 双组件例外）均绑定该 identity。
- Theme epoch schema 升至 `1.4.0`，identity 纳入 contract/epoch identity、公开 packet、admission/outcome/formal 三类私有 receipt；运行时 identity 不同即 `epoch_contract_mismatch`。
- start/reset/recovery 沿用 transition guard 同一次返回值；三类 receipt writer 在首写前重验 epoch-bound identity，formal receipt validator 显式核对同源字段。

### 负向控制与当前证据

- 已编写同步修改共享 weekly schema 并同版重封 packet 的反向控制：旧 epoch 必须停止、不得写新 receipt；七轨 fingerprint 全部改键；显式 reset 绑定新 identity 后只建立新 epoch evidence。
- 已补 epoch schema、公开 packet、bound runtime、formal receipt 的 missing/空或替换 freeze_id/旧版/错误或替换 record hash/extra 字段负控，以及 receipt writer 静态 inventory。
- 固定 `C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe` 已确认 Python 3.13.8；focused superset `130 OK`、本轮 Python 文件 `py_compile`、route/doc guards `66 OK` 均通过；exact-code-state full A-short ledger `2185 OK (skipped=3)`，fingerprint `4a77c03a16de`，ledger PASS。

### 边界与下一步

- 当前生产 packet 未重封，七轨未解冻，时钟未启动；EGS、M6.7、active profile、provider、账户均未改。
- 已有明确测试与 ledger 终态；下一步为 Claude Code 独立复审。PASS 后由 Claude Code 提交，不 push。

## 2026-08-01 追加：第五刀复审 Optional 收口（Codex；待 Claude Code 独立复审）

### 修复范围

- freeze schema validator 仅按 schema 路径和 metadata 缓存编译结果；packet 每次重新读取与完整验证，不会因缓存掩盖 patch、篡改或重封。
- receipt writer 守卫由 runner 的 `build_*_receipt` import 自动派生，不再依赖三个硬编码函数名；start/admission/outcome/formal 均要求在首次 build 前有 identity/transition guard。

### 负向控制与验证

- 同 schema 两次 query 命中一个 compiled validator；篡改同路径 packet 仍转红；改 schema metadata 后强制 cache miss。200 次预冻结 query 实测 `0.422719s`、约 `2.114 ms/call`。
- AST 植入未来无 guard receipt writer 必须转红；fixed Python 定向 `51 OK`、五模块 focused `132 OK`、`py_compile` 通过。当前交接写入后的 route/doc guards 和 exact-code-state full-pack 尚待执行。

### 边界与下一步

- 不缓存 packet，不解冻、不重封生产 packet、不起时钟，也不改 EGS、M6.7、active profile、provider 或账户。
- 跑完最终门禁和 exact-code-state full-pack 后交 Claude Code 独立复审；PASS 后由 Claude Code 提交，不 push。

### 验证补充（2026-08-01）

- 固定 Python 3.13.8 的 route/doc guards 为 `Ran 66 tests in 1.305s — OK`；exact-code-state full A-short ledger fingerprint `d8ed7cc1dd8b` 为 `Ran 2187 tests in 311.837s — OK (skipped=3)`，ledger `PASS / exit=0 / tests=2187 / elapsed=313.2s`。
- Optional 的下一步仅为 Claude Code 独立复审；PASS 后由其按流程提交，不 push。

## 2026-08-01 追加：第五刀两条复审 Optional 的独立复审收口（Claude Code，PASS）

### 改了什么 / 为什么

- 本轮我不改代码，只复审 Codex 对我上一轮两条 Optional 的收口，并提交合入 master。改动函数只有四个新增/改写的符号：`_freeze_schema_cache_key`、`_compiled_freeze_packet_validator`、`_freeze_packet_validator`、`_validate_fifth_knife_freeze_packet` 的 schema 校验段；加上 runner 测试里把硬编码三函数清单换成 `_frozen_receipt_writer_offenders` AST 扫描。
- 复审重点不是「快了没有」，而是「快是不是靠少验了东西换来的」。缓存的是 schema 的编译结果，packet 仍每次读盘 + schema-validate + self-hash + honesty + inventory（冻结态还照旧重算八项契约哈希），所以 fail-closed 语义没有被缓存吃掉。

### 验证命令 / 验证结果

- `.tools\run_unittest_with_repo_pythonpath.cmd tests.test_a_short_evidence_epoch_mode tests.test_a_short_theme_forward_comparison tests.test_a_short_theme_forward_comparison_runner tests.schema.test_a_short_fifth_knife_forward_evidence_freeze_schema tests.schema.test_a_short_theme_forward_comparison_governance_schema` → `Ran 132 tests in 198.092s / OK`，bounded `tier=focused status=PASS exit=0 deadline=300s`。与执行方自报的 132 一致，为 reviewer 亲跑。
- reviewer 自写探针（scratchpad，不入库）8 项全过，逐条见 register 的「Optional 复审证据」行。其中最关键的两条：AST 清单在真模块上非空洞（会自动分出四个 writer，不是靠 offenders 恒为空假绿）；缓存暖起来后就地改坏同一路径的 packet，下一次调用立即 `EvidenceEpochModeError`。
- 缓存真命中率已实测而非推断：生产单路径 `cache_info()=hits 200 / misses 1 / currsize 1 / maxsize 8`，键数远小于 maxsize，无颠簸；`enforcement_enabled` 由 57.4 ms/call 降到 2.00 ms/call，全量包 `2185/416.4s → 2187/311.8s`。
- 全量按 AGENTS rule 4 由执行方持有，reviewer 不重跑：独立重算当前代码态 ledger 指纹 `d8ed7cc1dd8b`，与记录的 `2187 OK` 完全一致。

### 失效旧结论

- 我上一轮记在 register 的两条「复审 Optional（不阻断，未修）」已作废，现为已修 + 复审 PASS + 已提交。
- 「预冻结 `enforcement_enabled()` 57.4 ms/call」是修前实测，已被 2.00 ms/call 取代。

### 下一步注意事项

- 第五刀三条 Required + 两条 Optional 至此全部 closed，本刀无待办。
- 以后再动 `_validate_fifth_knife_freeze_packet`：**不要**顺手把 packet 解析也塞进 `lru_cache`。测试全靠 `mock.patch.object` 换 `FIFTH_KNIFE_FREEZE_PACKET_PATH` 与就地改写临时 packet，缓存 packet 会让「改坏立刻转红」这条负控假绿。
- AST receipt-writer 守卫只认 `ast.Name` 形式的 `build_*_receipt` 调用；未来若有人用 `模块.build_xxx_receipt(...)` 或别名调用，扫描不到。真要收这一类可复用 knife 10 的 consumer-guard 做法，但那是更贵的一档，现在七轨仍 pre-freeze，不值得。

## 2026-08-01 追加：第五刀三条冻结包 Required 的独立复审收口（Claude Code，PASS）

### 改了什么 / 为什么

- 本轮我不改代码，只做独立复审并收口。被审工作树 `D:\cnhea\Codex\worktrees\19d3\Stock` 的未提交改动是一个叠了三条 Required 的整体产物：`R-ASHORT-FIFTH-KNIFE-FREEZE-PACKET-RUNTIME-ORPHAN`（冻结包接进七轨运行时）、`R-ASHORT-FIFTH-KNIFE-FROZEN-TRANSITION-BYPASS`（写前 transition guard）、`R-ASHORT-FIFTH-KNIFE-PACKET-EPOCH-SOURCE-BINDING`（packet identity 成为 epoch/fingerprint 的 source binding）。三条状态已在 register 改为 closed 并记入本次复审证据。
- 复审重点放在最后一条：它要挡的是「改共享契约 + 同版重封 packet」这种自洽绕过，属于证据口径完整性，是这三条里唯一无法靠既有负控覆盖的类。

### 验证命令 / 验证结果

- `.tools\run_unittest_with_repo_pythonpath.cmd -v tests.test_a_short_evidence_epoch_mode tests.test_a_short_theme_forward_comparison tests.test_a_short_theme_forward_comparison_runner tests.schema.test_a_short_fifth_knife_forward_evidence_freeze_schema tests.schema.test_a_short_theme_forward_comparison_governance_schema` → `Ran 130 tests in 224.777s / OK`，bounded `tier=focused status=PASS exit=0 deadline=300s`。计数与执行方自报一致，为 reviewer 亲跑。
- reviewer 自写探针（scratchpad，不入库，不复用执行方 fixture）：镜像八契约到临时 ROOT → 取身份 I1 → 改 `weekly_report_schema` 并同版重封 → I2；12 项断言全过，含 `I1≠I2` 且仅 `record_sha256` 移动、`bind_frozen_fingerprint(I1)` 拒绝、theme `contract_fingerprint`/`epoch_identity_fingerprint`/冻结轨 real fingerprint 全部改键、预冻结六轨常量不动、未重封的纯漂移 fail-closed，以及一条植入控制（把 identity 从指纹输入拿掉后同一攻击不可见）。
- 独立重算 `.tools\full_pack_ledger.py` 的当前代码态指纹 = `4a77c03a16de`，与 ledger 记录的 `2185 OK` 完全一致，按 AGENTS rule 4 由执行方持有那一次全量、reviewer 不重跑。
- 静态确认 `schemas/a_short_fifth_knife_forward_evidence_freeze.schema.json` 声明 2020-12 草案，故新加的 `prefixItems` + `items:false` 在 jsonschema 4.26.0 下真生效（若是 draft-07 会整包拒绝）。

### 失效旧结论

- register 三条的「待 Claude Code 独立复审 / 未提交 / 运行验证 NOT_VERIFIED」状态全部作废，现为 closed 且已提交。
- 「executor 的 `2178 OK` / `2175 OK` 不覆盖该反向控制」仍成立，但已被本轮 `130 OK` + `2185 OK` 取代为当前终态。

### 下一步注意事项

- 两条 Optional 未修，正文在 register 该条目的「复审 Optional」行：① 预冻结 `enforcement_enabled()` 实测 57.4 ms/call，其中 `jsonschema.validate` 每次重编译校验器占 35.9 ms（预编译后 1.0 ms），全量包由 `2178/265.5s` 变为 `2185/416.4s`；② `test_every_frozen_receipt_writer_validates_epoch_packet_binding_before_write` 是硬编码三函数清单，不是 AST 枚举。
- 若要做 Optional ①：只缓存已编译校验器是安全的（schema 路径固定、内容不变）；**不要**给 `_validate_fifth_knife_freeze_packet` 直接挂 `lru_cache`，测试靠 `mock.patch.object` 换 `FIFTH_KNIFE_FREEZE_PACKET_PATH`，无键缓存会假绿。要缓存 packet 解析必须以「路径 + mtime + size」为键。
- 七轨仍全部 `pre_freeze_audit_only`，生产 packet 仍有六项漂移；本轮没有重封、没有解冻、没有启动时钟。桌面方案第 0 节的「设计未定稿前不建冻结件」仍成立：预冻结路径返回常量，改这八个契约文件在预冻结期不会作废任何东西。
- 后续任何刀若要重命名或移动这八个契约中的任一个，必须同时改 `engine/a_short_evidence_epoch_mode.py::_FIFTH_KNIFE_FROZEN_CONTRACTS`、freeze schema 的 `prefixItems` const 与 packet 三处，否则七轨 epoch-mode 调用会整体抛错。

## 2026-08-03 追加：桌面清单第 4 条日线窗口修复（Codex；待 Claude Code 独立审查）

### 改了什么 / 为什么

- 桌面现象 `short_history_candidate_count=3191` 的直接根因是：公共日线面板实际只保留 60 个交易日，而 `pct_60d` 的定义需要当前收盘加上 60 个交易日前的收盘，即至少 61 根有效收盘。于是 `pct_60d` 全部不可算，短历史计数也退化为“有行情的主板票数量”。
- `A-EGS/egs_main.py` 现在用同一组声明统一 `pct_5d/pct_20d/pct_60d` lookback、所需收盘根数、65 个交易日窗口（61 根需求 + 4 根缓冲）、`run_egs()` 的取数、缓存 key 和短历史告警口径。窗口或配置不足时在 cache/provider 之前 fail closed；没有把 61 改成 21，也没有改变候选阈值。
- `engine/egs_industry_heat.py` 的既有消费者未改业务逻辑；新增回归证明 `pct_60d` 有值时会参与，全部缺失时才明确退化到 p20-only。effect contract 只同步了本次 A-EGS 变更触发的 predicate/runtime-constant 两个指纹。

### 改动文件

- `A-EGS/egs_main.py`
- `schemas/a_short_m67_effect_contract.json`
- `tests/phase6/test_egs_main_daily_stats_guard.py`
- `tests/phase6/test_egs_main_qfq_price_basis.py`
- `tests/test_egs_industry_heat.py`
- `docs/system_risk_register.md`（`R-ASHORT-QFQ-60D-WINDOW-SILENCES-PCT60D`）
- `docs/SESSION_LOG.md`

### 验证与边界

- 唯一解释器：`C:\Users\cnhea\AppData\Local\Programs\Python\Python313\python.exe`，版本 `Python 3.13.8`。
- focused：`Ran 94 tests in 58.199s ... OK`；最终 A-short full lane：`Ran 2274 tests in 436.681s ... OK (skipped=3)`，ledger `status=PASS exit=0 tests=2274 elapsed=438.6s deadline=860s`；`py_compile`、`git diff --check` 已执行。第一次 full lane 因未重封 effect contract 先报错，重封后只对最终代码态重跑一次并通过。
- 未执行新的 provider/live `--as-of 20260803` 运行；当前桌面产物不因本刀刷新。无账户、持仓、下单、自动交易、commit、push、merge。

### 交接给下一位

- Claude Code 需独立审查当前五个代码/测试/schema 文件、风险登记、SESSION_LOG、窗口/缓存 source binding、消费者退化和负向门；PASS 后由 Claude Code 按项目流程提交。当前未授权把 real `--as-of 20260803` 运行结果写成已验证事实。
