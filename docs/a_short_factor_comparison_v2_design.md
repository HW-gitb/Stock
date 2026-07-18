# A-short 对比轨 v2 owner design

状态：第 1 刀修复和第 2 刀离线裁决均已实现，待 Claude Code 独立审查；第 3 刀 weekly 接线尚未开始。

## 目的与边界

v2 是 A-short 对比轨的私密证据层。它把 D1 与 D3 登记为 question，把 baseline 与候选规则登记为显式有序 arm，并用同一 PIT 候选输入、固定 model-paper 账户和既有 forward cache 生成可供后续裁决器消费的周证据。

- 只限 A-short，所有 ticker、名单、逐票收益和仓位明细只写入 gitignored `state/a_short/factor_comparison_private/v2/`。
- v1 保持只读；不自动搬迁、不导入 v1 历史周，也不与 v1 ledger 混算。
- 不调用 provider，不改变 EGS、TopN、M6.7、仓位、veto、账户状态或生产配置。第 2 刀只能在私密目录写出统计建议、人工回执和提醒；它们均不能自动改生产策略。
- 第 2 刀只读取已冻结证据；第 3 刀才将 capture/settle 接入 weekly。三刀以外的生产修改必须另起经用户确认的任务。

## 契约与证据身份

`presets/a_short_factor_comparison_v2_governance_20260718.json` 是初始 program 权威，`ordered_arm_ids` 是唯一臂顺序权威，禁止从 JSON/dict key 顺序推断。每个 challenger 的 `effect_surface` 只能等于其 question 的受测面；额外 allocation、候选池或参数字段会被 schema/运行时拒绝。

初始问题：

- `d1_entry_anchor`：`baseline`、`entry_ma_pullback`、`entry_range_pullback`，唯一允许变化面为 `entry_type`。
- `d3_iv_policy`：`baseline`、`iv_step_down`、`iv_joint_stress`，唯一允许变化面为 `iv_policy`。

baseline 不重写算法。materializer 继续调用 `a_short_phase5_engine` 的 `compute_indicators`、`classify_risk_families`、`entry_type`、`exit_and_size`，并以 v1 已冻结的因素定义仅生成受测 arm。baseline parity 测试把 v2 baseline 与同一 canonical primitive 的直接结果逐项比对。

## Epoch 与来源绑定

每周 capture 写入 program manifest、capture、source receipt、epoch identity 和 source digest。只有本机实际日期、`run_date`、`source_as_of` 与 `decision_date` 全部一致，且 `run_identity.candidate_digest` 等于实际规范化候选快照的摘要、每只候选的最后一根价格恰为该日并与候选 close 一致时，capture 才可标为 forward eligible；历史诊断可落盘但其 ledger 身份永远为非 forward。重放或结算会重新计算 capture、候选快照和 source receipt 的哈希/来源/共享池绑定；已冻结的 arm `selected_symbols`、`decisions` 和 model-paper plan 是 capture 的哈希绑定载荷，不会在结算时重新运行选择器。部分目录、错日期、摘要漂移、非私密路径和旧 v1 路径一律失败。

epoch fast-path 同时绑定三种正交契约：decision-delta、immutable common-pool、outcome contract。任一契约摘要变化即新开 epoch；本刀只记录分段，不清零、不跨段合并。跨 epoch random-effects、最小块数、异质性和最终结论由第 2 刀实现。

common pool 是同一 PIT 候选输入在非 IV 的不可变硬门之后的共享 seam（`same_pit_candidate_universe_after_non_iv_immutable_hard_gates`），也是所有 arm 实际送入 canonical Phase5 policy 的唯一候选输入。D3 受测的 IV>90 门被明确标为 `iv_policy_deferred`，所以仅命中该门的候选仍留在公共池，交由 baseline/challenger 按各自 IV policy 处理；`收缩期` 即使同时 IV>90 也在公共池前单独排除，绝不因分类器优先报告 IV 原因而被名义计入。流动性、事件、持仓、过热及其他不可变硬门同样不能被 D3 绕过。

## Cache-only outcome 与数据完整性

结算仅接受既有 `daily_payload.stocks`，且不抓取数据。selected-union 的 as-of 到 H20 所有关键价位必须有有限 open/close、正数 `adj_factor`、`adj_factor_observed=true` 与 `adj_factor_source=provider_observed`。缺失、无来源前填/默认值、未核验的复权突变或 QFQ 异常跳空均令该 question-week `no_count`；同时按 arm 写入 no-count 原因与计数。

完整证据采用 T+1 open 至 H5/H10/H20 close 的 QFQ、扣成本、固定 slots 且保留未成交现金的 model-paper NAV。结算缓存 decision-date `close` 必须与 capture 冻结候选 close 精确一致，否则 fail-closed；entry 模型分母和无涨停表时的默认涨停价均只用该冻结 close。H10 `max_drawdown_pct` 按每个累计收益点的 `NAV=1+累计收益/100`（含入场时初始 NAV=1）计算峰谷回撤，不把累计收益再按逐期收益连乘。`bad_name_rate` 与 `tail_loss_pct` 只在实际成交仓位上计算，并随结果记录 `loss_distribution_basis=filled_positions_only` 与样本数；未成交仓位只通过 `cash_drag_pct`、`unfilled_rate` 单独衡量。它还输出成交、换手、成本、集中度和 adjustment coverage；第 2 刀必须逐项读取这些结果，不能只在结果文件中展示。

## 第 2 刀：冻结证据的离线统计裁决

裁决器 `engine/a_short_factor_comparison_v2_adjudication.py` 只读取私密 ledger 中 `forward_eligible=true` 且已终态、且属于该问题当前 experiment batch 的证据；每周都重新验证 source receipt、capture hash，以及 outcome payload 的重新计算摘要（必须同时等于 outcome 自报值与 ledger 值）、question/arm 顺序、epoch 和当前统计合同摘要。三签名 epoch 变化只切分证据段并触发跨 epoch 重算，不会把已有裁决永久阻断；统计合同或批次身份漂移才会使旧裁决失效。它不捕捉数据、不执行 weekly、不调用 provider，因而不能把历史回放、伪造摘要或被篡改的旧合同算成新证据。

每个问题的 `question_type`、`experiment_batch_id`、`multiplicity_family_id`、可组合资格、风险上限、块数、统计抽样次数和阶段阈值均冻结在 v2 governance。每个 challenger 只和同周 baseline 作配对差；H10 块仅在新 decision date 晚于前一块 exit date 时纳入，避免重叠持有窗口重复计数。0--11 个有效周只继续积累；12--23 周只出预审；24 周和 36 周才是正式检查点。

正式检查点同时执行：固定种子的 paired bootstrap CI、双侧 paired sign-flip p 值、单侧 sign-test 展示、同一 multiplicity family 内 Holm 校正，以及跨 epoch 的 REML random-effects + Hartung--Knapp 汇总。24/36 周分别使用冻结的 alpha spending 0.025/0.025；当期 epoch 必须自身至少有 4 个非重叠块、方向为正且不变坏，状态分层和异质性也必须一致。无论仅有一个还是多个 challenger，采用门都要求 paired bootstrap 下界不低于冻结经济优势；若多个 challenger 都越过各自门槛，只有每一 finalist pair 都至少有 12 个共同非重叠 H10 块，且 simultaneous bootstrap 下界仍超过该优势的唯一 arm 才能建议采用；绝不按点估计挑胜者。

每个 arm 在建议采用前还必须逐项通过 `max_drawdown_pct`、`bad_name_rate`、`tail_loss_pct`、filled-only 损失分布样本数、`cash_drag_pct`、`unfilled_rate`、`fill_rate`、`turnover_pct`、`total_cost_pct`、`max_name_weight_pct`、`adjustment_coverage_pct` 和 no-count rate 的硬门。任一缺失、越界、损失口径漂移、跨 epoch/状态方向冲突或当期 epoch 变坏都会阻断 adopt；36 周的持续可靠伤害可建议淘汰，冲突且 24/36 均无结论则转为 dormant。

裁决只写入私密 `adjudication.json`、`decision_receipts.json` 和 `reminder.json`。建议的回执指纹绑定问题、arm、正式检查点、合同摘要、epoch、batch 和 arm 定义；只有当前裁决的 pending 回执可被人工记录为 accepted/rejected/deferred，过期回执不能压掉新的提醒。dormant 问题必须由人工给出理由才能登记重启；登记会在 `experiment_batches.json` 实际生成新的 batch id，后续 capture 把它冻结到 question 和 ledger entry，裁决器只读当前 batch，因而旧数据无法回填。两个不同问题都获人工接受时，组合调度器会把已接受的两个 arm 和回执指纹冻结为新的、forward-only 组合 batch。只有显式预注册的 `combination_policy` question（恰好一个 entry factor 和一个 IV factor，且组件集合与该 batch 的 `component_question_ids` 精确一一对应）才能领取该 batch；领取前会回读 `decision_receipts.json`，要求每条指纹存在、已 accepted 且 question/arm/hash 精确一致。它在 v2 私密 materializer 中按两组件共同计算，并正常走 capture→settle→ledger→adjudication；即使同一组合问题曾有已结算 ledger，切换到新 batch 后旧 batch 行也为零计数。现有问题和历史 ledger 都不能被它复用，更不改变现有生产规则。

## 私密落盘结构

```text
state/a_short/factor_comparison_private/v2/
  program_manifest.json
  epochs.json
  ledger.json                  # capture-only 或仅记录私密 adjudication 摘要
  weeks/<decision_date>/
    capture.json
    outcome.json
    source_receipt.json
  adjudication.json            # 仅第 2 刀：统计建议、队列和重启登记
  decision_receipts.json       # 仅第 2 刀：人工回执，过期回执不可复用
  reminder.json                # 仅第 2 刀：只提醒当前 pending 回执
  experiment_batches.json      # 当前问题 batch 与 dormant/组合新前向 batch 的私密登记
```

四个 schema 责任面固定为 program/governance、weekly capture/outcome、ledger/adjudication、decision receipt；adjudication、回执集合和提醒的完整字段另由裁决器以固定 key、合同摘要和 receipt schema 做语义校验。第 2 刀不改变第 1 刀的证据生产层，因而不能提前形成 weekly 或生产接线。
