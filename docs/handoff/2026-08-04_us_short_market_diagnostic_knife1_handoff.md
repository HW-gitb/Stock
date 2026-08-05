# US-short 26 周市场诊断轨 Knife1/Knife2 handoff

## 范围

Knife1 是不读账户、不联网、不调用 provider 的纯计算层。Knife2 在其上增加本地只读适配：校验既有 model-paper store 和本地四基准价格包，再投影为 schema-shaped 逐周记录；两刀都不改变选股、操作建议、sizing、model-paper NAV 或 Ship gate。

本轮已继续落地 Knife3 生命周期读取之后的 Knife4 聚合器：它只在第 26、52、78 等 canonical 边界生成当前 26 周固定区块 + since-inception 双视图，输出确定性的去标识化 JSON/Markdown；当前真实 model-paper 私有根尚未启动，所以没有真实成绩单或真实 10 万美元账户状态被创建。

## 已固化的计算契约

- 策略周收益由 prior NAV/NAV 构造；首周使用 `100000.000000`，`no_count` 周不补零。
- 复利、相对财富、raw excess、最大回撤、Information Ratio 和 Newey-West HAC t 已实现；HAC 的描述性 lag 为 `min(4, n - 1)`。
- 四个基准固定为 VTI/IWB/SPY/QQQ；少于 20 个 joint 周不能给 ahead/behind，price-only 或不可用数据保持降级状态。
- 26 周区块互不重叠；窗口触发是纯函数且按 `window_id` 幂等；epoch 不得静默混入，ruleset 按连续段输出。
- 计算摘要入口与触发入口共用 `window_for_week(end_week)` 的 canonical 锚点；第 5—30 周这类非边界窗口在计算路径也 fail-closed。
- 窗口身份、起止周和 `calendar_weeks` 统一由 `window_containing_week()` 产生；`window_for_week`、单周校验和 lifecycle register 不得各自重写窗口算术。
- 缺失换手率或未成交数输出 `null`；不以 0 代替缺失数据。
- 刀2 读取 `head_manifest.json`、指定结算周的 `settlement.json`、`portfolio_state.json`、`nav_snapshot.json`，并重新核对 settlement/state/NAV digest 绑定；不写 store、不推进 head。
- 刀2 的本地价格包固定 VTI/IWB/SPY/QQQ；SPY/QQQ 可来自 `grouped_market_window`，IWB/VTI 来自 `local_etf_price_packet`；每周保留 price date/source/SHA。
- 刀2 只输出 `price_return_diagnostic`；股息 sidecar 不在本刀消费，缺价格或缺前值输出 `unavailable`，不填零、不换基准。

## 代码和验证入口

- 计算器：`engine/us_short_market_diagnostic.py`
- 本地适配器：`engine/us_short_market_diagnostic_local_adapter.py`
- 合成 fixture / 反向测试 / schema 校验：`tests/test_us_short_market_diagnostic.py`
- 刀2 adapter / 私有 store digest / 本地价格包测试：`tests/test_us_short_market_diagnostic_local_adapter.py`
- 记录 schema：`schemas/us_short_market_diagnostic_weekly_record.schema.json`
- 摘要 schema：`schemas/us_short_market_diagnostic_summary.schema.json`
- 刀2 输入 schema：`schemas/us_short_market_diagnostic_local_price_packet.schema.json`
- 刀3 lifecycle persister：`engine/us_short_market_diagnostic_lifecycle.py`
- 刀3 lifecycle register schema：`schemas/us_short_market_diagnostic_lifecycle_register.schema.json`
- 刀3 计数、幂等、提醒和私有路径反向测试：`tests/test_us_short_market_diagnostic_lifecycle.py`
- 刀4 26 周聚合与发布：`engine/us_short_market_diagnostic_aggregator.py`
- 刀4 报告 schema：`schemas/us_short_market_diagnostic_report.schema.json`
- 刀4 聚合、幂等、半成品保护和 lifecycle 发布测试：`tests/test_us_short_market_diagnostic_aggregator.py`
- 设计入口：`docs/us_short_market_diagnostic_26w_design.md`

## 后续边界

刀3 已接周记录、26 周计数器和 v1.1 reminder 生命周期；Knife4 已在其上增加只读聚合与公开报告发布。聚合器只接受 lifecycle 已校验的 settled 记录；同一 `window_id` 重跑字节级幂等，JSON/Markdown 缺一不可，冲突或半成品拒绝覆盖。Knife5 已补上四 ETF total-return sidecar 的离线 schema、纯复算器和本地适配接线；Knife6 已补上 v1.1 归因的离线契约与纯计算器，真实 provider 获取和真实归因数据仍需单独授权；当前真实 model-paper 根尚未启动，因此不会出现真实 26 周成绩单。

## Knife5 新增实现入口

- sidecar schema：`schemas/us_short_market_diagnostic_etf_total_return_sidecar.schema.json`
- sidecar 纯校验/复算：`engine/us_short_market_diagnostic_total_return.py`
- 本地周记录接线：`engine/us_short_market_diagnostic_local_adapter.py`
- sidecar 回归：`tests/test_us_short_market_diagnostic_total_return.py`
- adapter 接线回归：`tests/test_us_short_market_diagnostic_local_adapter.py`

Knife5 只消费已捕获的 source-bound sidecar：完整覆盖周升级为 `total_return_evaluable`，缺失或错配只降级对应 ETF 周为 `price_return_diagnostic`，不补零、不改变策略收益、NAV、选股或操作建议。当前实现没有 provider/network/raw/account 写入。

补充状态：`_overall_status` 的全 `flat_diagnostic` 分支已经随当前 Knife5 提交落地；它保持 overall 六值契约，使用 `mixed_across_benchmarks` 加明确的 `all_four_benchmarks_show_flat_diagnostic_excess` 理由。风险登记中更早的“未修”文字属于历史记录，不是当前代码状态。

## Knife6 新增实现入口

- attribution input schema：`schemas/us_short_market_diagnostic_attribution_input.schema.json`
- attribution report schema：`schemas/us_short_market_diagnostic_attribution_report.schema.json`
- 纯校验/归因计算器：`engine/us_short_market_diagnostic_attribution.py`
- 刀6回归：`tests/test_us_short_market_diagnostic_attribution.py`
- schema 闭世界入口：`tests/schema/test_us_short_market_diagnostic_26w_schemas.py`

Knife6 是独立的 v1.1 解释层：它消费已绑定的 weekly record、Knife5 VTI total-return 观测、PIT 3M T-bill 观测和规则隐含目标暴露，计算 `g*`、匹配基准、`raw_excess`、`exposure_effect` 与 `active_system_effect`。当前修复让报告携带四个目标暴露约束并由 validator 重算 `g*` / binding constraints；input、report 与 builder 全接 `as_of_date`；巨整数、缺 PIT 日期、错误 map 和兄弟异常统一为 `AttributionError`。任一周缺少必要输入时，报告保持 `unavailable`，不补零、不用固定现金利率、不做不可复现历史回填。当前实现没有 provider/network/raw/account 写入，也不修改 v1 weekly/report、选股、操作建议、NAV 或 Ship gate；真实 model-paper、ETF sidecar 与 PIT 现金数据尚未启动。

Knife3 lifecycle 同步改为机器自动激活 v1.1：启用前按连续 `paper_evaluable=true` 周计数，false/no_count/missing 清零；第 4 个连续真周结算后生成确定的 `attribution_epoch` 并标记 active，从下一周生效；激活后状态保持 active。正式 weekly task 自动调用 Knife6、以及 Codex 完成通知 + `diagnostic_start_receipt` 的首周硬门留给 Knife7；当前设计工作基线不构成完成通知，26 周时钟未由本轮启动。
