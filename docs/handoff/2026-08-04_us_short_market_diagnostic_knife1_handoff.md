# US-short 26 周市场诊断轨 Knife1 handoff

## 范围

Knife1 是不读账户、不联网、不调用 provider 的纯计算层。输入是 schema-shaped 的逐周记录，输出是 26 周去标识化摘要；它不改变选股、操作建议、sizing、model-paper NAV 或 Ship gate。

## 已固化的计算契约

- 策略周收益由 prior NAV/NAV 构造；首周使用 `100000.000000`，`no_count` 周不补零。
- 复利、相对财富、raw excess、最大回撤、Information Ratio 和 Newey-West HAC t 已实现；HAC 的描述性 lag 为 `min(4, n - 1)`。
- 四个基准固定为 VTI/IWB/SPY/QQQ；少于 20 个 joint 周不能给 ahead/behind，price-only 或不可用数据保持降级状态。
- 26 周区块互不重叠；窗口触发是纯函数且按 `window_id` 幂等；epoch 不得静默混入，ruleset 按连续段输出。
- 计算摘要入口与触发入口共用 `window_for_week(end_week)` 的 canonical 锚点；第 5—30 周这类非边界窗口在计算路径也 fail-closed。
- 缺失换手率或未成交数输出 `null`；不以 0 代替缺失数据。

## 代码和验证入口

- 计算器：`engine/us_short_market_diagnostic.py`
- 合成 fixture / 反向测试 / schema 校验：`tests/test_us_short_market_diagnostic.py`
- 记录 schema：`schemas/us_short_market_diagnostic_weekly_record.schema.json`
- 摘要 schema：`schemas/us_short_market_diagnostic_summary.schema.json`
- 设计入口：`docs/us_short_market_diagnostic_26w_design.md`

## 后续边界

刀2才接入既有本地 model-paper NAV 与四个 ETF 的本地价格材料；刀3才接周记录和 v1.1 reminder 生命周期。ETF 总回报 sidecar、provider 调用和 v1.1 归因仍在各自后续刀，不能由 Knife1 计算器自行补齐。
