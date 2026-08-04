# US-short 26 周市场表现诊断轨 — 刀0设计契约

> 状态：Knife 0 contract baseline  
> 性质：诊断轨；不改变 US-short 选股、操作建议、paper 账户或 Ship gate。  
> 本文件是仓库内执行契约；桌面执行总方案是 C:/Users/cnhea/Desktop/usshort-compare.md。

## 1. 目的

验证完整 US-short model-paper 账户相对固定美国市场基准的表现：

最终选股 → 最终操作建议 → 仓位与现金 → 跨周持仓 → 成本后 NAV

不使用 Top 15 等权收益代替完整账户收益。

本轨只能回答过去固定窗口的事实，不能预测未来，不能证明永久 alpha。

## 2. 固定边界

每个周记录和摘要都必须满足：

- diagnostic_only = true
- comparison_only = true
- counts_ship_gate = false
- changes_selection_or_action = false
- automatic_policy_switch = false
- broker_or_order_automation = false

诊断失败只能生成 unavailable 或数据降级状态，不得阻断正式 weekly report、选股、操作建议或 paper 结算。

诊断开关打开或关闭时，最终选股、action table、sizing、model-paper 状态和 NAV 必须相同；唯一允许变化的是已注册的 lifecycle reminder 区块。

## 3. 账户启动和本地输入

10 万美元是一次性播种的归一化 model-paper 本金，不是真实账户资金。刀0不播种账户、不创建 head_manifest、不启动26周时钟。

正式 model-paper 路径启动后，必须先产生：

- 私有 head_manifest；
- 当前 portfolio state；
- 首份真实已结算 settlement；
- 首份 nav_snapshot。

首份真实已结算 nav_snapshot 才是诊断第1个 calendar week。禁止 fixture、历史回填、事后重建和未来数据。

策略侧每周从私有 model-paper store 读取：

- head_manifest.json；
- weeks/<decision_date>/settlement.json；
- weeks/<decision_date>/portfolio_state.json；
- weeks/<decision_date>/nav_snapshot.json。

这些文件提供现金、持仓市值、NAV、累计盈亏、累计成本、订单结果、paper_evaluable、降级原因和来源摘要。诊断轨不读真实手工账户。

## 4. 价格收益先积累

账户正式启动后，v1允许先保存价格型诊断收益：

- 策略侧保存 diagnostic_nav 和价格型周收益；
- 基准股息不完整时保存 price_return_diagnostic；
- 策略侧 paper_evaluable = false 时，该周只能保存观察数字；
- strategy paper_evaluable = false 的周不计入 joint_evaluable_weeks，不得显示 ahead 或 behind；
- 策略侧 paper_evaluable = true 后，基准若只有价格收益，结果仍标记 data_degraded；
- 缺失股息不得填零、不得静默换基准、不得使用固定年化股息率。

## 5. 时间和窗口

使用固定、互不重叠的26个 canonical decision weeks：

- 第1—26周；
- 第27—52周；
- 第53—78周；
- 以后依次类推。

同时保存 since-inception 累计结果，但不能替代固定区块结果。

每周保存：

- calendar_week_index；
- window_id；
- decision_date；
- valuation_date；
- 每个基准的 price_date、price_source、price_packet_sha256 和数据质量；
- strategy_evaluable；
- joint_evaluable；
- total_return_evaluable；
- price_only；
- no_count。

第25周不生成26周摘要，第26周生成一次。重复运行必须幂等。no_count 周保留在窗口分母，不补收益、不延长窗口。

单个基准至少有20个 joint_evaluable_weeks 才允许 ahead_diagnostic 或 behind_diagnostic。

本轨26周时钟与 A1 24/36 divergence weeks、Ship gate 24/36个月检查完全分离。

## 6. 固定基准

四个基准在第一个计数周之前冻结：

- VTI：Ship gate 经济基准连续性；
- IWB：Russell 1000 可交易 ETF 代理；
- SPY：美国大盘和大型股敏感性；
- QQQ：科技成长风格敏感性。

IWB 是 ETF 代理，不是 Russell 1000 指数本身。禁止结果出来后挑选最有利基准。

## 7. 数据质量

严格总回报：

拆股调整价格 + 对应股息现金流

每个基准每周标记：

- total_return_evaluable；
- price_return_diagnostic；
- unavailable。

现有 Massive 公司行动探针只作为接口形状和受限样本证据复用。刀0不重复创建通用探针。

刀5另行完成四个 ETF 专用 coverage/reconciliation sidecar，至少核对：

- SPY、QQQ、IWB、VTI 股息历史；
- 分页；
- ex_dividend_date、cash_amount、split_adjusted_cash_amount；
- adjusted/unadjusted 价格一致性；
- 每周 total return 可重复计算。

刀5真实 provider 调用必须单独授权；raw 只进 gitignored 私有目录；tracked 摘要不得包含 secret、request URL、原始价格或原始事件行。

## 8. v1 指标

对策略和每个基准计算：

- 周收益；
- 26周累计收益；
- since-inception累计收益；
- 每周算术超额收益；
- 复利相对财富；
- 最大回撤；
- 超额收益 Information Ratio；
- HAC/Newey-West t 值；
- 平均现金比例和股票比例；
- 累计交易成本；
- 换手率；
- 未成交数量；
- no_count 数量；
- 数据覆盖率；
- ruleset fingerprint 分段。

HAC t 值只作描述，不作自动通过、失败或策略切换。

## 9. v1.1 提醒和时机

v1只回答总成绩；v1.1解释总成绩来自仓位、现金，还是主动系统效果。

v1.1在4—8个连续、真实、paper_evaluable = true 的可评估周后实施：

- 第4个可评估周：状态变为 ready_for_v1_1_implementation；
- 第4—8个可评估周：完成独立 schema、代码、测试和审查；
- 第8个可评估周仍未启用：状态为 overdue；
- v1.1不重置v1的26周时钟；
- v1.1开启新的 attribution_epoch，不回填不可复现的历史归因。

从第1个 calendar week 起，weekly report 的 lifecycle reminder 必须显示：

v1.1归因：待做。当前已积累 X 个可评估周，计划在4—8个可评估周后实施。作用：解释领先或落后主要来自仓位/现金，还是来自主动系统能力。当前v1只能告诉总成绩，暂时不能完整解释原因。

## 10. 状态

允许的整体状态：

- ahead_diagnostic；
- behind_diagnostic；
- mixed_across_benchmarks；
- data_insufficient；
- data_degraded；
- unavailable。

少于20个 joint_evaluable_weeks 时只能 data_insufficient。缺失或价格-only 数据必须保留降级原因。

v1.1 reminder 状态：

- pending；
- ready_for_v1_1_implementation；
- overdue；
- active。

## 11. 规则版本

每周保存 strategy_ruleset_fingerprint。26周窗口不因主规则升级自动重置，但报告必须展示窗口内版本和分段周数。

诊断 preset、基准集合、收益计算方法、窗口计数规则或数据质量口径改变时，开启新的 diagnostic_epoch。

## 12. 存储

私有逐周记录：

    state/us_short/market_diagnostic_private/

去标识化摘要：

    research/results/us_short/market_diagnostic_26w/

## 12.1 Machine-bound v1 summary and status contract

The v1 summary schema must carry the metrics promised in section 8. The following block is the canonical field list used by the schema test; values are null when the metric is not calculable, never silently replaced with zero.

```json
{
  "v1_summary_strategy_metric_fields": [
    "since_inception_return",
    "cash_ratio",
    "equity_ratio",
    "turnover",
    "unfilled_order_count",
    "data_coverage"
  ],
  "v1_summary_benchmark_metric_fields": [
    "information_ratio",
    "hac_t",
    "data_coverage"
  ],
  "status_priority": [
    "unavailable",
    "data_insufficient",
    "data_degraded",
    "mixed_across_benchmarks",
    "ahead_diagnostic",
    "behind_diagnostic"
  ]
}
```

The weekly strategy status and the summary strategy status use the same three values: `evaluable`, `diagnostic_data_degraded`, and `not_evaluable`. The summary `overall_status` uses the six-value priority list above. `mixed_ruleset_window` is true when more than one strategy ruleset fingerprint appears in the 26-week window and no single fingerprint has at least 20 strategy-evaluable weeks; it blocks a single-ruleset performance claim.

Each benchmark summary may additionally use `flat_diagnostic` when its own joint compounded excess is exactly zero. `mixed_across_benchmarks` remains an overall cross-benchmark status and is never used to label one benchmark's individual tie. A flat benchmark does not make the overall result ahead or behind; the overall six-value status contract stays unchanged.

## 12.2 Knife 1 calculation contract

刀1的计算器是纯函数：调用方传入已经准备好的周记录，计算器不读取账户文件、不联网、不调用 provider，也不改变选股、操作建议、仓位或 NAV。

- 策略周收益优先由 `prior_nav` 和 `nav` 构造；首周使用冻结的 `100000.000000` 归一化本金。记录中若同时有 `weekly_return`，必须与构造结果一致；`no_count` 周不补零；
- 复利财富从 1 开始，累计收益不年化；`raw_excess` 是 joint 周内策略复利财富减基准复利财富，`relative_wealth` 是 `(1 + 策略累计收益) / (1 + 基准累计收益) - 1`；
- Information Ratio 使用周算术超额收益的样本标准差，不年化；HAC 使用 Newey-West、`lag = min(4, n - 1)`，只作描述；
- 任一基准少于 20 个 `joint_evaluable` 周时不得给 `ahead_diagnostic` 或 `behind_diagnostic`；price-only 或缺失数据保留 `data_degraded` / `unavailable`，不把缺失改成零，也不替换基准；
- 26 周始终是分母；窗口为 `1—26`、`27—52`、`53—78` 等互不重叠区块。重复触发同一个 `window_id` 返回幂等的“不再触发”；
- 每周记录可带 `turnover` 和 `unfilled_order_count`。缺失时摘要输出 `null`，而不是伪造 0；
- epoch 混入同一摘要窗口会 fail-closed；ruleset 按连续区段输出，并在单一 ruleset 不足 20 个可评估周时设置 `mixed_ruleset_window`。

私有路径必须受 gitignore 和 fail-closed 路径保护。公开摘要不得包含 ticker、逐笔交易、持仓明细、账户余额、原始价格或可还原个人账户的信息。

## 12.3 Knife 2 local adapter contract

Knife 2 的本地适配器是 `engine/us_short_market_diagnostic_local_adapter.py`，输入契约是 `schemas/us_short_market_diagnostic_local_price_packet.schema.json`。它只读，不写入 model-paper store，也不推进 `head_manifest`。

- 策略侧先通过既有 model-paper store 的 `head_manifest` 校验，再读取指定结算周的 `settlement.json`、`portfolio_state.json` 和 `nav_snapshot.json`；三份文件必须互相绑定，最近结算还必须与 head 指针一致。
- 价格包固定包含 VTI/IWB/SPY/QQQ。`grouped_market_window` 可继续提供 SPY/QQQ，`local_etf_price_packet` 提供 IWB/VTI；适配器不根据结果替换或挑选基准。
- 价格包的 `settlement_decision_date` 是被读取的 `weeks/<decision_date>/` 目录日期；输出记录的 `decision_date` 是结算完成后可观察该周的报告决策日期，`valuation_date` 必须与 NAV 和价格日期一致且不晚于输出决策日期。
- 只用拆股调整收盘价构造价格型周收益。股息 sidecar 即使存在也不在本刀消费，输出固定为 `price_return_diagnostic`、`dividend_sidecar_sha256 = null` 和明确的数据质量原因；缺价格或缺前值则输出 `unavailable`，绝不填零。
- 每周输出保留价格日期、来源、价格包 SHA 和源 digest，随后由刀3负责不可变周记录、26 周计数器和 reminder 接线。适配器不调用 provider、不创建 10 万美元账户、不读取真实手工账户、不改变选股、操作建议、仓位、NAV 或 Ship gate。

## 12.4 Knife 3：不可变逐周记录、26 周计数器和 v1.1 reminder

刀3的实现入口是 `engine/us_short_market_diagnostic_lifecycle.py`，窗口身份、起止周和 `calendar_weeks` 统一由计算引擎的 `window_containing_week()` 生成；私有输出根是：

    state/us_short/market_diagnostic_private/

每次只能接收已经由刀2从 settled model-paper 周构造好的 weekly record。第一条必须是 `calendar_week_index = 1`；之后只能按 `+1` 追加，不能跳周、回填或把不同 `diagnostic_epoch` 静默混在一起。重复提交完全相同的周返回幂等结果；修改同一周的任何内容则 fail-closed。

逐周文件写入 `weeks/<decision_date>/weekly_record.json`，首次写入后不可变；`lifecycle_register.json` 只保存每周文件的相对路径、SHA、周号、日期和 `strategy_evaluable` 标记，以及由这些文件重新计算出的累计数。寄存器不保存 ticker、持仓、订单或账户金额。寄存器缺失、周文件孤儿、SHA 不一致或累计数不是由逐周文件推导出来时拒绝继续。

这里的“可评估周”定义为 weekly record 中 `strategy.strategy_evaluable = true` 的周；`paper_evaluable = false` 或 `no_count = true` 不进入 v1.1 计数，但仍保留为日历周记录。第4个可评估周状态为 `ready_for_v1_1_implementation`，第8个及以后仍未启用 v1.1 时为 `overdue`。每周生成的 `us_short_market_diagnostic_v1_1` reminder block 注册到周报第12节，显示日历周数、可评估周数、当前状态和大白话作用说明。刀3不实现 v1.1 归因本身，也不生成26周摘要；摘要留给刀4，归因留给刀6。

刀3的写入只写诊断轨私有目录；`provider_fetch=false`、`account_write=false`、`changes_selection_or_action=false`、`automatic_policy_switch=false`、`counts_ship_gate=false`。当前真实 model-paper 私有根尚未启动时，不创建 head、不生成虚假的第1周；刀3只通过临时夹具验证该接线。

## 12.5 Knife 4：26 周聚合器与公开报告

Knife 4 的实现入口是 `engine/us_short_market_diagnostic_aggregator.py`，输入只来自 Knife 3 已校验的私有 settled weekly records；它不读取 provider、真实账户、持仓明细或订单，也不创建 10 万美元 model-paper 账户。

- 只有当最后一条记录正好落在 `26`、`52`、`78` 等 canonical 边界时才生成报告；不足 26 周、缺周、断档或窗口不完整时返回“尚未到期”或 fail-closed，不凑数、不补零；
- 报告同时保留当前 26 周固定区块和从第 1 周到当前的 since-inception 视图。固定区块继续复用 Knife 1 的四基准、状态、数据质量、成本后 NAV、回撤、现金/权益比例、turnover、joint 周数、IR 和 HAC 等既有字段；本刀不改 Knife 0 已冻结 schema，也不新增“周收益波动”字段；
- 四个基准始终是 `VTI`、`IWB`、`SPY`、`QQQ`，不按结果替换。Knife 5 接入 ETF 股息 sidecar 之前，缺股息的周仍明确标成 `price_return_diagnostic` / `data_degraded`，不能冒充 total return；
- `ruleset_segments` 同时记录固定区块和 since-inception 的 epoch/ruleset 连续分段，防止跨规则版本把成绩混成一个结论；
- 去标识化报告输出到 `research/results/us_short/market_diagnostic_26w/`，每个窗口一对 `<window_id>.json` 和 `<window_id>.md`。JSON 是机器接口，Markdown 是人读摘要；不写逐周原始记录、持仓、交易、原始价格或可还原个人账户的信息；
- 写入采用确定性字节序列：同一窗口重复运行返回幂等；只存在 JSON 或 Markdown 的半成品、或内容冲突时拒绝覆盖，避免产生两份不同成绩单；
- 报告只是比较诊断，不改变选股、最终操作建议、仓位、NAV 或 Ship gate。当前真实 model-paper 私有根尚未启动时，不会生成实际第 26 周成绩单，测试只用临时夹具验证逻辑。

## 13. Knife 0 验收

刀0完成必须证明：

1. policy preset、weekly record schema、summary schema 均为合法 Draft 7；
2. schema 根对象和嵌套对象均 closed-world；
3. 四个基准、26周、20周阈值和状态词被固定；
4. 10万美元账户启动条件被固定，但刀0未播种账户；
5. 策略 paper_evaluable 与基准 return quality 被分开；
6. 价格收益降级不伪装成 total return；
7. no_count、幂等、未来日期和错误时钟边界进入 schema/测试契约；
8. v1.1 的4—8周时机、每周提醒和 overdue 规则被固定；
9. 刀0不联网、不调用 provider、不写 state 运行态、不改变正式选股或操作建议。

## 14. Knife 4 验收

Knife 4 完成必须证明：

1. 第 26 周之前不发布报告，第 26、52、78 周边界可按同一规则生成固定区块；
2. 固定 26 周与 since-inception 两套视图分别通过 schema，四个基准和 ruleset 分段完整；
3. 公开 JSON/Markdown 不包含逐周记录，且不改变诊断边界；
4. 同一窗口重复运行字节级幂等，半成品或冲突内容 fail-closed；
5. 从 Knife 3 私有 lifecycle 读取时只消费已 settled 记录；没有真实私有根时不创建真实输出；
6. 固定 Python 下聚合器、诊断引擎、lifecycle、schema 和文档治理测试通过。
