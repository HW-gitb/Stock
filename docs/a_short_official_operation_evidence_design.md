# A-short 正式 M6.7 操作建议证据

## 定位

本程序把已经发布的 `weekly_m67.json` 所代表的正式 M6.7 操作建议，冻结为私有、不可变的事实记录。它服务于以后对建议与实际进展的对照；本阶段不判断建议对错，也不产生交易或业绩结论。

## 可信来源与触发

- 只消费同一目录下、状态为 `complete` 的 `weekly_m67.receipt.json` 所绑定的 `weekly_m67.json` 和 Markdown；缺文件、名称、`as_of`、`run_id`、候选摘要或账户快照不一致即拒绝。
- capture 再校验 weekly schema、每张 M6.7 schema 与 `validate_m67_consistency`，所以不能由中间 dataframe、P3 模型集、缓存或重跑分析近似生成建议。
- `weekly_screening.ps1` 只在 live canonical 周把私有 root 传给 weekly pipeline；pipeline 只在 bundle 与 receipt 发布成功后调用 capture。sidecar 异常不影响已发布的 M6.7。

## 冻结内容

每条正式显示行以 `run_id`、`as_of`、候选摘要、账户快照摘要、股票、scope 与“最终操作 + 持仓处置”生成稳定 `decision_id`。capture 保存原始显示表和以下已发布事实：

- 新候选、既有持仓或纯组合层 scope；最终操作与持仓处置独立保存；禁止加仓、硬否决、advisory 降级及组合阻断分别留痕。
- 进场区间、止损、TP1/TP2、持仓减仓/清仓路径、建议股数、现金使用与已发布组合风险结果。
- 正式市场环境、风险族、覆盖度、stateful risk、ratchet；V14.3 字段只在官方 bundle 已提供时原样记录。
- `live_normalized` 初始为 `capture_pending`；`manual_actual` 只能在后续事件引用中记录，不能伪造成交。

若官方 bundle 没有个股报告但存在组合风险阻断，才允许 `portfolio_only`；该记录没有股票、进场、止损、止盈或建议股数。

## 私密与不可变边界

- 全字段写入 gitignored `state/a_short/operation_evidence_private/v1/weeks/<as_of>/capture.json`。repo 内 root 必须由 `git check-ignore` 证明已忽略；tracked 只包含代码、schema、测试与此设计。
- 同一来源重跑完全幂等；同一周既有 capture 与新内容不同会写入只含摘要哈希的私有 conflict 记录，并拒绝覆盖原始 capture。
- 本程序没有 outcome、账本、cohort、缓存读取或价格抓取接口。后续结算只能按 `decision_id` 另存引用，不能修改 capture；P2/P3/P5 ledger 与 verdict 也不复用。
- capture 不改选股、排名、M6.7、展示、receipt、账户状态或下单行为；所有 boundary 由私有 schema const-pin。
