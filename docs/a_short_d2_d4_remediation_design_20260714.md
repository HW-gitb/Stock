# A-short D2 / D4 修复与审查标准

> **2026-07-16 D4 provenance correction (current standard):** The spent 2026-07-14 D4 result has only a SHA-256 recorded after execution. Its `input_integrity.binding_status` is `posthoc_recorded_unverified`; the source snapshot is absent, so interpretation is reviewer-trust-only and it is not source-hash-bound. Do not amend the historical preregistration or rerun the spent singleton. Any future D4 needs a new reviewed preregistration and singleton ledger that pin the canonical source path plus `expected_sha256` before execution; the new runner must reject a mismatch before result write or ledger spend.

范围只限 A-short。两项均为研究或比较旁路：不改 EGS、M6.7、仓位、否决或下单。

## D2：环境记录和操作建议对照

每个可运行周必须单独记录：

- 原始 V14.2 环境；原始值为 `unknown` 时，实际用于基线的 fail-closed `shock` 也必须同时记录。
- 这两个环境各自对应的固定 policy id / epoch；旧的 unknown-only V14.3 记录不进入新账本。
- V14.3 原始环境及其触发规则；两边的冻结建议仅为 `allow/forbidden + 0/60/80%` 市场风险暴露代理。
- 同周 M6.7 的 SHA-256 和候选建仓数量，不保存持仓或逐票内容；盘前的周一决策允许绑定上一已结算交易日，但相差超过 7 天必须失败。
- 每条 action record 必须冻结完整的三钟：`forward_origin.decision_as_of`、runner 自取且不可由调用方传入的 `forward_origin.run_date`，以及 M6.7 来源绑定的 `forward_origin.price_data_through`；同时记录 `capture_mode`、`source_receipt_complete`、`price_day_latest_settled`。`forward_eligible` 只能由这些字段在代码中推导：`capture_mode=live`、决策日不早于 runner 日、来源 receipt 完整、价格日已结算且不晚于决策日。盘前的周一决策允许绑定上一已结算交易日；历史回放、缺时钟或来源未对账一律不计入，即使有完整 h10 也不能标为 live forward。写入器只可追加本次 runner 记录；其他周只能做已审计前瞻收益回填，不能改决策或新造历史周。汇总还要求每个有效记录来自不同 runner 日期，同一天堆多条一律拒绝。汇总的 12 周和 8 个已到期分歧样本只数 live forward 记录。
- 已审计的 CSI1000 h1/h3/h5/h10 前瞻收益。它只衡量环境建议的风险开关方向，不能冒充选股收益。

结论只在至少 12 个 forward 周、且至少 8 个有分歧并到期 h10 周后才可从“积累中”变成“需人工审查”。无论结果如何，禁止自动切生产；用户确认后还必须另起生产变更切片。

Claude 必查：原始/有效环境没有混淆、旧账本未混入、规则矩阵和 epoch 不可漂移、M6.7 仅留下摘要、回填没有前视、盘前日期没有错配、没有自动生产消费者。

## D4：规则消融的单次检验

D4 的独立预注册和 singleton budget 固定为一次、只读既有 `rank_samples.csv`：同一 T+1 开仓到 T+5 收盘、同一既有净成本口径。`hard_veto` 的数值 `0/1/0.0/1.0` 与布尔文本等价；未来执行先原子写 spent ledger、再发布结果，发布失败也不得留下“结果已出但预算未花”的状态。它必须同时报告：

1. 全体、Tier1、Tier2、当前 Rule6 通过的 Tier1；
2. 当前四项 Rule6 与无 Rule6 的旧基线；
3. 每项 Rule6 的 leave-one-out 和 only-one-on；
4. 4 天与 5 天 crash veto 的独立 matched-cohort 前瞻状态。

第 4 项不得拿历史 Rule6 消融替代。它只能消费已冻结的 4 天旧组和 5 天新增组；未到期时必须写 `forward_pending`。D4 的任何结果都不能删规则、切生产或再次重跑；下一次测试必须新预注册、复审和用户授权。

本轮单次执行产物和预算账本是 D4 的唯一事实源。Claude 必查：输入 SHA-256、全部固定头都在、四项 Rule6 命名没有漏项、4/5 天保持独立、预算已经花掉、无再跑后门、无生产消费者。
